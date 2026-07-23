from __future__ import annotations

import pytest

from src.eval.budget_simulator import render_markdown_report
from src.execution.gateway_v2 import GatewayV2
from src.execution.models import ModelGateway, ModelResult
from src.execution.providers.gemini import GeminiProvider
from src.governance.budget import RunBudget
from src.governance.cost_simulator import simulate_research_cost


def test_run_budget_estimates_model_prices_by_stage():
    budget = RunBudget(max_usd=1.0)
    prompt = "x" * 4000

    council = budget.estimate(stage="council", prompt=prompt, provider="anthropic")
    research = budget.estimate(stage="research", prompt=prompt, provider="gemini")

    assert council == pytest.approx(0.135)
    assert research == pytest.approx(0.02)


@pytest.mark.parametrize(
    "brief",
    [
        "Korean smart-farm distribution plan for paprika growers",
        "US FDA go-to-market research for microbiome diagnostics",
        "Japan senior care robotics willingness-to-pay analysis",
        "EU carbon farming software buyer discovery",
    ],
)
def test_research_cost_scenarios_fit_half_dollar_goal(brief):
    result = simulate_research_cost(brief)

    assert result["budget_ok"] is True
    assert result["total_usd"] < 0.5
    assert set(result["breakdown"]) >= {"council", "research", "evidence", "report"}


def test_budget_limit_triggers_gateway_fallback_chain(tmp_path):
    budget = RunBudget(max_usd=0.01, cost_log_path=tmp_path / "cost-log.jsonl")
    gateway = GatewayV2(
        providers={
            "anthropic": _SuccessProvider("anthropic", "claude-opus-4-7"),
            "gemini": _SuccessProvider("gemini", "gemini-3.1-pro-preview"),
        },
        stage_routes={"council": "anthropic"},
        fallback_chain={"council": ["anthropic", "gemini"]},
        budget=budget,
    )

    result = gateway.call("council", "x" * 1000)

    assert result.provider == "gemini"
    assert result.is_fallback is True
    assert "budget exceeded" in (result.fallback_reason or "")
    assert gateway.fallback_events[0]["provider"] == "anthropic"


def test_model_gateway_budget_uses_explicit_gemini_model_override(tmp_path):
    budget = RunBudget(max_usd=1.0, cost_log_path=tmp_path / "cost-log.jsonl")
    provider = GeminiProvider(offline=True, use_cli=False)
    gateway = ModelGateway(provider=provider, budget=budget)

    result = gateway.call(
        "research",
        "x" * 400_000,
        model="gemini-2.5-flash",
    )

    assert result.model == "gemini-2.5-flash"
    assert budget.records[0].model == "gemini-2.5-flash"
    assert budget.records[0].estimated_usd == pytest.approx(0.405)


def test_gateway_v2_rejects_unpriced_gemini_model_before_reservation(tmp_path):
    budget = RunBudget(max_usd=1.0, cost_log_path=tmp_path / "cost-log.jsonl")
    provider = GeminiProvider(offline=True, use_cli=False)
    gateway = GatewayV2(
        providers={"gemini": provider},
        stage_routes={"research": "gemini"},
        fallback_chain={"research": ["gemini"]},
        budget=budget,
    )

    with pytest.raises(ValueError, match="pricing is not configured"):
        gateway.call("research", "prompt", model="gemini-unpriced-model")

    assert budget.records == []


def test_model_gateway_rejects_unpriced_non_gemini_model_before_dispatch(tmp_path):
    budget = RunBudget(max_usd=1.0, cost_log_path=tmp_path / "cost-log.jsonl")
    provider = _SuccessProvider("anthropic", "claude-sonnet-4-6")
    gateway = ModelGateway(provider=provider, budget=budget)

    with pytest.raises(ValueError, match="pricing is not configured"):
        gateway.call("council", "prompt", model="unpriced-paid-model")

    assert budget.records == []
    assert provider.calls == 0


def test_gateway_v2_rejects_unpriced_non_gemini_model_before_dispatch(tmp_path):
    budget = RunBudget(max_usd=1.0, cost_log_path=tmp_path / "cost-log.jsonl")
    provider = _SuccessProvider("anthropic", "claude-sonnet-4-6")
    gateway = GatewayV2(
        providers={"anthropic": provider},
        stage_routes={"council": "anthropic"},
        fallback_chain={"council": ["anthropic"]},
        budget=budget,
    )

    with pytest.raises(ValueError, match="pricing is not configured"):
        gateway.call("council", "prompt", model="unpriced-paid-model")

    assert budget.records == []
    assert provider.calls == 0


def test_reserve_reconcile_status_uses_actual_cost_for_remaining_budget(tmp_path):
    budget = RunBudget(max_usd=0.5, cost_log_path=tmp_path / "cost-log.jsonl")
    first = budget.reserve(stage="council", estimated_usd=0.4)
    assert first is not False

    budget.reconcile(str(first), actual_usd=0.1)
    second = budget.reserve(stage="research", estimated_usd=0.35)

    assert second is not False
    status = budget.status()
    assert status["reserved_usd"] == pytest.approx(0.45)
    assert status["remaining_usd"] == pytest.approx(0.05)
    assert status["breakdown"]["council"]["actual_usd"] == pytest.approx(0.1)


def test_budget_simulator_renders_markdown_report():
    report = render_markdown_report("Korea agtech market entry", num_rounds=2, num_personas=2)

    assert "# Budget Simulation" in report
    assert "Council routing" in report
    assert "Single Opus" in report


def test_live_mode_rejects_short_primary_and_uses_fallback_chain():
    gateway = GatewayV2(
        providers={
            "mimo": _SuccessProvider("mimo", "mimo-v2.5-pro", text=""),
            "opencode": _SuccessProvider("opencode", "opencode-go", text="live council output with enough detail"),
        },
        stage_routes={"council": "mimo"},
        fallback_chain={"council": ["mimo", "opencode"]},
    )

    result = gateway.call("council", "persona proposal prompt", require_live=True)

    assert result.provider == "opencode"
    assert result.is_fallback is True
    assert "too-short" in (result.fallback_reason or "")
    assert gateway.fallback_events[0]["provider"] == "mimo"


def test_budgeted_live_mode_rejects_short_primary_and_uses_fallback_chain(tmp_path):
    budget = RunBudget(max_usd=1.0, cost_log_path=tmp_path / "cost-log.jsonl")
    gateway = GatewayV2(
        providers={
            "mimo": _SuccessProvider("mimo", "mimo-v2.5-pro", text="", rate_per_1k_chars=0.1),
            "opencode": _SuccessProvider(
                "opencode",
                "opencode-go",
                text="live council output with enough detail",
                cost_usd=0.01,
                rate_per_1k_chars=0.1,
            ),
        },
        stage_routes={"council": "mimo"},
        fallback_chain={"council": ["mimo", "opencode"]},
        budget=budget,
    )

    result = gateway.call("council", "persona proposal prompt", require_live=True)

    assert result.provider == "opencode"
    assert result.is_fallback is True
    assert "too-short" in (result.fallback_reason or "")
    assert gateway.fallback_events[0]["provider"] == "mimo"


class _SuccessProvider:
    def __init__(
        self,
        name: str,
        model: str,
        *,
        text: str | None = None,
        cost_usd: float = 0.0,
        rate_per_1k_chars: float | None = None,
    ):
        self.name = name
        self.model = model
        self._text = text
        self._cost_usd = cost_usd
        self.calls = 0
        if rate_per_1k_chars is not None:
            self.rate_per_1k_chars = rate_per_1k_chars

    def call(self, stage: str, prompt: str, **kwargs):
        self.calls += 1
        return ModelResult(
            text=self._text if self._text is not None else f"ok-{self.name}",
            provider=self.name,
            model=self.model,
            cost_usd=self._cost_usd,
        )
