from __future__ import annotations

from collections.abc import Mapping
from typing import Any, IO

from ..events import ScientificEnvelope, emit_scientific


def _scientific_error(
    stdout: IO[str],
    *,
    code: str,
    message: str,
    action: ScientificEnvelope | None = None,
) -> None:
    retryability = "after_refresh" if code in {"revision_conflict", "cursor_ahead", "cursor_mismatch", "ack_mismatch"} else "never"
    outcome = "unknown" if code == "commit_outcome_unknown" else "not_committed"
    emit_scientific(
        ScientificEnvelope(
            kind="error",
            name="command.rejected.error",
            payload={
                "stable_code": code, "message": message, "details": {},
                "retryability": retryability, "outcome": outcome,
            },
            cycle_id=action.cycle_id if action else None,
            correlation_id=action.message_id if action else None,
            causation_id=action.message_id if action else None,
            sequence=action.sequence if action else 0,
            revision=action.revision if action else 0,
        ),
        stream=stdout,
    )


def _scientific_response(
    stdout: IO[str],
    action: ScientificEnvelope,
    *,
    name: str,
    payload: Mapping[str, Any],
    cycle_id: str | None = None,
    sequence: int = 0,
    revision: int = 0,
) -> None:
    emit_scientific(
        ScientificEnvelope(
            kind="response",
            name=name,
            payload=dict(payload),
            cycle_id=cycle_id if cycle_id is not None else action.cycle_id,
            correlation_id=action.message_id,
            causation_id=action.message_id,
            sequence=sequence,
            revision=revision,
        ),
        stream=stdout,
    )


def _scientific_snapshot(
    stdout: IO[str], action: ScientificEnvelope, *, snapshot: Mapping[str, Any], reason: str,
) -> None:
    checkpoint = snapshot["checkpoint"]
    emit_scientific(
        ScientificEnvelope(
            kind="snapshot", name="cycle.snapshot",
            payload={"request_message_id": action.message_id, "reason": reason, **snapshot},
            cycle_id=checkpoint["cycle_id"], correlation_id=action.message_id,
            causation_id=action.message_id, sequence=checkpoint["sequence"],
            revision=snapshot["state"]["revision"],
        ),
        stream=stdout,
    )


def _repository_response(stdout: IO[str], response: bytes) -> None:
    """Write the repository's committed envelope without changing its bytes."""
    stdout.write(response.decode("utf-8"))
    stdout.write("\n")
    stdout.flush()
