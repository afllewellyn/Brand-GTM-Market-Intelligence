"""The Run Ledger's own behaviour, tested through its interface.

These cover what used to be reachable only by driving a whole Pipeline:
which files a mode clears, what happens when a rendition fails, and what
the manifest reports afterwards.
"""

import json
import zipfile

import pytest

from demand_radar import run_ledger as ledger_mod
from demand_radar.docx_export import DocxUnavailable
from demand_radar.run_ledger import (
    ARTIFACTS,
    ArtifactSpec,
    Rendition,
    RunLedger,
    RunMode,
    RunStats,
)
from demand_radar.schemas.evidence import EvidenceRow
from demand_radar.schemas.signals import SignalSummary

FULL_FILES = {
    "queries.json",
    "evidence.json",
    "evidence.csv",
    "signals.json",
    "analysis.json",
    "gtm_plan.md",
    "gtm_plan.docx",
    "executive_summary.md",
    "executive_summary.docx",
    "run_metadata.json",
}
ANALYZE_FILES = FULL_FILES - {"queries.json", "evidence.json", "evidence.csv"}


def _rows(n=2):
    return [
        EvidenceRow(
            evidence_id=f"e{i}",
            query="q",
            query_type="market",
            title=f"t{i}",
            snippet=f"s{i}",
            url=f"https://example.com/{i}",
            domain="example.com",
            retrieved_at="2026-01-01T00:00:00+00:00",
        )
        for i in range(1, n + 1)
    ]


def _open(tmp_path, mode=RunMode.FULL, brand="Acme"):
    return RunLedger(tmp_path, mode, brand)


# -- the artifact table -----------------------------------------------------
def test_the_table_describes_exactly_the_documented_output():
    """docs/workflow.md lists these files; the table is their only source."""
    full = {
        f for s in ARTIFACTS if RunMode.FULL in s.produced_by for f in s.filenames()
    }
    analyze = {
        f for s in ARTIFACTS if RunMode.ANALYZE in s.produced_by for f in s.filenames()
    }
    assert full == FULL_FILES
    assert analyze == ANALYZE_FILES


# -- clearing ---------------------------------------------------------------
def test_opening_a_run_clears_exactly_what_that_run_will_write(tmp_path):
    for name in FULL_FILES:
        (tmp_path / name).write_text("STALE", encoding="utf-8")
    (tmp_path / "unrelated.txt").write_text("KEEP", encoding="utf-8")

    _open(tmp_path, RunMode.FULL)

    assert not any((tmp_path / n).exists() for n in FULL_FILES)
    assert (tmp_path / "unrelated.txt").read_text(encoding="utf-8") == "KEEP"


def test_an_analyze_run_can_never_delete_the_evidence_it_reads(tmp_path):
    """`analyze --input output/evidence.json` reads the directory it writes.

    This is not a special case in the ledger: a mode clears exactly what it
    produces, and evidence is produced only by a full Run.
    """
    for name in FULL_FILES:
        (tmp_path / name).write_text("PRIOR", encoding="utf-8")

    _open(tmp_path, RunMode.ANALYZE)

    assert (tmp_path / "evidence.json").read_text(encoding="utf-8") == "PRIOR"
    assert (tmp_path / "evidence.csv").read_text(encoding="utf-8") == "PRIOR"
    assert (tmp_path / "queries.json").read_text(encoding="utf-8") == "PRIOR"
    assert not (tmp_path / "signals.json").exists()


def test_opening_a_run_creates_a_missing_output_directory(tmp_path):
    target = tmp_path / "nested" / "out"
    ledger = _open(target)
    assert target.is_dir()
    assert ledger.dir == target


def test_each_run_gets_its_own_id(tmp_path):
    assert _open(tmp_path).run_id != _open(tmp_path).run_id


# -- renditions -------------------------------------------------------------
def test_one_record_call_writes_every_rendition(tmp_path):
    """Evidence is one Artifact written as JSON and CSV, from one call."""
    ledger = _open(tmp_path)
    result = ledger.record("evidence", _rows(3))

    assert {p.name for p in result.written} == {"evidence.json", "evidence.csv"}
    assert result.degraded == ()
    assert len(json.loads((tmp_path / "evidence.json").read_text())) == 3
    assert (tmp_path / "evidence.csv").read_text().startswith("evidence_id,")


def test_the_word_rendition_is_titled_with_the_brand(tmp_path):
    from docx import Document

    ledger = _open(tmp_path, brand="Acme Corp")
    ledger.record("executive_summary", "WHAT CHANGED\nSomething did.\n")

    docx = tmp_path / "executive_summary.docx"
    assert zipfile.is_zipfile(docx)
    assert "Acme Corp" in Document(str(docx)).paragraphs[0].text


def test_a_best_effort_rendition_degrades_without_losing_the_run(tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise DocxUnavailable("python-docx is not installed")

    monkeypatch.setattr(ledger_mod, "markdown_to_docx", _boom)
    ledger = _open(tmp_path)

    result = ledger.record("gtm_plan", "# Plan\n\nBody.\n")

    assert [p.name for p in result.written] == ["gtm_plan.md"]
    assert (tmp_path / "gtm_plan.md").read_text(encoding="utf-8") == "# Plan\n\nBody.\n"
    assert not (tmp_path / "gtm_plan.docx").exists()
    assert len(result.degraded) == 1
    # The exception travels, not a rendered sentence: how a failure is
    # worded for a person is the caller's decision.
    assert isinstance(result.degraded[0].error, DocxUnavailable)
    assert result.degraded[0].path.name == "gtm_plan.docx"


def test_a_required_rendition_failure_aborts_the_run(tmp_path, monkeypatch):
    def _boom(payload, path, title):
        raise OSError("disk full")

    monkeypatch.setattr(
        ledger_mod,
        "ARTIFACTS",
        (ArtifactSpec("signals", frozenset({RunMode.FULL}), (Rendition(".json", _boom),)),),
    )
    ledger = _open(tmp_path)

    with pytest.raises(OSError, match="disk full"):
        ledger.record("signals", SignalSummary())


# -- the manifest -----------------------------------------------------------
def test_the_manifest_reports_what_was_written_not_what_is_on_disk(tmp_path):
    ledger = _open(tmp_path)
    ledger.record("evidence", _rows())
    manifest = ledger.finalize(
        stats=RunStats(queries_run=4, raw_results=9, normalized_evidence_rows=2),
        search_provider="mock",
        llm_provider="mock",
        models_used={"trend_analysis": "mock-model"},
    )

    assert manifest.wrote("evidence", ".csv")
    assert manifest.path("evidence", ".csv") == tmp_path / "evidence.csv"
    assert not manifest.wrote("gtm_plan", ".md")

    # A file that appears in the directory but was not written by this Run
    # is not in its manifest.
    (tmp_path / "gtm_plan.md").write_text("planted", encoding="utf-8")
    assert not manifest.wrote("gtm_plan", ".md")


def test_asking_for_a_path_that_was_never_written_says_so(tmp_path):
    manifest = _open(tmp_path).finalize(
        stats=RunStats(),
        search_provider="mock",
        llm_provider="mock",
        models_used={},
    )
    with pytest.raises(KeyError, match="did not write gtm_plan.docx"):
        manifest.path("gtm_plan", ".docx")


def test_finalize_writes_the_metadata_the_run_accumulated(tmp_path):
    ledger = _open(tmp_path, brand="Acme")
    ledger.finalize(
        stats=RunStats(queries_run=12, raw_results=88, normalized_evidence_rows=61),
        search_provider="dataforseo",
        llm_provider="anthropic",
        models_used={"trend_analysis": "claude-sonnet-5"},
    )
    meta = json.loads((tmp_path / "run_metadata.json").read_text(encoding="utf-8"))

    assert meta["brand"] == "Acme"
    assert meta["run_id"] == ledger.run_id
    assert meta["started_at"] == ledger.started_at
    assert meta["search_provider"] == "dataforseo"
    assert (meta["queries_run"], meta["raw_results"]) == (12, 88)
    assert meta["normalized_evidence_rows"] == 61


# -- misuse -----------------------------------------------------------------
def test_recording_an_artifact_this_mode_does_not_produce_is_an_error(tmp_path):
    ledger = _open(tmp_path, RunMode.ANALYZE)
    with pytest.raises(KeyError, match="No artifact 'evidence'"):
        ledger.record("evidence", _rows())


def test_stages_cannot_write_before_a_run_is_opened(tmp_path):
    """Pipeline stages reach for a ledger; failing clearly beats AttributeError."""
    from demand_radar.cli import _demo_config
    from demand_radar.pipeline import Pipeline
    from demand_radar.providers.llm.router import build_router
    from demand_radar.providers.search.mock import MockSearchProvider

    cfg = _demo_config()
    pipe = Pipeline(
        cfg, build_router(cfg.llm), MockSearchProvider(), output_dir=tmp_path
    )
    with pytest.raises(RuntimeError, match="No Run is open"):
        pipe.stage5_aggregate(_rows())
