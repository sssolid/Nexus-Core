from sqlalchemy import Column, Integer, String, Boolean, JSON, ForeignKey
from sqlalchemy.orm import relationship
from nexus_core.models.base import Base, TimestampMixin
class Plugin(Base, TimestampMixin):
    __tablename__ = 'plugins'
    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)
    version = Column(String(32), nullable=False)
    description = Column(String(255), nullable=True)
    author = Column(String(128), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    installed_path = Column(String(255), nullable=True)
    configuration = Column(JSON, nullable=True)
    def __repr__(self) -> str:
        return f"<Plugin(id={self.id}, name='{self.name}', version='{self.version}')>"