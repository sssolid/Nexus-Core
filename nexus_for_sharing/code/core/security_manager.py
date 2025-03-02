from __future__ import annotations
import datetime
import hashlib
import os
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union, cast
import jwt
from passlib.context import CryptContext
from nexus_core.core.base import NexusManager
from nexus_core.utils.exceptions import ManagerInitializationError, ManagerShutdownError, SecurityError
class UserRole(Enum):
    ADMIN = 'admin'
    OPERATOR = 'operator'
    USER = 'user'
    VIEWER = 'viewer'
@dataclass
class User:
    id: str
    username: str
    email: str
    hashed_password: str
    roles: List[UserRole]
    active: bool = True
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    last_login: Optional[datetime.datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
@dataclass
class Permission:
    id: str
    name: str
    description: str
    resource: str
    action: str
    roles: List[UserRole] = field(default_factory=list)
@dataclass
class AuthToken:
    token: str
    token_type: str
    user_id: str
    expires_at: datetime.datetime
    issued_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    jti: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: Dict[str, Any] = field(default_factory=dict)
class SecurityManager(NexusManager):
    def __init__(self, config_manager: Any, logger_manager: Any, event_bus_manager: Any, db_manager: Optional[Any]=None) -> None:
        super().__init__(name='SecurityManager')
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger('security_manager')
        self._event_bus = event_bus_manager
        self._db_manager = db_manager
        self._pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto', bcrypt__rounds=12)
        self._users: Dict[str, User] = {}
        self._username_to_id: Dict[str, str] = {}
        self._email_to_id: Dict[str, str] = {}
        self._permissions: Dict[str, Permission] = {}
        self._token_blacklist: Set[str] = set()
        self._token_blacklist_lock = threading.RLock()
        self._active_tokens: Dict[str, List[AuthToken]] = {}
        self._active_tokens_lock = threading.RLock()
        self._jwt_secret: Optional[str] = None
        self._jwt_algorithm = 'HS256'
        self._access_token_expire_minutes = 30
        self._refresh_token_expire_days = 7
        self._password_policy = {'min_length': 8, 'require_uppercase': True, 'require_lowercase': True, 'require_digit': True, 'require_special': True}
        self._default_permissions: List[Permission] = []
        self._use_memory_storage = True
    def initialize(self) -> None:
        try:
            security_config = self._config_manager.get('security', {})
            jwt_config = security_config.get('jwt', {})
            self._jwt_secret = jwt_config.get('secret')
            if not self._jwt_secret:
                self._jwt_secret = secrets.token_hex(32)
                self._logger.warning('No JWT secret provided in configuration, generated a random one. This is insecure for production use.')
            self._jwt_algorithm = jwt_config.get('algorithm', 'HS256')
            self._access_token_expire_minutes = jwt_config.get('access_token_expire_minutes', 30)
            self._refresh_token_expire_days = jwt_config.get('refresh_token_expire_days', 7)
            self._password_policy = security_config.get('password_policy', self._password_policy)
            self._use_memory_storage = self._db_manager is None
            self._initialize_default_permissions()
            if self._use_memory_storage and (not self._users):
                self._initialize_default_admin()
            self._event_bus.subscribe(event_type='security/token_revoke', callback=self._on_token_revoke_event, subscriber_id='security_manager')
            self._config_manager.register_listener('security', self._on_config_changed)
            self._initialized = True
            self._healthy = True
            self._logger.info('Security Manager initialized')
        except Exception as e:
            self._logger.error(f'Failed to initialize Security Manager: {str(e)}')
            raise ManagerInitializationError(f'Failed to initialize SecurityManager: {str(e)}', manager_name=self.name) from e
    def _initialize_default_permissions(self) -> None:
        self._add_permission(name='system.view', description='View system information and status', resource='system', action='view', roles=[UserRole.ADMIN, UserRole.OPERATOR, UserRole.USER])
        self._add_permission(name='system.manage', description='Manage system configuration and settings', resource='system', action='manage', roles=[UserRole.ADMIN])
        self._add_permission(name='users.view', description='View user information', resource='users', action='view', roles=[UserRole.ADMIN, UserRole.OPERATOR])
        self._add_permission(name='users.manage', description='Create, update, and delete users', resource='users', action='manage', roles=[UserRole.ADMIN])
        self._add_permission(name='plugins.view', description='View plugin information', resource='plugins', action='view', roles=[UserRole.ADMIN, UserRole.OPERATOR, UserRole.USER])
        self._add_permission(name='plugins.manage', description='Install, update, and remove plugins', resource='plugins', action='manage', roles=[UserRole.ADMIN])
        self._add_permission(name='files.view', description='View files and directories', resource='files', action='view', roles=[UserRole.ADMIN, UserRole.OPERATOR, UserRole.USER, UserRole.VIEWER])
        self._add_permission(name='files.manage', description='Create, update, and delete files', resource='files', action='manage', roles=[UserRole.ADMIN, UserRole.OPERATOR, UserRole.USER])
    def _initialize_default_admin(self) -> None:
        try:
            default_admin_password = 'admin'
            admin_user = self.create_user(username='admin', email='admin@example.com', password=default_admin_password, roles=[UserRole.ADMIN], metadata={'default_user': True})
            if admin_user:
                self._logger.warning("Created default admin user with username 'admin' and password 'admin'. Please change this password immediately.")
        except Exception as e:
            self._logger.error(f'Failed to create default admin user: {str(e)}')
    def _add_permission(self, name: str, description: str, resource: str, action: str, roles: List[UserRole]) -> Permission:
        permission_id = f'{resource}.{action}'
        permission = Permission(id=permission_id, name=name, description=description, resource=resource, action=action, roles=roles)
        self._permissions[permission_id] = permission
        self._default_permissions.append(permission)
        return permission
    def create_user(self, username: str, email: str, password: str, roles: List[UserRole], metadata: Optional[Dict[str, Any]]=None) -> Optional[str]:
        if not self._initialized:
            raise SecurityError('Security Manager not initialized')
        if not username or not email or (not password):
            raise SecurityError('Username, email, and password are required')
        if not self._is_valid_username(username):
            raise SecurityError('Invalid username. Username must be 3-32 characters and can only contain letters, numbers, dots, hyphens, and underscores.')
        if not self._is_valid_email(email):
            raise SecurityError('Invalid email address')
        password_validation = self._validate_password(password)
        if not password_validation['valid']:
            raise SecurityError(f"Invalid password: {password_validation['reason']}")
        if self._use_memory_storage:
            if username.lower() in self._username_to_id:
                raise SecurityError(f"Username '{username}' already exists")
            if email.lower() in self._email_to_id:
                raise SecurityError(f"Email '{email}' already exists")
            user_id = str(uuid.uuid4())
            hashed_password = self._pwd_context.hash(password)
            user = User(id=user_id, username=username, email=email, hashed_password=hashed_password, roles=roles, active=True, metadata=metadata or {})
            self._users[user_id] = user
            self._username_to_id[username.lower()] = user_id
            self._email_to_id[email.lower()] = user_id
            self._logger.info(f"Created user '{username}'", extra={'user_id': user_id, 'email': email})
            self._event_bus.publish(event_type='security/user_created', source='security_manager', payload={'user_id': user_id, 'username': username, 'email': email, 'roles': [role.value for role in roles]})
            return user_id
        else:
            self._logger.warning('Database-backed user creation not implemented yet')
            return None
    def authenticate_user(self, username_or_email: str, password: str) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            return None
        user = self._get_user_by_username_or_email(username_or_email)
        if not user:
            self._logger.warning(f"Authentication failed: User '{username_or_email}' not found", extra={'username_or_email': username_or_email})
            return None
        if not user.active:
            self._logger.warning(f"Authentication failed: User '{username_or_email}' is inactive", extra={'username_or_email': username_or_email, 'user_id': user.id})
            return None
        if not self._verify_password(password, user.hashed_password):
            self._logger.warning(f"Authentication failed: Invalid password for user '{username_or_email}'", extra={'username_or_email': username_or_email, 'user_id': user.id})
            return None
        access_token = self._create_token(user_id=user.id, token_type='access', expires_delta=datetime.timedelta(minutes=self._access_token_expire_minutes))
        refresh_token = self._create_token(user_id=user.id, token_type='refresh', expires_delta=datetime.timedelta(days=self._refresh_token_expire_days))
        user.last_login = datetime.datetime.now()
        self._logger.info(f"User '{username_or_email}' authenticated successfully", extra={'username_or_email': username_or_email, 'user_id': user.id})
        self._event_bus.publish(event_type='security/user_login', source='security_manager', payload={'user_id': user.id, 'username': user.username, 'timestamp': user.last_login.isoformat()})
        return {'user_id': user.id, 'username': user.username, 'email': user.email, 'roles': [role.value for role in user.roles], 'access_token': access_token.token, 'token_type': 'bearer', 'expires_in': self._access_token_expire_minutes * 60, 'refresh_token': refresh_token.token, 'last_login': user.last_login.isoformat() if user.last_login else None}
    def refresh_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            return None
        try:
            payload = self._verify_token(refresh_token)
            if not payload or payload.get('token_type') != 'refresh':
                self._logger.warning('Token refresh failed: Invalid token or not a refresh token', extra={'token_sub': payload.get('sub') if payload else None})
                return None
            user_id = payload.get('sub')
            jti = payload.get('jti')
            with self._token_blacklist_lock:
                if jti in self._token_blacklist:
                    self._logger.warning('Token refresh failed: Token is blacklisted', extra={'token_sub': user_id, 'jti': jti})
                    return None
            user = self._get_user_by_id(user_id) if user_id else None
            if not user or not user.active:
                self._logger.warning('Token refresh failed: User not found or inactive', extra={'user_id': user_id})
                return None
            access_token = self._create_token(user_id=user.id, token_type='access', expires_delta=datetime.timedelta(minutes=self._access_token_expire_minutes))
            self._logger.info(f"Generated new access token for user '{user.username}'", extra={'user_id': user.id})
            return {'access_token': access_token.token, 'token_type': 'bearer', 'expires_in': self._access_token_expire_minutes * 60}
        except Exception as e:
            self._logger.error(f'Error refreshing token: {str(e)}')
            return None
    def revoke_token(self, token: str) -> bool:
        if not self._initialized:
            return False
        try:
            payload = self._verify_token(token, verify_exp=False)
            if not payload:
                self._logger.warning('Token revocation failed: Invalid token')
                return False
            jti = payload.get('jti')
            user_id = payload.get('sub')
            if not jti:
                self._logger.warning('Token revocation failed: Token has no JTI')
                return False
            with self._token_blacklist_lock:
                self._token_blacklist.add(jti)
            self._logger.info('Token revoked successfully', extra={'jti': jti, 'user_id': user_id})
            self._event_bus.publish(event_type='security/token_revoked', source='security_manager', payload={'jti': jti, 'user_id': user_id})
            return True
        except Exception as e:
            self._logger.error(f'Error revoking token: {str(e)}')
            return False
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        return self._verify_token(token)
    def has_permission(self, user_id: str, resource: str, action: str) -> bool:
        if not self._initialized:
            return False
        user = self._get_user_by_id(user_id)
        if not user or not user.active:
            return False
        permission_id = f'{resource}.{action}'
        permission = self._permissions.get(permission_id)
        if not permission:
            return False
        for role in user.roles:
            if role in permission.roles:
                return True
        return False
    def has_role(self, user_id: str, role: UserRole) -> bool:
        if not self._initialized:
            return False
        user = self._get_user_by_id(user_id)
        if not user or not user.active:
            return False
        return role in user.roles
    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            return None
        user = self._get_user_by_id(user_id)
        if not user:
            return None
        return {'id': user.id, 'username': user.username, 'email': user.email, 'roles': [role.value for role in user.roles], 'active': user.active, 'created_at': user.created_at.isoformat(), 'last_login': user.last_login.isoformat() if user.last_login else None, 'metadata': user.metadata}
    def update_user(self, user_id: str, updates: Dict[str, Any]) -> bool:
        if not self._initialized:
            raise SecurityError('Security Manager not initialized')
        if self._use_memory_storage:
            user = self._get_user_by_id(user_id)
            if not user:
                raise SecurityError(f"User with ID '{user_id}' not found")
            if 'username' in updates and updates['username'] != user.username:
                new_username = updates['username']
                if not self._is_valid_username(new_username):
                    raise SecurityError('Invalid username format')
                if new_username.lower() in self._username_to_id and self._username_to_id[new_username.lower()] != user_id:
                    raise SecurityError(f"Username '{new_username}' already exists")
                if user.username.lower() in self._username_to_id:
                    del self._username_to_id[user.username.lower()]
                user.username = new_username
                self._username_to_id[new_username.lower()] = user_id
            if 'email' in updates and updates['email'] != user.email:
                new_email = updates['email']
                if not self._is_valid_email(new_email):
                    raise SecurityError('Invalid email format')
                if new_email.lower() in self._email_to_id and self._email_to_id[new_email.lower()] != user_id:
                    raise SecurityError(f"Email '{new_email}' already exists")
                if user.email.lower() in self._email_to_id:
                    del self._email_to_id[user.email.lower()]
                user.email = new_email
                self._email_to_id[new_email.lower()] = user_id
            if 'password' in updates:
                password = updates['password']
                password_validation = self._validate_password(password)
                if not password_validation['valid']:
                    raise SecurityError(f"Invalid password: {password_validation['reason']}")
                user.hashed_password = self._pwd_context.hash(password)
                self._revoke_user_tokens(user_id)
            if 'roles' in updates:
                roles = []
                for role in updates['roles']:
                    if isinstance(role, str):
                        try:
                            roles.append(UserRole(role))
                        except ValueError:
                            raise SecurityError(f'Invalid role: {role}')
                    elif isinstance(role, UserRole):
                        roles.append(role)
                    else:
                        raise SecurityError(f'Invalid role type: {type(role)}')
                user.roles = roles
            if 'active' in updates:
                user.active = bool(updates['active'])
                if not user.active:
                    self._revoke_user_tokens(user_id)
            if 'metadata' in updates:
                if updates['metadata'] is None:
                    user.metadata = {}
                else:
                    user.metadata.update(updates['metadata'])
            self._logger.info(f"Updated user '{user.username}'", extra={'user_id': user_id, 'updated_fields': list(updates.keys())})
            self._event_bus.publish(event_type='security/user_updated', source='security_manager', payload={'user_id': user_id, 'username': user.username, 'updated_fields': list(updates.keys())})
            return True
        else:
            self._logger.warning('Database-backed user updates not implemented yet')
            return False
    def delete_user(self, user_id: str) -> bool:
        if not self._initialized:
            raise SecurityError('Security Manager not initialized')
        if self._use_memory_storage:
            user = self._get_user_by_id(user_id)
            if not user:
                raise SecurityError(f"User with ID '{user_id}' not found")
            if user.username.lower() in self._username_to_id:
                del self._username_to_id[user.username.lower()]
            if user.email.lower() in self._email_to_id:
                del self._email_to_id[user.email.lower()]
            del self._users[user_id]
            self._revoke_user_tokens(user_id)
            self._logger.info(f"Deleted user '{user.username}'", extra={'user_id': user_id})
            self._event_bus.publish(event_type='security/user_deleted', source='security_manager', payload={'user_id': user_id, 'username': user.username})
            return True
        else:
            self._logger.warning('Database-backed user deletion not implemented yet')
            return False
    def get_all_users(self) -> List[Dict[str, Any]]:
        if not self._initialized:
            return []
        result = []
        if self._use_memory_storage:
            for user in self._users.values():
                result.append({'id': user.id, 'username': user.username, 'email': user.email, 'roles': [role.value for role in user.roles], 'active': user.active, 'created_at': user.created_at.isoformat(), 'last_login': user.last_login.isoformat() if user.last_login else None})
        else:
            self._logger.warning('Database-backed user listing not implemented yet')
        return result
    def get_all_permissions(self) -> List[Dict[str, Any]]:
        if not self._initialized:
            return []
        result = []
        for permission in self._permissions.values():
            result.append({'id': permission.id, 'name': permission.name, 'description': permission.description, 'resource': permission.resource, 'action': permission.action, 'roles': [role.value for role in permission.roles]})
        return result
    def _get_user_by_id(self, user_id: str) -> Optional[User]:
        if self._use_memory_storage:
            return self._users.get(user_id)
        else:
            return None
    def _get_user_by_username_or_email(self, username_or_email: str) -> Optional[User]:
        if self._use_memory_storage:
            user_id = self._username_to_id.get(username_or_email.lower())
            if not user_id:
                user_id = self._email_to_id.get(username_or_email.lower())
            if user_id:
                return self._users.get(user_id)
            return None
        else:
            return None
    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        return self._pwd_context.verify(plain_password, hashed_password)
    def _validate_password(self, password: str) -> Dict[str, Any]:
        if not password:
            return {'valid': False, 'reason': 'Password cannot be empty'}
        min_length = self._password_policy.get('min_length', 8)
        if len(password) < min_length:
            return {'valid': False, 'reason': f'Password must be at least {min_length} characters long'}
        if self._password_policy.get('require_uppercase', True) and (not any((c.isupper() for c in password))):
            return {'valid': False, 'reason': 'Password must contain at least one uppercase letter'}
        if self._password_policy.get('require_lowercase', True) and (not any((c.islower() for c in password))):
            return {'valid': False, 'reason': 'Password must contain at least one lowercase letter'}
        if self._password_policy.get('require_digit', True) and (not any((c.isdigit() for c in password))):
            return {'valid': False, 'reason': 'Password must contain at least one digit'}
        if self._password_policy.get('require_special', True):
            special_chars = '!@#$%^&*()_-+={}[]\\|:;"\'<>,.?/'
            if not any((c in special_chars for c in password)):
                return {'valid': False, 'reason': 'Password must contain at least one special character'}
        return {'valid': True}
    def _is_valid_username(self, username: str) -> bool:
        if not username:
            return False
        if len(username) < 3 or len(username) > 32:
            return False
        username_pattern = '^[a-zA-Z0-9._-]+$'
        return bool(re.match(username_pattern, username))
    def _is_valid_email(self, email: str) -> bool:
        if not email:
            return False
        email_pattern = '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'
        return bool(re.match(email_pattern, email))
    def _create_token(self, user_id: str, token_type: str, expires_delta: datetime.timedelta) -> AuthToken:
        if not self._jwt_secret:
            raise SecurityError('JWT secret not configured')
        issued_at = datetime.datetime.now(datetime.timezone.utc)
        expiration = issued_at + expires_delta
        jti = str(uuid.uuid4())
        payload = {'sub': user_id, 'iat': issued_at.timestamp(), 'exp': expiration.timestamp(), 'jti': jti, 'token_type': token_type}
        token = jwt.encode(payload, self._jwt_secret, algorithm=self._jwt_algorithm)
        auth_token = AuthToken(token=token, token_type=token_type, user_id=user_id, issued_at=issued_at, expires_at=expiration, jti=jti)
        with self._active_tokens_lock:
            if user_id not in self._active_tokens:
                self._active_tokens[user_id] = []
            self._active_tokens[user_id].append(auth_token)
        return auth_token
    def _verify_token(self, token: str, verify_exp: bool=True) -> Optional[Dict[str, Any]]:
        if not self._jwt_secret:
            self._logger.error('JWT secret not configured')
            return None
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=[self._jwt_algorithm], options={'verify_exp': verify_exp})
            jti = payload.get('jti')
            if jti:
                with self._token_blacklist_lock:
                    if jti in self._token_blacklist:
                        self._logger.warning('Token validation failed: Token is blacklisted', extra={'jti': jti})
                        return None
            return payload
        except jwt.ExpiredSignatureError:
            self._logger.warning('Token validation failed: Token has expired')
            return None
        except jwt.InvalidTokenError as e:
            self._logger.warning(f'Token validation failed: {str(e)}')
            return None
        except Exception as e:
            self._logger.error(f'Error verifying token: {str(e)}')
            return None
    def _revoke_user_tokens(self, user_id: str) -> None:
        with self._active_tokens_lock:
            tokens = self._active_tokens.get(user_id, [])
            with self._token_blacklist_lock:
                for token in tokens:
                    self._token_blacklist.add(token.jti)
            self._active_tokens.pop(user_id, None)
        self._logger.info(f'Revoked all tokens for user {user_id}', extra={'user_id': user_id})
    def _on_token_revoke_event(self, event: Any) -> None:
        payload = event.payload
        token = payload.get('token')
        if not token:
            self._logger.error('Invalid token revocation event: Missing token', extra={'event_id': event.event_id})
            return
        self.revoke_token(token)
    def _on_config_changed(self, key: str, value: Any) -> None:
        if key == 'security.jwt.secret':
            self._jwt_secret = value
            self._logger.info('Updated JWT secret')
            with self._active_tokens_lock:
                for user_id in list(self._active_tokens.keys()):
                    self._revoke_user_tokens(user_id)
        elif key == 'security.jwt.algorithm':
            self._jwt_algorithm = value
            self._logger.info(f'Updated JWT algorithm to {value}')
            with self._active_tokens_lock:
                for user_id in list(self._active_tokens.keys()):
                    self._revoke_user_tokens(user_id)
        elif key == 'security.jwt.access_token_expire_minutes':
            self._access_token_expire_minutes = value
            self._logger.info(f'Updated access token expiration to {value} minutes')
        elif key == 'security.jwt.refresh_token_expire_days':
            self._refresh_token_expire_days = value
            self._logger.info(f'Updated refresh token expiration to {value} days')
        elif key.startswith('security.password_policy.'):
            policy_name = key.split('.')[-1]
            if policy_name in self._password_policy:
                self._password_policy[policy_name] = value
                self._logger.info(f'Updated password policy: {policy_name} = {value}')
    def shutdown(self) -> None:
        if not self._initialized:
            return
        try:
            self._logger.info('Shutting down Security Manager')
            self._event_bus.unsubscribe('security_manager')
            self._config_manager.unregister_listener('security', self._on_config_changed)
            if self._use_memory_storage:
                self._users.clear()
                self._username_to_id.clear()
                self._email_to_id.clear()
            with self._token_blacklist_lock:
                self._token_blacklist.clear()
            with self._active_tokens_lock:
                self._active_tokens.clear()
            self._initialized = False
            self._healthy = False
            self._logger.info('Security Manager shut down successfully')
        except Exception as e:
            self._logger.error(f'Failed to shut down Security Manager: {str(e)}')
            raise ManagerShutdownError(f'Failed to shut down SecurityManager: {str(e)}', manager_name=self.name) from e
    def status(self) -> Dict[str, Any]:
        status = super().status()
        if self._initialized:
            status.update({'storage': 'memory' if self._use_memory_storage else 'database', 'users': {'count': len(self._users) if self._use_memory_storage else 0}, 'permissions': {'count': len(self._permissions)}, 'tokens': {'active': sum((len(tokens) for tokens in self._active_tokens.values())), 'blacklisted': len(self._token_blacklist)}, 'jwt': {'algorithm': self._jwt_algorithm, 'access_token_expire_minutes': self._access_token_expire_minutes, 'refresh_token_expire_days': self._refresh_token_expire_days}})
        return status