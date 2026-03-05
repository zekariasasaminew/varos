"""SpliceAI connector — splice impact prediction scores."""

from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

SPLICEAI_API = "https://spliceailookup-api.broadinstitute.org/spliceai/"

# SpliceAI score types
SCORE_TYPES = ["DS_AG", "DS_AL", "DS_DG", "DS_DL"]  # Acceptor Gain/Loss, Donor Gain/Loss


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_spliceai_scores(
    chrom: str,
    pos: int,
    ref: str,
    alt: str,
    genome_build: str = "38",
    distance: int = 50,
) -> dict:
    """
    Fetch SpliceAI scores from the Broad Institute lookup API.
    Returns dict with DS_AG, DS_AL, DS_DG, DS_DL scores and max_delta.
    Any score > 0.2 warrants attention; > 0.5 is strong evidence of splice impact.
    """
    chrom_clean = chrom.replace("chr", "")
    params = {
        "variant": f"{chrom_clean}-{pos}-{ref}-{alt}",
        "hg": genome_build,
        "distance": distance,
        "mask": 0,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(SPLICEAI_API, params=params)

    if resp.status_code == 404:
        return {"not_found": True, "max_delta": 0.0}

    resp.raise_for_status()
    data = resp.json()

    scores = data.get("scores", [{}])[0] if data.get("scores") else {}
    result: dict = {"not_found": False}
    for key in SCORE_TYPES:
        result[key] = scores.get(key, 0.0)
    result["max_delta"] = max(result.get(k, 0.0) for k in SCORE_TYPES)
    result["position_detail"] = {
        k: scores.get(f"DP_{k.split('_')[1]}", None) for k in SCORE_TYPES
    }
    return result
