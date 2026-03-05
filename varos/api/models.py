"""SQLAlchemy ORM models for users, API keys, usage tracking, and organizations."""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship

from varos.api.database import Base


# Individual user quotas (variants/month)
TIER_LIMITS = {
    "free": 10,
    "starter": 200,
    "pro": 2000,
    "enterprise": 999_999,
}

# Organization-level quotas (shared pool across all members, variants/month)
ORG_TIER_LIMITS = {
    "team": 10_000,       # $299/mo, 5 seats
    "lab": 999_999,       # $999/mo, 20 seats, unlimited
    "oncology": 2_000,    # $499/mo, somatic-only
    "enterprise": 999_999,
}

# Seat limits per org tier
ORG_SEAT_LIMITS = {
    "team": 5,
    "lab": 20,
    "oncology": 5,
    "enterprise": 999,
}


class Organization(Base):
    """A lab or company that groups users under shared quota + billing."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True, index=True, nullable=False)
    tier = Column(String, default="team")  # team | lab | oncology | enterprise
    stripe_customer_id = Column(String, nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    memberships = relationship("Membership", back_populates="org", cascade="all, delete-orphan")

    @property
    def max_seats(self) -> int:
        return ORG_SEAT_LIMITS.get(self.tier, 5)

    @property
    def credits_limit(self) -> int:
        return ORG_TIER_LIMITS.get(self.tier, 10_000)

    @property
    def credits_used_this_month(self) -> int:
        now = datetime.now(timezone.utc)
        total = 0
        for m in self.memberships:
            if m.user:
                total += sum(
                    1 for r in m.user.usage_records
                    if r.created_at.month == now.month and r.created_at.year == now.year
                )
        return total

    @property
    def credits_remaining(self) -> int:
        return max(0, self.credits_limit - self.credits_used_this_month)


class Membership(Base):
    """Association between a User and an Organization with a role."""
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True, index=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # null = pending invite
    role = Column(String, default="analyst")  # owner | analyst | viewer
    invite_email = Column(String, nullable=True)
    invite_token = Column(String, nullable=True, unique=True, index=True)
    joined_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    org = relationship("Organization", back_populates="memberships")
    user = relationship("User", back_populates="memberships")


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
    memberships = relationship("Membership", back_populates="user")

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
