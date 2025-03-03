import pytest
import datetime
import time
import jwt
from unittest.mock import MagicMock, patch
from nexus_core.core.security_manager import SecurityManager, UserRole
from nexus_core.utils.exceptions import SecurityError
@pytest.fixture
def security_config():
    return {'jwt': {'secret': 'test_secret_key_that_is_long_enough_for_testing', 'algorithm': 'HS256', 'access_token_expire_minutes': 30, 'refresh_token_expire_days': 7}, 'password_policy': {'min_length': 8, 'require_uppercase': True, 'require_lowercase': True, 'require_digit': True, 'require_special': True}}
@pytest.fixture
def config_manager_mock(security_config):
    config_manager = MagicMock()
    config_manager.get.return_value = security_config
    return config_manager
@pytest.fixture
def security_manager(config_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    event_bus_manager = MagicMock()
    security_mgr = SecurityManager(config_manager_mock, logger_manager, event_bus_manager)
    security_mgr.initialize()
    yield security_mgr
    security_mgr.shutdown()
def test_security_manager_initialization(config_manager_mock):
    logger_manager = MagicMock()
    logger_manager.get_logger.return_value = MagicMock()
    event_bus_manager = MagicMock()
    security_mgr = SecurityManager(config_manager_mock, logger_manager, event_bus_manager)
    security_mgr.initialize()
    assert security_mgr.initialized
    assert security_mgr.healthy
    assert len(security_mgr._users) > 0
    assert len(security_mgr._permissions) > 0
    event_bus_manager.subscribe.assert_called_with(event_type='security/token_revoke', callback=security_mgr._on_token_revoke_event, subscriber_id='security_manager')
    security_mgr.shutdown()
    assert not security_mgr.initialized
def test_create_user(security_manager):
    user_id = security_manager.create_user(username='testuser', email='test@example.com', password='Password123!', roles=[UserRole.USER])
    assert user_id is not None
    assert 'testuser' in security_manager._username_to_id
    assert 'test@example.com' in security_manager._email_to_id
    user_info = security_manager.get_user_info(user_id)
    assert user_info is not None
    assert user_info['username'] == 'testuser'
    assert user_info['email'] == 'test@example.com'
    assert 'USER' in user_info['roles']
    assert user_info['active'] is True
    security_manager._event_bus.publish.assert_called_with(event_type='security/user_created', source='security_manager', payload={'user_id': user_id, 'username': 'testuser', 'email': 'test@example.com', 'roles': ['user']})
def test_password_validation(security_manager):
    valid_password = 'Password123!'
    validation = security_manager._validate_password(valid_password)
    assert validation['valid'] is True
    test_cases = [('short', 'must be at least 8 characters'), ('password123!', 'must contain at least one uppercase letter'), ('PASSWORD123!', 'must contain at least one lowercase letter'), ('Password!!!', 'must contain at least one digit'), ('Password123', 'must contain at least one special character')]
    for password, expected_reason in test_cases:
        validation = security_manager._validate_password(password)
        assert validation['valid'] is False
        assert expected_reason in validation['reason']
def test_user_authentication(security_manager):
    username = 'authuser'
    email = 'auth@example.com'
    password = 'AuthPass123!'
    user_id = security_manager.create_user(username=username, email=email, password=password, roles=[UserRole.USER])
    auth_result = security_manager.authenticate_user(username, password)
    assert auth_result is not None
    assert auth_result['user_id'] == user_id
    assert auth_result['username'] == username
    assert 'access_token' in auth_result
    assert 'refresh_token' in auth_result
    assert auth_result['token_type'] == 'bearer'
    auth_result = security_manager.authenticate_user(email, password)
    assert auth_result is not None
    auth_result = security_manager.authenticate_user(username, 'WrongPass123!')
    assert auth_result is None
    auth_result = security_manager.authenticate_user('nonexistent', password)
    assert auth_result is None
def test_token_verification(security_manager):
    username = 'tokenuser'
    password = 'TokenPass123!'
    user_id = security_manager.create_user(username=username, email='token@example.com', password=password, roles=[UserRole.USER])
    auth_result = security_manager.authenticate_user(username, password)
    access_token = auth_result['access_token']
    token_data = security_manager.verify_token(access_token)
    assert token_data is not None
    assert token_data['sub'] == user_id
    assert 'exp' in token_data
    assert 'jti' in token_data
    invalid_token = 'invalid.token.string'
    token_data = security_manager.verify_token(invalid_token)
    assert token_data is None
    with patch('nexus_core.core.security_manager.jwt.decode') as mock_decode:
        mock_decode.side_effect = jwt.ExpiredSignatureError('Token expired')
        token_data = security_manager.verify_token(access_token)
        assert token_data is None
def test_token_refresh(security_manager):
    username = 'refreshuser'
    password = 'RefreshPass123!'
    user_id = security_manager.create_user(username=username, email='refresh@example.com', password=password, roles=[UserRole.USER])
    auth_result = security_manager.authenticate_user(username, password)
    refresh_token = auth_result['refresh_token']
    refresh_result = security_manager.refresh_token(refresh_token)
    assert refresh_result is not None
    assert 'access_token' in refresh_result
    assert refresh_result['token_type'] == 'bearer'
    token_data = security_manager.verify_token(refresh_result['access_token'])
    assert token_data is not None
    assert token_data['sub'] == user_id
    refresh_result = security_manager.refresh_token('invalid.refresh.token')
    assert refresh_result is None
def test_token_revocation(security_manager):
    username = 'revokeuser'
    password = 'RevokePass123!'
    security_manager.create_user(username=username, email='revoke@example.com', password=password, roles=[UserRole.USER])
    auth_result = security_manager.authenticate_user(username, password)
    access_token = auth_result['access_token']
    assert security_manager.verify_token(access_token) is not None
    result = security_manager.revoke_token(access_token)
    assert result is True
    assert security_manager.verify_token(access_token) is None
    result = security_manager.revoke_token(access_token)
    assert result is False
def test_user_update(security_manager):
    user_id = security_manager.create_user(username='updateuser', email='update@example.com', password='UpdatePass123!', roles=[UserRole.USER])
    result = security_manager.update_user(user_id, {'username': 'newusername'})
    assert result is True
    user_info = security_manager.get_user_info(user_id)
    assert user_info['username'] == 'newusername'
    result = security_manager.update_user(user_id, {'email': 'new@example.com'})
    assert result is True
    user_info = security_manager.get_user_info(user_id)
    assert user_info['email'] == 'new@example.com'
    result = security_manager.update_user(user_id, {'password': 'NewPass123!'})
    assert result is True
    auth_result = security_manager.authenticate_user('newusername', 'NewPass123!')
    assert auth_result is not None
    result = security_manager.update_user(user_id, {'roles': ['admin']})
    assert result is True
    user_info = security_manager.get_user_info(user_id)
    assert 'admin' in [r.lower() for r in user_info['roles']]
    with pytest.raises(SecurityError):
        security_manager.update_user(user_id, {'username': ''})
def test_user_deletion(security_manager):
    user_id = security_manager.create_user(username='deleteuser', email='delete@example.com', password='DeletePass123!', roles=[UserRole.USER])
    assert security_manager.get_user_info(user_id) is not None
    result = security_manager.delete_user(user_id)
    assert result is True
    assert security_manager.get_user_info(user_id) is None
    with pytest.raises(SecurityError):
        security_manager.delete_user('nonexistent_id')
def test_permissions_and_roles(security_manager):
    admin_id = security_manager.create_user(username='adminuser', email='admin@example.com', password='AdminPass123!', roles=[UserRole.ADMIN])
    user_id = security_manager.create_user(username='regularuser', email='user@example.com', password='UserPass123!', roles=[UserRole.USER])
    assert security_manager.has_role(admin_id, UserRole.ADMIN) is True
    assert security_manager.has_role(user_id, UserRole.ADMIN) is False
    assert security_manager.has_role(user_id, UserRole.USER) is True
    assert security_manager.has_permission(admin_id, 'system', 'manage') is True
    assert security_manager.has_permission(user_id, 'system', 'view') is True
    assert security_manager.has_permission(user_id, 'system', 'manage') is False
    assert security_manager.has_permission('nonexistent', 'system', 'view') is False
def test_get_all_users(security_manager):
    security_manager.create_user(username='user1', email='user1@example.com', password='User1Pass123!', roles=[UserRole.USER])
    security_manager.create_user(username='user2', email='user2@example.com', password='User2Pass123!', roles=[UserRole.OPERATOR])
    users = security_manager.get_all_users()
    assert len(users) >= 3
    usernames = [user['username'] for user in users]
    assert 'user1' in usernames
    assert 'user2' in usernames
def test_get_all_permissions(security_manager):
    permissions = security_manager.get_all_permissions()
    assert len(permissions) > 0
    for perm in permissions:
        assert 'id' in perm
        assert 'name' in perm
        assert 'description' in perm
        assert 'resource' in perm
        assert 'action' in perm
        assert 'roles' in perm
def test_email_and_username_validation(security_manager):
    assert security_manager._is_valid_username('valid_user') is True
    assert security_manager._is_valid_email('valid@example.com') is True
    assert security_manager._is_valid_username('') is False
    assert security_manager._is_valid_username('ab') is False
    assert security_manager._is_valid_username('a' * 33) is False
    assert security_manager._is_valid_username('invalid user') is False
    assert security_manager._is_valid_username('invalid@user') is False
    assert security_manager._is_valid_email('') is False
    assert security_manager._is_valid_email('invalidemail') is False
    assert security_manager._is_valid_email('invalid@') is False
    assert security_manager._is_valid_email('@example.com') is False
    assert security_manager._is_valid_email('invalid@example') is False
def test_uniqueness_constraints(security_manager):
    security_manager.create_user(username='uniqueuser', email='unique@example.com', password='UniquePass123!', roles=[UserRole.USER])
    with pytest.raises(SecurityError, match='already exists'):
        security_manager.create_user(username='uniqueuser', email='different@example.com', password='DifferentPass123!', roles=[UserRole.USER])
    with pytest.raises(SecurityError, match='already exists'):
        security_manager.create_user(username='differentuser', email='unique@example.com', password='DifferentPass123!', roles=[UserRole.USER])
def test_config_change_handling(security_manager):
    with patch.object(security_manager, '_revoke_user_tokens') as mock_revoke:
        security_manager._on_config_changed('security.jwt.secret', 'new_secret')
        assert security_manager._jwt_secret == 'new_secret'
        mock_revoke.assert_called()
    with patch.object(security_manager, '_revoke_user_tokens') as mock_revoke:
        security_manager._on_config_changed('security.jwt.algorithm', 'HS512')
        assert security_manager._jwt_algorithm == 'HS512'
        mock_revoke.assert_called()
    security_manager._on_config_changed('security.jwt.access_token_expire_minutes', 60)
    assert security_manager._access_token_expire_minutes == 60
    security_manager._on_config_changed('security.jwt.refresh_token_expire_days', 14)
    assert security_manager._refresh_token_expire_days == 14
    security_manager._on_config_changed('security.password_policy.min_length', 10)
    assert security_manager._password_policy['min_length'] == 10
def test_security_manager_status(security_manager):
    status = security_manager.status()
    assert status['name'] == 'SecurityManager'
    assert status['initialized'] is True
    assert 'storage' in status
    assert 'users' in status
    assert 'permissions' in status
    assert 'tokens' in status
    assert 'jwt' in status