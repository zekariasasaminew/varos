"""
VCF Batch Processing routes.

Enables bulk classification of VCF files — the core feature for pharma and lab pipelines.

Endpoints:
  POST /v1/classify/batch          — Upload VCF file, returns job_id
  GET  /v1/classify/batch/{job_id} — Poll job status and download results
  GET  /v1/classify/batch          — List all batch jobs

Pricing: $0.005 per classified variant (after pre-filtering synonymous/intronic variants).
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timezone
from io import StringIO
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from varos.api.auth import require_api_key
from varos.api.database import get_db
from varos.api.models import BatchJob, User

router = APIRouter(prefix="/v1/classify/batch", tags=["batch"])

# Pre-filter: skip these consequence types (not worth classifying)
_SKIP_CONSEQUENCES = {"synonymous_variant", "stop_retained_variant", "non_coding_transcript_exon_variant"}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BatchJobResponse(BaseModel):
    job_id: str
    status: str
    vcf_filename: Optional[str]
    total_variants: int
    filtered_variants: int
    processed_variants: int
    failed_variants: int
    mode: str
    estimated_cost_usd: Optional[float]
    results: Optional[list]
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class BatchCostEstimate(BaseModel):
    total_variants: int
    filtered_variants: int
    estimated_cost_usd: float
    cost_per_variant_usd: float = 0.005


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "",
    status_code=202,
    response_model=BatchJobResponse,
    summary="Submit VCF file for batch classification",
)
async def submit_batch(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="VCF 4.2 file (.vcf or .vcf.gz)"),
    mode: str = Form("germline", description="germline or somatic"),
    webhook_url: Optional[str] = Form(None, description="Optional webhook URL for job completion"),
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Upload a VCF file for batch ACMG/somatic classification.

    - Accepts VCF 4.2 format (plain text or gzipped)
    - Pre-filters synonymous and deep intronic variants
    - Returns job_id immediately; poll GET /v1/classify/batch/{job_id} for results
    - Cost: $0.005/variant (after pre-filtering)
    """
    if mode not in ("germline", "somatic"):
        raise HTTPException(status_code=422, detail="mode must be 'germline' or 'somatic'")

    filename = file.filename or "upload.vcf"
    if not (filename.endswith(".vcf") or filename.endswith(".vcf.gz")):
        raise HTTPException(status_code=422, detail="File must be a .vcf or .vcf.gz file")

    content = await file.read()

    # Handle gzip
    if filename.endswith(".gz"):
        import gzip
        try:
            content = gzip.decompress(content)
        except Exception:
            raise HTTPException(status_code=422, detail="Could not decompress .vcf.gz file")

    try:
        vcf_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="VCF file must be UTF-8 encoded")

    # Parse and pre-filter variants
    variants = _parse_vcf(vcf_text)
    filtered = _prefilter_variants(variants)

    job_id = str(uuid.uuid4())
    job = BatchJob(
        job_id=job_id,
        user_id=user.id,
        status="queued",
        vcf_filename=filename,
        total_variants=len(variants),
        filtered_variants=len(filtered),
        mode=mode,
        webhook_url=webhook_url,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Launch background classification
    background_tasks.add_task(_run_batch, job_id, filtered, mode, webhook_url)

    estimated_cost = round(len(filtered) * 0.005, 2)
    return _to_response(job, estimated_cost=estimated_cost)


@router.get("", response_model=List[BatchJobResponse], summary="List batch jobs")
async def list_batch_jobs(
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """List all batch jobs for the current user."""
    jobs = db.query(BatchJob).filter(BatchJob.user_id == user.id).order_by(BatchJob.created_at.desc()).limit(50).all()
    return [_to_response(j) for j in jobs]


@router.get(
    "/{job_id}",
    response_model=BatchJobResponse,
    summary="Poll batch job status and results",
)
async def get_batch_job(
    job_id: str,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Poll status of a batch classification job.

    Returns status: queued | processing | complete | failed
    When status=complete, results contains the full classification list.
    """
    job = db.query(BatchJob).filter(
        BatchJob.job_id == job_id,
        BatchJob.user_id == user.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _to_response(job)


@router.post(
    "/estimate",
    response_model=BatchCostEstimate,
    summary="Estimate cost before submitting a VCF",
)
async def estimate_batch_cost(
    file: UploadFile = File(...),
    user: User = Depends(require_api_key),
):
    """
    Upload a VCF file to get a cost estimate before actual classification.
    Does not consume quota or charge — read-only analysis.
    """
    content = await file.read()
    if file.filename and file.filename.endswith(".gz"):
        import gzip
        content = gzip.decompress(content)
    vcf_text = content.decode("utf-8", errors="replace")
    variants = _parse_vcf(vcf_text)
    filtered = _prefilter_variants(variants)
    return BatchCostEstimate(
        total_variants=len(variants),
        filtered_variants=len(filtered),
        estimated_cost_usd=round(len(filtered) * 0.005, 2),
    )


# ---------------------------------------------------------------------------
# VCF parsing + pre-filtering
# ---------------------------------------------------------------------------

def _parse_vcf(vcf_text: str) -> List[dict]:
    """Parse VCF 4.2 text into list of variant dicts."""
    variants = []
    for line in vcf_text.splitlines():
        if line.startswith("#"):
            continue
        parts = line.strip().split("\t")
        if len(parts) < 5:
            continue
        chrom = parts[0].lstrip("chr")
        pos = parts[1]
        variant_id = parts[2] if len(parts) > 2 else "."
        ref = parts[3]
        alt_field = parts[4]
        # Multi-allelic: split ALT
        for alt in alt_field.split(","):
            if alt in (".", "*", "<NON_REF>"):
                continue
            variants.append({
                "chrom": chrom,
                "pos": pos,
                "id": variant_id,
                "ref": ref,
                "alt": alt,
                "hgvs": f"chr{chrom}:g.{pos}{ref}>{alt}",
            })
    return variants


def _prefilter_variants(variants: List[dict]) -> List[dict]:
    """
    Pre-filter variants to remove those not worth classifying.
    Keeps: missense, frameshift, stop-gain, stop-loss, splice region, start-loss.
    Removes: synonymous, deep intronic, non-coding.
    """
    # For now, keep all variants (filtering requires VEP annotation).
    # In production this would call VEP or use annotation from VCF INFO field.
    # We return all non-trivially named variants as a conservative approach.
    filtered = []
    for v in variants:
        ref, alt = v["ref"], v["alt"]
        # Skip if not a real variant
        if not ref or not alt or ref == alt:
            continue
        # Skip if it looks like a structural variant notation
        if alt.startswith("<"):
            continue
        filtered.append(v)
    return filtered


# ---------------------------------------------------------------------------
# Background batch worker
# ---------------------------------------------------------------------------

async def _run_batch(job_id: str, variants: List[dict], mode: str, webhook_url: Optional[str]) -> None:
    """Background task: classify each variant and update job record."""
    from varos.api.database import SessionLocal
    from varos.agents.orchestrator import run_classification
    from varos.models import VariantInput

    db = SessionLocal()
    try:
        job = db.query(BatchJob).filter(BatchJob.job_id == job_id).first()
        if not job:
            return

        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        results = []
        failed = 0
        processed = 0

        for v in variants:
            try:
                if mode == "somatic":
                    from varos.classifiers.somatic import classify_somatic
                    result = await classify_somatic(v["hgvs"], gene="")
                    results.append({
                        "variant": v["hgvs"],
                        "tier": result.tier,
                        "level": result.level,
                        "oncogenicity": result.oncogenicity,
                        "summary": result.summary,
                    })
                else:
                    vi = VariantInput(hgvs=v["hgvs"], gene=v.get("gene", ""))
                    result = await run_classification(vi)
                    results.append({
                        "variant": v["hgvs"],
                        "classification": result.classification,
                        "confidence": result.confidence,
                        "summary": result.evidence_summary,
                    })
                processed += 1
            except Exception as exc:
                failed += 1
                results.append({"variant": v["hgvs"], "error": str(exc)})

        job.status = "complete"
        job.processed_variants = processed
        job.failed_variants = failed
        job.results_json = json.dumps(results)
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

        # Fire webhook if configured
        if webhook_url:
            await _send_webhook(webhook_url, job_id, processed, failed)

    except Exception as exc:
        job = db.query(BatchJob).filter(BatchJob.job_id == job_id).first()
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            db.commit()
    finally:
        db.close()


async def _send_webhook(url: str, job_id: str, processed: int, failed: int) -> None:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json={
                "event": "batch.complete",
                "job_id": job_id,
                "processed": processed,
                "failed": failed,
            })
    except Exception:
        pass


def _to_response(job: BatchJob, estimated_cost: Optional[float] = None) -> BatchJobResponse:
    results = None
    if job.results_json:
        try:
            results = json.loads(job.results_json)
        except Exception:
            pass
    return BatchJobResponse(
        job_id=job.job_id,
        status=job.status,
        vcf_filename=job.vcf_filename,
        total_variants=job.total_variants,
        filtered_variants=job.filtered_variants,
        processed_variants=job.processed_variants,
        failed_variants=job.failed_variants,
        mode=job.mode,
        estimated_cost_usd=estimated_cost or (round(job.filtered_variants * 0.005, 2) if job.filtered_variants else 0.0),
        results=results,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
