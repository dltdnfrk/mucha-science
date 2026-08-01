"""Tests for src.source_adapters — curated-source lookup with license gates."""

from __future__ import annotations

import pytest

from src.source_adapters import (
    CHEMBL_RESOURCE,
    SourcePolicyError,
    ResourceError,
    activation_verdict,
    build_chembl_url,
    fetch_chembl,
    parse_chembl,
)


SAMPLE_PAYLOAD = """
{
  "molecules": [
    {
      "molecule_chembl_id": "CHEMBL25",
      "pref_name": "ASPIRIN",
      "molecule_type": "Small molecule",
      "max_phase": 4,
      "molecule_properties": {"full_molformula": "C9H8O4"}
    }
  ]
}
"""


class TestBuildChemblUrl:
    def test_uses_iexact_filter_not_similarity_search(self) -> None:
        url = build_chembl_url("Aspirin")
        assert "pref_name__iexact=Aspirin" in url
        assert "/search" not in url.split("?")[0].replace("molecule.json", "")
        assert "limit=1" in url

    def test_quotes_name(self) -> None:
        url = build_chembl_url("beta carotene")
        assert "beta+carotene" in url


class TestParseChembl:
    def test_exact_match_returns_record(self) -> None:
        match = parse_chembl(SAMPLE_PAYLOAD, "aspirin")
        assert match is not None
        assert match.resource == CHEMBL_RESOURCE
        assert match.external_id == "CHEMBL25"
        assert match.matched_name == "ASPIRIN"
        assert match.facts["max_phase"] == "4"
        assert match.facts["formula"] == "C9H8O4"
        assert "CHEMBL25" in match.record_url

    def test_near_miss_returns_none_not_closest(self) -> None:
        # Resource offers ASPIRIN when asked for ASPIRINN — must miss, not attach.
        assert parse_chembl(SAMPLE_PAYLOAD, "aspirinn") is None

    def test_empty_molecules_returns_none(self) -> None:
        assert parse_chembl('{"molecules": []}', "aspirin") is None

    def test_unparseable_json_raises(self) -> None:
        with pytest.raises(ResourceError):
            parse_chembl("not json", "aspirin")


class TestLicenseGate:
    def test_deferred_source_refused_without_allowed_decision(self) -> None:
        with pytest.raises(SourcePolicyError):
            activation_verdict(CHEMBL_RESOURCE, license_decision="UNKNOWN")
        with pytest.raises(SourcePolicyError):
            activation_verdict(CHEMBL_RESOURCE, license_decision="DENIED")

    def test_deferred_source_activates_only_with_allowed_decision(self) -> None:
        verdict = activation_verdict(CHEMBL_RESOURCE, license_decision="ALLOWED")
        assert verdict.active is True
        assert "defer" in verdict.note.lower() or "license" in verdict.note.lower()

    def test_required_source_still_records_decision(self) -> None:
        verdict = activation_verdict("uniprot", license_decision="ALLOWED")
        assert verdict.active is True


class TestFetchChembl:
    def test_fetch_uses_injected_transport_and_gate(self) -> None:
        calls: list[str] = []

        def fake_get(url: str) -> str:
            calls.append(url)
            return SAMPLE_PAYLOAD

        match = fetch_chembl("aspirin", http_get=fake_get, license_decision="ALLOWED")
        assert match is not None and match.external_id == "CHEMBL25"
        assert len(calls) == 1 and "pref_name__iexact=aspirin" in calls[0]

    def test_fetch_refused_when_gate_denies(self) -> None:
        def boom(url: str) -> str:  # pragma: no cover - must not be called
            raise AssertionError("transport must not be called when gate denies")

        with pytest.raises(SourcePolicyError):
            fetch_chembl("aspirin", http_get=boom, license_decision="UNKNOWN")
