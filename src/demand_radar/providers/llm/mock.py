"""Mock LLM provider for demo mode and tests.

Returns realistic, clearly synthetic output for each pipeline task without
any network calls. Evidence IDs referenced in mock analysis are harvested
from the prompt itself, so they point at real rows from the current run.
"""

from __future__ import annotations

import re
from typing import Any

from .base import LLMProvider

_EID = re.compile(r"\be\d+\b")


def _ids_from_prompt(prompt: str, n: int, offset: int = 0) -> list[str]:
    ids = list(dict.fromkeys(_EID.findall(prompt)))
    return ids[offset : offset + n]


class MockLLMProvider(LLMProvider):
    """Deterministic canned responses; used by `demand-radar demo` and pytest."""

    name = "mock"

    def complete(
        self,
        task: str,
        prompt: str,
        model: str = "mock-model",
        schema: type | None = None,
        reasoning_level: str = "medium",
    ) -> Any:
        handler = {
            "query_expansion": self._query_expansion,
            "trend_analysis": self._trend_analysis,
            "gtm_recommendations": self._gtm_recommendations,
            "executive_summary": self._executive_summary,
        }.get(task)
        if handler is None:
            raise ValueError(f"MockLLMProvider has no handler for task '{task}'")
        payload = handler(prompt)
        if schema is not None:
            return schema(**payload) if isinstance(payload, dict) else payload
        return payload

    # ------------------------------------------------------------------
    @staticmethod
    def _query_expansion(prompt: str) -> dict:
        return {
            "market_queries": [
                "enterprise voice AI adoption trends 2026",
                "AI contact center transformation enterprise",
                "voice agents customer experience use cases",
                "multilingual voice AI enterprise adoption",
            ],
            "intent_queries": [
                "enterprise voice AI pricing",
                "voice AI ROI contact center",
                "voice AI implementation requirements",
                "voice AI SOC 2 compliance enterprise",
                "voice AI vendors comparison",
            ],
            "competitor_queries": [
                "PolyAI enterprise case study",
                "Deepgram enterprise pricing",
                "OpenAI voice agent enterprise launch",
                "WellSaid Labs enterprise customers",
            ],
        }

    @staticmethod
    def _trend_analysis(prompt: str) -> dict:
        return {
            "trends": [
                {
                    "id": "t1",
                    "name": "Economic scrutiny of voice AI purchases",
                    "description": (
                        "[SYNTHETIC DEMO OUTPUT] Pricing, ROI, and cost language "
                        "appears across market and intent evidence, suggesting "
                        "buyers are pressure-testing the economics of voice AI."
                    ),
                    "supporting_evidence_ids": _ids_from_prompt(prompt, 3),
                    "strength_score_1_to_10": 7,
                    "relevance_to_brand_1_to_10": 8,
                    "relevant_icps": ["Head of CX", "Contact Center Operations"],
                    "time_horizon": "short",
                },
                {
                    "id": "t2",
                    "name": "Compliance as a gating requirement",
                    "description": (
                        "[SYNTHETIC DEMO OUTPUT] Security and compliance terms "
                        "recur in intent-stage evidence, consistent with "
                        "procurement and risk review entering the cycle."
                    ),
                    "supporting_evidence_ids": _ids_from_prompt(prompt, 3, offset=3),
                    "strength_score_1_to_10": 5,
                    "relevance_to_brand_1_to_10": 7,
                    "relevant_icps": ["Head of Compliance"],
                    "time_horizon": "medium",
                },
            ],
            "buying_signals": [
                {
                    "id": "b1",
                    "description": (
                        "[SYNTHETIC DEMO OUTPUT] Mid-stage evaluation signal: "
                        "pricing and implementation queries dominate intent "
                        "evidence."
                    ),
                    "stage": "mid",
                    "related_keywords": ["pricing", "roi", "implementation"],
                    "related_competitors": [],
                    "evidence_ids": _ids_from_prompt(prompt, 4),
                },
                {
                    "id": "b2",
                    "description": (
                        "[SYNTHETIC DEMO OUTPUT] Late-stage comparison signal: "
                        "vendor-versus-vendor and alternatives language present."
                    ),
                    "stage": "late",
                    "related_keywords": ["vs", "alternatives", "benchmark"],
                    "related_competitors": ["PolyAI", "Deepgram"],
                    "evidence_ids": _ids_from_prompt(prompt, 3, offset=6),
                },
            ],
            "competitor_moves": [
                {
                    "competitor_name": "PolyAI",
                    "move_type": "case_study",
                    "description": (
                        "[SYNTHETIC DEMO OUTPUT] Enterprise proof content "
                        "surfaced in competitor query results."
                    ),
                    "risk_to_brand_1_to_10": 6,
                    "opportunity_for_brand_1_to_10": 5,
                    "evidence_ids": _ids_from_prompt(prompt, 2, offset=9),
                }
            ],
        }

    @staticmethod
    def _gtm_recommendations(prompt: str) -> str:
        return (
            "# GTM Plan (SYNTHETIC DEMO OUTPUT)\n\n"
            "> Generated by MockLLMProvider without API calls. Counts referenced\n"
            "> below come from the deterministic signal aggregator for this run.\n\n"
            "## Market Changes\n"
            "Pricing/ROI and voice-agent themes lead the aggregated signal counts,\n"
            "indicating buyers are past category education and into evaluation.\n\n"
            "## Buying-Cycle Signals\n"
            "- Mid stage: pricing, ROI, and implementation language (b1)\n"
            "- Late stage: comparison and benchmark language (b2)\n\n"
            "## Top 3 GTM Plays\n\n"
            "### 1. Enterprise ROI Calculator\n"
            "- Insight: Economic scrutiny dominates intent evidence (t1)\n"
            "- Evidence: see theme_counts.pricing_roi and b1 evidence IDs\n"
            "- Why it matters: unblocks the economic buyer conversation\n"
            "- Target ICP: Head of CX\n- Buying stage: mid\n"
            "- Recommended action: interactive ROI calculator + gated worksheet\n"
            "- Asset required: calculator, 1-pager\n"
            "- Distribution channel: web, outbound, sales enablement\n"
            "- Expected business impact: faster mid-stage progression\n"
            "- Supporting evidence IDs: from b1\n\n"
            "### 2. Compliance & Security Framework\n"
            "- Insight: Compliance terms recur in intent evidence (t2)\n"
            "- Target ICP: Head of Compliance\n- Buying stage: mid\n"
            "- Recommended action: publish a security/compliance overview pack\n"
            "- Asset required: framework doc\n- Distribution channel: web, SDR\n"
            "- Expected business impact: removes procurement blockers\n\n"
            "### 3. Performance Proof Pack\n"
            "- Insight: Comparison/benchmark language in late-stage evidence (b2)\n"
            "- Target ICP: Director of Product\n- Buying stage: late\n"
            "- Recommended action: benchmark methodology + reference stories\n"
            "- Asset required: proof pack\n- Distribution channel: sales\n"
            "- Expected business impact: higher late-stage win rate\n\n"
            "## Content / Thought Leadership\nEconomics-of-voice-AI series.\n\n"
            "## ABM / Retargeting\nRetarget pricing-page and calculator visitors.\n\n"
            "## Sales Enablement\nROI talk track + compliance objection handling.\n\n"
            "## Events / Field Marketing\nCX operations roundtable on AI economics.\n\n"
            "## Messaging Implications\nLead with measurable economics, not novelty.\n"
        )

    @staticmethod
    def _executive_summary(prompt: str) -> str:
        return (
            "SYNTHETIC DEMO OUTPUT — generated without API calls.\n\n"
            "WHAT CHANGED\n"
            "Observed Evidence: pricing/ROI and voice-agent themes lead this "
            "run's deterministic signal counts.\n"
            "Interpretation: buyers appear to be evaluating economics, not "
            "learning the category.\n\n"
            "WHAT BUYER BEHAVIOR SUGGESTS\n"
            "Interpretation: mid-stage evaluation (pricing, implementation) "
            "with an emerging late-stage comparison thread.\n\n"
            "SIGNALS CLOSEST TO REVENUE\n"
            "Comparison/benchmark evidence (b2) sits closest to procurement.\n\n"
            "WHAT MARKETING SHOULD DO\n"
            "Recommended Action: ship an ROI calculator and a compliance pack.\n\n"
            "WHAT SALES SHOULD DO\n"
            "Recommended Action: adopt the ROI talk track; use proof points in "
            "late-stage deals.\n\n"
            "THREE MOST IMPORTANT ACTIONS\n"
            "1. Enterprise ROI calculator (mid stage)\n"
            "2. Compliance/security framework (mid stage)\n"
            "3. Performance proof pack (late stage)\n"
        )
