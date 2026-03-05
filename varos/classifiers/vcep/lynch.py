"""
Lynch Syndrome / MMR VCEP — ClinGen Mismatch Repair (MMR) Gene VCEP rules.

Genes: MLH1, MSH2, MSH6, PMS2, EPCAM
Specification: ClinGen InSiGHT/MMR VCEP v3.0.0 (2022)
https://clinicalgenome.org/affiliation/50002/

Key modifications from generic ACMG/AMP 2015:
  - PM2: AF threshold <0.0001 (1e-4) for MMR genes — Lynch syndrome prevalence ~1/279
  - BS1: AF threshold 0.0001 — variants common in general population unlikely pathogenic for LS
  - BP7: Restricted — must use MaxEntScan to confirm no cryptic splice effect (not just location)
  - PP2: Disabled — MMR genes have pathogenic missense throughout; criterion not informative
  - PP3: REVEL ≥0.70 required for supporting (more stringent than generic 0.5)
  - BP4: REVEL ≤0.15 required for supporting benign (more stringent)
  - PS3: Functional assays considered strong evidence (MMR assays well-validated)
  - BS3: Well-established functional studies showing no impact = stand-alone benign
"""

from __future__ import annotations

from typing import ClassVar, Dict, List

from varos.classifiers.vcep.base import CriteriaOverride, VCEPRuleset, register


@register
class MMRLynchVCEP(VCEPRuleset):
    """ClinGen MMR/Lynch syndrome VCEP v3.0.0 ruleset."""

    name: ClassVar[str] = "MMR/Lynch Syndrome VCEP"
    version: ClassVar[str] = "v3.0.0"
    genes: ClassVar[List[str]] = ["MLH1", "MSH2", "MSH6", "PMS2", "EPCAM"]
    specification_url: ClassVar[str] = "https://clinicalgenome.org/affiliation/50002/"

    def overrides(self) -> Dict[str, CriteriaOverride]:
        return {
            # PM2: Lynch prevalence ~1/279, so AF threshold tightened
            "PM2": CriteriaOverride(
                criterion="PM2",
                enabled=True,
                threshold=0.0001,  # 1 in 10,000
                notes="MMR VCEP v3.0.0: PM2 threshold 1e-4 (popmax gnomAD; Lynch prevalence ~1/279)",
            ),
            # BS1: variant too common to be causative for Lynch syndrome
            "BS1": CriteriaOverride(
                criterion="BS1",
                enabled=True,
                threshold=0.0001,
                notes="MMR VCEP v3.0.0: BS1 threshold 1e-4 in gnomAD popmax",
            ),
            # PP2: disabled — MMR genes have pathogenic missense throughout
            "PP2": CriteriaOverride(
                criterion="PP2",
                enabled=False,
                notes="MMR VCEP v3.0.0: PP2 not applicable for MMR genes",
            ),
            # PP3: REVEL ≥0.70 required (InSiGHT calibration study)
            "PP3": CriteriaOverride(
                criterion="PP3",
                enabled=True,
                threshold=0.70,
                notes="MMR VCEP v3.0.0: PP3 requires REVEL ≥0.70 (calibrated to MMR gene data)",
            ),
            # BP4: REVEL ≤0.15 required for supporting benign
            "BP4": CriteriaOverride(
                criterion="BP4",
                enabled=True,
                threshold=0.15,
                notes="MMR VCEP v3.0.0: BP4 requires REVEL ≤0.15",
            ),
            # BP7: cannot rely solely on position — require MaxEntScan confirmation
            "BP7": CriteriaOverride(
                criterion="BP7",
                enabled=True,
                notes=(
                    "MMR VCEP v3.0.0: BP7 requires MaxEntScan ≤10% splice score change "
                    "to confirm no cryptic splice effect before applying"
                ),
            ),
        }
