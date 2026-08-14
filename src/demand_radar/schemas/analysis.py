"""Trend / buying-signal / competitor-move analysis schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Trend(BaseModel):
    id: str
    name: str
    description: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    strength_score_1_to_10: int = Field(ge=0, le=10)
    relevance_to_brand_1_to_10: int = Field(ge=0, le=10)
    relevant_icps: list[str] = Field(default_factory=list)
    time_horizon: Literal["short", "medium", "long"] = "short"


class BuyingSignal(BaseModel):
    id: str
    description: str
    stage: Literal["early", "mid", "late"]
    related_keywords: list[str] = Field(default_factory=list)
    related_competitors: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class CompetitorMove(BaseModel):
    competitor_name: str
    move_type: str
    description: str
    risk_to_brand_1_to_10: int = Field(ge=0, le=10)
    opportunity_for_brand_1_to_10: int = Field(ge=0, le=10)
    evidence_ids: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    trends: list[Trend] = Field(default_factory=list)
    buying_signals: list[BuyingSignal] = Field(default_factory=list)
    competitor_moves: list[CompetitorMove] = Field(default_factory=list)
