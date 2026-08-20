# Workflow

## Full run (live providers)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# primary production search provider:
export DATAFORSEO_LOGIN=... DATAFORSEO_PASSWORD=...
# (alternative: export SERPER_API_KEY=... with search.provider: serper)

demand-radar run --config config/example.yaml
```

Credentials are environment-only. The config loader rejects any config
file containing credential-like fields, so configs stay shareable.

What happens, stage by stage:

```
[1/8] Configuration loaded
  Brand: Example Corp
  Market: North America
  Competitors: 3
  Seed topics: 7
[2/8] Expanding queries with LLM...
[3/8] Collecting search evidence...
  Market queries: 6/6
  Intent queries: 6/6
  Competitor queries: 8/8
  200 raw results collected
[4/8] Normalizing and deduplicating evidence...
[5/8] Aggregating signals (deterministic Python)...
[6/8] Trend & buying-cycle analysis (LLM)...
[7/8] Generating GTM recommendations (LLM)...
[8/8] Writing executive summary (LLM)...
```

## Re-analyze saved evidence

Evidence collection is the slow, rate-limited part. Once
`output/evidence.json` exists you can iterate on analysis alone:

```bash
demand-radar analyze --input output/evidence.json --config config/example.yaml
```

Without `--config`, analysis runs against the mock LLM (clearly labeled
synthetic output) — useful for testing prompt or taxonomy changes offline.

## Demo (no credentials)

```bash
demand-radar demo
```

Runs the entire pipeline with `MockSearchProvider` and `MockLLMProvider`.
Output is realistic in shape and clearly labeled synthetic in content.

## Outputs

| File | Producer | Contents |
|---|---|---|
| `output/queries.json` | LLM | Expanded market/intent/competitor queries |
| `output/evidence.json` / `.csv` | Python | Deduplicated evidence rows with IDs |
| `output/signals.json` | Python | Theme counts, query-type counts, top domains |
| `output/analysis.json` | LLM (validated) | Trends, buying signals, competitor moves |
| `output/gtm_plan.md` | LLM | Full GTM plan with Top 3 plays |
| `output/executive_summary.md` | LLM | ≤500-word summary, also printed to stdout |
| `output/run_metadata.json` | Python | Run ID, providers, models, counts, timing |

## Buying-stage definitions

- **Early** — the buyer is learning about the category, opportunity, use
  case, or strategic viability.
- **Mid** — the buyer is evaluating economics, implementation, integration,
  security, compliance, or requirements.
- **Late** — the buyer is comparing vendors, examining proof, benchmarking
  performance, consuming case studies, or preparing procurement.
