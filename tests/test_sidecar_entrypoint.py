from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools import build_scientific_sidecar as sidecar


def _hello() -> dict[str, object]:
    return {
        "protocol": "muchanipo",
        "protocol_version": "ai-scientist.v1",
        "kind": "action",
        "name": "protocol.hello",
        "message_id": "message_00000000000000000000000000000000",
        "cycle_id": None,
        "correlation_id": "message_00000000000000000000000000000000",
        "causation_id": None,
        "sequence": 0,
        "revision": 0,
        "idempotency_key": "request-1",
        "timestamp": "1970-01-01T00:00:00.000000Z",
        "payload": {
            "handshake_idempotency_key": "request-1",
            "client_instance_id": "client_00000000000000000000000000000000",
            "supported_versions": ["ai-scientist.v1"],
            "capabilities": [],
            "projection": "full",
            "cursors": [],
        },
        "extensions": {},
    }


def _scientific_home(tmp_path: Path) -> Path:
    home = tmp_path / "MUCHANIPO_HOME"
    home.mkdir()
    (home / "config.json").write_text(json.dumps({
        "ai_scientist": {
            "enabled": True,
            "protocol_capability": True,
            "allow_new_cycles": True,
            "allow_external_result_import": False,
            "emergency_read_only": False,
        }
    }), encoding="utf-8")
    return home


def _build(output_dir: Path) -> tuple[Path, Path]:
    return sidecar.build(Path(sys.executable), sidecar.host_target(), output_dir, "-")


def test_built_sidecar_runs_scientific_handshake_outside_repository(tmp_path: Path) -> None:
    artifact, _ = _build(tmp_path / "sidecar")
    home = _scientific_home(tmp_path)
    outside_repository = tmp_path / "outside-repository"
    outside_repository.mkdir()
    completed = subprocess.run(
        [str(artifact), "serve", "--topic", "scientific-cycle", "--scientific-mode", "--scientific-home", str(home)],
        input=json.dumps(_hello()) + "\n",
        text=True,
        capture_output=True,
        check=False,
        cwd=outside_repository,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    response = json.loads(completed.stdout.splitlines()[0])
    assert response["name"] == "protocol.welcome.response"
    assert response["correlation_id"] == _hello()["message_id"]
    assert response["payload"]["selected_version"] == "ai-scientist.v1"


def test_build_is_deterministic_and_manifest_matches_artifact(tmp_path: Path) -> None:
    first_artifact, first_manifest_path = _build(tmp_path / "first")
    second_artifact, second_manifest_path = _build(tmp_path / "second")

    assert first_artifact.read_bytes() == second_artifact.read_bytes()
    assert first_manifest_path.read_bytes() == second_manifest_path.read_bytes()
    manifest = json.loads(first_manifest_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(first_artifact.read_bytes()).hexdigest()
    assert manifest["artifact"] == first_artifact.name
    assert manifest["artifact_sha256"] == digest
    assert manifest["byte_length"] == first_artifact.stat().st_size
    assert manifest["pyinstaller_version"] == sidecar.PINNED_PYINSTALLER_VERSION
    assert (first_artifact.parent / f"{first_artifact.name}.sha256").read_text(encoding="ascii") == f"{digest}  {first_artifact.name}\n"


def test_source_manifest_rejects_symlinked_runtime_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repository"
    source = root / "src" / "muchanipo"
    source.mkdir(parents=True)
    target = tmp_path / "outside.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    (source / "server.py").symlink_to(target)
    (root / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
    monkeypatch.setattr(sidecar, "ROOT", root)
    monkeypatch.setattr(sidecar, "RUNTIME_MODULES", ("src.muchanipo.server",))

    with pytest.raises(ValueError, match="must not be a symlink"):
        sidecar.source_manifest()


def test_runtime_modules_are_a_closed_allowlist() -> None:
    assert "src.muchanipo.server" in sidecar.RUNTIME_MODULES
    assert "src.muchanipo.web" in sidecar.RUNTIME_MODULES
    assert "src.muchanipo.web.protocol_dispatch" in sidecar.RUNTIME_MODULES
    assert "src.muchanipo.web.protocol_handler" in sidecar.RUNTIME_MODULES
    assert "src.muchanipo.web.protocol_output" in sidecar.RUNTIME_MODULES
    assert "src.muchanipo.web.scientific_config" in sidecar.RUNTIME_MODULES
    assert "src.pipeline.scientific_contracts" in sidecar.RUNTIME_MODULES
    assert all("*" not in module for module in sidecar.RUNTIME_MODULES)
