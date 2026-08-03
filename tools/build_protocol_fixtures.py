#!/usr/bin/env python3
"""Build and verify the frozen ai-scientist.v1 protocol byte corpus.

The corpus deliberately contains raw JSON Lines rather than parsed fixtures.  Readers
must hash and parse the checked-in bytes themselves; this script is the sole writer.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "config/protocol/ai-scientist.v1"
MANIFEST = CORPUS / "manifest.json"
UNICODE_VERSION = "15.1.0"
# NFC examples whose decompositions/compositions are stable data from Unicode 15.1.
# Do not use unicodedata here: host Unicode tables are not protocol data.
NORMALIZATION_CORPUS = (
    ("Cafe\u0301", "Café"),
    ("A\u030a", "Å"),
    ("\u212b", "Å"),
    ("\u1100\u1161", "가"),
)
ACTION_NAMES = ("protocol.hello", "cycle.start", "cycle.replay", "cycle.resume", "cycle.continue", "responsibility.question_selection.disposition", "responsibility.safety_ethics_review.disposition", "responsibility.execution_accountability.disposition", "responsibility.exception_interpretation.disposition", "responsibility.novelty_value_judgment.disposition", "responsibility.final_accountability.disposition", "responsibility.disposition.supersede", "proposal.reject", "result.submit", "validation.adjudicate", "export.create", "export.get", "report.render", "cycle.abort", "cycle.ack")
EVENT_NAMES = ("cycle.started", "cycle.continued", "cycle.completed", "responsibility.disposition.recorded", "responsibility.disposition.superseded", "proposal.rejected", "result.recorded", "validation.assessment.recorded", "validation.assessment.transitioned", "export.created", "cycle.aborted")
RESPONSE_NAMES = ("protocol.welcome.response", "command.accepted.response", "cycle.replay.response", "cycle.resume.response", "export.get.response", "report.render.response", "cycle.acknowledged.response")
ERROR_NAMES = ("command.rejected.error", "protocol.invalid.error")


def line(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"



def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def sha256_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def frame_vector(case: str, *, sequence: int, text: str) -> dict[str, Any]:
    cycle_id = "cycle_0123456789abcdef0123456789abcdef"
    event = {
        "causation_id": "message_0123456789abcdef0123456789abcdef",
        "correlation_id": "message_0123456789abcdef0123456789abcdef",
        "cycle_id": cycle_id,
        "extensions": {},
        "idempotency_key": f"fixture-{sequence}",
        "kind": "event",
        "message_id": f"event_{sequence:032x}",
        "name": "cycle.continued",
        "payload": {
            "created_records": [],
            "derived_current_refs": {},
            "note": text,
            "operation": "write.interim",
            "superseded_record_ids": [],
        },
        "protocol": "muchanipo",
        "protocol_version": "ai-scientist.v1",
        "revision": sequence,
        "sequence": sequence,
        "timestamp": "2026-07-19T00:00:00.000000Z",
    }
    frame_id = f"frame_{sequence:032x}"
    preimage = {
        "event": event,
        "frame_id": frame_id,
        "frame_version": 1,
        "record_type": "event",
    }
    frame_hash = sha256_digest(canonical(preimage))
    frame = {**preimage, "frame_hash": frame_hash}
    marker = {
        "event_hash": sha256_digest(canonical(event)),
        "frame_hash": frame_hash,
        "frame_id": frame_id,
        "frame_version": 1,
        "record_type": "commit",
    }
    event_line = canonical(frame) + b"\n"
    marker_line = canonical(marker) + b"\n"
    combined = event_line + marker_line
    return {
        "case": case,
        "combined_bytes_sha256": sha256_digest(combined),
        "event_line_utf8_base64": base64.b64encode(event_line).decode("ascii"),
        "expected_frame_hash": frame_hash,
        "frame_preimage_utf8_base64": base64.b64encode(canonical(preimage)).decode("ascii"),
        "marker_line_utf8_base64": base64.b64encode(marker_line).decode("ascii"),
    }


def corrupted_frame_vectors() -> list[dict[str, Any]]:
    first = frame_vector("event-frame-genesis", sequence=1, text="genesis")
    second = frame_vector("event-frame-non-ascii", sequence=2, text="가설 Café")
    ordered = frame_vector("frame-hash-member-order", sequence=3, text="member order")
    event_line = base64.b64decode(first["event_line_utf8_base64"])
    marker_line = base64.b64decode(first["marker_line_utf8_base64"])
    marker = json.loads(marker_line)
    corruptions: list[dict[str, Any]] = []
    for case, field, value in (
        ("marker-frame-hash-mismatch", "frame_hash", "sha256:" + "0" * 64),
        ("event-hash-mismatch", "event_hash", "sha256:" + "0" * 64),
        ("frame-id-mismatch", "frame_id", "frame_ffffffffffffffffffffffffffffffff"),
    ):
        changed = dict(marker)
        changed[field] = value
        stream = event_line + canonical(changed) + b"\n"
        corruptions.append({
            "case": case,
            "stream_utf8_base64": base64.b64encode(stream).decode("ascii"),
            "stream_sha256": sha256_digest(stream),
        })
    partial_marker = event_line + marker_line[: max(1, len(marker_line) // 2)]
    second_pair = (
        base64.b64decode(second["event_line_utf8_base64"])
        + base64.b64decode(second["marker_line_utf8_base64"])
    )
    interior = event_line + marker_line + b"{\"corrupt\":true}\n" + second_pair
    corruptions.extend([
        {
            "case": "trailing-event",
            "stream_utf8_base64": base64.b64encode(event_line).decode("ascii"),
            "stream_sha256": sha256_digest(event_line),
        },
        {
            "case": "partial-marker",
            "stream_utf8_base64": base64.b64encode(partial_marker).decode("ascii"),
            "stream_sha256": sha256_digest(partial_marker),
        },
        {
            "case": "interior-corruption",
            "stream_utf8_base64": base64.b64encode(interior).decode("ascii"),
            "stream_sha256": sha256_digest(interior),
        },
    ])
    return [first, second, ordered, *corruptions]

def envelope(kind: str, name: str, number: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    identifier = f"message_{number:032x}"
    return {"causation_id": None, "correlation_id": identifier if kind == "action" else None, "cycle_id": None, "extensions": {}, "idempotency_key": None, "kind": kind, "message_id": identifier, "name": name, "payload": payload or {}, "protocol": "muchanipo", "protocol_version": "ai-scientist.v1", "revision": 0 if kind == "action" else number, "sequence": 0 if kind == "action" else number, "timestamp": "2026-07-19T00:00:00.000000Z"}


def records() -> dict[str, bytes]:
    valid = [
        {"case": "normalization-unicode-15.1", "unicode_version": UNICODE_VERSION, "pairs": NORMALIZATION_CORPUS},
        {"case": "identity-null-cycle-start", "cycle_id": None, "retry_key": "creation_00000000000000000000000000000000"},
        {"case": "retry-same-key", "attempt": 2, "retry_key": "creation_00000000000000000000000000000000"},
        {"case": "safe-integer-boundaries", "minimum": -9007199254740991, "maximum": 9007199254740991},
        {"case": "frame-preimage-member-order", "members": ["protocol", "protocol_version", "kind", "name", "message_id", "cycle_id", "correlation_id", "causation_id", "sequence", "revision", "idempotency_key", "timestamp", "payload", "extensions"]},
    ]
    valid += [envelope("action", name, index + 1) for index, name in enumerate(ACTION_NAMES)]
    valid += [envelope("event", name, index + 100) for index, name in enumerate(EVENT_NAMES)]
    valid += [envelope("response", name, index + 200) for index, name in enumerate(RESPONSE_NAMES)]
    valid += [envelope("error", name, index + 300) for index, name in enumerate(ERROR_NAMES)]
    valid += [envelope("snapshot", "cycle.snapshot", 400), envelope("ack", "cycle.acknowledged", 401)]
    valid += [{"case": "six-dispositions", "names": list(ACTION_NAMES[5:11])}, {"case": "eight-continue-branches-and-inverses", "branches": ["landscape", "hypothesis", "proposal", "not_run", "analysis", "interim", "final", "complete"], "inverses": ["landscape", "hypothesis", "proposal", "not_run", "analysis", "interim", "final", "complete"]}, {"case": "adjudication-links-policy", "claim_ids": ["claim_00000000000000000000000000000000"], "result_ids": ["result_00000000000000000000000000000000"], "validation_policy_id": "muchanipo.validation.general", "validation_policy_version": "1", "validation_policy_reference": "policy_00000000000000000000000000000000"}]
    invalid = [{"case": name, "valid": False} for name in ("required-frame-preimage", "frame-hash", "member-order", "marker-mismatch", "event-hash", "invalid-id", "trailing-bytes", "partial-frame", "interior-corruption", "unsafe-integer")]
    replay = [{"case": "replay-gap", "after_sequence": 1}, {"case": "snapshot-recovery", "at_revision": 2}, {"case": "ack-coordinate", "sequence": 3, "revision": 3}]
    legacy = [{"case": "legacy-event", "bytes": '{"event":"legacy.started"}\n'}, {"case": "mixed-frame-rejected", "bytes": '{"event":"legacy.started","protocol":"muchanipo"}\n'}]
    bytes_cases = corrupted_frame_vectors()
    groups = {"valid": valid, "invalid": invalid, "replay": replay, "legacy": legacy, "bytes": bytes_cases}
    return {f"{group}/corpus.jsonl": b"".join(line(item) for item in items) for group, items in groups.items()}


def manifest_for(files: dict[str, bytes]) -> dict[str, Any]:
    return {"format": "muchanipo.protocol-fixtures.v1", "unicode_version": UNICODE_VERSION, "normalization_profile": "unicode-nfc-whitespace", "files": [{"path": path, "length": len(data), "sha256": hashlib.sha256(data).hexdigest()} for path, data in sorted(files.items())]}


def verify() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("unicode_version") != UNICODE_VERSION:
        raise SystemExit("manifest Unicode version is not pinned to 15.1.0")
    expected = manifest_for(records())
    if manifest != expected:
        raise SystemExit("manifest is stale; run build_protocol_fixtures.py")
    for entry in manifest["files"]:
        data = (CORPUS / entry["path"]).read_bytes()
        if len(data) != entry["length"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise SystemExit(f"fixture bytes do not match manifest: {entry['path']}")


def build() -> None:
    files = records()
    for relative, data in files.items():
        target = CORPUS / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    MANIFEST.write_text(json.dumps(manifest_for(files), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify checked-in bytes and manifest")
    args = parser.parse_args()
    if args.check:
        verify()
    else:
        build()

if __name__ == "__main__":
    main()
