"""Integration tests for the database subsystem."""

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
    """Create a temporary SQLite database file."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def db_config(temp_db_file):
    """Create a database configuration for testing with a file-based SQLite database."""
    return {
        "type": "sqlite",
        "name": temp_db_file,
        "echo": False
    }


@pytest.fixture
def config_manager_with_db(db_config):
    """Create a ConfigManager with database settings."""
    config_manager = MagicMock()
    config_manager.get.return_value = db_config
    return config_manager


@pytest.fixture
def db_manager(config_manager_with_db):
    """Create a DatabaseManager with a file-based SQLite database."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    db_mgr = DatabaseManager(config_manager_with_db, logger_manager)
    db_mgr.initialize()
    db_mgr.create_tables()
    
    yield db_mgr
    db_mgr.shutdown()


def test_user_crud_operations(db_manager):
    """Test CRUD operations for the User model."""
    # Create a user
    with db_manager.session() as session:
        user = User(
            username="testuser",
            email="test@example.com",
            hashed_password="hashed_password_here",
            roles=[UserRole.USER]
        )
        session.add(user)
    
    # Read the user
    with db_manager.session() as session:
        retrieved_user = session.query(User).filter_by(username="testuser").first()
        assert retrieved_user is not None
        assert retrieved_user.username == "testuser"
        assert retrieved_user.email == "test@example.com"
        assert retrieved_user.hashed_password == "hashed_password_here"
        assert UserRole.USER in retrieved_user.roles
        assert retrieved_user.active is True  # Default value
    
    # Update the user
    with db_manager.session() as session:
        user_to_update = session.query(User).filter_by(username="testuser").first()
        user_to_update.email = "updated@example.com"
        user_to_update.roles = [UserRole.ADMIN, UserRole.USER]
    
    # Verify update
    with db_manager.session() as session:
        updated_user = session.query(User).filter_by(username="testuser").first()
        assert updated_user.email == "updated@example.com"
        assert len(updated_user.roles) == 2
        assert UserRole.ADMIN in updated_user.roles
        assert UserRole.USER in updated_user.roles
    
    # Delete the user
    with db_manager.session() as session:
        user_to_delete = session.query(User).filter_by(username="testuser").first()
        session.delete(user_to_delete)
    
    # Verify deletion
    with db_manager.session() as session:
        deleted_user = session.query(User).filter_by(username="testuser").first()
        assert deleted_user is None


def test_system_settings(db_manager):
    """Test operations for the SystemSetting model."""
    # Create settings
    with db_manager.session() as session:
        session.add(SystemSetting(
            key="app.name",
            value="Test Application",
            description="Application name",
            is_secret=False,
            is_editable=True
        ))
        session.add(SystemSetting(
            key="email.smtp_password",
            value="secret123",
            description="SMTP password",
            is_secret=True,
            is_editable=True
        ))
    
    # Read settings
    with db_manager.session() as session:
        app_name = session.query(SystemSetting).filter_by(key="app.name").first()
        assert app_name is not None
        assert app_name.value == "Test Application"
        assert app_name.is_secret is False
        
        smtp_pass = session.query(SystemSetting).filter_by(key="email.smtp_password").first()
        assert smtp_pass is not None
        assert smtp_pass.value == "secret123"
        assert smtp_pass.is_secret is True
    
    # Update setting
    with db_manager.session() as session:
        app_name = session.query(SystemSetting).filter_by(key="app.name").first()
        app_name.value = "Updated App Name"
    
    # Verify update
    with db_manager.session() as session:
        updated_name = session.query(SystemSetting).filter_by(key="app.name").first()
        assert updated_name.value == "Updated App Name"


def test_transaction_rollback(db_manager):
    """Test transaction rollback with multiple models."""
    # First add a valid user
    with db_manager.session() as session:
        session.add(User(
            username="valid_user",
            email="valid@example.com",
            hashed_password="valid_hash"
        ))
    
    # Try to add a setting with an invalid key (missing dot)
    try:
        with db_manager.session() as session:
            # Add another valid user
            session.add(User(
                username="another_user",
                email="another@example.com",
                hashed_password="another_hash"
            ))
            
            # Add invalid setting - this should trigger a validation error and rollback
            session.add(SystemSetting(
                key="invalid_key_without_dot",  # Invalid key format
                value="Test Value"
            ))
    except:
        pass  # Expected exception
    
    # Verify the entire transaction was rolled back
    with db_manager.session() as session:
        # First user should still exist
        valid_user = session.query(User).filter_by(username="valid_user").first()
        assert valid_user is not None
        
        # Second user should not exist due to rollback
        another_user = session.query(User).filter_by(username="another_user").first()
        assert another_user is None


def test_query_with_joins(db_manager):
    """Test complex queries with joins."""
    # Create test data
    with db_manager.session() as session:
        # Add users with different roles
        admin = User(
            username="admin_user",
            email="admin@example.com",
            hashed_password="admin_hash",
            roles=[UserRole.ADMIN]
        )
        operator = User(
            username="operator_user",
            email="operator@example.com",
            hashed_password="operator_hash",
            roles=[UserRole.OPERATOR]
        )
        regular = User(
            username="regular_user",
            email="regular@example.com",
            hashed_password="regular_hash",
            roles=[UserRole.USER]
        )
        
        session.add_all([admin, operator, regular])
    
    # Query using raw SQL to find users with specific roles
    admin_users = db_manager.execute_raw(
        """
        SELECT u.* FROM users u
        JOIN user_roles ur ON u.id = ur.user_id
        WHERE ur.role = 'admin'
        """
    )
    
    assert len(admin_users) == 1
    assert admin_users[0]["username"] == "admin_user"
    
    # Query using SQLAlchemy
    with db_manager.session() as session:
        import sqlalchemy as sa
        from sqlalchemy.orm import aliased
        
        # Query to find all users with their roles
        user_alias = aliased(User)
        stmt = sa.select(user_alias, UserRole).join(
            user_alias.roles
        )
        
        results = session.execute(stmt).all()
        
        # There should be 3 users with roles
        assert len(results) == 3
        
        # Extract role counts
        role_counts = {}
        for user, role in results:
            if role not in role_counts:
                role_counts[role] = 0
            role_counts[role] += 1
        
        assert role_counts[UserRole.ADMIN] == 1
        assert role_counts[UserRole.OPERATOR] == 1
        assert role_counts[UserRole.USER] == 1


def test_concurrent_access(db_manager):
    """Test concurrent database access."""
    import threading
    import random
    
    # Flag to track if errors occurred
    errors = []
    
    # Function to be run in multiple threads
    def worker_thread(thread_id):
        try:
            # Add a user
            with db_manager.session() as session:
                session.add(User(
                    username=f"thread_user_{thread_id}",
                    email=f"thread{thread_id}@example.com",
                    hashed_password=f"hash_{thread_id}"
                ))
            
            # Read data
            with db_manager.session() as session:
                users = session.query(User).all()
                assert len(users) > 0
            
            # Random delay
            time.sleep(random.uniform(0.01, 0.05))
            
            # Add a system setting
            with db_manager.session() as session:
                session.add(SystemSetting(
                    key=f"thread.setting.{thread_id}",
                    value=f"Value from thread {thread_id}"
                ))
        except Exception as e:
            errors.append(str(e))
    
    # Create and start threads
    threads = []
    for i in range(10):
        thread = threading.Thread(target=worker_thread, args=(i,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    # Check for errors
    assert not errors, f"Errors occurred during concurrent access: {errors}"
    
    # Verify that all data was written correctly
    with db_manager.session() as session:
        user_count = session.query(User).count()
        assert user_count == 10
        
        settings_count = session.query(SystemSetting).count()
        assert settings_count == 10
