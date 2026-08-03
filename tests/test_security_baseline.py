from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from src.muchanipo.web.websocket_server import (
    ALLOWED_ORIGINS,
    BINARY_CLOSE_CODE,
    DEFAULT_HOST,
    MAX_MESSAGE_SIZE,
)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def test_browser_origin_allowlist_is_loopback_only() -> None:
    # Given the pipeline socket owns mutable scientific-cycle state
    browser_origins = [origin for origin in ALLOWED_ORIGINS if origin is not None]

    # Then every accepted browser origin stays on this machine
    assert browser_origins
    for origin in browser_origins:
        assert "*" not in origin, origin
        assert urlsplit(origin).hostname in LOOPBACK_HOSTS, origin


def test_pipeline_server_defaults_to_a_loopback_bind() -> None:
    assert DEFAULT_HOST == "127.0.0.1"


def test_transport_caps_message_size_and_rejects_binary_frames() -> None:
    assert MAX_MESSAGE_SIZE == 1_048_576
    assert BINARY_CLOSE_CODE == 1003


def test_local_web_launcher_binds_the_ui_to_loopback() -> None:
    launcher = Path("scripts/run-local-web.sh").read_text(encoding="utf-8")

    assert "--host 127.0.0.1" in launcher
    assert "0.0.0.0" not in launcher


def test_security_baseline_document_describes_the_current_surface() -> None:
    doc = Path("docs/security-baseline.md").read_text(encoding="utf-8")

    assert "# Mucha Science Security Baseline" in doc
    assert "Browser origin allowlist" in doc
    assert "Loopback-only dev server" in doc
    assert "Frame and message limits" in doc
    assert "No Express/Helmet server" in doc
    assert "app/muchanipo-tauri" not in doc
