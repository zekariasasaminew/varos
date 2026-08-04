# VAROS

**Variant Autonomous Reclassification & Observation System**

Classify genetic variants using ACMG/AMP 2015 guidelines and AMP/ASCO/CAP 2017 (somatic) + AI-powered evidence synthesis.  
Built for clinical genomics labs, pharma drug discovery teams, and bioinformatics startups.

[![Tests](https://img.shields.io/badge/tests-103%20passing-brightgreen)](#development)
[![API](https://img.shields.io/badge/API-FastAPI-009688)](#rest-api)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

> ⚠️ **Research Use Only. Not for diagnostic use.** VAROS is a pre-clinical research tool. Its classifications
> have not been clinically validated and must not be used to make patient care decisions without independent
> review and confirmation by a qualified clinical geneticist.

---

## What VAROS Does

VAROS automatically classifies genetic variants by aggregating evidence from a dozen public databases, applying the latest ACMG/AMP and gene-specific VCEP rules, and producing structured classifications with full evidence audit trails.

**Who uses VAROS:**
- 🔬 **Academic genomics labs** — Classify VUS cohorts for papers and grants
- 💊 **Pharma drug discovery teams** — Batch classify variants in target genes, match to clinical trials
- 🧬 **Genomics SaaS companies** — Use VAROS as a classification microservice via API
- 🏥 **Rare disease platforms** — Automate ACMG classification in patient pipelines

---

## Features

### Core Classification
- **ACMG/AMP 2015 engine** — PVS1, PM2, PP3, PP5, BA1, BS1, BS2, BP4 + all combination rules
- **AMP/ASCO/CAP 2017 somatic** — Tier I–IV classification for oncology
- **Gene-specific VCEP rules** — BRCA1/2 VCEP v1.1.0, Lynch/MMR VCEP v3.0.0 (more genes planned)
- **Parallel evidence gathering** — ClinVar, gnomAD v4.1, PubMed, AlphaMissense, SpliceAI, CADD v1.7, REVEL, OMIM, UniProt

### Intelligence Layer
- **LLM evidence summarizer** — Reads PubMed abstracts, extracts structured ACMG evidence with confidence scores
- **OncoKB connector** — FDA-approved therapy evidence for somatic variants (Tier I/II)
- **CIViC connector** — Open clinical evidence for cancer variants
- **Clinical trial matching** — ClinicalTrials.gov integration: find open trials for any gene/variant

### Workflow Features
- **VCF batch processing** — Upload a .vcf.gz file, get job_id, poll for results; $0.005/variant
- **Cost estimator** — Pre-flight cost estimate before batch submission
- **VUS reclassification watchlist** — Subscribe to variants, get weekly ClinVar diff alerts via email + webhook
- **ClinVar XML/CSV export** — One-click ClinVar Submission API v2 XML or bulk upload CSV (saves 30–60 min/variant)
- **PDF/HTML reports** — Clinical-grade variant interpretation reports
- **Organization management** — Multi-seat orgs with OWNER/ANALYST/VIEWER roles
- **VAROS Network** — Opt-in federated variant intelligence: contribute de-identified classifications, query cross-org consensus
- **Approval workflow** — DRAFT → PENDING_REVIEW → APPROVED/REJECTED state machine with four-eyes review
- **Audit logs** — Immutable append-only event log with CSV export for compliance reporting

### API & Integrations
- **REST API** — Authenticated JSON API, Swagger UI at `/docs`
- **Stripe billing** — Self-serve upgrades, per-tier quotas, batch overages
- **SendGrid alerts** — Email notifications for quota warnings and reclassifications
- **Webhooks** — POST notifications for batch job completion and variant reclassification

---

## Quick Start (CLI)

```bash
pip install varos
cp .env.example .env   # add ANTHROPIC_API_KEY and NCBI_EMAIL
varos classify "BRCA1:c.5266dup"
```

Output:
```
🧬 VAROS — BRCA1:c.5266dup
Classification : Likely Pathogenic  (confidence: 67/100)
Criteria       : PVS1 (PathogenicVeryStrong), PM2 (PathogenicModerate)
VCEP           : BRCA1/2 VCEP v1.1.0 (ClinGen, 2023)
```

Batch VCF analysis:
```bash
varos analyze --vcf cohort.vcf.gz --output ./reports --format pdf
```

VUS watchlist:
```bash
varos watch add "BRCA2:c.5946delT" --email you@lab.edu
varos watch start   # checks ClinVar weekly, emails on reclassification
```

---

## REST API

### Run locally

```bash
pip install -e ".[dev]"
cp .env.example .env
varos serve --port 8000 --reload
# Swagger UI → http://localhost:8000/docs
```

### All endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/register` | Create account + get free API key |
| `POST` | `/v1/classify` | Classify a single germline variant |
| `POST` | `/v1/classify/somatic` | Classify a somatic variant (AMP/ASCO/CAP 2017) |
| `POST` | `/v1/classify/report` | Classify + return PDF report |
| `POST` | `/v1/classify/batch` | Upload VCF file for async batch classification |
| `GET`  | `/v1/classify/batch/{job_id}` | Poll batch job status + download results |
| `POST` | `/v1/classify/batch/estimate` | Pre-flight cost estimate for a VCF |
| `GET`  | `/v1/classify/history/{id}/clinvar-xml` | Export as ClinVar Submission XML |
| `GET`  | `/v1/classify/history/clinvar-csv` | Bulk ClinVar upload CSV |
| `GET`  | `/v1/trials/{variant_hgvs}` | Find open clinical trials for a gene/variant |
| `POST` | `/v1/watch` | Subscribe to VUS reclassification alerts |
| `GET`  | `/v1/watch` | List all watched variants |
| `GET`  | `/v1/watch/dashboard` | Reclassification probability dashboard |
| `DELETE` | `/v1/watch/{id}` | Unsubscribe from a watch |
| `POST` | `/v1/organizations` | Create organization |
| `POST` | `/v1/organizations/{id}/invite` | Invite team member |
| `GET`  | `/v1/me` | Account info + tier |
| `GET`  | `/v1/usage` | Monthly usage & quota |
| `POST` | `/v1/billing/checkout` | Stripe checkout session |
| `GET`  | `/v1/network/consensus/{hash}` | Federated cross-org consensus for a variant |
| `POST` | `/v1/network/share` | Contribute a de-identified classification to the network |
| `POST` | `/v1/network/hash` | Compute SHA-256 privacy hash for an HGVS notation |
| `GET`  | `/v1/network/stats` | Global network statistics |
| `GET`  | `/v1/network/my-shares` | List your org's network contributions |
| `GET`  | `/v1/approvals` | List classification approvals (filter by state) |
| `POST` | `/v1/approvals/{id}/submit` | Submit classification for curator review |
| `POST` | `/v1/approvals/{id}/approve` | Approve classification (four-eyes enforced) |
| `POST` | `/v1/approvals/{id}/reject` | Reject with comment (required) |
| `GET`  | `/v1/audit-logs` | List immutable audit log entries |
| `GET`  | `/v1/audit-logs/export` | Export audit trail as CSV |
| `GET`  | `/health` | Health check |

### Authentication

All endpoints except `/health` and `/v1/register` require an API key:

```bash
# As header
X-VAROS-KEY: vrs_your_key_here

# Or as Bearer token
Authorization: Bearer vrs_your_key_here
```

### Examples

```bash
# Register (free, instant)
curl -X POST https://api.varos.io/v1/register \
  -d '{"email": "you@lab.edu", "name": "Dr. Smith"}'
# → {"api_key": "vrs_...", "tier": "free"}

# Classify germline variant
curl -X POST https://api.varos.io/v1/classify \
  -H "X-VAROS-KEY: vrs_..." \
  -d '{"variant": "BRCA1:c.5266dup", "genome_build": "GRCh38"}'

# Classify somatic variant
curl -X POST https://api.varos.io/v1/classify/somatic \
  -H "X-VAROS-KEY: vrs_..." \
  -d '{"variant": "chr7:g.55174772C>T", "gene": "EGFR", "tumor_type": "NSCLC"}'

# Upload VCF for batch classification
curl -X POST https://api.varos.io/v1/classify/batch \
  -H "X-VAROS-KEY: vrs_..." \
  -F "file=@cohort.vcf.gz" \
  -F "mode=germline" \
  -F "webhook_url=https://your-app.com/webhooks/varos"

# Find clinical trials for a gene
curl "https://api.varos.io/v1/trials/NM_007294.4:c.5266dupC?gene=BRCA1&tumor_type=breast+cancer" \
  -H "X-VAROS-KEY: vrs_..."

# Export ClinVar submission XML
curl "https://api.varos.io/v1/classify/history/42/clinvar-xml?submitter_org=MyLab" \
  -H "X-VAROS-KEY: vrs_..." > submission.xml
```

---

## Evidence Sources

| Source | Data | Used For |
|--------|------|----------|
| gnomAD v4.1 | Population allele frequencies | PM2, BA1, BS1 |
| ClinVar | Aggregate classifications | PP5, BP6 |
| PubMed / Entrez | Literature abstracts | PS3, PM3, PP1 |
| AlphaMissense | Missense pathogenicity (0–1) | PP3, BP4 |
| SpliceAI | Splice variant delta scores | PP3 splice |
| CADD v1.7 | Ensemble pathogenicity PHRED | PP3, BP4 |
| REVEL | Missense pathogenicity | PP3, BP4 |
| OMIM | Gene–disease associations | PP2, PM1 |
| UniProt | Protein domain annotations | PM1 |
| OncoKB | FDA-approved therapy levels | Somatic Tier I/II |
| CIViC | Clinical evidence items | Somatic Tier I/II |
| ClinicalTrials.gov | Open clinical trials | Trial matching |

---

## VCEP Gene-Specific Rules

VAROS auto-detects the gene from your HGVS notation and applies the correct VCEP ruleset:

| Gene(s) | Ruleset | Version | Key Modifications |
|---------|---------|---------|-------------------|
| BRCA1, BRCA2 | ClinGen BRCA1/2 VCEP | v1.1.0 | PM2 threshold 1e-5, PP2 disabled, BP1 disabled |
| MLH1, MSH2, MSH6, PMS2, EPCAM | ClinGen Lynch/MMR VCEP | v3.0.0 | PM2 threshold 1e-4, REVEL PP3/BP4 thresholds |
| All others | Generic ACMG/AMP 2015 | — | Standard criteria |

Classification report includes: _"Classified using BRCA1/2 VCEP v1.1.0 (ClinGen, 2023)"_

---

## VAROS Network — Federated Variant Intelligence

The VAROS Network is the **competitive moat**: each organization that contributes de-identified classifications makes VAROS more valuable for everyone else.

### How it works

1. **Contribute** — After classifying a variant, opt in to share it to the network.  
   Your variant is stored as a SHA-256 hash — raw HGVS notation is never exposed across organizations.

2. **Query consensus** — Ask "what do other labs say about this variant?"  
   Returns the majority classification, contributor count, and agreement level.

3. **Network bonus** — Organizations that share data receive a 20% monthly quota discount.

### Agreement levels

| Level | Meaning |
|-------|---------|
| `strong` | ≥90% of contributing orgs agree |
| `moderate` | 75–89% agree |
| `weak` | <75% agree (genuine scientific uncertainty) |
| `single` | Only one organization has seen this variant |

### Example

```bash
# Contribute a classification to the network
curl -X POST https://api.varos.io/v1/network/share \
  -H "X-VAROS-KEY: vrs_..." \
  -d '{
    "variant_hgvs": "NM_007294.4:c.5266dupC",
    "gene": "BRCA1",
    "classification": "Pathogenic",
    "criteria_codes": ["PVS1", "PS2"],
    "confidence": 95,
    "genome_build": "GRCh38"
  }'

# Query cross-org consensus
curl "https://api.varos.io/v1/network/consensus/c9b4d649..." \
  -H "X-VAROS-KEY: vrs_..."
# → {"total_orgs": 7, "consensus": "Pathogenic", "agreement": "strong", "agreement_pct": 0.86}
```

---

## Compliance & Audit

### Audit Logs

VAROS maintains an **immutable append-only audit trail** for every significant action:

- `variant.classified` — every classification event
- `batch.job_submitted` — batch VCF uploads
- `classification.approved` / `classification.rejected` — approval workflow events
- `api_key.created` — key provisioning
- `network.share_contributed` — network contributions

```bash
# List recent events
curl "https://api.varos.io/v1/audit-logs?action=variant.classified&limit=50" \
  -H "X-VAROS-KEY: vrs_..."

# Export full audit trail as CSV
curl "https://api.varos.io/v1/audit-logs/export" \
  -H "X-VAROS-KEY: vrs_..." > audit_trail.csv
```

### Approval Workflow

Built-in **four-eyes review** state machine for labs that require dual authorization before finalizing a classification:

```
DRAFT → PENDING_REVIEW → APPROVED
                       → REJECTED → PENDING_REVIEW (re-submit after rework)
```

Rules enforced:
- The **approver cannot be the same person as the submitter** (four-eyes principle)
- **Rejection requires a comment** documenting the reason
- All state transitions are written to the immutable audit log

This powers the CLIA-module premium add-on for labs requiring workflow compliance.

---

## Pricing

| Tier | Price | Variants/month | Key Features |
|------|-------|----------------|--------------|
| Free | $0 | 50 | Single variants, basic ACMG |
| Researcher | $49/mo | 500 | Batch VCF, VCEP rules, VUS watch (5) |
| Pro | $199/mo | 5,000 | Somatic mode, LLM evidence, trial matching |
| Team | $299/mo | 10,000 | 5 seats, org shared history, ClinVar export |
| Lab | $999/mo | Unlimited | 20 seats, webhooks, network sharing, priority queue |
| Oncology | $499/mo | 2,000 somatic | Somatic-only (pharma research teams) |
| Batch API | $0.005/variant | Pay-per-use | Pipeline integration |

---

## Deployment

### Docker (recommended)

```bash
cp .env.example .env   # fill in secrets
docker compose -f docker/docker-compose.yml up -d
# API at http://localhost:8000
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
  NCBI_EMAIL=you@lab.edu \
  OMIM_API_KEY=... \
  ONCKB_API_TOKEN=...
fly deploy
```

Set Stripe webhook endpoint: `https://your-app.fly.dev/v1/billing/webhook`

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key (LLM reasoning + evidence extraction) |
| `NCBI_EMAIL` | Yes | Required by NCBI Entrez |
| `NCBI_API_KEY` | Recommended | 10 req/s vs 3 req/s |
| `OMIM_API_KEY` | Recommended | Gene–disease for PP2/PM1 (free at omim.org/api) |
| `ONCKB_API_TOKEN` | Recommended | Therapy evidence for somatic (free at oncokb.org) |
| `STRIPE_SECRET_KEY` | For billing | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | For billing | Stripe webhook signing secret |
| `STRIPE_STARTER_PRICE_ID` | For billing | Researcher plan price ID |
| `STRIPE_PRO_PRICE_ID` | For billing | Pro plan price ID |
| `SENDGRID_API_KEY` | For emails | Quota warnings + reclassification alerts |
| `SENDGRID_FROM_EMAIL` | For emails | Verified sender email |
| `DATABASE_URL` | Optional | SQLite (default) or PostgreSQL |
| `OPENAI_API_KEY` | Optional | GPT-4o fallback for LLM features |

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v         # 103 tests passing
varos serve --reload     # Hot-reload dev server
```

### Project structure

```
varos/
├── agents/
│   ├── orchestrator.py          # Main async classification pipeline
│   └── evidence_summarizer.py   # LLM ACMG evidence extraction from PubMed
├── api/
│   ├── app.py                   # FastAPI app + router registration
│   ├── audit.py                 # Append-only audit log helper
│   ├── models.py                # SQLAlchemy ORM (User, Org, Watch, BatchJob, NetworkShare, AuditLog, ClassificationApproval)
│   ├── routes/
│   │   ├── classify.py          # POST /v1/classify + /somatic
│   │   ├── batch.py             # VCF batch processing
│   │   ├── watch.py             # VUS reclassification watchlist
│   │   ├── orgs.py              # Organization + team management
│   │   ├── trials.py            # Clinical trial matching
│   │   ├── clinvar_export.py    # ClinVar XML/CSV export
│   │   ├── users.py             # Account management
│   │   └── billing.py           # Stripe checkout + webhook
├── classifiers/
│   ├── acmg.py                  # ACMG/AMP 2015 criteria engine
│   ├── somatic.py               # AMP/ASCO/CAP 2017 Tier I-IV engine
│   └── vcep/
│       ├── base.py              # VCEPRuleset ABC + registry
│       ├── brca.py              # BRCA1/2 VCEP v1.1.0
│       └── lynch.py             # Lynch/MMR VCEP v3.0.0
├── connectors/
│   ├── gnomad.py, clinvar.py, pubmed.py, alphamissense.py, spliceai.py
│   ├── cadd.py                  # CADD v1.7 PHRED scores
│   ├── revel.py                 # REVEL missense pathogenicity
│   ├── omim.py                  # Gene–disease associations
│   ├── uniprot.py               # Protein domain annotations
│   ├── onckb.py                 # OncoKB therapy evidence
│   ├── civic.py                 # CIViC cancer variant evidence
│   └── clinicaltrials.py        # ClinicalTrials.gov trial matching
├── daemon/
│   ├── scheduler.py             # APScheduler daemon
│   └── reclassification_check.py  # Weekly ClinVar diff job
└── reports/
    ├── pdf.py                   # WeasyPrint PDF reports
    ├── json_report.py           # JSON report serializer
    └── clinvar_xml.py           # ClinVar submission XML/CSV
```

---

## Architecture

```
varos classify "BRCA1:c.5266dup"
        │
        ▼
  normalize_variant → detect VCEP ruleset (BRCA1 → BRCA1/2 VCEP v1.1.0)
        │
        ▼ asyncio.gather (parallel)
  ┌─────┬─────┬──────┬──────────────┬──────┬──────┐
gnomAD ClinVar PubMed AlphaMissense SpliceAI CADD REVEL
  └─────┴─────┴──────┴──────────────┴──────┴──────┘
        │
        ▼
  llm_evidence_summarizer (extracts structured ACMG evidence from abstracts)
        │
        ▼
  acmg_classify (criteria engine + VCEP overrides → combination rules)
        │
        ▼
  llm_reason (Claude — clinical/evidence/patient notes)
        │
        ▼
  ClassificationResult → JSON / PDF / ClinVar XML
```

---

## License

MIT — see [LICENSE](LICENSE)
