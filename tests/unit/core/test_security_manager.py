"""Unit tests for the Security Manager."""

import pytest
import datetime
import time
import jwt
from unittest.mock import MagicMock, patch

from nexus_core.core.security_manager import SecurityManager, UserRole
from nexus_core.utils.exceptions import SecurityError


@pytest.fixture
def security_config():
    """Create a security configuration for testing."""
    return {
        "jwt": {
            "secret": "test_secret_key_that_is_long_enough_for_testing",
            "algorithm": "HS256",
            "access_token_expire_minutes": 30,
            "refresh_token_expire_days": 7
        },
        "password_policy": {
            "min_length": 8,
            "require_uppercase": True,
            "require_lowercase": True,
            "require_digit": True,
            "require_special": True
        }
    }


@pytest.fixture
def config_manager_mock(security_config):
    """Create a mock ConfigManager for the SecurityManager."""
    config_manager = MagicMock()
    config_manager.get.return_value = security_config
    return config_manager


@pytest.fixture
def security_manager(config_manager_mock):
    """Create a SecurityManager for testing."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    event_bus_manager = MagicMock()
    
    security_mgr = SecurityManager(
        config_manager_mock,
        logger_manager,
        event_bus_manager
    )
    security_mgr.initialize()
    
    yield security_mgr
    security_mgr.shutdown()


def test_security_manager_initialization(config_manager_mock):
    """Test that the SecurityManager initializes correctly."""
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    
    event_bus_manager = MagicMock()
    
    security_mgr = SecurityManager(
        config_manager_mock,
        logger_manager,
        event_bus_manager
    )
    security_mgr.initialize()
    
    assert security_mgr.initialized
    assert security_mgr.healthy
    
    # Default admin should be created
    assert len(security_mgr._users) > 0
    
    # Default permissions should be initialized
    assert len(security_mgr._permissions) > 0
    
    # Event subscription should be set up
    event_bus_manager.subscribe.assert_called_with(
        event_type='security/token_revoke',
        callback=security_mgr._on_token_revoke_event,
        subscriber_id='security_manager'
    )
    
    security_mgr.shutdown()
    assert not security_mgr.initialized


def test_create_user(security_manager):
    """Test creating a user."""
    # Create a test user
    user_id = security_manager.create_user(
        username="testuser",
        email="test@example.com",
        password="Password123!",
        roles=[UserRole.USER]
    )
    
    assert user_id is not None
    assert "testuser" in security_manager._username_to_id
    assert "test@example.com" in security_manager._email_to_id
    
    # Get user info
    user_info = security_manager.get_user_info(user_id)
    assert user_info is not None
    assert user_info["username"] == "testuser"
    assert user_info["email"] == "test@example.com"
    assert "USER" in user_info["roles"]
    assert user_info["active"] is True
    
    # Verify event was published
    security_manager._event_bus.publish.assert_called_with(
        event_type='security/user_created',
        source='security_manager',
        payload={
            'user_id': user_id,
            'username': 'testuser',
            'email': 'test@example.com',
            'roles': ['user']
        }
    )


def test_password_validation(security_manager):
    """Test password validation against the policy."""
    # Valid password
    valid_password = "Password123!"
    validation = security_manager._validate_password(valid_password)
    assert validation["valid"] is True
    
    # Test various invalid passwords
    test_cases = [
        ("short", "must be at least 8 characters"),
        ("password123!", "must contain at least one uppercase letter"),
        ("PASSWORD123!", "must contain at least one lowercase letter"),
        ("Password!!!", "must contain at least one digit"),
        ("Password123", "must contain at least one special character")
    ]
    
    for password, expected_reason in test_cases:
        validation = security_manager._validate_password(password)
        assert validation["valid"] is False
        assert expected_reason in validation["reason"]


def test_user_authentication(security_manager):
    """Test user authentication and token generation."""
    # Create a test user
    username = "authuser"
    email = "auth@example.com"
    password = "AuthPass123!"
    
    user_id = security_manager.create_user(
        username=username,
        email=email,
        password=password,
        roles=[UserRole.USER]
    )
    
    # Test successful authentication with username
    auth_result = security_manager.authenticate_user(username, password)
    assert auth_result is not None
    assert auth_result["user_id"] == user_id
    assert auth_result["username"] == username
    assert "access_token" in auth_result
    assert "refresh_token" in auth_result
    assert auth_result["token_type"] == "bearer"
    
    # Test successful authentication with email
    auth_result = security_manager.authenticate_user(email, password)
    assert auth_result is not None
    
    # Test failed authentication with wrong password
    auth_result = security_manager.authenticate_user(username, "WrongPass123!")
    assert auth_result is None
    
    # Test failed authentication with non-existent user
    auth_result = security_manager.authenticate_user("nonexistent", password)
    assert auth_result is None


def test_token_verification(security_manager):
    """Test token verification."""
    # Create a user and get a token
    username = "tokenuser"
    password = "TokenPass123!"
    
    user_id = security_manager.create_user(
        username=username,
        email="token@example.com",
        password=password,
        roles=[UserRole.USER]
    )
    
    auth_result = security_manager.authenticate_user(username, password)
    access_token = auth_result["access_token"]
    
    # Verify valid token
    token_data = security_manager.verify_token(access_token)
    assert token_data is not None
    assert token_data["sub"] == user_id
    assert "exp" in token_data
    assert "jti" in token_data
    
    # Verify with invalid token
    invalid_token = "invalid.token.string"
    token_data = security_manager.verify_token(invalid_token)
    assert token_data is None
    
    # Verify with expired token
    with patch('nexus_core.core.security_manager.jwt.decode') as mock_decode:
        mock_decode.side_effect = jwt.ExpiredSignatureError("Token expired")
        token_data = security_manager.verify_token(access_token)
        assert token_data is None


def test_token_refresh(security_manager):
    """Test refreshing an access token with a refresh token."""
    # Create a user and get tokens
    username = "refreshuser"
    password = "RefreshPass123!"
    
    user_id = security_manager.create_user(
        username=username,
        email="refresh@example.com",
        password=password,
        roles=[UserRole.USER]
    )
    
    auth_result = security_manager.authenticate_user(username, password)
    refresh_token = auth_result["refresh_token"]
    
    # Refresh the token
    refresh_result = security_manager.refresh_token(refresh_token)
    assert refresh_result is not None
    assert "access_token" in refresh_result
    assert refresh_result["token_type"] == "bearer"
    
    # Verify the new access token
    token_data = security_manager.verify_token(refresh_result["access_token"])
    assert token_data is not None
    assert token_data["sub"] == user_id
    
    # Test with invalid refresh token
    refresh_result = security_manager.refresh_token("invalid.refresh.token")
    assert refresh_result is None


def test_token_revocation(security_manager):
    """Test revoking tokens."""
    # Create a user and get tokens
    username = "revokeuser"
    password = "RevokePass123!"
    
    security_manager.create_user(
        username=username,
        email="revoke@example.com",
        password=password,
        roles=[UserRole.USER]
    )
    
    auth_result = security_manager.authenticate_user(username, password)
    access_token = auth_result["access_token"]
    
    # Verify token works before revocation
    assert security_manager.verify_token(access_token) is not None
    
    # Revoke the token
    result = security_manager.revoke_token(access_token)
    assert result is True
    
    # Verify token is now invalid
    assert security_manager.verify_token(access_token) is None
    
    # Test with already revoked token
    result = security_manager.revoke_token(access_token)
    assert result is False


def test_user_update(security_manager):
    """Test updating user information."""
    # Create a test user
    user_id = security_manager.create_user(
        username="updateuser",
        email="update@example.com",
        password="UpdatePass123!",
        roles=[UserRole.USER]
    )
    
    # Update username
    result = security_manager.update_user(user_id, {"username": "newusername"})
    assert result is True
    
    # Verify username was updated
    user_info = security_manager.get_user_info(user_id)
    assert user_info["username"] == "newusername"
    
    # Update email
    result = security_manager.update_user(user_id, {"email": "new@example.com"})
    assert result is True
    
    # Verify email was updated
    user_info = security_manager.get_user_info(user_id)
    assert user_info["email"] == "new@example.com"
    
    # Update password
    result = security_manager.update_user(user_id, {"password": "NewPass123!"})
    assert result is True
    
    # Verify password was updated by authenticating
    auth_result = security_manager.authenticate_user("newusername", "NewPass123!")
    assert auth_result is not None
    
    # Update roles
    result = security_manager.update_user(user_id, {"roles": ["admin"]})
    assert result is True
    
    # Verify roles were updated
    user_info = security_manager.get_user_info(user_id)
    assert "admin" in [r.lower() for r in user_info["roles"]]
    
    # Test update with invalid data
    with pytest.raises(SecurityError):
        security_manager.update_user(user_id, {"username": ""})


def test_user_deletion(security_manager):
    """Test deleting a user."""
    # Create a test user
    user_id = security_manager.create_user(
        username="deleteuser",
        email="delete@example.com",
        password="DeletePass123!",
        roles=[UserRole.USER]
    )
    
    # Verify user exists
    assert security_manager.get_user_info(user_id) is not None
    
    # Delete the user
    result = security_manager.delete_user(user_id)
    assert result is True
    
    # Verify user no longer exists
    assert security_manager.get_user_info(user_id) is None
    
    # Test deleting non-existent user
    with pytest.raises(SecurityError):
        security_manager.delete_user("nonexistent_id")


def test_permissions_and_roles(security_manager):
    """Test permission and role checking."""
    # Create users with different roles
    admin_id = security_manager.create_user(
        username="adminuser",
        email="admin@example.com",
        password="AdminPass123!",
        roles=[UserRole.ADMIN]
    )
    
    user_id = security_manager.create_user(
        username="regularuser",
        email="user@example.com",
        password="UserPass123!",
        roles=[UserRole.USER]
    )
    
    # Test role checking
    assert security_manager.has_role(admin_id, UserRole.ADMIN) is True
    assert security_manager.has_role(user_id, UserRole.ADMIN) is False
    assert security_manager.has_role(user_id, UserRole.USER) is True
    
    # Test permission checking - admin should have all permissions
    assert security_manager.has_permission(admin_id, "system", "manage") is True
    
    # Regular user should have limited permissions
    assert security_manager.has_permission(user_id, "system", "view") is True
    assert security_manager.has_permission(user_id, "system", "manage") is False
    
    # Test with non-existent user
    assert security_manager.has_permission("nonexistent", "system", "view") is False


def test_get_all_users(security_manager):
    """Test retrieving all users."""
    # Create some test users
    security_manager.create_user(
        username="user1",
        email="user1@example.com",
        password="User1Pass123!",
        roles=[UserRole.USER]
    )
    
    security_manager.create_user(
        username="user2",
        email="user2@example.com",
        password="User2Pass123!",
        roles=[UserRole.OPERATOR]
    )
    
    # Get all users
    users = security_manager.get_all_users()
    
    # There should be at least the two we created plus the default admin
    assert len(users) >= 3
    
    # Check for our test users
    usernames = [user["username"] for user in users]
    assert "user1" in usernames
    assert "user2" in usernames


def test_get_all_permissions(security_manager):
    """Test retrieving all permissions."""
    permissions = security_manager.get_all_permissions()
    
    # There should be several default permissions
    assert len(permissions) > 0
    
    # Check for common permission structure
    for perm in permissions:
        assert "id" in perm
        assert "name" in perm
        assert "description" in perm
        assert "resource" in perm
        assert "action" in perm
        assert "roles" in perm


def test_email_and_username_validation(security_manager):
    """Test validation of email and username formats."""
    # Valid formats
    assert security_manager._is_valid_username("valid_user") is True
    assert security_manager._is_valid_email("valid@example.com") is True
    
    # Invalid username formats
    assert security_manager._is_valid_username("") is False
    assert security_manager._is_valid_username("ab") is False  # Too short
    assert security_manager._is_valid_username("a" * 33) is False  # Too long
    assert security_manager._is_valid_username("invalid user") is False  # Contains space
    assert security_manager._is_valid_username("invalid@user") is False  # Contains @
    
    # Invalid email formats
    assert security_manager._is_valid_email("") is False
    assert security_manager._is_valid_email("invalidemail") is False
    assert security_manager._is_valid_email("invalid@") is False
    assert security_manager._is_valid_email("@example.com") is False
    assert security_manager._is_valid_email("invalid@example") is False


def test_uniqueness_constraints(security_manager):
    """Test that usernames and emails must be unique."""
    # Create initial user
    security_manager.create_user(
        username="uniqueuser",
        email="unique@example.com",
        password="UniquePass123!",
        roles=[UserRole.USER]
    )
    
    # Try to create user with same username
    with pytest.raises(SecurityError, match="already exists"):
        security_manager.create_user(
            username="uniqueuser",
            email="different@example.com",
            password="DifferentPass123!",
            roles=[UserRole.USER]
        )
    
    # Try to create user with same email
    with pytest.raises(SecurityError, match="already exists"):
        security_manager.create_user(
            username="differentuser",
            email="unique@example.com",
            password="DifferentPass123!",
            roles=[UserRole.USER]
        )


def test_config_change_handling(security_manager):
    """Test handling of configuration changes."""
    # Test changing JWT secret
    with patch.object(security_manager, '_revoke_user_tokens') as mock_revoke:
        security_manager._on_config_changed("security.jwt.secret", "new_secret")
        assert security_manager._jwt_secret == "new_secret"
        mock_revoke.assert_called()
    
    # Test changing JWT algorithm
    with patch.object(security_manager, '_revoke_user_tokens') as mock_revoke:
        security_manager._on_config_changed("security.jwt.algorithm", "HS512")
        assert security_manager._jwt_algorithm == "HS512"
        mock_revoke.assert_called()
    
    # Test changing token expiration
    security_manager._on_config_changed("security.jwt.access_token_expire_minutes", 60)
    assert security_manager._access_token_expire_minutes == 60
    
    security_manager._on_config_changed("security.jwt.refresh_token_expire_days", 14)
    assert security_manager._refresh_token_expire_days == 14
    
    # Test changing password policy
    security_manager._on_config_changed("security.password_policy.min_length", 10)
    assert security_manager._password_policy["min_length"] == 10


def test_security_manager_status(security_manager):
    """Test getting status from SecurityManager."""
    status = security_manager.status()
    
    assert status["name"] == "SecurityManager"
    assert status["initialized"] is True
    assert "storage" in status
    assert "users" in status
    assert "permissions" in status
    assert "tokens" in status
    assert "jwt" in status
