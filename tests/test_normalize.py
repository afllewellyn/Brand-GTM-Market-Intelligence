"""URL normalization, deduplication, and evidence ID assignment."""

from demand_radar.processing.normalize import dedupe_and_assign_ids, normalize_url
from demand_radar.processing.serp import extract_domain


def _row(url: str, **overrides) -> dict:
    base = {
        "query": "enterprise voice AI pricing",
        "query_type": "intent",
        "title": "Pricing guide",
        "snippet": "Cost and ROI breakdown",
        "url": url,
        "domain": extract_domain(url),
        "source_type": "serp",
        "competitor_name": None,
        "retrieved_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_normalize_url_strips_tracking_params():
    url = "https://Example.com/post/?utm_source=x&utm_medium=y&id=3"
    assert normalize_url(url) == "https://example.com/post?id=3"


def test_normalize_url_strips_www_fragment_and_trailing_slash():
    assert (
        normalize_url("http://www.Example.com/a/b/#section")
        == "http://example.com/a/b"
    )


def test_normalize_url_sorts_query_params():
    a = normalize_url("https://example.com/p?b=2&a=1")
    b = normalize_url("https://example.com/p?a=1&b=2")
    assert a == b


def test_dedupe_collapses_url_variants():
    rows = [
        _row("https://example.com/post?utm_source=news"),
        _row("https://www.example.com/post/"),
        _row("https://example.com/other"),
    ]
    out = dedupe_and_assign_ids(rows)
    assert len(out) == 2


def test_evidence_ids_are_sequential_and_stable():
    rows = [_row(f"https://example.com/{i}") for i in range(3)]
    out = dedupe_and_assign_ids(rows)
    assert [r.evidence_id for r in out] == ["e1", "e2", "e3"]
    # same input -> same IDs
    again = dedupe_and_assign_ids(rows)
    assert [r.evidence_id for r in again] == ["e1", "e2", "e3"]


def test_rows_without_url_are_dropped():
    out = dedupe_and_assign_ids([_row(""), _row("https://example.com/x")])
    assert len(out) == 1
