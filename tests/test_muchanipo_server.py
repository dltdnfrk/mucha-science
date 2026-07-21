"""Worker-1 acceptance: subprocess + JSON-line parsing for `muchanipo serve`."""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.muchanipo import parse_action
from src.muchanipo import server as server_mod
from src.muchanipo.events import KNOWN_EVENTS, emit
from src.muchanipo.server import _detect_offline_mode, scientific_serve, serve
from src.muchanipo import server
from src.runtime.paths import (
    ENV_MUCHANIPO_HOME,
    ENV_VAULT_PATH,
    get_muchanipo_home,
    get_vault_path,
    rubric_score_max,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_serve(args: list[str], *, stdin_text: str = "") -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Ensure the project root is on PYTHONPATH so `python -m muchanipo` resolves
    # the top-level shim package without requiring `pip install -e .`.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + existing if existing else "")
    return subprocess.run(
        [sys.executable, "-m", "muchanipo", "serve", *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=15,
        check=False,
    )


def _parse_lines(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_serve_emits_canonical_phase_order(tmp_path: Path) -> None:
    report = tmp_path / "REPORT.md"
    proc = _run_serve(
        ["--topic", "test", "--pipeline", "stub", "--no-wait", "--report-path", str(report)],
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    phase_order = [e["phase"] for e in events if e["event"] == "phase_change"]
    assert phase_order == ["STARTUP", "INTERVIEW", "COUNCIL", "REPORT"]
    assert any(e["event"] == "done" for e in events)
    assert report.exists()


def test_serve_every_event_type_is_known(tmp_path: Path) -> None:
    proc = _run_serve(
        ["--topic", "x", "--pipeline", "stub", "--no-wait", "--report-path", str(tmp_path / "R.md")],
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    assert events, "expected at least one event line"
    for ev in events:
        assert ev["event"] in KNOWN_EVENTS, f"unknown event: {ev}"


def test_serve_advances_after_interview_answer(tmp_path: Path) -> None:
    answer = json.dumps({"action": "interview_answer", "q_id": "Q1", "answer": "A"})
    proc = _run_serve(
        ["--topic", "wired", "--pipeline", "stub", "--report-path", str(tmp_path / "R.md")],
        stdin_text=answer + "\n",
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    # After the answer, COUNCIL + REPORT phases must run.
    phases = [e["phase"] for e in events if e["event"] == "phase_change"]
    assert "COUNCIL" in phases
    assert "REPORT" in phases


def test_serve_aborts_cleanly_on_abort_action(tmp_path: Path) -> None:
    proc = _run_serve(
        ["--topic", "stop", "--pipeline", "stub", "--report-path", str(tmp_path / "R.md")],
        stdin_text=json.dumps({"action": "abort"}) + "\n",
    )
    assert proc.returncode == 0, proc.stderr
    events = _parse_lines(proc.stdout)
    assert events[-1]["event"] == "done"
    assert events[-1].get("aborted") is True


def test_emit_writes_json_line_and_flushes() -> None:
    buf = io.StringIO()
    emit("phase_change", stream=buf, phase="INTERVIEW", data={"q": 1})
    line = buf.getvalue()
    assert line.endswith("\n")
    obj = json.loads(line)
    assert obj == {"event": "phase_change", "phase": "INTERVIEW", "data": {"q": 1}}


def test_parse_action_round_trips() -> None:
    a = parse_action(json.dumps({"action": "interview_answer", "q_id": "Q1", "answer": "B"}))
    assert a is not None
    assert a.action == "interview_answer"
    assert a.fields == {"q_id": "Q1", "answer": "B"}

    assert parse_action("") is None
    assert parse_action("not-json") is None
    assert parse_action(json.dumps({"no_action_key": 1})) is None


def test_serve_in_process_writes_report(tmp_path: Path) -> None:
    report = tmp_path / "R.md"
    rc = serve(
        "in-process",
        report_path=report,
        wait_for_input=False,
        stdout=io.StringIO(),
        stdin=io.StringIO(),
        pipeline="stub",
    )
    assert rc == 0
    assert report.read_text(encoding="utf-8").startswith("# in-process")


def test_serve_rejects_stub_pipeline_when_live_requested(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MUCHANIPO_REQUIRE_LIVE", "1")
    report = tmp_path / "R.md"
    stdout = io.StringIO()

    rc = serve(
        "live-stub",
        report_path=report,
        wait_for_input=False,
        stdout=stdout,
        stdin=io.StringIO(),
        pipeline="stub",
    )

    events = _parse_lines(stdout.getvalue())
    assert rc == 1
    assert events[-2]["event"] == "error"
    assert events[-2]["kind"] == "live_mode_violation"
    assert events[-1] == {"event": "done", "pipeline": "stub", "aborted": True}
    assert not report.exists()


def test_serve_subcommand_accepts_depth_for_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []

    def fake_serve(topic, *, report_path, wait_for_input, stdout, stdin, pipeline="full", depth="deep", scientific_mode=False, repository=None, scientific_config=None):
        calls.append(
            {
                "topic": topic,
                "report_path": report_path,
                "wait_for_input": wait_for_input,
                "pipeline": pipeline,
                "depth": depth,
            }
        )
        return 0

    monkeypatch.setattr(server_mod, "serve", fake_serve)

    rc = server_mod.main([
        "serve",
        "--topic",
        "depth bridge",
        "--pipeline",
        "full",
        "--depth",
        "shallow",
        "--report-path",
        str(tmp_path / "R.md"),
        "--no-wait",
    ])

    assert rc == 0
    assert calls == [
        {
            "topic": "depth bridge",
            "report_path": tmp_path / "R.md",
            "wait_for_input": False,
            "pipeline": "full",
            "depth": "shallow",
        }
    ]


def test_serve_subcommand_defaults_to_full_pipeline(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict] = []

    def fake_serve(topic, *, report_path, wait_for_input, stdout, stdin, pipeline="full", depth="deep", scientific_mode=False, repository=None, scientific_config=None):
        calls.append(
            {
                "topic": topic,
                "report_path": report_path,
                "wait_for_input": wait_for_input,
                "pipeline": pipeline,
                "depth": depth,
            }
        )
        return 0

    monkeypatch.setattr(server_mod, "serve", fake_serve)

    rc = server_mod.main([
        "serve",
        "--topic",
        "default full",
        "--report-path",
        str(tmp_path / "R.md"),
        "--no-wait",
    ])

    assert rc == 0
    assert calls == [
        {
            "topic": "default full",
            "report_path": tmp_path / "R.md",
            "wait_for_input": False,
            "pipeline": "full",
            "depth": "deep",
        }
    ]


def test_detect_offline_mode_treats_local_cli_as_online(monkeypatch):
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "1")

    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/claude" if name == "claude" else None)

    assert _detect_offline_mode() is False


def test_detect_offline_mode_treats_opencode_cli_as_online(monkeypatch):
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "1")

    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/opencode" if name == "opencode" else None)

    assert _detect_offline_mode() is False


def test_detect_offline_mode_treats_opencode_api_key_as_online(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "0")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "oc-test")

    import shutil

    monkeypatch.setattr(shutil, "which", lambda _name: None)

    assert _detect_offline_mode() is False


def test_detect_offline_mode_can_disable_cli_preference(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_PREFER_CLI", "0")
    monkeypatch.delenv("MUCHANIPO_USE_CLI", raising=False)
    monkeypatch.delenv("ANTHROPIC_USE_CLI", raising=False)
    monkeypatch.delenv("OPENCODE_USE_CLI", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.delenv("XIAOMI_MIMO_API_KEY", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)

    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/claude")

    assert _detect_offline_mode() is True


def test_detect_offline_mode_keeps_pytest_offline_despite_host_keys(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "server-test")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "host-token")
    monkeypatch.delenv("MUCHANIPO_PREFER_CLI", raising=False)
    monkeypatch.delenv("MUCHANIPO_USE_CLI", raising=False)
    monkeypatch.delenv("MUCHANIPO_ONLINE", raising=False)
    monkeypatch.delenv("MUCHANIPO_OFFLINE", raising=False)

    assert _detect_offline_mode() is True
def _scientific_action(name: str, *, payload: dict, cycle_id: str | None = None) -> str:
    message_id = "message_00000000000000000000000000000000"
    if name == "protocol.hello" and "protocol_versions" in payload:
        payload = {
            "handshake_idempotency_key": "request-1",
            "client_instance_id": "client_00000000000000000000000000000000",
            "supported_versions": payload["protocol_versions"],
            "capabilities": [], "projection": "full", "cursors": [],
        }
    if name == "cycle.resume" and not payload:
        cycle_id = cycle_id or "cycle_00000000000000000000000000000000"
        payload = {
            "client_instance_id": "client_00000000000000000000000000000000",
            "request_ordinal": 1, "cycle_id": cycle_id,
            "cursor": {"cycle_id": cycle_id, "sequence": 0,
                       "event_hash": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"},
            "projection": "full",
        }
    return json.dumps({
        "protocol": "muchanipo", "protocol_version": "ai-scientist.v1", "kind": "action", "name": name,
        "message_id": message_id, "cycle_id": cycle_id,
        "correlation_id": message_id, "causation_id": None, "sequence": 0, "revision": 0,
        "idempotency_key": None if name in {"cycle.replay", "cycle.resume", "export.get", "report.render", "cycle.ack"} else "request-1",
        "timestamp": "1970-01-01T00:00:00.000000Z",
        "payload": payload, "extensions": {},
    })


def test_scientific_result_submit_without_approved_root_is_not_advertised_and_denied(tmp_path: Path) -> None:
    from src.pipeline.cycle_repository import CycleRepository

    config = {"enabled": True, "protocol_capability": True, "allow_new_cycles": True,
              "allow_external_result_import": True, "emergency_read_only": False}
    digest = "sha256:" + "0" * 64
    reference = {
        "reference_type": "run", "issuer": "external", "title": "completed work",
        "uri_or_identifier": "reference-1", "content_hash": digest,
        "assertion_source": "external_reference",
        "verification_status": "external_reference_unverified",
        "authority_scope": {"kind": "externally_asserted", "scope": "work"},
    }
    result_submit = {
        "expected_revision": 0,
        "proposal_id": "proposal_00000000000000000000000000000000",
        "proposal_hash": digest,
        "supersedes_result_id": None,
        "execution_kind": "computational",
        "accountable_party": {
            "actor_kind": "human", "display_name": "Operator", "organization": None, "role": None,
            "assertion_source": "operator_entry", "verification_status": "operator_asserted_unverified",
            "authority_scope": {"kind": "none", "scope": None}, "external_reference": None,
        },
        "performers": [{
            "kind": "organization", "name": "External Lab", "version": None,
            "external_reference": reference,
        }],
        "started_at": "2026-07-19T00:00:00.000000Z",
        "completed_at": "2026-07-19T01:00:00.000000Z",
        "external_references": [reference],
        "staged_blob_ids": ["external_blob_00000000000000000000000000000000"],
        "result_manifest": {"summary": "completed externally"},
        "deviations": [],
    }
    stdin = io.StringIO("\n".join((
        _scientific_action("protocol.hello", payload={
            "protocol_versions": ["ai-scientist.v1"],
            "normalization_profile": "unicode-nfc-whitespace",
            "normalization_profile_version": "1",
        }),
        _scientific_action("result.submit", payload=result_submit),
    )) + "\n")
    stdout = io.StringIO()
    assert scientific_serve(repository=CycleRepository(tmp_path / "home"), stdin=stdin, stdout=stdout,
                            scientific_config=config) == 0
    welcome, rejection = _parse_lines(stdout.getvalue())
    assert re.fullmatch(r"[a-z][a-z0-9_]*_[0-9a-f]{32}", welcome["payload"]["connection_id"])
    assert re.fullmatch(r"[a-z][a-z0-9_]*_[0-9a-f]{32}", welcome["payload"]["server_instance_id"])
    assert "result.submit" not in welcome["payload"]["capabilities"]
    assert rejection["payload"]["stable_code"] == "import_forbidden"
def test_scientific_import_roots_are_absolute_canonical_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    file_root = tmp_path / "file"
    file_root.write_text("not a directory", encoding="utf-8")
    symlink_root = tmp_path / "approved-link"
    symlink_root.symlink_to(approved, target_is_directory=True)

    for root in ("relative-root", str(file_root), str(symlink_root)):
        with pytest.raises(server.ScientificConfigError):
            server._scientific_config({"approved_import_roots": [root]})

    monkeypatch.chdir(tmp_path)
    config = server._scientific_config({
        "allow_external_result_import": True,
        "approved_import_roots": [str(approved.resolve())],
    })

    assert server._approved_import_roots(config) == (approved.resolve(),)
    assert "result.submit" in server._advertised_capabilities(config)

def test_load_scientific_config_prefers_explicit_home_and_falls_back_only_when_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "__file__", str(tmp_path / "src" / "muchanipo" / "server.py"))
    fallback = tmp_path / "config" / "config.json"
    fallback.parent.mkdir()
    fallback.write_text('{"enabled": false}', encoding="utf-8")
    home = tmp_path / "home"

    assert server._load_scientific_config(home) == {"enabled": False}

    home.mkdir()
    (home / "config.json").write_text('{"enabled": true}', encoding="utf-8")
    assert server._load_scientific_config(home) == {"enabled": True}


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("{", "invalid JSON scientific config"),
        ("[]", "must be a JSON object"),
    ],
)
def test_load_scientific_config_rejects_invalid_explicit_config(
    tmp_path: Path, contents: str, message: str,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / "config.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(server.ScientificConfigError, match=message) as exc_info:
        server._load_scientific_config(home)

    assert str(path) in str(exc_info.value)


def test_load_scientific_config_rejects_unreadable_explicit_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    path = home / "config.json"
    path.write_text("{}", encoding="utf-8")
    read_text = Path.read_text

    def deny_config_read(candidate: Path, *args: object, **kwargs: object) -> str:
        if candidate == path:
            raise PermissionError("denied")
        return read_text(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_config_read)

    with pytest.raises(server.ScientificConfigError, match="unable to read scientific config") as exc_info:
        server._load_scientific_config(home)

    assert str(path) in str(exc_info.value)


@pytest.mark.parametrize("error", [KeyError("repository bug"), TypeError("repository bug"), ValueError("repository bug")])
def test_scientific_server_propagates_unexpected_repository_errors(error: Exception) -> None:
    class BrokenRepository:
        def state_snapshot(self, cycle_id: str) -> dict[str, object]:
            del cycle_id
            raise error

    config = {"enabled": True, "protocol_capability": True, "allow_new_cycles": True,
              "emergency_read_only": False}
    stdin = io.StringIO("\n".join((
        _scientific_action("protocol.hello", payload={
            "protocol_versions": ["ai-scientist.v1"],
            "normalization_profile": "unicode-nfc-whitespace",
            "normalization_profile_version": "1",
        }),
        _scientific_action("cycle.resume", payload={}, cycle_id="cycle_00000000000000000000000000000000"),
    )) + "\n")

    with pytest.raises(type(error), match="repository bug"):
        scientific_serve(repository=BrokenRepository(), stdin=stdin, stdout=io.StringIO(), scientific_config=config)


def test_scientific_server_returns_validation_error_for_cycle_request_error() -> None:
    config = {"enabled": True, "protocol_capability": True, "allow_new_cycles": True,
              "emergency_read_only": False}
    stdin = io.StringIO("\n".join((
        _scientific_action("protocol.hello", payload={
            "protocol_versions": ["ai-scientist.v1"],
            "normalization_profile": "unicode-nfc-whitespace",
            "normalization_profile_version": "1",
        }),
        _scientific_action("cycle.resume", payload={}),
    )) + "\n")
    stdout = io.StringIO()

    class InvalidRepository:
        def state_snapshot(self, cycle_id: str) -> dict[str, object]:
            del cycle_id
            raise server.CycleError("invalid cycle request")

    assert scientific_serve(repository=InvalidRepository(), stdin=stdin, stdout=stdout, scientific_config=config) == 0
    assert _parse_lines(stdout.getvalue())[-1]["payload"]["stable_code"] == "validation_failed"
@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"ai_scientist": []}, "ai_scientist section must be a JSON object"),
        *[
            ({"ai_scientist": {name: value}}, f"ai_scientist.{name} must be a boolean")
            for name in (
                "enabled",
                "protocol_capability",
                "allow_new_cycles",
                "allow_external_result_import",
                "emergency_read_only",
            )
            for value in (0, "false", None)
        ],
    ],
)
def test_scientific_server_rejects_malformed_policy_before_negotiation(
    config: dict[str, object], message: str,
) -> None:
    stdout = io.StringIO()

    with pytest.raises(server.ScientificConfigError, match=message):
        scientific_serve(
            repository=object(),
            stdin=io.StringIO(_scientific_action("protocol.hello", payload={
                "protocol_versions": ["ai-scientist.v1"],
                "normalization_profile": "unicode-nfc-whitespace",
                "normalization_profile_version": "1",
            }) + "\n"),
            stdout=stdout,
            scientific_config=config,
        )

    assert stdout.getvalue() == ""


@pytest.mark.parametrize(
    ("environment", "getter"),
    [
        (ENV_MUCHANIPO_HOME, get_muchanipo_home),
        (ENV_VAULT_PATH, get_vault_path),
    ],
)
def test_rooted_runtime_paths_reject_absolute_traversal_and_symlink_escapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    getter: object,
) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    monkeypatch.setenv(environment, str(root))

    for part in (str(outside), "../outside"):
        with pytest.raises(ValueError, match="must not be absolute or traverse parents"):
            getter(part, create=True)  # type: ignore[operator]

    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes its configured root"):
        getter("escape", "created", create=True)  # type: ignore[operator]

    assert not (outside / "created").exists()


@pytest.mark.parametrize(
    ("environment", "getter"),
    [
        (ENV_MUCHANIPO_HOME, get_muchanipo_home),
        (ENV_VAULT_PATH, get_vault_path),
    ],
)
def test_rooted_runtime_paths_create_only_under_configured_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    getter: object,
) -> None:
    root = tmp_path / "root"
    monkeypatch.setenv(environment, str(root))

    path = getter("nested", "child", create=True)  # type: ignore[operator]

    assert path == root.resolve() / "nested" / "child"
    assert path.is_dir()


def test_rubric_score_max_preserves_explicit_zero_and_defaults_only_missing_axes() -> None:
    assert rubric_score_max({}) == 100
    assert rubric_score_max({"axes": {}}) == 0
    assert rubric_score_max({"axes": {
        "inactive": {"active_for_score": False, "max": 10},
        "zero_weight": {"weight": 0, "max": 10},
    }}) == 0
    assert rubric_score_max({"axes": {"active": {"weight": 1, "max": 7}}}) == 7


def test_rubric_score_max_retains_list_and_malformed_axis_behavior() -> None:
    assert rubric_score_max({"axes": ["a", "b"]}) == 20
    assert rubric_score_max({"axes": None}) == 100
    assert rubric_score_max({"axes": {"legacy": None}}) == 10
    with pytest.raises(ValueError):
        rubric_score_max({"axes": {"bad_weight": {"weight": "not-a-number"}}})
    with pytest.raises(ValueError):
        rubric_score_max({"axes": {"bad_max": {"max": "not-a-number"}}})
