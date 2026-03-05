# VAROS API Reference

Base URL: `https://api.varos.io` (or `http://localhost:8000` for local dev)

Interactive docs: `GET /docs` (Swagger UI) · `GET /redoc` (ReDoc)

---

## Authentication

All endpoints except `/health` and `POST /v1/register` require an API key.

**Header (recommended):**
```http
X-VAROS-KEY: vrs_your_key_here
```

**Bearer token (alternative):**
```http
Authorization: Bearer vrs_your_key_here
```

Get a free API key (10 variants/month, no credit card):
```bash
curl -X POST https://api.varos.io/v1/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@lab.edu", "name": "Dr. Smith"}'
```

---

## Endpoints

### `GET /health`

Returns API status. No authentication required.

**Response:**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "llm_available": true,
  "timestamp": "2026-03-05T00:00:00Z"
}
```

---

### `POST /v1/register`

Create a free account and receive an API key instantly.

**Request body:**
```json
{
  "email": "researcher@lab.edu",
  "name": "Dr. Jane Smith",
  "organization": "Broad Institute"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `email` | string | ✅ | Valid email address |
| `name` | string | ❌ | Display name |
| `organization` | string | ❌ | Lab or company |

**Response `201 Created`:**
```json
{
  "email": "researcher@lab.edu",
  "name": "Dr. Jane Smith",
  "organization": "Broad Institute",
  "tier": "free",
  "api_key": "vrs_abc123...",
  "credits_used": 0,
  "credits_limit": 10,
  "credits_remaining": 10,
  "member_since": "2026-03-05T00:00:00Z"
}
```

> ⚠️ Store your API key securely — it's shown only once.

---

### `POST /v1/classify` 🔐

Classify a genetic variant. Returns JSON with ACMG classification and evidence.

**Request body:**
```json
{
  "variant": "BRCA1:c.5266dup",
  "genome_build": "GRCh38",
  "include_llm": true,
  "audience": "clinician"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `variant` | string | required | HGVS, gene shorthand (`BRCA1:c.5266dup`), protein (`BRCA1:p.Gln1756fs`), or rsID |
| `genome_build` | string | `GRCh38` | `GRCh38` or `GRCh37` |
| `include_llm` | boolean | `true` | Generate LLM narrative summaries |
| `audience` | string | `clinician` | `clinician` \| `patient` \| `researcher` |

**Response `200 OK`:**
```json
{
  "variant": "BRCA1:c.5266dup",
  "gene": "BRCA1",
  "classification": "Likely Pathogenic",
  "confidence": 67,
  "criteria_triggered": [
    {
      "code": "PVS1",
      "direction": "pathogenic",
      "strength": "PathogenicVeryStrong",
      "triggered": true,
      "evidence": "Frameshift variant in BRCA1 (pLI=1.0, LOEUF=0.09) — null variants are a known disease mechanism."
    },
    {
      "code": "PM2",
      "direction": "pathogenic",
      "strength": "PathogenicModerate",
      "triggered": true,
      "evidence": "Absent from gnomAD v4.1 (not found in population databases)."
    }
  ],
  "population_frequency": null,
  "clinvar_classification": "Pathogenic",
  "clinvar_stars": 3,
  "alphamissense_score": null,
  "llm_summary": "BRCA1:c.5266dup introduces a premature stop codon...",
  "llm_clinical_note": "This frameshift variant in BRCA1...",
  "llm_patient_note": "This genetic change creates an incomplete version of...",
  "warnings": [],
  "varos_version": "0.1.0"
}
```

**Classification values:**

| Value | Meaning |
|-------|---------|
| `Pathogenic` | Strong evidence of pathogenicity |
| `Likely Pathogenic` | Moderate evidence, ≥90% probability of pathogenicity |
| `VUS` | Variant of Uncertain Significance — insufficient evidence |
| `Likely Benign` | Moderate evidence of benignity |
| `Benign` | Strong evidence of benignity |

---

### `POST /v1/classify/report` 🔐

Same as `/v1/classify` but streams a PDF report (or HTML if WeasyPrint is unavailable).

**Request:** Same as `POST /v1/classify`

**Response:** `200 OK` with `Content-Type: application/pdf` (binary stream)

```bash
curl -X POST https://api.varos.io/v1/classify/report \
  -H "X-VAROS-KEY: vrs_xxx" \
  -H "Content-Type: application/json" \
  -d '{"variant": "BRCA1:c.5266dup"}' \
  --output report.pdf
```

---

### `GET /v1/me` 🔐

Returns your account details and current usage.

**Response `200 OK`:**
```json
{
  "email": "researcher@lab.edu",
  "name": "Dr. Jane Smith",
  "organization": "Broad Institute",
  "tier": "free",
  "api_key": "vrs_abc123...",
  "credits_used": 3,
  "credits_limit": 10,
  "credits_remaining": 7,
  "member_since": "2026-03-05T00:00:00Z"
}
```

---

### `GET /v1/usage` 🔐

Returns this month's usage, quota, and last 10 classified variants.

**Response `200 OK`:**
```json
{
  "tier": "free",
  "credits_used": 3,
  "credits_limit": 10,
  "credits_remaining": 7,
  "reset_date": "April 1, 2026",
  "recent_variants": [
    "BRCA1:c.5266dup",
    "TP53:c.817C>T",
    "CFTR:c.1521_1523delCTT"
  ]
}
```

---

### `POST /v1/billing/checkout` 🔐

Create a Stripe Checkout session to upgrade your plan.

**Request body:**
```json
{
  "tier": "starter",
  "success_url": "https://myapp.com/settings?upgraded=true",
  "cancel_url": "https://myapp.com/settings"
}
```

**Response `200 OK`:**
```json
{
  "checkout_url": "https://checkout.stripe.com/pay/cs_...",
  "session_id": "cs_test_..."
}
```

Redirect the user to `checkout_url`. After payment, Stripe fires a webhook to
`POST /v1/billing/webhook` which upgrades the user's tier automatically.

---

### `POST /v1/billing/webhook`

Stripe webhook endpoint. Called by Stripe — do not call directly.

---

## Error Codes

| Status | Code | Meaning |
|--------|------|---------|
| 401 | Unauthorized | Missing or invalid API key |
| 403 | Forbidden | Account disabled |
| 409 | Conflict | Email already registered |
| 422 | Unprocessable Entity | Invalid request body (validation error) |
| 429 | Too Many Requests | Monthly quota exceeded. Upgrade at varos.io/pricing |
| 500 | Internal Server Error | Classification pipeline error |

**429 response example:**
```json
{
  "detail": "Monthly quota exceeded (10 variants for free tier). Upgrade at https://varos.io/pricing"
}
```
Headers included with 429:
- `X-Quota-Limit: 10`
- `X-Quota-Used: 10`

---

## Rate Limits

| Tier | Variants/month | Requests/minute |
|------|---------------|-----------------|
| Free | 10 | 10 |
| Starter | 200 | 60 |
| Pro | 2,000 | 200 |
| Enterprise | Unlimited | Custom |

---

## SDK / Code Examples

### Python
```python
import requests

API_KEY = "vrs_your_key_here"
BASE_URL = "https://api.varos.io"

result = requests.post(
    f"{BASE_URL}/v1/classify",
    headers={"X-VAROS-KEY": API_KEY},
    json={"variant": "BRCA1:c.5266dup", "include_llm": False},
).json()

print(result["classification"])  # "Likely Pathogenic"
print(result["confidence"])       # 67
```

### JavaScript / Node.js
```javascript
const response = await fetch("https://api.varos.io/v1/classify", {
  method: "POST",
  headers: {
    "X-VAROS-KEY": "vrs_your_key_here",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ variant: "BRCA1:c.5266dup" }),
});
const result = await response.json();
console.log(result.classification); // "Likely Pathogenic"
```

### CLI (curl)
```bash
# Set your key once
export VAROS_KEY="vrs_your_key_here"

# Classify
curl -s -X POST https://api.varos.io/v1/classify \
  -H "X-VAROS-KEY: $VAROS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"variant": "BRCA1:c.5266dup"}' | python -m json.tool

# Download PDF report
curl -X POST https://api.varos.io/v1/classify/report \
  -H "X-VAROS-KEY: $VAROS_KEY" \
  -H "Content-Type: application/json" \
  -d '{"variant": "BRCA1:c.5266dup"}' \
  --output BRCA1_c.5266dup_report.pdf
```
