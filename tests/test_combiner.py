"""Tests for ACMG criteria combiner (pure functions, no API calls)."""

from __future__ import annotations

from varos.classifiers.combiner import classify
from varos.models import (
    ACMGClassification,
    ACMGCriterion,
    ACMGDirection,
    ACMGStrength,
)


def make_criterion(
    code: str,
    direction: ACMGDirection,
    strength: ACMGStrength,
    triggered: bool = True,
) -> ACMGCriterion:
    return ACMGCriterion(
        code=code,
        triggered=triggered,
        direction=direction,
        default_strength=strength,
        applied_strength=strength,
        evidence_text=f"Test evidence for {code}",
    )


# --- Pathogenic rules ---

def test_pvs1_pm2_pp3_pp5_is_pathogenic():
    criteria = [
        make_criterion("PVS1", ACMGDirection.PATHOGENIC, ACMGStrength.VERY_STRONG),
        make_criterion("PM2", ACMGDirection.PATHOGENIC, ACMGStrength.MODERATE),
        make_criterion("PP3", ACMGDirection.PATHOGENIC, ACMGStrength.SUPPORTING),
        make_criterion("PP5", ACMGDirection.PATHOGENIC, ACMGStrength.SUPPORTING),
    ]
    classification, confidence = classify(criteria)
    assert classification == ACMGClassification.PATHOGENIC


def test_pvs1_alone_is_likely_pathogenic():
    """PVS1 alone → Likely Pathogenic or VUS (needs ≥1 additional criterion for P)."""
    criteria = [
        make_criterion("PVS1", ACMGDirection.PATHOGENIC, ACMGStrength.VERY_STRONG),
    ]
    classification, _ = classify(criteria)
    assert classification in (ACMGClassification.LIKELY_PATHOGENIC, ACMGClassification.VUS)


def test_two_strong_pathogenic_is_pathogenic():
    """PS1 + PS3 → Pathogenic."""
    criteria = [
        make_criterion("PS1", ACMGDirection.PATHOGENIC, ACMGStrength.STRONG),
        make_criterion("PS3", ACMGDirection.PATHOGENIC, ACMGStrength.STRONG),
    ]
    classification, _ = classify(criteria)
    assert classification == ACMGClassification.PATHOGENIC


# --- Benign rules ---

def test_ba1_alone_is_benign():
    """BA1 alone → Benign (standalone rule)."""
    criteria = [
        make_criterion("BA1", ACMGDirection.BENIGN, ACMGStrength.STRONG),
    ]
    classification, _ = classify(criteria)
    assert classification == ACMGClassification.BENIGN


def test_two_bs_is_benign():
    """BS1 + BS2 → Benign."""
    criteria = [
        make_criterion("BS1", ACMGDirection.BENIGN, ACMGStrength.STRONG),
        make_criterion("BS2", ACMGDirection.BENIGN, ACMGStrength.STRONG),
    ]
    classification, _ = classify(criteria)
    assert classification in (ACMGClassification.BENIGN, ACMGClassification.LIKELY_BENIGN)


def test_one_bs_is_likely_benign():
    """BS1 alone → Likely Benign."""
    criteria = [
        make_criterion("BS1", ACMGDirection.BENIGN, ACMGStrength.STRONG),
    ]
    classification, _ = classify(criteria)
    assert classification == ACMGClassification.LIKELY_BENIGN


# --- VUS (conflicting / insufficient) ---

def test_no_criteria_is_vus():
    """No triggered criteria → VUS."""
    classification, _ = classify([])
    assert classification == ACMGClassification.VUS


def test_conflicting_evidence_is_vus():
    """Pathogenic + Benign criteria → VUS (conflicting)."""
    criteria = [
        make_criterion("PVS1", ACMGDirection.PATHOGENIC, ACMGStrength.VERY_STRONG),
        make_criterion("BA1", ACMGDirection.BENIGN, ACMGStrength.STRONG),
    ]
    classification, _ = classify(criteria)
    assert classification == ACMGClassification.VUS


# --- Confidence scoring ---

def test_pathogenic_confidence_high():
    """Strong pathogenic evidence should give high confidence."""
    criteria = [
        make_criterion("PVS1", ACMGDirection.PATHOGENIC, ACMGStrength.VERY_STRONG),
        make_criterion("PS3", ACMGDirection.PATHOGENIC, ACMGStrength.STRONG),
        make_criterion("PM2", ACMGDirection.PATHOGENIC, ACMGStrength.MODERATE),
    ]
    classification, confidence = classify(criteria)
    assert confidence >= 70


def test_vus_confidence_low():
    """Single supporting criterion → low confidence."""
    criteria = [
        make_criterion("PP3", ACMGDirection.PATHOGENIC, ACMGStrength.SUPPORTING),
    ]
    _classification, confidence = classify(criteria)
    assert confidence < 60
