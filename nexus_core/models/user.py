"""User model for authentication and authorization."""

import enum
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Table, Boolean
from sqlalchemy.orm import relationship

from nexus_core.models.base import Base, TimestampMixin

class UserRole(enum.Enum):
    """User roles for role-based access control."""
    
    ADMIN = "admin"
    OPERATOR = "operator"
    USER = "user"
    VIEWER = "viewer"

# Association table for user-role many-to-many relationship
user_roles = Table(
    'user_roles',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id'), primary_key=True),
    Column('role', Enum(UserRole), primary_key=True)
)

class User(Base, TimestampMixin):
    """User model for authentication and authorization."""
    
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    last_login = Column(DateTime, nullable=True)
    
    # Relationships
    roles = relationship('UserRole', secondary=user_roles, backref='users')
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}')>"