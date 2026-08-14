"""End-to-end pipeline behavior with mock providers, plus failure handling."""

import json

import pytest

from demand_radar.cli import _demo_config
from demand_radar.pipeline import Pipeline
from demand_radar.providers.llm.base import LLMProvider
from demand_radar.providers.llm.mock import MockLLMProvider
from demand_radar.providers.llm.router import LLMRouter, build_router
from demand_radar.providers.search.mock import MockSearchProvider
from demand_radar.schemas.queries import QuerySet


def test_mock_search_is_deterministic():
    p = MockSearchProvider()
    assert p.search("enterprise voice AI", limit=5) == p.search(
        "enterprise voice AI", limit=5
    )
    assert len(p.search("x", limit=7)) == 7


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
