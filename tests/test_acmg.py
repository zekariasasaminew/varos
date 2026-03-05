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
    ClinVarEvidence,
    ComputationalScore,
    GeneInfo,
    NormalizedVariant,
    PopulationFrequency,
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


# --- BP4 (computational benign) ---

def test_bp4_triggers_low_alphamissense():
    comp = _comp(pathogenicity=0.1)
    crit = evaluate_bp4(comp)
    assert crit.triggered is True


def test_bp4_not_triggered_high_alphamissense():
    comp = _comp(pathogenicity=0.8)
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
