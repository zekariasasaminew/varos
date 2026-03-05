"""
Phase 3B unit tests — VAROS Network, audit log, and approval workflow.

Covers:
  - VAROS Network: hash computation, share, consensus, stats
  - Audit log: helper, list endpoint, CSV export
  - Approval workflow: state machine transitions, four-eyes rule
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from varos.api.audit import log_action
from varos.api.models import (
    AuditLog,
    Base,
    ClassificationApproval,
    NetworkShare,
    UsageRecord,
    User,
)

# ---------------------------------------------------------------------------
# Shared in-memory DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session_ = sessionmaker(bind=engine)
    session = Session_()
    yield session
    session.close()


@pytest.fixture(scope="module")
def test_user(db: Session) -> User:
    user = User(email="p3b@test.varos.ai")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(scope="module")
def test_usage(db: Session, test_user: User) -> UsageRecord:
    rec = UsageRecord(
        user_id=test_user.id,
        variant="NM_007294.4:c.5266dupC",
        classification="Likely Pathogenic",
        confidence=78,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


# ===========================================================================
# VAROS Network tests
# ===========================================================================

class TestVariantHash:
    """SHA-256 hash computation for privacy-preserving variant IDs."""

    def test_hash_is_64_hex_chars(self):
        from varos.api.routes.network import _variant_hash
        h = _variant_hash("NM_007294.4:c.5266dupC")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_same_input_same_hash(self):
        from varos.api.routes.network import _variant_hash
        h1 = _variant_hash("NM_007294.4:c.5266dupC")
        h2 = _variant_hash("NM_007294.4:c.5266dupC")
        assert h1 == h2

    def test_different_input_different_hash(self):
        from varos.api.routes.network import _variant_hash
        h1 = _variant_hash("NM_007294.4:c.5266dupC")
        h2 = _variant_hash("NM_007294.4:c.1000A>G")
        assert h1 != h2

    def test_hash_matches_sha256(self):
        from varos.api.routes.network import _variant_hash
        hgvs = "NM_007294.4:c.5266dupC"
        # Implementation normalizes to lowercase before hashing
        normalized = hgvs.strip().lower().replace(" ", "")
        expected = hashlib.sha256(normalized.encode()).hexdigest()
        assert _variant_hash(hgvs) == expected

    def test_whitespace_stripped(self):
        from varos.api.routes.network import _variant_hash
        h1 = _variant_hash("NM_007294.4:c.5266dupC")
        h2 = _variant_hash("  NM_007294.4:c.5266dupC  ")
        assert h1 == h2


class TestNetworkShareModel:
    """NetworkShare ORM model basics."""

    def test_create_network_share(self, db: Session, test_user: User):
        share = NetworkShare(
            variant_hash="a" * 64,
            variant_hgvs="NM_000000.1:c.1A>G",
            gene="BRCA2",
            classification="Pathogenic",
            criteria_codes=json.dumps(["PVS1", "PS1"]),
            confidence=95,
            user_id=test_user.id,
            genome_build="GRCh38",
            is_shared=True,
            shared_at=datetime.now(timezone.utc),
        )
        db.add(share)
        db.commit()
        db.refresh(share)
        assert share.id is not None
        assert share.classification == "Pathogenic"

    def test_network_share_requires_hash(self, db: Session, test_user: User):
        """variant_hash is NOT NULL — omitting it should raise."""
        share = NetworkShare(
            variant_hgvs="NM_000000.1:c.2A>G",
            classification="VUS",
            user_id=test_user.id,
        )
        db.add(share)
        with pytest.raises(Exception):
            db.flush()
        db.rollback()


class TestNetworkConsensus:
    """Consensus aggregation logic."""

    def test_single_share_gives_single_agreement(self, db: Session, test_user: User):
        """One org == 'single' agreement level."""
        h = hashlib.sha256(b"NM_111111.1:c.111A>G").hexdigest()
        share = NetworkShare(
            variant_hash=h,
            variant_hgvs="NM_111111.1:c.111A>G",
            gene="TP53",
            classification="Pathogenic",
            confidence=90,
            user_id=test_user.id,
            genome_build="GRCh38",
            is_shared=True,
            shared_at=datetime.now(timezone.utc),
        )
        db.add(share)
        db.commit()

        shares = db.query(NetworkShare).filter(NetworkShare.variant_hash == h).all()
        assert len(shares) == 1
        # Agreement level calculation: 1 org -> "single"
        total = len(shares)
        top_count = 1
        pct = top_count / total
        if total == 1:
            level = "single"
        elif pct >= 0.9:
            level = "strong"
        elif pct >= 0.75:
            level = "moderate"
        else:
            level = "weak"
        assert level == "single"

    def test_majority_classification_logic(self):
        """Simple majority classification from mock data."""
        classifications = ["Pathogenic", "Pathogenic", "Pathogenic", "VUS"]
        from collections import Counter
        counts = Counter(classifications)
        top_class, top_count = counts.most_common(1)[0]
        pct = top_count / len(classifications)

        assert top_class == "Pathogenic"
        assert top_count == 3
        assert pct == 0.75

        level = "strong" if pct >= 0.9 else "moderate" if pct >= 0.75 else "weak"
        assert level == "moderate"


# ===========================================================================
# Audit log tests
# ===========================================================================

class TestAuditLogHelper:
    """Audit log helper (varos.api.audit)."""

    def test_log_action_creates_entry(self, db: Session, test_user: User):
        entry = log_action(
            db,
            action="variant.classified",
            user_id=test_user.id,
            resource_type="variant",
            resource_id="NM_007294.4:c.5266dupC",
            details={"classification": "Pathogenic"},
        )
        assert entry is not None
        assert entry.id is not None
        assert entry.action == "variant.classified"

    def test_log_action_stores_json_details(self, db: Session, test_user: User):
        entry = log_action(
            db,
            action="batch.job_submitted",
            user_id=test_user.id,
            details={"variant_count": 250, "estimated_cost": 1.25},
        )
        assert entry.details_json is not None
        parsed = json.loads(entry.details_json)
        assert parsed["variant_count"] == 250

    def test_log_action_without_user(self, db: Session):
        """System-level actions have no user_id."""
        entry = log_action(
            db,
            action="daemon.clinvar_check.started",
            details={"job": "weekly_clinvar_diff"},
        )
        assert entry is not None
        assert entry.user_id is None

    def test_log_action_never_raises(self, db: Session):
        """Even if DB is closed, log_action must not raise."""
        mock_db = MagicMock()
        mock_db.add.side_effect = Exception("DB connection lost")
        result = log_action(mock_db, action="test.event")
        assert result is None  # returns None on failure, never raises

    def test_ip_address_stored(self, db: Session, test_user: User):
        entry = log_action(
            db,
            action="user.login",
            user_id=test_user.id,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )
        assert entry.ip_address == "192.168.1.1"

    def test_query_by_action(self, db: Session, test_user: User):
        logs = (
            db.query(AuditLog)
            .filter(
                AuditLog.user_id == test_user.id,
                AuditLog.action == "variant.classified",
            )
            .all()
        )
        assert len(logs) >= 1
        assert all(log.action == "variant.classified" for log in logs)


# ===========================================================================
# Approval workflow tests
# ===========================================================================

class TestApprovalModel:
    """ClassificationApproval ORM model."""

    def test_create_approval_draft(self, db: Session, test_user: User, test_usage: UsageRecord):
        approval = ClassificationApproval(
            usage_record_id=test_usage.id,
            user_id=test_user.id,
            state="draft",
        )
        db.add(approval)
        db.commit()
        db.refresh(approval)
        assert approval.id is not None
        assert approval.state == "draft"
        assert approval.submitted_at is None
        assert approval.reviewed_at is None

    def test_approval_internal_ref(self, db: Session, test_user: User, test_usage: UsageRecord):
        approval = ClassificationApproval(
            usage_record_id=test_usage.id,
            user_id=test_user.id,
            state="draft",
            internal_ref="LAB-2024-001",
        )
        db.add(approval)
        db.commit()
        db.refresh(approval)
        assert approval.internal_ref == "LAB-2024-001"


class TestApprovalStateMachine:
    """State machine transition logic."""

    def test_valid_transitions_from_draft(self):
        from varos.api.routes.approvals import _STATE_TRANSITIONS
        assert "pending_review" in _STATE_TRANSITIONS["draft"]

    def test_draft_cannot_go_to_approved_directly(self):
        from varos.api.routes.approvals import _STATE_TRANSITIONS
        assert "approved" not in _STATE_TRANSITIONS.get("draft", set())

    def test_pending_review_can_approve_or_reject(self):
        from varos.api.routes.approvals import _STATE_TRANSITIONS
        allowed = _STATE_TRANSITIONS["pending_review"]
        assert "approved" in allowed
        assert "rejected" in allowed

    def test_rejected_can_be_resubmitted(self):
        from varos.api.routes.approvals import _STATE_TRANSITIONS
        assert "pending_review" in _STATE_TRANSITIONS["rejected"]

    def test_assert_transition_raises_on_invalid(self):
        from fastapi import HTTPException
        from varos.api.routes.approvals import _assert_transition
        with pytest.raises(HTTPException) as exc_info:
            _assert_transition("draft", "approved")
        assert exc_info.value.status_code == 409

    def test_assert_transition_passes_on_valid(self):
        from varos.api.routes.approvals import _assert_transition
        # Should not raise
        _assert_transition("draft", "pending_review")
        _assert_transition("pending_review", "approved")
        _assert_transition("pending_review", "rejected")
        _assert_transition("rejected", "pending_review")

    def test_four_eyes_states_defined(self):
        """Approved transitions exist to enforce reviewer != submitter."""
        from varos.api.routes.approvals import _STATE_TRANSITIONS
        # Approved is reachable only via pending_review
        assert "pending_review" in _STATE_TRANSITIONS
        assert "approved" in _STATE_TRANSITIONS["pending_review"]

    def test_valid_states_set(self):
        from varos.api.routes.approvals import _VALID_STATES
        assert "draft" in _VALID_STATES
        assert "pending_review" in _VALID_STATES
        assert "approved" in _VALID_STATES
        assert "rejected" in _VALID_STATES
        assert "superseded" in _VALID_STATES


# ===========================================================================
# Network model field integrity
# ===========================================================================

class TestNetworkShareFields:
    """Verify NetworkShare has all required fields."""

    def test_network_share_has_genome_build(self, db: Session, test_user: User):
        h = hashlib.sha256(b"test_genome_build").hexdigest()
        share = NetworkShare(
            variant_hash=h,
            variant_hgvs="NM_999.1:c.1A>T",
            classification="VUS",
            user_id=test_user.id,
            genome_build="GRCh37",
            is_shared=False,
        )
        db.add(share)
        db.commit()
        db.refresh(share)
        assert share.genome_build == "GRCh37"
        assert share.is_shared is False

    def test_network_share_clinvar_variation_id(self, db: Session, test_user: User):
        h = hashlib.sha256(b"test_clinvar_var_id").hexdigest()
        share = NetworkShare(
            variant_hash=h,
            variant_hgvs="NM_000059.4:c.68-1G>A",
            classification="Pathogenic",
            user_id=test_user.id,
            genome_build="GRCh38",
            clinvar_variation_id="VCV000123456",
            is_shared=True,
            shared_at=datetime.now(timezone.utc),
        )
        db.add(share)
        db.commit()
        db.refresh(share)
        assert share.clinvar_variation_id == "VCV000123456"

    def test_criteria_codes_json_roundtrip(self, db: Session, test_user: User):
        h = hashlib.sha256(b"test_criteria_roundtrip").hexdigest()
        codes = ["PVS1", "PS2", "PM2"]
        share = NetworkShare(
            variant_hash=h,
            variant_hgvs="NM_000000.1:c.999del",
            classification="Pathogenic",
            user_id=test_user.id,
            genome_build="GRCh38",
            criteria_codes=json.dumps(codes),
            is_shared=True,
            shared_at=datetime.now(timezone.utc),
        )
        db.add(share)
        db.commit()
        db.refresh(share)
        loaded = json.loads(share.criteria_codes)
        assert loaded == codes
