"""LLM routing layer.

The pipeline asks the router, not a vendor SDK, for completions. The router
resolves which model handles a task using the central per-task configuration
(`llm.tasks` in the run config) and delegates to a swappable provider.

Routing modes
-------------
* ``static`` (implemented): task -> model mapping straight from config.
* ``adaptive`` (reserved): a future external model-routing service will pick
  the model from task complexity, cost, latency, and confidence requirements.
  See ``docs/model_routing.md`` and :class:`ExternalRouterProvider`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ...config import LLMConfig
from .base import LLMError, LLMProvider

log = logging.getLogger(__name__)


@dataclass
class RouteDecision:
    """The outcome of a routing choice (mirrors the future external API)."""

    task: str
    model: str
    reasoning_level: str
    provider: str


class LLMRouter:
    """Selects a model per task and forwards the call to the provider."""

    def __init__(self, provider: LLMProvider, llm_config: LLMConfig) -> None:
        self._provider = provider
        self._config = llm_config
        if llm_config.routing_mode == "adaptive":
            log.warning(
                "routing_mode=adaptive is reserved for a future external "
                "router; falling back to static routing."
            )

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def route(self, task: str) -> RouteDecision:
        """Resolve the model + reasoning level for a task (static mode)."""
        task_cfg = self._config.task(task)
        return RouteDecision(
            task=task,
            model=task_cfg.model,
            reasoning_level=task_cfg.reasoning_level,
            provider=self._provider.name,
        )

    def complete(
        self,
        task: str,
        prompt: str,
        schema: type | None = None,
        reasoning_level: str | None = None,
    ) -> Any:
        decision = self.route(task)
        level = reasoning_level or decision.reasoning_level
        log.debug("Routing task=%s -> model=%s level=%s", task, decision.model, level)
        return self._provider.complete(
            task=task,
            prompt=prompt,
            model=decision.model,
            schema=schema,
            reasoning_level=level,
        )


class ExternalRouterProvider(LLMProvider):
    """Stub adapter for a future external model-routing service.

    The external service would expose something like::

        decision = router.route(
            task="trend_analysis",
            complexity="high",
            structured_output=True,
            context_tokens=45000,
        )

    and this adapter would forward the completion to whichever provider and
    model the service selects. Not implemented yet — instantiate raises.
    """

    name = "external-router"

    def __init__(self, endpoint: str | None = None) -> None:
        raise LLMError(
            "ExternalRouterProvider is a stub for future integration. "
            "Use provider=anthropic or provider=mock. See docs/model_routing.md."
        )

    def complete(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError


def build_router(llm_config: LLMConfig, api_key: str | None = None) -> LLMRouter:
    """Factory: construct the configured provider wrapped in a router."""
    if llm_config.provider == "mock":
        from .mock import MockLLMProvider

        return LLMRouter(MockLLMProvider(), llm_config)
    from .anthropic import AnthropicProvider

    return LLMRouter(AnthropicProvider(api_key=api_key), llm_config)
