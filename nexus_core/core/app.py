from __future__ import annotations

import atexit
import importlib
import signal
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, cast

from nexus_core.core.base import BaseManager, NexusManager
from nexus_core.core.config_manager import ConfigManager
from nexus_core.core.event_bus import EventBusManager
from nexus_core.core.logging_manager import LoggingManager
from nexus_core.utils.exceptions import ManagerInitializationError, NexusError


class ApplicationCore:
    """Core application controller for Nexus Core.
    
    The Application Core is responsible for initializing and managing all the core
    managers that make up the Nexus Core system. It handles startup, shutdown,
    and provides access to initialized managers.
    """
    
    def __init__(self, config_path: Optional[str] = None) -> None:
        """Initialize the Application Core.
        
        Args:
            config_path: Optional path to the configuration file. If not provided,
                        the default configuration path will be used.
        """
        self._config_path = config_path
        self._managers: Dict[str, NexusManager] = {}
        self._initialized = False
        self._logger = None
    
    def initialize(self) -> None:
        """Initialize the Application Core and all managers.
        
        Initializes managers in the correct order to handle dependencies.
        
        Raises:
            ManagerInitializationError: If initialization of any manager fails.
        """
        try:
            # Initialize Configuration Manager first
            config_manager = ConfigManager(config_path=self._config_path)
            config_manager.initialize()
            self._managers["config"] = config_manager
            
            # Initialize Logging Manager second
            logging_manager = LoggingManager(config_manager)
            logging_manager.initialize()
            self._managers["logging"] = logging_manager
            
            # Get logger for Application Core
            self._logger = logging_manager.get_logger("app_core")
            self._logger.info("Starting Nexus Core initialization")
            
            # Initialize Event Bus Manager third
            event_bus_manager = EventBusManager(config_manager, logging_manager)
            event_bus_manager.initialize()
            self._managers["event_bus"] = event_bus_manager
            
            # TODO: Initialize other managers in the correct order
            # For example:
            # - Thread Manager
            # - File Manager
            # - Resource Manager
            # - Database Manager
            # - Plugin Manager
            # - Remote Services Manager
            # - Monitoring Manager
            # - Security Manager
            # - API Manager
            # - Cloud Manager
            
            # Set up signal handlers
            self._setup_signal_handlers()
            
            # Register shutdown function with atexit
            atexit.register(self.shutdown)
            
            self._initialized = True
            self._logger.info("Nexus Core initialization complete")
        
        except Exception as e:
            # If logging is initialized, log the error
            if self._logger:
                self._logger.error(f"Initialization failed: {str(e)}")
                self._logger.debug(f"Initialization error details: {traceback.format_exc()}")
            
            # Shut down any initialized managers
            self.shutdown()
            
            # Re-raise the exception
            if isinstance(e, NexusError):
                raise
            else:
                raise ManagerInitializationError(
                    f"Failed to initialize Nexus Core: {str(e)}",
                    manager_name="ApplicationCore",
                ) from e
    
    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""
        if sys.platform != "win32":
            # Handle SIGTERM and SIGINT on Unix-like systems
            signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Handle SIGINT (Ctrl+C) on all platforms
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, sig: int, frame: Any) -> None:
        """Handle signals for graceful shutdown.
        
        Args:
            sig: The signal number.
            frame: The current stack frame.
        """
        if self._logger:
            self._logger.info(f"Received signal {sig}, shutting down")
        
        self.shutdown()
        sys.exit(0)
    
    def get_manager(self, name: str) -> Optional[NexusManager]:
        """Get a manager by name.
        
        Args:
            name: The name of the manager to retrieve.
            
        Returns:
            Optional[NexusManager]: The requested manager, or None if not found.
        """
        return self._managers.get(name)
    
    def shutdown(self) -> None:
        """Shut down all managers in the reverse order of initialization."""
        if not self._initialized and not self._managers:
            return
        
        if self._logger:
            self._logger.info("Shutting down Nexus Core")
        
        # Get a list of managers in reverse order for proper shutdown sequence
        managers = list(self._managers.items())
        managers.reverse()
        
        for name, manager in managers:
            try:
                if manager.initialized:
                    if self._logger:
                        self._logger.debug(f"Shutting down {name} manager")
                    manager.shutdown()
            except Exception as e:
                if self._logger:
                    self._logger.error(f"Error shutting down {name} manager: {str(e)}")
        
        # Clear the managers dictionary
        self._managers.clear()
        self._initialized = False
        
        # Remove the atexit handler
        try:
            atexit.unregister(self.shutdown)
        except:
            pass
        
        if self._logger:
            self._logger.info("Nexus Core shutdown complete")
            # The logger is now unavailable
            self._logger = None
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the Application Core and all managers.
        
        Returns:
            Dict[str, Any]: Status information about the Application Core and all managers.
        """
        status = {
            "name": "ApplicationCore",
            "initialized": self._initialized,
            "managers": {},
        }
        
        for name, manager in self._managers.items():
            try:
                status["managers"][name] = manager.status()
            except Exception as e:
                status["managers"][name] = {
                    "error": f"Failed to get status: {str(e)}",
                    "initialized": manager.initialized,
                    "healthy": False,
                }
        
        return status
