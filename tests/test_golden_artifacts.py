"""Characterization: the exact artifacts a Run writes, byte for byte.

This suite guards behaviour, not design. It pins what the pipeline produces
*today* so a change to how artifacts are written can be proven not to change
*what* is written.

Mock providers make a Run deterministic, with two exceptions that are
scrubbed rather than pinned: evidence rows carry a `retrieved_at` timestamp,
and `run_metadata.json` carries a UUID and two timestamps. The metadata file
is therefore checked for shape, not content.

THESE FIXTURES DESCRIBE THE DEMO SCENARIO
-----------------------------------------
The files in `tests/golden/` are the output of one specific Run: the one
`demand_radar.demo.demo_config()` describes, against the mock providers.
They are not a neutral sample, so editing the demo can legitimately change
them — and when it does, this suite is *supposed* to fail.

Only some of it reaches the artifacts. Measured, not assumed:

    change this                          and these fixtures move
    -----------------------------------  -----------------------------
    demo competitors                     evidence.json, evidence.csv
    demo_themes.yaml / themes_file       signals.json
    search.results_per_query             evidence.*, signals.json
    MockSearchProvider results           evidence.*, signals.json
    MockLLM._query_expansion             queries.json, evidence.*,
                                           signals.json
    MockLLM._trend_analysis              analysis.json
    MockLLM._gtm_recommendations         gtm_plan.md
    MockLLM._executive_summary           executive_summary.md
    -----------------------------------  -----------------------------
    brand_name, base_keywords,           nothing
    icp_roles, primary_markets

`_query_expansion` is the one with reach beyond its own artifact, and the
reason is easy to miss: `MockSearchProvider` derives each result from a
hash of the query string it is given. Change the canned queries and you
change the evidence they retrieve, which changes the signals counted over
it. The other three canned responses are terminal — nothing downstream
reads them.

The bottom row is not an oversight. Those four fields only ever reach
prompt text, and the mock LLM ignores its prompt entirely.

**That is a real limit on what this suite covers: it pins the artifacts a
Run writes, not the prompts it builds.** A change to prompt wording — a
dropped instruction, a mangled section list, a lost "never invent a count"
— passes here untouched, and nothing else in the suite catches it either:
no test in this repository calls any prompt builder.
`tests/test_trend_analysis_prompt.py` covers only the `_sample_evidence`
truncation helper, not the prompt it feeds. Prompt construction is
currently unguarded.

When a fixture does move:

1. Read the diff the failure prints. Confirm it is the change you intended
   and that nothing else moved with it.
2. Regenerate: ``python tests/test_golden_artifacts.py --regenerate``
3. Commit the regenerated fixtures *with* the change that caused them, so
   the two are reviewable together.

If you did **not** touch the demo config, the taxonomy, or either mock
provider and this suite fails, the pipeline's output changed. That is the
case this suite exists for: treat it as a regression until proven
otherwise, and do not regenerate to make it quiet.
"""

import json
import re
from pathlib import Path

import pytest

from demand_radar.demo import demo_config
from demand_radar.pipeline import Pipeline
from demand_radar.reporting import ConsoleReporter
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


def _stale_fixture_message(name: str) -> str:
    """Say what changed and what to do, so a failure is not a puzzle."""
    return (
        f"{name} no longer matches tests/golden/{name}.\n\n"
        f"If you changed the demo competitors, demo_themes.yaml, "
        f"results_per_query, or either mock provider, this is expected — the "
        f"demo's output genuinely changed. Review the diff above, then run:\n"
        f"    python tests/test_golden_artifacts.py --regenerate\n"
        f"and commit the regenerated fixtures alongside the change.\n\n"
        f"If you did NOT touch the demo or the mocks, the pipeline's output "
        f"changed. Treat that as a regression until proven otherwise; do not "
        f"regenerate to silence it."
    )


def _full_run(out: Path) -> Path:
    cfg = demo_config()
    Pipeline(
        cfg, build_router(cfg.llm), MockSearchProvider(), output_dir=out, reporter=ConsoleReporter(echo=False)
    ).run()
    return out


def _analyze_run(out: Path, rows: list[EvidenceRow]) -> Path:
    cfg = demo_config()
    Pipeline(
        cfg, build_router(cfg.llm), MockSearchProvider(), output_dir=out, reporter=ConsoleReporter(echo=False)
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
    assert actual == expected, _stale_fixture_message(name)


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
    own input. This pins it as end-to-end behaviour; the rule itself lives
    in the artifact table (see tests/test_run_ledger.py).
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


# -- regeneration -----------------------------------------------------------
def _regenerate() -> None:
    """Rewrite tests/golden/ from a fresh demo Run.

    Deliberately lives here rather than in a separate script: it reuses the
    same STABLE_ARTIFACTS list and the same _scrub() the assertions use, so
    the fixtures cannot drift from what they are compared against.
    """
    import shutil
    import tempfile

    workdir = Path(tempfile.mkdtemp(prefix="golden-"))
    try:
        _full_run(workdir)
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for name in STABLE_ARTIFACTS:
            written = _scrub((workdir / name).read_text(encoding="utf-8"))
            target = GOLDEN / name
            before = (
                target.read_text(encoding="utf-8") if target.exists() else None
            )
            target.write_text(written, encoding="utf-8")
            state = "unchanged" if before == written else "UPDATED"
            print(f"  {state:9} tests/golden/{name}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(
        "\nRegenerated from demo_config(). Review the diff before committing: "
        "these fixtures are the demo's output, so every change here should "
        "correspond to a change you meant to make."
    )


if __name__ == "__main__":
    import sys

    if "--regenerate" not in sys.argv:
        print(
            "This module is a pytest suite. To rewrite the fixtures it "
            "compares against:\n    python tests/test_golden_artifacts.py "
            "--regenerate"
        )
        raise SystemExit(2)
    _regenerate()
