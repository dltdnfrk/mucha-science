"""Run-owned, reproducible skill outputs exposed as derived evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from src.evidence.artifact import EvidenceRef
from src.evidence.provenance import Provenance


SCHEMA = "mucha-science.skill-artifact.v1"
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDS = 200
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def search(query: str, limit: int = 4) -> list[EvidenceRef]:
    """Load relevant skill receipts from the active execution staging area."""
    artifact_path = _owned_artifact_path()
    if artifact_path is None:
        return []
    try:
        if not artifact_path.is_file() or artifact_path.stat().st_size > MAX_BYTES:
            return []
        lines = artifact_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []

    evidence: list[EvidenceRef] = []
    for line in lines[:MAX_RECORDS]:
        record = _parse_record(line)
        if record is None or not _matches_query(query, record):
            continue
        evidence.append(_to_evidence(record))
        if len(evidence) >= max(1, int(limit)):
            break
    return evidence


def _owned_artifact_path() -> Path | None:
    home = os.getenv("MUCHANIPO_HOME", "").strip()
    run_id = os.getenv("MUCHANIPO_APP_RUN_ID", "").strip()
    generation = os.getenv("MUCHANIPO_EXECUTION_GENERATION", "").strip()
    configured_path = os.getenv("MUCHANIPO_SKILL_ARTIFACTS_PATH", "").strip()
    if not home or not run_id or not generation.isdigit() or not configured_path:
        return None
    try:
        staging = (
            Path(home)
            / "runs"
            / run_id
            / f"generation-{int(generation)}"
            / "staging"
        ).resolve(strict=False)
        artifact_path = Path(configured_path).resolve(strict=False)
        artifact_path.relative_to(staging)
    except (OSError, RuntimeError, ValueError):
        return None
    return artifact_path


def _parse_record(line: str) -> dict[str, str] | None:
    try:
        value = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        return None
    required = (
        "skill_name",
        "skill_version",
        "input_sha256",
        "output_sha256",
        "title",
        "text",
    )
    if any(not isinstance(value.get(key), str) or not value[key].strip() for key in required):
        return None
    if not _SHA256.fullmatch(value["input_sha256"]) or not _SHA256.fullmatch(value["output_sha256"]):
        return None
    source_url = value.get("source_url")
    if source_url is not None:
        source_url = _safe_url(source_url)
        if source_url is None:
            return None
    return {
        key: " ".join(value[key].split())
        for key in required
    } | ({"source_url": source_url} if source_url else {})


def _matches_query(query: str, record: dict[str, str]) -> bool:
    terms = {
        term.casefold()
        for term in re.findall(r"[0-9A-Za-z가-힣_-]{3,}", str(query or ""))
    }
    if not terms:
        return True
    haystack = " ".join(
        record.get(key, "")
        for key in ("skill_name", "title", "text")
    ).casefold()
    return any(term in haystack for term in terms)


def _to_evidence(record: dict[str, str]) -> EvidenceRef:
    digest = hashlib.sha256(
        "|".join(
            (
                record["skill_name"],
                record["skill_version"],
                record["input_sha256"],
                record["output_sha256"],
            )
        ).encode("utf-8")
    ).hexdigest()[:24]
    return EvidenceRef(
        id=f"skill-artifact:{digest}",
        source_url=record.get("source_url"),
        source_title=record["title"],
        quote=record["text"][:1000],
        source_grade="C",
        provenance=Provenance(
            kind="skill_artifact",
            metadata={
                "skill_name": record["skill_name"],
                "skill_version": record["skill_version"],
                "input_sha256": record["input_sha256"],
                "output_sha256": record["output_sha256"],
            },
        ).as_dict(),
        access_status="derived_artifact",
    )


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
