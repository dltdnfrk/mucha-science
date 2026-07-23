from __future__ import annotations

from typing import Any


PRICE_PER_M_INPUT = {
    "claude-opus-4-7": 15.00,
    "claude-sonnet-4-6": 3.00,
    "claude-sonnet-4-5": 3.00,
    "claude-haiku-4-5": 0.25,
    "gemini-3.1-pro-preview": 2.00,
    "gemini-3.1-pro-preview-customtools": 2.00,
    "gemini-2.5-flash": 0.30,
    "kimi-k2-0711-preview": 0.55,
    "gpt-5.4": 2.00,
    "gpt-5.5": 2.00,
    "mock": 0.0,
}

PRICE_PER_M_OUTPUT = {
    model: price * 4.0 for model, price in PRICE_PER_M_INPUT.items()
} | {
    "gemini-3.1-pro-preview": 12.00,
    "gemini-3.1-pro-preview-customtools": 12.00,
    "gemini-2.5-flash": 2.50,
}

GEMINI_PRO_MODELS = frozenset({
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
})

STAGE_OUTPUT_MULTIPLIER = {
    "intake": 0.6,
    "interview": 1.2,
    "targeting": 0.8,
    "research": 1.5,
    "evidence": 1.0,
    "council": 2.0,
    "consensus": 1.6,
    "report": 2.4,
    "eval": 1.0,
    "ingest": 0.5,
}

STAGE_PROVIDER_MODELS = {
    ("intake", "gemini"): "gemini-2.5-flash",
    ("interview", "anthropic"): "claude-sonnet-4-6",
    ("targeting", "gemini"): "gemini-2.5-flash",
    ("research", "gemini"): "gemini-3.1-pro-preview",
    ("evidence", "gemini"): "gemini-3.1-pro-preview",
    ("council", "gemini"): "gemini-3.1-pro-preview",
    ("consensus", "gemini"): "gemini-3.1-pro-preview",
    ("research", "kimi"): "kimi-k2-0711-preview",
    ("evidence", "kimi"): "kimi-k2-0711-preview",
    ("council", "anthropic"): "claude-opus-4-7",
    ("consensus", "anthropic"): "claude-opus-4-7",
    ("report", "anthropic"): "claude-sonnet-4-6",
    ("eval", "codex"): "gpt-5.4",
    ("mock", "mock"): "mock",
}

PROVIDER_DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-2.5-flash",
    "kimi": "kimi-k2-0711-preview",
    "codex": "gpt-5.4",
    "openai": "gpt-5.5",
    "mock": "mock",
}


class UnpricedModelError(ValueError):
    pass


def estimate_input_tokens(prompt: str) -> int:
    return max(len(prompt) // 4, 1)


def estimate_output_tokens(input_tokens: int, stage: str) -> int:
    multiplier = STAGE_OUTPUT_MULTIPLIER.get(stage, 1.0)
    return max(int(round(input_tokens * multiplier)), 1)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if model in GEMINI_PRO_MODELS and input_tokens > 200_000:
        input_price, output_price = 4.0, 18.0
    else:
        try:
            input_price = PRICE_PER_M_INPUT[model]
            output_price = PRICE_PER_M_OUTPUT[model]
        except KeyError as exc:
            raise UnpricedModelError(
                f"Model pricing is not configured: {model}"
            ) from exc
    cost = (input_tokens / 1_000_000.0) * input_price
    cost += (output_tokens / 1_000_000.0) * output_price
    return round(cost, 8)


def provider_name(provider: Any) -> str | None:
    if provider is None:
        return None
    if isinstance(provider, str):
        return provider
    return getattr(provider, "name", None)


def resolve_model(*, stage: str, provider: Any = None, model: str | None = None) -> str | None:
    if model:
        return model
    name = provider_name(provider)
    model_for_stage = getattr(provider, "model_for_stage", None)
    if callable(model_for_stage):
        resolved_model = model_for_stage(stage)
        if resolved_model:
            return str(resolved_model)
    if name:
        stage_model = STAGE_PROVIDER_MODELS.get((stage, name))
        if stage_model:
            return stage_model
    provider_model = getattr(provider, "model", None)
    if provider_model:
        return str(provider_model)
    if name:
        return PROVIDER_DEFAULT_MODELS.get(name)
    return None
