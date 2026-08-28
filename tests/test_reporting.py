"""ConsoleReporter's wording, pinned in the one place that owns it.

The pipeline tests assert on events. These assert on the sentences a person
actually reads — so a copy edit breaks exactly one file, and only if it
changes something a reader depends on.
"""

import logging

import pytest

from demand_radar.docx_export import DocxUnavailable
from demand_radar.reporting import ConsoleReporter, RecordingReporter, RunReporter
from demand_radar.run_ledger import RunLedger, RunMode, RunStats


@pytest.fixture
def manifest(tmp_path):
    """A finished full Run: both deliverables, both Word twins, evidence CSV."""
    ledger = RunLedger(tmp_path, RunMode.FULL, "Acme")
    ledger.record("gtm_plan", "# Plan\n\nBody.\n")
    ledger.record("executive_summary", "WHAT CHANGED\nThings.\n")
    ledger.record("evidence", [])
    return ledger.finalize(
        stats=RunStats(), search_provider="mock", llm_provider="mock", models_used={}
    )


def _out(capsys):
    return capsys.readouterr().out


# -- progress ---------------------------------------------------------------
def test_a_stage_line_carries_its_position(capsys):
    ConsoleReporter().stage(3, 8, "Collecting search evidence...")
    assert _out(capsys) == "[3/8] Collecting search evidence...\n"


def test_details_are_indented_under_their_stage(capsys):
    ConsoleReporter().detail("42 raw results collected")
    assert _out(capsys) == "  42 raw results collected\n"


# -- findings ---------------------------------------------------------------
def test_the_coverage_warning_names_the_number_the_brand_and_the_source(capsys):
    ConsoleReporter().taxonomy_coverage_low(
        coverage=0.12, source="config/themes.yaml", brand="Acme"
    )
    out = _out(capsys)
    assert "WARNING" in out
    assert "12% of evidence matched any theme" in out
    assert "unreliable for Acme" in out
    assert "config/themes.yaml" in out
    assert "Set themes_file" in out


def test_a_missing_dependency_is_reported_with_its_own_guidance(capsys, tmp_path):
    """DocxUnavailable already explains what to do; don't bury it."""
    ConsoleReporter().deliverable_degraded(
        path=tmp_path / "gtm_plan.docx",
        error=DocxUnavailable("python-docx is not installed, so install it"),
    )
    out = _out(capsys)
    assert "NOTE: python-docx is not installed, so install it" in out


def test_any_other_render_failure_says_the_markdown_survived(capsys, tmp_path):
    ConsoleReporter().deliverable_degraded(
        path=tmp_path / "gtm_plan.docx", error=ValueError("bad style")
    )
    out = _out(capsys)
    assert "could not write gtm_plan.docx (bad style)" in out
    assert "gtm_plan.md is complete and unaffected" in out


# -- completion -------------------------------------------------------------
def test_a_completed_run_prints_the_summary_and_its_pointers(capsys, manifest, tmp_path):
    ConsoleReporter().run_complete(
        brand="Acme", summary="SYNTHETIC SUMMARY BODY", manifest=manifest
    )
    out = _out(capsys)
    assert "ENTERPRISE DEMAND RADAR — ACME" in out
    assert "SYNTHETIC SUMMARY BODY" in out
    assert f"Full report: {tmp_path / 'gtm_plan.md'}" in out
    assert f"(Word version for sharing: {tmp_path / 'gtm_plan.docx'})" in out
    assert f"Evidence: {tmp_path / 'evidence.csv'}" in out


def test_nothing_points_at_a_rendition_the_run_did_not_write(capsys, tmp_path):
    """An analyze Run writes no evidence CSV, and the Word twin is best-effort."""
    ledger = RunLedger(tmp_path, RunMode.ANALYZE, "Acme")
    ledger.record("gtm_plan", "# Plan\n")
    manifest = ledger.finalize(
        stats=RunStats(), search_provider="mock", llm_provider="mock", models_used={}
    )

    ConsoleReporter().run_complete(brand="Acme", summary="body", manifest=manifest)
    out = _out(capsys)

    assert "Full report:" in out
    # The summary body legitimately contains "Observed Evidence:", so match
    # the pointer line itself rather than the substring.
    assert not any(line.startswith("Evidence:") for line in out.splitlines())


# -- echo -------------------------------------------------------------------
def test_echo_off_stays_silent_but_still_logs(capsys, caplog):
    with caplog.at_level(logging.INFO, logger="demand_radar.run"):
        ConsoleReporter(echo=False).stage(1, 8, "Configuration loaded")
    assert _out(capsys) == ""
    assert "[1/8] Configuration loaded" in caplog.text


def test_echo_off_does_not_print_the_summary_body(capsys, manifest):
    ConsoleReporter(echo=False).run_complete(
        brand="Acme", summary="SHOULD NOT APPEAR", manifest=manifest
    )
    assert _out(capsys) == ""


# -- the recording adapter --------------------------------------------------
def test_the_recording_reporter_keeps_events_instead_of_rendering(capsys, manifest):
    reporter = RecordingReporter()
    reporter.stage(5, 8, "Aggregating...")
    reporter.detail("pricing_roi: 31")
    reporter.taxonomy_coverage_low(coverage=0.4, source="s.yaml", brand="Acme")
    reporter.run_complete(brand="Acme", summary="body", manifest=manifest)

    assert reporter.stages == [(5, 8, "Aggregating...")]
    assert reporter.details == ["pricing_roi: 31"]
    assert reporter.coverage_warnings[0].coverage == 0.4
    assert reporter.completions[0].manifest is manifest
    assert _out(capsys) == ""


def test_both_adapters_satisfy_the_interface():
    assert issubclass(ConsoleReporter, RunReporter)
    assert issubclass(RecordingReporter, RunReporter)
