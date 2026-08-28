"""Pipeline orchestration for Enterprise Demand Radar.

Stages
------
1. Load configuration            (Python)
2. Expand queries                (LLM)
3. Execute searches              (Python + search provider)
4. Normalize evidence            (Python — deterministic)
5. Aggregate signals             (Python — deterministic; owns ALL counts)
6. Trend & buying-cycle analysis (LLM; counts are read-only input)
7. GTM recommendations           (LLM)
8. Executive summary             (LLM)

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
from .docx_export import DocxUnavailable
from .processing.normalize import dedupe_and_assign_ids
from .processing.serp import normalize_result
from .processing.signals import aggregate_signals, load_themes
from .prompts.executive_summary import build_summary_prompt
from .prompts.gtm_recommendations import build_gtm_prompt
from .prompts.query_expansion import build_query_expansion_prompt
from .prompts.trend_analysis import build_trend_analysis_prompt
from .providers.llm.router import LLMRouter
from .providers.search.base import SearchError, SearchProvider
from .run_ledger import Manifest, RecordResult, RunLedger, RunMode, RunStats
from .schemas.analysis import AnalysisResult
from .schemas.evidence import EvidenceRow
from .schemas.queries import QuerySet
from .schemas.signals import SignalSummary

log = logging.getLogger(__name__)

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
        echo: bool = True,
    ) -> None:
        self.config = config
        self.router = router
        self.search = search
        self._output_dir = Path(output_dir)
        self._echo = echo
        self._stats = RunStats()
        self._open_ledger: RunLedger | None = None

    # -- small helpers --------------------------------------------------
    def _say(self, msg: str) -> None:
        if self._echo:
            # flush=True keeps progress ordered against errors. stdout is
            # block-buffered when piped while stderr is not, so without this a
            # failure message surfaces *above* the stage that caused it.
            print(msg, flush=True)
        log.info(msg)

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
        Run has already paid for its LLM and search calls, so this reads as
        a note rather than a failure.
        """
        for failure in result.degraded:
            if isinstance(failure.error, DocxUnavailable):
                self._say(f"  NOTE: {failure.error}")
            else:
                self._say(
                    f"  NOTE: could not write {failure.path.name} "
                    f"({failure.error}). {failure.path.stem}.md is complete "
                    f"and unaffected."
                )

    # -- Stage 1 ------------------------------------------------------
    def stage1_show_config(self) -> None:
        cfg = self.config
        self._say("[1/8] Configuration loaded")
        self._say(f"  Brand: {cfg.brand_name}")
        self._say(f"  Market: {', '.join(cfg.primary_markets)}")
        self._say(f"  Competitors: {len(cfg.competitors)}")
        self._say(f"  Seed topics: {len(cfg.base_keywords)}")

    # -- Stage 2 ------------------------------------------------------
    def stage2_expand_queries(self) -> QuerySet:
        self._say("[2/8] Expanding queries with LLM...")
        queries: QuerySet = self.router.complete(
            task="query_expansion",
            prompt=build_query_expansion_prompt(self.config),
            schema=QuerySet,
        )
        self._ledger.record("queries", queries)
        self._say(
            f"  {len(queries.market_queries)} market / "
            f"{len(queries.intent_queries)} intent / "
            f"{len(queries.competitor_queries)} competitor queries"
        )
        return queries

    # -- Stage 3 ------------------------------------------------------
    def stage3_execute_searches(self, queries: QuerySet) -> list[dict]:
        self._say("[3/8] Collecting search evidence...")
        limit = self.config.search.results_per_query
        raw: list[dict] = []
        plan = [
            ("market", queries.market_queries, None),
            ("intent", queries.intent_queries, None),
            ("competitor", queries.competitor_queries, self.config.competitors),
        ]
        for query_type, qlist, competitors in plan:
            done = 0
            for query in qlist:
                competitor = None
                if competitors:
                    competitor = next(
                        (c for c in competitors if c.lower() in query.lower()), None
                    )
                try:
                    results = self.search.search(query, limit=limit)
                except SearchError as exc:
                    log.warning("Skipping query %r: %s", query, exc)
                    results = []
                if not results:
                    log.info("No results for %r", query)
                raw.extend(
                    normalize_result(r, query, query_type, competitor)
                    for r in results
                )
                done += 1
            self._say(f"  {query_type.capitalize()} queries: {done}/{len(qlist)}")
        self._say(f"  {len(raw)} raw results collected")
        self._stats.queries_run = queries.total()
        self._stats.raw_results = len(raw)
        return raw

    # -- Stage 4 ------------------------------------------------------
    def stage4_normalize(self, raw: list[dict]) -> list[EvidenceRow]:
        self._say("[4/8] Normalizing and deduplicating evidence...")
        rows = dedupe_and_assign_ids(raw)
        if not rows:
            raise SearchError(
                "No evidence collected: every search query returned no "
                "results or failed. Check search provider credentials and "
                "connectivity before re-running — a report built on zero "
                "evidence would look valid but rest on nothing."
            )
        self._ledger.record("evidence", rows)
        self._say(f"  {len(rows)} unique evidence rows (from {len(raw)} raw)")
        self._stats.normalized_evidence_rows = len(rows)
        return rows

    # -- Stage 5 ------------------------------------------------------
    def stage5_aggregate(self, rows: list[EvidenceRow]) -> SignalSummary:
        self._say("[5/8] Aggregating signals (deterministic Python)...")
        themes = load_themes(self.config.themes_file)
        signals = aggregate_signals(rows, themes)
        self._ledger.record("signals", signals)
        top = list(signals.theme_counts.items())[:4]
        for name, count in top:
            self._say(f"  {name}: {count}")
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
        source = self.config.themes_file or "the built-in default taxonomy"
        self._say(
            f"  WARNING: only {coverage:.0%} of evidence matched any theme "
            f"(from {source}).\n"
            f"  Theme counts above are unreliable for {self.config.brand_name}. "
            f"Set themes_file in your config to a taxonomy for this market."
        )

    # -- Stage 6 ------------------------------------------------------
    def stage6_analyze(
        self, rows: list[EvidenceRow], signals: SignalSummary
    ) -> AnalysisResult:
        self._say("[6/8] Trend & buying-cycle analysis (LLM)...")
        analysis: AnalysisResult = self.router.complete(
            task="trend_analysis",
            prompt=build_trend_analysis_prompt(self.config, signals, rows),
            schema=AnalysisResult,
        )
        analysis = _validate_evidence_refs(analysis, rows)
        self._ledger.record("analysis", analysis)
        self._say(
            f"  {len(analysis.trends)} trends / "
            f"{len(analysis.buying_signals)} buying signals / "
            f"{len(analysis.competitor_moves)} competitor moves"
        )
        return analysis

    # -- Stage 7 ------------------------------------------------------
    def stage7_gtm(
        self, signals: SignalSummary, analysis: AnalysisResult
    ) -> str:
        self._say("[7/8] Generating GTM recommendations (LLM)...")
        plan_md: str = self.router.complete(
            task="gtm_recommendations",
            prompt=build_gtm_prompt(self.config, signals, analysis),
        )
        self._note_degradations(self._ledger.record("gtm_plan", plan_md))
        return plan_md

    # -- Stage 8 ------------------------------------------------------
    def stage8_summary(
        self, signals: SignalSummary, analysis: AnalysisResult, plan_md: str
    ) -> str:
        self._say("[8/8] Writing executive summary (LLM)...")
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
        self.stage1_show_config()
        queries = self.stage2_expand_queries()
        raw = self.stage3_execute_searches(queries)
        rows = self.stage4_normalize(raw)
        signals = self.stage5_aggregate(rows)
        analysis = self.stage6_analyze(rows, signals)
        plan_md = self.stage7_gtm(signals, analysis)
        summary = self.stage8_summary(signals, analysis, plan_md)
        self._print_summary(summary, self._close())
        return summary

    def analyze_only(self, rows: list[EvidenceRow]) -> str:
        """Stages 5-8 over pre-collected evidence (``demand-radar analyze``)."""
        self._open(RunMode.ANALYZE)
        self._stats.normalized_evidence_rows = len(rows)
        signals = self.stage5_aggregate(rows)
        analysis = self.stage6_analyze(rows, signals)
        plan_md = self.stage7_gtm(signals, analysis)
        summary = self.stage8_summary(signals, analysis, plan_md)
        self._print_summary(summary, self._close())
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

    def _print_summary(self, summary: str, manifest: Manifest) -> None:
        bar = "=" * 60
        self._say(
            f"\n{bar}\nENTERPRISE DEMAND RADAR — "
            f"{self.config.brand_name.upper()}\n{bar}\n"
        )
        if self._echo:
            print(summary)
        # Every pointer below comes from the manifest — what this Run
        # actually wrote — rather than from probing the output directory.
        # The Word twin is best-effort, and `analyze` writes no evidence
        # CSV; naming either unconditionally would send someone looking for
        # a file that was never there.
        self._say(f"\nFull report: {manifest.path('gtm_plan', '.md')}")
        if manifest.wrote("gtm_plan", ".docx"):
            self._say(
                f"  (Word version for sharing: {manifest.path('gtm_plan', '.docx')})"
            )
        if manifest.wrote("evidence", ".csv"):
            self._say(f"Evidence: {manifest.path('evidence', '.csv')}")
