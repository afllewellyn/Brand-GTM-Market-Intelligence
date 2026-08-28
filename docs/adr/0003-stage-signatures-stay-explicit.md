# 3. Stage signatures stay explicit; no shared run-state object

Date: 2026-08-28

## Status

Accepted.

## Context

`run()` and `analyze_only()` duplicated their tail. Both called stages 5
through 8 in the same order, then wrote metadata, then printed the same
closing summary. The two paths had to be kept in step by hand, and they had
already drifted once: the pair of artifact filename tuples that
[ADR-0001](0001-run-artifacts-have-one-owner.md) removed existed precisely
because nothing tied the two entry points together.

An architecture review proposed going further — expressing the Run as an
ordered list of stage callables, with each mode defined as a slice of that
list:

```python
STAGES = [_load_config, _expand_queries, _execute_searches, ...]
for stage in STAGES[first_stage_for(mode):]:
    stage(state)
```

## Decision

Unify the duplicated tail into one private `_interpret_evidence()`, make
the eight stage methods private, and derive the `[n/8]` progress labels
from a single `STAGES` table.

**Do not introduce a shared run-state object, and do not make the stages a
list of uniform callables.**

A list of callables only works if every stage has the same signature, which
means every stage takes one state bag and mutates it. Today the signatures
are narrow and specific:

```python
_stage6_analyze(rows, signals) -> AnalysisResult
_stage7_gtm(signals, analysis) -> str
_stage8_summary(signals, analysis, plan_md) -> str
```

Each one states exactly what that stage reads and what it produces. Stage 7
cannot accidentally reach for evidence rows, because it was not given any.
A state bag would erase all of that — every stage would receive everything,
and the real dataflow would become discoverable only by reading each body
and noting which attributes it touches.

Applying the deletion test to the state bag: removing it and restoring
explicit arguments would not concentrate complexity anywhere. It would
*restore* information. That is the signature of an abstraction that is not
paying for itself.

The uniformity such a list buys is also unused. Nothing iterates the
stages: the two entry points call them in a fixed sequence, and neither
resumes from the middle, retries a stage, nor reorders anything. The
artifact set per mode is already derived — from
`run_ledger.ARTIFACTS.produced_by`, not from a stage list — so nothing
downstream needs the sequence as data either.

## Consequences

- The tail exists once. Adding or reordering a stage in the interpretation
  half is a single edit.
- The eight stage methods are private. Nothing outside `Pipeline` ever
  called them, and a public `stage5_aggregate` implied that partial
  execution was a supported entry point when it never was. Progress
  labels, artifact clearing, and the ledger lifecycle all assume a whole
  Run.
- `STAGES` gives the `[n/8]` denominator one home, replacing eight
  hardcoded label strings and the module docstring's hand-maintained copy
  of the same list.
- If a genuine iterating consumer ever appears — resume-from-stage, a
  dry-run cost estimate, per-stage timing — the tradeoff changes and this
  record should be revisited. The trigger is a real caller that needs to
  iterate, not the aesthetic appeal of a list.
