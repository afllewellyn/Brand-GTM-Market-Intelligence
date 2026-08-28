# Architecture

## Design principle

> **Evidence first. Interpretation second.**

The system draws a hard line between two kinds of work:

| Deterministic Python owns | The LLM owns |
|---|---|
| Search result processing | Search-query expansion |
| URL normalization | Market trend interpretation |
| Deduplication | Buying-stage classification |
| Evidence ID assignment | Competitor GTM interpretation |
| Keyword/theme matching | GTM recommendations |
| Counts and aggregation | Executive-summary generation |
| Timestamps and persistence | |

The LLM **never** produces a signal count. It receives Python-computed
counts as read-only input, and every conclusion it draws must reference
evidence IDs (`e1`, `e2`, ...) assigned by the normalizer. If a model
hallucinates an ID, `pipeline._validate_evidence_refs` drops it and logs a
warning — invalid references are never silently trusted.

## Module map

```
src/demand_radar/
├── cli.py            Typer CLI: run / analyze / demo
├── config.py         Pydantic config models + loader
├── pipeline.py       8-stage orchestrator; stages are private and
│                  both entry points share one interpretation tail
├── run_ledger.py     Owns everything a run writes: artifact table,
│                  renditions, clearing policy, manifest, metadata
├── providers/
│   ├── llm/          LLMProvider ABC, AnthropicProvider, MockLLMProvider,
│   │                 LLMRouter, ExternalRouterProvider stub
│   └── search/       SearchProvider ABC, DataForSEOSearchProvider
│                     (production default), SerperSearchProvider,
│                     MockSearchProvider, factory
├── processing/       serp.py (shaping), normalize.py (canonical URLs,
│                     dedup, IDs), signals.py (theme taxonomy + counting)
├── prompts/          One prompt builder per LLM task
└── schemas/          Pydantic models for evidence, queries, signals, analysis
```

## Pipeline stages

1. **Load configuration** — Pydantic validation, echo brand/market/counts.
2. **Expand queries** (LLM) — seed keywords → market/intent/competitor
   queries. Saved to `output/queries.json`.
3. **Execute searches** — via the configured `SearchProvider`, with retry
   and per-query error tolerance.
4. **Normalize evidence** (Python) — canonical URLs, dedup, `e1..eN` IDs.
   Saved to `output/evidence.json` and `output/evidence.csv`.
5. **Aggregate signals** (Python) — theme counts, query-type counts, top
   domains. Saved to `output/signals.json`. *The only source of numbers.*
6. **Trend & buying-cycle analysis** (LLM) — structured JSON validated
   against `schemas/analysis.py`; evidence refs verified.
7. **GTM recommendations** (LLM) — Markdown plan with Top 3 plays.
8. **Executive summary** (LLM) — ≤500 words, labeled Observed Evidence /
   Interpretation / Recommended Action. Printed to stdout.

Every run also writes `output/run_metadata.json` (run ID, providers,
models used, row counts, timestamps).

Which files a run writes, in which formats, and which are cleared first is
described by a single table in `run_ledger.py` — see
[ADR-0001](adr/0001-run-artifacts-have-one-owner.md). Stages name what they
produce; they do not know where it lands. Because a run clears exactly the
artifacts it produces, `analyze` can never delete the `evidence.json` it
was given as input.

## Provider abstraction

Both external dependencies sit behind interfaces:

- `SearchProvider.search(query, limit)` — implemented by
  `DataForSEOSearchProvider` (production default; `DATAFORSEO_LOGIN` +
  `DATAFORSEO_PASSWORD`), `SerperSearchProvider` (supported alternative;
  `SERPER_API_KEY`), and `MockSearchProvider` (seeded synthetic results).
  SerpAPI, Tavily, or Brave adapters slot in behind the same interface.
- `LLMProvider.complete(task, prompt, model, schema, reasoning_level)` —
  implemented by `AnthropicProvider` (default) and `MockLLMProvider`.
  `OpenAIProvider`, `GeminiProvider`, `LocalProvider`, and
  `ExternalRouterProvider` can be added without touching the pipeline.

`LLMRouter` sits between the pipeline and the provider and resolves the
model per task from central config. See `docs/model_routing.md`.

## Error handling

- Missing API keys → actionable message pointing at `.env.example` and
  demo mode.
- Credential-like fields inside a config file → `ConfigError`. Keys are
  environment-only by construction, so configs are always shareable.
- Malformed config → `ConfigError` with the Pydantic validation detail.
- Search failures → exponential-backoff retries, then the query is skipped
  with a warning (a partial run beats a dead run).
- Malformed model JSON → one repair retry, then a clear `LLMError`.
- Invalid evidence references → dropped and logged.

## Historical comparison (not built)

Nothing is persisted between runs, and no code for comparing them exists.

Feeding run-over-run deltas into the trend-analysis prompt would upgrade
claims from "there are many pricing mentions" to "pricing interest is
increasing," which is the claim a GTM team actually needs. When it is
built it belongs in `processing/signals.py`, which already owns every
count in the system — see
[ADR-0002](adr/0002-no-run-history-module-yet.md).
