# 2. No run-history module until there is a run history

Date: 2026-08-28

## Status

Accepted.

## Context

`src/demand_radar/history.py` shipped in the initial commit as a
"foundation" for run-over-run comparison: a `HistoryStore` class whose two
methods both raised `NotImplementedError`, and a pure
`compare_theme_counts()` helper.

Nothing imported it. No test covered it. `docs/architecture.md` nevertheless
listed it in the module map, and both the README and the architecture doc
described it as an available building block — one of them claiming its
delta function was "tested by design" when no test existed.

The idea it recorded is a good one. "There are many pricing mentions" is a
weaker claim than "pricing interest is increasing," and only the second is
worth acting on. But the module contained no implementation of that idea —
only the shape one might take.

The cost was not the 56 lines. It was that the module map advertised a
capability the system does not have. A reader planning work against this
codebase would reasonably assume run history was partially built and
needed finishing, when in fact nothing existed to finish.

## Decision

Delete `history.py`. Record the intent here and in the README roadmap
instead.

When run-over-run comparison is built, it belongs in
`processing/signals.py`, not in a module of its own. That module already
owns every count in the system — the design principle is that if a number
is not in `signals.json`, it does not exist. Comparing counts across runs
is the same responsibility as producing them, and splitting the two would
put half of "the only source of numbers" in a second file.

Persistence is the part that does not exist yet, and it is a product
decision (where do past runs live? how many are kept? does `analyze` see
them?) rather than a refactor.

## Consequences

- The module map now describes only what is built.
- Anyone implementing run history starts from `processing/signals.py` and
  a persistence decision, rather than from an empty interface that
  presupposes both.
- This record exists so the next architecture review proposes *building*
  run history, rather than re-proposing the deletion of a placeholder.
