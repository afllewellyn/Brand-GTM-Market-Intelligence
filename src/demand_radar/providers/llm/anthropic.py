"""Anthropic implementation of the LLM provider interface.

Uses the official ``anthropic`` Python SDK (Messages API). For structured
tasks the provider instructs the model to return only JSON, then parses and
validates it against the supplied Pydantic schema, with one repair retry.

No hidden chain-of-thought is stored: only the final structured output.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .base import LLMError, LLMProvider

log = logging.getLogger(__name__)

# Token budgets scale with the requested reasoning level. These are deliberately
# generous: on models with adaptive thinking, max_tokens caps thinking *and*
# response text together, so a budget sized only for the answer truncates it.
_MAX_TOKENS = {"low": 4000, "medium": 8000, "high": 16000}


def _extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating markdown code fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip ```json ... ``` fences
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in model response")
    return json.loads(cleaned[start : end + 1])


class AnthropicProvider(LLMProvider):
    """LLM provider backed by the Anthropic Messages API."""

    name = "anthropic"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError(
                "ANTHROPIC_API_KEY is not set. Export it (see .env.example) "
                "or run `demand-radar demo` which needs no credentials."
            )
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError(
                "The `anthropic` package is not installed. Run `pip install -e .`"
            ) from exc
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=key)

    # ------------------------------------------------------------------
    def complete(
        self,
        task: str,
        prompt: str,
        model: str,
        schema: type | None = None,
        reasoning_level: str = "medium",
    ) -> Any:
        max_tokens = _MAX_TOKENS.get(reasoning_level, 8000)
        system = (
            "You are the analysis engine inside Enterprise Demand Radar. "
            "You never invent counts, statistics, sources, or customer results. "
            "All numeric signal counts you mention must come verbatim from the "
            "input. Reference evidence IDs (e.g. e42) for every conclusion "
            "whenever possible. If evidence is weak, say so explicitly."
        )
        if schema is not None:
            system += (
                " Respond with a single valid JSON object only — no prose, "
                "no markdown fences."
            )

        text = self._call(model, system, prompt, max_tokens)

        if schema is None:
            return text

        try:
            return schema(**_extract_json(text))
        except Exception as exc:
            log.warning("Task %s returned invalid JSON (%s); retrying once", task, exc)
            repair_prompt = (
                f"{prompt}\n\nYour previous response was not valid JSON for the "
                f"required schema ({exc}). Return ONLY the corrected JSON object."
            )
            text = self._call(model, system, repair_prompt, max_tokens)
            try:
                return schema(**_extract_json(text))
            except Exception as exc2:
                raise LLMError(
                    f"Task '{task}' returned malformed JSON twice: {exc2}"
                ) from exc2

    # ------------------------------------------------------------------
    def _call(self, model: str, system: str, prompt: str, max_tokens: int) -> str:
        try:
            resp = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except self._anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc
        return "".join(
            block.text for block in resp.content if getattr(block, "type", "") == "text"
        )
