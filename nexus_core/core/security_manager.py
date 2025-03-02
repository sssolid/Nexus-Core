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
    """User roles for role-based access control."""
    
    ADMIN = "admin"  # Full system access
    OPERATOR = "operator"  # Can manage operations but not system configuration
    USER = "user"  # Regular user with limited access
    VIEWER = "viewer"  # Read-only access


@dataclass
class User:
    """Represents a user in the system."""
    
    id: str  # Unique identifier for the user
    username: str  # User's login name
    email: str  # User's email address
    hashed_password: str  # Hashed password
    roles: List[UserRole]  # User's assigned roles
    active: bool = True  # Whether the user account is active
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    last_login: Optional[datetime.datetime] = None  # Last successful login
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional user metadata


@dataclass
class Permission:
    """Represents a system permission that can be granted to roles."""
    
    id: str  # Unique identifier for the permission
    name: str  # Human-readable name of the permission
    description: str  # Description of what the permission allows
    resource: str  # The resource this permission applies to
    action: str  # The action this permission allows (create, read, update, delete, etc.)
    roles: List[UserRole] = field(default_factory=list)  # Roles that have this permission


@dataclass
class AuthToken:
    """Represents an authentication token."""
    
    token: str  # The JWT token string
    token_type: str  # Type of token (access, refresh)
    user_id: str  # ID of the user this token belongs to
    expires_at: datetime.datetime  # When the token expires
    issued_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    jti: str = field(default_factory=lambda: str(uuid.uuid4()))  # Unique token ID
    metadata: Dict[str, Any] = field(default_factory=dict)  # Additional token metadata


class SecurityManager(NexusManager):
    """Manages authentication, authorization, and security features.
    
    The Security Manager handles user authentication, role-based access control (RBAC),
    token management, and other security-related functionality for the Nexus Core system.
    """
    
    def __init__(
        self,
        config_manager: Any,
        logger_manager: Any,
        event_bus_manager: Any,
        db_manager: Optional[Any] = None,
    ) -> None:
        """Initialize the Security Manager.
        
        Args:
            config_manager: The Configuration Manager for security settings.
            logger_manager: The Logging Manager for logging.
            event_bus_manager: The Event Bus Manager for security events.
            db_manager: Optional Database Manager for persistent storage.
        """
        super().__init__(name="SecurityManager")
        self._config_manager = config_manager
        self._logger = logger_manager.get_logger("security_manager")
        self._event_bus = event_bus_manager
        self._db_manager = db_manager
        
        # Crypto context for password hashing
        self._pwd_context = CryptContext(
            schemes=["bcrypt"],
            deprecated="auto",
            bcrypt__rounds=12,
        )
        
        # In-memory storage for users, permissions, and tokens when no DB is available
        self._users: Dict[str, User] = {}
        self._username_to_id: Dict[str, str] = {}
        self._email_to_id: Dict[str, str] = {}
        self._permissions: Dict[str, Permission] = {}
        
        # Blacklisted tokens (for revoked tokens)
        self._token_blacklist: Set[str] = set()
        self._token_blacklist_lock = threading.RLock()
        
        # Active tokens by user id
        self._active_tokens: Dict[str, List[AuthToken]] = {}
        self._active_tokens_lock = threading.RLock()
        
        # JWT settings
        self._jwt_secret: Optional[str] = None
        self._jwt_algorithm = "HS256"
        self._access_token_expire_minutes = 30
        self._refresh_token_expire_days = 7
        
        # Password policy
        self._password_policy = {
            "min_length": 8,
            "require_uppercase": True,
            "require_lowercase": True,
            "require_digit": True,
            "require_special": True,
        }
        
        # Default permissions
        self._default_permissions: List[Permission] = []
        
        # Whether to use memory storage or database
        self._use_memory_storage = True
    
    def initialize(self) -> None:
        """Initialize the Security Manager.
        
        Sets up security configurations, creates default users and permissions if needed.
        
        Raises:
            ManagerInitializationError: If initialization fails.
        """
        try:
            # Get security configuration
            security_config = self._config_manager.get("security", {})
            
            # JWT configuration
            jwt_config = security_config.get("jwt", {})
            self._jwt_secret = jwt_config.get("secret")
            
            # If no secret is provided, generate one (for development only)
            if not self._jwt_secret:
                self._jwt_secret = secrets.token_hex(32)
                self._logger.warning(
                    "No JWT secret provided in configuration, generated a random one. "
                    "This is insecure for production use."
                )
            
            self._jwt_algorithm = jwt_config.get("algorithm", "HS256")
            self._access_token_expire_minutes = jwt_config.get("access_token_expire_minutes", 30)
            self._refresh_token_expire_days = jwt_config.get("refresh_token_expire_days", 7)
            
            # Password policy
            self._password_policy = security_config.get("password_policy", self._password_policy)
            
            # Determine if we should use database or memory storage
            self._use_memory_storage = self._db_manager is None
            
            # Initialize default permissions
            self._initialize_default_permissions()
            
            # Initialize default admin user if using memory storage and no users exist
            if self._use_memory_storage and not self._users:
                self._initialize_default_admin()
            
            # Subscribe to security-related events
            self._event_bus.subscribe(
                event_type="security/token_revoke",
                callback=self._on_token_revoke_event,
                subscriber_id="security_manager"
            )
            
            # Register for config changes
            self._config_manager.register_listener(
                "security", self._on_config_changed
            )
            
            self._initialized = True
            self._healthy = True
            
            self._logger.info("Security Manager initialized")
        
        except Exception as e:
            self._logger.error(f"Failed to initialize Security Manager: {str(e)}")
            raise ManagerInitializationError(
                f"Failed to initialize SecurityManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def _initialize_default_permissions(self) -> None:
        """Initialize the default set of permissions used in the system."""
        # System permissions
        self._add_permission(
            name="system.view",
            description="View system information and status",
            resource="system",
            action="view",
            roles=[UserRole.ADMIN, UserRole.OPERATOR, UserRole.USER]
        )
        
        self._add_permission(
            name="system.manage",
            description="Manage system configuration and settings",
            resource="system",
            action="manage",
            roles=[UserRole.ADMIN]
        )
        
        # User permissions
        self._add_permission(
            name="users.view",
            description="View user information",
            resource="users",
            action="view",
            roles=[UserRole.ADMIN, UserRole.OPERATOR]
        )
        
        self._add_permission(
            name="users.manage",
            description="Create, update, and delete users",
            resource="users",
            action="manage",
            roles=[UserRole.ADMIN]
        )
        
        # Plugin permissions
        self._add_permission(
            name="plugins.view",
            description="View plugin information",
            resource="plugins",
            action="view",
            roles=[UserRole.ADMIN, UserRole.OPERATOR, UserRole.USER]
        )
        
        self._add_permission(
            name="plugins.manage",
            description="Install, update, and remove plugins",
            resource="plugins",
            action="manage",
            roles=[UserRole.ADMIN]
        )
        
        # File permissions
        self._add_permission(
            name="files.view",
            description="View files and directories",
            resource="files",
            action="view",
            roles=[UserRole.ADMIN, UserRole.OPERATOR, UserRole.USER, UserRole.VIEWER]
        )
        
        self._add_permission(
            name="files.manage",
            description="Create, update, and delete files",
            resource="files",
            action="manage",
            roles=[UserRole.ADMIN, UserRole.OPERATOR, UserRole.USER]
        )
    
    def _initialize_default_admin(self) -> None:
        """Create a default admin user if no users exist."""
        try:
            # Create admin user with a default password
            default_admin_password = "admin"  # This should be changed after first login
            
            admin_user = self.create_user(
                username="admin",
                email="admin@example.com",
                password=default_admin_password,
                roles=[UserRole.ADMIN],
                metadata={"default_user": True}
            )
            
            if admin_user:
                self._logger.warning(
                    "Created default admin user with username 'admin' and password 'admin'. "
                    "Please change this password immediately."
                )
        
        except Exception as e:
            self._logger.error(f"Failed to create default admin user: {str(e)}")
    
    def _add_permission(
        self,
        name: str,
        description: str,
        resource: str,
        action: str,
        roles: List[UserRole],
    ) -> Permission:
        """Add a permission to the system.
        
        Args:
            name: Human-readable name of the permission.
            description: Description of what the permission allows.
            resource: The resource this permission applies to.
            action: The action this permission allows.
            roles: Roles that have this permission.
            
        Returns:
            Permission: The created permission.
        """
        permission_id = f"{resource}.{action}"
        
        permission = Permission(
            id=permission_id,
            name=name,
            description=description,
            resource=resource,
            action=action,
            roles=roles,
        )
        
        self._permissions[permission_id] = permission
        self._default_permissions.append(permission)
        
        return permission
    
    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        roles: List[UserRole],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Create a new user.
        
        Args:
            username: User's login name.
            email: User's email address.
            password: User's password.
            roles: List of roles to assign to the user.
            metadata: Optional additional user metadata.
            
        Returns:
            Optional[str]: The ID of the created user, or None if creation failed.
            
        Raises:
            SecurityError: If the user cannot be created.
        """
        if not self._initialized:
            raise SecurityError("Security Manager not initialized")
        
        # Validate username, email, and password
        if not username or not email or not password:
            raise SecurityError("Username, email, and password are required")
        
        if not self._is_valid_username(username):
            raise SecurityError(
                "Invalid username. Username must be 3-32 characters and can only contain "
                "letters, numbers, dots, hyphens, and underscores."
            )
        
        if not self._is_valid_email(email):
            raise SecurityError("Invalid email address")
        
        password_validation = self._validate_password(password)
        if not password_validation["valid"]:
            raise SecurityError(f"Invalid password: {password_validation['reason']}")
        
        if self._use_memory_storage:
            # Check if username or email already exists
            if username.lower() in self._username_to_id:
                raise SecurityError(f"Username '{username}' already exists")
            
            if email.lower() in self._email_to_id:
                raise SecurityError(f"Email '{email}' already exists")
            
            # Create the user
            user_id = str(uuid.uuid4())
            hashed_password = self._pwd_context.hash(password)
            
            user = User(
                id=user_id,
                username=username,
                email=email,
                hashed_password=hashed_password,
                roles=roles,
                active=True,
                metadata=metadata or {},
            )
            
            self._users[user_id] = user
            self._username_to_id[username.lower()] = user_id
            self._email_to_id[email.lower()] = user_id
            
            self._logger.info(
                f"Created user '{username}'",
                extra={"user_id": user_id, "email": email},
            )
            
            # Publish user created event
            self._event_bus.publish(
                event_type="security/user_created",
                source="security_manager",
                payload={
                    "user_id": user_id,
                    "username": username,
                    "email": email,
                    "roles": [role.value for role in roles],
                },
            )
            
            return user_id
        
        else:
            # TODO: Implement database-backed user creation
            self._logger.warning("Database-backed user creation not implemented yet")
            return None
    
    def authenticate_user(
        self,
        username_or_email: str,
        password: str,
    ) -> Optional[Dict[str, Any]]:
        """Authenticate a user with username/email and password.
        
        Args:
            username_or_email: User's login name or email address.
            password: User's password.
            
        Returns:
            Optional[Dict[str, Any]]: User information and tokens if authentication succeeds,
                                     None if authentication fails.
        """
        if not self._initialized:
            return None
        
        user = self._get_user_by_username_or_email(username_or_email)
        
        if not user:
            self._logger.warning(
                f"Authentication failed: User '{username_or_email}' not found",
                extra={"username_or_email": username_or_email},
            )
            return None
        
        if not user.active:
            self._logger.warning(
                f"Authentication failed: User '{username_or_email}' is inactive",
                extra={"username_or_email": username_or_email, "user_id": user.id},
            )
            return None
        
        if not self._verify_password(password, user.hashed_password):
            self._logger.warning(
                f"Authentication failed: Invalid password for user '{username_or_email}'",
                extra={"username_or_email": username_or_email, "user_id": user.id},
            )
            return None
        
        # Authentication successful, create tokens
        access_token = self._create_token(
            user_id=user.id,
            token_type="access",
            expires_delta=datetime.timedelta(minutes=self._access_token_expire_minutes),
        )
        
        refresh_token = self._create_token(
            user_id=user.id,
            token_type="refresh",
            expires_delta=datetime.timedelta(days=self._refresh_token_expire_days),
        )
        
        # Update last login time
        user.last_login = datetime.datetime.now()
        
        self._logger.info(
            f"User '{username_or_email}' authenticated successfully",
            extra={"username_or_email": username_or_email, "user_id": user.id},
        )
        
        # Publish login event
        self._event_bus.publish(
            event_type="security/user_login",
            source="security_manager",
            payload={
                "user_id": user.id,
                "username": user.username,
                "timestamp": user.last_login.isoformat(),
            },
        )
        
        # Return user info and tokens
        return {
            "user_id": user.id,
            "username": user.username,
            "email": user.email,
            "roles": [role.value for role in user.roles],
            "access_token": access_token.token,
            "token_type": "bearer",
            "expires_in": self._access_token_expire_minutes * 60,
            "refresh_token": refresh_token.token,
            "last_login": user.last_login.isoformat() if user.last_login else None,
        }
    
    def refresh_token(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Generate a new access token using a refresh token.
        
        Args:
            refresh_token: The refresh token to use for generating a new access token.
            
        Returns:
            Optional[Dict[str, Any]]: New access token info, or None if token is invalid.
        """
        if not self._initialized:
            return None
        
        try:
            # Verify the refresh token
            payload = self._verify_token(refresh_token)
            
            if not payload or payload.get("token_type") != "refresh":
                self._logger.warning(
                    "Token refresh failed: Invalid token or not a refresh token",
                    extra={"token_sub": payload.get("sub") if payload else None},
                )
                return None
            
            user_id = payload.get("sub")
            jti = payload.get("jti")
            
            # Check if token is blacklisted
            with self._token_blacklist_lock:
                if jti in self._token_blacklist:
                    self._logger.warning(
                        "Token refresh failed: Token is blacklisted",
                        extra={"token_sub": user_id, "jti": jti},
                    )
                    return None
            
            # Check if user exists and is active
            user = self._get_user_by_id(user_id) if user_id else None
            
            if not user or not user.active:
                self._logger.warning(
                    "Token refresh failed: User not found or inactive",
                    extra={"user_id": user_id},
                )
                return None
            
            # Create a new access token
            access_token = self._create_token(
                user_id=user.id,
                token_type="access",
                expires_delta=datetime.timedelta(minutes=self._access_token_expire_minutes),
            )
            
            self._logger.info(
                f"Generated new access token for user '{user.username}'",
                extra={"user_id": user.id},
            )
            
            # Return new access token info
            return {
                "access_token": access_token.token,
                "token_type": "bearer",
                "expires_in": self._access_token_expire_minutes * 60,
            }
        
        except Exception as e:
            self._logger.error(f"Error refreshing token: {str(e)}")
            return None
    
    def revoke_token(self, token: str) -> bool:
        """Revoke a token by adding it to the blacklist.
        
        Args:
            token: The token to revoke.
            
        Returns:
            bool: True if the token was revoked, False otherwise.
        """
        if not self._initialized:
            return False
        
        try:
            # Verify the token (but ignore expiration)
            payload = self._verify_token(token, verify_exp=False)
            
            if not payload:
                self._logger.warning("Token revocation failed: Invalid token")
                return False
            
            # Get the token ID (jti)
            jti = payload.get("jti")
            user_id = payload.get("sub")
            
            if not jti:
                self._logger.warning("Token revocation failed: Token has no JTI")
                return False
            
            # Add to blacklist
            with self._token_blacklist_lock:
                self._token_blacklist.add(jti)
            
            self._logger.info(
                "Token revoked successfully",
                extra={"jti": jti, "user_id": user_id},
            )
            
            # Publish token revoked event
            self._event_bus.publish(
                event_type="security/token_revoked",
                source="security_manager",
                payload={
                    "jti": jti,
                    "user_id": user_id,
                },
            )
            
            return True
        
        except Exception as e:
            self._logger.error(f"Error revoking token: {str(e)}")
            return False
    
    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Verify a JWT token and return its payload.
        
        Args:
            token: The JWT token to verify.
            
        Returns:
            Optional[Dict[str, Any]]: The decoded token payload,
                                     or None if verification fails.
        """
        return self._verify_token(token)
    
    def has_permission(
        self,
        user_id: str,
        resource: str,
        action: str,
    ) -> bool:
        """Check if a user has permission to perform an action on a resource.
        
        Args:
            user_id: The ID of the user to check.
            resource: The resource to check permission for.
            action: The action to check permission for.
            
        Returns:
            bool: True if the user has permission, False otherwise.
        """
        if not self._initialized:
            return False
        
        # Get the user
        user = self._get_user_by_id(user_id)
        
        if not user or not user.active:
            return False
        
        # Check if permission exists
        permission_id = f"{resource}.{action}"
        permission = self._permissions.get(permission_id)
        
        if not permission:
            return False
        
        # Check if user has any role with this permission
        for role in user.roles:
            if role in permission.roles:
                return True
        
        return False
    
    def has_role(self, user_id: str, role: UserRole) -> bool:
        """Check if a user has a specific role.
        
        Args:
            user_id: The ID of the user to check.
            role: The role to check for.
            
        Returns:
            bool: True if the user has the role, False otherwise.
        """
        if not self._initialized:
            return False
        
        # Get the user
        user = self._get_user_by_id(user_id)
        
        if not user or not user.active:
            return False
        
        return role in user.roles
    
    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get information about a user.
        
        Args:
            user_id: The ID of the user to get information for.
            
        Returns:
            Optional[Dict[str, Any]]: Information about the user,
                                     or None if the user is not found.
        """
        if not self._initialized:
            return None
        
        user = self._get_user_by_id(user_id)
        
        if not user:
            return None
        
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "roles": [role.value for role in user.roles],
            "active": user.active,
            "created_at": user.created_at.isoformat(),
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "metadata": user.metadata,
        }
    
    def update_user(
        self,
        user_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """Update user information.
        
        Args:
            user_id: The ID of the user to update.
            updates: Dict of fields to update. Can include:
                - username
                - email
                - password
                - roles
                - active
                - metadata
                
        Returns:
            bool: True if the user was updated, False otherwise.
            
        Raises:
            SecurityError: If the update fails.
        """
        if not self._initialized:
            raise SecurityError("Security Manager not initialized")
        
        if self._use_memory_storage:
            user = self._get_user_by_id(user_id)
            
            if not user:
                raise SecurityError(f"User with ID '{user_id}' not found")
            
            # Update fields
            if "username" in updates and updates["username"] != user.username:
                new_username = updates["username"]
                
                if not self._is_valid_username(new_username):
                    raise SecurityError("Invalid username format")
                
                # Check if username already exists
                if new_username.lower() in self._username_to_id and self._username_to_id[new_username.lower()] != user_id:
                    raise SecurityError(f"Username '{new_username}' already exists")
                
                # Remove old username mapping
                if user.username.lower() in self._username_to_id:
                    del self._username_to_id[user.username.lower()]
                
                # Update username
                user.username = new_username
                self._username_to_id[new_username.lower()] = user_id
            
            if "email" in updates and updates["email"] != user.email:
                new_email = updates["email"]
                
                if not self._is_valid_email(new_email):
                    raise SecurityError("Invalid email format")
                
                # Check if email already exists
                if new_email.lower() in self._email_to_id and self._email_to_id[new_email.lower()] != user_id:
                    raise SecurityError(f"Email '{new_email}' already exists")
                
                # Remove old email mapping
                if user.email.lower() in self._email_to_id:
                    del self._email_to_id[user.email.lower()]
                
                # Update email
                user.email = new_email
                self._email_to_id[new_email.lower()] = user_id
            
            if "password" in updates:
                password = updates["password"]
                
                # Validate password
                password_validation = self._validate_password(password)
                if not password_validation["valid"]:
                    raise SecurityError(f"Invalid password: {password_validation['reason']}")
                
                # Update password
                user.hashed_password = self._pwd_context.hash(password)
                
                # Revoke all tokens for this user
                self._revoke_user_tokens(user_id)
            
            if "roles" in updates:
                # Convert string roles to enum
                roles = []
                for role in updates["roles"]:
                    if isinstance(role, str):
                        try:
                            roles.append(UserRole(role))
                        except ValueError:
                            raise SecurityError(f"Invalid role: {role}")
                    elif isinstance(role, UserRole):
                        roles.append(role)
                    else:
                        raise SecurityError(f"Invalid role type: {type(role)}")
                
                # Update roles
                user.roles = roles
            
            if "active" in updates:
                user.active = bool(updates["active"])
                
                # If user is deactivated, revoke all tokens
                if not user.active:
                    self._revoke_user_tokens(user_id)
            
            if "metadata" in updates:
                # Update metadata (merge with existing)
                if updates["metadata"] is None:
                    user.metadata = {}
                else:
                    user.metadata.update(updates["metadata"])
            
            self._logger.info(
                f"Updated user '{user.username}'",
                extra={"user_id": user_id, "updated_fields": list(updates.keys())},
            )
            
            # Publish user updated event
            self._event_bus.publish(
                event_type="security/user_updated",
                source="security_manager",
                payload={
                    "user_id": user_id,
                    "username": user.username,
                    "updated_fields": list(updates.keys()),
                },
            )
            
            return True
        
        else:
            # TODO: Implement database-backed user updates
            self._logger.warning("Database-backed user updates not implemented yet")
            return False
    
    def delete_user(self, user_id: str) -> bool:
        """Delete a user.
        
        Args:
            user_id: The ID of the user to delete.
            
        Returns:
            bool: True if the user was deleted, False otherwise.
            
        Raises:
            SecurityError: If the deletion fails.
        """
        if not self._initialized:
            raise SecurityError("Security Manager not initialized")
        
        if self._use_memory_storage:
            user = self._get_user_by_id(user_id)
            
            if not user:
                raise SecurityError(f"User with ID '{user_id}' not found")
            
            # Remove username and email mappings
            if user.username.lower() in self._username_to_id:
                del self._username_to_id[user.username.lower()]
            
            if user.email.lower() in self._email_to_id:
                del self._email_to_id[user.email.lower()]
            
            # Remove user
            del self._users[user_id]
            
            # Revoke all tokens for this user
            self._revoke_user_tokens(user_id)
            
            self._logger.info(
                f"Deleted user '{user.username}'",
                extra={"user_id": user_id},
            )
            
            # Publish user deleted event
            self._event_bus.publish(
                event_type="security/user_deleted",
                source="security_manager",
                payload={
                    "user_id": user_id,
                    "username": user.username,
                },
            )
            
            return True
        
        else:
            # TODO: Implement database-backed user deletion
            self._logger.warning("Database-backed user deletion not implemented yet")
            return False
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """Get information about all users.
        
        Returns:
            List[Dict[str, Any]]: List of user information dictionaries.
        """
        if not self._initialized:
            return []
        
        result = []
        
        if self._use_memory_storage:
            for user in self._users.values():
                result.append({
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "roles": [role.value for role in user.roles],
                    "active": user.active,
                    "created_at": user.created_at.isoformat(),
                    "last_login": user.last_login.isoformat() if user.last_login else None,
                })
        
        else:
            # TODO: Implement database-backed user listing
            self._logger.warning("Database-backed user listing not implemented yet")
        
        return result
    
    def get_all_permissions(self) -> List[Dict[str, Any]]:
        """Get information about all permissions.
        
        Returns:
            List[Dict[str, Any]]: List of permission information dictionaries.
        """
        if not self._initialized:
            return []
        
        result = []
        
        for permission in self._permissions.values():
            result.append({
                "id": permission.id,
                "name": permission.name,
                "description": permission.description,
                "resource": permission.resource,
                "action": permission.action,
                "roles": [role.value for role in permission.roles],
            })
        
        return result
    
    def _get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get a user by ID.
        
        Args:
            user_id: The ID of the user to get.
            
        Returns:
            Optional[User]: The user object, or None if not found.
        """
        if self._use_memory_storage:
            return self._users.get(user_id)
        
        else:
            # TODO: Implement database-backed user retrieval
            return None
    
    def _get_user_by_username_or_email(self, username_or_email: str) -> Optional[User]:
        """Get a user by username or email.
        
        Args:
            username_or_email: The username or email of the user to get.
            
        Returns:
            Optional[User]: The user object, or None if not found.
        """
        if self._use_memory_storage:
            # Try username first
            user_id = self._username_to_id.get(username_or_email.lower())
            
            if not user_id:
                # Try email
                user_id = self._email_to_id.get(username_or_email.lower())
            
            if user_id:
                return self._users.get(user_id)
            
            return None
        
        else:
            # TODO: Implement database-backed user retrieval
            return None
    
    def _verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against its hash.
        
        Args:
            plain_password: The plain text password to verify.
            hashed_password: The hashed password to compare against.
            
        Returns:
            bool: True if the password matches, False otherwise.
        """
        return self._pwd_context.verify(plain_password, hashed_password)
    
    def _validate_password(self, password: str) -> Dict[str, Any]:
        """Validate a password against the password policy.
        
        Args:
            password: The password to validate.
            
        Returns:
            Dict[str, Any]: Dictionary with validation result:
                - valid: bool - Whether the password is valid
                - reason: str - Reason for failure if invalid
        """
        if not password:
            return {"valid": False, "reason": "Password cannot be empty"}
        
        # Check minimum length
        min_length = self._password_policy.get("min_length", 8)
        if len(password) < min_length:
            return {
                "valid": False,
                "reason": f"Password must be at least {min_length} characters long",
            }
        
        # Check for uppercase letters
        if (self._password_policy.get("require_uppercase", True)
                and not any(c.isupper() for c in password)):
            return {
                "valid": False,
                "reason": "Password must contain at least one uppercase letter",
            }
        
        # Check for lowercase letters
        if (self._password_policy.get("require_lowercase", True)
                and not any(c.islower() for c in password)):
            return {
                "valid": False,
                "reason": "Password must contain at least one lowercase letter",
            }
        
        # Check for digits
        if (self._password_policy.get("require_digit", True)
                and not any(c.isdigit() for c in password)):
            return {
                "valid": False,
                "reason": "Password must contain at least one digit",
            }
        
        # Check for special characters
        if self._password_policy.get("require_special", True):
            special_chars = "!@#$%^&*()_-+={}[]\\|:;\"'<>,.?/"
            if not any(c in special_chars for c in password):
                return {
                    "valid": False,
                    "reason": "Password must contain at least one special character",
                }
        
        return {"valid": True}
    
    def _is_valid_username(self, username: str) -> bool:
        """Check if a username is valid.
        
        Args:
            username: The username to check.
            
        Returns:
            bool: True if the username is valid, False otherwise.
        """
        if not username:
            return False
        
        # Check length
        if len(username) < 3 or len(username) > 32:
            return False
        
        # Check pattern (letters, numbers, dots, hyphens, underscores)
        username_pattern = r"^[a-zA-Z0-9._-]+$"
        return bool(re.match(username_pattern, username))
    
    def _is_valid_email(self, email: str) -> bool:
        """Check if an email address is valid.
        
        Args:
            email: The email address to check.
            
        Returns:
            bool: True if the email is valid, False otherwise.
        """
        if not email:
            return False
        
        # Simple email validation pattern
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(email_pattern, email))
    
    def _create_token(
        self,
        user_id: str,
        token_type: str,
        expires_delta: datetime.timedelta,
    ) -> AuthToken:
        """Create a JWT token.
        
        Args:
            user_id: The ID of the user the token is for.
            token_type: The type of token (access or refresh).
            expires_delta: How long the token is valid for.
            
        Returns:
            AuthToken: The created token.
            
        Raises:
            SecurityError: If the token cannot be created.
        """
        if not self._jwt_secret:
            raise SecurityError("JWT secret not configured")
        
        # Get current time
        issued_at = datetime.datetime.now(datetime.timezone.utc)
        expiration = issued_at + expires_delta
        
        # Generate token ID
        jti = str(uuid.uuid4())
        
        # Create JWT payload
        payload = {
            "sub": user_id,
            "iat": issued_at.timestamp(),
            "exp": expiration.timestamp(),
            "jti": jti,
            "token_type": token_type,
        }
        
        # Create JWT token
        token = jwt.encode(payload, self._jwt_secret, algorithm=self._jwt_algorithm)
        
        # Create AuthToken object
        auth_token = AuthToken(
            token=token,
            token_type=token_type,
            user_id=user_id,
            issued_at=issued_at,
            expires_at=expiration,
            jti=jti,
        )
        
        # Store the token
        with self._active_tokens_lock:
            if user_id not in self._active_tokens:
                self._active_tokens[user_id] = []
            
            self._active_tokens[user_id].append(auth_token)
        
        return auth_token
    
    def _verify_token(
        self,
        token: str,
        verify_exp: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """Verify a JWT token and return its payload.
        
        Args:
            token: The JWT token to verify.
            verify_exp: Whether to verify that the token has not expired.
            
        Returns:
            Optional[Dict[str, Any]]: The decoded token payload,
                                     or None if verification fails.
        """
        if not self._jwt_secret:
            self._logger.error("JWT secret not configured")
            return None
        
        try:
            # Decode and verify the token
            payload = jwt.decode(
                token,
                self._jwt_secret,
                algorithms=[self._jwt_algorithm],
                options={"verify_exp": verify_exp},
            )
            
            # Check if token is blacklisted
            jti = payload.get("jti")
            if jti:
                with self._token_blacklist_lock:
                    if jti in self._token_blacklist:
                        self._logger.warning(
                            "Token validation failed: Token is blacklisted",
                            extra={"jti": jti},
                        )
                        return None
            
            return payload
        
        except jwt.ExpiredSignatureError:
            self._logger.warning("Token validation failed: Token has expired")
            return None
        
        except jwt.InvalidTokenError as e:
            self._logger.warning(f"Token validation failed: {str(e)}")
            return None
        
        except Exception as e:
            self._logger.error(f"Error verifying token: {str(e)}")
            return None
    
    def _revoke_user_tokens(self, user_id: str) -> None:
        """Revoke all tokens for a user.
        
        Args:
            user_id: The ID of the user whose tokens to revoke.
        """
        with self._active_tokens_lock:
            # Get tokens for the user
            tokens = self._active_tokens.get(user_id, [])
            
            # Add all token JTIs to blacklist
            with self._token_blacklist_lock:
                for token in tokens:
                    self._token_blacklist.add(token.jti)
            
            # Remove tokens from active tokens
            self._active_tokens.pop(user_id, None)
        
        self._logger.info(
            f"Revoked all tokens for user {user_id}",
            extra={"user_id": user_id},
        )
    
    def _on_token_revoke_event(self, event: Any) -> None:
        """Handle token revocation events.
        
        Args:
            event: The token revocation event.
        """
        payload = event.payload
        token = payload.get("token")
        
        if not token:
            self._logger.error(
                "Invalid token revocation event: Missing token",
                extra={"event_id": event.event_id},
            )
            return
        
        self.revoke_token(token)
    
    def _on_config_changed(self, key: str, value: Any) -> None:
        """Handle configuration changes for security.
        
        Args:
            key: The configuration key that changed.
            value: The new value.
        """
        if key == "security.jwt.secret":
            self._jwt_secret = value
            self._logger.info("Updated JWT secret")
            
            # Revoke all tokens when secret changes
            with self._active_tokens_lock:
                for user_id in list(self._active_tokens.keys()):
                    self._revoke_user_tokens(user_id)
        
        elif key == "security.jwt.algorithm":
            self._jwt_algorithm = value
            self._logger.info(f"Updated JWT algorithm to {value}")
            
            # Revoke all tokens when algorithm changes
            with self._active_tokens_lock:
                for user_id in list(self._active_tokens.keys()):
                    self._revoke_user_tokens(user_id)
        
        elif key == "security.jwt.access_token_expire_minutes":
            self._access_token_expire_minutes = value
            self._logger.info(f"Updated access token expiration to {value} minutes")
        
        elif key == "security.jwt.refresh_token_expire_days":
            self._refresh_token_expire_days = value
            self._logger.info(f"Updated refresh token expiration to {value} days")
        
        elif key.startswith("security.password_policy."):
            policy_name = key.split(".")[-1]
            if policy_name in self._password_policy:
                self._password_policy[policy_name] = value
                self._logger.info(f"Updated password policy: {policy_name} = {value}")
    
    def shutdown(self) -> None:
        """Shut down the Security Manager.
        
        Cleans up resources and prepares for shutdown.
        
        Raises:
            ManagerShutdownError: If shutdown fails.
        """
        if not self._initialized:
            return
        
        try:
            self._logger.info("Shutting down Security Manager")
            
            # Unregister from event bus
            self._event_bus.unsubscribe("security_manager")
            
            # Unregister config listener
            self._config_manager.unregister_listener("security", self._on_config_changed)
            
            # Clear in-memory data if using memory storage
            if self._use_memory_storage:
                self._users.clear()
                self._username_to_id.clear()
                self._email_to_id.clear()
            
            # Clear token data
            with self._token_blacklist_lock:
                self._token_blacklist.clear()
            
            with self._active_tokens_lock:
                self._active_tokens.clear()
            
            self._initialized = False
            self._healthy = False
            
            self._logger.info("Security Manager shut down successfully")
        
        except Exception as e:
            self._logger.error(f"Failed to shut down Security Manager: {str(e)}")
            raise ManagerShutdownError(
                f"Failed to shut down SecurityManager: {str(e)}",
                manager_name=self.name,
            ) from e
    
    def status(self) -> Dict[str, Any]:
        """Get the status of the Security Manager.
        
        Returns:
            Dict[str, Any]: Status information about the Security Manager.
        """
        status = super().status()
        
        if self._initialized:
            status.update({
                "storage": "memory" if self._use_memory_storage else "database",
                "users": {
                    "count": len(self._users) if self._use_memory_storage else 0,
                },
                "permissions": {
                    "count": len(self._permissions),
                },
                "tokens": {
                    "active": sum(len(tokens) for tokens in self._active_tokens.values()),
                    "blacklisted": len(self._token_blacklist),
                },
                "jwt": {
                    "algorithm": self._jwt_algorithm,
                    "access_token_expire_minutes": self._access_token_expire_minutes,
                    "refresh_token_expire_days": self._refresh_token_expire_days,
                },
            })
        
        return status
