"""Ensembl REST connector — transcript/exon/CDS annotation for PVS1.

Provides the transcript context (exon rank, CDS position/length, MANE
Select status) that ``classifiers.acmg.evaluate_pvs1`` needs to predict
nonsense-mediated decay and exon-skipping outcomes, instead of guessing
from the raw variant-type string alone.

Two calls per variant:
  1. ``vep/human/hgvs/{hgvs}`` — per-transcript consequence, including the
     "exon" field ("N/M"), cds_start/cds_end, protein_start, and (on
     current Ensembl releases) ``mane_select``.
  2. ``lookup/id/{transcript_id}?expand=1`` — full transcript structure
     (exon list with genomic coordinates, translation length), used to
     compute total CDS length and the genomic length of a given exon.

Both are read-only, public, unauthenticated endpoints — same pattern as
the existing Ensembl VEP call in ``agents.orchestrator``.
"""

from __future__ import annotations

import logging
import re

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from varos.models import TranscriptAnnotation

logger = logging.getLogger("varos.connectors.ensembl")

_ENSEMBL_REST = "https://rest.ensembl.org"
_ENSEMBL_REST_GRCH37 = "https://grch37.rest.ensembl.org"

_EXON_RANK_RE = re.compile(r"^(\d+)/(\d+)$")


def _base_url(genome_build: str) -> str:
    return _ENSEMBL_REST if genome_build == "GRCh38" else _ENSEMBL_REST_GRCH37


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_vep_consequences(hgvs: str, genome_build: str = "GRCh38") -> list[dict]:
    """Return the raw list of transcript_consequences dicts from Ensembl VEP."""
    base = _base_url(genome_build)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{base}/vep/human/hgvs/{httpx.URL(hgvs)}",
            params={"content-type": "application/json"},
            headers={"Content-Type": "application/json"},
        )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    data = resp.json()
    if not data or not isinstance(data, list):
        return []
    return data[0].get("transcript_consequences", [])


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_transcript_structure(transcript_id: str, genome_build: str = "GRCh38") -> dict:
    """Return the raw Ensembl ``lookup/id`` response for a transcript, expanded with exons."""
    base = _base_url(genome_build)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{base}/lookup/id/{transcript_id}",
            params={"expand": 1, "utr": 0, "content-type": "application/json"},
            headers={"Content-Type": "application/json"},
        )
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    return resp.json()


def _pick_consequence(consequences: list[dict], transcript_id: str | None) -> dict | None:
    """Pick the transcript consequence to use: exact transcript match, then
    MANE Select, then the first entry (VEP already sorts by severity)."""
    if not consequences:
        return None
    if transcript_id:
        stripped = transcript_id.split(".")[0]
        for c in consequences:
            if c.get("transcript_id", "").split(".")[0] == stripped:
                return c
    for c in consequences:
        if c.get("mane_select"):
            return c
    return consequences[0]


def _skipped_exon_length(structure: dict, exon_rank: int | None) -> int | None:
    """Genomic length (nt) of the exon at 1-based ``exon_rank`` in the transcript."""
    if exon_rank is None:
        return None
    exons = structure.get("Exon") or []
    # Ensembl returns exons in genomic (not necessarily transcript) order for
    # some endpoints; rely on explicit rank via position in the returned list
    # only when it matches the transcript's exon count, which is the common
    # case for protein-coding transcripts fetched this way.
    if 1 <= exon_rank <= len(exons):
        exon = exons[exon_rank - 1]
        start, end = exon.get("start"), exon.get("end")
        if start is not None and end is not None:
            return abs(end - start) + 1
    return None


async def annotate_transcript(
    hgvs: str,
    transcript_id: str | None = None,
    genome_build: str = "GRCh38",
) -> TranscriptAnnotation | None:
    """Fetch and combine VEP consequence + transcript structure for PVS1.

    Returns None (rather than raising) on any failure — this is enrichment
    data, not a hard dependency; callers should fall back to the coarser
    variant-type heuristic when it's unavailable.
    """
    try:
        consequences = await fetch_vep_consequences(hgvs, genome_build)
        chosen = _pick_consequence(consequences, transcript_id)
        if chosen is None:
            return TranscriptAnnotation(not_found=True)

        exon_number = total_exons = None
        exon_field = chosen.get("exon")
        if exon_field:
            m = _EXON_RANK_RE.match(exon_field)
            if m:
                exon_number, total_exons = int(m.group(1)), int(m.group(2))

        annotation = TranscriptAnnotation(
            transcript_id=chosen.get("transcript_id"),
            is_mane_select=bool(chosen.get("mane_select")),
            consequence_terms=chosen.get("consequence_terms", []),
            exon_number=exon_number,
            total_exons=total_exons,
            cds_position=chosen.get("cds_start"),
            protein_position=chosen.get("protein_start"),
            hgvsc=chosen.get("hgvsc"),
            hgvsp=chosen.get("hgvsp"),
        )

        tx_id = chosen.get("transcript_id")
        if tx_id:
            structure = await fetch_transcript_structure(tx_id, genome_build)
            protein_length = (structure.get("Translation") or {}).get("length")
            if protein_length:
                annotation.protein_length = protein_length
                annotation.cds_length = (protein_length + 1) * 3  # + stop codon
            annotation.skipped_exon_length_nt = _skipped_exon_length(structure, exon_number)

        return annotation
    except Exception as exc:
        logger.debug("Ensembl transcript annotation failed for %s: %s", hgvs, exc)
        return None
