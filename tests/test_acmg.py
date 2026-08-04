"""Tests for ACMG criteria evaluators (with mocked evidence)."""

from __future__ import annotations

from varos.classifiers.acmg import (
    evaluate_ba1,
    evaluate_bs1,
    evaluate_bs2,
    evaluate_pm2,
    evaluate_pp3,
    evaluate_bp4,
    evaluate_pvs1,
    evaluate_pp5,
)
from varos.models import (
    ACMGStrength,
    ClinVarEvidence,
    ComputationalScore,
    GeneInfo,
    NormalizedVariant,
    PopulationFrequency,
    TranscriptAnnotation,
)


def _gene(lof_intolerant: bool = True) -> GeneInfo:
    return GeneInfo(
        gene_symbol="BRCA1",
        is_lof_intolerant=lof_intolerant,
        inheritance_patterns=["AD"],
    )


def _pop(af_global: float = 0.0, homozygote_count: int = 0) -> PopulationFrequency:
    return PopulationFrequency(
        allele_frequency=af_global,
        allele_count=int(af_global * 251496),
        allele_number=251496,
        homozygote_count=homozygote_count,
        not_found=False,
    )


def _comp(pathogenicity: float = 0.5) -> ComputationalScore:
    return ComputationalScore(
        alphamissense_score=pathogenicity,
        alphamissense_class="likely_pathogenic" if pathogenicity > 0.564 else "ambiguous",
    )


# --- BA1 ---

def test_ba1_triggers_above_5pct():
    crit = evaluate_ba1(_pop(af_global=0.06))
    assert crit.triggered is True


def test_ba1_not_triggered_below_5pct():
    crit = evaluate_ba1(_pop(af_global=0.01))
    assert crit.triggered is False


def test_ba1_not_triggered_no_frequency():
    crit = evaluate_ba1(None)
    assert crit.triggered is False


# --- PM2 ---

def test_pm2_triggers_absent_from_controls():
    crit = evaluate_pm2(None)  # absent from gnomAD
    assert crit.triggered is True


def test_pm2_triggers_very_low_frequency():
    crit = evaluate_pm2(_pop(af_global=0.000005))
    assert crit.triggered is True


def test_pm2_not_triggered_moderate_frequency():
    crit = evaluate_pm2(_pop(af_global=0.001))
    assert crit.triggered is False


def test_pm2_applied_at_supporting_strength():
    """SVI 2020: PM2 is applied at Supporting, not Moderate, by default."""
    crit = evaluate_pm2(None)
    assert crit.applied_strength == ACMGStrength.SUPPORTING
    assert crit.default_strength == ACMGStrength.SUPPORTING


# --- BS1 ---

def test_bs1_triggers_above_expected():
    """AF 1% for a rare disease gene triggers BS1."""
    crit = evaluate_bs1(_pop(af_global=0.02), _gene())
    assert crit.triggered is True


def test_bs1_not_triggered_very_low_af():
    crit = evaluate_bs1(_pop(af_global=0.0001), _gene())
    assert crit.triggered is False


# --- PP3 (AlphaMissense pathogenic) ---

def test_pp3_triggers_high_alphamissense():
    comp = _comp(pathogenicity=0.9)
    crit = evaluate_pp3(comp)
    assert crit.triggered is True


def test_pp3_not_triggered_low_alphamissense():
    comp = _comp(pathogenicity=0.2)
    crit = evaluate_pp3(comp)
    assert crit.triggered is False


def test_pp3_not_triggered_no_scores():
    crit = evaluate_pp3(None)
    assert crit.triggered is False


# --- PP3 (REVEL, Pejaver 2022 calibrated tiers) ---

def test_pp3_revel_strong_tier():
    comp = ComputationalScore(revel_score=0.95)
    crit = evaluate_pp3(comp)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.STRONG


def test_pp3_revel_moderate_tier():
    comp = ComputationalScore(revel_score=0.8)
    crit = evaluate_pp3(comp)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.MODERATE


def test_pp3_revel_supporting_tier():
    comp = ComputationalScore(revel_score=0.65)
    crit = evaluate_pp3(comp)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.SUPPORTING


def test_pp3_revel_below_threshold_not_triggered():
    comp = ComputationalScore(revel_score=0.5)
    crit = evaluate_pp3(comp)
    assert crit.triggered is False


def test_pp3_prefers_revel_over_alphamissense():
    """REVEL is the better-calibrated predictor and takes priority."""
    comp = ComputationalScore(revel_score=0.95, alphamissense_score=0.1, alphamissense_class="ambiguous")
    crit = evaluate_pp3(comp)
    assert crit.applied_strength == ACMGStrength.STRONG


# --- BP4 (computational benign) ---

def test_bp4_triggers_low_alphamissense():
    comp = _comp(pathogenicity=0.1)
    crit = evaluate_bp4(comp)
    assert crit.triggered is True


def test_bp4_not_triggered_high_alphamissense():
    comp = _comp(pathogenicity=0.8)
    crit = evaluate_bp4(comp)
    assert crit.triggered is False


def test_bp4_revel_moderate_tier():
    comp = ComputationalScore(revel_score=0.1)
    crit = evaluate_bp4(comp)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.MODERATE


def test_bp4_revel_supporting_tier():
    comp = ComputationalScore(revel_score=0.25)
    crit = evaluate_bp4(comp)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.SUPPORTING


def test_bp4_revel_above_threshold_not_triggered():
    comp = ComputationalScore(revel_score=0.5)
    crit = evaluate_bp4(comp)
    assert crit.triggered is False


# --- PVS1 ---

def test_pvs1_triggers_lof_in_intolerant_gene():
    variant = NormalizedVariant(
        hgvs_cdna="NM_007294.4:c.5266dupC",
        gene_symbol="BRCA1",
        transcript="NM_007294.4",
        variant_type="frameshift",
    )
    crit = evaluate_pvs1(variant, _gene(lof_intolerant=True))
    assert crit.triggered is True


def test_pvs1_not_triggered_missense():
    variant = NormalizedVariant(
        hgvs_cdna="NM_007294.4:c.5123A>G",
        gene_symbol="BRCA1",
        transcript="NM_007294.4",
        variant_type="missense",
    )
    crit = evaluate_pvs1(variant, _gene(lof_intolerant=True))
    assert crit.triggered is False


def test_pvs1_not_triggered_tolerant_gene():
    variant = NormalizedVariant(
        hgvs_cdna="NM_000059.4:c.999+1G>A",
        gene_symbol="SOME_GENE",
        transcript="NM_000059.4",
        variant_type="splice_donor",
    )
    crit = evaluate_pvs1(variant, _gene(lof_intolerant=False))
    assert crit.triggered is False


# --- PVS1 (NMD / exon-skip flowchart, via TranscriptAnnotation) ---

def _frameshift_variant() -> NormalizedVariant:
    return NormalizedVariant(
        hgvs_cdna="NM_007294.4:c.5266dupC",
        gene_symbol="BRCA1",
        transcript="NM_007294.4",
        variant_type="frameshift",
    )


def test_pvs1_full_strength_when_not_last_exon():
    annotation = TranscriptAnnotation(
        exon_number=8, total_exons=23, cds_position=1000, cds_length=5592,
    )
    crit = evaluate_pvs1(_frameshift_variant(), _gene(lof_intolerant=True), annotation=annotation)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.VERY_STRONG


def test_pvs1_downgraded_in_last_exon():
    """PTC in the last exon escapes NMD — downgraded from Very Strong."""
    annotation = TranscriptAnnotation(
        exon_number=23, total_exons=23, cds_position=5000, cds_length=5592,
    )
    crit = evaluate_pvs1(_frameshift_variant(), _gene(lof_intolerant=True), annotation=annotation)
    assert crit.triggered is True
    assert crit.applied_strength in (ACMGStrength.STRONG, ACMGStrength.MODERATE)


def test_pvs1_downgraded_to_moderate_for_small_truncation_in_last_exon():
    """PTC in the last exon AND truncating <10% of the protein → Moderate."""
    annotation = TranscriptAnnotation(
        exon_number=23, total_exons=23, cds_position=5500, cds_length=5592,  # ~98% through CDS
    )
    crit = evaluate_pvs1(_frameshift_variant(), _gene(lof_intolerant=True), annotation=annotation)
    assert crit.applied_strength == ACMGStrength.MODERATE


def test_pvs1_downgraded_within_50nt_of_penultimate_exon_end():
    """PTC within the last 50nt of the penultimate exon also escapes NMD."""
    annotation = TranscriptAnnotation(
        exon_number=22, total_exons=23, cds_position=5560, cds_length=5592,  # 32nt from CDS end
    )
    crit = evaluate_pvs1(_frameshift_variant(), _gene(lof_intolerant=True), annotation=annotation)
    assert crit.applied_strength in (ACMGStrength.STRONG, ACMGStrength.MODERATE)


def test_pvs1_not_downgraded_far_from_penultimate_exon_end():
    """PTC in the penultimate exon but >50nt from its end → still full strength."""
    annotation = TranscriptAnnotation(
        exon_number=22, total_exons=23, cds_position=5000, cds_length=5592,  # 592nt from CDS end
    )
    crit = evaluate_pvs1(_frameshift_variant(), _gene(lof_intolerant=True), annotation=annotation)
    assert crit.applied_strength == ACMGStrength.VERY_STRONG


def test_pvs1_splice_in_frame_skip_capped_at_strong():
    variant = NormalizedVariant(
        hgvs_cdna="NM_007294.4:c.999+1G>A",
        gene_symbol="BRCA1",
        transcript="NM_007294.4",
        variant_type="splice_donor",
    )
    annotation = TranscriptAnnotation(
        exon_number=5, total_exons=23, skipped_exon_length_nt=90,  # divisible by 3
    )
    crit = evaluate_pvs1(variant, _gene(lof_intolerant=True), spliceai_max_delta=0.8, annotation=annotation)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.STRONG


def test_pvs1_splice_out_of_frame_skip_treated_as_frameshift():
    variant = NormalizedVariant(
        hgvs_cdna="NM_007294.4:c.999+1G>A",
        gene_symbol="BRCA1",
        transcript="NM_007294.4",
        variant_type="splice_donor",
    )
    annotation = TranscriptAnnotation(
        exon_number=5, total_exons=23, skipped_exon_length_nt=91,  # not divisible by 3
        cds_position=1000, cds_length=5592,
    )
    crit = evaluate_pvs1(variant, _gene(lof_intolerant=True), spliceai_max_delta=0.8, annotation=annotation)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.VERY_STRONG


def test_pvs1_start_loss_applied_at_moderate():
    variant = NormalizedVariant(
        hgvs_cdna="NM_007294.4:c.1A>G",
        gene_symbol="BRCA1",
        transcript="NM_007294.4",
        variant_type="start_lost",
    )
    annotation = TranscriptAnnotation(consequence_terms=["start_lost"])
    crit = evaluate_pvs1(variant, _gene(lof_intolerant=True), annotation=annotation)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.MODERATE


def test_pvs1_no_annotation_falls_back_to_full_strength():
    crit = evaluate_pvs1(_frameshift_variant(), _gene(lof_intolerant=True), annotation=None)
    assert crit.triggered is True
    assert crit.applied_strength == ACMGStrength.VERY_STRONG


# --- PP5 ---

def test_pp5_triggers_pathogenic_clinvar():
    clinvar = ClinVarEvidence(
        variation_id="12345",
        aggregate_classification="Pathogenic",
        review_status="criteria provided, multiple submitters, no conflicts",
        gold_stars=2,
    )
    crit = evaluate_pp5(clinvar)
    assert crit.triggered is True


def test_pp5_not_triggered_vus_clinvar():
    clinvar = ClinVarEvidence(
        variation_id="99999",
        aggregate_classification="Uncertain significance",
        review_status="no assertion criteria provided",
        gold_stars=0,
    )
    crit = evaluate_pp5(clinvar)
    assert crit.triggered is False


def test_pp5_not_triggered_no_clinvar():
    crit = evaluate_pp5(None)
    assert crit.triggered is False


def _gene(lof_intolerant: bool = True) -> GeneInfo:
    return GeneInfo(
        gene_symbol="BRCA1",
        is_lof_intolerant=lof_intolerant,
        inheritance_patterns=["AD"],
    )
