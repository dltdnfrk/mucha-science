"""Adversarial citation-faithfulness benchmark primitives."""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from src.research.evaluation import ClaimLabel, classify_claim_evidence


_HANGUL_RE = re.compile(r"[가-힣]")
_VARIANTS = ("gold", "swap", "hide", "contradict")


def evaluate_evidence_interventions(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate causal dependence on supporting, swapped, hidden, and conflicting evidence."""

    if payload.get("schema_version") != "citation-faithfulness-benchmark.v1":
        raise ValueError("unsupported citation-faithfulness benchmark schema")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("citation-faithfulness benchmark requires non-empty cases")

    rows: list[dict[str, Any]] = []
    hash_checks = 0
    hash_valid = 0
    for raw_case in cases:
        if not isinstance(raw_case, Mapping):
            raise ValueError("citation-faithfulness case must be an object")
        case_id = str(raw_case.get("case_id") or "").strip()
        claim = str(raw_case.get("claim") or "").strip()
        variants = raw_case.get("variants")
        if not case_id or not claim or not isinstance(variants, Mapping):
            raise ValueError("citation-faithfulness case is missing identity, claim, or variants")
        if any(name not in variants for name in _VARIANTS):
            raise ValueError(f"citation-faithfulness case {case_id} is missing a required variant")

        labels: dict[str, str] = {}
        for name in _VARIANTS:
            variant = variants.get(name)
            if variant is None:
                labels[name] = ClaimLabel.INSUFFICIENT_EVIDENCE.value
                continue
            if not isinstance(variant, Mapping):
                raise ValueError(f"citation-faithfulness variant {case_id}/{name} must be an object")
            text = str(variant.get("text") or "")
            expected_hash = str(variant.get("content_sha256") or "")
            hash_checks += 1
            if hashlib.sha256(text.encode("utf-8")).hexdigest() == expected_hash:
                hash_valid += 1
            labels[name] = classify_claim_evidence(claim, text).value

        rows.append(
            {
                "case_id": case_id,
                "claim": claim,
                "language": "ko" if _HANGUL_RE.search(claim) else "en",
                "labels": labels,
                "gold_supported": labels["gold"] == ClaimLabel.SUPPORTS.value,
                "swap_rejected": labels["swap"] != ClaimLabel.SUPPORTS.value,
                "hidden_abstained": labels["hide"] == ClaimLabel.INSUFFICIENT_EVIDENCE.value,
                "contradiction_detected": labels["contradict"] == ClaimLabel.REFUTES.value,
            }
        )

    case_count = len(rows)
    gold_support_rate = _rate(rows, "gold_supported")
    evidence_swap_rejection = _rate(rows, "swap_rejected")
    hidden_abstention = _rate(rows, "hidden_abstained")
    contradiction_detection = _rate(rows, "contradiction_detected")
    content_hash_validity = hash_valid / hash_checks if hash_checks else 0.0
    passed = (
        gold_support_rate == 1.0
        and evidence_swap_rejection >= 0.9
        and hidden_abstention >= 0.8
        and contradiction_detection >= 0.8
        and content_hash_validity == 1.0
    )
    return {
        "schema_version": "citation-faithfulness-benchmark-result.v1",
        "case_count": case_count,
        "gold_support_rate": round(gold_support_rate, 3),
        "evidence_swap_rejection": round(evidence_swap_rejection, 3),
        "hidden_abstention": round(hidden_abstention, 3),
        "contradiction_detection": round(contradiction_detection, 3),
        "content_hash_validity": round(content_hash_validity, 3),
        "passed": passed,
        "rows": rows,
    }


def _rate(rows: list[dict[str, Any]], key: str) -> float:
    return sum(bool(row.get(key)) for row in rows) / len(rows)
