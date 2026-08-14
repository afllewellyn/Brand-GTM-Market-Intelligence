"""LLM provider interface.

Any provider (Anthropic, mock, or a future external router service) must
implement :class:`LLMProvider`. The pipeline never talks to a vendor SDK
directly — only to this interface via :class:`~demand_radar.providers.llm.router.LLMRouter`.
"""

from __future__ import annotations

import abc
from typing import Any


class LLMError(RuntimeError):
    """Raised when an LLM call fails or returns unusable output."""


class LLMProvider(abc.ABC):
    """Minimal contract every LLM backend must satisfy."""

    name: str = "base"

    @abc.abstractmethod
    def complete(
        self,
        task: str,
        prompt: str,
        model: str,
        schema: type | None = None,
        reasoning_level: str = "medium",
    ) -> Any:
        """Run a completion.

        Args:
            task: Pipeline task name (query_expansion, trend_analysis, ...).
            prompt: Fully rendered prompt text.
            model: Model identifier chosen by the router.
            schema: Optional Pydantic model. When given, the provider must
                return a validated instance of it (JSON-mode behavior).
            reasoning_level: low | medium | high. Providers may use this to
                tune token budgets or sampling; it must not change semantics.

        Returns:
            A validated ``schema`` instance when ``schema`` is given,
            otherwise the raw text response.
        """
