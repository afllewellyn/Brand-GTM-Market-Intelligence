# 4. Runs report events; only findings get their own event

Date: 2026-08-28

## Status

Accepted.

## Context

Everything a Run told a person went through one `Pipeline._say(str)` helper
— twenty-odd call sites — gated by an `echo: bool` constructor flag.

Most of those lines are progress: which stage started, how many rows came
back. Two are not. That the theme taxonomy barely matched the evidence, and
that a Word twin could not be rendered, are *findings*: conditions the Run
discovered that change what a reader should believe or do.

Findings had no representation beyond their own prose. The tests guarding
them reached for `capsys` and substring-matched English:

```python
assert "WARNING" in out
assert "0% of evidence matched any theme" in out
```

So rewording a message broke a test, while the condition it described —
coverage was 0% — was not stored, returned, or inspectable anywhere. A
`--json` mode or a structured run log would have had nothing to serialize.

## Decision

Stages report to a `RunReporter`. `ConsoleReporter` owns every user-facing
word; `RecordingReporter` keeps events for tests and any other in-process
caller.

**The interface stays small: `stage()` and `detail()` carry free-form
progress, and only findings get a method of their own.**

A reporter method per printed line would mean roughly fifteen methods —
`brand_loaded`, `queries_expanded`, `rows_deduplicated` — each called once,
each just a string with extra ceremony. That is a wide interface pretending
to be an abstraction: it would move the same prose behind a bigger surface
without making any condition inspectable, because a caller wanting
"how many rows?" already has the return value of the stage that counted
them.

The line is drawn at whether something is a **Finding** (see `CONTEXT.md`):
would a consumer other than a terminal want to act on it? Low taxonomy
coverage and a degraded deliverable both qualify. "Stage 4 started" does
not.

`run_complete()` takes the ledger's manifest rather than pre-rendered
pointer lines, because deciding *which* pointers to show is presentation:
the Word twin is best-effort and an analyze Run writes no evidence CSV.

Consequences of the boundary:

- `echo: bool` left `Pipeline` for `ConsoleReporter`, where it belongs —
  whether to print is a console concern. With it off, events are still
  logged, which is what a library caller wants.
- Wording is pinned once, in `tests/test_reporting.py`. Pipeline tests
  assert on events, so a copy edit breaks exactly one file.
- `capsys` no longer appears in `tests/test_mock_pipeline.py` at all.

## Consequences

- A `--json` output mode, a structured run log, or a UI progress feed is a
  new adapter rather than an edit to twenty call sites.
- A finding is addressable data. "Did this Run report low coverage, and at
  what percentage?" is answerable without parsing stdout.
- The CLI still narrates through `typer.secho` for its own messages — spend
  confirmation, the demo banner. Those belong to a different lifecycle
  (before a Run exists) and were deliberately left alone.
- If a third finding appears, it gets a method. If someone wants an event
  per progress line, this record is the argument against, and the trigger
  for revisiting it is a real consumer that needs the distinction — not
  symmetry.
