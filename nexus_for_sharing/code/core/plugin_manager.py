from __future__ import annotations
import importlib
import importlib.metadata
import importlib.util
import inspect
import os
import pathlib
import pkgutil
import sys
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union, cast
from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import ManagerInitializationError, ManagerShutdownError, PluginError
class PluginState(Enum):
    DISCOVERED = 'discovered'
    LOADED = 'loaded'
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    FAILED = 'failed'
    DISABLED = 'disabled'
@dataclass
class PluginInfo:
    name: str
    version: str
    description: str
    author: str
    state: PluginState = PluginState.DISCOVERED
    dependencies: List[str] = None
    path: Optional[str] = None
    instance: Optional[Any] = None
    error: Optional[str] = None
    load_time: Optional[float] = None
    metadata: Dict[str, Any] = None
    def __post_init__(self) -> None:
        if self.dependencies is None:
            self.dependencies = []
        if self.metadata is None:
            self.metadata = {}
class PluginManager(NexusManager):
    def __init__(self, config_manager: Any, logger_manager: Any, event_bus_manager: Any, file_manager: Any) -> None:
        super().__init__(name='PluginManager')
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger('plugin_manager')
        self._event_bus = event_bus_manager
        self._file_manager = file_manager
        self._plugins: Dict[str, PluginInfo] = {}
        self._plugin_dir: Optional[pathlib.Path] = None
        self._entry_point_group = 'nexus_core.plugins'
        self._auto_load = True
        self._enabled_plugins: List[str] = []
        self._disabled_plugins: List[str] = []
    def initialize(self) -> None:
        try:
            plugin_config = self._config_manager.get('plugins', {})
            plugin_dir = plugin_config.get('directory', 'plugins')
            self._plugin_dir = pathlib.Path(plugin_dir)
            self._auto_load = plugin_config.get('autoload', True)
            self._enabled_plugins = plugin_config.get('enabled', [])
            self._disabled_plugins = plugin_config.get('disabled', [])
            os.makedirs(self._plugin_dir, exist_ok=True)
            self._event_bus.subscribe(event_type='plugin/install', callback=self._on_plugin_install_event, subscriber_id='plugin_manager')
            self._event_bus.subscribe(event_type='plugin/uninstall', callback=self._on_plugin_uninstall_event, subscriber_id='plugin_manager')
            self._event_bus.subscribe(event_type='plugin/enable', callback=self._on_plugin_enable_event, subscriber_id='plugin_manager')
            self._event_bus.subscribe(event_type='plugin/disable', callback=self._on_plugin_disable_event, subscriber_id='plugin_manager')
            self._discover_entry_point_plugins()
            self._discover_directory_plugins()
            self._config_manager.register_listener('plugins', self._on_config_changed)
            if self._auto_load:
                self._load_enabled_plugins()
            self._logger.info(f'Plugin Manager initialized with {len(self._plugins)} plugins discovered')
            self._initialized = True
            self._healthy = True
            self._event_bus.publish(event_type='plugin_manager/initialized', source='plugin_manager', payload={'plugin_count': len(self._plugins)})
        except Exception as e:
            self._logger.error(f'Failed to initialize Plugin Manager: {str(e)}')
            raise ManagerInitializationError(f'Failed to initialize PluginManager: {str(e)}', manager_name=self.name) from e
    def _discover_entry_point_plugins(self) -> None:
        try:
            entry_points = importlib.metadata.entry_points().get(self._entry_point_group, [])
            for entry_point in entry_points:
                try:
                    plugin_class = entry_point.load()
                    plugin_info = self._extract_plugin_metadata(plugin_class, entry_point.name, entry_point_name=entry_point.name)
                    self._plugins[plugin_info.name] = plugin_info
                    self._logger.debug(f"Discovered plugin '{plugin_info.name}' from entry point", extra={'plugin': plugin_info.name, 'version': plugin_info.version})
                except Exception as e:
                    self._logger.error(f"Failed to discover plugin from entry point '{entry_point.name}': {str(e)}", extra={'entry_point': entry_point.name})
        except Exception as e:
            self._logger.error(f'Failed to discover entry point plugins: {str(e)}')
    def _discover_directory_plugins(self) -> None:
        if not self._plugin_dir or not self._plugin_dir.exists():
            self._logger.warning(f'Plugin directory does not exist: {self._plugin_dir}')
            return
        plugin_dir_str = str(self._plugin_dir.absolute())
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)
        try:
            for item in self._plugin_dir.iterdir():
                if not item.is_dir():
                    continue
                init_file = item / '__init__.py'
                plugin_file = item / 'plugin.py'
                if init_file.exists() or plugin_file.exists():
                    try:
                        module_name = item.name
                        if init_file.exists():
                            module = importlib.import_module(module_name)
                        elif plugin_file.exists():
                            spec = importlib.util.spec_from_file_location(f'{module_name}.plugin', plugin_file)
                            if not spec or not spec.loader:
                                continue
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)
                        else:
                            continue
                        plugin_class = self._find_plugin_class(module)
                        if not plugin_class:
                            self._logger.warning(f'No plugin class found in {module_name}', extra={'module': module_name})
                            continue
                        plugin_info = self._extract_plugin_metadata(plugin_class, module_name, path=str(item))
                        if plugin_info.name not in self._plugins:
                            self._plugins[plugin_info.name] = plugin_info
                            self._logger.debug(f"Discovered plugin '{plugin_info.name}' from directory", extra={'plugin': plugin_info.name, 'version': plugin_info.version, 'path': str(item)})
                    except Exception as e:
                        self._logger.error(f"Failed to discover plugin from directory '{item.name}': {str(e)}", extra={'directory': str(item)})
        except Exception as e:
            self._logger.error(f'Failed to discover directory plugins: {str(e)}')
    def _find_plugin_class(self, module: Any) -> Optional[Type]:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if hasattr(obj, 'name') and hasattr(obj, 'version') and hasattr(obj, 'description'):
                return obj
        return None
    def _extract_plugin_metadata(self, plugin_class: Type, default_name: str, path: Optional[str]=None, entry_point_name: Optional[str]=None) -> PluginInfo:
        name = getattr(plugin_class, 'name', default_name)
        version = getattr(plugin_class, 'version', '0.1.0')
        description = getattr(plugin_class, 'description', 'No description')
        author = getattr(plugin_class, 'author', 'Unknown')
        dependencies = getattr(plugin_class, 'dependencies', [])
        plugin_info = PluginInfo(name=name, version=version, description=description, author=author, state=PluginState.DISCOVERED, dependencies=dependencies, path=path, metadata={'class': plugin_class.__name__, 'module': plugin_class.__module__, 'entry_point': entry_point_name})
        return plugin_info
    def _load_enabled_plugins(self) -> None:
        for plugin_name, plugin_info in self._plugins.items():
            if not plugin_info.dependencies and self._is_plugin_enabled(plugin_name):
                self.load_plugin(plugin_name)
        for plugin_name, plugin_info in self._plugins.items():
            if plugin_info.dependencies and self._is_plugin_enabled(plugin_name):
                self.load_plugin(plugin_name)
    def _is_plugin_enabled(self, plugin_name: str) -> bool:
        if plugin_name in self._disabled_plugins:
            return False
        if plugin_name in self._enabled_plugins:
            return True
        return self._auto_load
    def load_plugin(self, plugin_name: str) -> bool:
        if not self._initialized:
            raise PluginError('Plugin Manager not initialized', plugin_name=plugin_name)
        if plugin_name not in self._plugins:
            raise PluginError(f"Plugin '{plugin_name}' not found", plugin_name=plugin_name)
        plugin_info = self._plugins[plugin_name]
        if plugin_info.state in (PluginState.LOADED, PluginState.ACTIVE):
            self._logger.debug(f"Plugin '{plugin_name}' is already loaded", extra={'plugin': plugin_name})
            return True
        if plugin_name in self._disabled_plugins:
            self._logger.warning(f"Plugin '{plugin_name}' is disabled and cannot be loaded", extra={'plugin': plugin_name})
            return False
        for dependency in plugin_info.dependencies:
            if dependency == 'core':
                continue
            if dependency not in self._plugins:
                plugin_info.state = PluginState.FAILED
                plugin_info.error = f"Dependency '{dependency}' not found"
                self._logger.error(f"Failed to load plugin '{plugin_name}': Dependency '{dependency}' not found", extra={'plugin': plugin_name, 'dependency': dependency})
                return False
            dependency_info = self._plugins[dependency]
            if dependency_info.state not in (PluginState.LOADED, PluginState.ACTIVE):
                if not self.load_plugin(dependency):
                    plugin_info.state = PluginState.FAILED
                    plugin_info.error = f"Failed to load dependency '{dependency}'"
                    self._logger.error(f"Failed to load plugin '{plugin_name}': Dependency '{dependency}' could not be loaded", extra={'plugin': plugin_name, 'dependency': dependency})
                    return False
        try:
            plugin_class = self._get_plugin_class(plugin_info)
            plugin_info.instance = plugin_class()
            if hasattr(plugin_info.instance, 'initialize'):
                plugin_info.instance.initialize(self._event_bus, self._logger._logger_manager, self._config_manager)
            plugin_info.state = PluginState.ACTIVE
            plugin_info.load_time = time.time()
            self._logger.info(f"Loaded plugin '{plugin_name}' v{plugin_info.version}", extra={'plugin': plugin_name, 'version': plugin_info.version})
            self._event_bus.publish(event_type='plugin/loaded', source='plugin_manager', payload={'plugin_name': plugin_name, 'version': plugin_info.version, 'description': plugin_info.description, 'author': plugin_info.author})
            return True
        except Exception as e:
            plugin_info.state = PluginState.FAILED
            plugin_info.error = str(e)
            self._logger.error(f"Failed to load plugin '{plugin_name}': {str(e)}", extra={'plugin': plugin_name, 'error': str(e)})
            self._event_bus.publish(event_type='plugin/error', source='plugin_manager', payload={'plugin_name': plugin_name, 'error': str(e)})
            raise PluginError(f"Failed to load plugin '{plugin_name}': {str(e)}", plugin_name=plugin_name) from e
    def unload_plugin(self, plugin_name: str) -> bool:
        if not self._initialized:
            raise PluginError('Plugin Manager not initialized', plugin_name=plugin_name)
        if plugin_name not in self._plugins:
            raise PluginError(f"Plugin '{plugin_name}' not found", plugin_name=plugin_name)
        plugin_info = self._plugins[plugin_name]
        if plugin_info.state not in (PluginState.LOADED, PluginState.ACTIVE):
            self._logger.debug(f"Plugin '{plugin_name}' is not loaded", extra={'plugin': plugin_name})
            return True
        for other_name, other_info in self._plugins.items():
            if other_name != plugin_name and plugin_name in other_info.dependencies and (other_info.state in (PluginState.LOADED, PluginState.ACTIVE)):
                self._logger.warning(f"Cannot unload plugin '{plugin_name}': Plugin '{other_name}' depends on it", extra={'plugin': plugin_name, 'dependent': other_name})
                return False
        try:
            if plugin_info.instance and hasattr(plugin_info.instance, 'shutdown'):
                plugin_info.instance.shutdown()
            plugin_info.state = PluginState.INACTIVE
            plugin_info.instance = None
            self._logger.info(f"Unloaded plugin '{plugin_name}'", extra={'plugin': plugin_name})
            self._event_bus.publish(event_type='plugin/unloaded', source='plugin_manager', payload={'plugin_name': plugin_name})
            return True
        except Exception as e:
            self._logger.error(f"Failed to unload plugin '{plugin_name}': {str(e)}", extra={'plugin': plugin_name, 'error': str(e)})
            self._event_bus.publish(event_type='plugin/error', source='plugin_manager', payload={'plugin_name': plugin_name, 'error': str(e)})
            raise PluginError(f"Failed to unload plugin '{plugin_name}': {str(e)}", plugin_name=plugin_name) from e
    def reload_plugin(self, plugin_name: str) -> bool:
        if not self._initialized:
            raise PluginError('Plugin Manager not initialized', plugin_name=plugin_name)
        try:
            if not self.unload_plugin(plugin_name):
                return False
            plugin_info = self._plugins[plugin_name]
            if plugin_info.metadata.get('module'):
                module_name = plugin_info.metadata['module']
                if '.' in module_name:
                    base_module_name = module_name.split('.')[0]
                else:
                    base_module_name = module_name
                if base_module_name in sys.modules:
                    importlib.reload(sys.modules[base_module_name])
            return self.load_plugin(plugin_name)
        except Exception as e:
            self._logger.error(f"Failed to reload plugin '{plugin_name}': {str(e)}", extra={'plugin': plugin_name, 'error': str(e)})
            self._event_bus.publish(event_type='plugin/error', source='plugin_manager', payload={'plugin_name': plugin_name, 'error': str(e)})
            raise PluginError(f"Failed to reload plugin '{plugin_name}': {str(e)}", plugin_name=plugin_name) from e
    def enable_plugin(self, plugin_name: str) -> bool:
        if not self._initialized:
            raise PluginError('Plugin Manager not initialized', plugin_name=plugin_name)
        if plugin_name not in self._plugins:
            raise PluginError(f"Plugin '{plugin_name}' not found", plugin_name=plugin_name)
        if plugin_name in self._disabled_plugins:
            self._disabled_plugins.remove(plugin_name)
        if plugin_name not in self._enabled_plugins:
            self._enabled_plugins.append(plugin_name)
        self._config_manager.set('plugins.enabled', self._enabled_plugins)
        self._config_manager.set('plugins.disabled', self._disabled_plugins)
        self._logger.info(f"Enabled plugin '{plugin_name}'", extra={'plugin': plugin_name})
        self._event_bus.publish(event_type='plugin/enabled', source='plugin_manager', payload={'plugin_name': plugin_name})
        return True
    def disable_plugin(self, plugin_name: str) -> bool:
        if not self._initialized:
            raise PluginError('Plugin Manager not initialized', plugin_name=plugin_name)
        if plugin_name not in self._plugins:
            raise PluginError(f"Plugin '{plugin_name}' not found", plugin_name=plugin_name)
        plugin_info = self._plugins[plugin_name]
        if plugin_info.state in (PluginState.LOADED, PluginState.ACTIVE):
            if not self.unload_plugin(plugin_name):
                raise PluginError(f"Cannot disable plugin '{plugin_name}': Failed to unload it", plugin_name=plugin_name)
        if plugin_name in self._enabled_plugins:
            self._enabled_plugins.remove(plugin_name)
        if plugin_name not in self._disabled_plugins:
            self._disabled_plugins.append(plugin_name)
        plugin_info.state = PluginState.DISABLED
        self._config_manager.set('plugins.enabled', self._enabled_plugins)
        self._config_manager.set('plugins.disabled', self._disabled_plugins)
        self._logger.info(f"Disabled plugin '{plugin_name}'", extra={'plugin': plugin_name})
        self._event_bus.publish(event_type='plugin/disabled', source='plugin_manager', payload={'plugin_name': plugin_name})
        return True
    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        if not self._initialized or plugin_name not in self._plugins:
            return None
        plugin_info = self._plugins[plugin_name]
        result = {'name': plugin_info.name, 'version': plugin_info.version, 'description': plugin_info.description, 'author': plugin_info.author, 'state': plugin_info.state.value, 'dependencies': plugin_info.dependencies, 'path': plugin_info.path, 'error': plugin_info.error, 'load_time': plugin_info.load_time, 'metadata': plugin_info.metadata, 'enabled': self._is_plugin_enabled(plugin_name)}
        return result
    def get_all_plugins(self) -> List[Dict[str, Any]]:
        if not self._initialized:
            return []
        return [self.get_plugin_info(plugin_name) for plugin_name in self._plugins]
    def get_active_plugins(self) -> List[Dict[str, Any]]:
        if not self._initialized:
            return []
        return [self.get_plugin_info(plugin_name) for plugin_name, plugin_info in self._plugins.items() if plugin_info.state == PluginState.ACTIVE]
    def _get_plugin_class(self, plugin_info: PluginInfo) -> Type:
        module_name = plugin_info.metadata.get('module')
        class_name = plugin_info.metadata.get('class')
        if not module_name or not class_name:
            raise PluginError(f"Invalid plugin metadata for '{plugin_info.name}'", plugin_name=plugin_info.name)
        try:
            module = importlib.import_module(module_name)
            plugin_class = getattr(module, class_name)
            return plugin_class
        except Exception as e:
            raise PluginError(f"Failed to get plugin class for '{plugin_info.name}': {str(e)}", plugin_name=plugin_info.name) from e
    def _on_plugin_install_event(self, event: Any) -> None:
        payload = event.payload
        plugin_path = payload.get('path')
        if not plugin_path:
            self._logger.error('Invalid plugin installation event: Missing path', extra={'event_id': event.event_id})
            return
        try:
            self._logger.warning('Plugin installation from path not implemented yet', extra={'path': plugin_path})
        except Exception as e:
            self._logger.error(f'Failed to install plugin: {str(e)}', extra={'path': plugin_path, 'error': str(e)})
    def _on_plugin_uninstall_event(self, event: Any) -> None:
        payload = event.payload
        plugin_name = payload.get('plugin_name')
        if not plugin_name:
            self._logger.error('Invalid plugin uninstallation event: Missing plugin_name', extra={'event_id': event.event_id})
            return
        try:
            self._logger.warning('Plugin uninstallation not implemented yet', extra={'plugin': plugin_name})
        except Exception as e:
            self._logger.error(f"Failed to uninstall plugin '{plugin_name}': {str(e)}", extra={'plugin': plugin_name, 'error': str(e)})
    def _on_plugin_enable_event(self, event: Any) -> None:
        payload = event.payload
        plugin_name = payload.get('plugin_name')
        if not plugin_name:
            self._logger.error('Invalid plugin enable event: Missing plugin_name', extra={'event_id': event.event_id})
            return
        try:
            success = self.enable_plugin(plugin_name)
            if success:
                self.load_plugin(plugin_name)
        except Exception as e:
            self._logger.error(f"Failed to enable plugin '{plugin_name}': {str(e)}", extra={'plugin': plugin_name, 'error': str(e)})
    def _on_plugin_disable_event(self, event: Any) -> None:
        payload = event.payload
        plugin_name = payload.get('plugin_name')
        if not plugin_name:
            self._logger.error('Invalid plugin disable event: Missing plugin_name', extra={'event_id': event.event_id})
            return
        try:
            self.disable_plugin(plugin_name)
        except Exception as e:
            self._logger.error(f"Failed to disable plugin '{plugin_name}': {str(e)}", extra={'plugin': plugin_name, 'error': str(e)})
    def _on_config_changed(self, key: str, value: Any) -> None:
        if key == 'plugins.autoload':
            self._auto_load = value
            self._logger.info(f'Plugin autoload set to {value}', extra={'autoload': value})
        elif key == 'plugins.enabled':
            self._enabled_plugins = value
            self._logger.info(f'Updated enabled plugins list: {value}', extra={'enabled': value})
        elif key == 'plugins.disabled':
            self._disabled_plugins = value
            self._logger.info(f'Updated disabled plugins list: {value}', extra={'disabled': value})
        elif key == 'plugins.directory':
            self._logger.warning('Changing plugin directory requires restart to take effect', extra={'directory': value})
    def shutdown(self) -> None:
        if not self._initialized:
            return
        try:
            self._logger.info('Shutting down Plugin Manager')
            active_plugins = [name for name, info in self._plugins.items() if info.state in (PluginState.LOADED, PluginState.ACTIVE)]
            sorted_plugins = []
            remaining_plugins = active_plugins.copy()
            for plugin_name in active_plugins:
                if not any((plugin_name in self._plugins[other].dependencies for other in active_plugins if other != plugin_name)):
                    sorted_plugins.append(plugin_name)
                    remaining_plugins.remove(plugin_name)
            sorted_plugins.extend(remaining_plugins)
            sorted_plugins.reverse()
            for plugin_name in sorted_plugins:
                try:
                    self.unload_plugin(plugin_name)
                except Exception as e:
                    self._logger.error(f"Error unloading plugin '{plugin_name}' during shutdown: {str(e)}", extra={'plugin': plugin_name, 'error': str(e)})
            if self._event_bus:
                self._event_bus.unsubscribe('plugin_manager')
            self._config_manager.unregister_listener('plugins', self._on_config_changed)
            self._initialized = False
            self._healthy = False
            self._logger.info('Plugin Manager shut down successfully')
        except Exception as e:
            self._logger.error(f'Failed to shut down Plugin Manager: {str(e)}')
            raise ManagerShutdownError(f'Failed to shut down PluginManager: {str(e)}', manager_name=self.name) from e
    def status(self) -> Dict[str, Any]:
        status = super().status()
        if self._initialized:
            plugin_counts = {state.value: 0 for state in PluginState}
            for plugin_info in self._plugins.values():
                plugin_counts[plugin_info.state.value] += 1
            status.update({'plugins': {'total': len(self._plugins), 'active': plugin_counts[PluginState.ACTIVE.value], 'loaded': plugin_counts[PluginState.LOADED.value], 'failed': plugin_counts[PluginState.FAILED.value], 'disabled': plugin_counts[PluginState.DISABLED.value]}, 'config': {'auto_load': self._auto_load, 'plugin_dir': str(self._plugin_dir) if self._plugin_dir else None, 'enabled_count': len(self._enabled_plugins), 'disabled_count': len(self._disabled_plugins)}})
        return status