"""Pure trust boundary for source data shown to council models."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Mapping, Sequence

from src.evidence.artifact import EvidenceRef


MAX_SOURCE_RECORDS = 8
MAX_EVIDENCE_ID_CHARS = 128
MAX_RUN_HASH_CHARS = 128
MAX_SOURCE_KIND_CHARS = 64
MAX_TITLE_CHARS = 256
MAX_LOCATOR_CHARS = 2048
MAX_EXCERPT_CHARS = 1024
MAX_ACCESS_STATUS_CHARS = 64
_CONTROL_ASSIGNMENT = re.compile(
    r"\b(?:provider|model|max_tokens|allowed_tools|budget|file)\s*=\s*"
    r"(?:\[[^\]]*\]|[^\s,;]+)",
    flags=re.IGNORECASE,
)
_FILE_ACTION = re.compile(
    r"\b(?:write|delete|remove|open|execute|run)\s+"
    r"(?:/[^\s,;]+|~\/[^\s,;]+)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SourceProjectionError(ValueError):
    reason: str

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class SourceRecord:
    evidence_id: str
    run_hash: str
    source_kind: str
    title: str
    locator: str
    excerpt: str
    access_status: str


@dataclass(frozen=True, slots=True)
class SourceBoundary:
    records: tuple[SourceRecord, ...]
    run_hash: str
    allowed_evidence_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class StageAdmissionReceipt:
    stage: str
    accepted: bool
    run_hash: str
    evidence_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    unsupported_critical_claim_count: int


RawSource = EvidenceRef | SourceRecord | Mapping[str, object]


def project_source_records(
    raw_records: Sequence[RawSource],
    *,
    run_hash: str | None = None,
) -> SourceBoundary:
    projected: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    existing_hashes: set[str] = set()
    for raw in raw_records:
        values = _project_values(raw)
        evidence_id = values["evidence_id"]
        if not evidence_id or evidence_id in seen_ids:
            continue
        seen_ids.add(evidence_id)
        if values["run_hash"]:
            existing_hashes.add(values["run_hash"])
        projected.append(values)
        if len(projected) == MAX_SOURCE_RECORDS:
            break

    if run_hash is None:
        if len(existing_hashes) > 1:
            raise SourceProjectionError("source records have mixed run hashes")
        run_hash = next(iter(existing_hashes), "") or _source_set_hash(projected)
    bounded_run_hash = _bounded_required(run_hash, MAX_RUN_HASH_CHARS, "run hash")
    if existing_hashes and existing_hashes != {bounded_run_hash}:
        raise SourceProjectionError("source record run hash does not match boundary")

    records = tuple(
        SourceRecord(
            evidence_id=item["evidence_id"],
            run_hash=bounded_run_hash,
            source_kind=item["source_kind"],
            title=item["title"],
            locator=item["locator"],
            excerpt=item["excerpt"],
            access_status=item["access_status"],
        )
        for item in projected
    )
    return SourceBoundary(
        records=records,
        run_hash=bounded_run_hash,
        allowed_evidence_ids=frozenset(record.evidence_id for record in records),
    )


def render_source_records(records: Sequence[SourceRecord]) -> str:
    run_hashes = {record.run_hash for record in records}
    if len(run_hashes) > 1:
        raise SourceProjectionError("source records have mixed run hashes")
    payload = {"records": [asdict(record) for record in records[:MAX_SOURCE_RECORDS]]}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def admit_stage_output(
    raw_output: str,
    *,
    stage: str,
    boundary: SourceBoundary,
) -> StageAdmissionReceipt:
    try:
        payload = json.loads(raw_output, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, SourceProjectionError):
        return _receipt(stage, boundary, (), ("malformed_stage_output",), 0)
    if not isinstance(payload, dict):
        return _receipt(stage, boundary, (), ("malformed_stage_output",), 0)

    reasons: list[str] = []
    output_run_hash = payload.get("run_hash")
    if not isinstance(output_run_hash, str):
        reasons.append("malformed_stage_output")
    elif output_run_hash != boundary.run_hash:
        reasons.append("run_hash_mismatch")

    evidence_ids, malformed_ids = _payload_evidence_ids(payload)
    if malformed_ids:
        reasons.append("malformed_stage_output")
    if any(evidence_id not in boundary.allowed_evidence_ids for evidence_id in evidence_ids):
        reasons.append("unknown_evidence_id")

    unsupported_count, malformed_claims = _unsupported_critical_claims(
        payload,
        boundary.allowed_evidence_ids,
    )
    if malformed_claims:
        reasons.append("malformed_stage_output")
    if unsupported_count:
        reasons.append("unsupported_critical_claim")

    return _receipt(
        stage,
        boundary,
        evidence_ids,
        tuple(dict.fromkeys(reasons)),
        unsupported_count,
    )


def _project_values(raw: RawSource) -> dict[str, str]:
    if isinstance(raw, SourceRecord):
        return asdict(raw)
    if isinstance(raw, EvidenceRef):
        provenance = raw.provenance if isinstance(raw.provenance, Mapping) else {}
        return {
            "evidence_id": _bounded_required(
                raw.id, MAX_EVIDENCE_ID_CHARS, "evidence id"
            ),
            "run_hash": "",
            "source_kind": _bounded_text(
                provenance.get("kind"), MAX_SOURCE_KIND_CHARS, "unknown"
            ),
            "title": _bounded_text(
                _sanitize_untrusted_text(raw.source_title),
                MAX_TITLE_CHARS,
                "untitled source",
            ),
            "locator": _bounded_text(raw.source_url, MAX_LOCATOR_CHARS),
            "excerpt": _bounded_text(
                _sanitize_untrusted_text(raw.quote),
                MAX_EXCERPT_CHARS,
            ),
            "access_status": _bounded_text(
                raw.access_status, MAX_ACCESS_STATUS_CHARS, "available"
            ),
        }

    provenance_value = raw.get("provenance")
    provenance = (
        provenance_value if isinstance(provenance_value, Mapping) else {}
    )
    return {
        "evidence_id": _bounded_required(
            raw.get("evidence_id") or raw.get("id"),
            MAX_EVIDENCE_ID_CHARS,
            "evidence id",
        ),
        "run_hash": _bounded_text(raw.get("run_hash"), MAX_RUN_HASH_CHARS),
        "source_kind": _bounded_text(
            raw.get("source_kind") or raw.get("kind") or provenance.get("kind"),
            MAX_SOURCE_KIND_CHARS,
            "unknown",
        ),
        "title": _bounded_text(
            _sanitize_untrusted_text(raw.get("title") or raw.get("source_title")),
            MAX_TITLE_CHARS,
            "untitled source",
        ),
        "locator": _bounded_text(
            raw.get("locator")
            or raw.get("source_url")
            or raw.get("url")
            or raw.get("doi"),
            MAX_LOCATOR_CHARS,
        ),
        "excerpt": _bounded_text(
            _sanitize_untrusted_text(
                raw.get("excerpt")
                or raw.get("quote")
                or raw.get("abstract")
                or raw.get("snippet")
            ),
            MAX_EXCERPT_CHARS,
        ),
        "access_status": _bounded_text(
            raw.get("access_status"), MAX_ACCESS_STATUS_CHARS, "available"
        ),
    }


def _bounded_required(value: object, limit: int, label: str) -> str:
    bounded = _bounded_text(value, limit)
    if not bounded:
        raise SourceProjectionError(f"{label} must not be empty")
    return bounded


def _bounded_text(value: object, limit: int, default: str = "") -> str:
    text = " ".join(str(value or default).split())
    return text[:limit]


def _sanitize_untrusted_text(value: object) -> str:
    text = str(value or "")
    text = _CONTROL_ASSIGNMENT.sub("[control field removed]", text)
    return _FILE_ACTION.sub("[file action removed]", text)


def _source_set_hash(projected: Sequence[Mapping[str, str]]) -> str:
    material = json.dumps(
        list(projected),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _reject_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SourceProjectionError(f"duplicate stage key: {key}")
        result[key] = value
    return result


def _payload_evidence_ids(
    payload: Mapping[str, object],
) -> tuple[tuple[str, ...], bool]:
    collected: list[str] = []
    malformed = False
    for key in ("evidence_ref_ids", "evidence_ids"):
        values, invalid = _string_ids(payload.get(key))
        collected.extend(values)
        malformed = malformed or invalid
    claims = payload.get("claims")
    if claims is None:
        return tuple(dict.fromkeys(collected)), malformed
    if not isinstance(claims, list):
        return tuple(dict.fromkeys(collected)), True
    for claim in claims:
        if not isinstance(claim, dict):
            malformed = True
            continue
        for key in (
            "supporting_evidence_ids",
            "refuting_evidence_ids",
            "evidence_ref_ids",
        ):
            values, invalid = _string_ids(claim.get(key))
            collected.extend(values)
            malformed = malformed or invalid
    return tuple(dict.fromkeys(collected)), malformed


def _string_ids(value: object) -> tuple[tuple[str, ...], bool]:
    if value is None:
        return (), False
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return (), True
    return tuple(value), len(set(value)) != len(value)


def _unsupported_critical_claims(
    payload: Mapping[str, object],
    allowed_ids: frozenset[str],
) -> tuple[int, bool]:
    declared = payload.get("unsupported_critical_claim_count", 0)
    if isinstance(declared, bool) or not isinstance(declared, int) or declared < 0:
        return 0, True
    unsupported = declared
    claims = payload.get("claims")
    if claims is None:
        return unsupported, False
    if not isinstance(claims, list):
        return unsupported, True
    malformed = False
    for claim in claims:
        if not isinstance(claim, dict):
            malformed = True
            continue
        critical = claim.get("is_critical", False)
        if not isinstance(critical, bool):
            malformed = True
            continue
        if not critical:
            continue
        supporting, invalid = _string_ids(claim.get("supporting_evidence_ids"))
        malformed = malformed or invalid
        if not supporting or not any(
            evidence_id in allowed_ids for evidence_id in supporting
        ):
            unsupported += 1
    return unsupported, malformed


def _receipt(
    stage: str,
    boundary: SourceBoundary,
    evidence_ids: tuple[str, ...],
    reasons: tuple[str, ...],
    unsupported_count: int,
) -> StageAdmissionReceipt:
    return StageAdmissionReceipt(
        stage=stage,
        accepted=not reasons,
        run_hash=boundary.run_hash,
        evidence_ids=evidence_ids,
        reasons=reasons,
        unsupported_critical_claim_count=unsupported_count,
    )
