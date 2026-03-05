"""ACMG classification combiner — applies combination rules from the 2015 guidelines.

Rules from Richards et al., Genetics in Medicine 2015, Table 5.
"""

from __future__ import annotations

from varos.models import ACMGClassification, ACMGCriterion, ACMGDirection, ACMGStrength


def _count(criteria: list[ACMGCriterion], direction: ACMGDirection, strength: ACMGStrength) -> int:
    return sum(
        1 for c in criteria
        if c.triggered and c.direction == direction and c.applied_strength == strength
    )


def classify(criteria: list[ACMGCriterion]) -> tuple[ACMGClassification, int]:
    """
    Apply ACMG combination rules to a list of evaluated criteria.
    Returns (classification, confidence_score 0-100).
    """
    triggered = [c for c in criteria if c.triggered]

    pvs = _count(triggered, ACMGDirection.PATHOGENIC, ACMGStrength.VERY_STRONG)
    ps = _count(triggered, ACMGDirection.PATHOGENIC, ACMGStrength.STRONG)
    pm = _count(triggered, ACMGDirection.PATHOGENIC, ACMGStrength.MODERATE)
    pp = _count(triggered, ACMGDirection.PATHOGENIC, ACMGStrength.SUPPORTING)

    has_ba1 = any(c.code == "BA1" for c in triggered)
    bs = _count(triggered, ACMGDirection.BENIGN, ACMGStrength.STRONG)
    bp = _count(triggered, ACMGDirection.BENIGN, ACMGStrength.SUPPORTING)

    has_path = pvs + ps + pm + pp > 0
    has_benign = has_ba1 or bs > 0 or bp > 0

    # Conflicting: pathogenic + benign evidence both present — always VUS
    if has_path and has_benign:
        return ACMGClassification.VUS, 30

    # --- Standalone Benign (only fires when no pathogenic conflict) ---
    if has_ba1:
        return ACMGClassification.BENIGN, 95

    # --- Pathogenic rules (ACMG 2015 Table 5) ---
    pathogenic = (
        (pvs >= 1 and (ps >= 1 or pm >= 2 or (pm >= 1 and pp >= 1) or pp >= 2))
        or ps >= 2
        or (ps >= 1 and (pm >= 3 or (pm >= 2 and pp >= 2) or (pm >= 1 and pp >= 4)))
    )

    # --- Likely Pathogenic rules ---
    likely_pathogenic = (
        (pvs >= 1 and pm >= 1)
        or (ps >= 1 and pm >= 1)
        or (ps >= 1 and pp >= 2)
        or pm >= 3
        or (pm >= 2 and pp >= 2)
        or (pm >= 1 and pp >= 4)
    )

    # --- Benign rules ---
    benign = bs >= 2 or (bs >= 1 and bp >= 1)

    # --- Likely Benign: 1 strong benign alone, or 2+ supporting benign ---
    likely_benign = bs >= 1 or bp >= 2

    if pathogenic:
        confidence = min(95, 70 + pvs * 10 + ps * 8 + pm * 5 + pp * 2)
        return ACMGClassification.PATHOGENIC, confidence

    if likely_pathogenic:
        confidence = min(85, 55 + pvs * 8 + ps * 6 + pm * 4 + pp * 2)
        return ACMGClassification.LIKELY_PATHOGENIC, confidence

    if benign:
        confidence = min(95, 70 + bs * 10 + bp * 3)
        return ACMGClassification.BENIGN, confidence

    if likely_benign:
        confidence = min(85, 55 + bs * 8 + bp * 4)
        return ACMGClassification.LIKELY_BENIGN, confidence

    # VUS — insufficient evidence
    total_evidence = pvs + ps + pm + pp + bs + bp
    confidence = max(10, 40 - total_evidence * 3)
    return ACMGClassification.VUS, confidence
