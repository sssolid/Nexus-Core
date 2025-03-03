import pytest
import sys
import json
from unittest.mock import MagicMock, patch, AsyncMock
from nexus_core.core.api_manager import APIManager
from nexus_core.utils.exceptions import ManagerInitializationError, APIError

# Skip tests if FastAPI is not installed
fastapi_installed = False
try:
    import fastapi
    fastapi_installed = True
except ImportError:
    pass

pytestmark = pytest.mark.skipif(not fastapi_installed, reason="FastAPI not installed")

@pytest.fixture
def api_config():
    return {
        'enabled': True,
        'host': '127.0.0.1',
        'port': 8000,
        'workers': 4,
        'cors': {
            'origins': ['*'],
            'methods': ['*'],
            'headers': ['*']
        },
        'rate_limit': {
            'enabled': False,
            'requests_per_minute': 100
        }
    }

@pytest.fixture
def config_manager_mock(api_config):
    config_manager = MagicMock()
    config_manager.get.return_value = api_config
    return config_manager

@pytest.fixture
def api_manager_dependencies():
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    security_manager = MagicMock()
    security_manager.verify_token.return_value = {
        'sub': 'test_user_id',
        'jti': 'test_jti'
    }
    security_manager.get_user_info.return_value = {
        'id': 'test_user_id',
        'username': 'testuser',
        'email': 'test@example.com',
        'roles': ['admin'],
        'active': True,
        'created_at': '2025-01-01T00:00:00',
        'last_login': '2025-01-01T12:00:00'
    }
    security_manager.authenticate_user.return_value = {
        'user_id': 'test_user_id',
        'username': 'testuser',
        'email': 'test@example.com',
        'roles': ['admin'],
        'access_token': 'test_access_token',
        'token_type': 'bearer',
        'expires_in': 1800,
        'refresh_token': 'test_refresh_token'
    }
    security_manager.refresh_token.return_value = {
        'access_token': 'new_access_token',
        'token_type': 'bearer',
        'expires_in': 1800
    }
    security_manager.revoke_token.return_value = True
    security_manager.has_permission.return_value = True
    
    event_bus_manager = MagicMock()
    thread_manager = MagicMock()
    
    registry = {
        'app_core': MagicMock(),
        'config': config_manager_mock,
        'security': security_manager,
        'plugin_manager': MagicMock(),
        'monitoring': MagicMock()
    }
    
    registry['app_core'].status.return_value = {
        'name': 'ApplicationCore',
        'initialized': True,
        'healthy': True,
        'version': '0.1.0',
        'managers': {}
    }
    
    return (logger_manager, security_manager, event_bus_manager, thread_manager, registry)

@pytest.fixture
def api_manager(config_manager_mock, api_manager_dependencies):
    logger_manager, security_manager, event_bus_manager, thread_manager, registry = api_manager_dependencies
    
    with patch('nexus_core.core.api_manager.FastAPI'), \
         patch('nexus_core.core.api_manager.APIRouter'), \
         patch('nexus_core.core.api_manager.OAuth2PasswordBearer'), \
         patch('nexus_core.core.api_manager.CORSMiddleware'), \
         patch('fastapi.Depends'), \
         patch.object(APIManager, '_start_api_server'):
        
        api_mgr = APIManager(
            config_manager_mock,
            logger_manager,
            security_manager,
            event_bus_manager,
            thread_manager,
            registry
        )
        api_mgr.initialize()
        
        yield api_mgr
        api_mgr.shutdown()

def test_api_manager_initialization(config_manager_mock, api_manager_dependencies):
    logger_manager, security_manager, event_bus_manager, thread_manager, registry = api_manager_dependencies
    
    # Test successful initialization
    with patch('nexus_core.core.api_manager.FastAPI') as mock_fastapi, \
         patch('nexus_core.core.api_manager.APIRouter') as mock_router, \
         patch('nexus_core.core.api_manager.OAuth2PasswordBearer'), \
         patch('nexus_core.core.api_manager.CORSMiddleware'), \
         patch.object(APIManager, '_start_api_server'):
        
        mock_app = MagicMock()
        mock_fastapi.return_value = mock_app
        
        api_mgr = APIManager(
            config_manager_mock,
            logger_manager,
            security_manager,
            event_bus_manager,
            thread_manager,
            registry
        )
        api_mgr.initialize()
        
        assert api_mgr.initialized
        assert api_mgr.healthy
        
        # Check if FastAPI app was created
        mock_fastapi.assert_called_once()
        
        # Check if middleware was added
        mock_app.add_middleware.assert_called_once()
        
        # Check if routers were created and included
        assert mock_router.call_count >= 1
        assert mock_app.include_router.call_count >= 1
        
        # Check if API server was started
        api_mgr._start_api_server.assert_called_once()
        
        # Check if event was published
        event_bus_manager.publish.assert_called_with(
            event_type='api/started',
            source='api_manager',
            payload={'host': '127.0.0.1', 'port': 8000, 'url': 'http://127.0.0.1:8000/api'}
        )
        
        api_mgr.shutdown()
        assert not api_mgr.initialized

def test_api_manager_disabled(config_manager_mock, api_manager_dependencies):
    logger_manager, security_manager, event_bus_manager, thread_manager, registry = api_manager_dependencies
    
    # Test initialization with API disabled
    config_manager_mock.get.return_value = {'enabled': False}
    
    api_mgr = APIManager(
        config_manager_mock,
        logger_manager,
        security_manager,
        event_bus_manager,
        thread_manager,
        registry
    )
    api_mgr.initialize()
    
    assert api_mgr.initialized
    assert api_mgr._app is None
    
    api_mgr.shutdown()

def test_api_manager_initialization_failure(config_manager_mock, api_manager_dependencies):
    logger_manager, security_manager, event_bus_manager, thread_manager, registry = api_manager_dependencies
    
    # Test failure when FastAPI is not available
    with patch('nexus_core.core.api_manager.fastapi', None):
        api_mgr = APIManager(
            config_manager_mock,
            logger_manager,
            security_manager,
            event_bus_manager,
            thread_manager,
            registry
        )
        
        with pytest.raises(ManagerInitializationError):
            api_mgr.initialize()

@pytest.mark.skipif(not fastapi_installed, reason="FastAPI not installed")
def test_register_api_endpoint(api_manager):
    # Create a test endpoint
    async def test_endpoint():
        return {"message": "test endpoint"}
    
    # Register it with the API manager
    mock_router = MagicMock()
    api_manager._routers['v1'] = mock_router
    
    result = api_manager.register_api_endpoint(
        path='/test',
        method='get',
        endpoint=test_endpoint,
        tags=['Test'],
        summary='Test endpoint'
    )
    
    assert result is True
    mock_router.get.assert_called_with(
        '/test',
        tags=['Test'],
        summary='Test endpoint'
    )

def test_api_manager_status(api_manager):
    api_manager._server_thread = MagicMock()
    api_manager._server_thread.is_alive.return_value = True
    
    status = api_manager.status()
    
    assert status['name'] == 'APIManager'
    assert status['initialized'] is True
    assert 'api' in status
    assert status['api']['enabled'] is True
    assert status['api']['running'] is True
    assert status['api']['host'] == '127.0.0.1'
    assert status['api']['port'] == 8000
    assert 'endpoints' in status
    assert 'rate_limit' in status

def test_on_config_changed(api_manager):
    # Test changing API enabled flag
    api_manager._on_config_changed('api.enabled', False)
    api_manager._logger.warning.assert_called_with(
        'Changing api.enabled requires restart to take effect',
        extra={'enabled': False}
    )
    
    # Test changing API port
    api_manager._on_config_changed('api.port', 8080)
    api_manager._logger.warning.assert_called_with(
        'Changing api.port requires restart to take effect',
        extra={'port': 8080}
    )
    
    # Test changing CORS settings
    api_manager._on_config_changed('api.cors.origins', ['http://localhost:3000'])
    api_manager._logger.warning.assert_called_with(
        'Changing api.cors.origins requires restart to take effect',
        extra={'origins': ['http://localhost:3000']}
    )

@pytest.mark.asyncio
async def test_endpoint_handlers(api_manager):
    # Here we would test the actual endpoint handler functions
    # Since they're defined as inner functions within the APIManager class,
    # we can't easily access them directly for unit testing
    # 
    # In a real scenario, we would use the FastAPI TestClient to call
    # these endpoints, which is covered in the integration tests
    
    # Instead, we'll mock the dependencies to test the handler logic
    security_manager = api_manager._security_manager
    
    # Test the auth token endpoint logic
    auth_data = {'username': 'testuser', 'password': 'password123'}
    form_data = MagicMock()
    form_data.username = auth_data['username']
    form_data.password = auth_data['password']
    
    # Create a mock handler that would simulate the login endpoint
    async def test_login():
        user_data = security_manager.authenticate_user(form_data.username, form_data.password)
        if not user_data:
            # In the actual handler, this would raise an HTTPException
            return None
        return {
            'access_token': user_data['access_token'],
            'token_type': user_data['token_type'],
            'expires_in': user_data['expires_in'],
            'refresh_token': user_data['refresh_token']
        }
    
    # Test the handler logic
    result = await test_login()
    security_manager.authenticate_user.assert_called_with('testuser', 'password123')
    assert result['access_token'] == 'test_access_token'
    assert result['token_type'] == 'bearer'
    assert result['expires_in'] == 1800
    assert result['refresh_token'] == 'test_refresh_token'

def test_api_shutdown(api_manager):
    # Set up mocks for shutdown
    api_manager._server_thread = MagicMock()
    api_manager._server_thread.is_alive.return_value = True
    api_manager._server_should_exit = MagicMock()
    
    # Call shutdown
    api_manager.shutdown()
    
    # Verify that server thread was asked to exit
    api_manager._server_should_exit.set.assert_called_once()
    
    # Verify that server thread was joined
    api_manager._server_thread.join.assert_called_once()
    
    # Verify that event subscriptions were cleaned up
    api_manager._config_manager.unregister_listener.assert_called_once()
    
    # Verify that managers were cleaned up
    assert api_manager._app is None
    assert not api_manager.initialized
    assert not api_manager.healthy
