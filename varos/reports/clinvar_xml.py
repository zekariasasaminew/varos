"""
ClinVar Submission XML and CSV export.

Converts a VAROS classification result into ClinVar Submission API v2-compatible
XML or bulk-upload CSV format. Saves labs 30-60 minutes per variant submission.

ClinVar Submission API v2 spec:
https://www.ncbi.nlm.nih.gov/clinvar/docs/api_http/

Usage:
    from varos.reports.clinvar_xml import to_clinvar_xml, to_clinvar_csv

    xml_str = to_clinvar_xml(result, submitter_org="My Lab", submission_name="VAROS-2024")
    csv_str = to_clinvar_csv([result1, result2, result3])
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Optional


# ClinVar clinical significance vocabulary (germline)
_VAROS_TO_CLINVAR = {
    "Pathogenic": "Pathogenic",
    "Likely Pathogenic": "Likely pathogenic",
    "Uncertain Significance": "Uncertain significance",
    "Likely Benign": "Likely benign",
    "Benign": "Benign",
}

# Default submitter info (overridden by function parameters)
_DEFAULT_SUBMITTER = "VAROS — Variant Autonomous Reclassification & Observation System"
_DEFAULT_ORG_ID = "VAROS_SUBMITTER"


def to_clinvar_xml(
    result,
    submitter_org: str = _DEFAULT_SUBMITTER,
    submitter_org_id: str = _DEFAULT_ORG_ID,
    submission_name: Optional[str] = None,
    condition_name: Optional[str] = None,
    condition_db: str = "OMIM",
    condition_id: Optional[str] = None,
    assertion_method: str = "ACMG Guidelines, 2015",
    assertion_method_citation_pmid: str = "25741868",
    collection_method: str = "clinical testing",
    allele_origin: str = "germline",
    affected_status: str = "unknown",
    comment: Optional[str] = None,
) -> str:
    """
    Generate ClinVar Submission API v2 XML for a single classified variant.

    Args:
        result: VAROS ClassificationResult object
        submitter_org: Full organization name
        submitter_org_id: ClinVar organization ID (get from clinvar.ncbi.nlm.nih.gov)
        submission_name: Optional submission name for tracking
        condition_name: OMIM/MedGen disease name
        condition_db: 'OMIM', 'MedGen', 'Orphanet', or 'Human Phenotype Ontology'
        condition_id: ID in the specified database
        assertion_method: Guideline citation string
        collection_method: 'clinical testing', 'research', or 'literature only'
        allele_origin: 'germline', 'somatic', or 'de novo'
        affected_status: 'yes', 'no', or 'unknown'
        comment: Free-text interpretation comment

    Returns:
        XML string in ClinVar Submission API v2 format
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sub_name = submission_name or f"VAROS-{now}"

    # Root
    root = ET.Element("ClinVarSubmissionSet")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root.set("xsi:noNamespaceSchemaLocation",
             "http://ftp.ncbi.nlm.nih.gov/pub/clinvar/xsd_public/clinvar_public_1.71.xsd")

    # Submission header
    sub = ET.SubElement(root, "ClinVarSubmission")

    header = ET.SubElement(sub, "Header")
    ET.SubElement(header, "OrgID").text = submitter_org_id
    ET.SubElement(header, "SubmitterName").text = submitter_org
    ET.SubElement(header, "SubmissionName").text = sub_name
    ET.SubElement(header, "SubmissionDate").text = now

    # ClinVarAssertion
    assertion = ET.SubElement(sub, "ClinVarAssertion")

    # ClinVarAccession (empty for new submissions)
    ET.SubElement(assertion, "ClinVarAccession", Accession="")

    # ClinVarSubmissionID
    variant_id_safe = (result.variant.hgvs_cdna or "variant").replace(":", "_").replace(">", "_")
    ET.SubElement(assertion, "ClinVarSubmissionID",
                  localKey=f"{submitter_org_id}_{variant_id_safe}",
                  localKeyIsSubmitted="1")

    # Assertion method
    assert_method = ET.SubElement(assertion, "AssertionMethod")
    ET.SubElement(assert_method, "Description").text = assertion_method
    citation = ET.SubElement(assert_method, "Citation")
    ET.SubElement(citation, "ID", Source="PubMed").text = assertion_method_citation_pmid

    # Clinical significance
    clin_sig = ET.SubElement(assertion, "ClinicalSignificance")
    ET.SubElement(clin_sig, "ReviewStatus").text = "criteria provided, single submitter"
    clinvar_class = _VAROS_TO_CLINVAR.get(result.classification.value, "Uncertain significance")
    ET.SubElement(clin_sig, "Description").text = clinvar_class
    ET.SubElement(clin_sig, "DateLastEvaluated").text = now

    # Evidence (triggered criteria)
    if result.criteria_triggered:
        criteria_text = "; ".join(
            f"{c.code} ({c.applied_strength.value}): {c.evidence_text[:100]}"
            for c in result.criteria_triggered
            if c.triggered
        )
        ET.SubElement(clin_sig, "Comment").text = comment or criteria_text

    # Observed data
    obs_data = ET.SubElement(assertion, "ObservedData")
    ET.SubElement(obs_data, "AlleleOrigin").text = allele_origin
    ET.SubElement(obs_data, "AffectedStatus").text = affected_status
    ET.SubElement(obs_data, "CollectionMethod").text = collection_method

    # Measure set (the variant itself)
    measure_set = ET.SubElement(assertion, "MeasureSet", Type="Variant")
    measure = ET.SubElement(measure_set, "Measure", Type="Variation")

    attr_set = ET.SubElement(measure, "AttributeSet")
    attr = ET.SubElement(attr_set, "Attribute", Type="HGVS")
    attr.text = result.variant.hgvs_cdna or ""

    if result.variant.gene_symbol:
        gene_list = ET.SubElement(measure, "GeneList")
        gene = ET.SubElement(gene_list, "Gene", Symbol=result.variant.gene_symbol)

    # Trait set (condition)
    if condition_name or condition_id:
        trait_set = ET.SubElement(assertion, "TraitSet", Type="Disease")
        trait = ET.SubElement(trait_set, "Trait", Type="Disease")
        if condition_name:
            name_el = ET.SubElement(trait, "Name")
            ET.SubElement(name_el, "ElementValue", Type="Preferred").text = condition_name
        if condition_id and condition_db:
            xref = ET.SubElement(trait, "XRef",
                                  DB=condition_db,
                                  ID=condition_id,
                                  Type="MIM number" if condition_db == "OMIM" else "primary")

    # Pretty print
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def to_clinvar_csv(
    results: List,
    submitter_org: str = _DEFAULT_SUBMITTER,
    collection_method: str = "clinical testing",
    allele_origin: str = "germline",
) -> str:
    """
    Generate ClinVar bulk upload CSV for multiple classified variants.

    Returns a CSV string following the ClinVar submission spreadsheet format.
    Download the template from: https://www.ncbi.nlm.nih.gov/clinvar/docs/spreadsheet/
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # ClinVar bulk upload CSV header (v1.7 template)
    writer.writerow([
        "##Local ID",
        "Linking ID",
        "Gene symbol",
        "Reference sequence",
        "HGVS",
        "Chromosome",
        "Start",
        "Stop",
        "Reference allele",
        "Alternate allele",
        "Condition ID type",
        "Condition ID value",
        "Condition name",
        "Preferred condition name",
        "Allele origin",
        "Affected status",
        "Clinical significance",
        "Date last evaluated",
        "Assertion method",
        "Assertion method citation",
        "Assertion method citation ClinVar ID",
        "Comment on clinical significance",
        "Collection method",
        "Explanation if not full length",
    ])

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for i, result in enumerate(results, start=1):
        hgvs = result.variant.hgvs_cdna or ""
        gene = result.variant.gene_symbol or ""
        clinvar_class = _VAROS_TO_CLINVAR.get(result.classification.value, "Uncertain significance")
        criteria_text = "; ".join(
            f"{c.code}: {c.evidence_text[:80]}"
            for c in result.criteria_triggered
            if c.triggered
        ) if result.criteria_triggered else ""

        writer.writerow([
            f"VAROS_{i:04d}",        # Local ID
            "",                       # Linking ID
            gene,                     # Gene symbol
            "",                       # Reference sequence (from HGVS)
            hgvs,                     # HGVS
            "",                       # Chromosome
            "",                       # Start
            "",                       # Stop
            "",                       # Reference allele
            "",                       # Alternate allele
            "",                       # Condition ID type
            "",                       # Condition ID value
            "",                       # Condition name
            "",                       # Preferred condition name
            allele_origin,            # Allele origin
            "unknown",                # Affected status
            clinvar_class,            # Clinical significance
            now,                      # Date last evaluated
            "ACMG Guidelines, 2015",  # Assertion method
            "PMID:25741868",          # Assertion method citation
            "",                       # Assertion method citation ClinVar ID
            criteria_text[:500],      # Comment
            collection_method,        # Collection method
            "",                       # Explanation if not full length
        ])

    return output.getvalue()
