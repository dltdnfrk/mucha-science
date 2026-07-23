from concurrent.futures import ThreadPoolExecutor

import pytest

from src.execution.providers.gemini import GeminiProvider, _STAGE_MODELS
from src.governance.audit import AuditLog
from src.governance.budget import (
    BudgetExceeded,
    RunBudget,
    UnpricedModelError,
    estimate_cost_usd,
    resolve_model,
)
from src.governance.profiles import resolve_profile


def test_run_budget_reserve_reconcile_log(tmp_path):
    budget = RunBudget(limit_usd=1.0, cost_log_path=tmp_path / "cost-log.jsonl")
    rid = budget.reserve(stage="report", estimated_usd=0.25)

    budget.reconcile(rid, actual_usd=0.10)

    assert budget.total_actual_usd == 0.10
    assert budget.records[0].stage == "report"
    assert "reconciled" in (tmp_path / "cost-log.jsonl").read_text(encoding="utf-8")


def test_budget_exceeded_returns_false_and_logs(tmp_path):
    budget = RunBudget(limit_usd=0.1, cost_log_path=tmp_path / "cost-log.jsonl")

    assert budget.reserve(stage="council", estimated_usd=0.2) is False

    assert "reserve_rejected" in (tmp_path / "cost-log.jsonl").read_text(encoding="utf-8")


def test_budget_exceeded_can_still_raise_for_legacy_callers(tmp_path):
    budget = RunBudget(
        limit_usd=0.1,
        cost_log_path=tmp_path / "cost-log.jsonl",
        raise_on_exceeded=True,
    )

    with pytest.raises(BudgetExceeded):
        budget.reserve(stage="council", estimated_usd=0.2)


def test_budget_reserve_is_atomic_under_race(tmp_path):
    budget = RunBudget(limit_usd=0.5, cost_log_path=tmp_path / "cost-log.jsonl")

    def reserve_one():
        return budget.reserve(stage="race", estimated_usd=0.1) is not False

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda _: reserve_one(), range(12)))

    assert results.count(True) == 5
    assert budget.total_estimated_usd == pytest.approx(0.5)


def test_estimate_uses_provider_rate():
    provider = type(
        "Provider",
        (),
        {
            "name": "custom",
            "model": "custom-priced-model",
            "rate_per_1k_chars": 0.2,
        },
    )()
    budget = RunBudget(limit_usd=1.0)

    assert budget.estimate(stage="x", prompt="x" * 500, provider=provider) == 0.1


@pytest.mark.parametrize("stage", ["research", "evidence", "council", "consensus"])
def test_gemini_pro_stage_budget_routes_current_pro_model(stage):
    provider = type("Provider", (), {"name": "gemini", "model": "gemini-2.5-flash"})()

    assert resolve_model(stage=stage, provider=provider) == "gemini-3.1-pro-preview"


def test_gemini_current_pro_budget_uses_documented_pricing():
    assert estimate_cost_usd("gemini-3.1-pro-preview", 200_000, 200_000) == 2.8
    assert estimate_cost_usd("gemini-3.1-pro-preview", 200_001, 1) == 0.800022
    assert estimate_cost_usd("gemini-3.1-pro-preview", 1_000_000, 1_000_000) == 22.0
    assert estimate_cost_usd("gemini-3.1-pro-preview-customtools", 200_001, 1) == 0.800022


def test_gemini_flash_budget_uses_documented_pricing():
    assert estimate_cost_usd("gemini-2.5-flash", 2_000_000, 1_000_000) == 3.1


def test_unknown_model_cost_is_rejected():
    with pytest.raises(UnpricedModelError, match="pricing is not configured"):
        estimate_cost_usd("unpriced-paid-model", 1_000, 1_000)


def test_budget_uses_gemini_provider_effective_stage_model(monkeypatch):
    monkeypatch.setitem(_STAGE_MODELS, "research", "gemini-override-model")
    provider = GeminiProvider(model="gemini-2.5-flash", offline=True, use_cli=False)

    assert resolve_model(stage="research", provider=provider) == "gemini-override-model"


def test_budget_rejects_unknown_gemini_override(monkeypatch):
    monkeypatch.setitem(_STAGE_MODELS, "research", "gemini-override-model")
    provider = GeminiProvider(model="gemini-2.5-flash", offline=True, use_cli=False)
    budget = RunBudget(limit_usd=1.0)

    with pytest.raises(ValueError, match="pricing is not configured"):
        budget.estimate(
            stage="research",
            prompt="x" * 4_000,
            provider=provider,
        )


def test_reconcile_unknown_reservation_raises():
    budget = RunBudget(limit_usd=1.0)

    with pytest.raises(KeyError):
        budget.reconcile("missing", actual_usd=0.1)


def test_audit_log_records_call_fields(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")

    record = log.record_call(
        stage="council",
        provider="mock",
        model="mock",
        cost_usd=0.0,
        fallback_reason="primary failed",
    )

    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert record.stage == "council"
    assert "primary failed" in text


def test_default_profile_is_dev(monkeypatch):
    monkeypatch.delenv("MUCHANIPO_PROFILE", raising=False)

    assert resolve_profile().name == "dev"


def test_unknown_profile_raises(monkeypatch):
    monkeypatch.setenv("MUCHANIPO_PROFILE", "nope")

    with pytest.raises(ValueError):
        resolve_profile()
