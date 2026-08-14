"""Deterministic signal-aggregation output schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SignalSummary(BaseModel):
    total_evidence_rows: int = 0
    theme_counts: dict[str, int] = Field(default_factory=dict)
    theme_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)
    query_type_counts: dict[str, int] = Field(default_factory=dict)
    top_domains: dict[str, int] = Field(default_factory=dict)
