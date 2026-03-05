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
)

# ---------------------------------------------------------------------------
# Pathogenic criteria
# ---------------------------------------------------------------------------

def evaluate_pvs1(
    variant: NormalizedVariant,
    gene_info: GeneInfo | None,
    spliceai_max_delta: float = 0.0,
) -> ACMGCriterion:
    """PVS1 — Null variant (frameshift, nonsense, splice ±1/2, initiation codon, exon deletion)
    in a gene where LOF is a known disease mechanism.
    """
    triggered = False
    evidence_parts = []

    lof_types = {"frameshift", "nonsense", "stop_gained", "splice_donor", "splice_acceptor", "start_lost"}
    if variant.variant_type and any(t in variant.variant_type.lower() for t in lof_types):
        triggered = True
        evidence_parts.append(f"Variant type is {variant.variant_type!r} (predicted loss-of-function)")

    if spliceai_max_delta >= 0.5 and not triggered:
        triggered = True
        evidence_parts.append(f"SpliceAI max delta score {spliceai_max_delta:.3f} ≥ 0.5 (strong splice impact)")

    if triggered and gene_info and not gene_info.is_lof_intolerant:
        # Downgrade if gene is not LOF intolerant (pLI < 0.9)
        triggered = False
        evidence_parts.append(
            f"Note: Gene {gene_info.gene_symbol} has pLI={gene_info.pli_score or "unknown"} (<0.9), "
            "LOF tolerance reduces PVS1 applicability"
        )

    return ACMGCriterion(
        code="PVS1",
        direction=ACMGDirection.PATHOGENIC,
        default_strength=ACMGStrength.VERY_STRONG,
        applied_strength=ACMGStrength.VERY_STRONG,
        triggered=triggered,
        evidence_text=" | ".join(evidence_parts) if evidence_parts else "No null variant type detected.",
        citations=["PMID:25741868", "PMID:30192042"],
    )


def evaluate_pm2(pop_freq: PopulationFrequency | None) -> ACMGCriterion:
    """PM2 — Absent or extremely low frequency in population databases (gnomAD).
    Threshold: AF < 0.0001 (0.01%) in the general population.
    """
    if pop_freq is None or pop_freq.not_found:
        triggered = True
        evidence = "Variant absent from gnomAD v4.1 — consistent with PM2 (absent from controls)."
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
        default_strength=ACMGStrength.MODERATE,
        applied_strength=ACMGStrength.MODERATE,
        triggered=triggered,
        evidence_text=evidence,
        citations=["PMID:25741868"],
    )


def evaluate_pp3(scores: ComputationalScore | None) -> ACMGCriterion:
    """PP3 — Multiple lines of computational evidence support pathogenicity.
    Uses AlphaMissense (primary) and CADD (secondary).
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

    evidence_parts = []
    supporting_count = 0

    if scores.alphamissense_score is not None:
        if scores.alphamissense_score >= 0.564:
            supporting_count += 1
            evidence_parts.append(
                f"AlphaMissense = {scores.alphamissense_score:.3f} "
                f"(≥0.564 threshold → {scores.alphamissense_class})"
            )
        else:
            evidence_parts.append(
                f"AlphaMissense = {scores.alphamissense_score:.3f} "
                f"(below pathogenic threshold → {scores.alphamissense_class})"
            )

    if scores.cadd_phred is not None:
        if scores.cadd_phred >= 20:
            supporting_count += 1
            evidence_parts.append(f"CADD phred = {scores.cadd_phred:.1f} (≥20 = deleterious)")
        else:
            evidence_parts.append(f"CADD phred = {scores.cadd_phred:.1f} (below 20)")

    if scores.revel_score is not None:
        if scores.revel_score >= 0.75:
            supporting_count += 1
            evidence_parts.append(f"REVEL = {scores.revel_score:.3f} (≥0.75 = pathogenic)")

    triggered = supporting_count >= 1
    return ACMGCriterion(
        code="PP3",
        direction=ACMGDirection.PATHOGENIC,
        default_strength=ACMGStrength.SUPPORTING,
        applied_strength=ACMGStrength.SUPPORTING,
        triggered=triggered,
        evidence_text=" | ".join(evidence_parts) or "No supporting computational evidence.",
        citations=["PMID:25741868", "PMID:36413997"],  # AlphaMissense paper
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


def evaluate_bp4(scores: ComputationalScore | None) -> ACMGCriterion:
    """BP4 — Multiple lines of computational evidence suggest benign impact."""
    if scores is None:
        return ACMGCriterion(
            code="BP4",
            direction=ACMGDirection.BENIGN,
            default_strength=ACMGStrength.SUPPORTING,
            applied_strength=ACMGStrength.SUPPORTING,
            triggered=False,
            evidence_text="No computational scores available.",
        )

    evidence_parts = []
    benign_count = 0

    if scores.alphamissense_score is not None:
        if scores.alphamissense_score < 0.340:
            benign_count += 1
            evidence_parts.append(
                f"AlphaMissense = {scores.alphamissense_score:.3f} "
                f"(<0.340 → {scores.alphamissense_class})"
            )
        else:
            evidence_parts.append(f"AlphaMissense = {scores.alphamissense_score:.3f} (not benign)")

    if scores.cadd_phred is not None and scores.cadd_phred < 10:
        benign_count += 1
        evidence_parts.append(f"CADD phred = {scores.cadd_phred:.1f} (<10 = tolerated)")

    triggered = benign_count >= 1
    return ACMGCriterion(
        code="BP4",
        direction=ACMGDirection.BENIGN,
        default_strength=ACMGStrength.SUPPORTING,
        applied_strength=ACMGStrength.SUPPORTING,
        triggered=triggered,
        evidence_text=" | ".join(evidence_parts) or "No benign computational evidence.",
        citations=["PMID:25741868"],
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
