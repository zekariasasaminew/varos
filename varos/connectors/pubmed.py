"""PubMed connector — literature evidence for variant pathogenicity."""

from __future__ import annotations

import asyncio
import re
from xml.etree import ElementTree as ET

from Bio import Entrez
from tenacity import retry, stop_after_attempt, wait_exponential

from varos.config import settings
from varos.models import LiteratureEvidence, PaperSummary

Entrez.email = settings.ncbi_email
if settings.ncbi_api_key:
    Entrez.api_key = settings.ncbi_api_key

# Keywords that suggest a paper contains functional/experimental evidence
FUNCTIONAL_KEYWORDS = [
    "functional", "assay", "in vitro", "in vivo", "expression", "splicing",
    "protein", "activity", "cell line", "mouse model", "knock", "mutant",
    "pathogenic", "deleterious", "loss of function", "gain of function",
]


def _build_search_query(gene: str, hgvs_cdna: str | None = None, hgvs_protein: str | None = None) -> str:
    """Build a PubMed search query for a variant."""
    terms = [f"{gene}[Gene Name]"]
    if hgvs_cdna:
        # Try both with and without transcript prefix
        cdna_short = re.sub(r"NM_\d+\.\d+:", "", hgvs_cdna)
        terms.append(f'("{hgvs_cdna}"[tiab] OR "{cdna_short}"[tiab])')
    if hgvs_protein:
        prot_short = re.sub(r"NP_\d+\.\d+:", "", hgvs_protein)
        terms.append(f'("{hgvs_protein}"[tiab] OR "{prot_short}"[tiab])')
    return " AND ".join(terms)


def _is_functional_paper(abstract: str) -> bool:
    text_lower = abstract.lower()
    return any(kw in text_lower for kw in FUNCTIONAL_KEYWORDS)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_literature_evidence(
    gene: str,
    hgvs_cdna: str | None = None,
    hgvs_protein: str | None = None,
    max_papers: int = 20,
) -> LiteratureEvidence:
    """Search PubMed for papers about this variant and extract key evidence."""
    loop = asyncio.get_event_loop()
    query = _build_search_query(gene, hgvs_cdna, hgvs_protein)

    # Search
    search_handle = await loop.run_in_executor(
        None,
        lambda: Entrez.esearch(db="pubmed", term=query, retmax=max_papers, sort="relevance"),
    )
    search_results = Entrez.read(search_handle)
    search_handle.close()

    pmids = search_results.get("IdList", [])
    if not pmids:
        return LiteratureEvidence(total_papers=0)

    # Fetch abstracts
    fetch_handle = await loop.run_in_executor(
        None,
        lambda: Entrez.efetch(db="pubmed", id=",".join(pmids), rettype="xml", retmode="xml"),
    )
    xml_content = fetch_handle.read()
    fetch_handle.close()

    papers = _parse_pubmed_xml(xml_content)
    functional = [p for p in papers if p.functional_evidence]

    return LiteratureEvidence(
        total_papers=len(papers),
        functional_papers=len(functional),
        papers=papers,
    )


def _parse_pubmed_xml(xml_content: bytes | str) -> list[PaperSummary]:
    """Parse PubMed XML into PaperSummary objects."""
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return []

    papers: list[PaperSummary] = []
    for article in root.findall(".//PubmedArticle"):
        pmid_elem = article.find(".//PMID")
        title_elem = article.find(".//ArticleTitle")
        abstract_elem = article.find(".//AbstractText")
        year_elem = article.find(".//PubDate/Year")
        journal_elem = article.find(".//Journal/Title")

        pmid = pmid_elem.text if pmid_elem is not None else ""
        title = title_elem.text if title_elem is not None else ""
        abstract = abstract_elem.text if abstract_elem is not None else ""
        year_text = year_elem.text if year_elem is not None else None
        journal = journal_elem.text if journal_elem is not None else None

        try:
            year = int(year_text) if year_text else None
        except ValueError:
            year = None

        functional = _is_functional_paper(f"{title} {abstract}")
        snippet = abstract[:300] + "..." if len(abstract) > 300 else abstract

        papers.append(PaperSummary(
            pmid=pmid,
            title=title,
            year=year,
            journal=journal,
            abstract_snippet=snippet,
            functional_evidence=functional,
        ))

    return papers
