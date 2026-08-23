"""SQLAlchemy declarative base for ARC models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all persisted ARC models."""
