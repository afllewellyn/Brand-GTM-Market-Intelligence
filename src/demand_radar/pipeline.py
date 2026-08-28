"""Pipeline orchestration for Enterprise Demand Radar.

The stages, in order, are :data:`STAGES`. Stages 1-4 build Evidence;
stages 5-8 interpret it. A full Run does all eight; an analyze Run enters
at stage 5 with Evidence collected earlier, which is why
:meth:`Pipeline._interpret_evidence` is shared rather than written twice.

Evidence first. Interpretation second.

Stages name what they produce; they do not know where it lands, what
format it is written in, or whether a Word twin came out. That belongs to
the :class:`~demand_radar.run_ledger.RunLedger` this Pipeline opens for
each Run.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import RadarConfig
from .processing.collect import collect_evidence
from .processing.normalize import dedupe_and_assign_ids
from .processing.signals import aggregate_signals, load_themes
from .prompts.executive_summary import build_summary_prompt
from .prompts.gtm_recommendations import build_gtm_prompt
from .prompts.query_expansion import build_query_expansion_prompt
from .prompts.trend_analysis import build_trend_analysis_prompt
from .providers.llm.router import LLMRouter
from .providers.search.base import SearchError, SearchProvider
from .reporting import ConsoleReporter, RunReporter
from .run_ledger import Manifest, RecordResult, RunLedger, RunMode, RunStats
from .schemas.analysis import AnalysisResult
from .schemas.evidence import EvidenceRow
from .schemas.queries import QuerySet
from .schemas.signals import SignalSummary

log = logging.getLogger(__name__)

#: The pipeline's stages, in order. The single source of the "[n/8]"
#: progress labels — adding a stage no longer means editing eight strings —
#: and the sequence the module docstring used to restate by hand.
STAGES: tuple[str, ...] = (
    "Load configuration                (Python)",
    "Expand queries                    (LLM)",
    "Execute searches                  (Python + search provider)",
    "Normalize evidence                (Python — deterministic)",
    "Aggregate signals                 (Python — owns ALL counts)",
    "Trend & buying-cycle analysis     (LLM; counts are read-only input)",
    "GTM recommendations               (LLM)",
    "Executive summary                 (LLM)",
)

#: LLM tasks whose resolved model is recorded in the run metadata.
_ROUTED_TASKS = (
    "query_expansion",
    "trend_analysis",
    "gtm_recommendations",
    "executive_summary",
)


def _validate_evidence_refs(
    analysis: AnalysisResult, rows: list[EvidenceRow]
) -> AnalysisResult:
    """Drop any evidence ID the LLM referenced that does not exist.

    Invalid references are logged, never silently trusted. This keeps the
    "every conclusion traces to real evidence" guarantee intact even if a
    model hallucinates an ID.
    """
    valid = {row.evidence_id for row in rows}

    def clean(ids: list[str], where: str) -> list[str]:
        bad = [i for i in ids if i not in valid]
        if bad:
            log.warning("Dropping invalid evidence refs in %s: %s", where, bad)
        return [i for i in ids if i in valid]

    for trend in analysis.trends:
        trend.supporting_evidence_ids = clean(
            trend.supporting_evidence_ids, f"trend {trend.id}"
        )
    for sig in analysis.buying_signals:
        sig.evidence_ids = clean(sig.evidence_ids, f"signal {sig.id}")
    for move in analysis.competitor_moves:
        move.evidence_ids = clean(
            move.evidence_ids, f"competitor move {move.competitor_name}"
        )
    return analysis


class Pipeline:
    """Runs the eight-stage demand radar for one configuration."""

    def __init__(
        self,
        config: RadarConfig,
        router: LLMRouter,
        search: SearchProvider,
        output_dir: str | Path = "output",
        reporter: RunReporter | None = None,
    ) -> None:
        self.config = config
        self.router = router
        self.search = search
        self._output_dir = Path(output_dir)
        self._report = reporter or ConsoleReporter()
        self._stats = RunStats()
        self._open_ledger: RunLedger | None = None

    # -- small helpers --------------------------------------------------
    def _announce(self, stage: int, detail: str) -> None:
        """Report a stage start. The denominator is derived."""
        self._report.stage(stage, len(STAGES), detail)

    @property
    def _ledger(self) -> RunLedger:
        if self._open_ledger is None:
            raise RuntimeError(
                "No Run is open. Stages are executed by run() or "
                "analyze_only(), which open the ledger owning a Run's output."
            )
        return self._open_ledger

    def _note_degradations(self, result: RecordResult) -> None:
        """Report a best-effort rendition that could not be written.

        The Markdown is the source of truth and is already on disk, and the
        Run has already paid for its LLM and search calls, so this is a
        finding to report, not a failure to raise.
        """
        for failure in result.degraded:
            self._report.deliverable_degraded(
                path=failure.path, error=failure.error
            )

    # -- Stage 1 ------------------------------------------------------
    def _stage1_show_config(self) -> None:
        cfg = self.config
        self._announce(1, "Configuration loaded")
        self._report.detail(f"Brand: {cfg.brand_name}")
        self._report.detail(f"Market: {', '.join(cfg.primary_markets)}")
        self._report.detail(f"Competitors: {len(cfg.competitors)}")
        self._report.detail(f"Seed topics: {len(cfg.base_keywords)}")

    # -- Stage 2 ------------------------------------------------------
    def _stage2_expand_queries(self) -> QuerySet:
        self._announce(2, "Expanding queries with LLM...")
        queries: QuerySet = self.router.complete(
            task="query_expansion",
            prompt=build_query_expansion_prompt(self.config),
            schema=QuerySet,
        )
        self._ledger.record("queries", queries)
        self._report.detail(
            f"{len(queries.market_queries)} market / "
            f"{len(queries.intent_queries)} intent / "
            f"{len(queries.competitor_queries)} competitor queries"
        )
        return queries

    # -- Stage 3 ------------------------------------------------------
    def _stage3_execute_searches(self, queries: QuerySet) -> list[dict]:
        self._announce(3, "Collecting search evidence...")
        result = collect_evidence(
            queries,
            self.search,
            competitors=self.config.competitors,
            limit=self.config.search.results_per_query,
        )
        for tally in result.tallies:
            self._report.detail(
                f"{tally.query_type.capitalize()} queries: "
                f"{tally.attempted}/{tally.total}"
            )
        self._report.detail(f"{len(result.rows)} raw results collected")
        self._stats.queries_run = result.queries_run
        self._stats.raw_results = len(result.rows)
        return result.rows

    # -- Stage 4 ------------------------------------------------------
    def _stage4_normalize(self, raw: list[dict]) -> list[EvidenceRow]:
        self._announce(4, "Normalizing and deduplicating evidence...")
        rows = dedupe_and_assign_ids(raw)
        if not rows:
            raise SearchError(
                "No evidence collected: every search query returned no "
                "results or failed. Check search provider credentials and "
                "connectivity before re-running — a report built on zero "
                "evidence would look valid but rest on nothing."
            )
        self._ledger.record("evidence", rows)
        self._report.detail(f"{len(rows)} unique evidence rows (from {len(raw)} raw)")
        self._stats.normalized_evidence_rows = len(rows)
        return rows

    # -- Stage 5 ------------------------------------------------------
    def _stage5_aggregate(self, rows: list[EvidenceRow]) -> SignalSummary:
        self._announce(5, "Aggregating signals (deterministic Python)...")
        themes = load_themes(self.config.themes_file)
        signals = aggregate_signals(rows, themes)
        self._ledger.record("signals", signals)
        top = list(signals.theme_counts.items())[:4]
        for name, count in top:
            self._report.detail(f"{name}: {count}")
        self._warn_on_low_theme_coverage(rows, signals)
        return signals

    def _warn_on_low_theme_coverage(
        self, rows: list[EvidenceRow], signals: SignalSummary, floor: float = 0.4
    ) -> None:
        """Warn when the taxonomy barely matches the evidence.

        A theme file tuned for a different market still produces counts —
        just meaningless ones — under a correct-looking brand header. Low
        coverage is the signal that the taxonomy does not fit this run.
        """
        if not rows:
            return
        matched = {eid for ids in signals.theme_evidence_ids.values() for eid in ids}
        coverage = len(matched) / len(rows)
        if coverage >= floor:
            return
        self._report.taxonomy_coverage_low(
            coverage=coverage,
            source=self.config.themes_file or "the built-in default taxonomy",
            brand=self.config.brand_name,
        )

    # -- Stage 6 ------------------------------------------------------
    def _stage6_analyze(
        self, rows: list[EvidenceRow], signals: SignalSummary
    ) -> AnalysisResult:
        self._announce(6, "Trend & buying-cycle analysis (LLM)...")
        analysis: AnalysisResult = self.router.complete(
            task="trend_analysis",
            prompt=build_trend_analysis_prompt(self.config, signals, rows),
            schema=AnalysisResult,
        )
        analysis = _validate_evidence_refs(analysis, rows)
        self._ledger.record("analysis", analysis)
        self._report.detail(
            f"{len(analysis.trends)} trends / "
            f"{len(analysis.buying_signals)} buying signals / "
            f"{len(analysis.competitor_moves)} competitor moves"
        )
        return analysis

    # -- Stage 7 ------------------------------------------------------
    def _stage7_gtm(
        self, signals: SignalSummary, analysis: AnalysisResult
    ) -> str:
        self._announce(7, "Generating GTM recommendations (LLM)...")
        plan_md: str = self.router.complete(
            task="gtm_recommendations",
            prompt=build_gtm_prompt(self.config, signals, analysis),
        )
        self._note_degradations(self._ledger.record("gtm_plan", plan_md))
        return plan_md

    # -- Stage 8 ------------------------------------------------------
    def _stage8_summary(
        self, signals: SignalSummary, analysis: AnalysisResult, plan_md: str
    ) -> str:
        self._announce(8, "Writing executive summary (LLM)...")
        summary: str = self.router.complete(
            task="executive_summary",
            prompt=build_summary_prompt(self.config, signals, analysis, plan_md),
        )
        self._note_degradations(self._ledger.record("executive_summary", summary))
        return summary

    # -- Orchestration ------------------------------------------------
    def run(self) -> str:
        """Execute all eight stages; returns the executive summary text."""
        self._open(RunMode.FULL)
        self._stage1_show_config()
        queries = self._stage2_expand_queries()
        raw = self._stage3_execute_searches(queries)
        rows = self._stage4_normalize(raw)
        return self._interpret_evidence(rows)

    def analyze_only(self, rows: list[EvidenceRow]) -> str:
        """Stages 5-8 over pre-collected evidence (``demand-radar analyze``)."""
        self._open(RunMode.ANALYZE)
        self._stats.normalized_evidence_rows = len(rows)
        return self._interpret_evidence(rows)

    def _interpret_evidence(self, rows: list[EvidenceRow]) -> str:
        """Stages 5-8 and close-out — where both entry points converge.

        A full Run reaches here having just collected this Evidence; an
        analyze Run was handed it. Everything downstream is identical, so
        it is written once. Written twice, the two paths drifted: that is
        why two hand-copied artifact lists existed before the Run Ledger.
        """
        signals = self._stage5_aggregate(rows)
        analysis = self._stage6_analyze(rows, signals)
        plan_md = self._stage7_gtm(signals, analysis)
        summary = self._stage8_summary(signals, analysis, plan_md)
        self._report.run_complete(
            brand=self.config.brand_name, summary=summary, manifest=self._close()
        )
        return summary

    # -- internals ----------------------------------------------------
    def _open(self, mode: RunMode) -> RunLedger:
        """Open a Run: fresh counters, fresh ledger, stale artifacts cleared."""
        self._stats = RunStats()
        self._open_ledger = RunLedger(
            self._output_dir, mode, self.config.brand_name
        )
        return self._open_ledger

    def _close(self) -> Manifest:
        """Write run metadata and return what this Run produced.

        Only reached on the success path — a Run that fails mid-way leaves
        visibly missing files rather than plausible-looking metadata.
        """
        return self._ledger.finalize(
            stats=self._stats,
            search_provider=self.search.name,
            llm_provider=self.router.provider_name,
            models_used={
                task: self.router.route(task).model for task in _ROUTED_TASKS
            },
        )

