# Contributing to VAROS

Thank you for your interest in contributing! This guide covers setting up your development
environment, understanding the codebase, and submitting changes.

---

## Development Setup

```bash
git clone https://github.com/zekariasasaminew/varos.git
cd varos

# Install with dev dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and NCBI_EMAIL at minimum

# Run tests to verify setup
pytest tests/ -v
# Expected: 42 passed
```

---

## Branch Workflow

**Never commit directly to `main`.** Branch protection is enforced.

```bash
# 1. Create a feature branch from main
git checkout main && git pull
git checkout -b feat/my-feature

# 2. Make small, focused commits (max 1 file per commit is ideal)
git add varos/classifiers/acmg.py
git commit -m "feat(acmg): add PS1 criterion for same amino acid change"

# 3. Push and open a PR
git push -u origin feat/my-feature
gh pr create --title "feat: add PS1 criterion" --body "..."

# 4. After PR is merged, delete the branch
git checkout main && git pull
git branch -d feat/my-feature
```

### Branch naming conventions

| Prefix | Use for |
|--------|---------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `test/` | Test additions/improvements |
| `docs/` | Documentation only |
| `refactor/` | Code refactoring without feature changes |
| `chore/` | Build, CI, dependency updates |

---

## Commit Message Format

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `perf`

**Scopes:** `acmg`, `combiner`, `orchestrator`, `connectors`, `api`, `cli`, `reports`, `daemon`

**Examples:**
```
feat(acmg): add PS1 criterion (same amino acid change as established pathogenic)
fix(combiner): correct likely_benign rule — BS1 alone should give Likely Benign
test(api): add quota exhaustion test
docs(api): add Python SDK example to API.md
chore: update pydantic to 2.10.0
```

---

## Adding a New ACMG Criterion

1. **Add the evaluator function** in `varos/classifiers/acmg.py`:

```python
def evaluate_ps1(
    normalized: NormalizedVariant | None,
    clinvar_ev: ClinVarEvidence | None,
) -> ACMGCriterion:
    """PS1 — Same amino acid change as established pathogenic variant."""
    criterion = ACMGCriterion(
        code="PS1",
        direction=ACMGDirection.PATHOGENIC,
        applied_strength=ACMGStrength.PATHOGENIC_STRONG,
    )
    # ... evaluation logic ...
    return criterion
```

2. **Wire it into the orchestrator** in `varos/agents/orchestrator.py`:

```python
criteria: list[ACMGCriterion] = [
    acmg_criteria.evaluate_pvs1(...),
    acmg_criteria.evaluate_ps1(norm, clinvar_ev),   # ← add here
    # ... other criteria ...
]
```

3. **Add a unit test** in `tests/test_acmg.py`:

```python
def test_ps1_triggered_when_same_aa_in_clinvar():
    clin = ClinVarEvidence(
        aggregate_classification="Pathogenic",
        same_amino_acid_change=True,
    )
    result = acmg_criteria.evaluate_ps1(None, clin)
    assert result.triggered is True
```

---

## Adding a New Connector

1. Create `varos/connectors/mydb.py`:

```python
"""Connector for MyDatabase."""

from __future__ import annotations
from varos.models import MyDataType


async def fetch_mydata(gene: str) -> MyDataType | None:
    """Fetch data from MyDatabase."""
    try:
        # ... HTTP/DB call ...
        return MyDataType(...)
    except Exception as e:
        raise  # let orchestrator handle gracefully
```

2. **Import it** in `varos/connectors/__init__.py`

3. **Add to `asyncio.gather`** in `varos/agents/orchestrator.py`:

```python
mydata_task = mydb.fetch_mydata(norm.gene_symbol)

pop_freq, clinvar_ev, lit_ev, comp_scores, my_result = await asyncio.gather(
    gnomad_task, clinvar_task, pubmed_task, computational_task, mydata_task,
    return_exceptions=True,
)
```

4. **Handle exceptions** with the `_unwrap` helper in orchestrator.py

5. **Write tests** using `unittest.mock.AsyncMock`

---

## Running Tests

```bash
# All tests
pytest tests/ -v

# With coverage report
pytest tests/ --cov=varos --cov-report=html
open htmlcov/index.html

# Just unit tests (fast, offline)
pytest tests/test_combiner.py tests/test_acmg.py -v

# Just API tests
pytest tests/test_api.py -v
```

---

## Code Style

- **Black** for formatting: `black varos/ tests/`
- **Ruff** for linting: `ruff check varos/ tests/`
- **Type hints** on all public functions
- **Docstrings** on all modules, classes, and public functions
- No inline comments unless the logic genuinely needs clarification

---

## Project Structure

```
varos/
├── __init__.py          # Version
├── config.py            # Pydantic Settings (env vars)
├── models.py            # Core Pydantic data models
├── agents/
│   └── orchestrator.py  # asyncio.gather pipeline
├── classifiers/
│   ├── acmg.py          # ACMG criteria evaluators
│   └── combiner.py      # Table 5 combination rules
├── connectors/
│   ├── gnomad.py        # gnomAD v4.1 GraphQL
│   ├── clinvar.py       # NCBI ClinVar Entrez
│   ├── alphamissense.py # Local SQLite index
│   ├── pubmed.py        # NCBI PubMed Entrez
│   └── spliceai.py      # SpliceAI Lookup API
├── api/
│   ├── app.py           # FastAPI app
│   ├── auth.py          # API key auth + quota
│   ├── database.py      # SQLAlchemy
│   ├── models.py        # ORM models
│   ├── schemas.py       # Pydantic schemas
│   └── routes/
│       ├── classify.py
│       ├── users.py
│       └── billing.py
├── cli/                 # Typer CLI commands
├── daemon/              # APScheduler monitoring daemon
└── reports/             # PDF/HTML report generation
```
