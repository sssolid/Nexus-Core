from __future__ import annotations

import atexit
import logging
import logging.handlers
import os
import pathlib
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union, cast

import structlog
from pythonjsonlogger import jsonlogger

from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import ManagerInitializationError, ManagerShutdownError


class LoggingManager(NexusManager):
    """Manages application logging configuration and access.
    
    The Logging Manager provides a unified logging interface for all components
    in the Nexus Core system. It configures Python's logging module with appropriate
    handlers based on configuration, and provides methods for components to obtain
    loggers specialized for their domain.
    """
    
    # Mapping from string log levels to logging module constants
    LOG_LEVELS = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }
    
    def __init__(self, config_manager: Any) -> None:
        """Initialize the Logging Manager.
        
        Args:
            config_manager: The Configuration Manager to use for logging settings.
        """
        super().__init__(name="LoggingManager")
        self._config_manager = config_manager
        self._root_logger: Optional[logging.Logger] = None
        self._file_handler: Optional[logging.Handler] = None
        self._console_handler: Optional[logging.Handler] = None
        self._database_handler: Optional[logging.Handler] = None
        self._elk_handler: Optional[logging.Handler] = None
        self._log_directory: Optional[pathlib.Path] = None
        self._enable_structlog = False
        self._handlers: List[logging.Handler] = []
    
    def initialize(self) -> None:
        """Initialize the Logging Manager.
        
        Sets up logging based on the configuration, creating handlers for console,
        file, database, and ELK as configured.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Get logging configuration
            logging_config = self._config_manager.get("logging", {})
            log_level_str = logging_config.get("level", "INFO").lower()
            log_level = self.LOG_LEVELS.get(log_level_str, logging.INFO)
            log_format = logging_config.get("format", "json").lower()
            
            # Create log directory if file logging is enabled
            if logging_config.get("file", {}).get("enabled", True):
                log_file_path = logging_config.get("file", {}).get("path", "logs/nexus_core.log")
                self._log_directory = pathlib.Path(log_file_path).parent
                os.makedirs(self._log_directory, exist_ok=True)
            
            # Reset the root logger
            self._root_logger = logging.getLogger()
            self._root_logger.setLevel(log_level)
            
            # Remove any existing handlers
            for handler in list(self._root_logger.handlers):
                self._root_logger.removeHandler(handler)
            
            # Set up formatters based on format type
            if log_format == "json":
                self._enable_structlog = True
                formatter = self._create_json_formatter()
            else:
                formatter = logging.Formatter(
                    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
            
            # Add console handler if enabled
            if logging_config.get("console", {}).get("enabled", True):
                console_level_str = logging_config.get("console", {}).get("level", "INFO").lower()
                console_level = self.LOG_LEVELS.get(console_level_str, logging.INFO)
                self._console_handler = logging.StreamHandler(sys.stdout)
                self._console_handler.setLevel(console_level)
                self._console_handler.setFormatter(formatter)
                self._root_logger.addHandler(self._console_handler)
                self._handlers.append(self._console_handler)
            
            # Add file handler if enabled
            if logging_config.get("file", {}).get("enabled", True):
                file_path = logging_config.get("file", {}).get("path", "logs/nexus_core.log")
                rotation = logging_config.get("file", {}).get("rotation", "10 MB")
                retention = logging_config.get("file", {}).get("retention", "30 days")
                
                # Parse rotation (e.g., "10 MB")
                if isinstance(rotation, str) and "MB" in rotation:
                    max_bytes = int(rotation.split()[0]) * 1024 * 1024
                else:
                    max_bytes = 10 * 1024 * 1024  # Default: 10 MB
                
                # Parse retention (e.g., "30 days")
                if isinstance(retention, str) and "days" in retention:
                    backup_count = int(retention.split()[0])
                else:
                    backup_count = 30  # Default: 30 days
                
                self._file_handler = logging.handlers.RotatingFileHandler(
                    file_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                )
                self._file_handler.setLevel(log_level)
                self._file_handler.setFormatter(formatter)
                self._root_logger.addHandler(self._file_handler)
                self._handlers.append(self._file_handler)
            
            # Add database handler if enabled (this is a placeholder)
            if logging_config.get("database", {}).get("enabled", False):
                # In a real implementation, we would create a custom handler
                # that writes log records to the database
                # For now, we'll just note that it's not implemented
                pass
            
            # Add ELK handler if enabled (this is a placeholder)
            if logging_config.get("elk", {}).get("enabled", False):
                # In a real implementation, we would create a handler
                # that sends logs to ELK (Elasticsearch)
                # For now, we'll just note that it's not implemented
                pass
            
            # Configure structlog if enabled
            if self._enable_structlog:
                self._configure_structlog()
            
            # Register for config changes
            self._config_manager.register_listener("logging", self._on_config_changed)
            
            # Make sure handlers are closed on exit
            atexit.register(self.shutdown)
            
            # Log successful initialization
            self._root_logger.info(
                "Logging Manager initialized",
                extra={"manager": "LoggingManager", "event": "initialization"},
            )
            
            self._initialized = True
            self._healthy = True
        
        except Exception as e:
            raise ManagerInitializationError(
                f"Failed to initialize LoggingManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def _create_json_formatter(self) -> logging.Formatter:
        """Create a JSON formatter for log records.
        
        Returns:
            logging.Formatter: A formatter that outputs logs in JSON format.
        """
        return jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
            json_ensure_ascii=False,
        )
    
    def _configure_structlog(self) -> None:
        """Configure structlog for structured logging."""
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )
    
    def get_logger(self, name: str) -> Union[logging.Logger, Any]:
        """Get a logger for a specific component.
        
        Args:
            name: The name of the component requesting a logger.
            
        Returns:
            Union[logging.Logger, Any]: A logger instance configured for the component.
            If structlog is enabled, returns a structured logger.
        """
        if not self._initialized:
            # Return a minimal logger before initialization
            return logging.getLogger(name)
        
        if self._enable_structlog:
            return structlog.get_logger(name)
        else:
            return logging.getLogger(name)
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for logging.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        if not key.startswith("logging."):
            return
        
        # Get the specific part that changed
        sub_key = key.split(".", 1)[1] if "." in key else ""
        
        if sub_key == "level" or key == "logging":
            # Update the root logger level
            log_level_str = value.lower() if isinstance(value, str) else "info"
            log_level = self.LOG_LEVELS.get(log_level_str, logging.INFO)
            if self._root_logger:
                self._root_logger.setLevel(log_level)
                
                # Also update file handler if it exists
                if self._file_handler:
                    self._file_handler.setLevel(log_level)
        
        elif sub_key.startswith("console.") and self._console_handler:
            if sub_key.endswith(".level"):
                # Update console handler level
                log_level_str = value.lower() if isinstance(value, str) else "info"
                log_level = self.LOG_LEVELS.get(log_level_str, logging.INFO)
                self._console_handler.setLevel(log_level)
            
            elif sub_key.endswith(".enabled"):
                # Enable/disable console handler
                if not value and self._console_handler in self._root_logger.handlers:
                    self._root_logger.removeHandler(self._console_handler)
                elif value and self._console_handler not in self._root_logger.handlers:
                    self._root_logger.addHandler(self._console_handler)
        
        elif sub_key.startswith("file.") and self._file_handler:
            if sub_key.endswith(".level"):
                # Update file handler level
                log_level_str = value.lower() if isinstance(value, str) else "info"
                log_level = self.LOG_LEVELS.get(log_level_str, logging.INFO)
                self._file_handler.setLevel(log_level)
            
            elif sub_key.endswith(".enabled"):
                # Enable/disable file handler
                if not value and self._file_handler in self._root_logger.handlers:
                    self._root_logger.removeHandler(self._file_handler)
                elif value and self._file_handler not in self._root_logger.handlers:
                    self._root_logger.addHandler(self._file_handler)
        
        # In a more complete implementation, we'd handle database and ELK handler
        # configuration changes as well
    
    def shutdown(self) -> None:
        """Shut down the Logging Manager.
        
        Closes all log handlers and performs any necessary cleanup.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            # Log shutdown
            if self._root_logger:
                self._root_logger.info(
                    "Shutting down Logging Manager",
                    extra={"manager": "LoggingManager", "event": "shutdown"},
                )
            
            # Close all handlers
            for handler in self._handlers:
                try:
                    handler.flush()
                    handler.close()
                except Exception:
                    # Just continue if a handler fails to close
                    pass
            
            # Unregister config listener
            self._config_manager.unregister_listener("logging", self._on_config_changed)
            
            # Unregister atexit handler
            atexit.unregister(self.shutdown)
            
            self._initialized = False
            self._healthy = False
        
        except Exception as e:
            raise ManagerShutdownError(
                f"Failed to shut down LoggingManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the Logging Manager.
        
        Returns:
            Dict[str, Any]: Status information about the Logging Manager.
        """
        status = super().status()
        
        if self._initialized:
            status.update({
                "log_directory": str(self._log_directory) if self._log_directory else None,
                "handlers": {
                    "console": self._console_handler is not None and
                              self._console_handler in self._root_logger.handlers
                              if self._root_logger else False,
                    "file": self._file_handler is not None and
                           self._file_handler in self._root_logger.handlers
                           if self._root_logger else False,
                    "database": self._database_handler is not None,
                    "elk": self._elk_handler is not None,
                },
                "structured_logging": self._enable_structlog,
            })
        
        return status
