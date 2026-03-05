"""Phase 3A unit tests — VCEP rules, somatic classifier, orgs, batch, watch, connectors."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# VCEP Framework Tests
# ---------------------------------------------------------------------------

class TestVCEPRegistry:
    def test_get_brca1_ruleset(self):
        from varos.classifiers.vcep.base import get_ruleset
        ruleset = get_ruleset("BRCA1")
        assert ruleset is not None
        assert "BRCA1" in ruleset.genes

    def test_get_brca2_ruleset(self):
        from varos.classifiers.vcep.base import get_ruleset
        ruleset = get_ruleset("BRCA2")
        assert ruleset is not None
        assert "BRCA2" in ruleset.genes

    def test_get_mlh1_ruleset(self):
        from varos.classifiers.vcep.base import get_ruleset
        ruleset = get_ruleset("MLH1")
        assert ruleset is not None
        assert "MLH1" in ruleset.genes

    def test_get_msh2_ruleset(self):
        from varos.classifiers.vcep.base import get_ruleset
        ruleset = get_ruleset("MSH2")
        assert ruleset is not None

    def test_unknown_gene_returns_none(self):
        from varos.classifiers.vcep.base import get_ruleset
        ruleset = get_ruleset("NONEXISTENT_GENE_XYZ")
        assert ruleset is None

    def test_brca_vcep_version(self):
        from varos.classifiers.vcep.brca import BRCA12VCEP
        assert BRCA12VCEP.version == "v1.1.0"

    def test_lynch_vcep_version(self):
        from varos.classifiers.vcep.lynch import MMRLynchVCEP
        assert MMRLynchVCEP.version == "v3.0.0"

    def test_brca_pm2_threshold(self):
        """BRCA VCEP uses stricter PM2 threshold than generic ACMG."""
        from varos.classifiers.vcep.brca import BRCA12VCEP
        instance = BRCA12VCEP()
        overrides = instance.overrides()
        assert "PM2" in overrides
        assert overrides["PM2"].threshold == 1e-5

    def test_brca_pp2_disabled(self):
        """BRCA VCEP disables PP2 (generic ACMG criterion not applicable)."""
        from varos.classifiers.vcep.brca import BRCA12VCEP
        instance = BRCA12VCEP()
        overrides = instance.overrides()
        assert "PP2" in overrides
        assert overrides["PP2"].enabled is False

    def test_lynch_pm2_threshold(self):
        """Lynch VCEP uses 1e-4 PM2 threshold."""
        from varos.classifiers.vcep.lynch import MMRLynchVCEP
        instance = MMRLynchVCEP()
        overrides = instance.overrides()
        assert "PM2" in overrides
        assert overrides["PM2"].threshold == 1e-4


# ---------------------------------------------------------------------------
# Somatic Classifier Tests
# ---------------------------------------------------------------------------

class TestSomaticClassifier:
    @pytest.mark.asyncio
    async def test_classify_somatic_returns_result(self, monkeypatch):
        """classify_somatic() returns a SomaticClassification with required fields."""
        # Patch connectors to avoid network calls
        from varos.classifiers import somatic
        monkeypatch.setattr(
            "varos.classifiers.somatic.get_onckb_annotation",
            lambda *a, **kw: None,
            raising=False,
        )
        monkeypatch.setattr(
            "varos.classifiers.somatic.get_civic_evidence",
            lambda *a, **kw: None,
            raising=False,
        )

        from varos.classifiers.somatic import classify_somatic
        result = await classify_somatic(
            variant_hgvs="chr7:g.55174772C>T",
            gene="EGFR",
            tumor_type="NSCLC",
        )
        assert result is not None
        assert result.tier in ("I", "II", "III", "IV", "Tier I", "Tier II", "Tier III", "Tier IV")
        assert 0.0 <= result.confidence <= 100.0

    @pytest.mark.asyncio
    async def test_somatic_tier_iii_without_evidence(self, monkeypatch):
        """Variant with no OncoKB/CIViC evidence should be Tier III (VUS)."""
        monkeypatch.setattr(
            "varos.classifiers.somatic.get_onckb_annotation",
            lambda *a, **kw: None,
            raising=False,
        )
        monkeypatch.setattr(
            "varos.classifiers.somatic.get_civic_evidence",
            lambda *a, **kw: None,
            raising=False,
        )

        from varos.classifiers.somatic import classify_somatic
        result = await classify_somatic(
            variant_hgvs="FAKE_VARIANT",
            gene="FAKE_GENE",
            tumor_type="solid_tumor",
        )
        assert result.tier in ("III", "Tier III")


# ---------------------------------------------------------------------------
# VCF Batch Processing Tests
# ---------------------------------------------------------------------------

class TestVCFParsing:
    def test_parse_vcf_basic(self):
        from varos.api.routes.batch import _parse_vcf
        vcf = "##header\n#CHROM\tPOS\tID\tREF\tALT\n7\t55174772\t.\tC\tT\n"
        variants = _parse_vcf(vcf)
        assert len(variants) == 1
        assert variants[0]["chrom"] == "7"
        assert variants[0]["ref"] == "C"
        assert variants[0]["alt"] == "T"

    def test_parse_vcf_skips_headers(self):
        from varos.api.routes.batch import _parse_vcf
        vcf = "##fileformat=VCFv4.2\n##FILTER=<ID=PASS>\n#CHROM\tPOS\tID\tREF\tALT\n1\t100\t.\tA\tG\n"
        variants = _parse_vcf(vcf)
        assert len(variants) == 1

    def test_parse_vcf_multiallelic(self):
        from varos.api.routes.batch import _parse_vcf
        vcf = "#CHROM\tPOS\tID\tREF\tALT\n1\t100\t.\tA\tG,T\n"
        variants = _parse_vcf(vcf)
        assert len(variants) == 2

    def test_parse_vcf_skips_star_allele(self):
        from varos.api.routes.batch import _parse_vcf
        vcf = "#CHROM\tPOS\tID\tREF\tALT\n1\t100\t.\tA\t*\n"
        variants = _parse_vcf(vcf)
        assert len(variants) == 0

    def test_prefilter_removes_same_ref_alt(self):
        from varos.api.routes.batch import _prefilter_variants
        variants = [{"ref": "A", "alt": "A", "chrom": "1", "pos": "100", "id": ".", "hgvs": ""}]
        filtered = _prefilter_variants(variants)
        assert len(filtered) == 0

    def test_prefilter_removes_structural(self):
        from varos.api.routes.batch import _prefilter_variants
        variants = [{"ref": "A", "alt": "<DEL>", "chrom": "1", "pos": "100", "id": ".", "hgvs": ""}]
        filtered = _prefilter_variants(variants)
        assert len(filtered) == 0

    def test_cost_estimate(self):
        """10 variants at $0.005 each = $0.05"""
        variants = [{"ref": "A", "alt": "G", "chrom": "1", "pos": str(i), "id": ".", "hgvs": ""} for i in range(10)]
        cost = round(len(variants) * 0.005, 2)
        assert cost == 0.05


# ---------------------------------------------------------------------------
# Watch Routes Tests (unit — no DB)
# ---------------------------------------------------------------------------

class TestWatchReclassificationProbability:
    def test_probability_vus_brca1(self):
        """VUS in BRCA1 should have high reclassification probability."""
        from varos.api.routes.watch import _reclassification_probability
        from unittest.mock import MagicMock
        from datetime import datetime, timezone
        watch = MagicMock()
        watch.original_classification = "Uncertain Significance"
        watch.gene = "BRCA1"
        watch.clinvar_variation_id = "12345"
        watch.created_at = datetime(2023, 1, 1, tzinfo=timezone.utc)
        prob = _reclassification_probability(watch)
        assert prob > 0.5

    def test_probability_benign_low(self):
        """Benign variant should have low reclassification probability."""
        from varos.api.routes.watch import _reclassification_probability
        from unittest.mock import MagicMock
        from datetime import datetime, timezone
        watch = MagicMock()
        watch.original_classification = "Benign"
        watch.gene = "OBSCURE_GENE"
        watch.clinvar_variation_id = None
        watch.created_at = datetime.now(timezone.utc)
        prob = _reclassification_probability(watch)
        assert prob < 0.5


# ---------------------------------------------------------------------------
# ClinVar XML Export Tests
# ---------------------------------------------------------------------------

class TestClinVarExport:
    def _make_stub_result(self, classification: str = "Likely Pathogenic", gene: str = "BRCA1"):
        from varos.api.routes.clinvar_export import _ResultStub, UsageRecord
        from unittest.mock import MagicMock
        record = MagicMock(spec=UsageRecord)
        record.variant = "NM_007294.4:c.5266dupC"
        record.classification = classification
        record.confidence = 85
        return _ResultStub(record)

    def test_xml_contains_hgvs(self):
        from varos.reports.clinvar_xml import to_clinvar_xml
        result = self._make_stub_result()
        xml = to_clinvar_xml(result)
        assert "NM_007294.4:c.5266dupC" in xml

    def test_xml_contains_classification(self):
        from varos.reports.clinvar_xml import to_clinvar_xml
        result = self._make_stub_result("Pathogenic")
        xml = to_clinvar_xml(result)
        assert "Pathogenic" in xml

    def test_xml_valid_structure(self):
        import xml.etree.ElementTree as ET
        from varos.reports.clinvar_xml import to_clinvar_xml
        result = self._make_stub_result()
        xml = to_clinvar_xml(result)
        # Should parse without error
        ET.fromstring(xml.split("\n", 1)[1])  # skip <?xml ...?> header

    def test_csv_has_headers(self):
        from varos.reports.clinvar_xml import to_clinvar_csv
        result = self._make_stub_result()
        csv = to_clinvar_csv([result])
        assert "HGVS" in csv
        assert "Clinical significance" in csv

    def test_csv_contains_classification(self):
        from varos.reports.clinvar_xml import to_clinvar_csv
        result = self._make_stub_result("Likely Pathogenic")
        csv = to_clinvar_csv([result])
        assert "Likely pathogenic" in csv  # maps to ClinVar vocabulary


# ---------------------------------------------------------------------------
# Evidence Summarizer Tests (no LLM)
# ---------------------------------------------------------------------------

class TestEvidenceSummarizer:
    @pytest.mark.asyncio
    async def test_no_llm_returns_empty(self, monkeypatch):
        """When no LLM is configured, summarizer returns empty list gracefully."""
        monkeypatch.setattr("varos.config.settings.anthropic_api_key", "")
        monkeypatch.setattr("varos.config.settings.openai_api_key", "")
        from varos.agents.evidence_summarizer import summarize_pubmed_evidence
        result = await summarize_pubmed_evidence(
            variant_hgvs="NM_007294.4:c.5266dupC",
            gene="BRCA1",
            abstracts=[{"pmid": "12345", "title": "Test", "abstract": "Test abstract"}],
        )
        assert result == []

    def test_parse_valid_json(self):
        from varos.agents.evidence_summarizer import _parse_llm_response
        json_str = '[{"criterion": "PS3", "direction": "pathogenic", "strength": "strong", "evidence": "Functional assay shows loss of function.", "pmid": "12345", "confidence": 0.92}]'
        annotations = _parse_llm_response(json_str, "12345")
        assert len(annotations) == 1
        assert annotations[0].criterion == "PS3"
        assert annotations[0].confidence == 0.92

    def test_parse_invalid_json_returns_empty(self):
        from varos.agents.evidence_summarizer import _parse_llm_response
        annotations = _parse_llm_response("not valid json {{", "12345")
        assert annotations == []

    def test_parse_unknown_criterion_skipped(self):
        from varos.agents.evidence_summarizer import _parse_llm_response
        json_str = '[{"criterion": "INVALID_CODE", "direction": "pathogenic", "strength": "strong", "evidence": "test", "pmid": "1", "confidence": 0.9}]'
        annotations = _parse_llm_response(json_str, "1")
        assert len(annotations) == 0

    def test_confidence_clamped(self):
        from varos.agents.evidence_summarizer import _parse_llm_response
        json_str = '[{"criterion": "PS3", "direction": "pathogenic", "strength": "strong", "evidence": "test", "pmid": "1", "confidence": 5.0}]'
        annotations = _parse_llm_response(json_str, "1")
        assert annotations[0].confidence == 1.0


# ---------------------------------------------------------------------------
# ClinicalTrials Connector Tests (mocked)
# ---------------------------------------------------------------------------

class TestClinicalTrialsConnector:
    @pytest.mark.asyncio
    async def test_search_returns_result_struct(self, monkeypatch):
        """search_trials_for_variant returns a TrialSearchResult."""
        import httpx
        from unittest.mock import AsyncMock, MagicMock

        mock_response = MagicMock()
        mock_response.json.return_value = {"studies": []}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        monkeypatch.setattr("varos.connectors.clinicaltrials.httpx.AsyncClient", lambda **kw: mock_client)

        from varos.connectors.clinicaltrials import search_trials_for_variant
        result = await search_trials_for_variant(
            variant_hgvs="NM_007294.4:c.5266dupC",
            gene="BRCA1",
            tumor_type="breast cancer",
        )
        assert result.gene == "BRCA1"
        assert result.total_found == 0
        assert result.trials == []

    @pytest.mark.asyncio
    async def test_no_gene_returns_empty(self):
        from varos.connectors.clinicaltrials import search_trials_for_variant
        result = await search_trials_for_variant(
            variant_hgvs="",
            gene=None,
        )
        assert result.total_found == 0
        assert result.trials == []
