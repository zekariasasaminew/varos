"""AlphaMissense connector — deep learning pathogenicity scores for missense variants.

AlphaMissense v1 covers 71 million human missense variants.
Source: https://storage.googleapis.com/dm_alphamissense/AlphaMissense_hg38.tsv.gz
Paper: Cheng et al., Science 2023 (https://doi.org/10.1126/science.adg7492)

On first use, the TSV is downloaded (~3.5 GB) and indexed in a local SQLite DB.
Subsequent queries are instant (<10ms).
"""

from __future__ import annotations

import csv
import gzip
import io
import os
import sqlite3
from pathlib import Path

import httpx
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

ALPHAMISSENSE_URL = "https://storage.googleapis.com/dm_alphamissense/AlphaMissense_hg38.tsv.gz"
DEFAULT_CACHE_DIR = Path(os.environ.get("VAROS_DATA_DIR", str(Path.home() / ".varos" / "data")))
DB_PATH = DEFAULT_CACHE_DIR / "alphamissense.db"

# Classification thresholds from DeepMind paper
LIKELY_PATHOGENIC_THRESHOLD = 0.564
LIKELY_BENIGN_THRESHOLD = 0.340


def _get_connection() -> sqlite3.Connection:
    DEFAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alphamissense (
            chrom TEXT NOT NULL,
            pos INTEGER NOT NULL,
            ref TEXT NOT NULL,
            alt TEXT NOT NULL,
            gene TEXT,
            transcript TEXT,
            protein_variant TEXT,
            am_pathogenicity REAL NOT NULL,
            am_class TEXT NOT NULL,
            PRIMARY KEY (chrom, pos, ref, alt)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pos ON alphamissense(chrom, pos)")
    conn.commit()


def is_indexed() -> bool:
    """Check if AlphaMissense data has been downloaded and indexed."""
    if not DB_PATH.exists():
        return False
    try:
        with _get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM alphamissense LIMIT 1").fetchone()
            return count is not None and count[0] > 0
    except Exception:
        return False


def download_and_index(cache_dir: Path | None = None) -> None:
    """Download AlphaMissense TSV and index into SQLite. ~3.5 GB download, takes 10-20 min."""
    db_path = (cache_dir or DEFAULT_CACHE_DIR) / "alphamissense.db"
    conn = sqlite3.connect(str(db_path))
    _ensure_table(conn)

    print("Downloading AlphaMissense v1 (~3.5 GB)...")
    with httpx.stream("GET", ALPHAMISSENSE_URL, follow_redirects=True, timeout=3600) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        compressed = io.BytesIO()
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn()) as progress:
            task = progress.add_task("Downloading AlphaMissense...", total=total)
            for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                compressed.write(chunk)
                progress.advance(task, len(chunk))

    print("Indexing into SQLite (this takes a few minutes)...")
    compressed.seek(0)
    batch: list[tuple] = []
    with gzip.open(compressed, "rt") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for i, row in enumerate(reader):
            if row.get("#CHROM", "").startswith("#"):
                continue
            batch.append((
                row.get("#CHROM", row.get("CHROM", "")),
                int(row.get("POS", 0)),
                row.get("REF", ""),
                row.get("ALT", ""),
                row.get("gene", ""),
                row.get("transcript", ""),
                row.get("protein_variant", ""),
                float(row.get("am_pathogenicity", 0)),
                row.get("am_class", ""),
            ))
            if len(batch) >= 100_000:
                conn.executemany(
                    "INSERT OR IGNORE INTO alphamissense VALUES (?,?,?,?,?,?,?,?,?)", batch
                )
                conn.commit()
                batch.clear()
                if i % 1_000_000 == 0:
                    print(f"  Indexed {i:,} variants...")
    if batch:
        conn.executemany("INSERT OR IGNORE INTO alphamissense VALUES (?,?,?,?,?,?,?,?,?)", batch)
        conn.commit()
    conn.close()
    print("AlphaMissense indexing complete.")


def lookup_score(chrom: str, pos: int, ref: str, alt: str) -> dict | None:
    """
    Look up AlphaMissense score for a missense variant.
    Returns dict with am_pathogenicity, am_class, protein_variant or None if not found.
    Note: Only covers missense variants. For other types, returns None.
    """
    if not is_indexed():
        return None

    chrom = chrom.replace("chr", "")
    with _get_connection() as conn:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT am_pathogenicity, am_class, protein_variant, gene FROM alphamissense "
            "WHERE chrom=? AND pos=? AND ref=? AND alt=?",
            (chrom, pos, ref, alt),
        ).fetchone()

    if row:
        return dict(row)
    return None
