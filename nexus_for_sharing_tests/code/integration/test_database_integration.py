import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock
from nexus_core.core.config_manager import ConfigManager
from nexus_core.core.database_manager import DatabaseManager, Base
from nexus_core.models.user import User, UserRole
from nexus_core.models.system import SystemSetting
@pytest.fixture
def temp_db_file():
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)
@pytest.fixture
def db_config(temp_db_file):
    return {'type': 'sqlite', 'name': temp_db_file, 'echo': False}
@pytest.fixture
def config_manager_with_db(db_config):
    config_manager = MagicMock()
    config_manager.get.return_value = db_config
    return config_manager
@pytest.fixture
def db_manager(config_manager_with_db):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    db_mgr = DatabaseManager(config_manager_with_db, logger_manager)
    db_mgr.initialize()
    db_mgr.create_tables()
    yield db_mgr
    db_mgr.shutdown()
def test_user_crud_operations(db_manager):
    with db_manager.session() as session:
        user = User(username='testuser', email='test@example.com', hashed_password='hashed_password_here', roles=[UserRole.USER])
        session.add(user)
    with db_manager.session() as session:
        retrieved_user = session.query(User).filter_by(username='testuser').first()
        assert retrieved_user is not None
        assert retrieved_user.username == 'testuser'
        assert retrieved_user.email == 'test@example.com'
        assert retrieved_user.hashed_password == 'hashed_password_here'
        assert UserRole.USER in retrieved_user.roles
        assert retrieved_user.active is True
    with db_manager.session() as session:
        user_to_update = session.query(User).filter_by(username='testuser').first()
        user_to_update.email = 'updated@example.com'
        user_to_update.roles = [UserRole.ADMIN, UserRole.USER]
    with db_manager.session() as session:
        updated_user = session.query(User).filter_by(username='testuser').first()
        assert updated_user.email == 'updated@example.com'
        assert len(updated_user.roles) == 2
        assert UserRole.ADMIN in updated_user.roles
        assert UserRole.USER in updated_user.roles
    with db_manager.session() as session:
        user_to_delete = session.query(User).filter_by(username='testuser').first()
        session.delete(user_to_delete)
    with db_manager.session() as session:
        deleted_user = session.query(User).filter_by(username='testuser').first()
        assert deleted_user is None
def test_system_settings(db_manager):
    with db_manager.session() as session:
        session.add(SystemSetting(key='app.name', value='Test Application', description='Application name', is_secret=False, is_editable=True))
        session.add(SystemSetting(key='email.smtp_password', value='secret123', description='SMTP password', is_secret=True, is_editable=True))
    with db_manager.session() as session:
        app_name = session.query(SystemSetting).filter_by(key='app.name').first()
        assert app_name is not None
        assert app_name.value == 'Test Application'
        assert app_name.is_secret is False
        smtp_pass = session.query(SystemSetting).filter_by(key='email.smtp_password').first()
        assert smtp_pass is not None
        assert smtp_pass.value == 'secret123'
        assert smtp_pass.is_secret is True
    with db_manager.session() as session:
        app_name = session.query(SystemSetting).filter_by(key='app.name').first()
        app_name.value = 'Updated App Name'
    with db_manager.session() as session:
        updated_name = session.query(SystemSetting).filter_by(key='app.name').first()
        assert updated_name.value == 'Updated App Name'
def test_transaction_rollback(db_manager):
    with db_manager.session() as session:
        session.add(User(username='valid_user', email='valid@example.com', hashed_password='valid_hash'))
    try:
        with db_manager.session() as session:
            session.add(User(username='another_user', email='another@example.com', hashed_password='another_hash'))
            session.add(SystemSetting(key='invalid_key_without_dot', value='Test Value'))
    except:
        pass
    with db_manager.session() as session:
        valid_user = session.query(User).filter_by(username='valid_user').first()
        assert valid_user is not None
        another_user = session.query(User).filter_by(username='another_user').first()
        assert another_user is None
def test_query_with_joins(db_manager):
    with db_manager.session() as session:
        admin = User(username='admin_user', email='admin@example.com', hashed_password='admin_hash', roles=[UserRole.ADMIN])
        operator = User(username='operator_user', email='operator@example.com', hashed_password='operator_hash', roles=[UserRole.OPERATOR])
        regular = User(username='regular_user', email='regular@example.com', hashed_password='regular_hash', roles=[UserRole.USER])
        session.add_all([admin, operator, regular])
    admin_users = db_manager.execute_raw("\n        SELECT u.* FROM users u\n        JOIN user_roles ur ON u.id = ur.user_id\n        WHERE ur.role = 'admin'\n        ")
    assert len(admin_users) == 1
    assert admin_users[0]['username'] == 'admin_user'
    with db_manager.session() as session:
        import sqlalchemy as sa
        from sqlalchemy.orm import aliased
        user_alias = aliased(User)
        stmt = sa.select(user_alias, UserRole).join(user_alias.roles)
        results = session.execute(stmt).all()
        assert len(results) == 3
        role_counts = {}
        for user, role in results:
            if role not in role_counts:
                role_counts[role] = 0
            role_counts[role] += 1
        assert role_counts[UserRole.ADMIN] == 1
        assert role_counts[UserRole.OPERATOR] == 1
        assert role_counts[UserRole.USER] == 1
def test_concurrent_access(db_manager):
    import threading
    import random
    errors = []
    def worker_thread(thread_id):
        try:
            with db_manager.session() as session:
                session.add(User(username=f'thread_user_{thread_id}', email=f'thread{thread_id}@example.com', hashed_password=f'hash_{thread_id}'))
            with db_manager.session() as session:
                users = session.query(User).all()
                assert len(users) > 0
            time.sleep(random.uniform(0.01, 0.05))
            with db_manager.session() as session:
                session.add(SystemSetting(key=f'thread.setting.{thread_id}', value=f'Value from thread {thread_id}'))
        except Exception as e:
            errors.append(str(e))
    threads = []
    for i in range(10):
        thread = threading.Thread(target=worker_thread, args=(i,))
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, f'Errors occurred during concurrent access: {errors}'
    with db_manager.session() as session:
        user_count = session.query(User).count()
        assert user_count == 10
        settings_count = session.query(SystemSetting).count()
        assert settings_count == 10