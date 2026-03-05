"""Classification routes — POST /v1/classify, POST /v1/classify/report."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import io

from sqlalchemy.orm import Session

from varos.agents.orchestrator import run_classification
from varos.api.auth import require_quota, record_usage
from varos.api.database import get_db
from varos.api.models import User
from varos.api.schemas import ClassifyRequest, ClassifyResponse, CriterionResponse
from varos.models import VariantInput

router = APIRouter(prefix="/v1", tags=["classify"])


def _build_response(result) -> ClassifyResponse:
    return ClassifyResponse(
        variant=result.variant.hgvs_cdna,
        gene=result.variant.gene_symbol or "",
        classification=result.classification.value,
        confidence=result.confidence,
        criteria_triggered=[
            CriterionResponse(
                code=c.code,
                direction=c.direction.value,
                strength=c.applied_strength.value,
                triggered=c.triggered,
                evidence=c.evidence_text,
            )
            for c in result.criteria_triggered
        ],
        population_frequency=(
            result.population_frequency.allele_frequency
            if result.population_frequency and not result.population_frequency.not_found
            else None
        ),
        clinvar_classification=(
            result.clinvar_evidence.aggregate_classification
            if result.clinvar_evidence else None
        ),
        clinvar_stars=(
            result.clinvar_evidence.gold_stars
            if result.clinvar_evidence else None
        ),
        alphamissense_score=(
            result.computational_scores.alphamissense_score
            if result.computational_scores else None
        ),
        llm_summary=result.llm_summary,
        llm_clinical_note=result.llm_clinical_note,
        llm_patient_note=result.llm_patient_note,
        warnings=result.warnings,
    )


@router.post("/classify", response_model=ClassifyResponse, summary="Classify a genetic variant")
async def classify_variant(
    body: ClassifyRequest,
    user: User = Depends(require_quota),
    db: Session = Depends(get_db),
) -> ClassifyResponse:
    """
    Classify a genetic variant using ACMG/AMP 2015 guidelines.

    Queries ClinVar, gnomAD, PubMed, AlphaMissense, and SpliceAI in parallel,
    applies all applicable ACMG criteria, and optionally generates an
    AI-powered evidence narrative.
    """
    try:
        vi = VariantInput(hgvs=body.variant, genome_build=body.genome_build)
        result = await run_classification(vi)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Classification failed: {e}")

    record_usage(db, user, body.variant, result.classification.value, result.confidence)
    return _build_response(result)


@router.post("/classify/report", summary="Classify and return PDF report")
async def classify_report(
    body: ClassifyRequest,
    user: User = Depends(require_quota),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """
    Classify a variant and return a clinical-quality PDF report.
    PDF is streamed directly — save to disk on the client side.
    """
    try:
        vi = VariantInput(hgvs=body.variant, genome_build=body.genome_build)
        result = await run_classification(vi)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Classification failed: {e}")

    record_usage(db, user, body.variant, result.classification.value, result.confidence)

    try:
        from varos.reports.pdf import to_html
        html = to_html(result)

        try:
            from weasyprint import HTML
            pdf_bytes = HTML(string=html).write_pdf()
            media_type = "application/pdf"
            filename = f"varos_report_{result.variant.gene_symbol or 'variant'}.pdf"
            content = io.BytesIO(pdf_bytes)
        except (ImportError, Exception):
            # Fallback to HTML if WeasyPrint not available
            html_bytes = html.encode("utf-8")
            media_type = "text/html"
            filename = f"varos_report_{result.variant.gene_symbol or 'variant'}.html"
            content = io.BytesIO(html_bytes)

        safe_name = filename.replace(":", "_").replace(">", "_")
        return StreamingResponse(
            content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {e}")


# ---------------------------------------------------------------------------
# Somatic classification endpoint (AMP/ASCO/CAP 2017)
# ---------------------------------------------------------------------------

class SomaticClassifyRequest(ClassifyRequest):
    """Extends base request with somatic-specific parameters."""
    tumor_type: str = "solid_tumor"
    gene: Optional[str] = None


@router.post(
    "/classify/somatic",
    summary="Classify a somatic variant (AMP/ASCO/CAP 2017)",
    tags=["classification"],
)
async def classify_somatic_variant(
    body: SomaticClassifyRequest,
    user: User = Depends(require_quota),
    db: Session = Depends(get_db),
):
    """
    Classify a somatic variant using AMP/ASCO/CAP 2017 guidelines.

    Returns Tier I–IV classification with oncogenicity, therapy evidence
    from OncoKB and CIViC, and clinical trial matches.

    - **Tier I**: Strong clinical significance (FDA-approved therapies)
    - **Tier II**: Potential clinical significance (off-label / investigational)
    - **Tier III**: Variant of unknown clinical significance
    - **Tier IV**: Benign somatic polymorphism

    Requires `Oncology Pro` plan or higher.
    """
    try:
        from varos.classifiers.somatic import classify_somatic
        result = await classify_somatic(
            variant_hgvs=body.variant,
            gene=body.gene or "",
            tumor_type=body.tumor_type,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Somatic classification failed: {exc}")

    record_usage(db, user, body.variant, f"somatic:{result.tier}", result.confidence)
    return result.__dict__
