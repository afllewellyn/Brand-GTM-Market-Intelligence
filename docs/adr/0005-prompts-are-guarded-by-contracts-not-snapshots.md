# 5. Prompts are guarded by their contracts, not by snapshots

Date: 2026-08-28

## Status

Accepted.

## Context

Four modules under `src/demand_radar/prompts/` build every instruction the
Run sends to a model, and until now **no test in the repository called any
of them**.

The golden-artifact suite looked like it covered them and did not.
`MockLLMProvider` returns canned data keyed on the task name and never
reads the prompt it is handed, so every fixture in `tests/golden/` is
byte-identical whether the prompt is correct, mangled, or the empty
string. The suite that guards the Run's output is structurally blind to
the Run's input.

What that left unguarded is not typos. It is the set of places a prompt is
coupled to code somewhere else:

- The JSON skeleton in `build_trend_analysis_prompt` is the shape
  `AnalysisResult` will be asked to parse. Add a field to the schema and
  forget the prompt, and the model is never asked for it: Pydantic fills
  the default and the analysis is quietly poorer.
- `attribute_competitor` is a containment check that works only because
  the query-expansion prompt tells the model to begin each competitor
  query with the configured name. Two halves of one contract, in two
  modules, with nothing connecting them.
- Every counts-carrying prompt embeds `SignalSummary` with
  `theme_evidence_ids` excluded — the one unbounded field on the model.
- A config field that stops being interpolated has no other symptom. The
  Run completes, the artifacts are well-formed, and the deliverable
  analyses a market nobody configured.

Each failure produces a plausible-looking deliverable rather than an
error, which is why nothing downstream catches them.

## Decision

`tests/test_prompts.py` asserts the **contracts** a prompt participates
in, not the text it produces.

The obvious alternative — snapshot each prompt to a fixture and diff — was
rejected. Prompt wording is edited deliberately and often; a snapshot
fails on every one of those edits, and a suite that always fails for
expected reasons trains its reader to regenerate without looking. It would
also be redundant with the golden fixtures in the one place it did work,
and silent about all four couplings above, because a diff cannot tell that
a renamed schema field and a prompt key have drifted apart.

So the tests read the prompt for the specific things that must be true:

- **Skeleton/schema parity**, in both directions, by parsing the embedded
  JSON and comparing key sets with `model_fields`.
- **Configured inputs reaching the prompt**, with distinctive fixture
  values so containment cannot pass by accident.
- **The counts block** present, and `theme_evidence_ids` absent.
- **The competitor-naming instruction**, asserted end to end: queries
  shaped the way the prompt demands are fed through
  `attribute_competitor` and must come back attributed. The fixture list
  is adversarial on purpose — `"AI"` inside `"OpenAI"`, `"Ferrolux"`
  inside `"Ferrolux Systems"`.
- **Truncation caps** on the plan excerpt, titles, and snippets, which
  bound the cost of the largest calls in the Run.

**Two tests are deliberate pinning tests** and are marked as such: the H2
section list of `gtm_plan.md` and the question list of
`executive_summary.md`. These are the shape of the document a reader
receives, nothing else in the repository checks them, and there is no
contract to assert instead — only the list itself. They fail on any edit
to the deliverable's structure, which is the intended behavior: confirm
the change was meant, then update the list in the test. The same reasoning
covers the three counting-discipline instructions, whose wording is
load-bearing because losing them turns the deliverable's figures into
fiction that no artifact check can detect.

Every test was verified to fail against a mutation of the thing it
guards — ten mutations, ten caught — rather than trusted because it
passed.

## Consequences

- Prompt wording stays free to change. Editing a sentence breaks nothing
  unless the sentence is one of the few doing structural work, and those
  are named explicitly with the reason attached.
- Schema drift now fails at import-time cost instead of at the end of a
  paid Run, where a rejected `AnalysisResult` has already cost the
  searches and two prior model calls.
- The suite is honest about the pinning tests rather than disguising them
  as behavioural ones. A reader who hits one knows what to do.
- These are unit tests over pure functions; they say nothing about whether
  a real model *obeys* the instructions. That needs an evaluation harness
  against a live provider, which is a different kind of test with a
  different cost, and does not exist here.
- One coupling was found and deliberately left alone: `docx_export`
  promotes bare uppercase lines to headings, and `MockLLMProvider` emits
  them, but `build_summary_prompt` never asks for that format. A real
  model's summary may render without headings. Recorded here rather than
  fixed, because changing the prompt is a product decision about the
  deliverable, not a test change.
