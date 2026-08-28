"""Evidence collection: run a QuerySet against a search provider.

Stage 3 is the only stage that carries real policy rather than a call and a
write: it decides the shape of the query plan, which competitor a result
belongs to, and what happens when an individual query fails. All of that
used to live inside the orchestrator, where it was reachable only by
constructing a Pipeline with a fake provider and running it end to end.

Nothing here talks to the network directly. A :class:`SearchProvider` is
passed in, which is what makes the policy testable on its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..providers.search.base import SearchError, SearchProvider
from ..schemas.queries import QuerySet
from .serp import normalize_result

log = logging.getLogger(__name__)


def attribute_competitor(query: str, competitors: list[str]) -> str | None:
    """Return the competitor a query is about, or None.

    The query-expansion prompt asks the model to begin each competitor
    query with a competitor's name exactly as configured, so a plain
    case-insensitive containment check is the right shape. Two refinements
    matter:

    **The longest match wins.** Naming the first competitor that happens to
    appear — which is what this did before — makes attribution depend on
    the order of ``competitors`` in the config file. With
    ``["AI", "OpenAI"]``, the query "OpenAI enterprise launch" was
    attributed to "AI", because "ai" is a substring of "openai" and came
    first in the list. Preferring the longest match makes the most specific
    name win regardless of config order.

    **Matching is not restricted to word boundaries.** Vendor names run
    words together ("PlayAI", "WellSaid") and carry punctuation that makes
    ``\\b`` behave unintuitively, so a boundary rule would silently drop
    real attributions. Longest-match already resolves the ambiguity that
    boundaries were needed for.

    Ties — two configured names of equal length both present — are broken
    by position in the query, then by config order, so the result is
    deterministic for a given input.
    """
    if not competitors:
        return None
    haystack = query.lower()
    matches = [
        (len(name), -haystack.index(name.lower()), -index, name)
        for index, name in enumerate(competitors)
        if name.lower() in haystack
    ]
    if not matches:
        return None
    return max(matches)[3]


@dataclass(frozen=True)
class QueryTypeTally:
    """How many of one query family were attempted, out of how many."""

    query_type: str
    attempted: int
    total: int


@dataclass(frozen=True)
class CollectionResult:
    """Raw results plus the counts a caller needs, returned rather than stashed."""

    rows: list[dict]
    queries_run: int
    tallies: tuple[QueryTypeTally, ...]


def collect_evidence(
    queries: QuerySet,
    provider: SearchProvider,
    competitors: list[str],
    limit: int,
) -> CollectionResult:
    """Search every query in ``queries`` and shape the raw results.

    A query that fails or returns nothing is logged and skipped rather than
    aborting the Run: one dead query should not cost the other forty. A Run
    that collects *nothing* is caught downstream, where the emptiness is
    unambiguous.
    """
    plan = (
        ("market", queries.market_queries, False),
        ("intent", queries.intent_queries, False),
        ("competitor", queries.competitor_queries, True),
    )
    rows: list[dict] = []
    tallies: list[QueryTypeTally] = []

    for query_type, query_list, attribute in plan:
        attempted = 0
        for query in query_list:
            competitor = (
                attribute_competitor(query, competitors) if attribute else None
            )
            try:
                results = provider.search(query, limit=limit)
            except SearchError as exc:
                log.warning("Skipping query %r: %s", query, exc)
                results = []
            if not results:
                log.info("No results for %r", query)
            rows.extend(
                normalize_result(r, query, query_type, competitor) for r in results
            )
            attempted += 1
        tallies.append(QueryTypeTally(query_type, attempted, len(query_list)))

    return CollectionResult(rows, queries.total(), tuple(tallies))
