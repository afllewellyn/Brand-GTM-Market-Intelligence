"""Prompt builder for Stage 7 — GTM recommendations."""

from __future__ import annotations

import json

from ..config import RadarConfig
from ..schemas.analysis import AnalysisResult
from ..schemas.signals import SignalSummary


def build_gtm_prompt(
    config: RadarConfig, signals: SignalSummary, analysis: AnalysisResult
) -> str:
    counts = json.dumps(signals.model_dump(exclude={"theme_evidence_ids"}), indent=2)
    analysis_json = json.dumps(analysis.model_dump(), indent=2)
    return f"""Write a GTM plan for {config.brand_name} as a Markdown document.

AGGREGATED SIGNAL COUNTS (computed in Python — cite these numbers verbatim
or not at all; never invent or adjust counts):
{counts}

STRUCTURED ANALYSIS (trends, buying signals, competitor moves — each carries
evidence IDs):
{analysis_json}

ICP roles: {", ".join(config.icp_roles) or "unspecified"}

Produce Markdown with exactly these H2 sections:
## Market Changes
## Buying-Cycle Signals
## Top 3 GTM Plays
## Content / Thought Leadership
## ABM / Retargeting
## Sales Enablement
## Events / Field Marketing
## Messaging Implications

Each of the Top 3 GTM Plays must include these labeled fields:
Insight, Evidence, Why it matters, Target ICP, Buying stage,
Recommended action, Asset required, Distribution channel,
Expected business impact, Supporting evidence IDs.

Prioritize plays by: (1) proximity to revenue, (2) evidence strength,
(3) expected pipeline impact, (4) speed to execute, (5) cross-functional
reusability.

Ground every claim in the analysis and counts above. Reference evidence IDs.
If a recommendation rests on weak evidence, label it as such.
Return only the Markdown document — no preamble."""
