# VAROS Deployment Guide

---

## Option 1: Local Development

### Prerequisites
- Python 3.11+
- `pip` or `uv`

### Steps

```bash
git clone https://github.com/zekariasasaminew/varos.git
cd varos

# Install with dev dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env — at minimum set:
#   ANTHROPIC_API_KEY=sk-ant-...
#   NCBI_EMAIL=you@lab.edu

# (Optional) Download AlphaMissense database (~3.5 GB, one-time)
varos setup --alphamissense

# Start the API
varos serve --reload
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)
```

---

## Option 2: Docker

### Prerequisites
- Docker + Docker Compose

### Steps

```bash
git clone https://github.com/zekariasasaminew/varos.git
cd varos

# Create .env from template
cp .env.example .env
# Edit .env with your secrets

# Start
docker compose -f docker/docker-compose.yml up -d

# View logs
docker compose -f docker/docker-compose.yml logs -f

# Stop
docker compose -f docker/docker-compose.yml down
```

The API will be available at `http://localhost:8000`.

Data is persisted in the `varos_data` Docker volume.

---

## Option 3: Fly.io (Production)

### Prerequisites
- [Fly.io CLI](https://fly.io/docs/flyctl/installing/): `brew install flyctl` or `curl -L https://fly.io/install.sh | sh`
- Fly.io account: `fly auth login`

### Steps

```bash
# 1. Clone and enter project
git clone https://github.com/zekariasasaminew/varos.git
cd varos

# 2. Create Fly app (uses fly.toml)
fly launch --name varos-api --region ord --no-deploy

# 3. Set secrets (never commit these to git)
fly secrets set \
  ANTHROPIC_API_KEY="sk-ant-..." \
  NCBI_EMAIL="you@lab.edu" \
  NCBI_API_KEY="your_ncbi_key" \
  STRIPE_SECRET_KEY="sk_live_..." \
  STRIPE_WEBHOOK_SECRET="whsec_..." \
  STRIPE_STARTER_PRICE_ID="price_..." \
  STRIPE_PRO_PRICE_ID="price_..." \
  SENDGRID_API_KEY="SG...." \
  SENDGRID_FROM_EMAIL="alerts@varos.io"

# 4. Create a persistent volume for SQLite DB
fly volumes create varos_data --size 1 --region ord

# 5. Deploy
fly deploy

# 6. Verify
fly status
curl https://varos-api.fly.dev/health
```

### Stripe Webhook Setup

1. Go to [dashboard.stripe.com/webhooks](https://dashboard.stripe.com/webhooks)
2. Add endpoint: `https://varos-api.fly.dev/v1/billing/webhook`
3. Select events:
   - `checkout.session.completed`
   - `customer.subscription.deleted`
4. Copy the signing secret → `fly secrets set STRIPE_WEBHOOK_SECRET=whsec_...`

---

## Option 4: Any PaaS (Heroku, Railway, Render)

Set these environment variables in your platform's dashboard:

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key |
| `NCBI_EMAIL` | NCBI Entrez contact email |
| `NCBI_API_KEY` | NCBI API key (optional, improves rate limits) |
| `STRIPE_SECRET_KEY` | Stripe secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook signing secret |
| `STRIPE_STARTER_PRICE_ID` | Starter plan price ID |
| `STRIPE_PRO_PRICE_ID` | Pro plan price ID |
| `SENDGRID_API_KEY` | SendGrid API key |
| `SENDGRID_FROM_EMAIL` | Verified sender email |
| `DATABASE_URL` | PostgreSQL connection string (see below) |

**Start command:** `uvicorn varos.api.app:app --host 0.0.0.0 --port $PORT`

---

## Switching to PostgreSQL

The default database is SQLite (fine for up to ~10K users). For production scale:

1. Provision a PostgreSQL database (e.g., Fly Postgres, Neon, Supabase)
2. Set `DATABASE_URL=postgresql://user:pass@host:5432/varos`
3. Restart the API — `init_db()` creates tables automatically on startup

---

## Environment Variables Reference

```bash
# --- Required ---
ANTHROPIC_API_KEY=sk-ant-...      # Claude API (LLM reasoning)
NCBI_EMAIL=you@lab.edu            # NCBI Entrez contact (required by NCBI)

# --- Recommended ---
NCBI_API_KEY=...                  # NCBI API key (10 req/s vs 3/s without)

# --- Stripe billing (required for paid plans) ---
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_STARTER_PRICE_ID=price_... # $49/mo plan
STRIPE_PRO_PRICE_ID=price_...     # $199/mo plan

# --- Email notifications ---
SENDGRID_API_KEY=SG....
SENDGRID_FROM_EMAIL=alerts@varos.io

# --- Database ---
DATABASE_URL=sqlite:///./varos.db              # SQLite (default)
# DATABASE_URL=postgresql://...                # PostgreSQL (production)

# --- App config ---
VAROS_ENV=production              # development | production
VAROS_LOG_LEVEL=INFO
VAROS_LLM_MODEL=claude-sonnet-4-6 # or gpt-4o
SECRET_KEY=change-me-in-production
```

---

## Health Checks

The `/health` endpoint returns `200 OK` when the API is running:

```bash
curl https://your-deployment.example.com/health
# {"status":"ok","version":"0.1.0","llm_available":true,"timestamp":"..."}
```

Configure your load balancer / uptime monitor to hit this endpoint every 30s.

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# Unit tests only (fast, no network)
pytest tests/test_combiner.py tests/test_acmg.py -v

# API integration tests (uses in-memory SQLite)
pytest tests/test_api.py -v
```

Expected: **42 tests passing**
