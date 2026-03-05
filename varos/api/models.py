"""SQLAlchemy ORM models for users, API keys, usage tracking, organizations, and audit logs."""

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
    watches = relationship("ReclassificationWatch", back_populates="user", cascade="all, delete-orphan")
    batch_jobs = relationship("BatchJob", back_populates="user", cascade="all, delete-orphan")

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


class ReclassificationWatch(Base):
    """A user's subscription to reclassification alerts for a specific variant."""
    __tablename__ = "reclassification_watches"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # HGVS genomic notation, e.g. "NM_007294.4:c.5266dupC"
    variant_hgvs = Column(String, nullable=False, index=True)
    gene = Column(String, nullable=True)
    # Classification at time of subscription
    original_classification = Column(String, nullable=True)
    # Latest known ClinVar classification (updated by weekly sync job)
    current_classification = Column(String, nullable=True)
    # ClinVar variation ID for efficient lookup
    clinvar_variation_id = Column(String, nullable=True, index=True)
    # Webhook URL to POST to on reclassification (optional)
    webhook_url = Column(String, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    alerted_at = Column(DateTime, nullable=True)  # last time an alert was sent
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="watches")


class BatchJob(Base):
    """Async batch VCF classification job."""
    __tablename__ = "batch_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String, unique=True, index=True, nullable=False)  # UUID4
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, default="queued")  # queued | processing | complete | failed
    # Input stats
    vcf_filename = Column(String, nullable=True)
    total_variants = Column(Integer, default=0)
    filtered_variants = Column(Integer, default=0)  # after pre-filter
    processed_variants = Column(Integer, default=0)
    failed_variants = Column(Integer, default=0)
    # Classification mode
    mode = Column(String, default="germline")  # germline | somatic
    # Results as JSON blob (for small jobs); large jobs use file storage
    results_json = Column(Text, nullable=True)
    error_message = Column(String, nullable=True)
    webhook_url = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="batch_jobs")


class NetworkShare(Base):
    """
    VAROS Network — opt-in de-identified variant sharing.

    Labs that opt in to network sharing contribute anonymized classifications.
    In exchange they get:
    - GET /v1/network/consensus/{hash} — see how other labs classified the same variant
    - 20% quota discount (in billing layer)
    - Priority queue for batch jobs

    Privacy: only variant_hash (SHA-256 of canonical HGVS) is stored,
    never the raw HGVS. Org name is never exposed; only org_id is used
    for deduplication (so each org's classification counts once).
    """
    __tablename__ = "network_shares"

    id = Column(Integer, primary_key=True, index=True)
    # SHA-256 of canonical HGVS (e.g. sha256("NM_007294.4:c.5266dupC"))
    variant_hash = Column(String, nullable=False, index=True)
    # Raw HGVS kept for internal use only (never returned in consensus API)
    variant_hgvs = Column(String, nullable=False)
    gene = Column(String, nullable=True, index=True)
    # Normalized VAROS classification (Pathogenic, Likely Pathogenic, etc.)
    classification = Column(String, nullable=False)
    # ACMG criteria triggered (comma-separated codes, e.g. "PVS1,PM2,PP3")
    criteria_codes = Column(String, nullable=True)
    # Classification confidence (0–100)
    confidence = Column(Integer, default=0)
    # Org that contributed (for deduplication, never exposed in API)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    # User that contributed (if not org member)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Genome build: GRCh37 or GRCh38
    genome_build = Column(String, default="GRCh38")
    # True = user opted in to sharing this specific variant
    is_shared = Column(Boolean, default=True)
    shared_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # ClinVar variation ID if known (helps network correlation)
    clinvar_variation_id = Column(String, nullable=True)

    org = relationship("Organization", backref="network_shares")
    user = relationship("User", backref="network_shares")


class AuditLog(Base):
    """
    Immutable audit log for classification and admin actions.

    Required for HIPAA-module compliance add-on (Phase 3C).
    Available now but exposed as a premium feature only.

    Actions logged:
    - variant.classified        — variant classification completed
    - variant.report_downloaded — PDF or HTML report downloaded
    - classification.approved   — curator signed off
    - classification.rejected   — curator sent back for review
    - api_key.created           — new API key issued
    - api_key.revoked           — API key revoked
    - user.login                — successful API key authentication
    - org.member_invited        — new member invited
    - org.member_accepted       — invite accepted
    - network.share_contributed — variant shared to network
    - batch.job_submitted       — VCF batch job submitted
    - batch.job_completed       — VCF batch job finished
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    # Who did it
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    # What happened
    action = Column(String, nullable=False, index=True)
    # Resource type (variant, user, org, api_key, batch_job)
    resource_type = Column(String, nullable=True)
    # Resource identifier (HGVS, user email, job_id, etc.)
    resource_id = Column(String, nullable=True)
    # JSON blob with event-specific context (never PII)
    details_json = Column(Text, nullable=True)
    # Request metadata
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    # Timestamps are immutable — never updated
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", backref="audit_logs")


class ClassificationApproval(Base):
    """
    Classification approval workflow (CLIA-module feature).

    Supports the DRAFT → PENDING_REVIEW → APPROVED / REJECTED state machine
    for labs that need curator sign-off before reporting variants.

    This is a Phase 3C compliance add-on ($500/month as CLIA module).
    The model is available now so data can accumulate before billing is enabled.

    States:
    - draft          — auto-created on classification, not yet reviewed
    - pending_review — submitted for curator review
    - approved       — curator signed off, can be released to clinical report
    - rejected       — curator rejected, returned for re-analysis
    - superseded     — replaced by a newer classification
    """
    __tablename__ = "classification_approvals"

    id = Column(Integer, primary_key=True, index=True)
    usage_record_id = Column(Integer, ForeignKey("usage_records.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)
    # State machine
    state = Column(String, default="draft", index=True)
    # Who submitted for review (usually the analyst)
    submitted_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    # Who reviewed (the curator/approver)
    reviewed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    # Curator comments
    review_comment = Column(Text, nullable=True)
    # Internal reference number (e.g., "LAB-2024-0042")
    internal_ref = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", foreign_keys=[user_id], backref="approvals")
    submitter = relationship("User", foreign_keys=[submitted_by_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by_id])
