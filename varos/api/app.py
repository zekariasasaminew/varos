"""VAROS FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from varos import __version__
from varos.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB on startup."""
    from varos.api.database import init_db
    init_db()
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

# CORS — allow all for MVP (restrict to specific domains in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

app.include_router(classify_router)
app.include_router(users_router)
app.include_router(billing_router)
app.include_router(orgs_router)
app.include_router(watch_router)
app.include_router(batch_router)
app.include_router(clinvar_export_router)
app.include_router(trials_router)

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
        "llm_available": settings.has_llm,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/", include_in_schema=False)
async def root():
    """Serve landing page or redirect to docs."""
    landing = _static_dir / "index.html"
    if landing.exists():
        return FileResponse(str(landing))
    return JSONResponse({"message": "VAROS API", "version": __version__, "docs": "/docs"})

