"""Evidence sampling for the trend-analysis prompt (Stage 6).

This covers the sampler underneath the builder; `tests/test_prompts.py`
covers the four prompt builders themselves.
"""

from demand_radar.prompts.trend_analysis import _MAX_ROWS, _sample_evidence
from demand_radar.schemas.evidence import EvidenceRow


def _row(query_type: str, i: int) -> EvidenceRow:
    return EvidenceRow(
        evidence_id=f"{query_type[0]}{i}",
        query="q",
        query_type=query_type,
        title="t",
        snippet="s",
        url=f"https://example.com/{query_type}/{i}",
        domain="example.com",
        retrieved_at="2026-01-01T00:00:00+00:00",
        competitor_name="Acme" if query_type == "competitor" else None,
    )


def test_sample_evidence_preserves_all_query_types_when_truncating():
    """A positional slice of market-then-intent-then-competitor rows can
    silently drop competitor evidence entirely once market+intent alone
    exceed the cap — leaving competitor-move conclusions with nothing to
    cite. Round-robin sampling must keep every type represented."""
    rows = (
        [_row("market", i) for i in range(100)]
        + [_row("intent", i) for i in range(100)]
        + [_row("competitor", i) for i in range(10)]
    )
    sampled = _sample_evidence(rows, _MAX_ROWS)

    assert len(sampled) == _MAX_ROWS
    types = {row.query_type for row in sampled}
    assert types == {"market", "intent", "competitor"}
    assert sum(1 for row in sampled if row.query_type == "competitor") == 10


def test_sample_evidence_is_a_no_op_under_the_cap():
    rows = [_row("market", i) for i in range(5)]
    assert _sample_evidence(rows, _MAX_ROWS) == rows
