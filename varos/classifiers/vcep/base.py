"""Base class for ClinGen Variant Curation Expert Panel (VCEP) rule sets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CriteriaOverride:
    """A modification to a standard ACMG criterion for a specific gene/context."""
    criterion: str           # e.g. "PM2", "PP3"
    enabled: bool = True     # False = criterion is disabled for this gene
    strength: Optional[str] = None  # Override default strength: "supporting" | "moderate" | "strong" | "very_strong"
    threshold: Optional[float] = None  # Override numeric threshold (e.g. gnomAD AF cutoff)
    notes: str = ""


@dataclass
class VCEPRuleset(ABC):
    """
    Abstract base for a ClinGen VCEP gene-specific ruleset.

    Subclasses implement ``applies_to`` and ``overrides`` to replace
    or disable ACMG criteria for specific genes.
    """

    name: str                 # Human-readable VCEP name, e.g. "BRCA1/2 VCEP"
    version: str              # Published specification version, e.g. "v1.1.0"
    genes: List[str]          # HGNC symbols this ruleset applies to, e.g. ["BRCA1", "BRCA2"]
    specification_url: str    # ClinGen SVI specification URL

    @abstractmethod
    def overrides(self) -> Dict[str, CriteriaOverride]:
        """
        Return a mapping of criterion_name -> CriteriaOverride.

        Criteria NOT listed here are evaluated using standard ACMG logic.
        """

    def applies_to(self, gene: str) -> bool:
        """Return True if this ruleset governs the given gene symbol."""
        return gene.upper() in [g.upper() for g in self.genes]

    def citation(self) -> str:
        """Return a human-readable citation string for reports."""
        return f"{self.name} {self.version} — {self.specification_url}"


# ---------------------------------------------------------------------------
# Registry — auto-populated when VCEP modules are imported
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, VCEPRuleset] = {}


def register(ruleset: VCEPRuleset) -> VCEPRuleset:
    """Register a VCEP ruleset instance; called at module import time."""
    for gene in ruleset.genes:
        _REGISTRY[gene.upper()] = ruleset
    return ruleset


def get_ruleset(gene: str) -> Optional[VCEPRuleset]:
    """Return the active VCEP ruleset for *gene*, or None for generic ACMG."""
    return _REGISTRY.get(gene.upper())
