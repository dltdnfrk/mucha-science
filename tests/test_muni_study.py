from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.muni import (
    StudyValidationError,
    create_study,
    create_target_selection,
    list_studies,
    load_study,
    save_study,
)
from src.muni_contracts import Study, TargetSelection
from src.packs_loader import IntegrityError


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_pack(directory: Path) -> Path:
    directory.mkdir()
    data = b'{"item":"synthetic"}\n'
    (directory / "data.json").write_bytes(data)
    manifest = {
        "name": "synthetic-pack",
        "semver": "1.2.3",
        "schema_version": "1",
        "title": "Synthetic pack",
        "license": {
            "expression": "CC0-1.0",
            "terms_uri": None,
            "decision": "ALLOWED",
            "restrictions": [],
        },
        "references": [],
        "files": [{"path": "data.json", "sha256": _sha256(data)}],
    }
    (directory / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_three_synthetic_targets_create_studies_without_target_configuration() -> None:
    targets = (("cropA", "pathogenX"), ("cropB", "pathogenY"), ("cropC", "pathogenZ"))

    studies = [create_study(crop, pathogen, "purposeAlpha") for crop, pathogen in targets]

    assert [(study.target_crop, study.target_pathogen) for study in studies] == list(targets)
    assert len({study.study_id for study in studies}) == 3


@pytest.mark.parametrize(
    "crop,pathogen,field",
    [
        ("", "pathogenX", "target_crop"),
        ("   ", "pathogenX", "target_crop"),
        ("cropA", "", "target_pathogen"),
        ("cropA", "\n", "target_pathogen"),
        ("crop\x00A", "pathogenX", "target_crop"),
        ("cropA", "pathogen\x1fX", "target_pathogen"),
    ],
)
def test_invalid_targets_raise_explicit_validation_error(
    crop: str, pathogen: str, field: str
) -> None:
    with pytest.raises(StudyValidationError, match=field):
        create_study(crop, pathogen, "purposeAlpha")


def test_overlong_target_is_rejected() -> None:
    with pytest.raises(StudyValidationError, match="target_crop.*256"):
        create_study("x" * 257, "pathogenX", "purposeAlpha")


def test_whitespace_is_normalized_without_constraining_target_values() -> None:
    padded = create_study("  cropA  ", " pathogenX   variantA ", " purpose   Alpha ")
    plain = create_study("cropA", "pathogenX variantA", "purpose Alpha")

    assert padded.target_crop == plain.target_crop == "cropA"
    assert padded.target_pathogen == plain.target_pathogen == "pathogenX variantA"
    assert padded.purpose == plain.purpose == "purpose Alpha"


def test_study_creation_does_not_require_a_pack() -> None:
    study = create_study("cropA", "pathogenX", "purposeAlpha", pack_ref=None)

    assert isinstance(study, Study)
    assert study.pack_ref is None


def test_valid_pack_records_the_loaded_pack_identity(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path / "pack")

    study = create_study("cropA", "pathogenX", "purposeAlpha", str(pack_dir))

    identity = json.loads(study.pack_ref or "")
    assert identity == {
        "manifest_sha256": identity["manifest_sha256"],
        "name": "synthetic-pack",
        "restricted": False,
        "version": "1.2.3",
    }
    assert identity["manifest_sha256"].startswith("sha256:")


def test_tampered_pack_fails_before_a_study_is_constructed(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path / "pack")
    (pack_dir / "data.json").write_bytes(b"tampered")

    with patch("src.muni.study.Study.from_content") as construct:
        with pytest.raises(IntegrityError, match="sha256 mismatch"):
            create_study("cropA", "pathogenX", "purposeAlpha", str(pack_dir))
    construct.assert_not_called()


def test_target_selection_captures_normalized_lab_provenance() -> None:
    selection = create_target_selection(
        " cropA ", " pathogenX ", selected_by=" lab   teamA ", note=" selected   externally "
    )

    assert isinstance(selection, TargetSelection)
    assert selection.to_content() == {
        "target_crop": "cropA",
        "target_pathogen": "pathogenX",
        "selected_by": "lab teamA",
        "note": "selected externally",
    }


def test_study_registry_round_trip_preserves_identity_and_targets(tmp_path: Path) -> None:
    study = create_study("cropB", "pathogenY", "purposeBeta")

    path = save_study(study, root=tmp_path)
    loaded = load_study(study.study_id, root=tmp_path)

    assert path == tmp_path / "studies" / f"{study.study_id}.json"
    assert loaded == study
    assert loaded.study_id == study.study_id
    assert (loaded.target_crop, loaded.target_pathogen) == ("cropB", "pathogenY")
    assert list_studies(root=tmp_path) == (study,)


def test_registry_root_can_be_configured_by_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUNI_DATA_ROOT", str(tmp_path))
    study = create_study("cropC", "pathogenZ", "purposeGamma")

    save_study(study)

    assert load_study(study.study_id) == study
    assert (tmp_path / "studies" / f"{study.study_id}.json").is_file()


def test_source_contains_no_hardcoded_real_world_targets() -> None:
    forbidden = ("wheat", "rice", "maize", "fusarium", "phytophthora", "xanthomonas")
    source_roots = (Path("src/muni"), Path("src/muni_contracts"))

    for root in source_roots:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            assert not any(term in text for term in forbidden), path
