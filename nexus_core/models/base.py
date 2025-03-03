"""Base classes for database models."""

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func

# Base class for all models
Base = declarative_base()

class TimestampMixin:
    """Mixin that adds created_at and updated_at columns to a model."""
    
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)