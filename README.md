# VAROS

**Variant Autonomous Reclassification & Observation System**

Classify genetic variants using ACMG/AMP 2015 guidelines + AI-powered evidence synthesis.
Built for clinical genomics labs, biotech startups, and genetic counselors.

---

## Features

- **ACMG/AMP 2015 engine** — PVS1, PM2, PP3, PP5, BA1, BS1, BS2, BP4 + combination rules
- **Parallel evidence gathering** — ClinVar, gnomAD v4.1, PubMed, AlphaMissense, SpliceAI
- **LLM reasoning** — Clinical summary, evidence narrative, patient-friendly explanation
- **PDF/HTML reports** — One-click clinical-grade variant reports
- **REST API** — Authenticated JSON API with per-tier quotas and Stripe billing
- **Continuous monitoring** — Watch variants for reclassification, get email alerts
- **CLI** — `varos classify`, `varos analyze`, `varos watch`, `varos serve`

---

## Quick Start (CLI)

```bash
pip install varos
cp .env.example .env   # add your ANTHROPIC_API_KEY and NCBI_EMAIL
varos classify "BRCA1:c.5266dup"
```

Sample output:
```
🧬 VAROS — BRCA1:c.5266dup
Classification : Likely Pathogenic  (confidence: 67/100)
Criteria       : PVS1 (PathogenicVeryStrong), PM2 (PathogenicModerate)
```

Batch VCF analysis:
```bash
varos analyze --vcf variants.vcf --output ./reports --format pdf
```

Continuous monitoring:
```bash
varos watch add "BRCA2:c.5946delT" --email you@lab.edu
varos watch start   # runs scheduler, checks ClinVar weekly
```

---

## REST API

### Run locally

```bash
# Install
pip install -e ".[dev]"
cp .env.example .env

# Start API
varos serve --port 8000 --reload
# or: uvicorn varos.api.app:app --reload
```

API docs available at `http://localhost:8000/docs`

### Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/register` | Get a free API key (no credit card) |
| `POST` | `/v1/classify` | Classify a variant (JSON) |
| `POST` | `/v1/classify/report` | Download PDF report |
| `GET`  | `/v1/me` | Account info + tier |
| `GET`  | `/v1/usage` | Monthly usage & quota |
| `POST` | `/v1/billing/checkout` | Upgrade plan (Stripe) |
| `GET`  | `/health` | Health check |

### Example

```bash
# Register (free, instant)
curl -X POST https://api.varos.io/v1/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@lab.edu", "name": "Dr. Smith"}'
# → {"api_key": "vrs_...", "tier": "free", "credits_limit": 10}

# Classify
curl -X POST https://api.varos.io/v1/classify \
  -H "X-VAROS-KEY: vrs_your_key_here" \
  -H "Content-Type: application/json" \
  -d '{"variant": "BRCA1:c.5266dup", "genome_build": "GRCh38"}'
```

---

## Deployment

### Docker (recommended)

```bash
cp .env.example .env   # fill in your secrets
docker compose -f docker/docker-compose.yml up -d
# API available at http://localhost:8000
```

### Fly.io (production)

```bash
fly launch --name varos-api --region ord
fly secrets set \
  ANTHROPIC_API_KEY=sk-ant-... \
  STRIPE_SECRET_KEY=sk_live_... \
  STRIPE_WEBHOOK_SECRET=whsec_... \
  STRIPE_STARTER_PRICE_ID=price_... \
  STRIPE_PRO_PRICE_ID=price_... \
  SENDGRID_API_KEY=SG... \
  NCBI_EMAIL=you@lab.edu
fly deploy
```

Stripe webhook: set endpoint to `https://your-app.fly.dev/v1/billing/webhook`

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key (LLM reasoning) |
| `NCBI_EMAIL` | Yes | NCBI Entrez email (rate limits) |
| `NCBI_API_KEY` | Recommended | NCBI API key (10 req/s vs 3/s) |
| `STRIPE_SECRET_KEY` | For billing | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | For billing | Stripe webhook signing secret |
| `STRIPE_STARTER_PRICE_ID` | For billing | $49/mo plan price ID |
| `STRIPE_PRO_PRICE_ID` | For billing | $199/mo plan price ID |
| `SENDGRID_API_KEY` | For emails | SendGrid API key |
| `SENDGRID_FROM_EMAIL` | For emails | Verified sender email |
| `DATABASE_URL` | Optional | SQLite (default) or PostgreSQL |

---

## Pricing Tiers

| Tier | Price | Variants/month |
|------|-------|---------------|
| Free | $0 | 10 |
| Starter | $49/mo | 200 |
| Pro | $199/mo | 2,000 |
| Enterprise | Custom | Unlimited |

---

## Development

```bash
# Install with dev deps
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run with auto-reload
varos serve --reload
```

Tests: 42 passing (unit + integration)

---

## Architecture

```
varos classify "BRCA1:c.5266dup"
        │
        ▼
  normalize_variant
        │
        ▼ asyncio.gather (parallel)
  ┌─────┬─────┬──────┬─────────────┐
gnomAD ClinVar PubMed AlphaMissense+SpliceAI
  └─────┴─────┴──────┴─────────────┘
        │
        ▼
  acmg_classify (8 criteria → combination rules)
        │
        ▼
  llm_reason (Claude — clinical/evidence/patient notes)
        │
        ▼
  ClassificationResult → JSON / PDF report
```

---

## License

MIT — see [LICENSE](LICENSE)

