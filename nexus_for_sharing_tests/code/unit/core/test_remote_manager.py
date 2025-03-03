import pytest
import os
import json
from unittest.mock import MagicMock, patch
from nexus_core.core.remote_manager import RemoteServicesManager, ServiceProtocol, HTTPService, AsyncHTTPService
@pytest.fixture
def remote_config():
    return {'health_check_interval': 60.0, 'services': {'test_service': {'enabled': True, 'type': 'http', 'protocol': 'https', 'base_url': 'https://api.example.com', 'timeout': 30.0, 'max_retries': 3, 'health_check_path': '/health'}, 'disabled_service': {'enabled': False, 'type': 'http', 'base_url': 'https://disabled.example.com'}}}
@pytest.fixture
def config_manager_mock(remote_config):
    config_manager = MagicMock()
    config_manager.get.return_value = remote_config
    return config_manager
@pytest.fixture
def remote_manager(config_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    event_bus_manager = MagicMock()
    thread_manager = MagicMock()
    remote_mgr = RemoteServicesManager(config_manager_mock, logger_manager, event_bus_manager, thread_manager)
    with patch('nexus_core.core.remote_manager.HTTPService'):
        remote_mgr.initialize()
    yield remote_mgr
    remote_mgr.shutdown()
def test_remote_manager_initialization(config_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    event_bus_manager = MagicMock()
    thread_manager = MagicMock()
    with patch('nexus_core.core.remote_manager.HTTPService') as mock_http_service:
        remote_mgr = RemoteServicesManager(config_manager_mock, logger_manager, event_bus_manager, thread_manager)
        remote_mgr.initialize()
        assert remote_mgr.initialized
        assert remote_mgr.healthy
        assert len(remote_mgr._services) == 1
        assert 'test_service' in remote_mgr._services
        event_bus_manager.subscribe.assert_called()
        thread_manager.schedule_periodic_task.assert_called_with(interval=60.0, func=remote_mgr._health_check_task, task_id='service_health_check')
        remote_mgr.shutdown()
        assert not remote_mgr.initialized
def test_register_service(remote_manager):
    mock_service = MagicMock()
    mock_service.name = 'new_service'
    mock_service.protocol = ServiceProtocol.HTTP
    mock_service.base_url = 'http://new.example.com'
    remote_manager.register_service(mock_service)
    assert 'new_service' in remote_manager._services
    remote_manager._event_bus.publish.assert_called_with(event_type='remote_service/registered', source='remote_manager', payload={'service_name': 'new_service', 'protocol': 'http', 'base_url': 'http://new.example.com'})
def test_unregister_service(remote_manager):
    mock_service = MagicMock()
    mock_service.name = 'to_remove'
    mock_service.protocol = ServiceProtocol.HTTP
    mock_service.base_url = 'http://remove.example.com'
    remote_manager._services['to_remove'] = mock_service
    result = remote_manager.unregister_service('to_remove')
    assert result is True
    assert 'to_remove' not in remote_manager._services
    mock_service.close.assert_called_once()
    remote_manager._event_bus.publish.assert_called_with(event_type='remote_service/unregistered', source='remote_manager', payload={'service_name': 'to_remove'})
def test_get_service(remote_manager):
    mock_service = MagicMock()
    remote_manager._services['test_service'] = mock_service
    service = remote_manager.get_service('test_service')
    assert service is mock_service
    nonexistent = remote_manager.get_service('nonexistent')
    assert nonexistent is None
@patch('nexus_core.core.remote_manager.HTTPService')
def test_http_service_methods(mock_http, remote_manager):
    mock_service = MagicMock()
    mock_service.get.return_value.json.return_value = {'data': 'test'}
    remote_manager._services['test_service'] = mock_service
    result = remote_manager.make_request('test_service', 'GET', '/endpoint')
    mock_service.get.assert_called_with('/endpoint')
    assert result == {'data': 'test'}
    remote_manager.make_request('test_service', 'POST', '/endpoint', json_data={'key': 'value'})
    mock_service.post.assert_called_with('/endpoint', json_data={'key': 'value'})
    remote_manager.make_request('test_service', 'PUT', '/endpoint')
    mock_service.put.assert_called_with('/endpoint')
    remote_manager.make_request('test_service', 'DELETE', '/endpoint')
    mock_service.delete.assert_called_with('/endpoint')
def test_service_health_check(remote_manager):
    mock_service1 = MagicMock()
    mock_service1.check_health.return_value = True
    mock_service2 = MagicMock()
    mock_service2.check_health.return_value = False
    remote_manager._services = {'service1': mock_service1, 'service2': mock_service2}
    result = remote_manager.check_all_services_health()
    assert result == {'service1': True, 'service2': False}
    mock_service1.check_health.assert_called_once()
    mock_service2.check_health.assert_called_once()
    remote_manager._health_check_task()
    remote_manager._event_bus.publish.assert_called_with(event_type='remote_service/health_check', source='remote_manager', payload={'services': {'service1': {'healthy': True}, 'service2': {'healthy': False}}, 'healthy_count': 1, 'unhealthy_count': 1, 'timestamp': mock.ANY})
def test_remote_manager_status(remote_manager):
    mock_service = MagicMock()
    mock_service.status.return_value = {'name': 'test_service', 'healthy': True, 'base_url': 'https://example.com'}
    remote_manager._services['test_service'] = mock_service
    status = remote_manager.status()
    assert status['name'] == 'RemoteServicesManager'
    assert status['initialized'] is True
    assert 'services' in status
    assert 'test_service' in status['services']['statuses']
    assert 'health_check' in status
def test_on_config_changed(remote_manager):
    remote_manager._on_config_changed('remote_services.health_check_interval', 120.0)
    assert remote_manager._health_check_interval == 120.0
    remote_manager._thread_manager.schedule_periodic_task.assert_called()
    remote_manager._on_config_changed('remote_services.services.test_service.timeout', 60.0)
    remote_manager._logger.warning.assert_called()
@patch('nexus_core.core.remote_manager.HTTPService')
def test_event_handlers(mock_http, remote_manager):
    register_event = MagicMock()
    register_event.payload = {'service_name': 'event_service', 'service_config': {'type': 'http', 'protocol': 'https', 'base_url': 'https://event.example.com'}}
    remote_manager._on_service_register_event(register_event)
    mock_http.assert_called()
    unregister_event = MagicMock()
    unregister_event.payload = {'service_name': 'test_service'}
    remote_manager._on_service_unregister_event(unregister_event)
    assert 'test_service' not in remote_manager._services