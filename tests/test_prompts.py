"""Contract tests for the four prompt builders.

No test called a prompt builder before this file. The golden-artifact
suite looks like coverage and is not: `MockLLMProvider` returns canned
data and never reads the prompt, so every fixture in `tests/golden/` is
byte-identical whether the prompt is correct, mangled, or empty.

Prompt wording is editorial and changes often, so asserting it verbatim
buys churn. These tests guard the places a prompt is coupled to code
elsewhere, where a divergence produces a plausible deliverable rather
than an error: response skeletons against the schemas that parse them,
config fields reaching the prompt at all, the counts block and its
`theme_evidence_ids` exclusion, the competitor-naming instruction that
`attribute_competitor` depends on, and the truncation caps.

Three tests pin a list instead — the GTM sections, the summary questions,
and the counting-discipline sentences. Those are the shape of the
document a reader receives, nothing else checks them, and there is no
contract to assert in their place. A failure means "confirm you meant to
change the deliverable, then update the list here."

`test_trend_analysis_prompt.py` covers the evidence sampler underneath.
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

#: Stand-in for the model-generated `gtm_plan.md`. Carries neither the
#: brand nor the counts: the summary prompt embeds this verbatim, so
#: anything in it can satisfy an assertion aimed at the summary prompt's
#: own interpolation. Passing the real GTM prompt here, which repeats
#: both, made two `executive_summary` assertions vacuous.
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
    """The shape the model is shown must be one the parser accepts. If they
    drift, the model returns exactly what it was asked for and validation
    rejects it — at the end of a paid Run, after the searches and two prior
    LLM calls are already spent."""
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
    """Field parity, both directions. A field added to the schema but not
    the prompt is never populated — Pydantic fills the default and the
    analysis is quietly poorer; one left in the prompt after leaving the
    schema spends tokens on output that is discarded."""
    prompt = build_trend_analysis_prompt(_config(), _signals(), _rows())
    skeleton = _trailing_json(prompt, ANALYSIS_SHAPE_MARKER)

    assert set(skeleton[key][0]) == set(model.model_fields)


def test_trend_analysis_skeleton_names_every_top_level_analysis_field():
    prompt = build_trend_analysis_prompt(_config(), _signals(), _rows())
    skeleton = _trailing_json(prompt, ANALYSIS_SHAPE_MARKER)

    assert set(skeleton) == set(AnalysisResult.model_fields)


def test_query_expansion_skeleton_names_every_queryset_field():
    """Same contract, asserted differently: this skeleton uses `[...]` as a
    placeholder and is not parseable JSON, so the keys are lifted out. A
    family named in the schema but missing here is one the model never
    generates — `QuerySet` defaults it to empty, and the Run searches less
    than it reports while every downstream count stays self-consistent."""
    prompt = build_query_expansion_prompt(_config())
    shape = prompt.split("Return ONLY a JSON object:", 1)[1]

    assert set(re.findall(r'"(\w+)"\s*:', shape)) == set(QuerySet.model_fields)


# --------------------------------------------------------------------------
# 2. Configured inputs reaching the prompt
# --------------------------------------------------------------------------


def _all_prompts(config: RadarConfig) -> dict[str, str]:
    """Every prompt, each built from independent inputs.

    The summary builder takes `PLAN`, not the GTM prompt beside it: in
    production it receives model-generated Markdown, and chaining the two
    would let the GTM prompt's brand and counts satisfy assertions aimed at
    the summary prompt.
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
    """A config field that stops being interpolated has no other symptom: the
    Run completes, the artifacts are well-formed, and the deliverable
    confidently analyses a market nobody configured."""
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
    """Each of these prompts tells the model to cite counts verbatim. If the
    counts stop being embedded, that instruction points at nothing: the
    deliverable's numbers become invented while the prompt still forbids
    inventing them."""
    prompt = _all_prompts(_config())[prompt_name]

    assert '"total_evidence_rows": 42' in prompt
    assert '"pricing_roi": 17' in prompt
    assert '"competitor": 7' in prompt


@pytest.mark.parametrize("prompt_name", COUNTS_CARRYING)
def test_evidence_id_lists_are_kept_out_of_the_counts_block(prompt_name):
    """`theme_evidence_ids` is the one unbounded field on `SignalSummary`.
    A dropped `exclude=` grows all three prompts with the size of the Run
    and adds nothing usable, since the evidence rows themselves are already
    supplied where they are needed."""
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
    """The link between the prompt's instruction and the code relying on it.

    `attribute_competitor` only works because the prompt requires each
    competitor query to begin with the configured name; the two live in
    different modules with nothing connecting them. The fixture list is
    adversarial on purpose — "AI" inside "OpenAI", "Ferrolux" inside
    "Ferrolux Systems" — since overlapping names are where a containment
    check goes wrong quietly.
    """
    for name in COMPETITORS:
        query = f"{name} enterprise pricing 2026"
        assert attribute_competitor(query, COMPETITORS) == name


def test_the_prompt_asks_for_competitor_queries_to_lead_with_the_name():
    """Drop this instruction and the model writes "pricing comparison for
    enterprise voice vendors", which attributes to nobody: `competitor_name`
    empties out and competitor-move analysis loses its evidence, with every
    artifact still well-formed."""
    prompt = build_query_expansion_prompt(_config())

    assert "Begin each competitor" in prompt
    assert "exactly as listed above" in prompt


# --------------------------------------------------------------------------
# 5. Truncation
# --------------------------------------------------------------------------


def test_the_gtm_plan_excerpt_is_capped_in_the_summary_prompt():
    """The plan is model-generated and unbounded, and the summary call
    already carries the counts and the whole analysis. Without the cap, one
    verbose plan doubles the cost of the last call in the Run."""
    plan = PLAN + "x" * 20_000
    prompt = build_summary_prompt(_config(), _signals(), _analysis(), plan)

    assert PLAN_MARKER in prompt, "the plan must reach the prompt at all"
    assert "x" * 3_900 in prompt
    assert "x" * 4_001 not in prompt


def test_evidence_titles_and_snippets_are_capped_in_the_analysis_prompt():
    """Applied per row and multiplied by up to 120 rows. A snippet is
    provider-controlled text of arbitrary length, so this cap bounds the
    largest prompt in the Run."""
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
    """Labeling every statement as observation, inference, or recommendation
    is the only thing keeping a 500-word document from reading as though the
    model's inferences were measurements."""
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
