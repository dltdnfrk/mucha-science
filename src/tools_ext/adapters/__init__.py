"""Built-in reference adapters for the external tool framework."""

from .mock_scorer import MockScorerAdapter, mock_scorer_config

__all__ = ["MockScorerAdapter", "mock_scorer_config"]
