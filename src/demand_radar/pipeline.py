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
"""

from __future__ import annotations

import logging
from pathlib import Path

from .config import RadarConfig
from .output import (
    ensure_dir,
    new_run_id,
    write_evidence_csv,
    write_json,
    write_text,
)
from .processing.normalize import dedupe_and_assign_ids
from .processing.serp import normalize_result, utc_now_iso
from .processing.signals import aggregate_signals, load_themes
from .prompts.executive_summary import build_summary_prompt
from .prompts.gtm_recommendations import build_gtm_prompt
from .prompts.query_expansion import build_query_expansion_prompt
from .prompts.trend_analysis import build_trend_analysis_prompt
from .providers.llm.router import LLMRouter
from .providers.search.base import SearchError, SearchProvider
from .schemas.analysis import AnalysisResult
from .schemas.evidence import EvidenceRow
from .schemas.queries import QuerySet
from .schemas.signals import SignalSummary

log = logging.getLogger(__name__)


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

    # Filenames each entry point (re)writes, in write order. Cleared before
    # a run starts so a stage failure leaves visibly missing files instead
    # of silently mixing this run's partial output with a prior run's.
    _RUN_ARTIFACTS = (
        "queries.json", "evidence.json", "evidence.csv", "signals.json",
        "analysis.json", "gtm_plan.md", "executive_summary.md",
        "run_metadata.json",
    )
    _ANALYZE_ARTIFACTS = (
        "signals.json", "analysis.json", "gtm_plan.md",
        "executive_summary.md", "run_metadata.json",
    )

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
        self.out = ensure_dir(output_dir)
        self._echo = echo
        self._metadata: dict = {}

    # -- small helpers --------------------------------------------------
    def _say(self, msg: str) -> None:
        if self._echo:
            print(msg)
        log.info(msg)

    def _clear_artifacts(self, names: tuple[str, ...]) -> None:
        for name in names:
            (self.out / name).unlink(missing_ok=True)

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
        write_json(self.out / "queries.json", queries.model_dump())
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
        self._metadata["queries_run"] = queries.total()
        self._metadata["raw_results"] = len(raw)
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
        write_json(
            self.out / "evidence.json", [r.model_dump() for r in rows]
        )
        write_evidence_csv(self.out / "evidence.csv", rows)
        self._say(f"  {len(rows)} unique evidence rows (from {len(raw)} raw)")
        self._metadata["normalized_evidence_rows"] = len(rows)
        return rows

    # -- Stage 5 ------------------------------------------------------
    def stage5_aggregate(self, rows: list[EvidenceRow]) -> SignalSummary:
        self._say("[5/8] Aggregating signals (deterministic Python)...")
        themes = load_themes(self.config.themes_file)
        signals = aggregate_signals(rows, themes)
        write_json(self.out / "signals.json", signals.model_dump())
        top = list(signals.theme_counts.items())[:4]
        for name, count in top:
            self._say(f"  {name}: {count}")
        return signals

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
        write_json(self.out / "analysis.json", analysis.model_dump())
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
        write_text(self.out / "gtm_plan.md", plan_md)
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
        write_text(self.out / "executive_summary.md", summary)
        return summary

    # -- Orchestration ------------------------------------------------
    def run(self) -> str:
        """Execute all eight stages; returns the executive summary text."""
        self._clear_artifacts(self._RUN_ARTIFACTS)
        run_id = new_run_id()
        started = utc_now_iso()
        self.stage1_show_config()
        queries = self.stage2_expand_queries()
        raw = self.stage3_execute_searches(queries)
        rows = self.stage4_normalize(raw)
        signals = self.stage5_aggregate(rows)
        analysis = self.stage6_analyze(rows, signals)
        plan_md = self.stage7_gtm(signals, analysis)
        summary = self.stage8_summary(signals, analysis, plan_md)
        self._write_metadata(run_id, started)
        self._print_summary(summary)
        return summary

    def analyze_only(self, rows: list[EvidenceRow]) -> str:
        """Stages 5-8 over pre-collected evidence (``demand-radar analyze``)."""
        self._clear_artifacts(self._ANALYZE_ARTIFACTS)
        run_id = new_run_id()
        started = utc_now_iso()
        self._metadata["normalized_evidence_rows"] = len(rows)
        signals = self.stage5_aggregate(rows)
        analysis = self.stage6_analyze(rows, signals)
        plan_md = self.stage7_gtm(signals, analysis)
        summary = self.stage8_summary(signals, analysis, plan_md)
        self._write_metadata(run_id, started)
        self._print_summary(summary)
        return summary

    # -- internals ----------------------------------------------------
    def _write_metadata(self, run_id: str, started_at: str) -> None:
        models = {
            task: self.router.route(task).model
            for task in (
                "query_expansion",
                "trend_analysis",
                "gtm_recommendations",
                "executive_summary",
            )
        }
        write_json(
            self.out / "run_metadata.json",
            {
                "run_id": run_id,
                "brand": self.config.brand_name,
                "started_at": started_at,
                "completed_at": utc_now_iso(),
                "search_provider": self.search.name,
                "llm_provider": self.router.provider_name,
                "models_used": models,
                "queries_run": self._metadata.get("queries_run", 0),
                "raw_results": self._metadata.get("raw_results", 0),
                "normalized_evidence_rows": self._metadata.get(
                    "normalized_evidence_rows", 0
                ),
            },
        )

    def _print_summary(self, summary: str) -> None:
        bar = "=" * 60
        self._say(
            f"\n{bar}\nENTERPRISE DEMAND RADAR — "
            f"{self.config.brand_name.upper()}\n{bar}\n"
        )
        if self._echo:
            print(summary)
        self._say(f"\nFull report: {self.out / 'gtm_plan.md'}")
        self._say(f"Evidence: {self.out / 'evidence.csv'}")
