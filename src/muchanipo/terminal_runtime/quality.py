from __future__ import annotations

import json
from typing import Any


def research_quality_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    artifacts = as_dict(result.get("artifacts"))
    source_audit = parse_artifact(artifacts.get("source_audit_summary"))
    claim_matrix = parse_artifact(artifacts.get("claim_evidence_matrix_summary"))
    benchmark_metrics = parse_artifact(artifacts.get("max_plus_benchmark_metrics"))
    ledger_metrics = parse_artifact(artifacts.get("evidence_ledger_readiness_metrics"))
    evidence_count = coerce_int(
        artifacts.get("evidence_count"),
        default=coerce_int(result.get("evidence_count"), default=0),
    )
    benchmark_decision = str(
        artifacts.get("max_plus_benchmark_decision")
        or result.get("max_plus_benchmark_decision")
        or ""
    )
    readiness = str(artifacts.get("research_quality_readiness") or "ready")
    quality_stop = str(
        result.get("research_quality_only_stop")
        or artifacts.get("research_quality_only_stop")
        or "before_council"
    )
    review_reasons: list[str] = []
    if benchmark_decision == "blocked":
        readiness = "needs_review"
        quality_stop = "needs_review_before_council"
        review_reasons.append("max_plus_benchmark_decision=blocked")
    snapshot = {
        "research_quality_stop": quality_stop,
        "research_quality_readiness": readiness,
        "evidence_ledger_readiness": str(artifacts.get("evidence_ledger_readiness") or ""),
        "evidence_ledger_metrics": ledger_metrics,
        "source_audit_summary": source_audit,
        "claim_evidence_matrix_summary": claim_matrix,
        "max_plus_benchmark_metrics": benchmark_metrics,
        "max_plus_benchmark_decision": benchmark_decision,
        "evidence_count": evidence_count,
    }
    if review_reasons:
        snapshot["research_quality_review_reasons"] = review_reasons
    snapshot.update(research_quality_iteration_counts(snapshot))
    return snapshot


def research_quality_iteration_counts(snapshot: dict[str, Any]) -> dict[str, Any]:
    source_audit = as_dict(snapshot.get("source_audit_summary"))
    benchmark_metrics = as_dict(snapshot.get("max_plus_benchmark_metrics"))
    counts: dict[str, Any] = {}
    for key in (
        "accepted_source_count",
        "rejected_source_count",
        "weak_source_count",
        "weak_source_flag_count",
        "gap_count",
    ):
        if key in source_audit:
            counts[key] = coerce_int(source_audit.get(key), default=0)
    if "evidence_count" in snapshot:
        counts["evidence_count"] = coerce_int(snapshot.get("evidence_count"), default=0)
    if "max_plus_benchmark_decision" in snapshot:
        counts["max_plus_benchmark_decision"] = str(
            snapshot.get("max_plus_benchmark_decision") or ""
        )
    for key in (
        "weak_source_penalty",
        "expected_claim_recall",
        "evidence_quote_coverage",
        "claim_traceability",
        "source_authority_score",
    ):
        if key in benchmark_metrics:
            counts[key] = coerce_float(benchmark_metrics.get(key), default=0.0)
    return counts


def parse_artifact(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    if isinstance(value, (dict, list)):
        return value
    return {} if value is None else value


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def coerce_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
