from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from threading import Thread
from typing import Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src.objectives import OBJECTIVE_REGISTRY, PLATFORM_CONSTRAINT_IDS
from src.platform_contracts import UserQueryRevision
from src.webserver import NonLoopbackBindError, create_server
from src.webserver.server import (
    API_ROUTE_TABLE,
    DATA_DIR_ENV,
    DataDirectoryError,
    RequestHandler,
    resolve_data_directory,
)


HASH = "sha256:" + "a" * 64
VALID_OBJECTIVE_REF = dict(OBJECTIVE_REGISTRY["target_binding_activity"].objective_ref)
QUERY_CONTENT = {
    "query_id": "query-1",
    "parent_revision_id": None,
    "application_type": "CONTAINED_LAB",
    "objectives": [{
        "term_id": "potency",
        "objective_ref": VALID_OBJECTIVE_REF,
        "weight_units": 3,
        "parameters": {"direction": "higher"},
    }],
    "user_constraints": [],
    "change_set": ["ADD_OBJECTIVE"],
    "actor": "scientist-1",
    "created_at": "2026-08-01T00:00:00.000000Z",
}


@contextmanager
def running_server(
    *, packs_root: Path, static_root: Path, runs_root: Path | None = None
) -> Iterator[str]:
    server = create_server(
        port=0,
        packs_root=packs_root,
        runs_root=runs_root or packs_root.parent / "runs",
        static_root=static_root,
        data_dir=packs_root.parent,
        is_container=lambda: False,
        is_mount_point=lambda _path: False,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def request(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    content_type: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    headers = {"Content-Type": content_type} if content_type else {}
    req = Request(base_url + path, method=method, data=body, headers=headers)
    try:
        response = urlopen(req, timeout=2)
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()
    with response:
        return response.status, dict(response.headers.items()), response.read()


def test_health_packs_and_static_index(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>Mucha</title>", encoding="utf-8")

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = request(base_url, "/api/health")
        assert status == 200
        assert json.loads(body) == {
            "status": "ok",
            "data_volume_mounted": False,
        }

        status, _, body = request(base_url, "/api/packs")
        assert status == 200
        assert json.loads(body) == {"packs": []}

        status, headers, body = request(base_url, "/")
        assert status == 200
        assert headers["Content-Type"].startswith("text/html")
        assert b"<title>Mucha</title>" in body


def test_packs_returns_content_addressed_handles(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    pack = packs / "example"
    pack.mkdir(parents=True)
    content = b"pack content\n"
    (pack / "data.txt").write_bytes(content)
    manifest = {
        "name": "example",
        "semver": "1.2.3",
        "schema_version": "1",
        "title": "Example pack",
        "license": {
            "expression": "MIT",
            "terms_uri": None,
            "decision": "ALLOWED",
            "restrictions": [],
        },
        "references": [],
        "files": [{
            "path": "data.txt",
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
        }],
    }
    (pack / "pack.json").write_text(json.dumps(manifest), encoding="utf-8")
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = request(base_url, "/api/packs")

    assert status == 200
    handles = json.loads(body)["packs"]
    assert len(handles) == 1
    assert handles[0]["name"] == "example"
    assert handles[0]["version"] == "1.2.3"
    assert handles[0]["manifest_sha256"].startswith("sha256:")
    assert handles[0]["restricted"] is False


def _m1_server(tmp_path: Path, runs: dict[str, object]) -> tuple[Path, Path, Path]:
    packs = tmp_path / "packs"
    packs.mkdir()
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    for run_id, audit in runs.items():
        run_dir = runs_root / run_id
        run_dir.mkdir()
        (run_dir / "provenance_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    return packs, static, runs_root


def test_m1_runs_lists_run_directories(tmp_path: Path) -> None:
    packs, static, runs = _m1_server(tmp_path, {"run-b": {}, "run-a": {}})
    (runs / "not-an-m1-run").mkdir()

    with running_server(packs_root=packs, static_root=static, runs_root=runs) as base_url:
        status, _, body = request(base_url, "/api/m1/runs")

    assert status == 200
    assert json.loads(body) == {"runs": ["run-a", "run-b"]}


def test_m1_run_returns_parsed_provenance_audit(tmp_path: Path) -> None:
    audit = {"pack_identity": {"manifest_sha256": HASH}, "disclaimer": "synthetic"}
    packs, static, runs = _m1_server(tmp_path, {"m1-demo-1": audit})

    with running_server(packs_root=packs, static_root=static, runs_root=runs) as base_url:
        status, _, body = request(base_url, "/api/m1/runs/m1-demo-1")

    assert status == 200
    assert json.loads(body) == audit


def test_m1_run_unknown_id_returns_404(tmp_path: Path) -> None:
    packs, static, runs = _m1_server(tmp_path, {})

    with running_server(packs_root=packs, static_root=static, runs_root=runs) as base_url:
        status, _, body = request(base_url, "/api/m1/runs/unknown")

    assert status == 404
    assert json.loads(body)["error"]["code"] == "run_not_found"


def test_m1_run_rejects_path_traversal(tmp_path: Path) -> None:
    packs, static, runs = _m1_server(tmp_path, {})
    (tmp_path / "provenance_audit.json").write_text('{"escaped":true}', encoding="utf-8")

    with running_server(packs_root=packs, static_root=static, runs_root=runs) as base_url:
        status, _, body = request(base_url, "/api/m1/runs/%2E%2E%2F")

    assert status == 404
    assert json.loads(body)["error"]["code"] == "run_not_found"


def test_query_validation_rankings_and_observation_stubs(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")
    payload = UserQueryRevision.from_content(QUERY_CONTENT).to_payload()

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = request(
            base_url,
            "/api/queries",
            method="POST",
            body=json.dumps(payload).encode(),
            content_type="application/json",
        )
        assert status == 201
        assert json.loads(body) == payload

        status, _, body = request(base_url, "/api/rankings/query-1")
        assert status == 200
        assert json.loads(body) == {
            "query_id": "query-1",
            "status": "pending_integration",
            "rankings": [],
        }

        status, _, body = request(base_url, "/api/evidence/observations")
        assert status == 200
        assert json.loads(body) == {"observations": []}


@pytest.mark.parametrize(
    "mutation, message",
    [
        (
            lambda payload: payload["objectives"][0].update(
                {"objective_ref": {"id": "unregistered", "version": "1", "sha256": HASH}}
            ),
            "pinned registry objective",
        ),
        (
            lambda payload: payload["objectives"].append(
                {**payload["objectives"][0], "term_id": "duplicate"}
            ),
            "duplicate objective",
        ),
        (
            lambda payload: payload["user_constraints"].append(
                {
                    "constraint_id": PLATFORM_CONSTRAINT_IDS["synthesizability"],
                    "owner": "USER",
                    "metric_ref": "metric.synthesizability_probability",
                    "operator": "GTE",
                    "threshold": {"value": "0.80", "unit": "probability"},
                    "policy_ref": None,
                }
            ),
            "shadow platform",
        ),
        (
            lambda payload: payload["user_constraints"].append(
                {
                    "constraint_id": "user.synthesizability",
                    "owner": "USER",
                    "metric_ref": "metric.synthesizability_probability",
                    "operator": "GTE",
                    "threshold": {"value": "0.60", "unit": "probability"},
                    "policy_ref": None,
                }
            ),
            "at least as strict",
        ),
    ],
)
def test_query_http_admission_rejects_d1_policy_violations(
    tmp_path: Path, mutation, message: str
) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")
    payload = UserQueryRevision.from_content(QUERY_CONTENT).to_payload()
    mutation(payload)
    # Re-form the content-addressed revision so this exercises policy admission,
    # not structural revision-ID verification.
    payload = UserQueryRevision.from_content(
        {key: value for key, value in payload.items() if key != "revision_id"}
    ).to_payload()

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = request(
            base_url,
            "/api/queries",
            method="POST",
            body=json.dumps(payload).encode(),
            content_type="application/json",
        )

    assert status == 422
    assert message in json.loads(body)["error"]["message"]


def test_malformed_payload_is_structured_4xx_without_traceback(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, headers, body = request(
            base_url,
            "/api/queries",
            method="POST",
            body=b'{"query_id":',
            content_type="application/json",
        )

    assert status == 400
    assert headers["Content-Type"].startswith("application/json")
    decoded = json.loads(body)
    assert decoded["error"]["code"] == "invalid_json"
    assert "Traceback" not in decoded["error"]["message"]


def test_contract_error_and_unknown_query_are_structured_4xx(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = request(
            base_url,
            "/api/queries",
            method="POST",
            body=b"{}",
            content_type="application/json",
        )
        assert status == 422
        assert json.loads(body)["error"]["code"] == "invalid_query"

        status, _, body = request(base_url, "/api/rankings/missing")
        assert status == 404
        assert json.loads(body)["error"]["code"] == "query_not_found"


def test_unexpected_handler_exception_is_logged_with_generic_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")

    def explode(_handler: RequestHandler) -> None:
        raise RuntimeError("diagnostic sentinel")

    monkeypatch.setattr(RequestHandler, "_get", explode)
    with caplog.at_level("ERROR", logger="src.webserver.server"):
        with running_server(packs_root=tmp_path, static_root=static) as base_url:
            status, _, body = request(base_url, "/api/health")

    assert status == 500
    assert json.loads(body)["error"] == {
        "code": "internal_error",
        "message": "request failed",
    }
    assert "diagnostic sentinel" in caplog.text


def test_static_root_absence_returns_clear_503(tmp_path: Path) -> None:
    packs = tmp_path / "packs"
    packs.mkdir()

    with running_server(packs_root=packs, static_root=tmp_path / "missing") as base_url:
        status, _, body = request(base_url, "/")

    assert status == 503
    error = json.loads(body)["error"]
    assert error["code"] == "static_files_unavailable"
    assert "web/ui/dist" in error["message"]


def test_data_directory_resolution_uses_flag_env_default_precedence(tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    environmental = tmp_path / "environmental"

    assert resolve_data_directory(configured, {DATA_DIR_ENV: str(environmental)}) == configured.resolve()
    assert resolve_data_directory(None, {DATA_DIR_ENV: str(environmental)}) == environmental.resolve()
    assert resolve_data_directory(None, {}) == Path("/data")


def test_startup_rejects_missing_or_unwritable_data_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(DataDirectoryError, match="does not exist"):
        create_server(port=0, data_dir=missing)

    unwritable = tmp_path / "unwritable"
    unwritable.mkdir()
    unwritable.chmod(0o555)
    try:
        with pytest.raises(DataDirectoryError, match="not writable"):
            create_server(port=0, data_dir=unwritable)
    finally:
        unwritable.chmod(0o755)


def test_container_mount_state_is_injectable_and_exposed_in_health(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")

    with caplog.at_level("WARNING", logger="src.webserver.server"):
        server = create_server(
            port=0,
            packs_root=tmp_path,
            static_root=static,
            data_dir=tmp_path,
            is_container=lambda: True,
            is_mount_point=lambda _path: False,
        )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        status, _, body = request(f"http://{host}:{port}", "/api/health")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status == 200
    assert json.loads(body)["data_volume_mounted"] is False
    assert "will not persist" in caplog.text

    mounted = create_server(
        port=0,
        packs_root=tmp_path,
        static_root=static,
        data_dir=tmp_path,
        is_container=lambda: True,
        is_mount_point=lambda _path: True,
    )
    try:
        assert mounted.data_volume_mounted is True
    finally:
        mounted.server_close()


def test_non_loopback_bind_requires_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(NonLoopbackBindError):
        create_server(
            host="0.0.0.0",
            port=0,
            packs_root=tmp_path,
            static_root=tmp_path,
        )


def _muni_server_paths(tmp_path: Path) -> tuple[Path, Path]:
    packs = tmp_path / "packs"
    packs.mkdir()
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")
    return packs, static


def _post_json(base_url: str, path: str, payload: object) -> tuple[int, dict[str, str], bytes]:
    return request(
        base_url,
        path,
        method="POST",
        body=json.dumps(payload).encode(),
        content_type="application/json",
    )


def test_muni_study_creation_happy_path(tmp_path: Path) -> None:
    packs, static = _muni_server_paths(tmp_path)

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = _post_json(base_url, "/api/muni/studies", {
            "target_crop": "cropA",
            "target_pathogen": "pathogenX",
            "purpose": "contained-lab reagent",
        })
        created = json.loads(body)
        assert status == 201
        assert created["target_crop"] == "cropA"
        assert created["target_pathogen"] == "pathogenX"

        status, _, body = request(base_url, f"/api/muni/studies/{created['study_id']}")
        assert status == 200
        assert json.loads(body) == created


def test_muni_corrupted_study_returns_data_integrity_error(tmp_path: Path) -> None:
    packs, static = _muni_server_paths(tmp_path)
    study_id = "muni_study_" + "0" * 32
    studies = tmp_path / "muni" / "studies"
    studies.mkdir(parents=True)
    (studies / f"{study_id}.json").write_text("{not valid JSON", encoding="utf-8")

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, headers, body = request(base_url, f"/api/muni/studies/{study_id}")

    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body) == {
        "error": {
            "code": "data_integrity_error",
            "message": "persisted MUNI data failed integrity validation",
        }
    }
    assert b"Traceback" not in body


def test_muni_corrupted_study_in_list_returns_data_integrity_error(tmp_path: Path) -> None:
    packs, static = _muni_server_paths(tmp_path)
    study_id = "muni_study_" + "1" * 32
    studies = tmp_path / "muni" / "studies"
    studies.mkdir(parents=True)
    (studies / f"{study_id}.json").write_text("{not valid JSON", encoding="utf-8")

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, headers, body = request(base_url, "/api/muni/studies")

    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body) == {
        "error": {
            "code": "data_integrity_error",
            "message": "persisted MUNI data failed integrity validation",
        }
    }
    assert b"Traceback" not in body


def test_muni_corrupted_candidate_store_returns_data_integrity_error(
    tmp_path: Path,
) -> None:
    packs, static = _muni_server_paths(tmp_path)

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = _post_json(base_url, "/api/muni/studies", {
            "target_crop": "cropA",
            "target_pathogen": "pathogenX",
            "purpose": "contained-lab reagent",
        })
        assert status == 201
        study_id = json.loads(body)["study_id"]
        candidate_store = (
            tmp_path
            / "muni"
            / "studies"
            / f"{study_id}.compound-candidate-sets.json"
        )
        candidate_store.write_text("[null]", encoding="utf-8")

        responses = [request(
            base_url, f"/api/muni/studies/{study_id}/candidates"
        )]
        responses.append(_post_json(
            base_url,
            "/api/muni/candidates/muni_candidate_set_" + "3" * 32 + "/review",
            {"reviewer": "researcher-1", "decision": "APPROVED", "note": "none"},
        ))

    for status, headers, body in responses:
        assert status == 500
        assert headers["Content-Type"].startswith("application/json")
        assert json.loads(body) == {
            "error": {
                "code": "data_integrity_error",
                "message": "persisted MUNI data failed integrity validation",
            }
        }
        assert b"Traceback" not in body


def test_muni_corrupted_review_lookup_returns_data_integrity_error(
    tmp_path: Path,
) -> None:
    packs, static = _muni_server_paths(tmp_path)
    studies = tmp_path / "muni" / "studies"
    studies.mkdir(parents=True)
    (studies / ("muni_study_" + "4" * 32 + ".reviews.json")).write_text(
        "[null]", encoding="utf-8"
    )

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, headers, body = request(
            base_url,
            "/api/muni/reviews/muni_review_" + "4" * 32 + "/handoff",
            method="POST",
            body=b"",
        )

    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body)["error"]["code"] == "data_integrity_error"
    assert b"Traceback" not in body


@pytest.mark.parametrize(
    "store_suffix, route, json_body",
    [
        ("collection-jobs", "collection", None),
        ("collected-data", "workflows/diagnostic/run", None),
        ("collected-data", "workflows/screening/run", {}),
    ],
)
def test_muni_workflow_routes_map_corrupted_persisted_inputs_to_integrity_error(
    tmp_path: Path,
    store_suffix: str,
    route: str,
    json_body: object | None,
) -> None:
    packs, static = _muni_server_paths(tmp_path)

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = _post_json(base_url, "/api/muni/studies", {
            "target_crop": "cropA",
            "target_pathogen": "pathogenX",
            "purpose": "contained-lab reagent",
        })
        assert status == 201
        study_id = json.loads(body)["study_id"]
        store = tmp_path / "muni" / "studies" / f"{study_id}.{store_suffix}.json"
        store.write_text("[{}]", encoding="utf-8")

        path = f"/api/muni/studies/{study_id}/{route}"
        if json_body is None:
            status, headers, body = request(
                base_url, path, method="POST", body=b""
            )
        else:
            status, headers, body = _post_json(base_url, path, json_body)

    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body)["error"]["code"] == "data_integrity_error"
    assert b"Traceback" not in body


def test_muni_absent_persisted_records_keep_route_specific_responses(
    tmp_path: Path,
) -> None:
    packs, static = _muni_server_paths(tmp_path)
    absent_study = "muni_study_" + "2" * 32
    absent_set = "muni_candidate_set_" + "2" * 32
    absent_review = "muni_review_" + "2" * 32

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = request(base_url, "/api/muni/studies")
        assert status == 200
        assert json.loads(body) == {"studies": []}

        status, _, body = request(
            base_url, f"/api/muni/studies/{absent_study}/candidates"
        )
        assert status == 404
        assert json.loads(body)["error"]["code"] == "study_not_found"

        status, _, body = _post_json(
            base_url,
            f"/api/muni/candidates/{absent_set}/review",
            {"reviewer": "researcher-1", "decision": "APPROVED", "note": "none"},
        )
        assert status == 404
        assert json.loads(body)["error"]["code"] == "candidate_not_found"

        status, _, body = request(
            base_url,
            f"/api/muni/reviews/{absent_review}/handoff",
            method="POST",
            body=b"",
        )
        assert status == 404
        assert json.loads(body)["error"]["code"] == "review_not_found"


def test_muni_empty_object_review_store_returns_data_integrity_error(
    tmp_path: Path,
) -> None:
    packs, static = _muni_server_paths(tmp_path)
    studies = tmp_path / "muni" / "studies"
    studies.mkdir(parents=True)
    (studies / ("muni_study_" + "6" * 32 + ".reviews.json")).write_text(
        "{}", encoding="utf-8"
    )

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, headers, body = request(
            base_url,
            "/api/muni/reviews/muni_review_" + "6" * 32 + "/handoff",
            method="POST",
            body=b"",
        )

    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body)["error"]["code"] == "data_integrity_error"
    assert b"Traceback" not in body


def test_muni_empty_object_review_store_on_review_append_returns_data_integrity_error(
    tmp_path: Path,
) -> None:
    packs, static = _muni_server_paths(tmp_path)

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = _post_json(base_url, "/api/muni/studies", {
            "target_crop": "cropA",
            "target_pathogen": "pathogenX",
            "purpose": "contained-lab reagent",
        })
        assert status == 201
        study_id = json.loads(body)["study_id"]

        status, _, _ = request(
            base_url,
            f"/api/muni/studies/{study_id}/collection",
            method="POST",
            body=b"",
        )
        assert status == 200
        status, _, body = request(
            base_url,
            f"/api/muni/studies/{study_id}/workflows/diagnostic/run",
            method="POST",
            body=b"",
        )
        assert status == 200
        set_id = json.loads(body)["set_id"]

        review_store = tmp_path / "muni" / "studies" / f"{study_id}.reviews.json"
        review_store.write_text("{}", encoding="utf-8")

        status, headers, body = _post_json(
            base_url,
            f"/api/muni/candidates/{set_id}/review",
            {"reviewer": "researcher-1", "decision": "APPROVED", "note": "none"},
        )

    assert status == 500
    assert headers["Content-Type"].startswith("application/json")
    assert json.loads(body)["error"]["code"] == "data_integrity_error"
    assert b"Traceback" not in body


def test_muni_empty_array_review_store_keeps_review_not_found(
    tmp_path: Path,
) -> None:
    packs, static = _muni_server_paths(tmp_path)
    studies = tmp_path / "muni" / "studies"
    studies.mkdir(parents=True)
    (studies / ("muni_study_" + "7" * 32 + ".reviews.json")).write_text(
        "[]", encoding="utf-8"
    )

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = request(
            base_url,
            "/api/muni/reviews/muni_review_" + "7" * 32 + "/handoff",
            method="POST",
            body=b"",
        )

    assert status == 404
    assert json.loads(body)["error"]["code"] == "review_not_found"


def test_muni_malformed_study_and_unknown_id_are_structured_4xx(tmp_path: Path) -> None:
    packs, static = _muni_server_paths(tmp_path)

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, headers, body = _post_json(
            base_url, "/api/muni/studies", {"target_crop": "cropA"}
        )
        assert status == 422
        assert headers["Content-Type"].startswith("application/json")
        assert json.loads(body)["error"]["code"] == "invalid_study"

        status, _, body = request(base_url, "/api/muni/studies/not-a-study")
        assert status == 404
        assert json.loads(body)["error"]["code"] == "study_not_found"


def test_muni_workflow_routes_are_independent_and_no_combined_route_exists() -> None:
    assert ("POST", "/api/muni/studies/{study_id}/workflows/diagnostic/run") in API_ROUTE_TABLE
    assert ("POST", "/api/muni/studies/{study_id}/workflows/screening/run") in API_ROUTE_TABLE
    assert all("combined" not in path and "{kind}" not in path for _, path in API_ROUTE_TABLE)


def test_muni_handoff_on_non_approved_review_is_structured_4xx(tmp_path: Path) -> None:
    packs, static = _muni_server_paths(tmp_path)

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = _post_json(base_url, "/api/muni/studies", {
            "target_crop": "cropA",
            "target_pathogen": "pathogenX",
            "purpose": "contained-lab reagent",
        })
        study_id = json.loads(body)["study_id"]
        assert status == 201

        status, _, _ = request(
            base_url, f"/api/muni/studies/{study_id}/collection", method="POST", body=b""
        )
        assert status == 200
        status, _, body = request(
            base_url,
            f"/api/muni/studies/{study_id}/workflows/diagnostic/run",
            method="POST",
            body=b"",
        )
        assert status == 200
        set_id = json.loads(body)["set_id"]

        status, _, body = _post_json(base_url, f"/api/muni/candidates/{set_id}/review", {
            "reviewer": "researcher-1",
            "decision": "REJECTED",
            "note": "requires additional evidence",
        })
        assert status == 201
        review_id = json.loads(body)["review_id"]

        status, headers, body = request(
            base_url, f"/api/muni/reviews/{review_id}/handoff", method="POST", body=b""
        )
        assert status == 409
        assert headers["Content-Type"].startswith("application/json")
        assert json.loads(body)["error"]["code"] == "handoff_not_allowed"


def test_muni_screening_listing_approved_review_and_handoff_over_http(
    tmp_path: Path,
) -> None:
    packs, static = _muni_server_paths(tmp_path)

    with running_server(packs_root=packs, static_root=static) as base_url:
        status, _, body = _post_json(base_url, "/api/muni/studies", {
            "target_crop": "synthetic-crop-http",
            "target_pathogen": "synthetic-pathogen-http",
            "purpose": "crop coating agent",
        })
        assert status == 201
        study_id = json.loads(body)["study_id"]

        status, _, body = request(
            base_url,
            f"/api/muni/studies/{study_id}/collection",
            method="POST",
            body=b"",
        )
        assert status == 200
        assert {job["status"] for job in json.loads(body)["jobs"]} == {
            "SUCCEEDED",
            "SKIPPED",
        }

        status, _, body = _post_json(
            base_url,
            f"/api/muni/studies/{study_id}/workflows/screening/run",
            {"purpose": "crop coating agent"},
        )
        assert status == 200
        screening = json.loads(body)
        assert screening["kind"] == "COMPOUND_SCREENING"
        assert screening["count"] >= 2
        assert all(item["disposition"] == "RANKED" for item in screening["items"])
        response_text = body.decode("utf-8")
        for constraint in (
            "crop_phytotoxicity",
            "soil_beneficial_microbe",
            "handler_exposure",
            "synthesizability",
        ):
            assert constraint in response_text

        candidate_store = (
            tmp_path
            / "muni"
            / "studies"
            / f"{study_id}.compound-candidate-sets.json"
        )
        persisted_sets = json.loads(candidate_store.read_text(encoding="utf-8"))
        assert any(item["set_id"] == screening["set_id"] for item in persisted_sets)

        status, _, body = request(
            base_url, f"/api/muni/studies/{study_id}/candidates"
        )
        assert status == 200
        listed = next(
            item
            for item in json.loads(body)["candidate_sets"]
            if item["set_id"] == screening["set_id"]
        )
        assert listed["ranked"]
        assert listed["excluded"]
        assert listed["abstained"] == []
        assert all(item["disposition"] == "RANKED" for item in listed["ranked"])
        assert all(item["disposition"] == "EXCLUDED" for item in listed["excluded"])

        status, _, body = _post_json(
            base_url,
            f"/api/muni/candidates/{screening['set_id']}/review",
            {
                "reviewer": "synthetic-http-reviewer",
                "decision": "APPROVED",
                "note": "Approved for synthetic HTTP handoff verification.",
            },
        )
        assert status == 201
        review = json.loads(body)
        assert review["decision"] == "APPROVED"
        review_store = tmp_path / "muni" / "studies" / f"{study_id}.reviews.json"
        persisted_reviews = json.loads(review_store.read_text(encoding="utf-8"))
        assert any(
            item["review_id"] == review["review_id"]
            and item["decision"] == "APPROVED"
            for item in persisted_reviews
        )

        status, _, body = request(
            base_url,
            f"/api/muni/reviews/{review['review_id']}/handoff",
            method="POST",
            body=b"",
        )
        assert status == 201
        handoff = json.loads(body)
        assert handoff["review_ref"] == review["review_id"]
        assert len(handoff["artifact_paths"]) == 2
        artifact_paths = [Path(path) for path in handoff["artifact_paths"]]
        assert all(path.is_file() for path in artifact_paths)
        handoff_payload = json.loads(artifact_paths[0].read_text(encoding="utf-8"))
        assert handoff_payload["review"]["review_id"] == review["review_id"]
        assert handoff_payload["candidate_set"]["set_id"] == screening["set_id"]
        assert handoff_payload["study"]["study_id"] == study_id


def test_runtime_status_command_has_http_compatibility_shape(tmp_path: Path) -> None:
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("app", encoding="utf-8")

    with running_server(packs_root=tmp_path, static_root=static) as base_url:
        status, _, body = request(
            base_url,
            "/api/commands/pipeline_runtime_status",
            method="POST",
            body=b"{}",
            content_type="application/json",
        )

    assert status == 200
    assert json.loads(body) == {"running": False, "buffered_event_count": 0}
