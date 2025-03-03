import pytest
from nexus_core.utils.exceptions import NexusError, ManagerError, ManagerInitializationError, ManagerShutdownError, ConfigurationError, EventBusError, PluginError, DatabaseError, SecurityError, ThreadManagerError, FileError, APIError
def test_nexus_error():
    error = NexusError('Test error message')
    assert str(error) == 'Test error message'
    assert error.code == 'NexusError'
    assert error.details == {}
    error = NexusError('Test with code', code='CUSTOM_CODE')
    assert error.code == 'CUSTOM_CODE'
    details = {'key': 'value', 'number': 123}
    error = NexusError('Test with details', details=details)
    assert error.details == details
def test_manager_error():
    error = ManagerError('Manager error message')
    assert str(error) == 'Manager error message'
    assert error.code == 'ManagerError'
    assert 'manager_name' not in error.details
    error = ManagerError('Manager error with name', manager_name='TestManager')
    assert error.details['manager_name'] == 'TestManager'
    details = {'key': 'value'}
    error = ManagerError('Manager error with details', manager_name='TestManager', details=details)
    assert error.details['manager_name'] == 'TestManager'
    assert error.details['key'] == 'value'
def test_manager_initialization_error():
    error = ManagerInitializationError('Init error', manager_name='TestManager')
    assert str(error) == 'Init error'
    assert error.code == 'ManagerInitializationError'
    assert error.details['manager_name'] == 'TestManager'
def test_manager_shutdown_error():
    error = ManagerShutdownError('Shutdown error', manager_name='TestManager')
    assert str(error) == 'Shutdown error'
    assert error.code == 'ManagerShutdownError'
    assert error.details['manager_name'] == 'TestManager'
def test_configuration_error():
    error = ConfigurationError('Config error message')
    assert str(error) == 'Config error message'
    assert error.code == 'ConfigurationError'
    assert 'config_key' not in error.details
    error = ConfigurationError('Config error with key', config_key='database.host')
    assert error.details['config_key'] == 'database.host'
    details = {'suggestion': 'Check your settings'}
    error = ConfigurationError('Config error with details', config_key='database.host', details=details)
    assert error.details['config_key'] == 'database.host'
    assert error.details['suggestion'] == 'Check your settings'
def test_event_bus_error():
    error = EventBusError('Event bus error message')
    assert str(error) == 'Event bus error message'
    assert error.code == 'EventBusError'
    assert 'event_type' not in error.details
    error = EventBusError('Event bus error with type', event_type='test/event')
    assert error.details['event_type'] == 'test/event'
def test_plugin_error():
    error = PluginError('Plugin error message')
    assert str(error) == 'Plugin error message'
    assert error.code == 'PluginError'
    assert 'plugin_name' not in error.details
    error = PluginError('Plugin error with name', plugin_name='test_plugin')
    assert error.details['plugin_name'] == 'test_plugin'
def test_database_error():
    error = DatabaseError('Database error message')
    assert str(error) == 'Database error message'
    assert error.code == 'DatabaseError'
    assert 'query' not in error.details
    error = DatabaseError('Database error with query', query='SELECT * FROM users')
    assert error.details['query'] == 'SELECT * FROM users'
def test_security_error():
    error = SecurityError('Security error message')
    assert str(error) == 'Security error message'
    assert error.code == 'SecurityError'
    assert 'user_id' not in error.details
    assert 'permission' not in error.details
    error = SecurityError('Security error with user', user_id='user123')
    assert error.details['user_id'] == 'user123'
    error = SecurityError('Security error with permission', permission='admin.read')
    assert error.details['permission'] == 'admin.read'
    error = SecurityError('Security error with both', user_id='user123', permission='admin.read')
    assert error.details['user_id'] == 'user123'
    assert error.details['permission'] == 'admin.read'
def test_thread_manager_error():
    error = ThreadManagerError('Thread error message')
    assert str(error) == 'Thread error message'
    assert error.code == 'ThreadManagerError'
    assert 'thread_id' not in error.details
    error = ThreadManagerError('Thread error with ID', thread_id='thread123')
    assert error.details['thread_id'] == 'thread123'
def test_file_error():
    error = FileError('File error message')
    assert str(error) == 'File error message'
    assert error.code == 'FileError'
    assert 'file_path' not in error.details
    error = FileError('File error with path', file_path='/path/to/file.txt')
    assert error.details['file_path'] == '/path/to/file.txt'
def test_api_error():
    error = APIError('API error message')
    assert str(error) == 'API error message'
    assert error.code == 'APIError'
    assert 'status_code' not in error.details
    assert 'endpoint' not in error.details
    error = APIError('API error with status', status_code=404)
    assert error.details['status_code'] == 404
    error = APIError('API error with endpoint', endpoint='/api/users')
    assert error.details['endpoint'] == '/api/users'
    error = APIError('API error with both', status_code=404, endpoint='/api/users')
    assert error.details['status_code'] == 404
    assert error.details['endpoint'] == '/api/users'
def test_exception_chaining():
    try:
        try:
            raise ValueError('Original error')
        except ValueError as e:
            raise DatabaseError('Database wrapper error', query='SELECT 1') from e
    except DatabaseError as db_error:
        assert str(db_error) == 'Database wrapper error'
        assert db_error.details['query'] == 'SELECT 1'
        assert db_error.__cause__ is not None
        assert str(db_error.__cause__) == 'Original error'