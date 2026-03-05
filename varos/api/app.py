"""VAROS FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from varos import __version__
from varos.config import settings

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.varos_log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def _warn_startup() -> None:
    """Log warnings about missing/insecure config at startup."""
    if settings.is_production:
        if settings.secret_key == "change-me-in-production":
            logger.warning(
                "SECRET_KEY is set to the default value — set a strong random value via env var!"
            )
        if not settings.has_llm:
            logger.warning(
                "No LLM API key set (ANTHROPIC_API_KEY / OPENAI_API_KEY) — "
                "AI reasoning and summaries will be unavailable."
            )
        if not settings.stripe_secret_key:
            logger.warning(
                "STRIPE_SECRET_KEY not set — billing endpoints will be non-functional."
            )
        if settings.allowed_origins == ["*"]:
            logger.warning(
                "CORS_ORIGINS is '*' in production — set to your frontend domain for security."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    _configure_logging()
    _warn_startup()
    logger.info("VAROS %s starting (env=%s)", __version__, settings.varos_env)
    from varos.api.database import init_db
    init_db()
    logger.info("Database ready.")
    yield


_DESCRIPTION = """
## VAROS — Variant Autonomous Reclassification & Observation System

Classify genetic variants against **ACMG/AMP 2015 guidelines** using parallel AI-powered
evidence synthesis from ClinVar, gnomAD, PubMed, AlphaMissense, and SpliceAI.

### Key capabilities

- 🧬 **ACMG/AMP 2015 classification** — PVS1, PM2, PP3, PP5, BA1, BS1, BS2, BP4 + combination rules
- 📊 **Parallel evidence gathering** — gnomAD v4.1, ClinVar, PubMed, AlphaMissense, SpliceAI
- 🤖 **LLM reasoning** — Claude generates clinical, evidence, and patient-friendly summaries
- 📄 **PDF reports** — clinical-grade variant interpretation reports
- 🔔 **Continuous monitoring** — watch variants for reclassification changes

### Authentication

All endpoints except `/health` and `/v1/register` require an API key.

Pass it as a header:
```
X-VAROS-KEY: vrs_your_key_here
```
Or as a Bearer token:
```
Authorization: Bearer vrs_your_key_here
```

[Get a free API key →](https://varos.io)

### Pricing tiers

| Tier | Price | Variants/month |
|------|-------|---------------|
| Free | $0 | 10 |
| Starter | $49/mo | 200 |
| Pro | $199/mo | 2,000 |
| Enterprise | Custom | Unlimited |
"""

_TAGS_METADATA = [
    {
        "name": "classification",
        "description": "Classify genetic variants using ACMG/AMP 2015 guidelines.",
    },
    {
        "name": "users",
        "description": "Register, manage your account, and check usage.",
    },
    {
        "name": "billing",
        "description": "Upgrade plans via Stripe Checkout.",
    },
    {
        "name": "meta",
        "description": "Health checks and API metadata.",
    },
]

app = FastAPI(
    title="VAROS API",
    description=_DESCRIPTION,
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=_TAGS_METADATA,
    contact={
        "name": "VAROS Support",
        "url": "https://varos.io",
        "email": "support@varos.io",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
)

# CORS — configure via CORS_ORIGINS env var (default: * for MVP, restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
from varos.api.routes.classify import router as classify_router
from varos.api.routes.users import router as users_router
from varos.api.routes.billing import router as billing_router
from varos.api.routes.orgs import router as orgs_router
from varos.api.routes.watch import router as watch_router
from varos.api.routes.batch import router as batch_router
from varos.api.routes.clinvar_export import router as clinvar_export_router
from varos.api.routes.trials import router as trials_router
from varos.api.routes.network import router as network_router
from varos.api.routes.approvals import router as approvals_router
from varos.api.routes.audit_logs import router as audit_router

app.include_router(classify_router)
app.include_router(users_router)
app.include_router(billing_router)
app.include_router(orgs_router)
app.include_router(watch_router)
app.include_router(batch_router)
app.include_router(clinvar_export_router)
app.include_router(trials_router)
app.include_router(network_router)
app.include_router(approvals_router)
app.include_router(audit_router)

# Serve landing page static files
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    tags=["meta"],
    summary="Health check",
    description="Returns API status, version, and whether LLM reasoning is available.",
    response_description="API health status",
)
async def health():
    return {
        "status": "ok",
        "version": __version__,
        "env": settings.varos_env,
        "llm_available": settings.has_llm,
        "billing_available": bool(settings.stripe_secret_key),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/", include_in_schema=False)
async def root():
    """Serve landing page or redirect to docs."""
    landing = _static_dir / "index.html"
    if landing.exists():
        return FileResponse(str(landing))
    return JSONResponse({"message": "VAROS API", "version": __version__, "docs": "/docs"})

