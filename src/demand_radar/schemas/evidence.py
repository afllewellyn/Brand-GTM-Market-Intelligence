"""Normalized evidence row schema."""

from __future__ import annotations

from pydantic import BaseModel


class EvidenceRow(BaseModel):
    """One deduplicated search result with a stable evidence ID."""

    evidence_id: str
    query: str
    query_type: str  # market | intent | competitor
    title: str
    snippet: str
    url: str
    domain: str
    source_type: str = "serp"
    competitor_name: str | None = None
    retrieved_at: str
