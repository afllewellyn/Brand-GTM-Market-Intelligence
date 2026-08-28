"""Characterization: the exact artifacts a Run writes, byte for byte.

This suite exists to guard a refactor, not to specify desired behaviour. It
pins what the pipeline produces *today* so that a change to how artifacts
are written can be proven not to change *what* is written.

Mock providers make a Run deterministic, with two exceptions that are
scrubbed rather than pinned: evidence rows carry a `retrieved_at`
timestamp, and `run_metadata.json` carries a UUID and two timestamps. The
metadata file is therefore checked for shape, not content.
"""

import json
import re
from pathlib import Path

import pytest

from demand_radar.cli import _demo_config
from demand_radar.pipeline import Pipeline
from demand_radar.providers.llm.router import build_router
from demand_radar.providers.search.mock import MockSearchProvider
from demand_radar.schemas.evidence import EvidenceRow

GOLDEN = Path(__file__).parent / "golden"

#: Artifacts whose bytes are fully determined by the mock providers.
STABLE_ARTIFACTS = (
    "queries.json",
    "evidence.json",
    "evidence.csv",
    "signals.json",
    "analysis.json",
    "gtm_plan.md",
    "executive_summary.md",
)

#: Everything a full Run leaves in the output directory.
FULL_RUN_FILES = {
    *STABLE_ARTIFACTS,
    "gtm_plan.docx",
    "executive_summary.docx",
    "run_metadata.json",
}

#: `analyze` replays stages 5-8, so it writes neither queries nor evidence.
ANALYZE_WRITES = (
    "signals.json",
    "analysis.json",
    "gtm_plan.md",
    "executive_summary.md",
)

_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00")


def _scrub(text: str) -> str:
    """Replace wall-clock timestamps, the one volatile field in evidence."""
    return _ISO.sub("<TIMESTAMP>", text)


def _full_run(out: Path) -> Path:
    cfg = _demo_config()
    Pipeline(
        cfg, build_router(cfg.llm), MockSearchProvider(), output_dir=out, echo=False
    ).run()
    return out


def _analyze_run(out: Path, rows: list[EvidenceRow]) -> Path:
    cfg = _demo_config()
    Pipeline(
        cfg, build_router(cfg.llm), MockSearchProvider(), output_dir=out, echo=False
    ).analyze_only(rows)
    return out


# -- full run ---------------------------------------------------------------
def test_full_run_writes_exactly_these_files(tmp_path):
    _full_run(tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == FULL_RUN_FILES


@pytest.mark.parametrize("name", STABLE_ARTIFACTS)
def test_full_run_artifact_matches_golden(tmp_path, name):
    _full_run(tmp_path)
    actual = _scrub((tmp_path / name).read_text(encoding="utf-8"))
    expected = (GOLDEN / name).read_text(encoding="utf-8")
    assert actual == expected, f"{name} changed; update tests/golden/ if intended"


def test_run_metadata_has_the_documented_shape(tmp_path):
    """Values are volatile; the keys and their types are the contract."""
    _full_run(tmp_path)
    meta = json.loads((tmp_path / "run_metadata.json").read_text(encoding="utf-8"))
    assert set(meta) == {
        "run_id",
        "brand",
        "started_at",
        "completed_at",
        "search_provider",
        "llm_provider",
        "models_used",
        "queries_run",
        "raw_results",
        "normalized_evidence_rows",
    }
    assert len(meta["run_id"]) == 12
    assert meta["brand"] == "ElevenLabs"
    assert meta["search_provider"] == "mock"
    assert meta["llm_provider"] == "mock"
    assert set(meta["models_used"]) == {
        "query_expansion",
        "trend_analysis",
        "gtm_recommendations",
        "executive_summary",
    }
    for key in ("queries_run", "raw_results", "normalized_evidence_rows"):
        assert isinstance(meta[key], int) and meta[key] > 0
    assert _ISO.fullmatch(meta["started_at"])
    assert _ISO.fullmatch(meta["completed_at"])


# -- analyze run ------------------------------------------------------------
def _evidence_from_golden() -> list[EvidenceRow]:
    data = json.loads((GOLDEN / "evidence.json").read_text(encoding="utf-8"))
    return [EvidenceRow(**row) for row in data]


def test_analyze_writes_exactly_these_files(tmp_path):
    _analyze_run(tmp_path, _evidence_from_golden())
    assert {p.name for p in tmp_path.iterdir()} == {
        *ANALYZE_WRITES,
        "gtm_plan.docx",
        "executive_summary.docx",
        "run_metadata.json",
    }


@pytest.mark.parametrize("name", ANALYZE_WRITES)
def test_analyze_reproduces_the_full_runs_artifacts(tmp_path, name):
    """Stages 5-8 over the same evidence must land in the same place.

    The two entry points duplicate this tail today, so agreement between
    them is a property worth pinning before anything unifies them.
    """
    _analyze_run(tmp_path, _evidence_from_golden())
    actual = _scrub((tmp_path / name).read_text(encoding="utf-8"))
    assert actual == (GOLDEN / name).read_text(encoding="utf-8")


def test_analyze_does_not_delete_the_evidence_it_reads(tmp_path):
    """`analyze --input output/evidence.json` reads the directory it writes.

    Clearing evidence.json before an analyze Run would destroy that Run's
    own input. Today the rule survives only as an absence from
    `_ANALYZE_ARTIFACTS`; this pins it as behaviour.
    """
    _full_run(tmp_path)
    before = (tmp_path / "evidence.json").read_bytes()
    _analyze_run(tmp_path, _evidence_from_golden())
    assert (tmp_path / "evidence.json").read_bytes() == before
    assert (tmp_path / "evidence.csv").exists()


def test_a_stale_artifact_is_cleared_not_left_behind(tmp_path):
    """A failed or partial Run must not blend into the next one's output."""
    _full_run(tmp_path)
    (tmp_path / "signals.json").write_text("STALE", encoding="utf-8")
    (tmp_path / "queries.json").write_text("STALE", encoding="utf-8")
    _full_run(tmp_path)
    assert "STALE" not in (tmp_path / "signals.json").read_text(encoding="utf-8")
    assert "STALE" not in (tmp_path / "queries.json").read_text(encoding="utf-8")
