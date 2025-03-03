import os
import pytest
import tempfile
import json
from unittest.mock import MagicMock, patch
import asyncio
from httpx import AsyncClient
try:
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
except ImportError:
    pytest.skip('FastAPI not installed', allow_module_level=True)
from nexus_core.core.api_manager import APIManager
from nexus_core.core.security_manager import SecurityManager, UserRole
@pytest.fixture
def mock_managers():
    config_manager = MagicMock()
    config_manager.get.return_value = {'enabled': True, 'host': '127.0.0.1', 'port': 8000, 'cors': {'origins': ['*'], 'methods': ['*'], 'headers': ['*']}, 'rate_limit': {'enabled': False}}
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    security_manager = MagicMock(spec=SecurityManager)
    security_manager.authenticate_user.return_value = {'user_id': 'test_user_id', 'username': 'testuser', 'email': 'test@example.com', 'roles': ['admin'], 'access_token': 'test_access_token', 'token_type': 'bearer', 'expires_in': 1800, 'refresh_token': 'test_refresh_token'}
    security_manager.verify_token.return_value = {'sub': 'test_user_id', 'jti': 'test_jti'}
    security_manager.get_user_info.return_value = {'id': 'test_user_id', 'username': 'testuser', 'email': 'test@example.com', 'roles': ['admin'], 'active': True, 'created_at': '2025-01-01T00:00:00', 'last_login': '2025-01-01T12:00:00'}
    security_manager.has_permission.return_value = True
    event_bus_manager = MagicMock()
    thread_manager = MagicMock()
    registry = {'app_core': MagicMock(), 'config': config_manager, 'security': security_manager, 'event_bus': event_bus_manager, 'thread_manager': thread_manager}
    registry['app_core'].status.return_value = {'name': 'ApplicationCore', 'initialized': True, 'healthy': True, 'version': '0.1.0', 'managers': {'config': {'initialized': True, 'healthy': True}, 'logging': {'initialized': True, 'healthy': True}, 'event_bus': {'initialized': True, 'healthy': True}}}
    return (config_manager, logger_manager, security_manager, event_bus_manager, thread_manager, registry)
@pytest.fixture
def api_manager(mock_managers):
    config_manager, logger_manager, security_manager, event_bus_manager, thread_manager, registry = mock_managers
    api_mgr = APIManager(config_manager, logger_manager, security_manager, event_bus_manager, thread_manager, registry)
    api_mgr.initialize()
    yield api_mgr
    api_mgr.shutdown()
@pytest.fixture
def test_client(api_manager):
    app = api_manager._app
    return TestClient(app)
@pytest.mark.asyncio
async def test_async_client(api_manager):
    app = api_manager._app
    async with AsyncClient(app=app, base_url='http://test') as client:
        response = await client.get('/')
        assert response.status_code == 200
        assert 'name' in response.json()
        assert response.json()['name'] == 'Nexus Core API'
def test_api_root_endpoint(test_client):
    response = test_client.get('/')
    assert response.status_code == 200
    assert response.json() == {'name': 'Nexus Core API', 'version': '0.1.0', 'docs_url': '/api/docs'}
def test_health_check_endpoint(test_client):
    response = test_client.get('/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok', 'healthy': True}
def test_authentication_endpoints(test_client, mock_managers):
    security_manager = mock_managers[2]
    response = test_client.post('/api/v1/auth/token', data={'username': 'testuser', 'password': 'password123'})
    assert response.status_code == 200
    assert 'access_token' in response.json()
    assert response.json()['token_type'] == 'bearer'
    security_manager.authenticate_user.assert_called_with('testuser', 'password123')
    response = test_client.post('/api/v1/auth/refresh', json={'refresh_token': 'test_refresh_token'})
    assert response.status_code == 200
    assert 'access_token' in response.json()
    security_manager.refresh_token.assert_called_with('test_refresh_token')
    response = test_client.post('/api/v1/auth/revoke', json={'token': 'test_access_token'})
    assert response.status_code == 200
    assert response.json() == {'success': True}
    security_manager.revoke_token.assert_called_with('test_access_token')
def test_protected_endpoints(test_client, mock_managers):
    security_manager = mock_managers[2]
    token = 'test_access_token'
    response = test_client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200
    assert response.json()['username'] == 'testuser'
    security_manager.get_user_info.assert_called()
    response = test_client.get('/api/v1/system/status', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200
    assert 'name' in response.json()
    assert response.json()['initialized'] is True
    response = test_client.get('/api/v1/system/status')
    assert response.status_code == 401
    security_manager.has_permission.return_value = False
    response = test_client.get('/api/v1/system/status', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 403
def test_api_endpoints_availability(test_client):
    token = 'test_access_token'
    auth_header = {'Authorization': f'Bearer {token}'}
    response = test_client.get('/api/v1/system/status', headers=auth_header)
    assert response.status_code == 200
    response = test_client.get('/api/v1/system/config/app.name', headers=auth_header)
    assert response.status_code in (200, 404)
    response = test_client.get('/api/v1/users/', headers=auth_header)
    assert response.status_code == 200
    response = test_client.get('/api/v1/plugins/', headers=auth_header)
    assert response.status_code in (200, 503)
    response = test_client.get('/api/v1/monitoring/alerts', headers=auth_header)
    assert response.status_code in (200, 503)
def test_custom_endpoint_registration(api_manager, test_client):
    async def custom_endpoint():
        return {'message': 'This is a custom endpoint'}
    result = api_manager.register_api_endpoint(path='/custom', method='get', endpoint=custom_endpoint, tags=['Custom'], summary='Custom test endpoint')
    assert result is True
    response = test_client.get('/api/v1/custom')
    assert response.status_code == 200
    assert response.json() == {'message': 'This is a custom endpoint'}
def test_api_manager_status(api_manager):
    status = api_manager.status()
    assert status['name'] == 'APIManager'
    assert status['initialized'] is True
    assert 'api' in status
    assert status['api']['enabled'] is True
    assert 'endpoints' in status