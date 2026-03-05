"""
Somatic Variant Classifier — AMP/ASCO/CAP 2017 Tiered Classification System.

Reference: Li et al. (2017) Standards and Guidelines for the Interpretation and
Reporting of Sequence Variants in Cancer: A Joint Consensus Recommendation of
the AMP, ASCO, and CAP. Journal of Molecular Diagnostics, 19(1):4-23.

Tier System:
  - Tier I:   Strong Clinical Significance — FDA-approved therapy or professional guidelines
  - Tier II:  Potential Clinical Significance — investigational or off-label evidence
  - Tier III: Variant of Uncertain Clinical Significance — limited/conflicting evidence
  - Tier IV:  Benign or Likely Benign somatic variant — common germline / passenger mutation

Each tier has two levels:
  - Level A: FDA-approved therapy / standard of care (highest evidence)
  - Level B: Clinical trial / well-powered study (strong evidence)
  - Level C: FDA-approved in different tumor type or case reports (moderate evidence)
  - Level D: Pre-clinical, case reports, biological relevance only (limited evidence)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Evidence weights for tier determination
_TIER_I_MIN_EVIDENCE = {"fda_approved_same_tumor": True, "professional_guidelines": True}
_TIER_II_MIN_EVIDENCE = {"fda_approved_diff_tumor": True, "clinical_trial": True, "well_powered_study": True}


@dataclass
class SomaticEvidence:
    """Raw evidence gathered for somatic variant classification."""

    # OncoKB tier (1-4, or None if not in OncoKB)
    onckb_level: Optional[str] = None
    onckb_gene_role: Optional[str] = None  # "Oncogene" | "TSG" | "Oncogene/TSG"
    onckb_is_oncogenic: Optional[bool] = None

    # CIViC evidence items
    civic_evidence: List[Dict[str, Any]] = field(default_factory=list)
    civic_score: Optional[float] = None  # CIViC EAP score

    # COSMIC hotspot
    cosmic_count: Optional[int] = None  # occurrences in COSMIC
    is_cosmic_hotspot: bool = False

    # Population frequency (germline contamination check)
    gnomad_af: Optional[float] = None
    is_likely_germline: bool = False

    # Tumor type context
    tumor_type: Optional[str] = None  # e.g. "breast_cancer", "nsclc"

    # Approved therapies found
    fda_approved_therapies: List[Dict[str, Any]] = field(default_factory=list)
    investigational_therapies: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SomaticClassification:
    """Result of AMP/ASCO/CAP somatic variant classification."""

    variant: str
    tier: str                          # "I" | "II" | "III" | "IV"
    level: Optional[str] = None        # "A" | "B" | "C" | "D"
    oncogenicity: Optional[str] = None # "Oncogenic" | "Likely Oncogenic" | "VUS" | "Likely Neutral" | "Neutral"
    summary: str = ""
    evidence_used: List[str] = field(default_factory=list)
    approved_therapies: List[str] = field(default_factory=list)
    clinical_trials: List[str] = field(default_factory=list)
    confidence: int = 0               # 0-100


async def classify_somatic(
    variant_hgvs: str,
    gene: str,
    tumor_type: Optional[str] = None,
) -> SomaticClassification:
    """
    Classify a somatic variant using AMP/ASCO/CAP 2017 Tier I-IV guidelines.

    Args:
        variant_hgvs: HGVS notation of the somatic variant
        gene:         HGNC gene symbol
        tumor_type:   Optional tumor type for context-specific evidence (e.g. "breast_cancer")

    Returns:
        SomaticClassification with tier, level, oncogenicity, and evidence summary.
    """
    logger.info("Somatic classification: %s in %s (tumor: %s)", variant_hgvs, gene, tumor_type)

    evidence = SomaticEvidence(tumor_type=tumor_type)

    # Gather evidence in parallel
    import asyncio
    from varos.connectors.onckb import get_onckb_annotation
    from varos.connectors.civic import get_civic_evidence

    onckb_task = asyncio.create_task(get_onckb_annotation(gene, variant_hgvs, tumor_type))
    civic_task = asyncio.create_task(get_civic_evidence(gene, variant_hgvs))

    onckb_result, civic_result = await asyncio.gather(
        onckb_task, civic_task, return_exceptions=True
    )

    if isinstance(onckb_result, dict) and onckb_result:
        evidence.onckb_level = onckb_result.get("highestSensitiveLevel")
        evidence.onckb_gene_role = onckb_result.get("geneRole")
        evidence.onckb_is_oncogenic = onckb_result.get("oncogenic") in ("Oncogenic", "Likely Oncogenic")
        evidence.fda_approved_therapies = onckb_result.get("treatments", [])

    if isinstance(civic_result, dict) and civic_result:
        evidence.civic_evidence = civic_result.get("evidence_items", [])
        evidence.civic_score = civic_result.get("civic_actionability_score")

    return _apply_tier_rules(variant_hgvs, gene, evidence)


def _apply_tier_rules(variant: str, gene: str, ev: SomaticEvidence) -> SomaticClassification:
    """Apply AMP/ASCO/CAP 2017 tier rules based on gathered evidence."""
    evidence_used = []
    approved_therapies = []
    clinical_trials = []

    # --- Tier I: Strong Clinical Significance ---
    # Level A: FDA-approved therapy in same tumor type
    has_fda_same = bool(ev.fda_approved_therapies) and ev.onckb_level in ("LEVEL_1", "LEVEL_R1")
    if has_fda_same:
        evidence_used.append(f"OncoKB Level {ev.onckb_level}: FDA-approved therapy")
        approved_therapies = [t.get("drugs", [{}])[0].get("drugName", "") for t in ev.fda_approved_therapies if t.get("drugs")]
        return SomaticClassification(
            variant=variant,
            tier="I",
            level="A",
            oncogenicity="Oncogenic",
            summary=_tier_summary("I", "A", gene, evidence_used),
            evidence_used=evidence_used,
            approved_therapies=approved_therapies,
            confidence=95,
        )

    # Level B: FDA-approved in different tumor / clinical trial evidence
    has_fda_diff = ev.onckb_level in ("LEVEL_2", "LEVEL_R2")
    has_strong_civic = ev.civic_score is not None and ev.civic_score >= 10.0
    if has_fda_diff or has_strong_civic:
        if has_fda_diff:
            evidence_used.append(f"OncoKB Level {ev.onckb_level}: FDA-approved (different indication)")
        if has_strong_civic:
            evidence_used.append(f"CIViC actionability score {ev.civic_score:.1f}")
        return SomaticClassification(
            variant=variant,
            tier="I",
            level="B",
            oncogenicity="Oncogenic",
            summary=_tier_summary("I", "B", gene, evidence_used),
            evidence_used=evidence_used,
            confidence=85,
        )

    # --- Tier II: Potential Clinical Significance ---
    # Level C: FDA-approved in different tumor type (moderate evidence)
    has_investigational = ev.onckb_level in ("LEVEL_3A", "LEVEL_3B")
    has_civic_moderate = (
        ev.civic_score is not None and 3.0 <= ev.civic_score < 10.0
    ) or bool(ev.civic_evidence)
    has_oncogenic = ev.onckb_is_oncogenic is True

    if has_investigational or has_civic_moderate or has_oncogenic:
        if has_investigational:
            evidence_used.append(f"OncoKB Level {ev.onckb_level}: investigational therapy")
        if has_civic_moderate:
            evidence_used.append(f"CIViC evidence ({len(ev.civic_evidence)} items)")
        if has_oncogenic:
            evidence_used.append(f"OncoKB: oncogenic variant in {gene}")
        level = "C" if has_investigational else "D"
        return SomaticClassification(
            variant=variant,
            tier="II",
            level=level,
            oncogenicity="Likely Oncogenic" if has_oncogenic else "VUS",
            summary=_tier_summary("II", level, gene, evidence_used),
            evidence_used=evidence_used,
            confidence=65,
        )

    # --- Tier IV: Benign / Likely Benign ---
    # gnomAD AF >1% suggests common germline variant, not somatic driver
    if ev.gnomad_af is not None and ev.gnomad_af > 0.01:
        evidence_used.append(f"gnomAD AF {ev.gnomad_af:.4f} (>1% — likely germline polymorphism)")
        return SomaticClassification(
            variant=variant,
            tier="IV",
            level=None,
            oncogenicity="Neutral",
            summary=f"Tier IV: Likely benign somatic variant. {gene} variant has gnomAD AF >{ev.gnomad_af:.4f}.",
            evidence_used=evidence_used,
            confidence=80,
        )

    # --- Tier III: VUS (default) ---
    evidence_used.append("Insufficient evidence for clinical actionability (Tier III)")
    return SomaticClassification(
        variant=variant,
        tier="III",
        level=None,
        oncogenicity="VUS",
        summary=_tier_summary("III", None, gene, evidence_used),
        evidence_used=evidence_used,
        confidence=40,
    )


def _tier_summary(tier: str, level: Optional[str], gene: str, evidence: List[str]) -> str:
    tier_labels = {
        "I":   "Tier I — Strong Clinical Significance",
        "II":  "Tier II — Potential Clinical Significance",
        "III": "Tier III — Variant of Uncertain Clinical Significance",
        "IV":  "Tier IV — Benign/Likely Benign",
    }
    level_str = f" Level {level}" if level else ""
    label = tier_labels.get(tier, f"Tier {tier}")
    evidence_str = "; ".join(evidence[:3]) if evidence else "No actionable evidence found"
    return f"{label}{level_str} — {gene}. Evidence: {evidence_str}."
