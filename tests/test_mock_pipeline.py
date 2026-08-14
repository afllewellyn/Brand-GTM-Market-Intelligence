"""End-to-end pipeline behavior with mock providers, plus failure handling."""

import json

import pytest

from demand_radar.cli import _demo_config
from demand_radar.pipeline import Pipeline
from demand_radar.providers.llm.base import LLMProvider
from demand_radar.providers.llm.mock import MockLLMProvider
from demand_radar.providers.llm.router import LLMRouter, build_router
from demand_radar.providers.search.base import SearchError, SearchProvider
from demand_radar.providers.search.mock import MockSearchProvider
from demand_radar.schemas.queries import QuerySet


def test_mock_search_is_deterministic():
    p = MockSearchProvider()
    assert p.search("enterprise voice AI", limit=5) == p.search(
        "enterprise voice AI", limit=5
    )
    assert len(p.search("x", limit=7)) == 7


def test_mock_search_urls_are_stable_across_processes():
    """Repeated calls within one process reuse the same hash salt, so they
    can't catch a slug derived from Python's per-process-salted hash() —
    only a pinned literal value catches that regression, since the old
    implementation would print a *different* value on every fresh
    interpreter run (e.g. every CI job or every `demand-radar demo`)."""
    urls = [r["url"] for r in MockSearchProvider().search("enterprise voice AI", limit=3)]
    assert urls == [
        "https://cx-operations-review.example.com/articles/82462",
        "https://cx-operations-review.example.com/articles/19930",
        "https://market-signal-daily.example.com/articles/36832",
    ]


def test_mock_llm_query_expansion_schema():
    out = MockLLMProvider().complete("query_expansion", "prompt", schema=QuerySet)
    assert isinstance(out, QuerySet)
    assert out.total() > 0


def test_full_mock_pipeline_writes_all_artifacts(tmp_path):
    cfg = _demo_config()
    router = build_router(cfg.llm)
    pipe = Pipeline(cfg, router, MockSearchProvider(), output_dir=tmp_path, echo=False)
    summary = pipe.run()
    assert "SYNTHETIC" in summary
    for name in (
        "queries.json",
        "evidence.json",
        "evidence.csv",
        "signals.json",
        "analysis.json",
        "gtm_plan.md",
        "executive_summary.md",
        "run_metadata.json",
    ):
        assert (tmp_path / name).exists(), name

    meta = json.loads((tmp_path / "run_metadata.json").read_text())
    assert meta["brand"] == "ElevenLabs"
    assert meta["normalized_evidence_rows"] > 0
    assert meta["llm_provider"] == "mock"


def test_analysis_evidence_ids_reference_real_rows(tmp_path):
    cfg = _demo_config()
    router = build_router(cfg.llm)
    pipe = Pipeline(cfg, router, MockSearchProvider(), output_dir=tmp_path, echo=False)
    pipe.run()
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    valid_ids = {row["evidence_id"] for row in evidence}
    analysis = json.loads((tmp_path / "analysis.json").read_text())
    referenced = [
        eid
        for trend in analysis["trends"]
        for eid in trend["supporting_evidence_ids"]
    ] + [eid for sig in analysis["buying_signals"] for eid in sig["evidence_ids"]]
    assert referenced, "mock analysis should reference some evidence"
    assert set(referenced) <= valid_ids


class _BadJSONProvider(LLMProvider):
    """Always returns non-JSON garbage, to exercise failure handling."""

    name = "bad"

    def complete(self, task, prompt, model, schema=None, reasoning_level="medium"):
        if schema is None:
            return "not json"
        raise ValueError("malformed JSON from model")


def test_invalid_llm_response_surfaces_cleanly(tmp_path):
    cfg = _demo_config()
    router = LLMRouter(_BadJSONProvider(), cfg.llm)
    pipe = Pipeline(cfg, router, MockSearchProvider(), output_dir=tmp_path, echo=False)
    with pytest.raises(ValueError, match="malformed JSON"):
        pipe.run()


class _EmptySearchProvider(SearchProvider):
    """Every query returns zero results, as if credentials had expired."""

    name = "empty"

    def search(self, query, limit=10):
        return []


def test_run_aborts_when_no_evidence_collected(tmp_path):
    """A silent zero-evidence run would print a confident-looking report
    with nothing behind it — the pipeline must fail loudly instead."""
    cfg = _demo_config()
    router = build_router(cfg.llm)
    pipe = Pipeline(cfg, router, _EmptySearchProvider(), output_dir=tmp_path, echo=False)
    with pytest.raises(SearchError, match="No evidence collected"):
        pipe.run()
    assert not (tmp_path / "gtm_plan.md").exists()


def test_run_clears_stale_downstream_artifacts_before_writing(tmp_path):
    """A prior run's analysis/plan must not survive next to a failed run's
    fresh (but incomplete) evidence — that would look like one coherent,
    valid snapshot when it's actually two runs mixed together."""
    (tmp_path / "gtm_plan.md").write_text("STALE PLAN FROM A PRIOR RUN")
    (tmp_path / "run_metadata.json").write_text("STALE METADATA")

    cfg = _demo_config()
    router = build_router(cfg.llm)
    pipe = Pipeline(cfg, router, MockSearchProvider(), output_dir=tmp_path, echo=False)
    pipe.run()

    assert "STALE" not in (tmp_path / "gtm_plan.md").read_text()
    assert "STALE" not in (tmp_path / "run_metadata.json").read_text()
