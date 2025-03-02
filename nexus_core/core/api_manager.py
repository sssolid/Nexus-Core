from __future__ import annotations

import asyncio
import inspect
import os
import sys
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union, cast

try:
    import fastapi
    from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from fastapi.routing import APIRouter
    from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
    import pydantic
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError:
    # Handling for when FastAPI is not installed
    fastapi = None
    FastAPI = object
    APIRouter = object
    BaseModel = object
    Field = lambda *args, **kwargs: None  # noqa

from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import ManagerInitializationError, ManagerShutdownError, APIError


# Define API models if FastAPI is available
if fastapi:
    class UserLogin(BaseModel):
        """Model for user login request body."""
        
        username: str = Field(..., description="Username or email")
        password: str = Field(..., description="User password")
    
    class Token(BaseModel):
        """Model for authentication token response."""
        
        access_token: str = Field(..., description="JWT access token")
        token_type: str = Field(..., description="Token type")
        expires_in: int = Field(..., description="Token expiration in seconds")
        refresh_token: Optional[str] = Field(None, description="JWT refresh token")
    
    class TokenData(BaseModel):
        """Model for token payload."""
        
        user_id: str = Field(..., description="User ID")
        username: Optional[str] = Field(None, description="Username")
        roles: List[str] = Field(default_factory=list, description="User roles")
    
    class UserCreate(BaseModel):
        """Model for user creation request body."""
        
        username: str = Field(..., description="Username")
        email: str = Field(..., description="Email address")
        password: str = Field(..., description="Password")
        roles: List[str] = Field(default_factory=list, description="User roles")
        metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    
    class UserUpdate(BaseModel):
        """Model for user update request body."""
        
        username: Optional[str] = Field(None, description="Username")
        email: Optional[str] = Field(None, description="Email address")
        password: Optional[str] = Field(None, description="Password")
        roles: Optional[List[str]] = Field(None, description="User roles")
        active: Optional[bool] = Field(None, description="User active status")
        metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    
    class UserResponse(BaseModel):
        """Model for user information response."""
        
        id: str = Field(..., description="User ID")
        username: str = Field(..., description="Username")
        email: str = Field(..., description="Email address")
        roles: List[str] = Field(default_factory=list, description="User roles")
        active: bool = Field(..., description="User active status")
        created_at: str = Field(..., description="Creation timestamp")
        last_login: Optional[str] = Field(None, description="Last login timestamp")
        metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    class PluginResponse(BaseModel):
        """Model for plugin information response."""
        
        name: str = Field(..., description="Plugin name")
        version: str = Field(..., description="Plugin version")
        description: str = Field(..., description="Plugin description")
        author: str = Field(..., description="Plugin author")
        state: str = Field(..., description="Plugin state")
        enabled: bool = Field(..., description="Whether the plugin is enabled")
        dependencies: List[str] = Field(default_factory=list, description="Plugin dependencies")
        metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    
    class StatusResponse(BaseModel):
        """Model for system status response."""
        
        name: str = Field(..., description="Component name")
        initialized: bool = Field(..., description="Whether the component is initialized")
        healthy: bool = Field(..., description="Whether the component is healthy")
        managers: Dict[str, Any] = Field(default_factory=dict, description="Manager statuses")
        version: str = Field(..., description="System version")
    
    class AlertResponse(BaseModel):
        """Model for alert information response."""
        
        id: str = Field(..., description="Alert ID")
        level: str = Field(..., description="Alert level")
        message: str = Field(..., description="Alert message")
        source: str = Field(..., description="Alert source")
        timestamp: str = Field(..., description="Alert timestamp")
        metric_name: Optional[str] = Field(None, description="Metric name")
        metric_value: Optional[float] = Field(None, description="Metric value")
        threshold: Optional[float] = Field(None, description="Alert threshold")
        resolved: bool = Field(..., description="Whether the alert is resolved")
        resolved_at: Optional[str] = Field(None, description="When the alert was resolved")
        metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class APIManager(NexusManager):
    """Manages the REST API for Nexus Core.
    
    The API Manager is responsible for setting up and running the REST API
    server, registering API endpoints, and handling authentication and
    authorization for API requests. It uses FastAPI to provide a modern,
    high-performance API with automatic documentation.
    """
    
    def __init__(
        self,
        config_manager: Any,
        logger_manager: Any,
        security_manager: Any,
        event_bus_manager: Any,
        thread_manager: Any,
        registry: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialize the API Manager.
        
        Args:
            config_manager: The Configuration Manager for API settings.
            logger_manager: The Logging Manager for logging.
            security_manager: The Security Manager for authentication and authorization.
            event_bus_manager: The Event Bus Manager for publishing API events.
            thread_manager: The Thread Manager for running the API server.
            registry: Optional registry of manager instances for API access.
        """
        super().__init__(name="APIManager")
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger("api_manager")
        self._security_manager = security_manager
        self._event_bus = event_bus_manager
        self._thread_manager = thread_manager
        self._registry = registry or {}
        
        # API server settings
        self._enabled = True
        self._host = "0.0.0.0"  # Default to all interfaces
        self._port = 8000
        self._workers = 4
        
        # CORS settings
        self._cors_origins = ["*"]
        self._cors_methods = ["*"]
        self._cors_headers = ["*"]
        
        # Rate limiting
        self._rate_limit_enabled = True
        self._rate_limit_requests = 100  # Requests per minute
        
        # FastAPI app and routers
        self._app: Optional[FastAPI] = None
        self._routers: Dict[str, APIRouter] = {}
        
        # OAuth2 scheme for token authentication
        self._oauth2_scheme: Optional[Any] = None
        
        # API server control
        self._server_thread: Optional[threading.Thread] = None
        self._server_should_exit = threading.Event()
        self._server_task: Optional[asyncio.Task] = None
    
    def initialize(self) -> None:
        """Initialize the API Manager.
        
        Sets up the FastAPI application, registers API endpoints, and starts the server.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Check if FastAPI is installed
            if not fastapi:
                raise ManagerInitializationError(
                    "FastAPI is not installed. Cannot initialize API Manager.",
                    manager_name=self.name,
                )
            
            # Get API configuration
            api_config = self._config_manager.get("api", {})
            
            self._enabled = api_config.get("enabled", True)
            if not self._enabled:
                self._logger.info("API is disabled in configuration")
                self._initialized = True
                return
            
            self._host = api_config.get("host", "0.0.0.0")
            self._port = api_config.get("port", 8000)
            self._workers = api_config.get("workers", 4)
            
            # CORS settings
            cors_config = api_config.get("cors", {})
            self._cors_origins = cors_config.get("origins", ["*"])
            self._cors_methods = cors_config.get("methods", ["*"])
            self._cors_headers = cors_config.get("headers", ["*"])
            
            # Rate limiting settings
            rate_limit_config = api_config.get("rate_limit", {})
            self._rate_limit_enabled = rate_limit_config.get("enabled", True)
            self._rate_limit_requests = rate_limit_config.get("requests_per_minute", 100)
            
            # Create FastAPI app
            self._app = FastAPI(
                title="Nexus Core API",
                description="API for the Nexus Core platform",
                version="0.1.0",
                docs_url="/api/docs",
                redoc_url="/api/redoc",
                openapi_url="/api/openapi.json",
            )
            
            # Add CORS middleware
            self._app.add_middleware(
                CORSMiddleware,
                allow_origins=self._cors_origins,
                allow_methods=self._cors_methods,
                allow_headers=self._cors_headers,
                allow_credentials=True,
            )
            
            # Add rate limiting middleware if enabled
            if self._rate_limit_enabled:
                self._add_rate_limiting_middleware()
            
            # Set up OAuth2 scheme
            self._oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
            
            # Register API routes
            self._register_api_routes()
            
            # Set up exception handlers
            self._setup_exception_handlers()
            
            # Register for config changes
            self._config_manager.register_listener("api", self._on_config_changed)
            
            # Start API server
            self._start_api_server()
            
            self._initialized = True
            self._healthy = True
            
            self._logger.info(
                f"API Manager initialized and server running on http://{self._host}:{self._port}"
            )
            
            # Publish API started event
            self._event_bus.publish(
                event_type="api/started",
                source="api_manager",
                payload={
                    "host": self._host,
                    "port": self._port,
                    "url": f"http://{self._host}:{self._port}/api",
                },
            )
        
        except Exception as e:
            self._logger.error(f"Failed to initialize API Manager: {str(e)}")
            raise ManagerInitializationError(
                f"Failed to initialize APIManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def _add_rate_limiting_middleware(self) -> None:
        """Add rate limiting middleware to the FastAPI app."""
        if not self._app:
            return
        
        # Simple in-memory rate limiting implementation
        rate_limits: Dict[str, List[float]] = {}
        rate_limit_window = 60.0  # 1 minute window
        
        @self._app.middleware("http")
        async def rate_limit_middleware(request: Request, call_next: Callable) -> Any:
            # Get client IP
            client_ip = request.client.host if request.client else "unknown"
            
            # Skip rate limiting for some paths
            if request.url.path.startswith(("/api/docs", "/api/redoc", "/api/openapi.json")):
                return await call_next(request)
            
            # Current time
            now = time.time()
            
            # Clean up rate limits for this client
            if client_ip in rate_limits:
                # Remove timestamps older than the window
                rate_limits[client_ip] = [
                    ts for ts in rate_limits[client_ip] if now - ts < rate_limit_window
                ]
            else:
                rate_limits[client_ip] = []
            
            # Check if rate limit exceeded
            if len(rate_limits[client_ip]) >= self._rate_limit_requests:
                self._logger.warning(
                    f"Rate limit exceeded for {client_ip}",
                    extra={"client_ip": client_ip, "path": request.url.path},
                )
                
                # Return 429 Too Many Requests
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Rate limit exceeded. Please try again later.",
                        "remaining": 0,
                        "reset_after": int(rate_limit_window - (now - rate_limits[client_ip][0])),
                    },
                )
            
            # Add current timestamp to rate limits
            rate_limits[client_ip].append(now)
            
            # Process the request
            return await call_next(request)
    
    def _setup_exception_handlers(self) -> None:
        """Set up exception handlers for the FastAPI app."""
        if not self._app:
            return
        
        @self._app.exception_handler(Exception)
        async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
            # Log the exception
            self._logger.error(
                f"Unhandled exception in API request: {str(exc)}",
                extra={"path": request.url.path, "method": request.method, "error": str(exc)},
            )
            
            # Return a generic error response
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "detail": "An internal server error occurred. Please try again later.",
                },
            )
    
    def _register_api_routes(self) -> None:
        """Register API routes for the FastAPI app."""
        if not self._app:
            return
        
        # Create API routers
        # v1 version router
        v1_router = APIRouter(prefix="/api/v1")
        self._routers["v1"] = v1_router
        
        # Auth router
        auth_router = self._create_auth_router()
        v1_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
        
        # Users router
        users_router = self._create_users_router()
        v1_router.include_router(users_router, prefix="/users", tags=["Users"])
        
        # System router
        system_router = self._create_system_router()
        v1_router.include_router(system_router, prefix="/system", tags=["System"])
        
        # Plugins router
        plugins_router = self._create_plugins_router()
        v1_router.include_router(plugins_router, prefix="/plugins", tags=["Plugins"])
        
        # Monitoring router
        monitoring_router = self._create_monitoring_router()
        v1_router.include_router(monitoring_router, prefix="/monitoring", tags=["Monitoring"])
        
        # Include the v1 router in the main app
        self._app.include_router(v1_router)
        
        # Root route
        @self._app.get("/", include_in_schema=False)
        async def root() -> Dict[str, str]:
            return {
                "name": "Nexus Core API",
                "version": "0.1.0",
                "docs_url": "/api/docs",
            }
        
        # Health check route
        @self._app.get("/health", tags=["Health"])
        async def health_check() -> Dict[str, bool]:
            return {"status": "ok", "healthy": True}
    
    def _create_auth_router(self) -> APIRouter:
        """Create a router for authentication endpoints.
        
        Returns:
            APIRouter: The auth router.
        """
        router = APIRouter()
        
        @router.post("/token", response_model=Token)
        async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> Dict[str, Any]:
            """Authenticate a user and return an access token."""
            user_data = self._security_manager.authenticate_user(
                form_data.username, form_data.password
            )
            
            if not user_data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Incorrect username or password",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            return {
                "access_token": user_data["access_token"],
                "token_type": user_data["token_type"],
                "expires_in": user_data["expires_in"],
                "refresh_token": user_data["refresh_token"],
            }
        
        @router.post("/refresh", response_model=Token)
        async def refresh(refresh_token: str) -> Dict[str, Any]:
            """Refresh an access token using a refresh token."""
            token_data = self._security_manager.refresh_token(refresh_token)
            
            if not token_data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired refresh token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            return token_data
        
        @router.post("/revoke")
        async def revoke(token: str) -> Dict[str, bool]:
            """Revoke a token."""
            success = self._security_manager.revoke_token(token)
            
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to revoke token",
                )
            
            return {"success": True}
        
        @router.get("/me", response_model=UserResponse)
        async def read_users_me(current_user: Dict[str, Any] = Depends(self._get_current_user)) -> Dict[str, Any]:
            """Get the current user's information."""
            return current_user
        
        return router
    
    def _create_users_router(self) -> APIRouter:
        """Create a router for user management endpoints.
        
        Returns:
            APIRouter: The users router.
        """
        router = APIRouter()
        
        @router.get("/", response_model=List[UserResponse])
        async def get_users(
            current_user: Dict[str, Any] = Depends(self._get_current_admin_user)
        ) -> List[Dict[str, Any]]:
            """Get all users (admin only)."""
            return self._security_manager.get_all_users()
        
        @router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
        async def create_user(
            user: UserCreate,
            current_user: Dict[str, Any] = Depends(self._get_current_admin_user),
        ) -> Dict[str, Any]:
            """Create a new user (admin only)."""
            try:
                user_id = self._security_manager.create_user(
                    username=user.username,
                    email=user.email,
                    password=user.password,
                    roles=[self._get_user_role(role) for role in user.roles],
                    metadata=user.metadata,
                )
                
                if not user_id:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to create user",
                    )
                
                return self._security_manager.get_user_info(user_id)
            
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
        
        @router.get("/{user_id}", response_model=UserResponse)
        async def get_user(
            user_id: str,
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("users.view")),
        ) -> Dict[str, Any]:
            """Get a user by ID."""
            user = self._security_manager.get_user_info(user_id)
            
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"User with ID {user_id} not found",
                )
            
            return user
        
        @router.put("/{user_id}", response_model=UserResponse)
        async def update_user(
            user_id: str,
            user_update: UserUpdate,
            current_user: Dict[str, Any] = Depends(self._get_current_admin_user),
        ) -> Dict[str, Any]:
            """Update a user (admin only)."""
            # Convert to dict and handle role conversions
            update_data = user_update.dict(exclude_unset=True)
            
            if "roles" in update_data:
                update_data["roles"] = [
                    self._get_user_role(role) for role in update_data["roles"]
                ]
            
            try:
                success = self._security_manager.update_user(user_id, update_data)
                
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to update user {user_id}",
                    )
                
                return self._security_manager.get_user_info(user_id)
            
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
        
        @router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def delete_user(
            user_id: str,
            current_user: Dict[str, Any] = Depends(self._get_current_admin_user),
        ) -> None:
            """Delete a user (admin only)."""
            try:
                success = self._security_manager.delete_user(user_id)
                
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to delete user {user_id}",
                    )
            
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
        
        return router
    
    def _create_system_router(self) -> APIRouter:
        """Create a router for system management endpoints.
        
        Returns:
            APIRouter: The system router.
        """
        router = APIRouter()
        
        @router.get("/status", response_model=StatusResponse)
        async def get_system_status(
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("system.view")),
        ) -> Dict[str, Any]:
            """Get system status information."""
            # Get status from App Core if available
            if "app_core" in self._registry:
                return self._registry["app_core"].status()
            
            # Fallback to a basic status
            return {
                "name": "Nexus Core",
                "initialized": True,
                "healthy": True,
                "managers": {},
                "version": "0.1.0",
            }
        
        @router.get("/config/{path:path}")
        async def get_config(
            path: str,
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("system.view")),
        ) -> Dict[str, Any]:
            """Get configuration value by path."""
            if "config" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Configuration Manager not available",
                )
            
            value = self._registry["config"].get(path)
            
            if value is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Configuration path {path} not found",
                )
            
            return {"path": path, "value": value}
        
        @router.put("/config/{path:path}")
        async def update_config(
            path: str,
            value: Any,
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("system.manage")),
        ) -> Dict[str, Any]:
            """Update configuration value by path."""
            if "config" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Configuration Manager not available",
                )
            
            try:
                self._registry["config"].set(path, value)
                return {"path": path, "value": value, "updated": True}
            
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
        
        return router
    
    def _create_plugins_router(self) -> APIRouter:
        """Create a router for plugin management endpoints.
        
        Returns:
            APIRouter: The plugins router.
        """
        router = APIRouter()
        
        @router.get("/", response_model=List[PluginResponse])
        async def get_plugins(
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("plugins.view")),
        ) -> List[Dict[str, Any]]:
            """Get all plugins."""
            if "plugin_manager" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Plugin Manager not available",
                )
            
            return self._registry["plugin_manager"].get_all_plugins()
        
        @router.get("/{plugin_name}", response_model=PluginResponse)
        async def get_plugin(
            plugin_name: str,
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("plugins.view")),
        ) -> Dict[str, Any]:
            """Get a plugin by name."""
            if "plugin_manager" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Plugin Manager not available",
                )
            
            plugin = self._registry["plugin_manager"].get_plugin_info(plugin_name)
            
            if not plugin:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Plugin {plugin_name} not found",
                )
            
            return plugin
        
        @router.post("/{plugin_name}/load")
        async def load_plugin(
            plugin_name: str,
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("plugins.manage")),
        ) -> Dict[str, Any]:
            """Load a plugin."""
            if "plugin_manager" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Plugin Manager not available",
                )
            
            try:
                success = self._registry["plugin_manager"].load_plugin(plugin_name)
                
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to load plugin {plugin_name}",
                    )
                
                return {"plugin": plugin_name, "loaded": True}
            
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
        
        @router.post("/{plugin_name}/unload")
        async def unload_plugin(
            plugin_name: str,
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("plugins.manage")),
        ) -> Dict[str, Any]:
            """Unload a plugin."""
            if "plugin_manager" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Plugin Manager not available",
                )
            
            try:
                success = self._registry["plugin_manager"].unload_plugin(plugin_name)
                
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to unload plugin {plugin_name}",
                    )
                
                return {"plugin": plugin_name, "unloaded": True}
            
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
        
        @router.post("/{plugin_name}/enable")
        async def enable_plugin(
            plugin_name: str,
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("plugins.manage")),
        ) -> Dict[str, Any]:
            """Enable a plugin."""
            if "plugin_manager" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Plugin Manager not available",
                )
            
            try:
                success = self._registry["plugin_manager"].enable_plugin(plugin_name)
                
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to enable plugin {plugin_name}",
                    )
                
                return {"plugin": plugin_name, "enabled": True}
            
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
        
        @router.post("/{plugin_name}/disable")
        async def disable_plugin(
            plugin_name: str,
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("plugins.manage")),
        ) -> Dict[str, Any]:
            """Disable a plugin."""
            if "plugin_manager" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Plugin Manager not available",
                )
            
            try:
                success = self._registry["plugin_manager"].disable_plugin(plugin_name)
                
                if not success:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to disable plugin {plugin_name}",
                    )
                
                return {"plugin": plugin_name, "disabled": True}
            
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )
        
        return router
    
    def _create_monitoring_router(self) -> APIRouter:
        """Create a router for monitoring endpoints.
        
        Returns:
            APIRouter: The monitoring router.
        """
        router = APIRouter()
        
        @router.get("/alerts", response_model=List[AlertResponse])
        async def get_alerts(
            include_resolved: bool = False,
            level: Optional[str] = None,
            metric_name: Optional[str] = None,
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("system.view")),
        ) -> List[Dict[str, Any]]:
            """Get monitoring alerts."""
            if "monitoring" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Monitoring Manager not available",
                )
            
            # Convert level string to AlertLevel if provided
            alert_level = None
            if level:
                try:
                    # This assumes AlertLevel is available from the monitoring manager
                    alert_level = getattr(self._registry["monitoring"], "AlertLevel")(level)
                except (ValueError, AttributeError):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Invalid alert level: {level}",
                    )
            
            return self._registry["monitoring"].get_alerts(
                include_resolved=include_resolved,
                level=alert_level,
                metric_name=metric_name,
            )
        
        @router.get("/diagnostics")
        async def get_diagnostics(
            current_user: Dict[str, Any] = Depends(self._get_current_user_with_permission("system.view")),
        ) -> Dict[str, Any]:
            """Get diagnostic report."""
            if "monitoring" not in self._registry:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Monitoring Manager not available",
                )
            
            report = self._registry["monitoring"].generate_diagnostic_report()
            
            if "error" in report:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=report["error"],
                )
            
            return report
        
        return router
    
    async def _get_current_user_data(self, token: str = Depends(OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token"))) -> Dict[str, Any]:
        """Get the current user's data from a JWT token.
        
        Args:
            token: The JWT token.
            
        Returns:
            Dict[str, Any]: The user data.
            
        Raises:
            HTTPException: If the token is invalid or the user is not found.
        """
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        # Verify the token
        payload = self._security_manager.verify_token(token)
        if not payload:
            raise credentials_exception
        
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_exception
        
        # Get user info
        user_info = self._security_manager.get_user_info(user_id)
        if not user_info:
            raise credentials_exception
        
        return user_info
    
    async def _get_current_user(self, user_data: Dict[str, Any] = Depends(_get_current_user_data)) -> Dict[str, Any]:
        """Get the current user from user data.
        
        Args:
            user_data: The user data from the token.
            
        Returns:
            Dict[str, Any]: The user data.
            
        Raises:
            HTTPException: If the user is inactive.
        """
        if not user_data.get("active", True):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Inactive user",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return user_data
    
    async def _get_current_admin_user(self, current_user: Dict[str, Any] = Depends(_get_current_user)) -> Dict[str, Any]:
        """Get the current user and verify they have admin role.
        
        Args:
            current_user: The current user data.
            
        Returns:
            Dict[str, Any]: The user data.
            
        Raises:
            HTTPException: If the user is not an admin.
        """
        if "admin" not in current_user.get("roles", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        
        return current_user
    
    def _get_current_user_with_permission(self, permission: str) -> Callable:
        """Generate a dependency function that checks if the current user has a permission.
        
        Args:
            permission: The permission to check for.
            
        Returns:
            Callable: A dependency function that returns the current user if they have the permission.
        """
        
        async def has_permission(current_user: Dict[str, Any] = Depends(self._get_current_user)) -> Dict[str, Any]:
            resource, action = permission.split(".")
            user_id = current_user["id"]
            
            if not self._security_manager.has_permission(user_id, resource, action):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Not enough permissions: {permission}",
                )
            
            return current_user
        
        return has_permission
    
    def _get_user_role(self, role_name: str) -> Any:
        """Convert a role name to a UserRole enum value.
        
        Args:
            role_name: The name of the role.
            
        Returns:
            Any: The UserRole enum value.
            
        Raises:
            ValueError: If the role name is invalid.
        """
        # This assumes UserRole is available from the security manager
        try:
            return getattr(self._security_manager.__class__, "UserRole")(role_name)
        except (ValueError, AttributeError):
            raise ValueError(f"Invalid role: {role_name}")
    
    async def _run_server(self) -> None:
        """Run the FastAPI server using uvicorn."""
        if not self._app:
            return
        
        config = uvicorn.Config(
            app=self._app,
            host=self._host,
            port=self._port,
            workers=self._workers,
            log_level="info",
            loop="asyncio",
        )
        
        server = uvicorn.Server(config)
        
        # Set the should_exit event when server is done
        original_shutdown = server.shutdown
        
        async def patched_shutdown() -> None:
            """Patched shutdown method to handle graceful shutdown."""
            await original_shutdown()
            self._server_should_exit.set()
        
        server.shutdown = patched_shutdown
        
        # Start the server
        await server.serve()
    
    def _start_api_server(self) -> None:
        """Start the API server in a separate thread."""
        if not self._app:
            return
        
        # Define the server thread function
        def server_thread() -> None:
            """Thread function for running the API server."""
            # Get or create event loop for this thread
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # Create and run the server task
            self._server_task = loop.create_task(self._run_server())
            
            try:
                # Run until the should_exit event is set
                loop.run_until_complete(self._server_task)
            except Exception as e:
                self._logger.error(f"API server error: {str(e)}")
            finally:
                # Clean up the loop
                loop.close()
        
        # Start the server thread
        self._server_thread = threading.Thread(
            target=server_thread,
            name="api-server",
            daemon=True,
        )
        self._server_thread.start()
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for the API.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        if key == "api.enabled":
            self._logger.warning(
                "Changing api.enabled requires restart to take effect",
                extra={"enabled": value},
            )
        
        elif key == "api.host" or key == "api.port" or key == "api.workers":
            self._logger.warning(
                f"Changing {key} requires restart to take effect",
                extra={key.split(".")[-1]: value},
            )
        
        elif key.startswith("api.cors."):
            self._logger.warning(
                f"Changing {key} requires restart to take effect",
                extra={key.split(".")[-1]: value},
            )
        
        elif key.startswith("api.rate_limit."):
            self._logger.warning(
                f"Changing {key} requires restart to take effect",
                extra={key.split(".")[-1]: value},
            )
    
    def register_api_endpoint(
        self,
        path: str,
        method: str,
        endpoint: Callable,
        tags: Optional[List[str]] = None,
        response_model: Optional[Any] = None,
        dependencies: Optional[List[Any]] = None,
        summary: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Register a custom API endpoint.
        
        Args:
            path: The URL path for the endpoint.
            method: The HTTP method (GET, POST, etc.).
            endpoint: The function that handles the endpoint.
            tags: Optional list of tags for the endpoint.
            response_model: Optional Pydantic model for the response.
            dependencies: Optional list of dependencies for the endpoint.
            summary: Optional summary for the endpoint.
            description: Optional description for the endpoint.
            
        Returns:
            bool: True if the endpoint was registered, False otherwise.
        """
        if not self._initialized or not self._app:
            return False
        
        # Get the router to add the endpoint to
        # Default to v1 router
        router = self._routers.get("v1", None)
        if not router:
            self._logger.error("Cannot register endpoint: No router available")
            return False
        
        try:
            # Add the endpoint to the router
            kwargs = {}
            if response_model:
                kwargs["response_model"] = response_model
            if dependencies:
                kwargs["dependencies"] = dependencies
            if summary:
                kwargs["summary"] = summary
            if description:
                kwargs["description"] = description
            
            # Register the endpoint with the router
            getattr(router, method.lower())(path, tags=tags or [], **kwargs)(endpoint)
            
            self._logger.info(
                f"Registered API endpoint: {method} {path}",
                extra={"method": method, "path": path, "tags": tags},
            )
            
            return True
        
        except Exception as e:
            self._logger.error(
                f"Failed to register API endpoint: {str(e)}",
                extra={"method": method, "path": path},
            )
            
            return False
    
    def shutdown(self) -> None:
        """Shut down the API Manager.
        
        Stops the API server and cleans up resources.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            self._logger.info("Shutting down API Manager")
            
            # Signal server to stop
            self._server_should_exit.set()
            
            # Wait for server thread to finish (with timeout)
            if self._server_thread and self._server_thread.is_alive():
                self._server_thread.join(timeout=5.0)
                if self._server_thread.is_alive():
                    self._logger.warning("API server thread did not exit gracefully")
            
            # Unregister config listener
            self._config_manager.unregister_listener("api", self._on_config_changed)
            
            # Clear routers and app
            self._routers.clear()
            self._app = None
            
            self._initialized = False
            self._healthy = False
            
            self._logger.info("API Manager shut down successfully")
        
        except Exception as e:
            self._logger.error(f"Failed to shut down API Manager: {str(e)}")
            raise ManagerShutdownError(
                f"Failed to shut down APIManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the API Manager.
        
        Returns:
            Dict[str, Any]: Status information about the API Manager.
        """
        status = super().status()
        
        if self._initialized:
            is_server_running = (
                self._server_thread is not None
                and self._server_thread.is_alive()
                and not self._server_should_exit.is_set()
            )
            
            status.update({
                "api": {
                    "enabled": self._enabled,
                    "running": is_server_running,
                    "host": self._host,
                    "port": self._port,
                    "url": f"http://{self._host}:{self._port}/api",
                },
                "endpoints": {
                    "count": sum(len(router.routes) for router in self._routers.values()) if self._routers else 0,
                },
                "rate_limit": {
                    "enabled": self._rate_limit_enabled,
                    "requests_per_minute": self._rate_limit_requests,
                },
            })
        
        return status
