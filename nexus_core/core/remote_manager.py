from __future__ import annotations

import abc
import asyncio
import importlib
import json
import threading
import time
import urllib.parse
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union, cast

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import ManagerInitializationError, ManagerShutdownError


class ServiceProtocol(Enum):
    """Supported service protocols."""
    
    HTTP = "http"
    HTTPS = "https"
    GRPC = "grpc"
    SOAP = "soap"
    CUSTOM = "custom"


class RemoteService:
    """Base class for remote services."""
    
    def __init__(
        self,
        name: str,
        protocol: ServiceProtocol,
        base_url: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        retry_max_delay: float = 60.0,
        headers: Optional[Dict[str, str]] = None,
        auth: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        logger: Any = None,
    ) -> None:
        """Initialize a remote service.
        
        Args:
            name: Unique name of the service.
            protocol: The protocol used to communicate with the service.
            base_url: Base URL of the service.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts for failed requests.
            retry_delay: Initial delay between retries in seconds.
            retry_max_delay: Maximum delay between retries in seconds.
            headers: Default headers to include in requests.
            auth: Authentication configuration.
            config: Additional service-specific configuration.
            logger: Logger instance for the service.
        """
        self.name = name
        self.protocol = protocol
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.retry_max_delay = retry_max_delay
        self.headers = headers or {}
        self.auth = auth or {}
        self.config = config or {}
        self._logger = logger
        
        # Client instance (initialized on demand)
        self._client = None
        
        # Service status
        self._healthy = False
        self._last_check_time = 0
        self._avg_response_time = 0
        self._request_count = 0
        self._error_count = 0
        
        # Service lock
        self._lock = threading.RLock()
    
    def get_client(self) -> Any:
        """Get the client instance for this service.
        
        Returns:
            Any: The client instance.
        """
        if self._client is None:
            self._initialize_client()
        
        return self._client
    
    def _initialize_client(self) -> None:
        """Initialize the client instance for this service."""
        pass  # Implemented by subclasses
    
    def check_health(self) -> bool:
        """Check if the service is healthy.
        
        Returns:
            bool: True if the service is healthy, False otherwise.
        """
        # Default implementation just returns current health status
        return self._healthy
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the service.
        
        Returns:
            Dict[str, Any]: Status information.
        """
        with self._lock:
            return {
                "name": self.name,
                "protocol": self.protocol.value,
                "base_url": self.base_url,
                "healthy": self._healthy,
                "avg_response_time": self._avg_response_time,
                "request_count": self._request_count,
                "error_count": self._error_count,
                "error_rate": self._error_count / self._request_count if self._request_count > 0 else 0,
                "last_check_time": self._last_check_time,
            }
    
    def _update_metrics(
        self, 
        response_time: Optional[float] = None, 
        success: bool = True
    ) -> None:
        """Update service metrics.
        
        Args:
            response_time: Response time in seconds.
            success: Whether the request was successful.
        """
        with self._lock:
            self._request_count += 1
            
            if not success:
                self._error_count += 1
            
            if response_time is not None:
                # Update average response time
                if self._avg_response_time == 0:
                    self._avg_response_time = response_time
                else:
                    # Weighted average (more weight to recent responses)
                    self._avg_response_time = (
                        0.7 * self._avg_response_time + 0.3 * response_time
                    )
            
            # Update last check time
            self._last_check_time = time.time()


class HTTPService(RemoteService):
    """HTTP/HTTPS remote service implementation."""
    
    def __init__(
        self,
        name: str,
        base_url: str,
        protocol: ServiceProtocol = ServiceProtocol.HTTPS,
        **kwargs: Any,
    ) -> None:
        """Initialize an HTTP service.
        
        Args:
            name: Unique name of the service.
            base_url: Base URL of the service.
            protocol: The protocol (HTTP or HTTPS).
            **kwargs: Additional arguments passed to RemoteService.
        """
        super().__init__(name, protocol, base_url, **kwargs)
        
        # Health check endpoint
        self.health_check_path = kwargs.get("health_check_path", "/health")
        
        # HTTP client options
        self.verify_ssl = kwargs.get("verify_ssl", True)
        self.follow_redirects = kwargs.get("follow_redirects", True)
    
    def _initialize_client(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=self.follow_redirects,
            verify=self.verify_ssl,
            headers=self.headers,
        )
        
        # Set up authentication if provided
        if self.auth:
            auth_type = self.auth.get("type", "").lower()
            
            if auth_type == "basic":
                self._client.auth = (
                    self.auth.get("username", ""),
                    self.auth.get("password", ""),
                )
            
            elif auth_type == "bearer":
                # Add Authorization header with bearer token
                token = self.auth.get("token", "")
                self._client.headers["Authorization"] = f"Bearer {token}"
    
    def check_health(self) -> bool:
        """Check if the service is healthy.
        
        Returns:
            bool: True if the service is healthy, False otherwise.
        """
        try:
            # Get client
            client = self.get_client()
            
            # Make a request to the health check endpoint
            start_time = time.time()
            response = client.get(self.health_check_path)
            response_time = time.time() - start_time
            
            # Update metrics
            self._update_metrics(response_time, response.is_success)
            
            # Check if the response is successful
            self._healthy = response.is_success
            
            if not self._healthy and self._logger:
                self._logger.warning(
                    f"Health check failed for {self.name}",
                    extra={
                        "service": self.name,
                        "status_code": response.status_code,
                        "response": response.text[:1000],  # Limit response size in logs
                    },
                )
            
            return self._healthy
        
        except Exception as e:
            # Update metrics
            self._update_metrics(None, False)
            
            # Log the error
            if self._logger:
                self._logger.error(
                    f"Health check error for {self.name}: {str(e)}",
                    extra={"service": self.name, "error": str(e)},
                )
            
            self._healthy = False
            return False
    
    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Make an HTTP request to the service.
        
        Args:
            method: HTTP method (GET, POST, etc.).
            path: Path relative to the base URL.
            params: Query parameters.
            data: Request body data.
            json_data: JSON request body.
            headers: Additional headers for this request.
            timeout: Request timeout in seconds (overrides default).
            
        Returns:
            httpx.Response: The HTTP response.
            
        Raises:
            httpx.HTTPError: If the request fails.
        """
        # Get client
        client = self.get_client()
        
        # Prepare request kwargs
        kwargs = {}
        if params is not None:
            kwargs["params"] = params
        if data is not None:
            kwargs["data"] = data
        if json_data is not None:
            kwargs["json"] = json_data
        if headers is not None:
            kwargs["headers"] = headers
        if timeout is not None:
            kwargs["timeout"] = timeout
        
        # Make the request
        start_time = time.time()
        try:
            response = client.request(method, path, **kwargs)
            response_time = time.time() - start_time
            
            # Update metrics
            self._update_metrics(response_time, response.is_success)
            
            return response
        
        except Exception as e:
            # Update metrics
            self._update_metrics(None, False)
            
            # Log the error
            if self._logger:
                self._logger.error(
                    f"Request error for {self.name}: {str(e)}",
                    extra={
                        "service": self.name,
                        "method": method,
                        "path": path,
                        "error": str(e),
                    },
                )
            
            raise
    
    def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a GET request to the service.
        
        Args:
            path: Path relative to the base URL.
            params: Query parameters.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return self.request("GET", path, params=params, **kwargs)
    
    def post(
        self,
        path: str,
        data: Optional[Any] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a POST request to the service.
        
        Args:
            path: Path relative to the base URL.
            data: Request body data.
            json_data: JSON request body.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return self.request("POST", path, data=data, json_data=json_data, **kwargs)
    
    def put(
        self,
        path: str,
        data: Optional[Any] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a PUT request to the service.
        
        Args:
            path: Path relative to the base URL.
            data: Request body data.
            json_data: JSON request body.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return self.request("PUT", path, data=data, json_data=json_data, **kwargs)
    
    def delete(
        self,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a DELETE request to the service.
        
        Args:
            path: Path relative to the base URL.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return self.request("DELETE", path, **kwargs)
    
    def patch(
        self,
        path: str,
        data: Optional[Any] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a PATCH request to the service.
        
        Args:
            path: Path relative to the base URL.
            data: Request body data.
            json_data: JSON request body.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return self.request("PATCH", path, data=data, json_data=json_data, **kwargs)
    
    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None


class AsyncHTTPService(RemoteService):
    """Asynchronous HTTP/HTTPS remote service implementation."""
    
    def __init__(
        self,
        name: str,
        base_url: str,
        protocol: ServiceProtocol = ServiceProtocol.HTTPS,
        **kwargs: Any,
    ) -> None:
        """Initialize an async HTTP service.
        
        Args:
            name: Unique name of the service.
            base_url: Base URL of the service.
            protocol: The protocol (HTTP or HTTPS).
            **kwargs: Additional arguments passed to RemoteService.
        """
        super().__init__(name, protocol, base_url, **kwargs)
        
        # Health check endpoint
        self.health_check_path = kwargs.get("health_check_path", "/health")
        
        # HTTP client options
        self.verify_ssl = kwargs.get("verify_ssl", True)
        self.follow_redirects = kwargs.get("follow_redirects", True)
    
    def _initialize_client(self) -> None:
        """Initialize the async HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            follow_redirects=self.follow_redirects,
            verify=self.verify_ssl,
            headers=self.headers,
        )
        
        # Set up authentication if provided
        if self.auth:
            auth_type = self.auth.get("type", "").lower()
            
            if auth_type == "basic":
                self._client.auth = (
                    self.auth.get("username", ""),
                    self.auth.get("password", ""),
                )
            
            elif auth_type == "bearer":
                # Add Authorization header with bearer token
                token = self.auth.get("token", "")
                self._client.headers["Authorization"] = f"Bearer {token}"
    
    async def check_health_async(self) -> bool:
        """Check if the service is healthy asynchronously.
        
        Returns:
            bool: True if the service is healthy, False otherwise.
        """
        try:
            # Get client
            client = self.get_client()
            
            # Make a request to the health check endpoint
            start_time = time.time()
            response = await client.get(self.health_check_path)
            response_time = time.time() - start_time
            
            # Update metrics
            self._update_metrics(response_time, response.is_success)
            
            # Check if the response is successful
            self._healthy = response.is_success
            
            if not self._healthy and self._logger:
                self._logger.warning(
                    f"Health check failed for {self.name}",
                    extra={
                        "service": self.name,
                        "status_code": response.status_code,
                        "response": response.text[:1000],  # Limit response size in logs
                    },
                )
            
            return self._healthy
        
        except Exception as e:
            # Update metrics
            self._update_metrics(None, False)
            
            # Log the error
            if self._logger:
                self._logger.error(
                    f"Health check error for {self.name}: {str(e)}",
                    extra={"service": self.name, "error": str(e)},
                )
            
            self._healthy = False
            return False
    
    def check_health(self) -> bool:
        """Check if the service is healthy.
        
        Returns:
            bool: True if the service is healthy, False otherwise.
        """
        # Run the async health check in a new event loop
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.check_health_async())
        finally:
            loop.close()
    
    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Any] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> httpx.Response:
        """Make an HTTP request to the service asynchronously.
        
        Args:
            method: HTTP method (GET, POST, etc.).
            path: Path relative to the base URL.
            params: Query parameters.
            data: Request body data.
            json_data: JSON request body.
            headers: Additional headers for this request.
            timeout: Request timeout in seconds (overrides default).
            
        Returns:
            httpx.Response: The HTTP response.
            
        Raises:
            httpx.HTTPError: If the request fails.
        """
        # Get client
        client = self.get_client()
        
        # Prepare request kwargs
        kwargs = {}
        if params is not None:
            kwargs["params"] = params
        if data is not None:
            kwargs["data"] = data
        if json_data is not None:
            kwargs["json"] = json_data
        if headers is not None:
            kwargs["headers"] = headers
        if timeout is not None:
            kwargs["timeout"] = timeout
        
        # Make the request
        start_time = time.time()
        try:
            response = await client.request(method, path, **kwargs)
            response_time = time.time() - start_time
            
            # Update metrics
            self._update_metrics(response_time, response.is_success)
            
            return response
        
        except Exception as e:
            # Update metrics
            self._update_metrics(None, False)
            
            # Log the error
            if self._logger:
                self._logger.error(
                    f"Request error for {self.name}: {str(e)}",
                    extra={
                        "service": self.name,
                        "method": method,
                        "path": path,
                        "error": str(e),
                    },
                )
            
            raise
    
    async def get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a GET request to the service asynchronously.
        
        Args:
            path: Path relative to the base URL.
            params: Query parameters.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return await self.request("GET", path, params=params, **kwargs)
    
    async def post(
        self,
        path: str,
        data: Optional[Any] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a POST request to the service asynchronously.
        
        Args:
            path: Path relative to the base URL.
            data: Request body data.
            json_data: JSON request body.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return await self.request("POST", path, data=data, json_data=json_data, **kwargs)
    
    async def put(
        self,
        path: str,
        data: Optional[Any] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a PUT request to the service asynchronously.
        
        Args:
            path: Path relative to the base URL.
            data: Request body data.
            json_data: JSON request body.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return await self.request("PUT", path, data=data, json_data=json_data, **kwargs)
    
    async def delete(
        self,
        path: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a DELETE request to the service asynchronously.
        
        Args:
            path: Path relative to the base URL.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return await self.request("DELETE", path, **kwargs)
    
    async def patch(
        self,
        path: str,
        data: Optional[Any] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Make a PATCH request to the service asynchronously.
        
        Args:
            path: Path relative to the base URL.
            data: Request body data.
            json_data: JSON request body.
            **kwargs: Additional arguments passed to request().
            
        Returns:
            httpx.Response: The HTTP response.
        """
        return await self.request("PATCH", path, data=data, json_data=json_data, **kwargs)
    
    async def close_async(self) -> None:
        """Close the async HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
    
    def close(self) -> None:
        """Close the async HTTP client."""
        if self._client is not None:
            # Run the async close in a new event loop
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self.close_async())
            finally:
                loop.close()


class RemoteServicesManager(NexusManager):
    """Manages integration with external or remote services.
    
    The Remote Services Manager is responsible for handling interactions with
    external services and APIs. It provides a unified interface for making
    requests to remote services, handles authentication, retries, and circuit
    breaking, and monitors the health of connected services.
    """
    
    def __init__(
        self,
        config_manager: Any,
        logger_manager: Any,
        event_bus_manager: Any,
        thread_manager: Any,
    ) -> None:
        """Initialize the Remote Services Manager.
        
        Args:
            config_manager: The Configuration Manager for service settings.
            logger_manager: The Logging Manager for logging.
            event_bus_manager: The Event Bus Manager for service events.
            thread_manager: The Thread Manager for service-related background tasks.
        """
        super().__init__(name="RemoteServicesManager")
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger("remote_manager")
        self._event_bus = event_bus_manager
        self._thread_manager = thread_manager
        
        # Remote services
        self._services: Dict[str, RemoteService] = {}
        
        # Service registry lock
        self._services_lock = threading.RLock()
        
        # Health check task
        self._health_check_interval = 60.0  # seconds
        self._health_check_task_id = None
    
    def initialize(self) -> None:
        """Initialize the Remote Services Manager.
        
        Sets up remote services based on configuration.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Get remote services configuration
            remote_config = self._config_manager.get("remote_services", {})
            services_config = remote_config.get("services", {})
            self._health_check_interval = remote_config.get(
                "health_check_interval", 60.0
            )
            
            # Register configured services
            for service_name, service_config in services_config.items():
                if not service_config.get("enabled", True):
                    continue
                
                try:
                    self._register_service_from_config(service_name, service_config)
                except Exception as e:
                    self._logger.error(
                        f"Failed to register service {service_name}: {str(e)}",
                        extra={"service": service_name, "error": str(e)},
                    )
            
            # Subscribe to service-related events
            self._event_bus.subscribe(
                event_type="remote_service/register",
                callback=self._on_service_register_event,
                subscriber_id="remote_manager"
            )
            
            self._event_bus.subscribe(
                event_type="remote_service/unregister",
                callback=self._on_service_unregister_event,
                subscriber_id="remote_manager"
            )
            
            # Register for config changes
            self._config_manager.register_listener(
                "remote_services", self._on_config_changed
            )
            
            # Schedule health check task
            self._schedule_health_checks()
            
            self._initialized = True
            self._healthy = True
            
            self._logger.info(
                f"Remote Services Manager initialized with {len(self._services)} services"
            )
        
        except Exception as e:
            self._logger.error(f"Failed to initialize Remote Services Manager: {str(e)}")
            raise ManagerInitializationError(
                f"Failed to initialize RemoteServicesManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def _register_service_from_config(
        self,
        service_name: str,
        service_config: Dict[str, Any],
    ) -> None:
        """Register a service from configuration.
        
        Args:
            service_name: Name of the service.
            service_config: Service configuration dictionary.
            
        Raises:
            ValueError: If the service configuration is invalid.
        """
        # Get service type and protocol
        service_type = service_config.get("type", "http").lower()
        protocol_str = service_config.get("protocol", "https").lower()
        
        try:
            protocol = ServiceProtocol(protocol_str)
        except ValueError:
            self._logger.warning(
                f"Invalid protocol '{protocol_str}' for service {service_name}, defaulting to HTTPS"
            )
            protocol = ServiceProtocol.HTTPS
        
        # Get service URL
        base_url = service_config.get("base_url")
        if not base_url:
            raise ValueError(f"No base URL provided for service {service_name}")
        
        # Create service
        if service_type == "http":
            service = HTTPService(
                name=service_name,
                base_url=base_url,
                protocol=protocol,
                timeout=service_config.get("timeout", 30.0),
                max_retries=service_config.get("max_retries", 3),
                retry_delay=service_config.get("retry_delay", 1.0),
                retry_max_delay=service_config.get("retry_max_delay", 60.0),
                headers=service_config.get("headers"),
                auth=service_config.get("auth"),
                config=service_config,
                logger=self._logger,
                health_check_path=service_config.get("health_check_path", "/health"),
                verify_ssl=service_config.get("verify_ssl", True),
                follow_redirects=service_config.get("follow_redirects", True),
            )
        
        elif service_type == "async_http":
            service = AsyncHTTPService(
                name=service_name,
                base_url=base_url,
                protocol=protocol,
                timeout=service_config.get("timeout", 30.0),
                max_retries=service_config.get("max_retries", 3),
                retry_delay=service_config.get("retry_delay", 1.0),
                retry_max_delay=service_config.get("retry_max_delay", 60.0),
                headers=service_config.get("headers"),
                auth=service_config.get("auth"),
                config=service_config,
                logger=self._logger,
                health_check_path=service_config.get("health_check_path", "/health"),
                verify_ssl=service_config.get("verify_ssl", True),
                follow_redirects=service_config.get("follow_redirects", True),
            )
        
        else:
            raise ValueError(f"Unsupported service type: {service_type}")
        
        # Register the service
        self.register_service(service)
    
    def register_service(self, service: RemoteService) -> None:
        """Register a remote service.
        
        Args:
            service: The service to register.
            
        Raises:
            ValueError: If a service with the same name is already registered.
        """
        if not self._initialized:
            raise ValueError("Remote Services Manager not initialized")
        
        with self._services_lock:
            if service.name in self._services:
                raise ValueError(f"Service '{service.name}' is already registered")
            
            self._services[service.name] = service
        
        self._logger.info(
            f"Registered service '{service.name}' with URL {service.base_url}"
        )
        
        # Publish service registered event
        self._event_bus.publish(
            event_type="remote_service/registered",
            source="remote_manager",
            payload={
                "service_name": service.name,
                "protocol": service.protocol.value,
                "base_url": service.base_url,
            },
        )
    
    def unregister_service(self, service_name: str) -> bool:
        """Unregister a remote service.
        
        Args:
            service_name: Name of the service to unregister.
            
        Returns:
            bool: True if the service was unregistered, False otherwise.
        """
        if not self._initialized:
            return False
        
        with self._services_lock:
            if service_name not in self._services:
                return False
            
            service = self._services.pop(service_name)
            
            # Close service connections
            if hasattr(service, "close") and callable(service.close):
                service.close()
        
        self._logger.info(f"Unregistered service '{service_name}'")
        
        # Publish service unregistered event
        self._event_bus.publish(
            event_type="remote_service/unregistered",
            source="remote_manager",
            payload={"service_name": service_name},
        )
        
        return True
    
    def get_service(self, service_name: str) -> Optional[RemoteService]:
        """Get a registered service by name.
        
        Args:
            service_name: Name of the service.
            
        Returns:
            Optional[RemoteService]: The service, or None if not found.
        """
        if not self._initialized:
            return None
        
        with self._services_lock:
            return self._services.get(service_name)
    
    def get_http_service(self, service_name: str) -> Optional[HTTPService]:
        """Get a registered HTTP service by name.
        
        Args:
            service_name: Name of the service.
            
        Returns:
            Optional[HTTPService]: The HTTP service, or None if not found or not an HTTP service.
        """
        service = self.get_service(service_name)
        
        if service is None or not isinstance(service, HTTPService):
            return None
        
        return service
    
    def get_async_http_service(self, service_name: str) -> Optional[AsyncHTTPService]:
        """Get a registered async HTTP service by name.
        
        Args:
            service_name: Name of the service.
            
        Returns:
            Optional[AsyncHTTPService]: The async HTTP service, or None if not found or not an async HTTP service.
        """
        service = self.get_service(service_name)
        
        if service is None or not isinstance(service, AsyncHTTPService):
            return None
        
        return service
    
    def get_all_services(self) -> Dict[str, RemoteService]:
        """Get all registered services.
        
        Returns:
            Dict[str, RemoteService]: Dictionary of service name to service.
        """
        if not self._initialized:
            return {}
        
        with self._services_lock:
            return dict(self._services)
    
    def check_service_health(self, service_name: str) -> bool:
        """Check the health of a specific service.
        
        Args:
            service_name: Name of the service to check.
            
        Returns:
            bool: True if the service is healthy, False otherwise.
        """
        if not self._initialized:
            return False
        
        service = self.get_service(service_name)
        
        if service is None:
            return False
        
        try:
            return service.check_health()
        
        except Exception as e:
            self._logger.error(
                f"Error checking health of service '{service_name}': {str(e)}",
                extra={"service": service_name, "error": str(e)},
            )
            
            return False
    
    def check_all_services_health(self) -> Dict[str, bool]:
        """Check the health of all registered services.
        
        Returns:
            Dict[str, bool]: Dictionary of service name to health status.
        """
        if not self._initialized:
            return {}
        
        result = {}
        
        for service_name in self.get_all_services():
            result[service_name] = self.check_service_health(service_name)
        
        return result
    
    def _health_check_task(self) -> None:
        """Periodic task to check the health of all services."""
        if not self._initialized:
            return
        
        try:
            # Check health of all services
            health_statuses = self.check_all_services_health()
            
            # Count healthy and unhealthy services
            healthy_count = sum(1 for status in health_statuses.values() if status)
            unhealthy_count = len(health_statuses) - healthy_count
            
            # Log health check results
            self._logger.debug(
                f"Health check completed: {healthy_count} healthy, {unhealthy_count} unhealthy"
            )
            
            # Publish health check event
            self._event_bus.publish(
                event_type="remote_service/health_check",
                source="remote_manager",
                payload={
                    "services": {
                        name: {"healthy": status}
                        for name, status in health_statuses.items()
                    },
                    "healthy_count": healthy_count,
                    "unhealthy_count": unhealthy_count,
                    "timestamp": time.time(),
                },
            )
        
        except Exception as e:
            self._logger.error(
                f"Error in health check task: {str(e)}",
                extra={"error": str(e)},
            )
    
    def _schedule_health_checks(self) -> None:
        """Schedule periodic health checks for all services."""
        if self._health_check_task_id is not None:
            # Cancel existing task
            self._thread_manager.cancel_periodic_task(self._health_check_task_id)
        
        # Schedule new task
        self._health_check_task_id = self._thread_manager.schedule_periodic_task(
            interval=self._health_check_interval,
            func=self._health_check_task,
            task_id="service_health_check",
        )
        
        self._logger.debug(
            f"Scheduled service health checks with interval {self._health_check_interval}s"
        )
    
    def _on_service_register_event(self, event: Any) -> None:
        """Handle service registration events.
        
        Args:
            event: Service registration event.
        """
        payload = event.payload
        
        if not isinstance(payload, dict):
            self._logger.error("Invalid service registration event payload")
            return
        
        service_config = payload.get("service_config")
        service_name = payload.get("service_name")
        
        if not service_config or not service_name:
            self._logger.error(
                "Missing service_config or service_name in registration event"
            )
            return
        
        try:
            self._register_service_from_config(service_name, service_config)
        except Exception as e:
            self._logger.error(
                f"Failed to register service '{service_name}' from event: {str(e)}",
                extra={"service": service_name, "error": str(e)},
            )
    
    def _on_service_unregister_event(self, event: Any) -> None:
        """Handle service unregistration events.
        
        Args:
            event: Service unregistration event.
        """
        payload = event.payload
        
        if not isinstance(payload, dict):
            self._logger.error("Invalid service unregistration event payload")
            return
        
        service_name = payload.get("service_name")
        
        if not service_name:
            self._logger.error("Missing service_name in unregistration event")
            return
        
        self.unregister_service(service_name)
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for remote services.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        if key == "remote_services.health_check_interval" and isinstance(value, (int, float)):
            # Update health check interval
            self._health_check_interval = float(value)
            self._logger.info(f"Updated health check interval to {self._health_check_interval}s")
            
            # Reschedule health checks
            self._schedule_health_checks()
        
        elif key.startswith("remote_services.services."):
            # Service configuration changed
            parts = key.split(".")
            if len(parts) >= 3:
                service_name = parts[2]
                self._logger.warning(
                    f"Service configuration for '{service_name}' changed, "
                    "restart required for changes to take effect",
                    extra={"service": service_name},
                )
    
    def make_request(
        self,
        service_name: str,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        """Make a request to a remote service.
        
        Args:
            service_name: Name of the service to call.
            method: HTTP method (GET, POST, etc.).
            path: Path relative to the service base URL.
            **kwargs: Additional arguments for the request.
            
        Returns:
            Any: The response from the service.
            
        Raises:
            ValueError: If the service is not found or the request fails.
        """
        if not self._initialized:
            raise ValueError("Remote Services Manager not initialized")
        
        # Get the service
        service = self.get_http_service(service_name)
        
        if service is None:
            raise ValueError(f"Service '{service_name}' not found or not an HTTP service")
        
        # Make the request
        try:
            method = method.upper()
            
            if method == "GET":
                response = service.get(path, **kwargs)
            elif method == "POST":
                response = service.post(path, **kwargs)
            elif method == "PUT":
                response = service.put(path, **kwargs)
            elif method == "DELETE":
                response = service.delete(path, **kwargs)
            elif method == "PATCH":
                response = service.patch(path, **kwargs)
            else:
                response = service.request(method, path, **kwargs)
            
            # Check if request was successful
            response.raise_for_status()
            
            # Return JSON response if available
            try:
                return response.json()
            except:
                return response.text
        
        except Exception as e:
            # Log the error
            self._logger.error(
                f"Error calling service '{service_name}': {str(e)}",
                extra={
                    "service": service_name,
                    "method": method,
                    "path": path,
                    "error": str(e),
                },
            )
            
            raise ValueError(f"Request to service '{service_name}' failed: {str(e)}")
    
    async def make_request_async(
        self,
        service_name: str,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        """Make an asynchronous request to a remote service.
        
        Args:
            service_name: Name of the service to call.
            method: HTTP method (GET, POST, etc.).
            path: Path relative to the service base URL.
            **kwargs: Additional arguments for the request.
            
        Returns:
            Any: The response from the service.
            
        Raises:
            ValueError: If the service is not found or the request fails.
        """
        if not self._initialized:
            raise ValueError("Remote Services Manager not initialized")
        
        # Get the service
        service = self.get_async_http_service(service_name)
        
        if service is None:
            raise ValueError(f"Service '{service_name}' not found or not an async HTTP service")
        
        # Make the request
        try:
            method = method.upper()
            
            if method == "GET":
                response = await service.get(path, **kwargs)
            elif method == "POST":
                response = await service.post(path, **kwargs)
            elif method == "PUT":
                response = await service.put(path, **kwargs)
            elif method == "DELETE":
                response = await service.delete(path, **kwargs)
            elif method == "PATCH":
                response = await service.patch(path, **kwargs)
            else:
                response = await service.request(method, path, **kwargs)
            
            # Check if request was successful
            response.raise_for_status()
            
            # Return JSON response if available
            try:
                return response.json()
            except:
                return response.text
        
        except Exception as e:
            # Log the error
            self._logger.error(
                f"Error calling service '{service_name}': {str(e)}",
                extra={
                    "service": service_name,
                    "method": method,
                    "path": path,
                    "error": str(e),
                },
            )
            
            raise ValueError(f"Request to service '{service_name}' failed: {str(e)}")
    
    def shutdown(self) -> None:
        """Shut down the Remote Services Manager.
        
        Closes connections to all remote services and cleans up resources.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            self._logger.info("Shutting down Remote Services Manager")
            
            # Cancel health check task
            if self._health_check_task_id is not None:
                self._thread_manager.cancel_periodic_task(self._health_check_task_id)
                self._health_check_task_id = None
            
            # Close connections to all services
            with self._services_lock:
                for service_name, service in list(self._services.items()):
                    try:
                        # Close service connections
                        if hasattr(service, "close") and callable(service.close):
                            service.close()
                        
                        self._logger.debug(f"Closed connections to service '{service_name}'")
                    
                    except Exception as e:
                        self._logger.error(
                            f"Error closing connections to service '{service_name}': {str(e)}",
                            extra={"service": service_name, "error": str(e)},
                        )
                
                # Clear services
                self._services.clear()
            
            # Unregister from event bus
            self._event_bus.unsubscribe("remote_manager")
            
            # Unregister config listener
            self._config_manager.unregister_listener("remote_services", self._on_config_changed)
            
            self._initialized = False
            self._healthy = False
            
            self._logger.info("Remote Services Manager shut down successfully")
        
        except Exception as e:
            self._logger.error(f"Failed to shut down Remote Services Manager: {str(e)}")
            raise ManagerShutdownError(
                f"Failed to shut down RemoteServicesManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the Remote Services Manager.
        
        Returns:
            Dict[str, Any]: Status information about the Remote Services Manager.
        """
        status = super().status()
        
        if self._initialized:
            # Get service statuses
            service_statuses = {}
            with self._services_lock:
                for service_name, service in self._services.items():
                    service_statuses[service_name] = service.status()
            
            status.update({
                "services": {
                    "count": len(self._services),
                    "statuses": service_statuses,
                },
                "health_check": {
                    "interval": self._health_check_interval,
                    "task_id": self._health_check_task_id,
                },
            })
        
        return status
