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
    """Possible states of a plugin."""
    
    DISCOVERED = "discovered"  # Plugin found but not loaded
    LOADED = "loaded"  # Plugin successfully loaded
    ACTIVE = "active"  # Plugin initialized and running
    INACTIVE = "inactive"  # Plugin loaded but not active
    FAILED = "failed"  # Plugin failed to load
    DISABLED = "disabled"  # Plugin manually disabled


@dataclass
class PluginInfo:
    """Information about a plugin."""
    
    name: str  # Unique identifier for the plugin
    version: str  # Plugin version
    description: str  # Plugin description
    author: str  # Plugin author
    state: PluginState = PluginState.DISCOVERED  # Current state of the plugin
    dependencies: List[str] = None  # List of plugin dependencies
    path: Optional[str] = None  # Path to the plugin module or package
    instance: Optional[Any] = None  # Instance of the plugin class
    error: Optional[str] = None  # Error message if plugin failed to load
    load_time: Optional[float] = None  # When the plugin was loaded
    metadata: Dict[str, Any] = None  # Additional plugin metadata
    
    def __post_init__(self) -> None:
        """Initialize default values for mutable types."""
        if self.dependencies is None:
            self.dependencies = []
        
        if self.metadata is None:
            self.metadata = {}


class PluginManager(NexusManager):
    """Manages plugin discovery, loading, and lifecycle.
    
    The Plugin Manager is responsible for finding, loading, and managing plugins
    that extend the functionality of Nexus Core. It handles plugin dependencies,
    versioning, and hot-loading of plugins at runtime.
    """
    
    def __init__(
        self,
        config_manager: Any,
        logger_manager: Any,
        event_bus_manager: Any,
        file_manager: Any,
    ) -> None:
        """Initialize the Plugin Manager.
        
        Args:
            config_manager: The Configuration Manager to use for plugin settings.
            logger_manager: The Logging Manager to use for logging.
            event_bus_manager: The Event Bus Manager for event-based communication.
            file_manager: The File Manager for file operations.
        """
        super().__init__(name="PluginManager")
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger("plugin_manager")
        self._event_bus = event_bus_manager
        self._file_manager = file_manager
        
        # Plugin registry
        self._plugins: Dict[str, PluginInfo] = {}
        
        # Plugin directory path
        self._plugin_dir: Optional[pathlib.Path] = None
        
        # Plugin entry points
        self._entry_point_group = "nexus_core.plugins"
        
        # Configuration
        self._auto_load = True  # Automatically load discovered plugins
        self._enabled_plugins: List[str] = []  # List of explicitly enabled plugins
        self._disabled_plugins: List[str] = []  # List of explicitly disabled plugins
    
    def initialize(self) -> None:
        """Initialize the Plugin Manager.
        
        Discovers plugins from entry points and the plugin directory, and loads enabled plugins.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Get configuration
            plugin_config = self._config_manager.get("plugins", {})
            
            plugin_dir = plugin_config.get("directory", "plugins")
            self._plugin_dir = pathlib.Path(plugin_dir)
            self._auto_load = plugin_config.get("autoload", True)
            self._enabled_plugins = plugin_config.get("enabled", [])
            self._disabled_plugins = plugin_config.get("disabled", [])
            
            # Create plugin directory if it doesn't exist
            os.makedirs(self._plugin_dir, exist_ok=True)
            
            # Subscribe to plugin-related events
            self._event_bus.subscribe(
                event_type="plugin/install",
                callback=self._on_plugin_install_event,
                subscriber_id="plugin_manager"
            )
            
            self._event_bus.subscribe(
                event_type="plugin/uninstall",
                callback=self._on_plugin_uninstall_event,
                subscriber_id="plugin_manager"
            )
            
            self._event_bus.subscribe(
                event_type="plugin/enable",
                callback=self._on_plugin_enable_event,
                subscriber_id="plugin_manager"
            )
            
            self._event_bus.subscribe(
                event_type="plugin/disable",
                callback=self._on_plugin_disable_event,
                subscriber_id="plugin_manager"
            )
            
            # Discover plugins from entry points
            self._discover_entry_point_plugins()
            
            # Discover plugins from plugin directory
            self._discover_directory_plugins()
            
            # Register for config changes
            self._config_manager.register_listener("plugins", self._on_config_changed)
            
            # Load enabled plugins
            if self._auto_load:
                self._load_enabled_plugins()
            
            self._logger.info(
                f"Plugin Manager initialized with {len(self._plugins)} plugins discovered"
            )
            self._initialized = True
            self._healthy = True
            
            # Publish initialization event
            self._event_bus.publish(
                event_type="plugin_manager/initialized",
                source="plugin_manager",
                payload={"plugin_count": len(self._plugins)},
            )
        
        except Exception as e:
            self._logger.error(f"Failed to initialize Plugin Manager: {str(e)}")
            raise ManagerInitializationError(
                f"Failed to initialize PluginManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def _discover_entry_point_plugins(self) -> None:
        """Discover plugins from entry points.
        
        This allows for plugins to be installed as Python packages with entry points.
        """
        try:
            # Get entry points for plugins
            entry_points = importlib.metadata.entry_points().get(self._entry_point_group, [])
            
            for entry_point in entry_points:
                try:
                    # Get plugin class or module
                    plugin_class = entry_point.load()
                    
                    # Get plugin metadata
                    plugin_info = self._extract_plugin_metadata(
                        plugin_class, 
                        entry_point.name,
                        entry_point_name=entry_point.name,
                    )
                    
                    # Add to registry
                    self._plugins[plugin_info.name] = plugin_info
                    
                    self._logger.debug(
                        f"Discovered plugin '{plugin_info.name}' from entry point",
                        extra={"plugin": plugin_info.name, "version": plugin_info.version},
                    )
                
                except Exception as e:
                    self._logger.error(
                        f"Failed to discover plugin from entry point '{entry_point.name}': {str(e)}",
                        extra={"entry_point": entry_point.name},
                    )
        
        except Exception as e:
            self._logger.error(f"Failed to discover entry point plugins: {str(e)}")
    
    def _discover_directory_plugins(self) -> None:
        """Discover plugins from the plugin directory.
        
        This allows for plugins to be added by placing them in the plugin directory.
        """
        if not self._plugin_dir or not self._plugin_dir.exists():
            self._logger.warning(f"Plugin directory does not exist: {self._plugin_dir}")
            return
        
        # Add plugin directory to Python path if not already there
        plugin_dir_str = str(self._plugin_dir.absolute())
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)
        
        try:
            # Iterate through directories in the plugin directory
            for item in self._plugin_dir.iterdir():
                if not item.is_dir():
                    continue
                
                # Check if this is a potential plugin package
                init_file = item / "__init__.py"
                plugin_file = item / "plugin.py"
                
                if init_file.exists() or plugin_file.exists():
                    try:
                        # Try to import the plugin module
                        module_name = item.name
                        
                        if init_file.exists():
                            # Import as a package
                            module = importlib.import_module(module_name)
                        elif plugin_file.exists():
                            # Import the plugin.py file
                            spec = importlib.util.spec_from_file_location(
                                f"{module_name}.plugin", 
                                plugin_file
                            )
                            if not spec or not spec.loader:
                                continue
                            
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)
                        else:
                            continue
                        
                        # Look for a plugin class in the module
                        plugin_class = self._find_plugin_class(module)
                        if not plugin_class:
                            self._logger.warning(
                                f"No plugin class found in {module_name}",
                                extra={"module": module_name},
                            )
                            continue
                        
                        # Get plugin metadata
                        plugin_info = self._extract_plugin_metadata(
                            plugin_class, 
                            module_name,
                            path=str(item),
                        )
                        
                        # Add to registry if not already discovered from entry point
                        if plugin_info.name not in self._plugins:
                            self._plugins[plugin_info.name] = plugin_info
                            
                            self._logger.debug(
                                f"Discovered plugin '{plugin_info.name}' from directory",
                                extra={
                                    "plugin": plugin_info.name, 
                                    "version": plugin_info.version,
                                    "path": str(item),
                                },
                            )
                    
                    except Exception as e:
                        self._logger.error(
                            f"Failed to discover plugin from directory '{item.name}': {str(e)}",
                            extra={"directory": str(item)},
                        )
        
        except Exception as e:
            self._logger.error(f"Failed to discover directory plugins: {str(e)}")
    
    def _find_plugin_class(self, module: Any) -> Optional[Type]:
        """Find a plugin class in a module.
        
        A plugin class should have name, version, and description attributes.
        
        Args:
            module: The module to search for a plugin class.
            
        Returns:
            Optional[Type]: The plugin class if found, None otherwise.
        """
        # Look for classes in the module
        for _, obj in inspect.getmembers(module, inspect.isclass):
            # Check if the class has the required attributes
            if (
                hasattr(obj, "name") 
                and hasattr(obj, "version") 
                and hasattr(obj, "description")
            ):
                return obj
        
        return None
    
    def _extract_plugin_metadata(
        self, 
        plugin_class: Type, 
        default_name: str,
        path: Optional[str] = None,
        entry_point_name: Optional[str] = None,
    ) -> PluginInfo:
        """Extract metadata from a plugin class.
        
        Args:
            plugin_class: The plugin class.
            default_name: Default name to use if not specified in the class.
            path: Optional path to the plugin.
            entry_point_name: Optional entry point name.
            
        Returns:
            PluginInfo: Metadata about the plugin.
        """
        # Get metadata from the class
        name = getattr(plugin_class, "name", default_name)
        version = getattr(plugin_class, "version", "0.1.0")
        description = getattr(plugin_class, "description", "No description")
        author = getattr(plugin_class, "author", "Unknown")
        dependencies = getattr(plugin_class, "dependencies", [])
        
        # Create plugin info
        plugin_info = PluginInfo(
            name=name,
            version=version,
            description=description,
            author=author,
            state=PluginState.DISCOVERED,
            dependencies=dependencies,
            path=path,
            metadata={
                "class": plugin_class.__name__,
                "module": plugin_class.__module__,
                "entry_point": entry_point_name,
            },
        )
        
        return plugin_info
    
    def _load_enabled_plugins(self) -> None:
        """Load all enabled plugins.
        
        This loads plugins that are enabled by default or explicitly enabled in config.
        """
        # First, load plugins with no dependencies
        for plugin_name, plugin_info in self._plugins.items():
            if not plugin_info.dependencies and self._is_plugin_enabled(plugin_name):
                self.load_plugin(plugin_name)
        
        # Then, load plugins with dependencies
        for plugin_name, plugin_info in self._plugins.items():
            if plugin_info.dependencies and self._is_plugin_enabled(plugin_name):
                self.load_plugin(plugin_name)
    
    def _is_plugin_enabled(self, plugin_name: str) -> bool:
        """Check if a plugin is enabled.
        
        A plugin is enabled if it's in the enabled list or if auto-load is True
        and it's not in the disabled list.
        
        Args:
            plugin_name: The name of the plugin to check.
            
        Returns:
            bool: True if the plugin is enabled, False otherwise.
        """
        if plugin_name in self._disabled_plugins:
            return False
        
        if plugin_name in self._enabled_plugins:
            return True
        
        return self._auto_load
    
    def load_plugin(self, plugin_name: str) -> bool:
        """Load and initialize a plugin.
        
        Args:
            plugin_name: The name of the plugin to load.
            
        Returns:
            bool: True if the plugin was loaded successfully, False otherwise.
            
        Raises:
            PluginError: If the plugin cannot be loaded.
        """
        if not self._initialized:
            raise PluginError(
                "Plugin Manager not initialized",
                plugin_name=plugin_name,
            )
        
        # Check if plugin exists
        if plugin_name not in self._plugins:
            raise PluginError(
                f"Plugin '{plugin_name}' not found",
                plugin_name=plugin_name,
            )
        
        plugin_info = self._plugins[plugin_name]
        
        # Check if plugin is already loaded
        if plugin_info.state in (PluginState.LOADED, PluginState.ACTIVE):
            self._logger.debug(
                f"Plugin '{plugin_name}' is already loaded",
                extra={"plugin": plugin_name},
            )
            return True
        
        # Check if plugin is explicitly disabled
        if plugin_name in self._disabled_plugins:
            self._logger.warning(
                f"Plugin '{plugin_name}' is disabled and cannot be loaded",
                extra={"plugin": plugin_name},
            )
            return False
        
        # Check dependencies
        for dependency in plugin_info.dependencies:
            # Skip if dependency is "core" (assumed to be the core application)
            if dependency == "core":
                continue
                
            # Check if dependency exists
            if dependency not in self._plugins:
                plugin_info.state = PluginState.FAILED
                plugin_info.error = f"Dependency '{dependency}' not found"
                self._logger.error(
                    f"Failed to load plugin '{plugin_name}': Dependency '{dependency}' not found",
                    extra={"plugin": plugin_name, "dependency": dependency},
                )
                return False
            
            # Check if dependency is loaded
            dependency_info = self._plugins[dependency]
            if dependency_info.state not in (PluginState.LOADED, PluginState.ACTIVE):
                # Try to load the dependency
                if not self.load_plugin(dependency):
                    plugin_info.state = PluginState.FAILED
                    plugin_info.error = f"Failed to load dependency '{dependency}'"
                    self._logger.error(
                        f"Failed to load plugin '{plugin_name}': Dependency '{dependency}' could not be loaded",
                        extra={"plugin": plugin_name, "dependency": dependency},
                    )
                    return False
        
        try:
            # Create an instance of the plugin class
            plugin_class = self._get_plugin_class(plugin_info)
            plugin_info.instance = plugin_class()
            
            # Initialize the plugin
            if hasattr(plugin_info.instance, "initialize"):
                plugin_info.instance.initialize(
                    self._event_bus,
                    self._logger._logger_manager,
                    self._config_manager,
                )
            
            # Update plugin state
            plugin_info.state = PluginState.ACTIVE
            plugin_info.load_time = time.time()
            
            self._logger.info(
                f"Loaded plugin '{plugin_name}' v{plugin_info.version}",
                extra={"plugin": plugin_name, "version": plugin_info.version},
            )
            
            # Publish plugin loaded event
            self._event_bus.publish(
                event_type="plugin/loaded",
                source="plugin_manager",
                payload={
                    "plugin_name": plugin_name,
                    "version": plugin_info.version,
                    "description": plugin_info.description,
                    "author": plugin_info.author,
                },
            )
            
            return True
        
        except Exception as e:
            plugin_info.state = PluginState.FAILED
            plugin_info.error = str(e)
            
            self._logger.error(
                f"Failed to load plugin '{plugin_name}': {str(e)}",
                extra={"plugin": plugin_name, "error": str(e)},
            )
            
            # Publish plugin error event
            self._event_bus.publish(
                event_type="plugin/error",
                source="plugin_manager",
                payload={
                    "plugin_name": plugin_name,
                    "error": str(e),
                },
            )
            
            raise PluginError(
                f"Failed to load plugin '{plugin_name}': {str(e)}",
                plugin_name=plugin_name,
            ) from e
    
    def unload_plugin(self, plugin_name: str) -> bool:
        """Unload a plugin, calling its shutdown method if available.
        
        Args:
            plugin_name: The name of the plugin to unload.
            
        Returns:
            bool: True if the plugin was unloaded successfully, False otherwise.
            
        Raises:
            PluginError: If the plugin cannot be unloaded.
        """
        if not self._initialized:
            raise PluginError(
                "Plugin Manager not initialized",
                plugin_name=plugin_name,
            )
        
        # Check if plugin exists
        if plugin_name not in self._plugins:
            raise PluginError(
                f"Plugin '{plugin_name}' not found",
                plugin_name=plugin_name,
            )
        
        plugin_info = self._plugins[plugin_name]
        
        # Check if plugin is loaded
        if plugin_info.state not in (PluginState.LOADED, PluginState.ACTIVE):
            self._logger.debug(
                f"Plugin '{plugin_name}' is not loaded",
                extra={"plugin": plugin_name},
            )
            return True
        
        # Check if other plugins depend on this one
        for other_name, other_info in self._plugins.items():
            if (
                other_name != plugin_name 
                and plugin_name in other_info.dependencies
                and other_info.state in (PluginState.LOADED, PluginState.ACTIVE)
            ):
                self._logger.warning(
                    f"Cannot unload plugin '{plugin_name}': Plugin '{other_name}' depends on it",
                    extra={"plugin": plugin_name, "dependent": other_name},
                )
                return False
        
        try:
            # Call the plugin's shutdown method if available
            if plugin_info.instance and hasattr(plugin_info.instance, "shutdown"):
                plugin_info.instance.shutdown()
            
            # Update plugin state
            plugin_info.state = PluginState.INACTIVE
            plugin_info.instance = None
            
            self._logger.info(
                f"Unloaded plugin '{plugin_name}'",
                extra={"plugin": plugin_name},
            )
            
            # Publish plugin unloaded event
            self._event_bus.publish(
                event_type="plugin/unloaded",
                source="plugin_manager",
                payload={"plugin_name": plugin_name},
            )
            
            return True
        
        except Exception as e:
            self._logger.error(
                f"Failed to unload plugin '{plugin_name}': {str(e)}",
                extra={"plugin": plugin_name, "error": str(e)},
            )
            
            # Publish plugin error event
            self._event_bus.publish(
                event_type="plugin/error",
                source="plugin_manager",
                payload={
                    "plugin_name": plugin_name,
                    "error": str(e),
                },
            )
            
            raise PluginError(
                f"Failed to unload plugin '{plugin_name}': {str(e)}",
                plugin_name=plugin_name,
            ) from e
    
    def reload_plugin(self, plugin_name: str) -> bool:
        """Reload a plugin by unloading and then loading it again.
        
        Args:
            plugin_name: The name of the plugin to reload.
            
        Returns:
            bool: True if the plugin was reloaded successfully, False otherwise.
            
        Raises:
            PluginError: If the plugin cannot be reloaded.
        """
        if not self._initialized:
            raise PluginError(
                "Plugin Manager not initialized",
                plugin_name=plugin_name,
            )
        
        try:
            # Unload the plugin
            if not self.unload_plugin(plugin_name):
                return False
            
            # Reload the plugin's module
            plugin_info = self._plugins[plugin_name]
            if plugin_info.metadata.get("module"):
                module_name = plugin_info.metadata["module"]
                
                # Get base module name (before the first dot)
                if "." in module_name:
                    base_module_name = module_name.split(".")[0]
                else:
                    base_module_name = module_name
                
                # Reload the module
                if base_module_name in sys.modules:
                    importlib.reload(sys.modules[base_module_name])
            
            # Load the plugin again
            return self.load_plugin(plugin_name)
        
        except Exception as e:
            self._logger.error(
                f"Failed to reload plugin '{plugin_name}': {str(e)}",
                extra={"plugin": plugin_name, "error": str(e)},
            )
            
            # Publish plugin error event
            self._event_bus.publish(
                event_type="plugin/error",
                source="plugin_manager",
                payload={
                    "plugin_name": plugin_name,
                    "error": str(e),
                },
            )
            
            raise PluginError(
                f"Failed to reload plugin '{plugin_name}': {str(e)}",
                plugin_name=plugin_name,
            ) from e
    
    def enable_plugin(self, plugin_name: str) -> bool:
        """Enable a plugin so it can be loaded.
        
        Args:
            plugin_name: The name of the plugin to enable.
            
        Returns:
            bool: True if the plugin was enabled, False otherwise.
            
        Raises:
            PluginError: If the plugin cannot be enabled.
        """
        if not self._initialized:
            raise PluginError(
                "Plugin Manager not initialized",
                plugin_name=plugin_name,
            )
        
        # Check if plugin exists
        if plugin_name not in self._plugins:
            raise PluginError(
                f"Plugin '{plugin_name}' not found",
                plugin_name=plugin_name,
            )
        
        # Remove from disabled list if present
        if plugin_name in self._disabled_plugins:
            self._disabled_plugins.remove(plugin_name)
        
        # Add to enabled list if not already there
        if plugin_name not in self._enabled_plugins:
            self._enabled_plugins.append(plugin_name)
        
        # Update configuration
        self._config_manager.set("plugins.enabled", self._enabled_plugins)
        self._config_manager.set("plugins.disabled", self._disabled_plugins)
        
        self._logger.info(
            f"Enabled plugin '{plugin_name}'",
            extra={"plugin": plugin_name},
        )
        
        # Publish plugin enabled event
        self._event_bus.publish(
            event_type="plugin/enabled",
            source="plugin_manager",
            payload={"plugin_name": plugin_name},
        )
        
        return True
    
    def disable_plugin(self, plugin_name: str) -> bool:
        """Disable a plugin so it won't be loaded.
        
        Args:
            plugin_name: The name of the plugin to disable.
            
        Returns:
            bool: True if the plugin was disabled, False otherwise.
            
        Raises:
            PluginError: If the plugin cannot be disabled.
        """
        if not self._initialized:
            raise PluginError(
                "Plugin Manager not initialized",
                plugin_name=plugin_name,
            )
        
        # Check if plugin exists
        if plugin_name not in self._plugins:
            raise PluginError(
                f"Plugin '{plugin_name}' not found",
                plugin_name=plugin_name,
            )
        
        # Unload the plugin if it's loaded
        plugin_info = self._plugins[plugin_name]
        if plugin_info.state in (PluginState.LOADED, PluginState.ACTIVE):
            if not self.unload_plugin(plugin_name):
                raise PluginError(
                    f"Cannot disable plugin '{plugin_name}': Failed to unload it",
                    plugin_name=plugin_name,
                )
        
        # Remove from enabled list if present
        if plugin_name in self._enabled_plugins:
            self._enabled_plugins.remove(plugin_name)
        
        # Add to disabled list if not already there
        if plugin_name not in self._disabled_plugins:
            self._disabled_plugins.append(plugin_name)
        
        # Update plugin state
        plugin_info.state = PluginState.DISABLED
        
        # Update configuration
        self._config_manager.set("plugins.enabled", self._enabled_plugins)
        self._config_manager.set("plugins.disabled", self._disabled_plugins)
        
        self._logger.info(
            f"Disabled plugin '{plugin_name}'",
            extra={"plugin": plugin_name},
        )
        
        # Publish plugin disabled event
        self._event_bus.publish(
            event_type="plugin/disabled",
            source="plugin_manager",
            payload={"plugin_name": plugin_name},
        )
        
        return True
    
    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a plugin.
        
        Args:
            plugin_name: The name of the plugin.
            
        Returns:
            Optional[Dict[str, Any]]: Information about the plugin, or None if not found.
        """
        if not self._initialized or plugin_name not in self._plugins:
            return None
        
        plugin_info = self._plugins[plugin_name]
        
        # Convert to a dictionary
        result = {
            "name": plugin_info.name,
            "version": plugin_info.version,
            "description": plugin_info.description,
            "author": plugin_info.author,
            "state": plugin_info.state.value,
            "dependencies": plugin_info.dependencies,
            "path": plugin_info.path,
            "error": plugin_info.error,
            "load_time": plugin_info.load_time,
            "metadata": plugin_info.metadata,
            "enabled": self._is_plugin_enabled(plugin_name),
        }
        
        return result
    
    def get_all_plugins(self) -> List[Dict[str, Any]]:
        """Get information about all discovered plugins.
        
        Returns:
            List[Dict[str, Any]]: List of plugin information dictionaries.
        """
        if not self._initialized:
            return []
        
        return [
            self.get_plugin_info(plugin_name) for plugin_name in self._plugins
        ]
    
    def get_active_plugins(self) -> List[Dict[str, Any]]:
        """Get information about all active plugins.
        
        Returns:
            List[Dict[str, Any]]: List of active plugin information dictionaries.
        """
        if not self._initialized:
            return []
        
        return [
            self.get_plugin_info(plugin_name)
            for plugin_name, plugin_info in self._plugins.items()
            if plugin_info.state == PluginState.ACTIVE
        ]
    
    def _get_plugin_class(self, plugin_info: PluginInfo) -> Type:
        """Get the plugin class from a plugin info object.
        
        Args:
            plugin_info: The plugin info.
            
        Returns:
            Type: The plugin class.
            
        Raises:
            PluginError: If the plugin class cannot be found.
        """
        # Get the module name from metadata
        module_name = plugin_info.metadata.get("module")
        class_name = plugin_info.metadata.get("class")
        
        if not module_name or not class_name:
            raise PluginError(
                f"Invalid plugin metadata for '{plugin_info.name}'",
                plugin_name=plugin_info.name,
            )
        
        try:
            # Import the module
            module = importlib.import_module(module_name)
            
            # Get the class from the module
            plugin_class = getattr(module, class_name)
            
            return plugin_class
        
        except Exception as e:
            raise PluginError(
                f"Failed to get plugin class for '{plugin_info.name}': {str(e)}",
                plugin_name=plugin_info.name,
            ) from e
    
    def _on_plugin_install_event(self, event: Any) -> None:
        """Handle plugin installation events.
        
        Args:
            event: The plugin installation event.
        """
        payload = event.payload
        plugin_path = payload.get("path")
        
        if not plugin_path:
            self._logger.error(
                "Invalid plugin installation event: Missing path",
                extra={"event_id": event.event_id},
            )
            return
        
        try:
            # TODO: Implement plugin installation from a path
            self._logger.warning(
                "Plugin installation from path not implemented yet",
                extra={"path": plugin_path},
            )
        
        except Exception as e:
            self._logger.error(
                f"Failed to install plugin: {str(e)}",
                extra={"path": plugin_path, "error": str(e)},
            )
    
    def _on_plugin_uninstall_event(self, event: Any) -> None:
        """Handle plugin uninstallation events.
        
        Args:
            event: The plugin uninstallation event.
        """
        payload = event.payload
        plugin_name = payload.get("plugin_name")
        
        if not plugin_name:
            self._logger.error(
                "Invalid plugin uninstallation event: Missing plugin_name",
                extra={"event_id": event.event_id},
            )
            return
        
        try:
            # TODO: Implement plugin uninstallation
            self._logger.warning(
                "Plugin uninstallation not implemented yet",
                extra={"plugin": plugin_name},
            )
        
        except Exception as e:
            self._logger.error(
                f"Failed to uninstall plugin '{plugin_name}': {str(e)}",
                extra={"plugin": plugin_name, "error": str(e)},
            )
    
    def _on_plugin_enable_event(self, event: Any) -> None:
        """Handle plugin enable events.
        
        Args:
            event: The plugin enable event.
        """
        payload = event.payload
        plugin_name = payload.get("plugin_name")
        
        if not plugin_name:
            self._logger.error(
                "Invalid plugin enable event: Missing plugin_name",
                extra={"event_id": event.event_id},
            )
            return
        
        try:
            # Enable the plugin
            success = self.enable_plugin(plugin_name)
            
            # Try to load it if enabled successfully
            if success:
                self.load_plugin(plugin_name)
        
        except Exception as e:
            self._logger.error(
                f"Failed to enable plugin '{plugin_name}': {str(e)}",
                extra={"plugin": plugin_name, "error": str(e)},
            )
    
    def _on_plugin_disable_event(self, event: Any) -> None:
        """Handle plugin disable events.
        
        Args:
            event: The plugin disable event.
        """
        payload = event.payload
        plugin_name = payload.get("plugin_name")
        
        if not plugin_name:
            self._logger.error(
                "Invalid plugin disable event: Missing plugin_name",
                extra={"event_id": event.event_id},
            )
            return
        
        try:
            # Disable the plugin
            self.disable_plugin(plugin_name)
        
        except Exception as e:
            self._logger.error(
                f"Failed to disable plugin '{plugin_name}': {str(e)}",
                extra={"plugin": plugin_name, "error": str(e)},
            )
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for plugins.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        if key == "plugins.autoload":
            self._auto_load = value
            self._logger.info(
                f"Plugin autoload set to {value}",
                extra={"autoload": value},
            )
        
        elif key == "plugins.enabled":
            self._enabled_plugins = value
            self._logger.info(
                f"Updated enabled plugins list: {value}",
                extra={"enabled": value},
            )
        
        elif key == "plugins.disabled":
            self._disabled_plugins = value
            self._logger.info(
                f"Updated disabled plugins list: {value}",
                extra={"disabled": value},
            )
        
        elif key == "plugins.directory":
            self._logger.warning(
                "Changing plugin directory requires restart to take effect",
                extra={"directory": value},
            )
    
    def shutdown(self) -> None:
        """Shut down the Plugin Manager.
        
        Unloads all active plugins and cleans up resources.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            self._logger.info("Shutting down Plugin Manager")
            
            # Unload all active plugins in reverse dependency order
            active_plugins = [
                name for name, info in self._plugins.items()
                if info.state in (PluginState.LOADED, PluginState.ACTIVE)
            ]
            
            # Sort by dependencies (plugins with no dependencies first)
            # This is a simplified approach, not a full topological sort
            sorted_plugins = []
            remaining_plugins = active_plugins.copy()
            
            # First, add plugins that no other plugins depend on
            for plugin_name in active_plugins:
                if not any(plugin_name in self._plugins[other].dependencies for other in active_plugins if other != plugin_name):
                    sorted_plugins.append(plugin_name)
                    remaining_plugins.remove(plugin_name)
            
            # Then add the rest in any order
            sorted_plugins.extend(remaining_plugins)
            
            # Reverse the list so plugins with dependencies are unloaded first
            sorted_plugins.reverse()
            
            # Unload each plugin
            for plugin_name in sorted_plugins:
                try:
                    self.unload_plugin(plugin_name)
                except Exception as e:
                    self._logger.error(
                        f"Error unloading plugin '{plugin_name}' during shutdown: {str(e)}",
                        extra={"plugin": plugin_name, "error": str(e)},
                    )
            
            # Unregister event subscribers
            if self._event_bus:
                self._event_bus.unsubscribe("plugin_manager")
            
            # Unregister config listener
            self._config_manager.unregister_listener("plugins", self._on_config_changed)
            
            self._initialized = False
            self._healthy = False
            
            self._logger.info("Plugin Manager shut down successfully")
        
        except Exception as e:
            self._logger.error(f"Failed to shut down Plugin Manager: {str(e)}")
            raise ManagerShutdownError(
                f"Failed to shut down PluginManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the Plugin Manager.
        
        Returns:
            Dict[str, Any]: Status information about the Plugin Manager.
        """
        status = super().status()
        
        if self._initialized:
            # Count plugins by state
            plugin_counts = {state.value: 0 for state in PluginState}
            for plugin_info in self._plugins.values():
                plugin_counts[plugin_info.state.value] += 1
            
            status.update({
                "plugins": {
                    "total": len(self._plugins),
                    "active": plugin_counts[PluginState.ACTIVE.value],
                    "loaded": plugin_counts[PluginState.LOADED.value],
                    "failed": plugin_counts[PluginState.FAILED.value],
                    "disabled": plugin_counts[PluginState.DISABLED.value],
                },
                "config": {
                    "auto_load": self._auto_load,
                    "plugin_dir": str(self._plugin_dir) if self._plugin_dir else None,
                    "enabled_count": len(self._enabled_plugins),
                    "disabled_count": len(self._disabled_plugins),
                },
            })
        
        return status
