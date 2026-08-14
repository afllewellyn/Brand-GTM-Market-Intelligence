"""Prompt builder for Stage 6 — trend & buying-cycle analysis."""

from __future__ import annotations

import json

from ..config import RadarConfig
from ..schemas.evidence import EvidenceRow
from ..schemas.signals import SignalSummary

# Evidence sample size sent to the model. Full evidence stays on disk.
_MAX_ROWS = 120


def _evidence_block(rows: list[EvidenceRow]) -> str:
    lines = []
    for row in rows[:_MAX_ROWS]:
        title = row.title[:110]
        snippet = row.snippet[:180]
        comp = f" competitor={row.competitor_name}" if row.competitor_name else ""
        lines.append(
            f"[{row.evidence_id}] ({row.query_type}{comp}) {title} — {snippet} "
            f"({row.domain})"
        )
    if len(rows) > _MAX_ROWS:
        lines.append(f"... plus {len(rows) - _MAX_ROWS} more rows on disk.")
    return "\n".join(lines)


def build_trend_analysis_prompt(
    config: RadarConfig, signals: SignalSummary, rows: list[EvidenceRow]
) -> str:
    counts = json.dumps(signals.model_dump(exclude={"theme_evidence_ids"}), indent=2)
    return f"""Analyze market evidence for {config.brand_name} ({", ".join(config.primary_markets)}).
ICP roles: {", ".join(config.icp_roles) or "unspecified"}.
Competitors tracked: {", ".join(config.competitors) or "none"}.

AGGREGATED SIGNAL COUNTS (computed deterministically in Python — these are
the only counts that exist; never modify or invent numbers):
{counts}

EVIDENCE ROWS (id, query type, title, snippet, domain):
{_evidence_block(rows)}

Buying-stage definitions:
- early: buyer is learning about the category, opportunity, use case, or
  strategic viability.
- mid: buyer is evaluating economics, implementation, integration, security,
  compliance, or requirements.
- late: buyer is comparing vendors, examining proof, benchmarking
  performance, consuming case studies, or preparing procurement.

Rules:
- Reference evidence IDs for every trend, signal, and competitor move.
- Do not invent evidence, market statistics, customer results, or
  certifications.
- If evidence for a conclusion is weak, say so explicitly in the description.
- Treat conclusions as inference, not established fact.

Return ONLY a JSON object with this exact shape:
{{
  "trends": [{{"id": "t1", "name": "", "description": "",
    "supporting_evidence_ids": [], "strength_score_1_to_10": 0,
    "relevance_to_brand_1_to_10": 0, "relevant_icps": [],
    "time_horizon": "short"}}],
  "buying_signals": [{{"id": "b1", "description": "", "stage": "early",
    "related_keywords": [], "related_competitors": [], "evidence_ids": []}}],
  "competitor_moves": [{{"competitor_name": "", "move_type": "",
    "description": "", "risk_to_brand_1_to_10": 0,
    "opportunity_for_brand_1_to_10": 0, "evidence_ids": []}}]
}}"""
