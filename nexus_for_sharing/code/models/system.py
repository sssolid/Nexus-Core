from sqlalchemy import Column, Integer, String, JSON, Boolean
from sqlalchemy.orm import validates
from nexus_core.models.base import Base, TimestampMixin
class SystemSetting(Base, TimestampMixin):
    __tablename__ = 'system_settings'
    id = Column(Integer, primary_key=True)
    key = Column(String(128), unique=True, nullable=False, index=True)
    value = Column(JSON, nullable=True)
    description = Column(String(255), nullable=True)
    is_secret = Column(Boolean, default=False, nullable=False)
    is_editable = Column(Boolean, default=True, nullable=False)
    @validates('key')
    def validate_key(self, key, value):
        if not value or not isinstance(value, str) or '.' not in value:
            raise ValueError("Setting key must be in the format 'category.name'")
        return value.lower()
    def __repr__(self) -> str:
        if self.is_secret:
            return f"<SystemSetting(id={self.id}, key='{self.key}', value='******')>"
        return f"<SystemSetting(id={self.id}, key='{self.key}', value={str(self.value)[:50]})>"