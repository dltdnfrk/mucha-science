from __future__ import annotations

import json
from pathlib import Path

from src.research.citation_faithfulness import evaluate_evidence_interventions


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "citation_faithfulness_benchmark.v1.json"
)


def test_evidence_intervention_benchmark_rejects_swap_hide_and_contradiction() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    metrics = evaluate_evidence_interventions(payload)

    assert metrics["case_count"] == 2
    assert metrics["gold_support_rate"] == 1.0
    assert metrics["evidence_swap_rejection"] == 1.0
    assert metrics["hidden_abstention"] == 1.0
    assert metrics["contradiction_detection"] == 1.0
    assert metrics["content_hash_validity"] == 1.0
    assert metrics["passed"] is True
    assert {row["language"] for row in metrics["rows"]} == {"en", "ko"}
