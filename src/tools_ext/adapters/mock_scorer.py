"""Reference deterministic adapter backed by a small local SHA-256 scorer."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from src.pipeline.scientific_contracts import byte_digest

from ..adapter import ParsedResult
from ..contract import ToolContractError, ToolIdentity, ToolLimitation
from ..registry import InvocationConfig

_ADAPTER_ID = "reference.mock_scorer"
_CONTRACT_VERSION = "tools-ext.mock-scorer.v1"
_SCRIPT = Path(__file__).with_name("bin") / "mock_scorer.py"
_RECIPE_FIELDS = frozenset({"candidate", "target"})


def _script_digest() -> str:
    return byte_digest(_SCRIPT.read_bytes())


def _recipe(parameters: Mapping[str, Any]) -> tuple[str, str]:
    if not isinstance(parameters, Mapping) or set(parameters) != _RECIPE_FIELDS:
        raise ToolContractError("mock scorer parameters must contain exactly candidate and target")
    candidate = parameters["candidate"]
    target = parameters["target"]
    if not isinstance(candidate, str) or not isinstance(target, str):
        raise ToolContractError("mock scorer candidate and target must be strings")
    return candidate, target


def mock_scorer_inputs(parameters: Mapping[str, Any]) -> dict[str, bytes]:
    """Reconstruct the complete input set from the invocation's frozen recipe."""
    candidate, target = _recipe(parameters)
    return {"candidate.txt": candidate.encode("utf-8"), "target.txt": target.encode("utf-8")}


def mock_scorer_request(parameters: Mapping[str, Any], seed: int) -> dict[str, Any]:
    candidate, target = _recipe(parameters)
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 2**64 - 1:
        raise ToolContractError("mock scorer seed must be uint64")
    return {"candidate": candidate, "target": target, "seed": seed}


def mock_scorer_config() -> InvocationConfig:
    return InvocationConfig(
        adapter_id=_ADAPTER_ID,
        contract_version=_CONTRACT_VERSION,
        adapter_build_sha256=_script_digest(),
        dependency_lock_sha256=byte_digest(b"python-stdlib-only"),
        reproducibility_mode="CANONICAL_EXACT",
    )


class MockScorerAdapter:
    """Pure adapter for the deterministic reference scorer executable."""

    def probe_version(self) -> ToolIdentity:
        return ToolIdentity("mucha-mock-scorer", "1", _script_digest())

    def limitations(self) -> tuple[ToolLimitation, ...]:
        return (
            ToolLimitation(
                "reference-only",
                "Synthetic hash similarity; not a scientific scoring tool",
                {"production_science": False},
            ),
        )

    def build_command(self, request: Mapping[str, Any]) -> list[str]:
        if not isinstance(request, Mapping) or set(request) != {"candidate", "target", "seed"}:
            raise ToolContractError("mock scorer request fields are frozen")
        candidate, target = _recipe({"candidate": request["candidate"], "target": request["target"]})
        seed = request["seed"]
        if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 2**64 - 1:
            raise ToolContractError("mock scorer seed must be uint64")
        encode = lambda value: base64.b64encode(value.encode("utf-8")).decode("ascii")
        return [
            sys.executable,
            str(_SCRIPT),
            "--candidate-b64", encode(candidate),
            "--target-b64", encode(target),
            "--seed", str(seed),
        ]

    def parse_output(self, raw: bytes) -> ParsedResult:
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolContractError("mock scorer emitted invalid JSON") from exc
        fields = {
            "abstention_disposition", "candidate_sha256", "constraint_disposition",
            "score", "score_ppm", "seed", "target_sha256",
        }
        if not isinstance(value, dict) or set(value) != fields:
            raise ToolContractError("mock scorer output fields are frozen")
        if (value["constraint_disposition"] != "PASS"
                or value["abstention_disposition"] != "RANKED"
                or not isinstance(value["score_ppm"], int)
                or not isinstance(value["seed"], int)
                or not isinstance(value["score"], str)):
            raise ToolContractError("mock scorer output values are invalid")
        for name in ("candidate_sha256", "target_sha256"):
            digest = value[name]
            if not isinstance(digest, str) or len(digest) != 71 or not digest.startswith("sha256:"):
                raise ToolContractError("mock scorer output digest is invalid")
            try:
                int(digest[7:], 16)
            except ValueError as exc:
                raise ToolContractError("mock scorer output digest is invalid") from exc
        return ParsedResult(value)


__all__ = [
    "MockScorerAdapter", "mock_scorer_config", "mock_scorer_inputs",
    "mock_scorer_request",
]
