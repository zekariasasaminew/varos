"""ACMG/AMP 2015 variant classification criteria engine.

Reference: Richards et al., Genetics in Medicine 2015 (PMID 25741868)
ClinGen refinements: https://clinicalgenome.org/site/assets/files/3459/svi_criteria_specifications_v1.pdf

Each criterion function takes the collected evidence and returns an ACMGCriterion.
The combiner then applies the classification rules to triggered criteria.
"""

from __future__ import annotations

from varos.models import (
    ACMGCriterion,
    ACMGDirection,
    ACMGStrength,
    ClassificationResult,
    ComputationalScore,
    GeneInfo,
    NormalizedVariant,
    PopulationFrequency,
    ClinVarEvidence,
    LiteratureEvidence,
    TranscriptAnnotation,
)

# ---------------------------------------------------------------------------
# Pathogenic criteria
# ---------------------------------------------------------------------------

_NMD_LAST_EXON_WINDOW_NT = 50  # SVI PVS1: PTC in last 50nt of penultimate exon escapes NMD
_SMALL_TRUNCATION_FRACTION = 0.10  # SVI PVS1: removing <10% of the protein is a downgrade signal


def _nmd_escape_reason(annotation: TranscriptAnnotation) -> str | None:
    """Return a reason string if the PTC is predicted to escape NMD, else None.

    Per Abou Tayoun et al. 2018 (PMID 30192042): a premature termination
    codon (PTC) escapes nonsense-mediated decay, and so produces a stable
    truncated protein rather than triggering transcript degradation, when
    it falls in the last exon, or within the last 50 nt of the penultimate
    exon.
    """
    if annotation.exon_number is None or annotation.total_exons is None:
        return None
    if annotation.exon_number == annotation.total_exons:
        return "PTC in the last exon"
    is_penultimate = annotation.exon_number == annotation.total_exons - 1
    if (
        is_penultimate
        and annotation.cds_length
        and annotation.cds_position
        and (annotation.cds_length - annotation.cds_position) <= _NMD_LAST_EXON_WINDOW_NT
    ):
        return f"PTC within the last {_NMD_LAST_EXON_WINDOW_NT} nt of the penultimate exon"
    return None


def _truncation_fraction(annotation: TranscriptAnnotation) -> float | None:
    if not annotation.cds_length or not annotation.cds_position:
        return None
    return 1.0 - (annotation.cds_position / annotation.cds_length)


def _pvs1_for_truncating_variant(annotation: TranscriptAnnotation) -> tuple[ACMGStrength, str]:
    """PVS1 strength for a variant that produces a premature termination codon
    (nonsense, frameshift, or an out-of-frame exon skip)."""
    escape_reason = _nmd_escape_reason(annotation)
    if escape_reason is None:
        return ACMGStrength.VERY_STRONG, (
            f"PTC in exon {annotation.exon_number}/{annotation.total_exons} — NMD predicted "
            "(not in the last exon or the last 50nt of the penultimate exon)."
        )

    frac = _truncation_fraction(annotation)
    if frac is not None and frac < _SMALL_TRUNCATION_FRACTION:
        strength = ACMGStrength.MODERATE
        frac_text = f"; truncates only ~{frac:.0%} of the protein"
    else:
        strength = ACMGStrength.STRONG
        frac_text = f"; truncates ~{frac:.0%} of the protein" if frac is not None else ""
    return strength, (
        f"{escape_reason} — NMD escape predicted, stable truncated protein likely{frac_text}."
    )


def _pvs1_for_splice_variant(
    annotation: TranscriptAnnotation, spliceai_max_delta: float
) -> tuple[ACMGStrength, str] | None:
    """PVS1 strength for a canonical splice-site variant, via predicted exon
    skipping. Returns None if we can't determine in-frame vs. frameshift.
    """
    if annotation.skipped_exon_length_nt is None:
        return None
    in_frame = annotation.skipped_exon_length_nt % 3 == 0
    if in_frame:
        # In-frame exon skipping does not, on its own, meet PVS1_VeryStrong —
        # the SVI spec requires checking whether the skipped exon overlaps a
        # functionally critical domain, which we don't have data for here.
        # Cap at Strong rather than claim a precision we don't have.
        return ACMGStrength.STRONG, (
            f"Canonical splice variant predicts in-frame skipping of a "
            f"{annotation.skipped_exon_length_nt}nt exon (SpliceAI Δ={spliceai_max_delta:.2f}). "
            "Critical-domain-overlap analysis is not implemented, so this is capped at "
            "Strong rather than Very Strong — see docs for this known limitation."
        )
    # Out-of-frame skip — treat like any other frameshift/PTC-producing event.
    strength, reason = _pvs1_for_truncating_variant(annotation)
    return strength, (
        f"Canonical splice variant predicts out-of-frame skipping of a "
        f"{annotation.skipped_exon_length_nt}nt exon (frameshift). {reason}"
    )


def evaluate_pvs1(
    variant: NormalizedVariant,
    gene_info: GeneInfo | None,
    spliceai_max_delta: float = 0.0,
    annotation: TranscriptAnnotation | None = None,
) -> ACMGCriterion:
    """PVS1 — Null variant (frameshift, nonsense, splice ±1/2, initiation codon, exon deletion)
    in a gene where LOF is a known disease mechanism.

    Strength follows the ClinGen SVI PVS1 decision tree (Abou Tayoun et al.
    2018, PMID 30192042) when transcript/exon annotation is available:
    nonsense-mediated decay (NMD) escape (last exon, or last 50nt of the
    penultimate exon) and small (<10%) truncations downgrade from Very
    Strong to Strong or Moderate; in-frame exon skipping is capped at
    Strong pending a critical-domain-overlap check we don't implement.
    Start-loss is applied at Moderate — alternative in-frame start codon
    analysis (within 25 codons downstream, per the spec) is not
    implemented, so this is a conservative default rather than a full
    flowchart evaluation.

    Without annotation (Ensembl lookup failed or wasn't attempted), this
    falls back to the coarser variant-type/SpliceAI heuristic at full
    Very Strong strength, same as before — an honest "unknown" rather
    than a guessed downgrade.
    """
    consequence_terms = set(annotation.consequence_terms) if annotation else set()
    lof_terms = {
        "frameshift_variant", "stop_gained", "splice_donor_variant",
        "splice_acceptor_variant", "start_lost", "transcript_ablation",
    }
    lof_types = {"frameshift", "nonsense", "stop_gained", "splice_donor", "splice_acceptor", "start_lost"}

    is_lof_by_annotation = bool(consequence_terms & lof_terms)
    is_lof_by_heuristic = bool(
        variant.variant_type and any(t in variant.variant_type.lower() for t in lof_types)
    )
    is_splice_signal = spliceai_max_delta >= 0.5

    triggered = is_lof_by_annotation or is_lof_by_heuristic or is_splice_signal
    if not triggered:
        return ACMGCriterion(
            code="PVS1",
            direction=ACMGDirection.PATHOGENIC,
            default_strength=ACMGStrength.VERY_STRONG,
            applied_strength=ACMGStrength.VERY_STRONG,
            triggered=False,
            evidence_text="No null variant type detected.",
            citations=["PMID:25741868", "PMID:30192042"],
        )

    if gene_info and not gene_info.is_lof_intolerant:
        return ACMGCriterion(
            code="PVS1",
            direction=ACMGDirection.PATHOGENIC,
            default_strength=ACMGStrength.VERY_STRONG,
            applied_strength=ACMGStrength.VERY_STRONG,
            triggered=False,
            evidence_text=(
                f"Note: Gene {gene_info.gene_symbol} has pLI={gene_info.pli_score or 'unknown'} "
                "(<0.9); LOF tolerance reduces PVS1 applicability."
            ),
            citations=["PMID:25741868", "PMID:30192042"],
        )

    strength = ACMGStrength.VERY_STRONG
    evidence: str

    is_start_loss = "start_lost" in consequence_terms or (
        variant.variant_type and "start_lost" in variant.variant_type.lower()
    )
    is_splice_consequence = bool(
        consequence_terms & {"splice_donor_variant", "splice_acceptor_variant"}
    ) or (variant.variant_type and any(
        t in variant.variant_type.lower() for t in ("splice_donor", "splice_acceptor")
    ))

    if annotation is None or annotation.not_found:
        evidence = (
            f"Variant type is {variant.variant_type!r} (predicted loss-of-function). "
            "No transcript/exon annotation available — NMD and exon-skipping analysis "
            "could not be performed; defaulting to full PVS1_VeryStrong."
        )
    elif is_start_loss:
        strength = ACMGStrength.MODERATE
        evidence = (
            "Start-loss variant. Alternative in-frame start codon analysis is not "
            "implemented — defaulting to PVS1_Moderate rather than assuming full strength."
        )
    elif is_splice_consequence:
        splice_result = _pvs1_for_splice_variant(annotation, spliceai_max_delta)
        if splice_result is None:
            evidence = (
                f"Canonical splice variant (SpliceAI Δ={spliceai_max_delta:.2f}). "
                "Skipped-exon length unavailable — could not determine in-frame vs. "
                "frameshift outcome; defaulting to full PVS1_VeryStrong."
            )
        else:
            strength, evidence = splice_result
    else:
        strength, evidence = _pvs1_for_truncating_variant(annotation)

    return ACMGCriterion(
        code="PVS1",
        direction=ACMGDirection.PATHOGENIC,
        default_strength=ACMGStrength.VERY_STRONG,
        applied_strength=strength,
        triggered=True,
        evidence_text=evidence,
        citations=["PMID:25741868", "PMID:30192042"],
    )


def evaluate_pm2(pop_freq: PopulationFrequency | None) -> ACMGCriterion:
    """PM2 — Absent or extremely low frequency in population databases (gnomAD).
    Threshold: AF < 0.0001 (0.01%) in the general population.

    Applied at Supporting strength (not Moderate) per the 2020 ClinGen SVI
    recommendation: absence from gnomAD is a weaker signal now than when the
    2015 guidelines were written, given much larger reference population
    sizes. See SVI PM2 recommendation, ClinGen SVI Criteria Specification.
    """
    if pop_freq is None or pop_freq.not_found:
        triggered = True
        evidence = (
            "Variant absent from gnomAD v4.1 — consistent with PM2_Supporting "
            "(absent from controls)."
        )
    elif pop_freq.allele_frequency < 0.0001:
        triggered = True
        evidence = (
            f"gnomAD v4.1 AF = {pop_freq.allele_frequency:.2e} "
            f"(below 0.01% PM2 threshold). "
            f"AC={pop_freq.allele_count}, AN={pop_freq.allele_number}."
        )
    else:
        triggered = False
        evidence = (
            f"gnomAD v4.1 AF = {pop_freq.allele_frequency:.4f} "
            f"(exceeds PM2 threshold of 0.0001). PM2 not triggered."
        )

    return ACMGCriterion(
        code="PM2",
        direction=ACMGDirection.PATHOGENIC,
        default_strength=ACMGStrength.SUPPORTING,
        applied_strength=ACMGStrength.SUPPORTING,
        triggered=triggered,
        evidence_text=evidence,
        citations=["PMID:25741868", "ClinGen SVI PM2 recommendation (2020)"],
    )


# Pejaver et al. 2022 (PMID 36413997) calibrated REVEL thresholds — the
# best-calibrated single predictor in that study, so it takes priority when
# available. Pejaver's benign-side calibration for REVEL was weaker than its
# pathogenic-side calibration (no Strong-benign tier reported), which is
# reflected below. These figures should be re-checked against the paper's
# Table 2 before being relied on for a real classification; treat them as a
# best-effort transcription, not a verified primary-source copy.
_REVEL_PATHOGENIC_TIERS = (
    (0.932, ACMGStrength.STRONG),
    (0.773, ACMGStrength.MODERATE),
    (0.644, ACMGStrength.SUPPORTING),
)
_REVEL_BENIGN_TIERS = (
    (0.183, ACMGStrength.MODERATE),
    (0.290, ACMGStrength.SUPPORTING),
)

# AlphaMissense (Cheng et al. 2023, PMID 37733863) publishes only a single
# likely-pathogenic / likely-benign cutoff, not graduated ACMG strengths —
# used here at Supporting only, and only when REVEL is unavailable.
_ALPHAMISSENSE_PATHOGENIC = 0.564
_ALPHAMISSENSE_BENIGN = 0.340


def _pick_pp3_strength(scores: ComputationalScore) -> tuple[ACMGStrength | None, str]:
    """Pick the strongest applicable pathogenic-side computational strength.

    Follows SVI guidance to use one well-calibrated predictor rather than
    stacking multiple correlated in-silico tools: REVEL (best calibrated,
    Pejaver 2022) takes priority, falling back to AlphaMissense, then CADD
    as a coarse last resort.
    """
    if scores.revel_score is not None:
        for threshold, strength in _REVEL_PATHOGENIC_TIERS:
            if scores.revel_score >= threshold:
                return strength, (
                    f"REVEL = {scores.revel_score:.3f} (≥{threshold} → "
                    f"PP3 at {strength.value} strength, Pejaver 2022 calibration)"
                )
        return None, f"REVEL = {scores.revel_score:.3f} (below PP3 thresholds)"

    if scores.alphamissense_score is not None:
        if scores.alphamissense_score >= _ALPHAMISSENSE_PATHOGENIC:
            return ACMGStrength.SUPPORTING, (
                f"AlphaMissense = {scores.alphamissense_score:.3f} "
                f"(≥{_ALPHAMISSENSE_PATHOGENIC} → {scores.alphamissense_class})"
            )
        return None, f"AlphaMissense = {scores.alphamissense_score:.3f} (below pathogenic threshold)"

    if scores.cadd_phred is not None and scores.cadd_phred >= 20:
        return ACMGStrength.SUPPORTING, (
            f"CADD phred = {scores.cadd_phred:.1f} (≥20 = deleterious; general heuristic, "
            "not a Pejaver-calibrated PP3 threshold — used only as a last resort)"
        )

    return None, "No supporting computational evidence."


def evaluate_pp3(scores: ComputationalScore | None) -> ACMGCriterion:
    """PP3 — Computational evidence supports a deleterious effect.

    Strength is calibrated per-predictor per Pejaver et al. 2022 (PMID
    36413997), preferring REVEL when available. See ``_pick_pp3_strength``.
    """
    if scores is None:
        return ACMGCriterion(
            code="PP3",
            direction=ACMGDirection.PATHOGENIC,
            default_strength=ACMGStrength.SUPPORTING,
            applied_strength=ACMGStrength.SUPPORTING,
            triggered=False,
            evidence_text="No computational scores available.",
        )

    strength, evidence = _pick_pp3_strength(scores)
    triggered = strength is not None
    return ACMGCriterion(
        code="PP3",
        direction=ACMGDirection.PATHOGENIC,
        default_strength=ACMGStrength.SUPPORTING,
        applied_strength=strength or ACMGStrength.SUPPORTING,
        triggered=triggered,
        evidence_text=evidence,
        citations=["PMID:25741868", "PMID:36413997"],  # ACMG 2015, Pejaver 2022
    )


def evaluate_pp5(clinvar: ClinVarEvidence | None) -> ACMGCriterion:
    """PP5 — Reputable source recently classified as pathogenic (ClinVar 2+ stars)."""
    if clinvar is None or clinvar.not_found:
        return ACMGCriterion(
            code="PP5",
            direction=ACMGDirection.PATHOGENIC,
            default_strength=ACMGStrength.SUPPORTING,
            applied_strength=ACMGStrength.SUPPORTING,
            triggered=False,
            evidence_text="Variant not found in ClinVar.",
        )

    path_classes = {"pathogenic", "likely pathogenic"}
    agg = (clinvar.aggregate_classification or "").lower()
    triggered = any(p in agg for p in path_classes) and clinvar.gold_stars >= 2

    evidence = (
        f"ClinVar aggregate: '{clinvar.aggregate_classification}' "
        f"({clinvar.gold_stars}★ review status: {clinvar.review_status}). "
        f"{len(clinvar.submissions)} total submissions."
    )
    return ACMGCriterion(
        code="PP5",
        direction=ACMGDirection.PATHOGENIC,
        default_strength=ACMGStrength.SUPPORTING,
        applied_strength=ACMGStrength.SUPPORTING,
        triggered=triggered,
        evidence_text=evidence,
        citations=["PMID:25741868"],
    )


# ---------------------------------------------------------------------------
# Benign criteria
# ---------------------------------------------------------------------------

def evaluate_ba1(pop_freq: PopulationFrequency | None) -> ACMGCriterion:
    """BA1 — Allele frequency > 5% in general population (standalone benign)."""
    if pop_freq is None or pop_freq.not_found:
        triggered = False
        evidence = "Variant absent from gnomAD — BA1 not applicable."
    elif pop_freq.allele_frequency > 0.05:
        triggered = True
        evidence = (
            f"gnomAD v4.1 AF = {pop_freq.allele_frequency:.4f} > 5% threshold. "
            "Classified as Benign as standalone criterion (BA1)."
        )
    else:
        triggered = False
        evidence = f"gnomAD v4.1 AF = {pop_freq.allele_frequency:.4f} — below 5% BA1 threshold."

    return ACMGCriterion(
        code="BA1",
        direction=ACMGDirection.BENIGN,
        default_strength=ACMGStrength.STRONG,
        applied_strength=ACMGStrength.STRONG,
        triggered=triggered,
        evidence_text=evidence,
        citations=["PMID:25741868"],
    )


def evaluate_bs1(pop_freq: PopulationFrequency | None, gene_info: GeneInfo | None) -> ACMGCriterion:
    """BS1 — Allele frequency is greater than expected for disorder (1% threshold)."""
    if pop_freq is None or pop_freq.not_found:
        return ACMGCriterion(
            code="BS1",
            direction=ACMGDirection.BENIGN,
            default_strength=ACMGStrength.STRONG,
            applied_strength=ACMGStrength.STRONG,
            triggered=False,
            evidence_text="Variant absent from gnomAD — BS1 not applicable.",
        )

    threshold = 0.01  # 1% general threshold; gene-specific thresholds in VCEP rules
    triggered = pop_freq.allele_frequency > threshold
    evidence = (
        f"gnomAD AF = {pop_freq.allele_frequency:.4f} "
        + ("exceeds" if triggered else "does not exceed")
        + f" BS1 threshold of {threshold*100:.1f}%."
    )
    return ACMGCriterion(
        code="BS1",
        direction=ACMGDirection.BENIGN,
        default_strength=ACMGStrength.STRONG,
        applied_strength=ACMGStrength.STRONG,
        triggered=triggered,
        evidence_text=evidence,
        citations=["PMID:25741868"],
    )


def _pick_bp4_strength(scores: ComputationalScore) -> tuple[ACMGStrength | None, str]:
    """Mirror of ``_pick_pp3_strength`` for the benign direction.

    Pejaver 2022's benign-side calibration for REVEL only reaches Moderate
    (no Strong tier reported); AlphaMissense/CADD are Supporting-only
    fallbacks, same rationale as the pathogenic side.
    """
    if scores.revel_score is not None:
        for threshold, strength in _REVEL_BENIGN_TIERS:
            if scores.revel_score <= threshold:
                return strength, (
                    f"REVEL = {scores.revel_score:.3f} (≤{threshold} → "
                    f"BP4 at {strength.value} strength, Pejaver 2022 calibration)"
                )
        return None, f"REVEL = {scores.revel_score:.3f} (above BP4 thresholds)"

    if scores.alphamissense_score is not None:
        if scores.alphamissense_score < _ALPHAMISSENSE_BENIGN:
            return ACMGStrength.SUPPORTING, (
                f"AlphaMissense = {scores.alphamissense_score:.3f} "
                f"(<{_ALPHAMISSENSE_BENIGN} → {scores.alphamissense_class})"
            )
        return None, f"AlphaMissense = {scores.alphamissense_score:.3f} (not benign)"

    if scores.cadd_phred is not None and scores.cadd_phred < 10:
        return ACMGStrength.SUPPORTING, (
            f"CADD phred = {scores.cadd_phred:.1f} (<10 = tolerated; general heuristic, "
            "not a Pejaver-calibrated BP4 threshold — used only as a last resort)"
        )

    return None, "No benign computational evidence."


def evaluate_bp4(scores: ComputationalScore | None) -> ACMGCriterion:
    """BP4 — Computational evidence suggests benign impact.

    Strength is calibrated per-predictor per Pejaver et al. 2022 (PMID
    36413997), preferring REVEL when available. See ``_pick_bp4_strength``.
    """
    if scores is None:
        return ACMGCriterion(
            code="BP4",
            direction=ACMGDirection.BENIGN,
            default_strength=ACMGStrength.SUPPORTING,
            applied_strength=ACMGStrength.SUPPORTING,
            triggered=False,
            evidence_text="No computational scores available.",
        )

    strength, evidence = _pick_bp4_strength(scores)
    triggered = strength is not None
    return ACMGCriterion(
        code="BP4",
        direction=ACMGDirection.BENIGN,
        default_strength=ACMGStrength.SUPPORTING,
        applied_strength=strength or ACMGStrength.SUPPORTING,
        triggered=triggered,
        evidence_text=evidence,
        citations=["PMID:25741868", "PMID:36413997"],
    )


def evaluate_bs2(pop_freq: PopulationFrequency | None, gene_info: GeneInfo | None) -> ACMGCriterion:
    """BS2 — Observed in a healthy adult individual with recessive or dominant disease
    (healthy homozygotes for recessive, or healthy het for fully penetrant dominant).
    """
    if pop_freq is None or pop_freq.not_found:
        return ACMGCriterion(
            code="BS2",
            direction=ACMGDirection.BENIGN,
            default_strength=ACMGStrength.STRONG,
            applied_strength=ACMGStrength.STRONG,
            triggered=False,
            evidence_text="Insufficient population data for BS2.",
        )

    triggered = False
    evidence = ""
    if pop_freq.homozygote_count > 5 and gene_info and "AR" in (gene_info.inheritance_patterns or []):
        triggered = True
        evidence = (
            f"{pop_freq.homozygote_count} healthy homozygotes in gnomAD "
            f"for this AR gene — strong evidence of benign impact."
        )
    else:
        evidence = (
            f"Homozygote count = {pop_freq.homozygote_count}. "
            "Insufficient for BS2 without inheritance pattern context."
        )

    return ACMGCriterion(
        code="BS2",
        direction=ACMGDirection.BENIGN,
        default_strength=ACMGStrength.STRONG,
        applied_strength=ACMGStrength.STRONG,
        triggered=triggered,
        evidence_text=evidence,
        citations=["PMID:25741868"],
    )
