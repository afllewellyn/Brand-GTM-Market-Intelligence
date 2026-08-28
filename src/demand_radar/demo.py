"""The demo scenario: a complete worked example that costs nothing to run.

`demand-radar demo` exists so the pipeline can be exercised end to end with
no credentials and no spend. That needs three things — a configuration, a
theme taxonomy, and providers that return synthetic data — and they belong
together rather than split across the CLI, the package root, and the mock
providers.

This module owns the first two. The mock providers own the third.
"""

from __future__ import annotations

from pathlib import Path

from .config import LLMConfig, RadarConfig

#: Taxonomy for the demo's voice-AI market. Lives in the package, not in
#: config/, because config/ holds files users copy for their own brand and
#: nothing there should be tied to one market.
DEMO_THEMES_FILE = Path(__file__).parent / "demo_themes.yaml"


def demo_config() -> RadarConfig:
    """The example configuration, with all providers mocked.

    Demo mode is the one place a real brand appears in a run: its output is
    banner-labeled synthetic, so a recognizable market makes the worked
    example easier to follow than an invented one would. Everything a user
    copies to run their own brand is market-agnostic.
    """
    return RadarConfig(
        brand_name="ElevenLabs",
        themes_file=str(DEMO_THEMES_FILE),
        primary_markets=["North America"],
        base_keywords=[
            "enterprise voice AI",
            "voice agents",
            "AI contact center",
            "AI phone agent",
            "multilingual voice AI",
            "voice AI compliance",
            "voice infrastructure",
        ],
        competitors=[
            "OpenAI", "PlayAI", "Speechify", "WellSaid Labs", "PolyAI", "Deepgram",
        ],
        icp_roles=[
            "Head of CX",
            "Contact Center Operations",
            "Director of Product",
            "Head of Localization",
            "Head of Compliance",
        ],
        search={"provider": "mock", "results_per_query": 8},
        llm={"provider": "mock", "routing_mode": "static"},
    )


def with_mock_providers(config: RadarConfig) -> RadarConfig:
    """Return `config` with both providers forced to mock.

    Lets a user shape the demo with their own brand, keywords, and taxonomy
    while guaranteeing nothing reaches a billable API — the file may name
    live providers and still cost nothing.
    """
    return config.model_copy(
        update={
            "search": config.search.model_copy(update={"provider": "mock"}),
            "llm": LLMConfig(provider="mock", routing_mode="static"),
        }
    )
