"""Core Pydantic data models shared across VAROS."""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Variant input
# ---------------------------------------------------------------------------

class VariantInput(BaseModel):
    """Raw user input — one of these fields must be provided."""
    hgvs: str | None = None          # "NM_007294.4:c.5266dupC"
    rsid: str | None = None           # "rs80357906"
    gene_aa: str | None = None        # "BRCA1:p.Gln1756fs"
    free_text: str | None = None      # "BRCA1 c.5266dupC" — LLM parses this
    genome_build: str = "GRCh38"


class NormalizedVariant(BaseModel):
    """Variant after HGVS normalization via Mutalyzer."""
    hgvs_cdna: str                    # NM_007294.4:c.5266dupC
    hgvs_protein: str | None = None   # NP_009225.1:p.Gln1756ProfsTer74
    gene_symbol: str                   # BRCA1
    transcript: str                    # NM_007294.4
    chrom: str | None = None           # chr17
    pos: int | None = None             # 43045711
    ref: str | None = None             # -
    alt: str | None = None             # C
    genome_build: str = "GRCh38"
    variant_type: str | None = None    # frameshift / missense / splice / synonymous / etc.


# ---------------------------------------------------------------------------
# Evidence from individual data sources
# ---------------------------------------------------------------------------

class PopulationFrequency(BaseModel):
    """Allele frequency data from gnomAD."""
    source: str = "gnomAD v4.1"
    allele_count: int = 0
    allele_number: int = 0
    allele_frequency: float = 0.0
    homozygote_count: int = 0
    popmax_af: float = 0.0
    popmax_population: str | None = None
    ancestry_breakdown: dict[str, float] = Field(default_factory=dict)
    genome_build: str = "GRCh38"
    not_found: bool = False           # True if variant absent from gnomAD


class ClinVarSubmission(BaseModel):
    variation_id: str
    clinical_significance: str        # Pathogenic / Likely pathogenic / VUS / etc.
    review_status: str                 # criteria provided, single submitter / etc.
    gold_stars: int = 0               # 0-4
    submitter: str
    last_evaluated: str | None = None
    conditions: list[str] = Field(default_factory=list)


class ClinVarEvidence(BaseModel):
    source: str = "ClinVar"
    variation_id: str | None = None
    aggregate_classification: str | None = None
    review_status: str | None = None
    gold_stars: int = 0
    submissions: list[ClinVarSubmission] = Field(default_factory=list)
    conflicting_interpretations: bool = False
    not_found: bool = False


class TranscriptAnnotation(BaseModel):
    """Transcript/exon/CDS context from Ensembl VEP + transcript lookup.

    Used by PVS1 to predict nonsense-mediated decay (NMD) and exon-skipping
    outcomes instead of a bare variant-type substring match. All fields are
    optional because upstream annotation calls can fail or be unavailable;
    callers must treat a missing field as "unknown", not "false".
    """
    source: str = "Ensembl VEP"
    transcript_id: str | None = None
    is_mane_select: bool = False
    consequence_terms: list[str] = Field(default_factory=list)
    exon_number: int | None = None        # 1-based rank of the affected/adjacent exon
    total_exons: int | None = None
    cds_position: int | None = None       # 1-based nt offset of the variant within the CDS
    cds_length: int | None = None         # total CDS length in nt, including the stop codon
    protein_position: int | None = None
    protein_length: int | None = None     # length in amino acids, excluding the stop
    skipped_exon_length_nt: int | None = None  # genomic length of the exon predicted skipped
    hgvsc: str | None = None
    hgvsp: str | None = None
    not_found: bool = False


class ComputationalScore(BaseModel):
    """Pathogenicity prediction scores."""
    alphamissense_score: float | None = None      # 0-1, >0.564 = likely pathogenic
    alphamissense_class: str | None = None        # likely_benign / uncertain / likely_pathogenic
    cadd_phred: float | None = None               # >20 deleterious, >30 very deleterious
    revel_score: float | None = None              # 0-1, >0.75 pathogenic
    spliceai_max_delta: float | None = None       # >0.5 strong splice impact
    spliceai_detail: dict[str, float] = Field(default_factory=dict)
    gerp_score: float | None = None               # conservation
    phylop_score: float | None = None             # conservation


class PaperSummary(BaseModel):
    pmid: str
    title: str
    year: int | None = None
    journal: str | None = None
    abstract_snippet: str | None = None
    functional_evidence: bool = False   # LLM-detected: paper has functional/experimental evidence
    key_finding: str | None = None      # LLM-extracted 1-sentence summary


class LiteratureEvidence(BaseModel):
    source: str = "PubMed"
    total_papers: int = 0
    functional_papers: int = 0
    papers: list[PaperSummary] = Field(default_factory=list)
    llm_summary: str | None = None     # LLM narrative of what the literature says


class GeneInfo(BaseModel):
    gene_symbol: str
    omim_id: str | None = None
    disease_associations: list[str] = Field(default_factory=list)
    inheritance_patterns: list[str] = Field(default_factory=list)  # AD, AR, XL, etc.
    is_lof_intolerant: bool = False   # pLI > 0.9 from gnomAD
    pli_score: float | None = None
    has_vcep_rules: bool = False      # ClinGen VCEP exists for this gene


# ---------------------------------------------------------------------------
# ACMG classification
# ---------------------------------------------------------------------------

class ACMGStrength(str, Enum):
    VERY_STRONG = "very_strong"
    STRONG = "strong"
    MODERATE = "moderate"
    SUPPORTING = "supporting"


class ACMGDirection(str, Enum):
    PATHOGENIC = "pathogenic"
    BENIGN = "benign"


class ACMGCriterion(BaseModel):
    code: str                          # e.g. "PVS1", "PM2", "BA1"
    direction: ACMGDirection
    default_strength: ACMGStrength
    applied_strength: ACMGStrength    # may be upgraded/downgraded
    triggered: bool
    evidence_text: str                 # human-readable explanation
    citations: list[str] = Field(default_factory=list)


class ACMGClassification(str, Enum):
    PATHOGENIC = "Pathogenic"
    LIKELY_PATHOGENIC = "Likely Pathogenic"
    VUS = "Variant of Uncertain Significance"
    LIKELY_BENIGN = "Likely Benign"
    BENIGN = "Benign"


class ClassificationResult(BaseModel):
    """Final ACMG classification with all evidence."""
    variant: NormalizedVariant
    classification: ACMGClassification
    confidence: int = Field(ge=0, le=100)   # 0-100
    point_total: int = 0                    # Tavtigian 2018 Bayesian point total
    posterior_probability: float = Field(0.0, ge=0.0, le=1.0)  # P(pathogenic)
    criteria_triggered: list[ACMGCriterion] = Field(default_factory=list)
    criteria_evaluated: list[ACMGCriterion] = Field(default_factory=list)

    # Raw evidence
    population_frequency: PopulationFrequency | None = None
    clinvar_evidence: ClinVarEvidence | None = None
    computational_scores: ComputationalScore | None = None
    literature_evidence: LiteratureEvidence | None = None
    gene_info: GeneInfo | None = None

    # LLM-generated narrative
    llm_summary: str | None = None          # 2-3 sentence plain-language summary
    llm_clinical_note: str | None = None    # For clinician report
    llm_patient_note: str | None = None     # For patient explanation

    # Metadata
    varos_version: str = "0.1.0"
    genome_build: str = "GRCh38"
    vcep_rules_applied: bool = False
    warnings: list[str] = Field(default_factory=list)

    @property
    def classification_badge(self) -> str:
        """Colored badge text for terminal display."""
        colors = {
            ACMGClassification.PATHOGENIC: "red",
            ACMGClassification.LIKELY_PATHOGENIC: "orange3",
            ACMGClassification.VUS: "yellow",
            ACMGClassification.LIKELY_BENIGN: "cyan",
            ACMGClassification.BENIGN: "green",
        }
        return colors.get(self.classification, "white")
