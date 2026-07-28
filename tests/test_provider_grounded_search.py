from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.execution.models import ModelResult
from src.research import provider_grounded_search


@dataclass
class FakeProvider:
    name: str
    result: ModelResult
    calls: list[dict[str, Any]] = field(default_factory=list)

    def call(self, stage: str, prompt: str, **kwargs: Any) -> ModelResult:
        self.calls.append({"stage": stage, "prompt": prompt, **kwargs})
        return self.result


def test_gemini_grounding_collects_only_citation_backed_sources() -> None:
    provider = FakeProvider(
        name="gemini",
        result=ModelResult(
            text="Generated synthesis must not become evidence by itself.",
            provider="gemini",
            model="gemini-test",
            raw={
                "candidates": [{
                    "groundingMetadata": {
                        "groundingChunks": [
                            {"web": {"uri": "https://example.org/paper", "title": "Primary paper"}},
                            {"web": {"uri": "javascript:alert(1)", "title": "Unsafe"}},
                        ],
                        "groundingSupports": [{
                            "segment": {"text": "Measured effect was reported."},
                            "groundingChunkIndices": [0],
                        }],
                    },
                }],
            },
        ),
    )

    hits = provider_grounded_search.search(
        "measured effect",
        providers=[provider],
        limit=4,
    )

    assert hits == [{
        "kind": "provider_search",
        "provider": "gemini",
        "model": "gemini-test",
        "url": "https://example.org/paper",
        "title": "Primary paper",
        "text": "Measured effect was reported.",
        "score": 0.65,
    }]
    assert provider.calls[0]["stage"] == "research"
    assert provider.calls[0]["search_grounding"] is True


def test_anthropic_web_search_collects_cited_text_and_rejects_uncited_generation() -> None:
    provider = FakeProvider(
        name="anthropic",
        result=ModelResult(
            text="Uncited prose",
            provider="anthropic",
            model="claude-test",
            raw={
                "content": [{
                    "type": "text",
                    "text": "Cited prose",
                    "citations": [{
                        "type": "web_search_result_location",
                        "url": "https://example.org/trial",
                        "title": "Trial registry",
                        "cited_text": "The trial enrolled 120 participants.",
                        "encrypted_index": "opaque",
                    }],
                }],
            },
        ),
    )

    hits = provider_grounded_search.search("trial participants", providers=[provider])

    assert len(hits) == 1
    assert hits[0]["url"] == "https://example.org/trial"
    assert hits[0]["text"] == "The trial enrolled 120 participants."
    assert provider.calls[0]["tools"] == [{
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 4,
    }]


def test_provider_search_rejects_model_text_without_source_metadata() -> None:
    provider = FakeProvider(
        name="gemini",
        result=ModelResult(
            text="Plausible but uncited answer",
            provider="gemini",
            model="gemini-test",
            raw={"candidates": [{"content": {"parts": [{"text": "No grounding"}]}}]},
        ),
    )

    assert provider_grounded_search.search("question", providers=[provider]) == []
