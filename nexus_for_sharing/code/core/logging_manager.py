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
    LOG_LEVELS = {'debug': logging.DEBUG, 'info': logging.INFO, 'warning': logging.WARNING, 'error': logging.ERROR, 'critical': logging.CRITICAL}
    def __init__(self, config_manager: Any) -> None:
        super().__init__(name='LoggingManager')
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
        try:
            logging_config = self._config_manager.get('logging', {})
            log_level_str = logging_config.get('level', 'INFO').lower()
            log_level = self.LOG_LEVELS.get(log_level_str, logging.INFO)
            log_format = logging_config.get('format', 'json').lower()
            if logging_config.get('file', {}).get('enabled', True):
                log_file_path = logging_config.get('file', {}).get('path', 'logs/nexus_core.log')
                self._log_directory = pathlib.Path(log_file_path).parent
                os.makedirs(self._log_directory, exist_ok=True)
            self._root_logger = logging.getLogger()
            self._root_logger.setLevel(log_level)
            for handler in list(self._root_logger.handlers):
                self._root_logger.removeHandler(handler)
            if log_format == 'json':
                self._enable_structlog = True
                formatter = self._create_json_formatter()
            else:
                formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            if logging_config.get('console', {}).get('enabled', True):
                console_level_str = logging_config.get('console', {}).get('level', 'INFO').lower()
                console_level = self.LOG_LEVELS.get(console_level_str, logging.INFO)
                self._console_handler = logging.StreamHandler(sys.stdout)
                self._console_handler.setLevel(console_level)
                self._console_handler.setFormatter(formatter)
                self._root_logger.addHandler(self._console_handler)
                self._handlers.append(self._console_handler)
            if logging_config.get('file', {}).get('enabled', True):
                file_path = logging_config.get('file', {}).get('path', 'logs/nexus_core.log')
                rotation = logging_config.get('file', {}).get('rotation', '10 MB')
                retention = logging_config.get('file', {}).get('retention', '30 days')
                if isinstance(rotation, str) and 'MB' in rotation:
                    max_bytes = int(rotation.split()[0]) * 1024 * 1024
                else:
                    max_bytes = 10 * 1024 * 1024
                if isinstance(retention, str) and 'days' in retention:
                    backup_count = int(retention.split()[0])
                else:
                    backup_count = 30
                self._file_handler = logging.handlers.RotatingFileHandler(file_path, maxBytes=max_bytes, backupCount=backup_count)
                self._file_handler.setLevel(log_level)
                self._file_handler.setFormatter(formatter)
                self._root_logger.addHandler(self._file_handler)
                self._handlers.append(self._file_handler)
            if logging_config.get('database', {}).get('enabled', False):
                pass
            if logging_config.get('elk', {}).get('enabled', False):
                pass
            if self._enable_structlog:
                self._configure_structlog()
            self._config_manager.register_listener('logging', self._on_config_changed)
            atexit.register(self.shutdown)
            self._root_logger.info('Logging Manager initialized', extra={'manager': 'LoggingManager', 'event': 'initialization'})
            self._initialized = True
            self._healthy = True
        except Exception as e:
            raise ManagerInitializationError(f'Failed to initialize LoggingManager: {str(e)}', manager_name=self.name) from e
    def _create_json_formatter(self) -> logging.Formatter:
        return jsonlogger.JsonFormatter(fmt='%(asctime)s %(name)s %(levelname)s %(message)s', datefmt='%Y-%m-%dT%H:%M:%S%z', json_ensure_ascii=False)
    def _configure_structlog(self) -> None:
        structlog.configure(processors=[structlog.stdlib.filter_by_level, structlog.processors.TimeStamper(fmt='iso'), structlog.stdlib.add_logger_name, structlog.stdlib.add_log_level, structlog.processors.StackInfoRenderer(), structlog.processors.format_exc_info, structlog.processors.UnicodeDecoder(), structlog.stdlib.ProcessorFormatter.wrap_for_formatter], context_class=dict, logger_factory=structlog.stdlib.LoggerFactory(), wrapper_class=structlog.stdlib.BoundLogger, cache_logger_on_first_use=True)
    def get_logger(self, name: str) -> Union[logging.Logger, Any]:
        if not self._initialized:
            return logging.getLogger(name)
        if self._enable_structlog:
            return structlog.get_logger(name)
        else:
            return logging.getLogger(name)
    def _on_config_changed(self, key: str, value: Any) -> None:
        if not key.startswith('logging.'):
            return
        sub_key = key.split('.', 1)[1] if '.' in key else ''
        if sub_key == 'level' or key == 'logging':
            log_level_str = value.lower() if isinstance(value, str) else 'info'
            log_level = self.LOG_LEVELS.get(log_level_str, logging.INFO)
            if self._root_logger:
                self._root_logger.setLevel(log_level)
                if self._file_handler:
                    self._file_handler.setLevel(log_level)
        elif sub_key.startswith('console.') and self._console_handler:
            if sub_key.endswith('.level'):
                log_level_str = value.lower() if isinstance(value, str) else 'info'
                log_level = self.LOG_LEVELS.get(log_level_str, logging.INFO)
                self._console_handler.setLevel(log_level)
            elif sub_key.endswith('.enabled'):
                if not value and self._console_handler in self._root_logger.handlers:
                    self._root_logger.removeHandler(self._console_handler)
                elif value and self._console_handler not in self._root_logger.handlers:
                    self._root_logger.addHandler(self._console_handler)
        elif sub_key.startswith('file.') and self._file_handler:
            if sub_key.endswith('.level'):
                log_level_str = value.lower() if isinstance(value, str) else 'info'
                log_level = self.LOG_LEVELS.get(log_level_str, logging.INFO)
                self._file_handler.setLevel(log_level)
            elif sub_key.endswith('.enabled'):
                if not value and self._file_handler in self._root_logger.handlers:
                    self._root_logger.removeHandler(self._file_handler)
                elif value and self._file_handler not in self._root_logger.handlers:
                    self._root_logger.addHandler(self._file_handler)
    def shutdown(self) -> None:
        if not self._initialized:
            return
        try:
            if self._root_logger:
                self._root_logger.info('Shutting down Logging Manager', extra={'manager': 'LoggingManager', 'event': 'shutdown'})
            for handler in self._handlers:
                try:
                    handler.flush()
                    handler.close()
                except Exception:
                    pass
            self._config_manager.unregister_listener('logging', self._on_config_changed)
            atexit.unregister(self.shutdown)
            self._initialized = False
            self._healthy = False
        except Exception as e:
            raise ManagerShutdownError(f'Failed to shut down LoggingManager: {str(e)}', manager_name=self.name) from e
    def status(self) -> Dict[str, Any]:
        status = super().status()
        if self._initialized:
            status.update({'log_directory': str(self._log_directory) if self._log_directory else None, 'handlers': {'console': self._console_handler is not None and self._console_handler in self._root_logger.handlers if self._root_logger else False, 'file': self._file_handler is not None and self._file_handler in self._root_logger.handlers if self._root_logger else False, 'database': self._database_handler is not None, 'elk': self._elk_handler is not None}, 'structured_logging': self._enable_structlog})
        return status