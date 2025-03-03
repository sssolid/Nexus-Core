import pytest
import json
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from nexus_core.models.base import Base, TimestampMixin
from nexus_core.models.user import User, UserRole, user_roles
from nexus_core.models.plugin import Plugin
from nexus_core.models.system import SystemSetting
from nexus_core.models.audit import AuditLog, AuditActionType
@pytest.fixture
def engine():
    return create_engine('sqlite:///:memory:')
@pytest.fixture
def tables(engine):
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)
@pytest.fixture
def session(engine, tables):
    connection = engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(bind=connection)
    session = Session()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
def test_timestamp_mixin():
    assert hasattr(TimestampMixin, 'created_at')
    assert hasattr(TimestampMixin, 'updated_at')
def test_user_model(session):
    user = User(username='testuser', email='test@example.com', hashed_password='hashed_password_here', roles=[UserRole.ADMIN, UserRole.USER])
    session.add(user)
    session.commit()
    retrieved_user = session.query(User).filter_by(username='testuser').first()
    assert retrieved_user is not None
    assert retrieved_user.id is not None
    assert retrieved_user.username == 'testuser'
    assert retrieved_user.email == 'test@example.com'
    assert retrieved_user.hashed_password == 'hashed_password_here'
    assert retrieved_user.active is True
    assert retrieved_user.created_at is not None
    assert len(retrieved_user.roles) == 2
    assert UserRole.ADMIN in retrieved_user.roles
    assert UserRole.USER in retrieved_user.roles
    assert f"User(id={retrieved_user.id}, username='testuser')" == repr(retrieved_user)
def test_plugin_model(session):
    plugin = Plugin(name='test_plugin', version='1.0.0', description='Test plugin for unit tests', author='Test Author', enabled=True, installed_path='/path/to/plugin', configuration={'setting1': 'value1', 'setting2': 42})
    session.add(plugin)
    session.commit()
    retrieved_plugin = session.query(Plugin).filter_by(name='test_plugin').first()
    assert retrieved_plugin is not None
    assert retrieved_plugin.id is not None
    assert retrieved_plugin.name == 'test_plugin'
    assert retrieved_plugin.version == '1.0.0'
    assert retrieved_plugin.description == 'Test plugin for unit tests'
    assert retrieved_plugin.author == 'Test Author'
    assert retrieved_plugin.enabled is True
    assert retrieved_plugin.installed_path == '/path/to/plugin'
    assert retrieved_plugin.configuration['setting1'] == 'value1'
    assert retrieved_plugin.configuration['setting2'] == 42
    assert f"Plugin(id={retrieved_plugin.id}, name='test_plugin', version='1.0.0')" == repr(retrieved_plugin)
def test_system_setting_model(session):
    valid_setting = SystemSetting(key='app.name', value='Test Application', description='Application name setting', is_secret=False, is_editable=True)
    session.add(valid_setting)
    session.commit()
    retrieved_setting = session.query(SystemSetting).filter_by(key='app.name').first()
    assert retrieved_setting is not None
    assert retrieved_setting.key == 'app.name'
    assert retrieved_setting.value == 'Test Application'
    assert retrieved_setting.is_secret is False
    assert retrieved_setting.is_editable is True
    json_setting = SystemSetting(key='app.config', value={'debug': True, 'log_level': 'info', 'features': ['a', 'b', 'c']})
    session.add(json_setting)
    session.commit()
    retrieved_json = session.query(SystemSetting).filter_by(key='app.config').first()
    assert retrieved_json.value['debug'] is True
    assert retrieved_json.value['log_level'] == 'info'
    assert retrieved_json.value['features'] == ['a', 'b', 'c']
    secret_setting = SystemSetting(key='db.password', value='secret123', is_secret=True)
    session.add(secret_setting)
    session.commit()
    assert "value='******'" in repr(secret_setting)
    with pytest.raises(ValueError):
        invalid_setting = SystemSetting(key='invalid_key', value='test')
        session.add(invalid_setting)
        session.commit()
def test_audit_log_model(session):
    user = User(username='audit_user', email='audit@example.com', hashed_password='password_hash')
    session.add(user)
    session.commit()
    audit_log = AuditLog(user_id=user.id, user_name='audit_user', action_type=AuditActionType.CREATE, resource_type='user', resource_id='123', description='Created new user', ip_address='127.0.0.1', user_agent='Test Browser', details={'key1': 'value1', 'key2': 42})
    session.add(audit_log)
    session.commit()
    retrieved_log = session.query(AuditLog).filter_by(user_name='audit_user').first()
    assert retrieved_log is not None
    assert retrieved_log.id is not None
    assert retrieved_log.user_id == user.id
    assert retrieved_log.action_type == AuditActionType.CREATE
    assert retrieved_log.resource_type == 'user'
    assert retrieved_log.resource_id == '123'
    assert retrieved_log.description == 'Created new user'
    assert retrieved_log.ip_address == '127.0.0.1'
    assert retrieved_log.user_agent == 'Test Browser'
    assert retrieved_log.details['key1'] == 'value1'
    assert retrieved_log.details['key2'] == 42
    assert f"AuditLog(id={retrieved_log.id}, action_type='create', resource_type='user')" == repr(retrieved_log)
    action_types = [(AuditActionType.READ, 'read'), (AuditActionType.UPDATE, 'update'), (AuditActionType.DELETE, 'delete'), (AuditActionType.LOGIN, 'login'), (AuditActionType.LOGOUT, 'logout'), (AuditActionType.EXPORT, 'export'), (AuditActionType.IMPORT, 'import'), (AuditActionType.CONFIG, 'config'), (AuditActionType.SYSTEM, 'system'), (AuditActionType.PLUGIN, 'plugin'), (AuditActionType.CUSTOM, 'custom')]
    for action_type, value in action_types:
        log = AuditLog(action_type=action_type, resource_type='test', user_name='system')
        session.add(log)
    session.commit()
    for action_type, value in action_types:
        log = session.query(AuditLog).filter_by(action_type=action_type, resource_type='test').first()
        assert log is not None
        assert log.action_type.value == value