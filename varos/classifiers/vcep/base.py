"""Base class for ClinGen Variant Curation Expert Panel (VCEP) rule sets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Dict, List, Optional


class CriteriaOverride:
    """A modification to a standard ACMG criterion for a specific gene/context."""

    def __init__(
        self,
        criterion: str,
        enabled: bool = True,
        strength: Optional[str] = None,
        threshold: Optional[float] = None,
        notes: str = "",
    ):
        self.criterion = criterion
        self.enabled = enabled
        self.strength = strength  # "supporting" | "moderate" | "strong" | "very_strong"
        self.threshold = threshold
        self.notes = notes


class VCEPRuleset(ABC):
    """
    Abstract base for a ClinGen VCEP gene-specific ruleset.

    Subclasses define ``name``, ``version``, ``genes``, ``specification_url``
    as class variables, then implement ``overrides()`` to replace or disable
    ACMG criteria for specific genes.
    """

    name: ClassVar[str]
    version: ClassVar[str]
    genes: ClassVar[List[str]]
    specification_url: ClassVar[str]

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

_REGISTRY: Dict[str, "VCEPRuleset"] = {}


def register(cls):
    """Class decorator — instantiates and registers a VCEPRuleset subclass."""
    instance = cls()
    for gene in cls.genes:
        _REGISTRY[gene.upper()] = instance
    return cls


def get_ruleset(gene: str) -> Optional[VCEPRuleset]:
    """Return the active VCEP ruleset for *gene*, or None for generic ACMG."""
    return _REGISTRY.get(gene.upper())

