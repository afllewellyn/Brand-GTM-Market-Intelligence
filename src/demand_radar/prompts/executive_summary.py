"""Prompt builder for Stage 8 — executive summary."""

from __future__ import annotations

import json

from ..config import RadarConfig
from ..schemas.analysis import AnalysisResult
from ..schemas.signals import SignalSummary


def build_summary_prompt(
    config: RadarConfig,
    signals: SignalSummary,
    analysis: AnalysisResult,
    gtm_plan_md: str,
) -> str:
    counts = json.dumps(signals.model_dump(exclude={"theme_evidence_ids"}), indent=2)
    analysis_json = json.dumps(analysis.model_dump(), indent=2)
    return f"""Write an executive summary (500 words maximum) for {config.brand_name}.

SIGNAL COUNTS (Python-computed; cite verbatim or omit):
{counts}

ANALYSIS:
{analysis_json}

GTM PLAN (for reference):
{gtm_plan_md[:4000]}

Answer, in order:
- What changed?
- What does buyer behavior suggest?
- Which signals appear closest to revenue?
- What should Marketing do?
- What should Sales do?
- What are the three most important actions now?

Throughout, clearly label statements as one of:
Observed Evidence / Interpretation / Recommended Action.

Plain text or light Markdown. No invented numbers. Under 500 words."""
