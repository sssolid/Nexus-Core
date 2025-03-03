import enum
from sqlalchemy import Column, Integer, String, DateTime, Enum, JSON, ForeignKey
from sqlalchemy.sql import func
from nexus_core.models.base import Base
class AuditActionType(enum.Enum):
    CREATE = 'create'
    READ = 'read'
    UPDATE = 'update'
    DELETE = 'delete'
    LOGIN = 'login'
    LOGOUT = 'logout'
    EXPORT = 'export'
    IMPORT = 'import'
    CONFIG = 'config'
    SYSTEM = 'system'
    PLUGIN = 'plugin'
    CUSTOM = 'custom'
class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=func.now(), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    user_name = Column(String(32), nullable=True)
    action_type = Column(Enum(AuditActionType), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(64), nullable=True)
    description = Column(String(255), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    details = Column(JSON, nullable=True)
    def __repr__(self) -> str:
        return f"<AuditLog(id={self.id}, action_type='{self.action_type.value}', resource_type='{self.resource_type}')>"