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
    def __init__(self, config_path: Optional[str]=None) -> None:
        self._config_path = config_path
        self._managers: Dict[str, NexusManager] = {}
        self._initialized = False
        self._logger = None
    def initialize(self) -> None:
        try:
            config_manager = ConfigManager(config_path=self._config_path)
            config_manager.initialize()
            self._managers['config'] = config_manager
            logging_manager = LoggingManager(config_manager)
            logging_manager.initialize()
            self._managers['logging'] = logging_manager
            self._logger = logging_manager.get_logger('app_core')
            self._logger.info('Starting Nexus Core initialization')
            event_bus_manager = EventBusManager(config_manager, logging_manager)
            event_bus_manager.initialize()
            self._managers['event_bus'] = event_bus_manager
            self._setup_signal_handlers()
            atexit.register(self.shutdown)
            self._initialized = True
            self._logger.info('Nexus Core initialization complete')
        except Exception as e:
            if self._logger:
                self._logger.error(f'Initialization failed: {str(e)}')
                self._logger.debug(f'Initialization error details: {traceback.format_exc()}')
            self.shutdown()
            if isinstance(e, NexusError):
                raise
            else:
                raise ManagerInitializationError(f'Failed to initialize Nexus Core: {str(e)}', manager_name='ApplicationCore') from e
    def _setup_signal_handlers(self) -> None:
        if sys.platform != 'win32':
            signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    def _signal_handler(self, sig: int, frame: Any) -> None:
        if self._logger:
            self._logger.info(f'Received signal {sig}, shutting down')
        self.shutdown()
        sys.exit(0)
    def get_manager(self, name: str) -> Optional[NexusManager]:
        return self._managers.get(name)
    def shutdown(self) -> None:
        if not self._initialized and (not self._managers):
            return
        if self._logger:
            self._logger.info('Shutting down Nexus Core')
        managers = list(self._managers.items())
        managers.reverse()
        for name, manager in managers:
            try:
                if manager.initialized:
                    if self._logger:
                        self._logger.debug(f'Shutting down {name} manager')
                    manager.shutdown()
            except Exception as e:
                if self._logger:
                    self._logger.error(f'Error shutting down {name} manager: {str(e)}')
        self._managers.clear()
        self._initialized = False
        try:
            atexit.unregister(self.shutdown)
        except:
            pass
        if self._logger:
            self._logger.info('Nexus Core shutdown complete')
            self._logger = None
    def status(self) -> Dict[str, Any]:
        status = {'name': 'ApplicationCore', 'initialized': self._initialized, 'managers': {}}
        for name, manager in self._managers.items():
            try:
                status['managers'][name] = manager.status()
            except Exception as e:
                status['managers'][name] = {'error': f'Failed to get status: {str(e)}', 'initialized': manager.initialized, 'healthy': False}
        return status