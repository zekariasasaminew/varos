"""
ClinVar export routes.

Converts VAROS classification history into ClinVar submission formats.
Saves labs 30-60 min per variant when submitting to ClinVar.

Endpoints:
  GET /v1/classify/history/{record_id}/clinvar-xml  — Single variant ClinVar XML
  GET /v1/classify/history/{record_id}/clinvar-csv  — Single variant CSV row
  GET /v1/classify/history/clinvar-csv              — Bulk CSV for all classifications
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from sqlalchemy.orm import Session

from varos.api.auth import require_api_key
from varos.api.database import get_db
from varos.api.models import User, UsageRecord

router = APIRouter(prefix="/v1/classify/history", tags=["clinvar-export"])


@router.get(
    "/{record_id}/clinvar-xml",
    summary="Export single variant as ClinVar Submission XML",
    responses={200: {"content": {"application/xml": {}}}},
)
async def export_clinvar_xml(
    record_id: int,
    submitter_org: str = Query("My Organization", description="Your organization name for ClinVar"),
    submitter_org_id: str = Query("YOUR_ORG_ID", description="ClinVar submitter organization ID"),
    condition_name: Optional[str] = Query(None, description="Disease/condition name"),
    condition_db: str = Query("OMIM", description="Condition database: OMIM, MedGen, Orphanet"),
    condition_id: Optional[str] = Query(None, description="Condition database ID"),
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Export a classified variant as ClinVar Submission API v2 XML.

    The XML can be directly submitted to ClinVar via their Submission Portal
    or programmatically via the ClinVar Submission API.

    Requires Starter plan or higher.
    """
    record = db.query(UsageRecord).filter(
        UsageRecord.id == record_id,
        UsageRecord.user_id == user.id,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Classification record {record_id} not found")

    # Build a minimal result-like object from the usage record
    result = _record_to_result_stub(record)

    from varos.reports.clinvar_xml import to_clinvar_xml
    xml_str = to_clinvar_xml(
        result,
        submitter_org=submitter_org,
        submitter_org_id=submitter_org_id,
        condition_name=condition_name,
        condition_db=condition_db,
        condition_id=condition_id,
    )

    safe_variant = (record.variant or "variant").replace(":", "_").replace(">", "_")[:40]
    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={
            "Content-Disposition": f'attachment; filename="varos_clinvar_{safe_variant}.xml"'
        },
    )


@router.get(
    "/clinvar-csv",
    summary="Export all classifications as ClinVar bulk CSV",
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_clinvar_bulk_csv(
    limit: int = Query(100, ge=1, le=1000, description="Max variants to export"),
    submitter_org: str = Query("My Organization"),
    collection_method: str = Query("clinical testing"),
    allele_origin: str = Query("germline"),
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Export all recent classifications as a ClinVar bulk upload CSV.

    Compatible with the ClinVar Submission Spreadsheet template.
    Upload directly at: https://submit.ncbi.nlm.nih.gov/clinvar/

    Available on Starter+ plans. Saves 30-60 min per variant vs manual entry.
    """
    records = (
        db.query(UsageRecord)
        .filter(UsageRecord.user_id == user.id)
        .order_by(UsageRecord.created_at.desc())
        .limit(limit)
        .all()
    )

    if not records:
        raise HTTPException(status_code=404, detail="No classification records found")

    results = [_record_to_result_stub(r) for r in records]

    from varos.reports.clinvar_xml import to_clinvar_csv
    csv_str = to_clinvar_csv(
        results,
        submitter_org=submitter_org,
        collection_method=collection_method,
        allele_origin=allele_origin,
    )

    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="varos_clinvar_submission.csv"'},
    )


# ---------------------------------------------------------------------------
# Helper: reconstruct a minimal result-like object from a UsageRecord
# ---------------------------------------------------------------------------

class _VariantStub:
    def __init__(self, hgvs: str, gene: str = ""):
        self.hgvs_cdna = hgvs
        self.gene_symbol = gene or None


class _ClassificationStub:
    def __init__(self, value: str):
        self.value = value


class _ResultStub:
    def __init__(self, record: UsageRecord):
        self.variant = _VariantStub(record.variant or "", "")
        self.classification = _ClassificationStub(record.classification or "Uncertain Significance")
        self.criteria_triggered = []
        self.confidence = record.confidence or 0


def _record_to_result_stub(record: UsageRecord) -> _ResultStub:
    return _ResultStub(record)
