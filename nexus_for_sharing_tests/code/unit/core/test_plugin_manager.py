import os
import sys
import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from nexus_core.core.plugin_manager import PluginManager, PluginState
from nexus_core.utils.exceptions import PluginError
class TestPlugin:
    name = 'test_plugin'
    version = '0.1.0'
    description = 'Test plugin for unit tests'
    author = 'Tester'
    dependencies = []
    def __init__(self):
        self._initialized = False
        self._event_bus = None
        self._logger = None
        self._config = None
    def initialize(self, event_bus, logger_provider, config_provider):
        self._event_bus = event_bus
        self._logger = logger_provider.get_logger(f'plugin.{self.name}')
        self._config = config_provider
        self._initialized = True
    def shutdown(self):
        self._initialized = False
@pytest.fixture
def temp_plugin_dir():
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)
@pytest.fixture
def plugin_config(temp_plugin_dir):
    return {'directory': temp_plugin_dir, 'autoload': True, 'enabled': ['test_plugin'], 'disabled': []}
@pytest.fixture
def config_manager_mock(plugin_config):
    config_manager = MagicMock()
    config_manager.get.return_value = plugin_config
    return config_manager
@pytest.fixture
def event_bus_mock():
    event_bus = MagicMock()
    return event_bus
@pytest.fixture
def file_manager_mock():
    file_manager = MagicMock()
    return file_manager
@pytest.fixture
def plugin_manager(config_manager_mock, event_bus_mock, file_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    plugin_mgr = PluginManager(config_manager_mock, logger_manager, event_bus_mock, file_manager_mock)
    original_extract = plugin_mgr._extract_plugin_metadata
    def mock_extract_metadata(plugin_class, default_name, **kwargs):
        if plugin_class == TestPlugin:
            plugin_info = original_extract(plugin_class, default_name, **kwargs)
            return plugin_info
        return original_extract(plugin_class, default_name, **kwargs)
    plugin_mgr._extract_plugin_metadata = mock_extract_metadata
    def init_with_test_plugin():
        plugin_mgr.initialize()
        plugin_info = plugin_mgr._extract_plugin_metadata(TestPlugin, 'test_plugin')
        plugin_mgr._plugins['test_plugin'] = plugin_info
    init_with_test_plugin()
    yield plugin_mgr
    plugin_mgr.shutdown()
def test_plugin_manager_initialization(config_manager_mock, event_bus_mock, file_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    plugin_mgr = PluginManager(config_manager_mock, logger_manager, event_bus_mock, file_manager_mock)
    plugin_mgr.initialize()
    assert plugin_mgr.initialized
    assert plugin_mgr.healthy
    event_bus_mock.subscribe.assert_called()
    plugin_mgr.shutdown()
    assert not plugin_mgr.initialized
def test_load_plugin(plugin_manager):
    assert 'test_plugin' in plugin_manager._plugins
    result = plugin_manager.load_plugin('test_plugin')
    assert result is True
    plugin_info = plugin_manager._plugins['test_plugin']
    assert plugin_info.state == PluginState.ACTIVE
    assert plugin_info.instance is not None
    plugin_manager._event_bus.publish.assert_called_with(event_type='plugin/loaded', source='plugin_manager', payload={'plugin_name': 'test_plugin', 'version': '0.1.0', 'description': 'Test plugin for unit tests', 'author': 'Tester'})
def test_unload_plugin(plugin_manager):
    plugin_manager.load_plugin('test_plugin')
    result = plugin_manager.unload_plugin('test_plugin')
    assert result is True
    plugin_info = plugin_manager._plugins['test_plugin']
    assert plugin_info.state == PluginState.INACTIVE
    assert plugin_info.instance is None
    plugin_manager._event_bus.publish.assert_called_with(event_type='plugin/unloaded', source='plugin_manager', payload={'plugin_name': 'test_plugin'})
def test_reload_plugin(plugin_manager):
    plugin_manager.load_plugin('test_plugin')
    result = plugin_manager.reload_plugin('test_plugin')
    assert result is True
    plugin_info = plugin_manager._plugins['test_plugin']
    assert plugin_info.state == PluginState.ACTIVE
    assert plugin_info.instance is not None
def test_enable_disable_plugin(plugin_manager):
    result = plugin_manager.enable_plugin('test_plugin')
    assert result is True
    assert 'test_plugin' in plugin_manager._enabled_plugins
    assert 'test_plugin' not in plugin_manager._disabled_plugins
    result = plugin_manager.disable_plugin('test_plugin')
    assert result is True
    assert 'test_plugin' not in plugin_manager._enabled_plugins
    assert 'test_plugin' in plugin_manager._disabled_plugins
    plugin_info = plugin_manager._plugins['test_plugin']
    assert plugin_info.state == PluginState.DISABLED
def test_get_plugin_info(plugin_manager):
    plugin_manager.load_plugin('test_plugin')
    info = plugin_manager.get_plugin_info('test_plugin')
    assert info is not None
    assert info['name'] == 'test_plugin'
    assert info['version'] == '0.1.0'
    assert info['description'] == 'Test plugin for unit tests'
    assert info['author'] == 'Tester'
    assert info['state'] == PluginState.ACTIVE.value
    assert info['enabled'] is True
def test_get_all_plugins(plugin_manager):
    plugins = plugin_manager.get_all_plugins()
    assert len(plugins) == 1
    assert plugins[0]['name'] == 'test_plugin'
def test_get_active_plugins(plugin_manager):
    active_plugins = plugin_manager.get_active_plugins()
    assert len(active_plugins) == 0
    plugin_manager.load_plugin('test_plugin')
    active_plugins = plugin_manager.get_active_plugins()
    assert len(active_plugins) == 1
    assert active_plugins[0]['name'] == 'test_plugin'
def test_plugin_with_dependencies(plugin_manager):
    class PluginWithDeps:
        name = 'plugin_with_deps'
        version = '0.1.0'
        description = 'Plugin with dependencies'
        author = 'Tester'
        dependencies = ['test_plugin']
        def __init__(self):
            self._initialized = False
        def initialize(self, event_bus, logger_provider, config_provider):
            self._initialized = True
        def shutdown(self):
            self._initialized = False
    plugin_info = plugin_manager._extract_plugin_metadata(PluginWithDeps, 'plugin_with_deps')
    plugin_manager._plugins['plugin_with_deps'] = plugin_info
    result = plugin_manager.load_plugin('plugin_with_deps')
    assert result is True
    assert plugin_manager._plugins['test_plugin'].state == PluginState.ACTIVE
    assert plugin_manager._plugins['plugin_with_deps'].state == PluginState.ACTIVE
def test_plugin_with_missing_dependency(plugin_manager):
    class PluginWithMissingDep:
        name = 'plugin_with_missing_dep'
        version = '0.1.0'
        description = 'Plugin with missing dependency'
        author = 'Tester'
        dependencies = ['nonexistent_plugin']
        def __init__(self):
            pass
        def initialize(self, event_bus, logger_provider, config_provider):
            pass
        def shutdown(self):
            pass
    plugin_info = plugin_manager._extract_plugin_metadata(PluginWithMissingDep, 'plugin_with_missing_dep')
    plugin_manager._plugins['plugin_with_missing_dep'] = plugin_info
    result = plugin_manager.load_plugin('plugin_with_missing_dep')
    assert result is False
    assert plugin_manager._plugins['plugin_with_missing_dep'].state == PluginState.FAILED
def test_dependent_plugin_unload_prevention(plugin_manager):
    class PluginWithDeps:
        name = 'plugin_with_deps'
        version = '0.1.0'
        description = 'Plugin with dependencies'
        author = 'Tester'
        dependencies = ['test_plugin']
        def __init__(self):
            self._initialized = False
        def initialize(self, event_bus, logger_provider, config_provider):
            self._initialized = True
        def shutdown(self):
            self._initialized = False
    plugin_info = plugin_manager._extract_plugin_metadata(PluginWithDeps, 'plugin_with_deps')
    plugin_manager._plugins['plugin_with_deps'] = plugin_info
    plugin_manager.load_plugin('test_plugin')
    plugin_manager.load_plugin('plugin_with_deps')
    result = plugin_manager.unload_plugin('test_plugin')
    assert result is False
    assert plugin_manager._plugins['test_plugin'].state == PluginState.ACTIVE
def test_plugin_manager_events(plugin_manager):
    plugin_manager._event_bus.reset_mock()
    plugin_manager.load_plugin('test_plugin')
    plugin_manager._event_bus.publish.assert_called_with(event_type='plugin/loaded', source='plugin_manager', payload={'plugin_name': 'test_plugin', 'version': '0.1.0', 'description': 'Test plugin for unit tests', 'author': 'Tester'})
    plugin_manager._event_bus.reset_mock()
    plugin_manager.unload_plugin('test_plugin')
    plugin_manager._event_bus.publish.assert_called_with(event_type='plugin/unloaded', source='plugin_manager', payload={'plugin_name': 'test_plugin'})
def test_plugin_manager_status(plugin_manager):
    plugin_manager.load_plugin('test_plugin')
    status = plugin_manager.status()
    assert status['name'] == 'PluginManager'
    assert status['initialized'] is True
    assert 'plugins' in status
    assert status['plugins']['active'] == 1
    assert 'config' in status
def test_operations_without_initialization():
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    plugin_mgr = PluginManager(MagicMock(), logger_manager, MagicMock(), MagicMock())
    with pytest.raises(PluginError):
        plugin_mgr.load_plugin('test_plugin')