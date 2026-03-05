# VAROS Architecture

## Overview

VAROS is a Python-based bioinformatics platform that classifies genetic variants according to
ACMG/AMP 2015 guidelines. It can run as a standalone CLI tool or as a hosted REST API.

---

## System Diagram

```
User Input (CLI / REST API)
         │
         ▼
  ┌──────────────────┐
  │  normalize_variant│  Parse HGVS / gene shorthand / protein notation
  └──────────┬───────┘
             │
             ▼  asyncio.gather (all 4 in parallel, ~8s total)
  ┌──────────┬──────────┬────────────────┬────────────────────┐
  │          │          │                │                    │
  ▼          ▼          ▼                ▼                    ▼
gnomAD    ClinVar    PubMed      AlphaMissense           SpliceAI
(pop freq) (reviews) (literature) (AI pathogenicity)   (splice impact)
  │          │          │                │                    │
  └──────────┴──────────┴────────────────┴────────────────────┘
             │
             ▼
  ┌──────────────────────┐
  │   ACMG Criteria      │  Evaluate 8 criteria (PVS1, PM2, PP3, PP5,
  │   Engine             │  BA1, BS1, BS2, BP4)
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │   ACMG Combiner      │  Apply Table 5 combination rules →
  │                      │  Pathogenic / LP / VUS / LB / Benign
  └──────────┬───────────┘
             │
             ▼
  ┌──────────────────────┐
  │   LLM Reasoning      │  Claude generates clinical note,
  │   (optional)         │  evidence summary, patient explanation
  └──────────┬───────────┘
             │
             ▼
  ClassificationResult → JSON response / PDF report / CLI output
```

---

## Component Responsibilities

### `varos/connectors/`

| Connector | Data source | What it provides |
|-----------|-------------|-----------------|
| `gnomad.py` | gnomAD v4.1 GraphQL API | Population allele frequency, homozygote count |
| `clinvar.py` | NCBI Entrez (ClinVar) | Aggregate classification, review stars, submission history |
| `pubmed.py` | NCBI Entrez (PubMed) | Literature evidence, functional study count |
| `alphamissense.py` | Local SQLite index (71M variants) | AI missense pathogenicity score + class |
| `spliceai.py` | SpliceAI Lookup REST API | Splice-altering delta scores |

All connectors implement graceful degradation: if they fail, a warning is logged and
classification continues with the remaining evidence.

### `varos/classifiers/`

| Module | Purpose |
|--------|---------|
| `acmg.py` | Evaluates individual ACMG criteria (8 implemented) |
| `combiner.py` | Applies ACMG 2015 Table 5 combination rules |
| `vcep/` | Reserved for gene-specific VCEP rules (Phase 3) |

**Implemented ACMG criteria:**

| Code | Direction | Strength | Evidence used |
|------|-----------|----------|---------------|
| PVS1 | Pathogenic | Very Strong | Loss-of-function variant in LoF-sensitive gene (pLI/LOEUF) |
| PM2 | Pathogenic | Moderate | Absent from gnomAD (or extremely rare AF < 0.0001) |
| PP3 | Pathogenic | Supporting | AlphaMissense ≥ 0.7 OR SpliceAI delta ≥ 0.5 |
| PP5 | Pathogenic | Supporting | ClinVar Pathogenic/Likely Pathogenic with ≥1 star |
| BA1 | Benign | Stand-alone | gnomAD AF ≥ 5% |
| BS1 | Benign | Strong | gnomAD AF > gene-specific expected frequency |
| BS2 | Benign | Strong | Observed in healthy homozygotes in gnomAD |
| BP4 | Benign | Supporting | AlphaMissense < 0.34 OR SpliceAI delta < 0.1 |

### `varos/agents/orchestrator.py`

Runs the full pipeline. Uses `asyncio.gather` for parallel connector calls.
Each connector is independently wrapped in a try/except — failures produce warnings
but do not abort the classification.

Entry point: `run_classification(VariantInput) → ClassificationResult`

### `varos/api/`

| File | Purpose |
|------|---------|
| `app.py` | FastAPI application, CORS, lifespan, OpenAPI metadata |
| `auth.py` | `require_api_key` + `require_quota` FastAPI dependencies |
| `database.py` | SQLAlchemy engine, session factory, `init_db()` |
| `models.py` | `User`, `ApiKey`, `UsageRecord` ORM models |
| `schemas.py` | Pydantic v2 request/response schemas |
| `routes/classify.py` | `POST /v1/classify`, `POST /v1/classify/report` |
| `routes/users.py` | `POST /v1/register`, `GET /v1/me`, `GET /v1/usage` |
| `routes/billing.py` | Stripe Checkout session + webhook handler |

### `varos/cli/`

Typer-based CLI with these commands:

```
varos classify  <variant>         # Classify a single variant
varos analyze   --vcf <file>      # Batch VCF analysis
varos watch     add/list/remove   # Manage monitored variants
varos watch     start             # Start monitoring daemon
varos serve                       # Start API server (uvicorn)
varos setup     --alphamissense   # Download required databases
varos version                     # Show version
```

---

## Database Schema

SQLite (default) or PostgreSQL (production). Tables:

```sql
-- Users and API keys
CREATE TABLE users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT UNIQUE NOT NULL,
    name        TEXT,
    organization TEXT,
    tier        TEXT DEFAULT 'free',   -- free | starter | pro | enterprise
    is_active   BOOLEAN DEFAULT TRUE,
    stripe_customer_id TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE api_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key         TEXT UNIQUE NOT NULL,  -- vrs_ prefix + secrets.token_urlsafe(32)
    user_id     INTEGER REFERENCES users(id),
    last_used_at DATETIME,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Usage tracking (one row per classify call)
CREATE TABLE usage_records (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER REFERENCES users(id),
    variant        TEXT,
    classification TEXT,
    confidence     INTEGER,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

Monthly quota is computed on-the-fly by counting `usage_records` where
`created_at` is in the current calendar month — no cron job needed.

---

## Authentication Flow

```
Client sends request with X-VAROS-KEY: vrs_xxx
         │
         ▼
require_api_key dependency
  → Lookup ApiKey row by key value
  → Load User via relationship
  → Update ApiKey.last_used_at
  → Return User
         │
         ▼ (for mutation endpoints)
require_quota dependency
  → Compute credits_used_this_month
  → If credits_used >= credits_limit → 429 Too Many Requests
  → Otherwise pass User through
```

---

## Tier Limits

```python
TIER_LIMITS = {
    "free":       10,
    "starter":    200,
    "pro":        2_000,
    "enterprise": 999_999,
}
```

---

## Deployment Options

| Option | Command | Best for |
|--------|---------|----------|
| Local dev | `varos serve --reload` | Development |
| Docker | `docker compose -f docker/docker-compose.yml up` | Self-hosted |
| Fly.io | `fly deploy` | Production cloud |
| Any PaaS | Set `DATABASE_URL` + env vars | Heroku, Railway, Render |
