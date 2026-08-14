"""Query-expansion output schema."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QuerySet(BaseModel):
    market_queries: list[str] = Field(default_factory=list)
    intent_queries: list[str] = Field(default_factory=list)
    competitor_queries: list[str] = Field(default_factory=list)

    def total(self) -> int:
        return (
            len(self.market_queries)
            + len(self.intent_queries)
            + len(self.competitor_queries)
        )
