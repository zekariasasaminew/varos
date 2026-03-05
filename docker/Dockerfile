# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# Install system deps for WeasyPrint (PDF generation)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
    libglib2.0-0 libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e .

# Copy source
COPY varos/ ./varos/

# /data is the Fly.io persistent volume mount point.
# SQLite DB lives at /data/varos.db
# AlphaMissense cache lives at /data/.varos/data (if pre-loaded)
RUN mkdir -p /data/.varos/data

ENV VAROS_ENV=production \
    DATABASE_URL=sqlite:////data/varos.db \
    VAROS_DATA_DIR=/data/.varos/data \
    HOME=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Single worker — 1GB Fly.io shared VM; scale horizontally not vertically
CMD ["uvicorn", "varos.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
