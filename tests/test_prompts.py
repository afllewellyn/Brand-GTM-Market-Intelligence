"""Contract tests for the four prompt builders.

WHY THIS EXISTS
---------------
Until this file, no test in the repository called a prompt builder. The
golden-artifact suite looks like coverage but is not: `MockLLMProvider`
returns canned data and never reads the prompt it is handed, so every
golden fixture is byte-identical whether the prompt is correct, mangled,
or an empty string. A dropped instruction, a stale JSON skeleton, or a
config field that stopped being interpolated all passed the entire suite.

WHAT IS WORTH GUARDING
----------------------
Prompt wording is editorial and changes often; asserting it verbatim buys
churn, not safety. What these tests guard instead is the set of places a
prompt is *coupled to code elsewhere* — where a silent divergence produces
a plausible-looking deliverable rather than an error:

1. **Response skeletons vs. Pydantic schemas.** Each prompt that asks for
   JSON embeds a literal example of the shape it wants, and that response
   is parsed into a model. Add a field to `AnalysisResult` and forget the
   prompt and nothing fails — the model is never asked for the field, and
   Pydantic fills the default. These tests assert both directions.

2. **Configured inputs actually reaching the prompt.** A field that stops
   being interpolated means the Run analyses the wrong market with total
   confidence. Nothing downstream can detect it.

3. **The counts block.** Three prompts carry `SignalSummary` and exclude
   `theme_evidence_ids`. Dropping that exclusion pushes every evidence ID
   for every theme into the prompt.

4. **The competitor-naming instruction.** `attribute_competitor` works
   only because the query-expansion prompt tells the model to lead each
   competitor query with the name exactly as configured. Two halves of one
   contract, in two modules, with nothing connecting them.

5. **Truncation.** Caps on the plan excerpt and on evidence titles and
   snippets bound prompt size and therefore cost.

Two tests here are deliberate pinning tests — they fail on any edit to a
deliverable's section list. That is the point: those lists are the shape of
the document a reader receives, and nothing else in the repository checks
them. A failure means "confirm you meant to change the deliverable, then
update the list here," not "the test is wrong."

`test_trend_analysis_prompt.py` covers the evidence *sampler* underneath
these builders; this file covers the builders themselves.
"""

from __future__ import annotations

import json
import re

import pytest

from demand_radar.config import RadarConfig
from demand_radar.processing.collect import attribute_competitor
from demand_radar.prompts.executive_summary import build_summary_prompt
from demand_radar.prompts.gtm_recommendations import build_gtm_prompt
from demand_radar.prompts.query_expansion import build_query_expansion_prompt
from demand_radar.prompts.trend_analysis import _MAX_ROWS, build_trend_analysis_prompt
from demand_radar.schemas.analysis import (
    AnalysisResult,
    BuyingSignal,
    CompetitorMove,
    Trend,
)
from demand_radar.schemas.evidence import EvidenceRow
from demand_radar.schemas.queries import QuerySet
from demand_radar.schemas.signals import SignalSummary

# Distinctive values, so a containment assertion cannot pass by matching
# boilerplate that happens to contain the same word.
BRAND = "Zolvex"
MARKETS = ["Nordics", "DACH"]
KEYWORDS = ["quantum invoicing", "ledger reconciliation"]
COMPETITORS = ["Ferrolux", "AI", "OpenAI", "Ferrolux Systems"]
ICP_ROLES = ["Head of Treasury", "VP Controllership"]
TIMEFRAME = "fortnightly"

#: Stand-in for the model-generated `gtm_plan.md` that the summary call
#: carries for reference. Deliberately free of the brand name and the
#: counts: the summary prompt embeds this text verbatim, so anything the
#: plan happens to contain can satisfy an assertion about the summary
#: prompt's *own* interpolation and hide the fact that it was dropped.
#: Passing the real GTM prompt here — which repeats both — made the brand
#: and counts assertions for `executive_summary` vacuous.
PLAN_MARKER = "Qorvith quarterly plan body"
PLAN = f"## Market Changes\n{PLAN_MARKER}\n"


def _config(**overrides) -> RadarConfig:
    base = dict(
        brand_name=BRAND,
        primary_markets=MARKETS,
        base_keywords=KEYWORDS,
        competitors=COMPETITORS,
        icp_roles=ICP_ROLES,
        timeframe=TIMEFRAME,
        search={"provider": "mock"},
        llm={"provider": "mock"},
    )
    base.update(overrides)
    return RadarConfig(**base)


def _signals() -> SignalSummary:
    """Signals with `theme_evidence_ids` populated, so its exclusion is testable."""
    return SignalSummary(
        total_evidence_rows=42,
        theme_counts={"pricing_roi": 17, "compliance": 4},
        theme_evidence_ids={"pricing_roi": ["e1", "e2"], "compliance": ["e9"]},
        query_type_counts={"market": 20, "intent": 15, "competitor": 7},
        top_domains={"example.com": 11},
    )


def _analysis() -> AnalysisResult:
    return AnalysisResult(
        trends=[
            Trend(
                id="t1",
                name="Treasury automation",
                description="d",
                supporting_evidence_ids=["e1"],
                strength_score_1_to_10=7,
                relevance_to_brand_1_to_10=8,
                relevant_icps=["Head of Treasury"],
                time_horizon="medium",
            )
        ],
        buying_signals=[
            BuyingSignal(id="b1", description="d", stage="mid", evidence_ids=["e2"])
        ],
        competitor_moves=[
            CompetitorMove(
                competitor_name="Ferrolux",
                move_type="launch",
                description="d",
                risk_to_brand_1_to_10=5,
                opportunity_for_brand_1_to_10=6,
                evidence_ids=["e9"],
            )
        ],
    )


def _row(query_type: str, i: int, **overrides) -> EvidenceRow:
    fields = dict(
        evidence_id=f"{query_type[0]}{i}",
        query="q",
        query_type=query_type,
        title=f"title {i}",
        snippet=f"snippet {i}",
        url=f"https://example.com/{query_type}/{i}",
        domain="example.com",
        retrieved_at="2026-01-01T00:00:00+00:00",
        competitor_name="Ferrolux" if query_type == "competitor" else None,
    )
    fields.update(overrides)
    return EvidenceRow(**fields)


def _rows(n: int = 3) -> list[EvidenceRow]:
    return [_row("market", i) for i in range(n)]


# --------------------------------------------------------------------------
# 1. Response skeletons vs. the schemas that parse the response
# --------------------------------------------------------------------------


#: The line the trend-analysis prompt ends its response skeleton behind.
ANALYSIS_SHAPE_MARKER = "Return ONLY a JSON object with this exact shape:"


def _trailing_json(prompt: str, marker: str) -> dict:
    """Parse the response skeleton a prompt ends with."""
    assert marker in prompt, f"prompt no longer contains the marker {marker!r}"
    return json.loads(prompt.split(marker, 1)[1])


def test_trend_analysis_skeleton_parses_as_an_analysis_result():
    """The shape the model is shown must be a shape the parser accepts.

    If these drift, the model returns exactly what it was asked for and
    validation rejects it — at the end of a paid Run, after all the
    searches and two prior LLM calls have already been spent.
    """
    prompt = build_trend_analysis_prompt(_config(), _signals(), _rows())
    skeleton = _trailing_json(prompt, ANALYSIS_SHAPE_MARKER)

    AnalysisResult.model_validate(skeleton)


@pytest.mark.parametrize(
    "key, model",
    [
        ("trends", Trend),
        ("buying_signals", BuyingSignal),
        ("competitor_moves", CompetitorMove),
    ],
)
def test_trend_analysis_skeleton_names_every_analysis_field(key, model):
    """Field parity, in both directions.

    A field added to the schema but not the prompt is never populated: the
    model is not asked for it, Pydantic fills the default, and the analysis
    is quietly poorer with no failure anywhere. A field removed from the
    schema but left in the prompt spends tokens on output that is discarded.
    """
    prompt = build_trend_analysis_prompt(_config(), _signals(), _rows())
    skeleton = _trailing_json(prompt, ANALYSIS_SHAPE_MARKER)

    assert set(skeleton[key][0]) == set(model.model_fields)


def test_trend_analysis_skeleton_names_every_top_level_analysis_field():
    prompt = build_trend_analysis_prompt(_config(), _signals(), _rows())
    skeleton = _trailing_json(prompt, ANALYSIS_SHAPE_MARKER)

    assert set(skeleton) == set(AnalysisResult.model_fields)


def test_query_expansion_skeleton_names_every_queryset_field():
    """Same contract as above, asserted differently.

    This skeleton uses `[...]` as a placeholder, so it is not parseable
    JSON — the keys are lifted out instead. A query family named in the
    schema but missing here is a family the model never generates, and
    `QuerySet` defaults it to an empty list: the Run searches less than it
    reports and every count downstream is consistent with itself.
    """
    prompt = build_query_expansion_prompt(_config())
    shape = prompt.split("Return ONLY a JSON object:", 1)[1]

    assert set(re.findall(r'"(\w+)"\s*:', shape)) == set(QuerySet.model_fields)


# --------------------------------------------------------------------------
# 2. Configured inputs reaching the prompt
# --------------------------------------------------------------------------


def _all_prompts(config: RadarConfig) -> dict[str, str]:
    """Every prompt, each built from independent inputs.

    The summary builder takes `PLAN` rather than the GTM prompt built
    beside it. In production it receives model-generated Markdown, not a
    prompt, and chaining the two here would mean the GTM prompt's own
    brand and counts satisfy assertions aimed at the summary prompt.
    """
    signals, analysis = _signals(), _analysis()
    return {
        "query_expansion": build_query_expansion_prompt(config),
        "trend_analysis": build_trend_analysis_prompt(config, signals, _rows()),
        "gtm_recommendations": build_gtm_prompt(config, signals, analysis),
        "executive_summary": build_summary_prompt(config, signals, analysis, PLAN),
    }


def test_the_brand_is_named_in_every_prompt():
    for name, prompt in _all_prompts(_config()).items():
        assert BRAND in prompt, f"{name} prompt does not name the brand"


@pytest.mark.parametrize(
    "prompt_name, expected",
    [
        ("query_expansion", KEYWORDS + COMPETITORS + ICP_ROLES + MARKETS + [TIMEFRAME]),
        ("trend_analysis", COMPETITORS + ICP_ROLES + MARKETS),
        ("gtm_recommendations", ICP_ROLES),
    ],
)
def test_configured_inputs_reach_the_prompts_that_use_them(prompt_name, expected):
    """A config field that stops being interpolated has no other symptom.

    The Run completes, the artifacts are well-formed, and the deliverable
    confidently analyses a market the user did not configure. Nothing
    downstream can tell the difference.
    """
    prompt = _all_prompts(_config())[prompt_name]

    for value in expected:
        assert value in prompt, f"{value!r} missing from the {prompt_name} prompt"


def test_empty_optional_config_lists_are_labeled_not_blank():
    """`competitors` and `icp_roles` are optional, and an empty interpolation
    reads as a truncated prompt rather than an absent list."""
    prompt = build_query_expansion_prompt(_config(competitors=[], icp_roles=[]))

    assert "Competitors:\n- (none)" in prompt
    assert "ICP roles:\n- (none)" in prompt

    trend = build_trend_analysis_prompt(
        _config(competitors=[], icp_roles=[]), _signals(), _rows()
    )
    assert "ICP roles: unspecified." in trend
    assert "Competitors tracked: none." in trend


# --------------------------------------------------------------------------
# 3. The counts block
# --------------------------------------------------------------------------


COUNTS_CARRYING = ["trend_analysis", "gtm_recommendations", "executive_summary"]


@pytest.mark.parametrize("prompt_name", COUNTS_CARRYING)
def test_the_signal_counts_reach_the_prompts_that_cite_them(prompt_name):
    """Each of these prompts instructs the model to cite counts verbatim.

    If the counts stop being embedded, that instruction points at nothing
    and the model has only prose to work from — the numbers in the
    deliverable become invented while the prompt still forbids inventing
    them.
    """
    prompt = _all_prompts(_config())[prompt_name]

    assert '"total_evidence_rows": 42' in prompt
    assert '"pricing_roi": 17' in prompt
    assert '"competitor": 7' in prompt


@pytest.mark.parametrize("prompt_name", COUNTS_CARRYING)
def test_evidence_id_lists_are_kept_out_of_the_counts_block(prompt_name):
    """`theme_evidence_ids` is excluded from all three counts blocks.

    It is the one unbounded field on `SignalSummary` — every evidence ID
    for every theme. A dropped `exclude=` grows all three prompts with the
    size of the Run and adds nothing the model can use, since the evidence
    rows themselves are already supplied where they are needed.
    """
    prompt = _all_prompts(_config())[prompt_name]

    assert "theme_evidence_ids" not in prompt


# --------------------------------------------------------------------------
# 4. The competitor-naming instruction (paired with `attribute_competitor`)
# --------------------------------------------------------------------------


def test_competitors_are_listed_verbatim_for_the_model_to_copy():
    """Attribution matches on the configured string, so the model has to be
    shown that exact string — not a normalized or joined rendering of it."""
    prompt = build_query_expansion_prompt(_config())

    for name in COMPETITORS:
        assert f"\n- {name}\n" in prompt or prompt.endswith(f"\n- {name}")


def test_queries_shaped_as_the_prompt_demands_attribute_to_the_right_competitor():
    """The other half of the contract, asserted end to end.

    `attribute_competitor` is a containment check that only works because
    the query-expansion prompt requires each competitor query to begin with
    the configured name. The instruction lives in one module and the code
    that depends on it in another, with nothing linking them. This test is
    that link: it builds queries the way the prompt demands and asserts
    attribution recovers the name.

    The fixture list is deliberately adversarial — "AI" is a substring of
    "OpenAI", and "Ferrolux" a prefix of "Ferrolux Systems" — because
    overlapping vendor names are exactly where a containment check goes
    wrong quietly, attributing a rival's activity to the wrong company.
    """
    for name in COMPETITORS:
        query = f"{name} enterprise pricing 2026"
        assert attribute_competitor(query, COMPETITORS) == name


def test_the_prompt_asks_for_competitor_queries_to_lead_with_the_name():
    """A pinning test on one load-bearing sentence.

    Wording here is not free: drop this instruction and the model starts
    writing "pricing comparison for enterprise voice vendors", which
    attributes to nobody. The `competitor_name` column empties out, the
    competitor-move section of the analysis loses its evidence, and every
    artifact is still well-formed.
    """
    prompt = build_query_expansion_prompt(_config())

    assert "Begin each competitor" in prompt
    assert "exactly as listed above" in prompt


# --------------------------------------------------------------------------
# 5. Truncation
# --------------------------------------------------------------------------


def test_the_gtm_plan_reaches_the_summary_prompt():
    """The summary is written against the plan, not just the analysis, so
    that the two deliverables do not contradict each other."""
    prompt = build_summary_prompt(_config(), _signals(), _analysis(), PLAN)

    assert PLAN_MARKER in prompt


def test_the_gtm_plan_excerpt_is_capped_in_the_summary_prompt():
    """The summary prompt carries the plan for reference, not in full.

    The plan is model-generated and unbounded; the summary call already
    carries the counts and the whole analysis. Without the cap, one verbose
    plan doubles the cost of the last call in the Run.
    """
    plan = "x" * 20_000
    prompt = build_summary_prompt(_config(), _signals(), _analysis(), plan)

    assert "x" * 4_000 in prompt
    assert "x" * 4_001 not in prompt


def test_evidence_titles_and_snippets_are_capped_in_the_analysis_prompt():
    """Caps applied per row, multiplied by up to 120 rows.

    An uncapped snippet is provider-controlled text of arbitrary length, so
    this bounds the largest prompt in the Run.
    """
    rows = [_row("market", 0, title="T" * 300, snippet="S" * 400)]
    prompt = build_trend_analysis_prompt(_config(), _signals(), rows)

    assert "T" * 110 in prompt
    assert "T" * 111 not in prompt
    assert "S" * 180 in prompt
    assert "S" * 181 not in prompt


def test_every_row_in_the_sample_is_addressable_by_its_evidence_id():
    """The prompt requires an evidence ID for every conclusion, which the
    model can only satisfy for rows whose IDs it was actually shown."""
    rows = _rows(5)
    prompt = build_trend_analysis_prompt(_config(), _signals(), rows)

    for row in rows:
        assert f"[{row.evidence_id}]" in prompt


def test_a_truncated_evidence_sample_says_how_much_it_left_out():
    """Otherwise the model reads a partial sample as the whole Run and
    describes an absence of evidence that is really an absence of sample."""
    rows = _rows(_MAX_ROWS + 17)
    prompt = build_trend_analysis_prompt(_config(), _signals(), rows)

    assert "plus 17 more rows on disk." in prompt


def test_an_untruncated_evidence_sample_makes_no_such_claim():
    prompt = build_trend_analysis_prompt(_config(), _signals(), _rows(4))

    assert "more rows on disk" not in prompt


# --------------------------------------------------------------------------
# 6. Deliverable structure (pinning tests — see the module docstring)
# --------------------------------------------------------------------------


#: The section list `gtm_plan.md` is written against. Editing the prompt's
#: sections without editing this list fails, on purpose.
GTM_SECTIONS = (
    "## Market Changes",
    "## Buying-Cycle Signals",
    "## Top 3 GTM Plays",
    "## Content / Thought Leadership",
    "## ABM / Retargeting",
    "## Sales Enablement",
    "## Events / Field Marketing",
    "## Messaging Implications",
)

#: The fields every play in "Top 3 GTM Plays" must carry. These are what
#: make a play actionable rather than an observation; a play missing
#: "Recommended action" or "Supporting evidence IDs" reads fine and cannot
#: be executed or checked.
PLAY_FIELDS = (
    "Insight",
    "Evidence",
    "Why it matters",
    "Target ICP",
    "Buying stage",
    "Recommended action",
    "Asset required",
    "Distribution channel",
    "Expected business impact",
    "Supporting evidence IDs",
)


def test_the_gtm_prompt_asks_for_the_full_section_list():
    prompt = build_gtm_prompt(_config(), _signals(), _analysis())

    for section in GTM_SECTIONS:
        assert section in prompt

    assert prompt.count("\n## ") == len(GTM_SECTIONS), (
        "the prompt asks for a section not listed in GTM_SECTIONS — confirm the "
        "change to the deliverable is intended, then update GTM_SECTIONS"
    )


def test_the_gtm_prompt_asks_for_every_field_a_play_needs():
    prompt = build_gtm_prompt(_config(), _signals(), _analysis())

    for field in PLAY_FIELDS:
        assert field in prompt


def test_the_gtm_sections_appear_in_the_order_they_are_written_in():
    """Order is the argument the document makes: what changed, what buyers
    are doing, what to do about it, then how to execute."""
    prompt = build_gtm_prompt(_config(), _signals(), _analysis())
    positions = [prompt.index(section) for section in GTM_SECTIONS]

    assert positions == sorted(positions)


#: The questions `executive_summary.md` answers, in order. `docx_export`
#: promotes the resulting section labels to headings.
SUMMARY_QUESTIONS = (
    "What changed?",
    "What does buyer behavior suggest?",
    "Which signals appear closest to revenue?",
    "What should Marketing do?",
    "What should Sales do?",
    "What are the three most important actions now?",
)


def test_the_summary_prompt_asks_its_questions_in_order():
    prompt = build_summary_prompt(_config(), _signals(), _analysis(), PLAN)
    positions = [prompt.index(question) for question in SUMMARY_QUESTIONS]

    assert positions == sorted(positions)


def test_the_summary_prompt_asks_for_evidence_labeling():
    """Every statement is labeled as observation, inference, or recommendation.

    This is the summary's central discipline: it is the only thing keeping a
    500-word document from reading as though the model's inferences were
    measurements.
    """
    prompt = build_summary_prompt(_config(), _signals(), _analysis(), PLAN)

    for label in ("Observed Evidence", "Interpretation", "Recommended Action"):
        assert label in prompt


# --------------------------------------------------------------------------
# 7. Counting discipline
# --------------------------------------------------------------------------


def test_every_counts_carrying_prompt_forbids_inventing_numbers():
    """The counts are computed in Python and are the only real numbers in
    the Run. Each prompt that carries them says so; losing that instruction
    in an edit turns the deliverable's figures into plausible fiction, which
    no artifact check can detect because the output stays well-formed."""
    prompts = _all_prompts(_config())

    assert "never modify or invent numbers" in prompts["trend_analysis"]
    assert "never invent or adjust counts" in prompts["gtm_recommendations"]
    assert "No invented numbers." in prompts["executive_summary"]
