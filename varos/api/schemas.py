"""Pydantic schemas for API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class ClassifyRequest(BaseModel):
    variant: str = Field(
        ...,
        description=(
            "Variant in HGVS notation (`NM_007294.4:c.5266dup`), "
            "gene-level shorthand (`BRCA1:c.5266dup`), "
            "protein notation (`BRCA1:p.Gln1756fs`), or rsID (`rs80357906`)."
        ),
    )
    genome_build: str = Field(
        "GRCh38",
        description="Reference genome build. `GRCh38` (default) or `GRCh37`.",
    )
    include_llm: bool = Field(
        True,
        description="Include LLM-generated narrative summaries (clinical, evidence, patient).",
    )
    audience: str = Field(
        "clinician",
        description="Narrative audience: `clinician` | `patient` | `researcher`.",
    )

    model_config = {"json_schema_extra": {"examples": [
        {
            "summary": "BRCA1 frameshift",
            "value": {
                "variant": "BRCA1:c.5266dup",
                "genome_build": "GRCh38",
                "include_llm": False,
            },
        },
        {
            "summary": "TP53 missense with LLM",
            "value": {
                "variant": "TP53:c.817C>T",
                "genome_build": "GRCh38",
                "include_llm": True,
                "audience": "clinician",
            },
        },
    ]}}


class RegisterRequest(BaseModel):
    email: EmailStr = Field(..., description="Your email address. Used for account recovery and alerts.")
    name: str = Field("", description="Optional display name (e.g. `Dr. Jane Smith`).")
    organization: str = Field("", description="Optional lab or company name.")

    model_config = {"json_schema_extra": {"example": {
        "email": "researcher@lab.edu",
        "name": "Dr. Jane Smith",
        "organization": "Broad Institute",
    }}}


class CheckoutRequest(BaseModel):
    tier: str = Field(..., description="Plan to upgrade to: `starter` ($49/mo) or `pro` ($199/mo).")
    success_url: str = Field("https://varos.io/success", description="Redirect URL after successful payment.")
    cancel_url: str = Field("https://varos.io/pricing", description="Redirect URL if user cancels checkout.")

    model_config = {"json_schema_extra": {"example": {
        "tier": "starter",
        "success_url": "https://myapp.com/settings?upgraded=true",
        "cancel_url": "https://myapp.com/settings",
    }}}


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class CriterionResponse(BaseModel):
    code: str = Field(..., description="ACMG criterion code (e.g. `PVS1`, `PM2`, `BA1`).")
    direction: str = Field(..., description="`pathogenic` or `benign`.")
    strength: str = Field(..., description="Criterion strength: `VeryStrong`, `Strong`, `Moderate`, `Supporting`, `Standalone`.")
    triggered: bool = Field(..., description="Whether this criterion was triggered by the evidence.")
    evidence: str = Field(..., description="Human-readable explanation of the evidence behind this criterion.")


class ClassifyResponse(BaseModel):
    variant: str = Field(..., description="Normalized variant identifier as submitted.")
    gene: str = Field(..., description="Gene symbol (e.g. `BRCA1`).")
    classification: str = Field(
        ...,
        description="ACMG/AMP 2015 classification: `Pathogenic`, `Likely Pathogenic`, `VUS`, `Likely Benign`, or `Benign`.",
    )
    confidence: int = Field(..., ge=0, le=100, description="Confidence score 0-100. Higher = more evidence supporting the classification.")
    criteria_triggered: list[CriterionResponse] = Field(..., description="ACMG criteria that were triggered and contributed to the classification.")
    population_frequency: Optional[float] = Field(None, description="Allele frequency from gnomAD v4.1 (if available).")
    clinvar_classification: Optional[str] = Field(None, description="ClinVar aggregate classification (if variant is in ClinVar).")
    clinvar_stars: Optional[int] = Field(None, description="ClinVar review status stars (0-4).")
    alphamissense_score: Optional[float] = Field(None, description="AlphaMissense pathogenicity score 0-1 (if available for missense variants).")
    llm_summary: Optional[str] = Field(None, description="LLM-generated evidence summary paragraph.")
    llm_clinical_note: Optional[str] = Field(None, description="LLM-generated clinical summary for genetic counselors.")
    llm_patient_note: Optional[str] = Field(None, description="LLM-generated plain-language explanation for patients.")
    warnings: list[str] = Field(default=[], description="Non-fatal warnings from evidence gathering (e.g. connector timeouts).")
    varos_version: str = Field("0.1.0", description="VAROS engine version used for this classification.")


class UserResponse(BaseModel):
    email: str = Field(..., description="Account email address.")
    name: str = Field(..., description="Display name.")
    organization: str = Field(..., description="Lab or company name.")
    tier: str = Field(..., description="Current plan tier: `free`, `starter`, `pro`, or `enterprise`.")
    api_key: str = Field(..., description="Your API key (prefix `vrs_`). Store securely — shown only once on registration.")
    credits_used: int = Field(..., description="Variants classified this calendar month.")
    credits_limit: int = Field(..., description="Maximum variants allowed per month on current tier.")
    credits_remaining: int = Field(..., description="Remaining variants for this month.")
    member_since: datetime = Field(..., description="Account creation timestamp (UTC).")


class UsageResponse(BaseModel):
    tier: str = Field(..., description="Current plan tier.")
    credits_used: int = Field(..., description="Variants classified this month.")
    credits_limit: int = Field(..., description="Monthly quota for current tier.")
    credits_remaining: int = Field(..., description="Remaining variants this month.")
    reset_date: str = Field(..., description="Human-readable date when quota resets (e.g. `April 1, 2026`).")
    recent_variants: list[str] = Field(default=[], description="Last 10 variant identifiers classified.")


class CheckoutResponse(BaseModel):
    checkout_url: str = Field(..., description="Stripe Checkout hosted page URL. Redirect the user here.")
    session_id: str = Field(..., description="Stripe Checkout session ID.")


class HealthResponse(BaseModel):
    status: str = Field("ok", description="Always `ok` if the API is running.")
    version: str = Field(..., description="VAROS API version.")
    llm_available: bool = Field(..., description="Whether LLM reasoning (Claude/GPT-4) is configured and available.")
    timestamp: datetime = Field(..., description="Current server time (UTC).")

