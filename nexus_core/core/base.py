from __future__ import annotations

import abc
from typing import Any, Dict, Optional, Protocol, TypeVar, runtime_checkable

T = TypeVar("T", bound="BaseManager")


@runtime_checkable
class BaseManager(Protocol):
    """Protocol defining the interface that all managers must implement.
    
    All core managers in Nexus Core must adhere to this interface to ensure
    consistent initialization, status reporting, and lifecycle management.
    """
    
    def initialize(self) -> None:
        """Initialize the manager and its resources.
        
        This method should be called after the manager is instantiated to set up
        any required resources, connections, or state. Managers should not perform
        heavy initialization in __init__ but should defer it to this method.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        ...
    
    def shutdown(self) -> None:
        """Gracefully shut down the manager and release resources.
        
        This method should properly close connections, stop threads, and release
        any resources held by the manager to prevent leaks or corruption.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        ...
    
    def status(self) -> Dict[str, Any]:
        """Return the current status of the manager.
        
        Returns:
            Dict[str, Any]: A dictionary containing status information such as:
                - 'name': The name of the manager
                - 'initialized': Whether the manager is properly initialized
                - 'healthy': Whether the manager is functioning correctly
                - Additional manager-specific status fields
        """
        ...


class NexusManager(abc.ABC):
    """Abstract base class for all Nexus Core managers.
    
    This class provides a concrete implementation of common functionality
    that all managers should have, serving as a base class for specific managers.
    """
    
    def __init__(self, name: str) -> None:
        """Initialize the manager with a name.
        
        Args:
            name: The name of the manager, used for logging and identification.
        """
        self._name: str = name
        self._initialized: bool = False
        self._healthy: bool = False
    
    @abc.abstractmethod
    def initialize(self) -> None:
        """Initialize the manager and its resources.
        
        Implementations should set self._initialized to True when successful.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        pass
    
    @abc.abstractmethod
    def shutdown(self) -> None:
        """Gracefully shut down the manager and release resources.
        
        Implementations should set self._initialized to False when successful.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        pass
    
    def status(self) -> Dict[str, Any]:
        """Return the current status of the manager.
        
        Returns:
            Dict[str, Any]: A dictionary containing status information.
        """
        return {
            "name": self._name,
            "initialized": self._initialized,
            "healthy": self._healthy,
        }
    
    @property
    def name(self) -> str:
        """Get the name of the manager.
        
        Returns:
            str: The manager name.
        """
        return self._name
    
    @property
    def initialized(self) -> bool:
        """Check if the manager is initialized.
        
        Returns:
            bool: True if the manager is initialized, False otherwise.
        """
        return self._initialized
    
    @property
    def healthy(self) -> bool:
        """Check if the manager is healthy.
        
        Returns:
            bool: True if the manager is healthy, False otherwise.
        """
        return self._healthy
