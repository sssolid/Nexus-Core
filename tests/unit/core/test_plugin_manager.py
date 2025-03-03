"""Unit tests for the Plugin Manager."""

import os
import sys
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from nexus_core.core.plugin_manager import PluginManager, PluginState
from nexus_core.utils.exceptions import PluginError


# Define a simple test plugin class
class TestPlugin:
    name = "test_plugin"
    version = "0.1.0"
    description = "Test plugin for unit tests"
    author = "Tester"
    dependencies = []
    
    def __init__(self):
        self._initialized = False
        self._event_bus = None
        self._logger = None
        self._config = None
    
    def initialize(self, event_bus, logger_provider, config_provider):
        self._event_bus = event_bus
        self._logger = logger_provider.get_logger(f"plugin.{self.name}")
        self._config = config_provider
        self._initialized = True
    
    def shutdown(self):
        self._initialized = False


@pytest.fixture
def temp_plugin_dir():
    """Create a temporary plugin directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def plugin_config(temp_plugin_dir):
    """Create a plugin configuration for testing."""
    return {
        "directory": temp_plugin_dir,
        "autoload": True,
        "enabled": ["test_plugin"],
        "disabled": []
    }


@pytest.fixture
def config_manager_mock(plugin_config):
    """Create a mock ConfigManager for the PluginManager."""
    config_manager = MagicMock()
    config_manager.get.return_value = plugin_config
    return config_manager


@pytest.fixture
def event_bus_mock():
    """Create a mock EventBusManager."""
    event_bus = MagicMock()
    return event_bus


@pytest.fixture
def file_manager_mock():
    """Create a mock FileManager."""
    file_manager = MagicMock()
    return file_manager


@pytest.fixture
def plugin_manager(config_manager_mock, event_bus_mock, file_manager_mock):
    """Create a PluginManager for testing."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    plugin_mgr = PluginManager(config_manager_mock, logger_manager, event_bus_mock, file_manager_mock)
    
    # Mock the plugin discovery to inject our test plugin
    original_extract = plugin_mgr._extract_plugin_metadata
    
    def mock_extract_metadata(plugin_class, default_name, **kwargs):
        if plugin_class == TestPlugin:
            plugin_info = original_extract(plugin_class, default_name, **kwargs)
            return plugin_info
        return original_extract(plugin_class, default_name, **kwargs)
    
    plugin_mgr._extract_plugin_metadata = mock_extract_metadata
    
    # Add test plugin to plugins dictionary
    def init_with_test_plugin():
        plugin_mgr.initialize()
        plugin_info = plugin_mgr._extract_plugin_metadata(TestPlugin, "test_plugin")
        plugin_mgr._plugins["test_plugin"] = plugin_info
    
    init_with_test_plugin()
    
    yield plugin_mgr
    plugin_mgr.shutdown()


def test_plugin_manager_initialization(config_manager_mock, event_bus_mock, file_manager_mock):
    """Test that the PluginManager initializes correctly."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    plugin_mgr = PluginManager(config_manager_mock, logger_manager, event_bus_mock, file_manager_mock)
    plugin_mgr.initialize()
    
    assert plugin_mgr.initialized
    assert plugin_mgr.healthy
    
    # Event bus subscriptions should be set up
    event_bus_mock.subscribe.assert_called()
    
    plugin_mgr.shutdown()
    assert not plugin_mgr.initialized


def test_load_plugin(plugin_manager):
    """Test loading a plugin."""
    # Should already be in the plugins dict from the fixture
    assert "test_plugin" in plugin_manager._plugins
    
    # Load the plugin
    result = plugin_manager.load_plugin("test_plugin")
    assert result is True
    
    # Check plugin state
    plugin_info = plugin_manager._plugins["test_plugin"]
    assert plugin_info.state == PluginState.ACTIVE
    assert plugin_info.instance is not None
    
    # Event should have been published
    plugin_manager._event_bus.publish.assert_called_with(
        event_type="plugin/loaded",
        source="plugin_manager",
        payload={"plugin_name": "test_plugin", "version": "0.1.0", 
                "description": "Test plugin for unit tests", "author": "Tester"}
    )


def test_unload_plugin(plugin_manager):
    """Test unloading a plugin."""
    # First load the plugin
    plugin_manager.load_plugin("test_plugin")
    
    # Then unload it
    result = plugin_manager.unload_plugin("test_plugin")
    assert result is True
    
    # Check plugin state
    plugin_info = plugin_manager._plugins["test_plugin"]
    assert plugin_info.state == PluginState.INACTIVE
    assert plugin_info.instance is None
    
    # Event should have been published
    plugin_manager._event_bus.publish.assert_called_with(
        event_type="plugin/unloaded",
        source="plugin_manager",
        payload={"plugin_name": "test_plugin"}
    )


def test_reload_plugin(plugin_manager):
    """Test reloading a plugin."""
    # First load the plugin
    plugin_manager.load_plugin("test_plugin")
    
    # Then reload it
    result = plugin_manager.reload_plugin("test_plugin")
    assert result is True
    
    # Check plugin state
    plugin_info = plugin_manager._plugins["test_plugin"]
    assert plugin_info.state == PluginState.ACTIVE
    assert plugin_info.instance is not None


def test_enable_disable_plugin(plugin_manager):
    """Test enabling and disabling a plugin."""
    # Start with enabling a plugin
    result = plugin_manager.enable_plugin("test_plugin")
    assert result is True
    assert "test_plugin" in plugin_manager._enabled_plugins
    assert "test_plugin" not in plugin_manager._disabled_plugins
    
    # Now disable it
    result = plugin_manager.disable_plugin("test_plugin")
    assert result is True
    assert "test_plugin" not in plugin_manager._enabled_plugins
    assert "test_plugin" in plugin_manager._disabled_plugins
    
    # Check plugin state
    plugin_info = plugin_manager._plugins["test_plugin"]
    assert plugin_info.state == PluginState.DISABLED


def test_get_plugin_info(plugin_manager):
    """Test getting plugin information."""
    # Load the plugin
    plugin_manager.load_plugin("test_plugin")
    
    # Get plugin info
    info = plugin_manager.get_plugin_info("test_plugin")
    assert info is not None
    assert info["name"] == "test_plugin"
    assert info["version"] == "0.1.0"
    assert info["description"] == "Test plugin for unit tests"
    assert info["author"] == "Tester"
    assert info["state"] == PluginState.ACTIVE.value
    assert info["enabled"] is True


def test_get_all_plugins(plugin_manager):
    """Test getting all plugins."""
    plugins = plugin_manager.get_all_plugins()
    assert len(plugins) == 1
    assert plugins[0]["name"] == "test_plugin"


def test_get_active_plugins(plugin_manager):
    """Test getting active plugins."""
    # Initially no plugins are active
    active_plugins = plugin_manager.get_active_plugins()
    assert len(active_plugins) == 0
    
    # Load the plugin
    plugin_manager.load_plugin("test_plugin")
    
    # Now we should have one active plugin
    active_plugins = plugin_manager.get_active_plugins()
    assert len(active_plugins) == 1
    assert active_plugins[0]["name"] == "test_plugin"


def test_plugin_with_dependencies(plugin_manager):
    """Test loading a plugin with dependencies."""
    # Create a plugin with dependencies
    class PluginWithDeps:
        name = "plugin_with_deps"
        version = "0.1.0"
        description = "Plugin with dependencies"
        author = "Tester"
        dependencies = ["test_plugin"]
        
        def __init__(self):
            self._initialized = False
        
        def initialize(self, event_bus, logger_provider, config_provider):
            self._initialized = True
        
        def shutdown(self):
            self._initialized = False
    
    # Add the plugin to the manager
    plugin_info = plugin_manager._extract_plugin_metadata(PluginWithDeps, "plugin_with_deps")
    plugin_manager._plugins["plugin_with_deps"] = plugin_info
    
    # Loading this plugin should automatically load the dependency
    result = plugin_manager.load_plugin("plugin_with_deps")
    assert result is True
    
    # Both plugins should be active
    assert plugin_manager._plugins["test_plugin"].state == PluginState.ACTIVE
    assert plugin_manager._plugins["plugin_with_deps"].state == PluginState.ACTIVE


def test_plugin_with_missing_dependency(plugin_manager):
    """Test loading a plugin with a missing dependency."""
    # Create a plugin with a non-existent dependency
    class PluginWithMissingDep:
        name = "plugin_with_missing_dep"
        version = "0.1.0"
        description = "Plugin with missing dependency"
        author = "Tester"
        dependencies = ["nonexistent_plugin"]
        
        def __init__(self):
            pass
        
        def initialize(self, event_bus, logger_provider, config_provider):
            pass
        
        def shutdown(self):
            pass
    
    # Add the plugin to the manager
    plugin_info = plugin_manager._extract_plugin_metadata(PluginWithMissingDep, "plugin_with_missing_dep")
    plugin_manager._plugins["plugin_with_missing_dep"] = plugin_info
    
    # Loading should fail due to missing dependency
    result = plugin_manager.load_plugin("plugin_with_missing_dep")
    assert result is False
    
    # Plugin should be in FAILED state
    assert plugin_manager._plugins["plugin_with_missing_dep"].state == PluginState.FAILED


def test_dependent_plugin_unload_prevention(plugin_manager):
    """Test that you can't unload a plugin when others depend on it."""
    # Create a plugin with dependencies
    class PluginWithDeps:
        name = "plugin_with_deps"
        version = "0.1.0"
        description = "Plugin with dependencies"
        author = "Tester"
        dependencies = ["test_plugin"]
        
        def __init__(self):
            self._initialized = False
        
        def initialize(self, event_bus, logger_provider, config_provider):
            self._initialized = True
        
        def shutdown(self):
            self._initialized = False
    
    # Add and load both plugins
    plugin_info = plugin_manager._extract_plugin_metadata(PluginWithDeps, "plugin_with_deps")
    plugin_manager._plugins["plugin_with_deps"] = plugin_info
    plugin_manager.load_plugin("test_plugin")
    plugin_manager.load_plugin("plugin_with_deps")
    
    # Trying to unload test_plugin should fail
    result = plugin_manager.unload_plugin("test_plugin")
    assert result is False
    
    # test_plugin should still be active
    assert plugin_manager._plugins["test_plugin"].state == PluginState.ACTIVE


def test_plugin_manager_events(plugin_manager):
    """Test that plugin manager publishes events correctly."""
    # Reset the event_bus mock to clear previous calls
    plugin_manager._event_bus.reset_mock()
    
    # Load a plugin
    plugin_manager.load_plugin("test_plugin")
    
    # Verify the loaded event was published
    plugin_manager._event_bus.publish.assert_called_with(
        event_type="plugin/loaded",
        source="plugin_manager",
        payload={"plugin_name": "test_plugin", "version": "0.1.0", 
                "description": "Test plugin for unit tests", "author": "Tester"}
    )
    
    # Reset the mock
    plugin_manager._event_bus.reset_mock()
    
    # Unload the plugin
    plugin_manager.unload_plugin("test_plugin")
    
    # Verify the unloaded event was published
    plugin_manager._event_bus.publish.assert_called_with(
        event_type="plugin/unloaded",
        source="plugin_manager",
        payload={"plugin_name": "test_plugin"}
    )


def test_plugin_manager_status(plugin_manager):
    """Test getting status from PluginManager."""
    # Load the test plugin
    plugin_manager.load_plugin("test_plugin")
    
    status = plugin_manager.status()
    
    assert status["name"] == "PluginManager"
    assert status["initialized"] is True
    assert "plugins" in status
    assert status["plugins"]["active"] == 1
    assert "config" in status


def test_operations_without_initialization():
    """Test plugin operations before initialization."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    plugin_mgr = PluginManager(MagicMock(), logger_manager, MagicMock(), MagicMock())
    
    with pytest.raises(PluginError):
        plugin_mgr.load_plugin("test_plugin")
