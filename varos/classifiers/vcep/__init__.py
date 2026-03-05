"""VCEP gene-specific rule overrides — ClinGen Variant Curation Expert Panels."""

from varos.classifiers.vcep.base import VCEPRuleset, CriteriaOverride, register, get_ruleset

# Import VCEP modules to trigger registration
from varos.classifiers.vcep import brca  # noqa: F401
from varos.classifiers.vcep import lynch  # noqa: F401

__all__ = ["VCEPRuleset", "CriteriaOverride", "register", "get_ruleset"]
