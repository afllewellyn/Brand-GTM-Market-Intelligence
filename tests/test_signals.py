"""Theme matching and deterministic signal counting."""

from demand_radar.processing.normalize import dedupe_and_assign_ids
from demand_radar.processing.signals import (
    DEFAULT_THEMES,
    aggregate_signals,
    match_themes,
)


def _rows():
    raw = [
        {
            "query": "q1", "query_type": "intent",
            "title": "Enterprise voice AI pricing and ROI",
            "snippet": "Total cost of ownership and payback period.",
            "url": "https://a.example.com/1", "domain": "a.example.com",
            "source_type": "serp", "competitor_name": None,
            "retrieved_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "query": "q2", "query_type": "market",
            "title": "Voice agents in the contact center",
            "snippet": "AI agents reshape customer experience.",
            "url": "https://b.example.com/2", "domain": "b.example.com",
            "source_type": "serp", "competitor_name": None,
            "retrieved_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "query": "q3", "query_type": "competitor",
            "title": "PolyAI case study: production benchmark",
            "snippet": "Latency and accuracy results at scale.",
            "url": "https://c.example.com/3", "domain": "c.example.com",
            "source_type": "serp", "competitor_name": "PolyAI",
            "retrieved_at": "2026-01-01T00:00:00+00:00",
        },
    ]
    return dedupe_and_assign_ids(raw)


def test_match_themes_is_case_insensitive():
    themes = match_themes("Enterprise PRICING and SOC 2 review", DEFAULT_THEMES)
    assert "pricing_roi" in themes
    assert "compliance_security" in themes


def test_aggregate_counts_are_deterministic():
    rows = _rows()
    s1 = aggregate_signals(rows)
    s2 = aggregate_signals(rows)
    assert s1 == s2


def test_aggregate_counts_match_evidence_ids():
    signals = aggregate_signals(_rows())
    for theme, count in signals.theme_counts.items():
        assert count == len(signals.theme_evidence_ids[theme])


def test_aggregate_query_type_and_domain_counts():
    signals = aggregate_signals(_rows())
    assert signals.total_evidence_rows == 3
    assert signals.query_type_counts == {"intent": 1, "market": 1, "competitor": 1}
    assert signals.top_domains["a.example.com"] == 1


def test_expected_theme_hits():
    signals = aggregate_signals(_rows())
    assert signals.theme_counts["pricing_roi"] == 1
    assert signals.theme_counts["voice_agents"] >= 1
    assert signals.theme_counts["performance_validation"] == 1
