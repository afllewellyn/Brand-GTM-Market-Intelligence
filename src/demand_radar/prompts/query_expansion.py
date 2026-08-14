"""Prompt builder for Stage 2 — query expansion."""

from __future__ import annotations

from ..config import RadarConfig


def build_query_expansion_prompt(config: RadarConfig) -> str:
    keywords = "\n".join(f"- {k}" for k in config.base_keywords)
    competitors = "\n".join(f"- {c}" for c in config.competitors) or "- (none)"
    icps = "\n".join(f"- {r}" for r in config.icp_roles) or "- (none)"
    markets = ", ".join(config.primary_markets)
    return f"""You are expanding seed topics into search queries for a B2B demand-intelligence scan.

Brand: {config.brand_name}
Primary markets: {markets}
Timeframe: {config.timeframe}

Seed keywords:
{keywords}

Competitors:
{competitors}

ICP roles:
{icps}

Generate three lists of Google-style search queries.

1. market_queries (4-8): category trends, use cases, changing technology
   priorities, and enterprise adoption themes.
2. intent_queries (4-8): buying-intent language — pricing, ROI, cost,
   implementation, alternatives, versus, RFP, security, compliance,
   integration, performance, benchmarks.
3. competitor_queries (4-10): per-competitor GTM activity — webinars, case
   studies, enterprise landing pages, pricing, launches, events, whitepapers,
   customer stories, AI agents, industry campaigns. Begin each competitor
   query with the competitor's name exactly as listed above.

Return ONLY a JSON object:
{{"market_queries": [...], "intent_queries": [...], "competitor_queries": [...]}}"""
