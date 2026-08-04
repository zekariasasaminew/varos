"""Tests for the Ensembl transcript/exon/CDS annotation connector.

Uses pytest-httpx to mock the Ensembl REST responses — this environment's
network policy blocks outbound calls to rest.ensembl.org, so these tests
verify the parsing/combination logic against realistic fixture payloads
rather than exercising the live API end-to-end.
"""

from __future__ import annotations

import pytest

from varos.connectors.ensembl import annotate_transcript

VEP_URL = "https://rest.ensembl.org/vep/human/hgvs/NM_007294.4:c.5266dupC?content-type=application%2Fjson"
LOOKUP_URL = "https://rest.ensembl.org/lookup/id/NM_007294.4?expand=1&utr=0&content-type=application%2Fjson"


def _vep_payload(exon="8/23", cds_start=5266, protein_start=1756, mane_select=True, terms=None):
    return [
        {
            "transcript_consequences": [
                {
                    "transcript_id": "NM_007294.4",
                    "mane_select": "NM_007294.4" if mane_select else None,
                    "consequence_terms": terms or ["frameshift_variant"],
                    "exon": exon,
                    "cds_start": cds_start,
                    "protein_start": protein_start,
                    "hgvsc": "NM_007294.4:c.5266dupC",
                    "hgvsp": "NP_009225.1:p.Gln1756ProfsTer74",
                }
            ]
        }
    ]


def _lookup_payload(n_exons=23, protein_length=1863, exon_lengths=None):
    exon_lengths = exon_lengths or [150] * n_exons
    exons = []
    pos = 1
    for length in exon_lengths:
        exons.append({"start": pos, "end": pos + length - 1})
        pos += length
    return {
        "Translation": {"length": protein_length},
        "Exon": exons,
    }


@pytest.mark.asyncio
async def test_annotate_transcript_parses_exon_and_cds(httpx_mock):
    httpx_mock.add_response(url=VEP_URL, json=_vep_payload(exon="8/23"))
    httpx_mock.add_response(url=LOOKUP_URL, json=_lookup_payload(n_exons=23, protein_length=1863))

    annotation = await annotate_transcript("NM_007294.4:c.5266dupC", "NM_007294.4")

    assert annotation is not None
    assert annotation.transcript_id == "NM_007294.4"
    assert annotation.is_mane_select is True
    assert annotation.exon_number == 8
    assert annotation.total_exons == 23
    assert annotation.cds_position == 5266
    assert annotation.protein_length == 1863
    assert annotation.cds_length == (1863 + 1) * 3
    assert "frameshift_variant" in annotation.consequence_terms


@pytest.mark.asyncio
async def test_annotate_transcript_computes_skipped_exon_length(httpx_mock):
    httpx_mock.add_response(
        url=VEP_URL,
        json=_vep_payload(exon="3/23", terms=["splice_donor_variant"]),
    )
    exon_lengths = [150] * 22 + [150]
    exon_lengths[2] = 90  # exon 3 (1-based) is 90nt
    httpx_mock.add_response(
        url=LOOKUP_URL,
        json=_lookup_payload(n_exons=23, protein_length=1863, exon_lengths=exon_lengths),
    )

    annotation = await annotate_transcript("NM_007294.4:c.5266dupC", "NM_007294.4")

    assert annotation.skipped_exon_length_nt == 90


@pytest.mark.asyncio
async def test_annotate_transcript_no_consequences_returns_not_found(httpx_mock):
    httpx_mock.add_response(url=VEP_URL, json=[])

    annotation = await annotate_transcript("NM_007294.4:c.5266dupC", "NM_007294.4")

    assert annotation is not None
    assert annotation.not_found is True


@pytest.mark.asyncio
async def test_annotate_transcript_returns_none_on_http_error(httpx_mock):
    # fetch_vep_consequences is wrapped in @retry(stop_after_attempt(3)) —
    # register enough failing responses to cover every retry attempt.
    for _ in range(3):
        httpx_mock.add_response(url=VEP_URL, status_code=500)

    annotation = await annotate_transcript("NM_007294.4:c.5266dupC", "NM_007294.4")

    assert annotation is None
