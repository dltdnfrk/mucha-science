"""Local HTTP API and static-file server for the Mucha Science browser UI."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
import json
import logging
import mimetypes
import os
from pathlib import Path, PurePosixPath
import signal
import stat
from threading import Lock
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import unquote, urlsplit

from src.objectives.validation import validate_query_revision
from src.packs_loader import PackLoadError, discover_packs, load_pack
from src.pipeline.scientific_contracts import ContractError
from src.platform_contracts import UserQueryRevision

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_DATA_DIR = Path("/data")
DATA_DIR_ENV = "MUCHA_SCIENCE_DATA_DIR"
MAX_REQUEST_BYTES = 1_048_576
_LOGGER = logging.getLogger(__name__)


class NonLoopbackBindError(ValueError):
    """Raised when a network-visible bind wasn't explicitly authorized."""


class DataDirectoryError(ValueError):
    """Raised when the configured persistent data directory is unusable."""


def resolve_data_directory(
    configured: str | Path | None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve data storage in flag, environment, default precedence order."""
    environment = os.environ if environ is None else environ
    value = configured if configured is not None else environment.get(DATA_DIR_ENV, DEFAULT_DATA_DIR)
    return Path(value).expanduser().resolve()


def _running_in_container() -> bool:
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods"))


def validate_data_directory(
    data_dir: str | Path,
    *,
    is_container: Callable[[], bool] = _running_in_container,
    is_mount_point: Callable[[str | Path], bool] = os.path.ismount,
) -> tuple[Path, bool]:
    """Fail closed on unusable storage and report whether persistence is mounted."""
    directory = Path(data_dir).expanduser().resolve()
    if not directory.is_dir():
        raise DataDirectoryError(f"data directory does not exist: {directory}")
    try:
        mode = directory.stat().st_mode
    except OSError as exc:
        raise DataDirectoryError(f"data directory is not accessible: {directory}") from exc
    write_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    if not mode & write_bits or not os.access(directory, os.W_OK):
        raise DataDirectoryError(f"data directory is not writable: {directory}")
    mounted = bool(is_mount_point(directory))
    if is_container() and not mounted:
        _LOGGER.warning(
            "data directory is ephemeral container storage and will not persist: %s",
            directory,
        )
    return directory, mounted


class InMemoryPlatform:
    """Process-local persistence until platform stores and combiners are wired."""

    def __init__(self, packs_root: Path, runs_root: Path) -> None:
        self._packs_root = packs_root
        self._runs_root = runs_root
        self._queries: dict[str, dict[str, object]] = {}
        self._lock = Lock()

    def list_packs(self) -> list[dict[str, object]]:
        return [asdict(load_pack(path)) for path in discover_packs(self._packs_root)]

    def submit_query(self, payload: Mapping[str, object]) -> dict[str, object]:
        revision = validate_query_revision(UserQueryRevision.from_payload(payload))
        result = revision.to_payload()
        with self._lock:
            self._queries[revision.query_id] = result
        return result

    def rankings(self, query_id: str) -> dict[str, object] | None:
        with self._lock:
            exists = query_id in self._queries
        if not exists:
            return None
        # TODO(nie:integration): invoke the objectives combiner and persist its ranking.
        return {
            "query_id": query_id,
            "status": "pending_integration",
            "rankings": [],
        }

    def observations(self) -> list[dict[str, object]]:
        # TODO(nie:integration): read AssayObservation records from the evidence store.
        return []

    def list_m1_runs(self) -> list[str]:
        try:
            children = tuple(self._runs_root.iterdir())
        except OSError:
            return []
        return sorted(
            child.name
            for child in children
            if child.is_dir() and self.m1_run(child.name) is not None
        )

    def m1_run(self, run_id: str) -> dict[str, object] | None:
        if not run_id or PurePosixPath(run_id).name != run_id:
            return None
        root = self._runs_root.resolve()
        audit_path = self._runs_root / run_id / "provenance_audit.json"
        try:
            audit_path.resolve(strict=True).relative_to(root)
            payload = json.loads(audit_path.read_bytes())
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None


class MuchaHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        platform: InMemoryPlatform,
        static_root: Path,
        data_dir: Path,
        data_volume_mounted: bool,
    ) -> None:
        self.platform = platform
        self.static_root = static_root
        self.data_dir = data_dir
        self.data_volume_mounted = data_volume_mounted
        super().__init__(server_address, handler_class)


class RequestHandler(BaseHTTPRequestHandler):
    server: MuchaHTTPServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            self._get()
        except Exception:
            self._internal_error()

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        try:
            self._post()
        except Exception:
            self._internal_error()

    def _internal_error(self) -> None:
        _LOGGER.exception("unhandled HTTP request failure")
        try:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "request failed")
        except (BrokenPipeError, ConnectionResetError):
            _LOGGER.info("client disconnected before the error response was written")

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Allow", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _get(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._json(HTTPStatus.OK, {
                "status": "ok",
                "data_volume_mounted": self.server.data_volume_mounted,
            })
            return
        if path == "/api/packs":
            try:
                packs = self.server.platform.list_packs()
            except PackLoadError as exc:
                self._error(HTTPStatus.SERVICE_UNAVAILABLE, "packs_unavailable", str(exc))
                return
            self._json(HTTPStatus.OK, {"packs": packs})
            return
        if path.startswith("/api/rankings/"):
            query_id = unquote(path.removeprefix("/api/rankings/"))
            if not query_id or "/" in query_id:
                self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")
                return
            ranking = self.server.platform.rankings(query_id)
            if ranking is None:
                self._error(HTTPStatus.NOT_FOUND, "query_not_found", "query does not exist")
                return
            self._json(HTTPStatus.OK, ranking)
            return
        if path == "/api/evidence/observations":
            self._json(HTTPStatus.OK, {"observations": self.server.platform.observations()})
            return
        if path == "/api/m1/runs":
            self._json(HTTPStatus.OK, {"runs": self.server.platform.list_m1_runs()})
            return
        if path.startswith("/api/m1/runs/"):
            run_id = unquote(path.removeprefix("/api/m1/runs/"))
            audit = self.server.platform.m1_run(run_id)
            if audit is None:
                self._error(HTTPStatus.NOT_FOUND, "run_not_found", "M1 run does not exist")
                return
            self._json(HTTPStatus.OK, audit)
            return
        if path.startswith("/api/"):
            self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")
            return
        self._serve_static(path)

    def _post(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/queries":
            payload = self._json_body()
            if payload is None:
                return
            try:
                query = self.server.platform.submit_query(payload)
            except (ContractError, TypeError, ValueError) as exc:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_query", str(exc))
                return
            self._json(HTTPStatus.CREATED, query)
            return
        if path.startswith("/api/commands/"):
            command = unquote(path.removeprefix("/api/commands/"))
            payload = self._json_body()
            if payload is None:
                return
            self._command(command, payload)
            return
        self._error(HTTPStatus.NOT_FOUND, "not_found", "API route not found")

    def _command(self, command: str, payload: Mapping[str, object]) -> None:
        if command == "pipeline_runtime_status":
            if payload:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_command", "request body must be empty")
                return
            # TODO(nie:integration): adapt PipelineRuntime once HTTP event replay is available.
            self._json(HTTPStatus.OK, {"running": False, "buffered_event_count": 0})
            return
        if command == "get_buffered_events":
            self._json(HTTPStatus.OK, [])
            return
        if command == "check_cli_status":
            self._json(HTTPStatus.OK, [])
            return
        known = {
            "start_pipeline", "cancel_pipeline", "send_action", "check_cli_smoke",
            "open_cli_auth", "start_scientific_sidecar", "stop_scientific_sidecar",
            "write_envelope",
        }
        if command in known:
            self._error(
                HTTPStatus.NOT_IMPLEMENTED,
                "command_not_integrated",
                f"command is not integrated with the local HTTP runtime: {command}",
            )
            return
        self._error(HTTPStatus.NOT_FOUND, "command_not_found", "unknown command")

    def _json_body(self) -> Mapping[str, object] | None:
        media_type = self.headers.get("Content-Type", "").partition(";")[0].strip().lower()
        if media_type != "application/json":
            self._error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "unsupported_media_type",
                "Content-Type must be application/json",
            )
            return None
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else -1
        except ValueError:
            length = -1
        if length < 0:
            self._error(HTTPStatus.LENGTH_REQUIRED, "content_length_required", "Content-Length is required")
            return None
        if length > MAX_REQUEST_BYTES:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "payload_too_large", "request body is too large")
            return None
        raw = self.rfile.read(length)
        try:
            value: Any = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "invalid_json", "request body is not valid JSON")
            return None
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_payload", "request body must be a JSON object")
            return None
        return value

    def _serve_static(self, request_path: str) -> None:
        root = self.server.static_root
        index = root / "index.html"
        if not root.is_dir() or not index.is_file():
            self._error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "static_files_unavailable",
                "built UI is unavailable; expected web/ui/dist/index.html",
            )
            return
        decoded = unquote(request_path)
        relative = PurePosixPath(decoded.lstrip("/"))
        if any(part in {"", ".", ".."} for part in relative.parts):
            self._error(HTTPStatus.NOT_FOUND, "not_found", "static file not found")
            return
        candidate = root.joinpath(*relative.parts) if relative.parts else index
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            self._error(HTTPStatus.NOT_FOUND, "not_found", "static file not found")
            return
        if not resolved.is_file():
            # Vite's client-side routes need the application shell.
            resolved = index
        try:
            body = resolved.read_bytes()
        except OSError:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "static file not found")
            return
        content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, body, content_type)

    def _json(self, status: HTTPStatus, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: HTTPStatus, code: str, message: str) -> None:
        self._json(status, {"error": {"code": code, "message": message}})

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "public, max-age=0")
        self.end_headers()
        self.wfile.write(body)


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def create_server(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    packs_root: str | Path = Path("packs"),
    runs_root: str | Path = Path("runs"),
    static_root: str | Path = Path("web/ui/dist"),
    data_dir: str | Path = Path("."),
    allow_non_loopback: bool = False,
    is_container: Callable[[], bool] = _running_in_container,
    is_mount_point: Callable[[str | Path], bool] = os.path.ismount,
) -> MuchaHTTPServer:
    if not _is_loopback(host) and not allow_non_loopback:
        raise NonLoopbackBindError(
            f"non-loopback host requires --allow-non-loopback: {host}"
        )
    resolved_data_dir, data_volume_mounted = validate_data_directory(
        data_dir,
        is_container=is_container,
        is_mount_point=is_mount_point,
    )
    platform = InMemoryPlatform(Path(packs_root), Path(runs_root))
    return MuchaHTTPServer(
        (host, port),
        RequestHandler,
        platform=platform,
        static_root=Path(static_root),
        data_dir=resolved_data_dir,
        data_volume_mounted=data_volume_mounted,
    )


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be in range 0..65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mucha-science-webserver")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=_port)
    parser.add_argument("--packs-root", type=Path, default=Path("packs"))
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--static-root", type=Path, default=Path("web/ui/dist"))
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help=f"persistent data directory (env: {DATA_DIR_ENV}; default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="explicitly permit a network-visible bind (there is no authentication)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = build_parser().parse_args(argv)
    try:
        data_dir = resolve_data_directory(args.data_dir)
        server = create_server(
            host=args.host,
            port=args.port,
            packs_root=args.packs_root,
            runs_root=args.runs_root,
            static_root=args.static_root,
            data_dir=data_dir,
            allow_non_loopback=args.allow_non_loopback,
        )
    except NonLoopbackBindError as exc:
        build_parser().error(str(exc))
    except DataDirectoryError as exc:
        _LOGGER.error("startup refused: %s", exc)
        return 1
    actual_host, actual_port = server.server_address
    print(
        json.dumps({
            "event": "mucha_science_web.ready",
            "host": actual_host,
            "port": actual_port,
            "url": f"http://{actual_host}:{actual_port}",
        }, separators=(",", ":")),
        flush=True,
    )
    terminated = False

    def stop_on_terminate(_signum: int, _frame: object) -> None:
        nonlocal terminated
        terminated = True
        raise KeyboardInterrupt

    previous_sigterm = signal.signal(signal.SIGTERM, stop_on_terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0 if terminated else 130
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)
        server.server_close()
    return 0
