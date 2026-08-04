"""VAROS orchestrator — parallel evidence gathering + ACMG classification.

Pipeline:
  normalize_variant
      └── enrich_genomic_coords (Ensembl REST, async)
      └── asyncio.gather(gnomAD, ClinVar, PubMed, SpliceAI, CADD, REVEL)
              └── acmg_classify → llm_reason → ClassificationResult
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from varos.config import settings
from varos.connectors import gnomad, clinvar, pubmed, alphamissense, spliceai
from varos.classifiers import acmg as acmg_criteria
from varos.classifiers.combiner import classify_detailed as acmg_classify_detailed
from varos.models import (
    ACMGCriterion,
    ClassificationResult,
    ComputationalScore,
    GeneInfo,
    NormalizedVariant,
    PopulationFrequency,
    ClinVarEvidence,
    LiteratureEvidence,
    VariantInput,
)

logger = logging.getLogger("varos.orchestrator")

_ENSEMBL_REST = "https://rest.ensembl.org"
_ENSEMBL_REST_GRCH37 = "https://grch37.rest.ensembl.org"


# ---------------------------------------------------------------------------
# Variant normalization (heuristic HGVS parser)
# ---------------------------------------------------------------------------

def _normalize_variant(vi: VariantInput) -> NormalizedVariant:
    hgvs = vi.hgvs or vi.gene_aa or vi.free_text or ""
    gene = ""
    transcript = ""
    variant_type = None
    chrom = None
    pos = None
    ref = None
    alt = None

    if ":" in hgvs:
        parts = hgvs.split(":", 1)
        gene_or_tx = parts[0].strip()
        notation = parts[1].strip() if len(parts) > 1 else ""
        gene = gene_or_tx.split(".")[0] if gene_or_tx.startswith("NM_") else gene_or_tx
        transcript = gene_or_tx if gene_or_tx.startswith("NM_") else ""

        # Parse genomic HGVS: chr17:g.41276045C>A  or  17:g.41276045C>A
        if notation.startswith("g."):
            chrom = gene_or_tx.replace("chr", "").replace("Chr", "")
            # g.12345A>T  or  g.12345_12347del
            m = re.match(r"g\.(\d+)([A-Z]+)>([A-Z]+)", notation)
            if m:
                pos = int(m.group(1))
                ref = m.group(2)
                alt = m.group(3)
        else:
            notation_lower = notation.lower()
            if "dup" in notation_lower:
                variant_type = "frameshift"
            elif "del" in notation_lower and "ins" not in notation_lower:
                variant_type = "deletion"
            elif "ins" in notation_lower and "del" not in notation_lower:
                variant_type = "insertion"
            elif any(x in notation_lower for x in ["+1", "+2", "-1", "-2", "splice"]):
                variant_type = "splice_donor"
            elif ">" in notation:
                variant_type = "substitution"
                # Try to extract ref/alt from simple SNV: c.1234A>T
                m = re.search(r">([A-Z])$", notation)
                if m:
                    alt = m.group(1)
                m2 = re.search(r"([A-Z])>", notation)
                if m2:
                    ref = m2.group(1)
            elif notation.startswith("c."):
                variant_type = "coding"
    elif "p." in hgvs:
        variant_type = (
            "frameshift" if any(x in hgvs for x in ["*", "Ter", "fs", "X"])
            else "missense"
        )

    if ref and alt and ref == alt:
        ref = None
        alt = None

    return NormalizedVariant(
        hgvs_cdna=hgvs,
        gene_symbol=gene,
        transcript=transcript,
        genome_build=vi.genome_build,
        variant_type=variant_type,
        chrom=chrom,
        pos=pos,
        ref=ref,
        alt=alt,
    )


async def _enrich_genomic_coords(norm: NormalizedVariant) -> NormalizedVariant:
    """
    If chrom/pos are missing and we have a transcript HGVS, call Ensembl REST
    VEP endpoint to get GRCh38 genomic coordinates.

    This enables gnomAD and SpliceAI lookups for transcript-based input like
    NM_007294.4:c.5266dupC.

    Non-blocking: on any error, returns norm unchanged.
    """
    if norm.chrom and norm.pos:
        return norm  # already have coords

    hgvs = norm.hgvs_cdna
    if not hgvs:
        return norm

    base = _ENSEMBL_REST if norm.genome_build == "GRCh38" else _ENSEMBL_REST_GRCH37
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{base}/vep/human/hgvs/{httpx.URL(hgvs)}",
                headers={"Content-Type": "application/json"},
                params={"content-type": "application/json"},
            )
            if resp.status_code != 200:
                return norm
            data = resp.json()
            if not data or not isinstance(data, list):
                return norm
            hit = data[0]
            seq_region = hit.get("seq_region_name", "")
            start = hit.get("start")
            allele_string = hit.get("allele_string", "")  # e.g. "C/T" or "-/C"
            if seq_region and start:
                norm.chrom = seq_region
                norm.pos = int(start)
                if "/" in allele_string:
                    parts = allele_string.split("/", 1)
                    norm.ref = parts[0] if parts[0] != "-" else ""
                    norm.alt = parts[1] if parts[1] != "-" else ""
    except Exception as exc:
        logger.debug("Ensembl VEP coord lookup failed for %s: %s", hgvs, exc)
    return norm


# ---------------------------------------------------------------------------
# Parallel evidence gathering — each returns (result | None, error | None)
# ---------------------------------------------------------------------------

async def _safe_gnomad(norm: NormalizedVariant) -> tuple[PopulationFrequency | None, str | None]:
    if not norm.chrom or not norm.pos:
        return PopulationFrequency(not_found=True), None
    try:
        freq = await gnomad.fetch_gnomad_frequency(
            norm.chrom, norm.pos, norm.ref or "", norm.alt or "", norm.genome_build
        )
        return freq, None
    except Exception as e:
        return PopulationFrequency(not_found=True), f"gnomAD: {e}"


async def _safe_clinvar(norm: NormalizedVariant) -> tuple[ClinVarEvidence | None, str | None]:
    try:
        ev = await clinvar.fetch_clinvar_evidence(norm.hgvs_cdna)
        return ev, None
    except Exception as e:
        return None, f"ClinVar: {e}"


async def _safe_pubmed(norm: NormalizedVariant) -> tuple[LiteratureEvidence | None, str | None]:
    if not norm.gene_symbol:
        return None, None
    try:
        ev = await pubmed.fetch_literature_evidence(
            gene=norm.gene_symbol,
            hgvs_cdna=norm.hgvs_cdna,
            hgvs_protein=norm.hgvs_protein,
        )
        return ev, None
    except Exception as e:
        return None, f"PubMed: {e}"


async def _safe_computational(norm: NormalizedVariant) -> tuple[ComputationalScore | None, str | None]:
    errors = []
    am_data = None
    spliceai_data = None

    if norm.chrom and norm.pos and norm.ref and norm.alt:
        am_data = alphamissense.lookup_score(norm.chrom, norm.pos, norm.ref, norm.alt)
        try:
            spliceai_data = await spliceai.fetch_spliceai_scores(
                norm.chrom, norm.pos, norm.ref or "", norm.alt or "",
                genome_build="38" if norm.genome_build == "GRCh38" else "37",
            )
        except Exception as e:
            errors.append(f"SpliceAI: {e}")

    scores = ComputationalScore(
        alphamissense_score=am_data["am_pathogenicity"] if am_data else None,
        alphamissense_class=am_data["am_class"] if am_data else None,
        spliceai_max_delta=spliceai_data.get("max_delta", 0.0) if spliceai_data else None,
        spliceai_detail=spliceai_data or {},
    )
    return scores, ("; ".join(errors) if errors else None)


# ---------------------------------------------------------------------------
# LLM reasoning
# ---------------------------------------------------------------------------

async def _llm_reason(result: ClassificationResult) -> tuple[str | None, str | None, str | None]:
    """Returns (clinical_note, evidence_summary, patient_note) or (None, None, None)."""
    if not settings.has_llm:
        return None, None, None
    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage

        llm = ChatAnthropic(model=settings.varos_llm_model, api_key=settings.anthropic_api_key)
        triggered_text = "\n".join(
            f"- {c.code} ({c.applied_strength.value}): {c.evidence_text}"
            for c in result.criteria_triggered
        ) or "No criteria triggered."

        prompt = f"""You are a clinical geneticist writing a variant interpretation report.

Variant: {result.variant.hgvs_cdna}
Gene: {result.variant.gene_symbol}
Classification: {result.classification.value} (confidence: {result.confidence}/100)

Triggered ACMG criteria:
{triggered_text}

ClinVar: {result.clinvar_evidence.aggregate_classification if result.clinvar_evidence else 'Not in ClinVar'}
Population frequency: {f"AF={result.population_frequency.allele_frequency:.2e}" if result.population_frequency and not result.population_frequency.not_found else 'Absent from gnomAD'}
Literature: {f"{result.literature_evidence.total_papers} papers, {result.literature_evidence.functional_papers} with functional data" if result.literature_evidence else 'Not searched'}

Write three short paragraphs:
1. CLINICAL SUMMARY (2-3 sentences for a genetic counselor)
2. EVIDENCE SUMMARY (3-4 sentences explaining WHY it was classified this way)
3. PATIENT EXPLANATION (2-3 plain-language sentences starting with "This genetic change...")

Respond ONLY with JSON: {{"clinical_note": "...", "evidence_summary": "...", "patient_note": "..."}}"""

        response = await llm.ainvoke([HumanMessage(content=prompt)])
        text = response.content
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            notes = json.loads(text[start:end])
            return notes.get("clinical_note"), notes.get("evidence_summary"), notes.get("patient_note")
    except Exception:
        pass
    return None, None, None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_classification(variant_input: VariantInput) -> ClassificationResult:
    """Classify a variant end-to-end using parallel evidence gathering."""
    # Step 1: normalize + enrich with genomic coordinates (enables gnomAD/SpliceAI)
    norm = _normalize_variant(variant_input)
    norm = await _enrich_genomic_coords(norm)
    warnings: list[str] = []

    # Step 2: parallel evidence gathering
    (pop_freq, e1), (clinvar_ev, e2), (lit_ev, e3), (comp_scores, e4) = await asyncio.gather(
        _safe_gnomad(norm),
        _safe_clinvar(norm),
        _safe_pubmed(norm),
        _safe_computational(norm),
    )
    for err in [e1, e2, e3, e4]:
        if err:
            warnings.append(err)

    # Step 3: ACMG classification
    splice_delta = comp_scores.spliceai_max_delta if comp_scores else 0.0
    criteria: list[ACMGCriterion] = [
        acmg_criteria.evaluate_pvs1(norm, None, splice_delta or 0.0),
        acmg_criteria.evaluate_pm2(pop_freq),
        acmg_criteria.evaluate_pp3(comp_scores),
        acmg_criteria.evaluate_pp5(clinvar_ev),
        acmg_criteria.evaluate_ba1(pop_freq),
        acmg_criteria.evaluate_bs1(pop_freq, None),
        acmg_criteria.evaluate_bs2(pop_freq, None),
        acmg_criteria.evaluate_bp4(comp_scores),
    ]
    combiner_result = acmg_classify_detailed(criteria)

    result = ClassificationResult(
        variant=norm,
        classification=combiner_result.classification,
        confidence=combiner_result.confidence,
        point_total=combiner_result.point_total,
        posterior_probability=combiner_result.posterior_probability,
        criteria_evaluated=criteria,
        criteria_triggered=[c for c in criteria if c.triggered],
        population_frequency=pop_freq,
        clinvar_evidence=clinvar_ev,
        computational_scores=comp_scores,
        literature_evidence=lit_ev,
        gene_info=None,
        warnings=warnings,
    )

    # Step 4: LLM reasoning (optional, non-blocking)
    clinical_note, evidence_summary, patient_note = await _llm_reason(result)
    result.llm_clinical_note = clinical_note
    result.llm_summary = evidence_summary
    result.llm_patient_note = patient_note

    return result
