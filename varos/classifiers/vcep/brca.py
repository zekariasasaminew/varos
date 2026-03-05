"""
BRCA1/2 VCEP — ClinGen BRCA1 and BRCA2 Variant Curation Expert Panel rules.

Specification: ClinGen BRCA1/2 VCEP v1.1.0 (2023)
https://clinicalgenome.org/affiliation/50087/

Key modifications from generic ACMG/AMP 2015:
  - PM2: gnomAD AF threshold lowered to <0.00001 (1e-5) for BRCA1/2 (more stringent than default 0.01)
  - BP7: Extended to include intronic variants >3bp from splice site
  - BS1: Threshold 0.001 (1 in 1000) — specific to BRCA1/2 disease prevalence
  - PP2: Not applicable to BRCA1/2 (too many missense variants of all classes)
  - BP1: BRCA1/2 have many pathogenic missense — criterion unreliable, disabled
  - PS1: Same amino acid change as established pathogenic — applicable with caution
  - PVS1: Reduced to strong for BRCA2 missense (BRCA2 has functional hotspots)
"""

from __future__ import annotations

from typing import ClassVar, Dict, List

from varos.classifiers.vcep.base import CriteriaOverride, VCEPRuleset, register


@register
class BRCA12VCEP(VCEPRuleset):
    """ClinGen BRCA1/2 VCEP v1.1.0 ruleset."""

    name: ClassVar[str] = "BRCA1/2 VCEP"
    version: ClassVar[str] = "v1.1.0"
    genes: ClassVar[List[str]] = ["BRCA1", "BRCA2"]
    specification_url: ClassVar[str] = "https://clinicalgenome.org/affiliation/50087/"

    def overrides(self) -> Dict[str, CriteriaOverride]:
        return {
            # PM2: more stringent AF threshold for dominant high-penetrance cancer genes
            "PM2": CriteriaOverride(
                criterion="PM2",
                enabled=True,
                threshold=0.00001,  # 1 in 100,000 (default is 0.01 = 1 in 100)
                notes="BRCA1/2 VCEP v1.1.0: PM2 threshold 1e-5 in gnomAD (popmax)",
            ),
            # BS1: benign stand-alone — variant too common for pathogenic in BRCA1/2
            "BS1": CriteriaOverride(
                criterion="BS1",
                enabled=True,
                threshold=0.001,  # 1 in 1,000 — slightly higher than generic
                notes="BRCA1/2 VCEP v1.1.0: BS1 threshold 0.001 given cancer risk prevalence",
            ),
            # PP2: disabled — not informative for BRCA1/2 (too many missense of all types)
            "PP2": CriteriaOverride(
                criterion="PP2",
                enabled=False,
                notes="BRCA1/2 VCEP v1.1.0: PP2 not applicable (missense variants not rare in BRCA1/2)",
            ),
            # BP1: disabled — many pathogenic missense in BRCA1/2 make this unreliable
            "BP1": CriteriaOverride(
                criterion="BP1",
                enabled=False,
                notes="BRCA1/2 VCEP v1.1.0: BP1 not applicable (BRCA1/2 has pathogenic missense throughout)",
            ),
            # BP7: extended to silent/intronic >3bp from splice (BRCA1/2 specific splice tolerance)
            "BP7": CriteriaOverride(
                criterion="BP7",
                enabled=True,
                notes="BRCA1/2 VCEP v1.1.0: BP7 applies to intronic variants >3bp from splice junction",
            ),
        }
