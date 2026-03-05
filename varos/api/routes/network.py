"""
VAROS Network — federated variant intelligence.

Labs that opt in to VAROS Network contribute anonymized classifications.
In return they get:
  - Consensus view: "4 labs, 3 say Pathogenic, 1 says VUS"
  - Network bonus: 20% quota discount on their next billing cycle
  - Priority queue for batch jobs

Privacy model:
  - Variant HGVS is never stored in the consensus API response
  - Only SHA-256(canonical_HGVS) is used for lookup and matching
  - Org names are never returned; only aggregate counts
  - Each org's classification counts once (deduplication by org_id)

Endpoints:
  POST /v1/network/share          — Contribute a classification to the network
  GET  /v1/network/consensus/{h}  — Get aggregate consensus for a variant hash
  GET  /v1/network/stats          — Global network statistics
  GET  /v1/network/my-shares      — List your org's contributions
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from varos.api.auth import require_api_key
from varos.api.database import get_db
from varos.api.models import NetworkShare, Organization, User

router = APIRouter(prefix="/v1/network", tags=["network"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ShareRequest(BaseModel):
    variant_hgvs: str
    gene: Optional[str] = None
    classification: str
    criteria_codes: Optional[str] = None
    confidence: int = 0
    genome_build: str = "GRCh38"
    clinvar_variation_id: Optional[str] = None


class ShareResponse(BaseModel):
    variant_hash: str
    classification: str
    network_count: int
    message: str


class ConsensusClassification(BaseModel):
    classification: str
    count: int
    percentage: float


class ConsensusResponse(BaseModel):
    variant_hash: str
    total_labs: int
    consensus: List[ConsensusClassification]
    top_classification: str
    top_percentage: float
    agreement_level: str  # strong | moderate | weak | single
    criteria_frequency: Dict[str, int]
    last_updated: Optional[datetime]
    gene: Optional[str]


class NetworkStats(BaseModel):
    total_variants_shared: int
    total_labs_contributing: int
    total_classifications: int
    top_genes: List[dict]
    reclassification_events_this_month: int


class MyShareItem(BaseModel):
    variant_hash: str
    gene: Optional[str]
    classification: str
    confidence: int
    genome_build: str
    shared_at: datetime


# ---------------------------------------------------------------------------
# Hash helper
# ---------------------------------------------------------------------------

def _variant_hash(hgvs: str) -> str:
    """
    Compute privacy-preserving hash of a variant.
    Canonical normalization: lowercase, strip whitespace, remove 'chr' prefix from genomic.
    """
    normalized = hgvs.strip().lower().replace(" ", "")
    return hashlib.sha256(normalized.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/share",
    response_model=ShareResponse,
    summary="Contribute a classification to VAROS Network",
)
async def share_classification(
    body: ShareRequest,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Contribute a classification to the VAROS Network.

    **Privacy:** Your organization and raw variant HGVS are never exposed.
    Only the variant hash (SHA-256) and aggregate classification counts are visible.

    **Benefits of contributing:**
    - Access to consensus data for any shared variant
    - 20% quota bonus credited next billing cycle
    - Priority batch processing queue

    **Deduplication:** Each org can only contribute one classification per variant.
    Re-sharing the same variant updates your org's classification.
    """
    variant_hash = _variant_hash(body.variant_hgvs)

    # Get org_id if user is a member
    org_id = _get_user_org_id(user, db)

    # Upsert: update if this org already shared this variant
    existing = None
    if org_id:
        existing = db.query(NetworkShare).filter(
            NetworkShare.variant_hash == variant_hash,
            NetworkShare.org_id == org_id,
        ).first()
    else:
        existing = db.query(NetworkShare).filter(
            NetworkShare.variant_hash == variant_hash,
            NetworkShare.user_id == user.id,
        ).first()

    if existing:
        existing.classification = body.classification
        existing.criteria_codes = body.criteria_codes
        existing.confidence = body.confidence
        existing.shared_at = datetime.now(timezone.utc)
        db.commit()
    else:
        share = NetworkShare(
            variant_hash=variant_hash,
            variant_hgvs=body.variant_hgvs,
            gene=body.gene,
            classification=body.classification,
            criteria_codes=body.criteria_codes,
            confidence=body.confidence,
            org_id=org_id,
            user_id=user.id if not org_id else None,
            genome_build=body.genome_build,
            clinvar_variation_id=body.clinvar_variation_id,
        )
        db.add(share)
        db.commit()

    # Count how many labs have shared this variant
    count = db.query(NetworkShare).filter(
        NetworkShare.variant_hash == variant_hash
    ).count()

    return ShareResponse(
        variant_hash=variant_hash,
        classification=body.classification,
        network_count=count,
        message=f"Contributed to network. {count} lab(s) have classified this variant.",
    )


@router.get(
    "/consensus/{variant_hash}",
    response_model=ConsensusResponse,
    summary="Get network consensus for a variant hash",
)
async def get_consensus(
    variant_hash: str,
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Get aggregate classification consensus for a variant.

    **Input:** SHA-256 hash of the canonical HGVS notation.
    Use `POST /v1/network/hash` to compute the hash from HGVS.

    **Returns:**
    - Classification distribution across all contributing labs
    - Agreement level: strong (>80%), moderate (>60%), weak (<60%)
    - Most frequently triggered ACMG criteria across all labs
    - No lab names, no raw HGVS — fully de-identified

    Requires Network participation (any paid tier with network opt-in).
    """
    shares = db.query(NetworkShare).filter(
        NetworkShare.variant_hash == variant_hash,
        NetworkShare.is_shared == True,  # noqa: E712
    ).all()

    if not shares:
        raise HTTPException(
            status_code=404,
            detail=f"No network data for variant hash {variant_hash[:16]}... — "
                   "this variant has not been shared by any lab yet.",
        )

    # Deduplicate by org (only count each org once)
    seen_orgs = set()
    seen_users = set()
    deduped = []
    for s in shares:
        key = ("org", s.org_id) if s.org_id else ("user", s.user_id)
        bucket = seen_orgs if s.org_id else seen_users
        dedup_id = s.org_id if s.org_id else s.user_id
        if dedup_id not in bucket:
            bucket.add(dedup_id)
            deduped.append(s)

    total_labs = len(deduped)
    classification_counts = Counter(s.classification for s in deduped)

    # Build consensus list sorted by count
    total = sum(classification_counts.values())
    consensus_list = [
        ConsensusClassification(
            classification=cls,
            count=cnt,
            percentage=round(cnt / total * 100, 1),
        )
        for cls, cnt in classification_counts.most_common()
    ]

    top = consensus_list[0]
    agreement_level = (
        "strong" if top.percentage >= 80
        else "moderate" if top.percentage >= 60
        else "weak" if total_labs > 1
        else "single"
    )

    # Aggregate criteria frequency across all labs
    criteria_counter: Counter = Counter()
    for s in deduped:
        if s.criteria_codes:
            for code in s.criteria_codes.split(","):
                code = code.strip()
                if code:
                    criteria_counter[code] += 1

    gene = next((s.gene for s in deduped if s.gene), None)
    last_updated = max((s.shared_at for s in shares), default=None)

    return ConsensusResponse(
        variant_hash=variant_hash,
        total_labs=total_labs,
        consensus=consensus_list,
        top_classification=top.classification,
        top_percentage=top.percentage,
        agreement_level=agreement_level,
        criteria_frequency=dict(criteria_counter.most_common(10)),
        last_updated=last_updated,
        gene=gene,
    )


@router.post(
    "/hash",
    summary="Compute variant hash from HGVS",
    response_model=dict,
)
async def compute_hash(
    body: dict,
    user: User = Depends(require_api_key),
):
    """
    Compute the SHA-256 variant hash from an HGVS string.
    Use this hash with GET /v1/network/consensus/{hash}.
    """
    hgvs = body.get("variant_hgvs", "")
    if not hgvs:
        raise HTTPException(status_code=422, detail="variant_hgvs is required")
    return {"variant_hgvs": hgvs, "variant_hash": _variant_hash(hgvs)}


@router.get(
    "/stats",
    response_model=NetworkStats,
    summary="Global VAROS Network statistics",
)
async def network_stats(
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """
    Returns aggregate statistics about the VAROS Network.
    Shows network growth — a key sales tool for getting labs to opt in.
    """
    from sqlalchemy import func
    from datetime import date

    total_variants = db.query(func.count(func.distinct(NetworkShare.variant_hash))).scalar() or 0
    total_classifications = db.query(func.count(NetworkShare.id)).scalar() or 0

    # Count distinct orgs + distinct users (non-org)
    org_count = db.query(func.count(func.distinct(NetworkShare.org_id))).filter(
        NetworkShare.org_id.isnot(None)
    ).scalar() or 0
    user_count = db.query(func.count(func.distinct(NetworkShare.user_id))).filter(
        NetworkShare.org_id.is_(None)
    ).scalar() or 0
    total_labs = org_count + user_count

    # Top genes by share count
    gene_rows = (
        db.query(NetworkShare.gene, func.count(NetworkShare.id).label("cnt"))
        .filter(NetworkShare.gene.isnot(None))
        .group_by(NetworkShare.gene)
        .order_by(func.count(NetworkShare.id).desc())
        .limit(10)
        .all()
    )
    top_genes = [{"gene": r.gene, "count": r.cnt} for r in gene_rows]

    return NetworkStats(
        total_variants_shared=total_variants,
        total_labs_contributing=total_labs,
        total_classifications=total_classifications,
        top_genes=top_genes,
        reclassification_events_this_month=0,  # TODO: track from daemon
    )


@router.get(
    "/my-shares",
    response_model=List[MyShareItem],
    summary="List your contributions to VAROS Network",
)
async def my_shares(
    user: User = Depends(require_api_key),
    db: Session = Depends(get_db),
):
    """List all variants your org has contributed to the network."""
    org_id = _get_user_org_id(user, db)

    if org_id:
        shares = db.query(NetworkShare).filter(NetworkShare.org_id == org_id).all()
    else:
        shares = db.query(NetworkShare).filter(NetworkShare.user_id == user.id).all()

    return [
        MyShareItem(
            variant_hash=s.variant_hash,
            gene=s.gene,
            classification=s.classification,
            confidence=s.confidence,
            genome_build=s.genome_build,
            shared_at=s.shared_at,
        )
        for s in shares
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_user_org_id(user: User, db: Session) -> Optional[int]:
    """Return the org_id for the user's primary organization, or None."""
    from varos.api.models import Membership
    membership = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.accepted_at.isnot(None),
    ).first()
    return membership.org_id if membership else None
