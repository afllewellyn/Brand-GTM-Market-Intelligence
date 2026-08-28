"""Evidence collection policy, tested without driving a whole Pipeline."""

import pytest

from demand_radar.processing.collect import (
    attribute_competitor,
    collect_evidence,
)
from demand_radar.providers.search.base import SearchError, SearchProvider
from demand_radar.schemas.queries import QuerySet

COMPETITORS = ["OpenAI", "PlayAI", "Speechify", "WellSaid Labs", "PolyAI"]


class _StubSearch(SearchProvider):
    """Records what it was asked, returns one result per query."""

    name = "stub"

    def __init__(self, fail_on=(), empty_on=()):
        self.seen: list[tuple[str, int]] = []
        self._fail = set(fail_on)
        self._empty = set(empty_on)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        self.seen.append((query, limit))
        if query in self._fail:
            raise SearchError(f"provider blew up on {query!r}")
        if query in self._empty:
            return []
        return [{"title": f"T:{query}", "snippet": "s", "url": f"https://e.com/{len(self.seen)}"}]


def _queries(market=1, intent=1, competitor=1) -> QuerySet:
    return QuerySet(
        market_queries=[f"market {i}" for i in range(market)],
        intent_queries=[f"pricing {i}" for i in range(intent)],
        competitor_queries=[f"PolyAI thing {i}" for i in range(competitor)],
    )


# -- competitor attribution -------------------------------------------------
def test_attributes_a_query_to_the_competitor_it_names():
    assert attribute_competitor("PolyAI enterprise case study", COMPETITORS) == "PolyAI"


def test_attribution_is_case_insensitive():
    assert attribute_competitor("wellsaid labs customers", COMPETITORS) == "WellSaid Labs"


def test_a_query_naming_nobody_is_attributed_to_nobody():
    assert attribute_competitor("enterprise voice AI trends", COMPETITORS) is None


def test_no_competitors_configured_attributes_nothing():
    assert attribute_competitor("OpenAI pricing", []) is None


def test_the_longest_matching_name_wins_regardless_of_config_order():
    """Regression: attribution used to name the *first* competitor that
    appeared anywhere in the query, so it depended on config order.

    With "AI" listed before "OpenAI", every OpenAI query was attributed to
    "AI" — "ai" is a substring of "openai". Competitor moves were then
    filed under the wrong vendor, in a report whose whole premise is that
    conclusions trace to real evidence.
    """
    competitors = ["AI", "OpenAI"]
    assert attribute_competitor("OpenAI voice agent launch", competitors) == "OpenAI"
    # And the reverse config order gives the same answer, which is the point.
    assert attribute_competitor("OpenAI voice agent launch", competitors[::-1]) == "OpenAI"


def test_a_shorter_name_still_wins_when_the_longer_one_is_absent():
    assert attribute_competitor("AI adoption in the enterprise", ["AI", "OpenAI"]) == "AI"


def test_equal_length_matches_resolve_by_position_in_the_query():
    assert attribute_competitor("Acme beats Beta", ["Beta", "Acme"]) == "Acme"


# -- collection -------------------------------------------------------------
def test_every_query_is_searched_with_the_configured_limit():
    search = _StubSearch()
    result = collect_evidence(_queries(2, 3, 2), search, COMPETITORS, limit=7)

    assert [q for q, _ in search.seen] == [
        "market 0", "market 1",
        "pricing 0", "pricing 1", "pricing 2",
        "PolyAI thing 0", "PolyAI thing 1",
    ]
    assert {lim for _, lim in search.seen} == {7}
    assert result.queries_run == 7
    assert len(result.rows) == 7


def test_rows_carry_their_query_type():
    result = collect_evidence(_queries(1, 1, 1), _StubSearch(), COMPETITORS, limit=5)
    assert [r["query_type"] for r in result.rows] == ["market", "intent", "competitor"]


def test_only_competitor_queries_get_a_competitor():
    """A market query that happens to mention a vendor is not a competitor row."""
    queries = QuerySet(
        market_queries=["OpenAI and the voice AI category"],
        competitor_queries=["PolyAI enterprise case study"],
    )
    result = collect_evidence(queries, _StubSearch(), COMPETITORS, limit=5)
    by_type = {r["query_type"]: r["competitor_name"] for r in result.rows}
    assert by_type == {"market": None, "competitor": "PolyAI"}


def test_one_failed_query_does_not_cost_the_others():
    search = _StubSearch(fail_on={"pricing 0"})
    result = collect_evidence(_queries(1, 2, 1), search, COMPETITORS, limit=5)

    assert len(result.rows) == 3  # four queries, one failed
    assert "pricing 0" in [q for q, _ in search.seen]


def test_a_query_returning_nothing_is_not_an_error():
    search = _StubSearch(empty_on={"market 0"})
    result = collect_evidence(_queries(1, 1, 1), search, COMPETITORS, limit=5)
    assert len(result.rows) == 2


def test_tallies_report_each_query_family():
    result = collect_evidence(_queries(2, 3, 4), _StubSearch(), COMPETITORS, limit=5)
    assert [(t.query_type, t.attempted, t.total) for t in result.tallies] == [
        ("market", 2, 2),
        ("intent", 3, 3),
        ("competitor", 4, 4),
    ]


def test_a_failed_query_still_counts_as_attempted():
    """The progress line reports queries issued, not queries that succeeded."""
    search = _StubSearch(fail_on={"market 0"})
    result = collect_evidence(_queries(1, 0, 0), search, COMPETITORS, limit=5)
    assert result.tallies[0] == result.tallies[0].__class__("market", 1, 1)


def test_an_empty_query_set_collects_nothing_without_failing():
    result = collect_evidence(QuerySet(), _StubSearch(), COMPETITORS, limit=5)
    assert result.rows == []
    assert result.queries_run == 0
    assert [t.total for t in result.tallies] == [0, 0, 0]
