from __future__ import annotations

from typing import Any, Dict, Optional


class NexusError(Exception):
    """Base exception for all Nexus Core errors.
    
    All custom exceptions in the Nexus Core system should inherit from this class
    to ensure consistent error handling and logging.
    """
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> None:
        """Initialize a NexusError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            code: An optional error code for programmatic identification.
            details: An optional dictionary with additional error details.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        self.code = code or self.__class__.__name__
        self.details = details or {}
        super().__init__(message, *args, **kwargs)


class ManagerError(NexusError):
    """Base exception for all manager-related errors."""
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        manager_name: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Initialize a ManagerError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            manager_name: The name of the manager that raised the error.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        details = kwargs.pop("details", {})
        if manager_name:
            details["manager_name"] = manager_name
        super().__init__(message, *args, details=details, **kwargs)


class ManagerInitializationError(ManagerError):
    """Exception raised when a manager fails to initialize."""
    pass


class ManagerShutdownError(ManagerError):
    """Exception raised when a manager fails to shut down cleanly."""
    pass


class ConfigurationError(NexusError):
    """Exception raised for configuration-related errors."""
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        config_key: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Initialize a ConfigurationError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            config_key: The configuration key that caused the error.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        details = kwargs.pop("details", {})
        if config_key:
            details["config_key"] = config_key
        super().__init__(message, *args, details=details, **kwargs)


class EventBusError(NexusError):
    """Exception raised for event bus-related errors."""
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        event_type: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Initialize an EventBusError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            event_type: The event type that caused the error.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        details = kwargs.pop("details", {})
        if event_type:
            details["event_type"] = event_type
        super().__init__(message, *args, details=details, **kwargs)


class PluginError(NexusError):
    """Exception raised for plugin-related errors."""
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        plugin_name: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Initialize a PluginError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            plugin_name: The name of the plugin that caused the error.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        details = kwargs.pop("details", {})
        if plugin_name:
            details["plugin_name"] = plugin_name
        super().__init__(message, *args, details=details, **kwargs)


class DatabaseError(NexusError):
    """Exception raised for database-related errors."""
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        query: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Initialize a DatabaseError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            query: The database query that caused the error.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        details = kwargs.pop("details", {})
        if query:
            details["query"] = query
        super().__init__(message, *args, details=details, **kwargs)


class SecurityError(NexusError):
    """Exception raised for security-related errors."""
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        user_id: Optional[str] = None,
        permission: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Initialize a SecurityError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            user_id: The ID of the user related to the security error.
            permission: The permission that was being checked.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        details = kwargs.pop("details", {})
        if user_id:
            details["user_id"] = user_id
        if permission:
            details["permission"] = permission
        super().__init__(message, *args, details=details, **kwargs)


class ThreadManagerError(NexusError):
    """Exception raised for thread management-related errors."""
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        thread_id: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Initialize a ThreadManagerError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            thread_id: The ID of the thread that caused the error.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        details = kwargs.pop("details", {})
        if thread_id:
            details["thread_id"] = thread_id
        super().__init__(message, *args, details=details, **kwargs)


class FileError(NexusError):
    """Exception raised for file-related errors."""
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        file_path: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Initialize a FileError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            file_path: The path of the file that caused the error.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        details = kwargs.pop("details", {})
        if file_path:
            details["file_path"] = file_path
        super().__init__(message, *args, details=details, **kwargs)


class APIError(NexusError):
    """Exception raised for API-related errors."""
    
    def __init__(
        self, 
        message: str, 
        *args: Any, 
        status_code: Optional[int] = None,
        endpoint: Optional[str] = None,
        **kwargs: Any
    ) -> None:
        """Initialize an APIError.
        
        Args:
            message: A descriptive error message.
            *args: Additional positional arguments to pass to the parent Exception.
            status_code: The HTTP status code associated with the error.
            endpoint: The API endpoint that caused the error.
            **kwargs: Additional keyword arguments to pass to the parent Exception.
        """
        details = kwargs.pop("details", {})
        if status_code:
            details["status_code"] = status_code
        if endpoint:
            details["endpoint"] = endpoint
        super().__init__(message, *args, details=details, **kwargs)
