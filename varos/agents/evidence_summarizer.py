"""
LLM Evidence Summarizer Agent.

Reads PubMed abstract text and extracts structured ACMG evidence annotations.
This is VAROS's unique intelligence layer — no competitor does this.

For each paper, the LLM extracts:
- Which ACMG criterion is supported (PS3, PM1, PP3, etc.)
- Evidence strength (supporting, moderate, strong, very_strong)
- A concise evidence statement from the paper
- Confidence score (0-1)

The extracted evidence integrates into the ACMG combiner with confidence weighting:
high-confidence evidence (>0.85) counts at full weight; lower confidence is downweighted.

Usage:
    from varos.agents.evidence_summarizer import summarize_pubmed_evidence

    results = await summarize_pubmed_evidence(
        variant_hgvs="NM_007294.4:c.5266dupC",
        gene="BRCA1",
        abstracts=[{"pmid": "36721891", "title": "...", "abstract": "..."}]
    )
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

logger = logging.getLogger("varos.agents.evidence_summarizer")

# ACMG criteria that functional/clinical papers typically support
_SUPPORTED_CRITERIA = {
    "PS1", "PS2", "PS3", "PS4",
    "PM1", "PM2", "PM3", "PM4", "PM5", "PM6",
    "PP1", "PP2", "PP3", "PP4", "PP5",
    "BA1",
    "BS1", "BS2", "BS3", "BS4",
    "BP1", "BP2", "BP3", "BP4", "BP5", "BP6", "BP7",
}

_STRENGTH_VALUES = {"supporting", "moderate", "strong", "very_strong", "stand_alone"}

_EXTRACTION_PROMPT = """You are an expert clinical genomicist specializing in ACMG/AMP 2015 variant classification.

Analyze the following PubMed abstract for variant classification evidence.

Variant: {variant_hgvs}
Gene: {gene}

Abstract:
Title: {title}
PMID: {pmid}
---
{abstract}
---

Extract ALL ACMG/AMP 2015 classification evidence from this abstract.
For each piece of evidence found, return a JSON object with these exact fields:
- "criterion": one of PS1/PS2/PS3/PS4/PM1/PM2/.../BP7 (null if none)
- "direction": "pathogenic" or "benign"
- "strength": "supporting", "moderate", "strong", or "very_strong"
- "evidence": a concise 1-2 sentence summary of the evidence
- "pmid": the PMID string
- "confidence": float 0-1 (how confident you are this evidence applies to the specific variant)

Return a JSON array. If no relevant evidence is found, return an empty array [].
Return ONLY the JSON array, no other text.

Focus on:
- PS3/BS3: Functional assay results (in vitro, animal models, cell lines)
- PM1: Critical domain or mutational hotspot
- PM3/BP2: Trans/cis phase information
- PP3/BP4: Computational predictions cited in the paper
- PP5/BP6: ClinVar or expert panel citations
- PS4/PM4: Prevalence in affected vs control populations"""


class EvidenceAnnotation:
    """Structured ACMG evidence extracted from a single paper."""

    def __init__(
        self,
        criterion: Optional[str],
        direction: str,
        strength: str,
        evidence: str,
        pmid: str,
        confidence: float,
    ):
        self.criterion = criterion
        self.direction = direction
        self.strength = strength
        self.evidence = evidence
        self.pmid = pmid
        self.confidence = confidence

    def to_dict(self) -> dict:
        return {
            "criterion": self.criterion,
            "direction": self.direction,
            "strength": self.strength,
            "evidence": self.evidence,
            "pmid": self.pmid,
            "confidence": self.confidence,
        }


async def summarize_pubmed_evidence(
    variant_hgvs: str,
    gene: str,
    abstracts: List[dict],
    max_abstracts: int = 5,
) -> List[EvidenceAnnotation]:
    """
    Extract structured ACMG evidence from PubMed abstracts using LLM.

    Args:
        variant_hgvs: Variant in HGVS notation
        gene: Gene symbol (e.g. BRCA1)
        abstracts: List of dicts with keys: pmid, title, abstract
        max_abstracts: Max abstracts to process (cost control)

    Returns:
        List of EvidenceAnnotation objects, sorted by confidence descending.
    """
    from varos.config import settings

    if not settings.has_llm:
        logger.debug("No LLM configured — skipping evidence summarization")
        return []

    abstracts_to_process = abstracts[:max_abstracts]
    if not abstracts_to_process:
        return []

    all_annotations: List[EvidenceAnnotation] = []

    for paper in abstracts_to_process:
        try:
            annotations = await _extract_from_abstract(
                variant_hgvs=variant_hgvs,
                gene=gene,
                pmid=paper.get("pmid", ""),
                title=paper.get("title", ""),
                abstract=paper.get("abstract", ""),
                settings=settings,
            )
            all_annotations.extend(annotations)
        except Exception as exc:
            logger.warning("Failed to extract evidence from PMID %s: %s", paper.get("pmid"), exc)

    # Sort by confidence descending
    all_annotations.sort(key=lambda x: x.confidence, reverse=True)
    return all_annotations


async def _extract_from_abstract(
    variant_hgvs: str,
    gene: str,
    pmid: str,
    title: str,
    abstract: str,
    settings,
) -> List[EvidenceAnnotation]:
    """Call LLM to extract structured evidence from a single abstract."""
    prompt = _EXTRACTION_PROMPT.format(
        variant_hgvs=variant_hgvs,
        gene=gene,
        title=title,
        pmid=pmid,
        abstract=abstract[:3000],  # truncate very long abstracts
    )

    raw_json = await _call_llm(prompt, settings)
    if not raw_json:
        return []

    return _parse_llm_response(raw_json, pmid)


async def _call_llm(prompt: str, settings) -> Optional[str]:
    """Call the configured LLM and return raw text response."""
    if settings.anthropic_api_key:
        return await _call_anthropic(prompt, settings)
    if settings.openai_api_key:
        return await _call_openai(prompt, settings)
    return None


async def _call_anthropic(prompt: str, settings) -> Optional[str]:
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model=settings.varos_llm_model or "claude-3-5-haiku-20241022",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text if message.content else None
    except Exception as exc:
        logger.warning("Anthropic call failed: %s", exc)
        return None


async def _call_openai(prompt: str, settings) -> Optional[str]:
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.warning("OpenAI call failed: %s", exc)
        return None


def _parse_llm_response(raw_json: str, pmid: str) -> List[EvidenceAnnotation]:
    """Parse and validate LLM JSON output into EvidenceAnnotation objects."""
    try:
        # Strip any markdown code fences the LLM might add
        text = raw_json.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        data = json.loads(text)
        if isinstance(data, dict) and "annotations" in data:
            data = data["annotations"]
        if not isinstance(data, list):
            return []

        annotations = []
        for item in data:
            if not isinstance(item, dict):
                continue
            criterion = item.get("criterion")
            if criterion and criterion not in _SUPPORTED_CRITERIA:
                continue
            direction = item.get("direction", "pathogenic").lower()
            if direction not in ("pathogenic", "benign"):
                direction = "pathogenic"
            strength = item.get("strength", "supporting").lower()
            if strength not in _STRENGTH_VALUES:
                strength = "supporting"
            evidence = str(item.get("evidence", ""))[:500]
            confidence = float(item.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            annotations.append(EvidenceAnnotation(
                criterion=criterion,
                direction=direction,
                strength=strength,
                evidence=evidence,
                pmid=str(item.get("pmid", pmid)),
                confidence=confidence,
            ))
        return annotations

    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("Failed to parse LLM evidence response: %s", exc)
        return []


async def generate_plain_english_summary(
    variant_hgvs: str,
    gene: str,
    classification: str,
    criteria_triggered: list,
) -> Optional[str]:
    """
    Generate a plain-English explanation of why a variant was classified.

    Used for the 'Why pathogenic?' feature — accessible to non-specialists.
    Available on Pro+ plans.
    """
    from varos.config import settings
    if not settings.has_llm:
        return None

    criteria_text = "\n".join(
        f"- {c.code} ({c.applied_strength.value}): {c.evidence_text[:200]}"
        for c in criteria_triggered
        if c.triggered
    ) if criteria_triggered else "No criteria triggered."

    prompt = f"""You are explaining a genetic variant classification to a patient or non-specialist clinician.

Variant: {variant_hgvs}
Gene: {gene}
Classification: {classification}

Evidence used:
{criteria_text}

Write a clear, jargon-free 2-3 sentence explanation of:
1. What this variant is
2. Why it was classified as {classification}
3. What this means clinically (in general terms — not medical advice)

Use plain language. Do not use ACMG codes. Do not give medical advice."""

    raw = await _call_llm(prompt, settings)
    return raw.strip() if raw else None
