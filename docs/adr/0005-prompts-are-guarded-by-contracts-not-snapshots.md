# 5. Prompts are guarded by their contracts, not by snapshots

Date: 2026-08-28

## Status

Accepted.

## Context

Four modules under `src/demand_radar/prompts/` build every instruction the
Run sends to a model, and no test called any of them.

The golden-artifact suite looked like it covered them and did not.
`MockLLMProvider` returns canned data keyed on the task name and never
reads the prompt, so every fixture in `tests/golden/` is byte-identical
whether the prompt is correct, mangled, or empty. The suite guarding the
Run's output is structurally blind to the Run's input.

What that left unguarded is not typos. It is the places a prompt is
coupled to code elsewhere, each failing by producing a plausible
deliverable rather than an error:

- The JSON skeleton in `build_trend_analysis_prompt` is the shape
  `AnalysisResult` will be asked to parse.
- `attribute_competitor` is a containment check that works only because
  the query-expansion prompt tells the model to begin each competitor
  query with the configured name.
- Three prompts embed `SignalSummary` with `theme_evidence_ids` excluded —
  its one unbounded field.
- A config field that stops being interpolated has no other symptom.

## Decision

`tests/test_prompts.py` asserts the contracts a prompt participates in,
not the text it produces.

Snapshotting each prompt to a fixture was the obvious alternative and was
rejected. Prompt wording is edited deliberately and often; a snapshot
fails on every one of those edits, which trains its reader to regenerate
without looking. It is also silent about every coupling above, because a
diff cannot tell that a renamed schema field and a prompt key have drifted
apart.

**Three tests pin a list instead of asserting a contract**, and are marked
as such: the H2 sections of `gtm_plan.md`, the questions in
`executive_summary.md`, and the counting-discipline sentences. Those are
the shape of the document a reader receives, nothing else checks them, and
there is no contract to assert in their place. They fail on any edit to a
deliverable's structure, which is intended: confirm the change was meant,
then update the list.

Every test was verified by mutating the thing it guards rather than
trusted because it passed — 29 mutations, 29 caught, and 23 of 24 tests
catch something no other test does.

## Consequences

- Prompt wording stays free to change. Editing a sentence breaks nothing
  unless the sentence is doing structural work, and those are named.
- Schema drift fails in milliseconds instead of at the end of a paid Run,
  where a rejected `AnalysisResult` has already cost the searches and two
  model calls.
- These are unit tests over pure functions. They say nothing about whether
  a real model *obeys* the instructions; that needs an evaluation harness
  against a live provider, which does not exist here.
- One coupling was found and left for the repo owner to decide:
  `docx_export` promoted bare uppercase lines to headings and
  `MockLLMProvider` emitted them, but `build_summary_prompt` never asked
  for that format, so a real model's summary could render without
  headings. Since resolved in
  [ADR-0006](0006-both-deliverables-share-one-markdown-subset.md).
