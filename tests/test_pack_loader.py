from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.pipeline.scientific_contracts import canonical_json
from src.packs_loader import (
    IntegrityError,
    LicenseActivationError,
    ManifestValidationError,
    discover_packs,
    load_pack,
)


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_pack(
    directory: Path,
    *,
    name: str = "example-knowledge",
    decision: str = "ALLOWED",
    extra_manifest: dict[str, object] | None = None,
) -> dict[str, object]:
    directory.mkdir(parents=True)
    data = b'{"knowledge":"example"}\n'
    (directory / "knowledge.json").write_bytes(data)
    manifest: dict[str, object] = {
        "name": name,
        "semver": "1.2.3",
        "schema_version": "1",
        "title": "Example knowledge pack",
        "license": {
            "expression": "CC-BY-4.0",
            "terms_uri": "https://creativecommons.org/licenses/by/4.0/",
            "decision": decision,
            "restrictions": ["internal-use-only"] if decision == "RESTRICTED" else [],
        },
        "references": [],
        "files": [{"path": "knowledge.json", "sha256": _sha256(data)}],
    }
    manifest.update(extra_manifest or {})
    (directory / "pack.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def test_valid_minimal_pack_loads_with_canonical_manifest_identity(tmp_path: Path) -> None:
    pack_dir = tmp_path / "example"
    manifest = _write_pack(pack_dir)

    handle = load_pack(pack_dir)

    assert handle.name == "example-knowledge"
    assert handle.version == "1.2.3"
    assert handle.manifest_sha256 == _sha256(canonical_json(manifest))
    assert handle.restricted is False


def test_tampered_data_file_is_rejected(tmp_path: Path) -> None:
    pack_dir = tmp_path / "example"
    _write_pack(pack_dir)
    with (pack_dir / "knowledge.json").open("ab") as data_file:
        data_file.write(b"x")

    with pytest.raises(IntegrityError, match="knowledge.json"):
        load_pack(pack_dir)


@pytest.mark.parametrize("field", ["functional_purpose", "fixed_objective"])
def test_manifest_cannot_fix_functional_purpose(tmp_path: Path, field: str) -> None:
    pack_dir = tmp_path / "example"
    _write_pack(pack_dir, extra_manifest={field: "maximize crop yield"})

    with pytest.raises(ManifestValidationError):
        load_pack(pack_dir)


@pytest.mark.parametrize("decision", ["DENIED", "UNKNOWN"])
def test_fail_closed_license_decisions_refuse_activation(tmp_path: Path, decision: str) -> None:
    pack_dir = tmp_path / "example"
    _write_pack(pack_dir, decision=decision)

    with pytest.raises(LicenseActivationError, match=decision):
        load_pack(pack_dir)


def test_restricted_pack_requires_explicit_override_and_is_flagged(tmp_path: Path) -> None:
    pack_dir = tmp_path / "example"
    _write_pack(pack_dir, decision="RESTRICTED")

    with pytest.raises(LicenseActivationError, match="RESTRICTED"):
        load_pack(pack_dir)

    handle = load_pack(pack_dir, allow_restricted=True)
    assert handle.restricted is True


def test_discovery_finds_multiple_pack_directories(tmp_path: Path) -> None:
    first = tmp_path / "z-pack"
    second = tmp_path / "a-pack"
    _write_pack(first, name="z-pack")
    _write_pack(second, name="a-pack")
    (tmp_path / "not-a-pack").mkdir()
    (tmp_path / "root-file").write_text("ignored", encoding="utf-8")

    assert discover_packs(tmp_path) == (second, first)
