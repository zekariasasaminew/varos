"""Tests for ACMG criteria combiner (pure functions, no API calls)."""

from __future__ import annotations

from varos.classifiers.combiner import classify, classify_detailed
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


def test_two_strong_pathogenic_is_likely_pathogenic():
    """PS1 + PS3 → Likely Pathogenic under the Tavtigian 2018 point framework.

    Under the original 2015 Richards et al. Table 5 rules, two Strong
    criteria alone were categorized as Pathogenic. The Bayesian point
    system (4 + 4 = 8 points) places this combination in the Likely
    Pathogenic range (6-9) instead — a documented, published divergence
    between the two frameworks (Tavtigian 2018, Table 4), not a bug.
    """
    criteria = [
        make_criterion("PS1", ACMGDirection.PATHOGENIC, ACMGStrength.STRONG),
        make_criterion("PS3", ACMGDirection.PATHOGENIC, ACMGStrength.STRONG),
    ]
    classification, _ = classify(criteria)
    assert classification == ACMGClassification.LIKELY_PATHOGENIC


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


# --- Bayesian point framework (Tavtigian 2018) ---

def test_point_total_sums_applied_strength():
    criteria = [
        make_criterion("PVS1", ACMGDirection.PATHOGENIC, ACMGStrength.VERY_STRONG),  # +8
        make_criterion("PM2", ACMGDirection.PATHOGENIC, ACMGStrength.SUPPORTING),     # +1
        make_criterion("BS1", ACMGDirection.BENIGN, ACMGStrength.STRONG),             # -4
    ]
    result = classify_detailed(criteria)
    assert result.point_total == 5


def test_posterior_probability_increases_with_points():
    weak = classify_detailed([make_criterion("PP3", ACMGDirection.PATHOGENIC, ACMGStrength.SUPPORTING)])
    strong = classify_detailed([make_criterion("PVS1", ACMGDirection.PATHOGENIC, ACMGStrength.VERY_STRONG)])
    assert 0.0 <= weak.posterior_probability <= 1.0
    assert 0.0 <= strong.posterior_probability <= 1.0
    assert strong.posterior_probability > weak.posterior_probability


def test_ba1_weighted_as_very_strong_benign():
    """BA1 alone (-8 points) reaches the Benign point range on its own."""
    result = classify_detailed([make_criterion("BA1", ACMGDirection.BENIGN, ACMGStrength.STRONG)])
    assert result.point_total == -8
    assert result.classification == ACMGClassification.BENIGN


def test_pathogenic_requires_ten_points():
    nine_points = classify_detailed([
        make_criterion("PVS1", ACMGDirection.PATHOGENIC, ACMGStrength.VERY_STRONG),  # 8
        make_criterion("PP3", ACMGDirection.PATHOGENIC, ACMGStrength.SUPPORTING),     # 1
    ])
    assert nine_points.point_total == 9
    assert nine_points.classification == ACMGClassification.LIKELY_PATHOGENIC

    ten_points = classify_detailed([
        make_criterion("PVS1", ACMGDirection.PATHOGENIC, ACMGStrength.VERY_STRONG),  # 8
        make_criterion("PM2", ACMGDirection.PATHOGENIC, ACMGStrength.MODERATE),       # 2
    ])
    assert ten_points.point_total == 10
    assert ten_points.classification == ACMGClassification.PATHOGENIC
