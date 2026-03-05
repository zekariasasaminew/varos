"""SQLAlchemy ORM models for users, API keys, and usage tracking."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship

from varos.api.database import Base


TIER_LIMITS = {
    "free": 10,
    "starter": 200,
    "pro": 2000,
    "enterprise": 999_999,
}


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, default="")
    organization = Column(String, default="")
    tier = Column(String, default="free")  # free | starter | pro | enterprise
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    api_key = relationship("ApiKey", back_populates="user", uselist=False, cascade="all, delete-orphan")
    usage_records = relationship("UsageRecord", back_populates="user", cascade="all, delete-orphan")

    @property
    def credits_limit(self) -> int:
        return TIER_LIMITS.get(self.tier, 10)

    @property
    def credits_used_this_month(self) -> int:
        now = datetime.now(timezone.utc)
        return sum(
            1 for r in self.usage_records
            if r.created_at.month == now.month and r.created_at.year == now.year
        )

    @property
    def credits_remaining(self) -> int:
        return max(0, self.credits_limit - self.credits_used_this_month)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="api_key")

    @staticmethod
    def generate() -> str:
        """Generate a new API key in the format vrs_XXXXXXXX."""
        return f"vrs_{secrets.token_urlsafe(32)}"


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    variant = Column(String, nullable=False)
    classification = Column(String, nullable=True)
    confidence = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="usage_records")
