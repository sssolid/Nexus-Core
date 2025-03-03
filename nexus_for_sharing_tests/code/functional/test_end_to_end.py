import os
import pytest
import tempfile
import time
import threading
from pathlib import Path
from nexus_core.core.app import ApplicationCore
from nexus_core.core.config_manager import ConfigManager
@pytest.fixture
def temp_data_dir():
    temp_dir = tempfile.mkdtemp()
    os.makedirs(os.path.join(temp_dir, 'data'), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, 'data', 'temp'), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, 'data', 'plugins'), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, 'data', 'backups'), exist_ok=True)
    os.makedirs(os.path.join(temp_dir, 'logs'), exist_ok=True)
    yield temp_dir
@pytest.fixture
def temp_config_file(temp_data_dir):
    config_content = f'''\napp:\n  name: "Nexus Core Functional Test"\n  version: "0.1.0"\n  environment: "testing"\n  debug: true\n  ui:\n    enabled: false\n\ndatabase:\n  type: "sqlite"\n  name: ":memory:"\n\nlogging:\n  level: "INFO"\n  format: "text"\n  file:\n    enabled: true\n    path: "{os.path.join(temp_data_dir, 'logs', 'nexus_test.log')}"\n  console:\n    enabled: true\n    level: "DEBUG"\n\nfiles:\n  base_directory: "{os.path.join(temp_data_dir, 'data')}"\n  temp_directory: "{os.path.join(temp_data_dir, 'data', 'temp')}"\n  plugin_data_directory: "{os.path.join(temp_data_dir, 'data', 'plugins')}"\n  backup_directory: "{os.path.join(temp_data_dir, 'data', 'backups')}"\n\nplugins:\n  directory: "{os.path.join(temp_data_dir, 'data', 'plugins')}"\n  autoload: false\n\napi:\n  enabled: false\n\nmonitoring:\n  enabled: true\n  prometheus:\n    enabled: false\n\nsecurity:\n  jwt:\n    secret: "functional-test-secret-key-for-testing-only"\n    algorithm: "HS256"\n'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(config_content)
        config_path = f.name
    yield config_path
    os.unlink(config_path)
class TestEndToEnd:
    def test_application_lifecycle(self, temp_config_file, temp_data_dir):
        app = ApplicationCore(config_path=temp_config_file)
        app.initialize()
        assert app._initialized
        config_manager = app.get_manager('config')
        assert config_manager is not None
        assert config_manager.initialized
        logging_manager = app.get_manager('logging')
        assert logging_manager is not None
        assert logging_manager.initialized
        event_bus = app.get_manager('event_bus')
        assert event_bus is not None
        assert event_bus.initialized
        events_received = []
        def event_handler(event):
            events_received.append(event)
        subscriber_id = event_bus.subscribe(event_type='test/functional', callback=event_handler, subscriber_id='functional_test')
        event_id = event_bus.publish(event_type='test/functional', source='functional_test', payload={'message': 'Test event from functional test'})
        time.sleep(0.1)
        assert len(events_received) == 1
        assert events_received[0].event_type == 'test/functional'
        assert events_received[0].event_id == event_id
        assert events_received[0].source == 'functional_test'
        assert events_received[0].payload['message'] == 'Test event from functional test'
        config_val = config_manager.get('app.name')
        assert config_val == 'Nexus Core Functional Test'
        config_manager.set('app.custom_setting', 'custom_value')
        assert config_manager.get('app.custom_setting') == 'custom_value'
        file_manager = app.get_manager('file_manager')
        if file_manager:
            test_file_content = 'This is a test file for functional testing.'
            file_manager.write_text('functional_test.txt', test_file_content)
            read_content = file_manager.read_text('functional_test.txt')
            assert read_content == test_file_content
            files = file_manager.list_files()
            assert any((f.name == 'functional_test.txt' for f in files))
            file_manager.delete_file('functional_test.txt')
            files = file_manager.list_files()
            assert not any((f.name == 'functional_test.txt' for f in files))
        db_manager = app.get_manager('database')
        if db_manager:
            db_manager.create_tables()
            result = db_manager.execute_raw('SELECT 1 as test')
            assert len(result) == 1
            assert result[0]['test'] == 1
        security_manager = app.get_manager('security')
        if security_manager:
            from nexus_core.core.security_manager import UserRole
            user_id = security_manager.create_user(username='functional_test_user', email='functional@test.com', password='Secure123!', roles=[UserRole.ADMIN])
            auth_result = security_manager.authenticate_user('functional_test_user', 'Secure123!')
            assert auth_result is not None
            assert auth_result['user_id'] == user_id
            assert 'access_token' in auth_result
            assert 'refresh_token' in auth_result
            token_data = security_manager.verify_token(auth_result['access_token'])
            assert token_data is not None
            assert token_data['sub'] == user_id
            has_permission = security_manager.has_permission(user_id, 'system', 'view')
            assert has_permission is True
        thread_manager = app.get_manager('thread_manager')
        if thread_manager:
            result_container = []
            def test_task(value):
                time.sleep(0.1)
                result_container.append(value * 2)
                return value * 2
            task_id = thread_manager.submit_task(test_task, 21, name='functional_test_task')
            time.sleep(0.2)
            task_info = thread_manager.get_task_info(task_id)
            assert task_info['status'] == 'completed'
            result = thread_manager.get_task_result(task_id)
            assert result == 42
            assert result_container[0] == 42
        status = app.status()
        assert status['name'] == 'ApplicationCore'
        assert status['initialized'] is True
        assert 'managers' in status
        app.shutdown()
        assert not app._initialized
        assert not config_manager.initialized