# Domain glossary

The vocabulary this codebase uses for its own concepts. One entry per term
that carries meaning beyond its ordinary English sense — if a word is used
loosely in conversation but precisely in code, it belongs here.

Terms are added when the code earns them, not in advance.

---

## Run

One execution of the pipeline for one **Configuration**. A Run has an id, a
start and completion time, a provider pair (search + LLM), and produces a
set of artifacts in the output directory.

Two shapes exist today:

- a **full Run** (`demand-radar run`) — all eight stages, starting from seed
  keywords;
- an **analyze Run** (`demand-radar analyze`) — stages 5–8 only, replayed
  over **Evidence** collected by an earlier Run.

Runs do not accumulate. Each one overwrites the output directory with a
fresh snapshot; there is no history.

## Configuration

The YAML or JSON file describing *whose* market is being scanned: brand
name, seed keywords, competitors, ICP roles, primary markets, and which
providers to use. Validated by `RadarConfig`.

Credentials are never part of a Configuration — they come from environment
variables only, and `load_config` refuses a file that embeds anything
credential-shaped. This is what makes a Configuration safe to commit and
share.

## Evidence

The deduplicated, normalized search results a Run collected — the factual
floor everything else stands on. One **Evidence row** is a single result
with a canonical URL, its originating query and query type, and a stable
**Evidence ID** (`e1`, `e2`, …) assigned in first-seen order.

Evidence IDs are the citation mechanism. Every conclusion the system draws
must reference the IDs it rests on, and an ID the model invents is dropped
rather than trusted.

## Query type

Which family a query belongs to, and therefore what its results are
evidence *of*: `market` (category trends, adoption, use cases), `intent`
(pricing, ROI, compliance, implementation — the language of a live
evaluation), or `competitor` (a named vendor's GTM activity).

The type travels with every **Evidence** row and is counted in **Signals**.
Only a `competitor` query attributes its results to a competitor: a market
query that happens to mention a vendor is evidence about the category, not
about that vendor.

## Signals

The counts computed from Evidence: theme counts, query-type counts, top
domains, totals. Deterministic Python, never the LLM.

**Signals are the only numbers that exist.** If a figure is not in
`signals.json`, the system does not know it. The LLM receives Signals as
read-only input and is instructed never to alter or invent one.

## Theme taxonomy

The keyword-to-theme mapping Signals are counted against — `pricing_roi`,
`compliance_security`, and so on. Supplied per-Configuration via
`themes_file`, with a deliberately market-agnostic fallback built in.

A taxonomy tuned to a different market still produces counts, just
meaningless ones, so a Run warns when too little Evidence matches any
theme.

## Analysis

The LLM's structured interpretation of Evidence and Signals: trends,
buying signals, and competitor moves, each carrying the Evidence IDs it
rests on. Validated against a schema, with invalid Evidence references
stripped before it is written.

Analysis is explicitly *inference*, not fact. The line between it and
Evidence is the system's central design principle: **evidence first,
interpretation second.**

## Deliverable

An output written for a person to read and forward, rather than for the
pipeline to consume — the GTM plan and the executive summary. The
distinction matters because a Deliverable is also written in a second
format for people whose tools render Markdown as raw syntax.

Contrast with the machine-facing outputs (`evidence.json`, `signals.json`,
`analysis.json`), which exist to be re-read by a later Run or inspected
directly.

## Finding

Something a Run discovers that a reader needs to act on, as distinct from
progress. Two exist today: the **Theme taxonomy** barely matched the
evidence, so the counts cannot be trusted; and a best-effort **Rendition**
could not be written.

The distinction is what a reporter's interface is built on. Progress is
free-form text on its way to a terminal. A Finding is data — it carries the
coverage percentage, or the exception — so that something other than a
terminal can act on it, and so a test can assert the condition rather than
the sentence describing it.

## Artifact

One logical output of a **Run**, identified by name rather than by
filename: `evidence`, `signals`, `gtm_plan`, `run_metadata`. Each Artifact
declares which Run modes produce it, which is what lets a Run clear exactly
the files it is about to write — and never the `evidence.json` an analyze
Run was handed as input.

## Rendition

One format an Artifact is written in. The same content, written more than
one way: `evidence` has a JSON and a CSV Rendition; `gtm_plan` has Markdown
and Word.

A Rendition is *required* or *best-effort*. A best-effort Rendition that
fails is recorded and the Run continues — reserved for formats derived from
a source of truth that is already safely on disk, so a Word rendering
problem cannot cost a Run its already-paid-for LLM and search calls.

## Manifest

The record of what a Run actually wrote — which Renditions of which
Artifacts, at which paths, and which degraded.

It exists so that nothing has to ask the filesystem what the Run itself
just did. "Was the Word twin written?" is a question about the Run, not
about the directory, and the two can disagree.

## Run Ledger

The module that owns Artifacts, Renditions, clearing, and the Manifest:
everything a Run writes to disk. Opened by an entry point, filled by the
stages, closed by `finalize()`.

It deliberately does not narrate. It records outcomes and hands them back;
deciding what a person reads about them belongs to the caller.

## Buying stage

Where a **Signal** sits in the purchase cycle: `early` (learning the
category), `mid` (evaluating economics, security, implementation), or
`late` (comparing vendors, examining proof, preparing procurement).

Proximity to `late` is the system's proxy for proximity to revenue, and
drives how GTM plays are prioritized.
