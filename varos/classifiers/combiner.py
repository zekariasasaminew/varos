"""ACMG classification combiner — Bayesian point-based framework.

Implements Tavtigian et al., Genetics in Medicine 2018 (PMID 29300386):
"Modeling the ACMG/AMP variant classification guidelines as a Bayesian
classification framework."

Each triggered criterion contributes points according to its *applied*
strength (which may already be upgraded/downgraded from the criterion's
default strength, e.g. by a VCEP override or a calibrated-threshold
evaluator such as PP3/BP4):

    Supporting = 1, Moderate = 2, Strong = 4, Very Strong = 8

Points are negated for benign-direction criteria. The point total is then
mapped to a classification using the ranges from Tavtigian 2018 Table 3,
and converted to a posterior probability of pathogenicity via the same
paper's OddsPath formulation (prior P(pathogenic) = 0.10, OddsPath at the
Very Strong level = 350, so one Supporting-equivalent point corresponds to
an odds multiplier of 350 ** (1/8)).

Note: translating the original 2015 Richards et al. combining rules
(Table 5) into this additive point system does not reproduce every 2015
rule exactly — this is a known, published property of the Bayesian
approximation (Tavtigian 2018, Table 4), not a bug. The most visible case
here is two Strong pathogenic criteria (PS+PS): 2015 Table 5 calls this
Pathogenic outright, but 4+4=8 points falls in the Likely Pathogenic
range (6-9) under the point framework.

BA1 (stand-alone benign, e.g. allele frequency > 5%) is not a Table-5
counting criterion — the ACMG/AMP guidelines treat it as dominant on its
own. It isn't naturally expressible in the four-level strength enum used
elsewhere, so it is weighted here at -8 points (the Very-Strong-equivalent
weight), which is enough to fully determine Benign by itself, and is only
overridden when other evidence's point total is large enough to indicate a
genuine annotation conflict worth flagging as a VUS on review.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from varos.models import ACMGClassification, ACMGCriterion, ACMGDirection, ACMGStrength

# Points per applied strength (Tavtigian 2018).
_STRENGTH_POINTS: dict[ACMGStrength, int] = {
    ACMGStrength.SUPPORTING: 1,
    ACMGStrength.MODERATE: 2,
    ACMGStrength.STRONG: 4,
    ACMGStrength.VERY_STRONG: 8,
}

# BA1 is stand-alone benign evidence, stronger than a Strong criterion but
# not represented by a dedicated enum value — weight it as Very Strong.
_BA1_POINTS = 8

# OddsPath at the Very Strong level, and the prior probability of
# pathogenicity for a variant under consideration (Tavtigian 2018).
_ODDS_PATH_VERY_STRONG = 350.0
_PRIOR_PATHOGENICITY = 0.10
_POINT_ODDS = _ODDS_PATH_VERY_STRONG ** (1.0 / 8.0)  # odds multiplier per point, ≈2.08


def _criterion_points(c: ACMGCriterion) -> int:
    if c.code == "BA1":
        return -_BA1_POINTS
    points = _STRENGTH_POINTS[c.applied_strength]
    return -points if c.direction == ACMGDirection.BENIGN else points


def _posterior_probability(points: int, prior: float = _PRIOR_PATHOGENICITY) -> float:
    """Posterior P(pathogenic) given total points, via the OddsPath formula."""
    odds_path = _POINT_ODDS ** points
    return (odds_path * prior) / ((odds_path - 1.0) * prior + 1.0)


def _classification_for_points(points: int) -> ACMGClassification:
    if points >= 10:
        return ACMGClassification.PATHOGENIC
    if points >= 6:
        return ACMGClassification.LIKELY_PATHOGENIC
    if points <= -7:
        return ACMGClassification.BENIGN
    if points <= -1:
        return ACMGClassification.LIKELY_BENIGN
    return ACMGClassification.VUS


@dataclass
class CombinerResult:
    classification: ACMGClassification
    confidence: int
    point_total: int
    posterior_probability: float


def classify_detailed(criteria: list[ACMGCriterion]) -> CombinerResult:
    """Apply the Bayesian point framework to a list of evaluated criteria."""
    triggered = [c for c in criteria if c.triggered]
    points = sum(_criterion_points(c) for c in triggered)

    classification = _classification_for_points(points)
    posterior = _posterior_probability(points)

    # Confidence reflects certainty in the *direction* implied by the point
    # total: P(pathogenic) when points are net-pathogenic (or zero/VUS),
    # P(benign) = 1 - P(pathogenic) when points are net-benign.
    confidence_probability = posterior if points >= 0 else (1.0 - posterior)
    confidence = max(0, min(100, round(confidence_probability * 100)))

    return CombinerResult(
        classification=classification,
        confidence=confidence,
        point_total=points,
        posterior_probability=round(posterior, 4) if not math.isnan(posterior) else 0.0,
    )


def classify(criteria: list[ACMGCriterion]) -> tuple[ACMGClassification, int]:
    """
    Apply ACMG combination rules to a list of evaluated criteria.
    Returns (classification, confidence_score 0-100).

    See ``classify_detailed`` for the point total and posterior probability.
    """
    result = classify_detailed(criteria)
    return result.classification, result.confidence
