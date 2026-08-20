"""Command-line interface for Enterprise Demand Radar."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import typer
from dotenv import find_dotenv, load_dotenv

from .config import ConfigError, LLMConfig, RadarConfig, load_config
from .pipeline import Pipeline
from .providers.llm.base import LLMError
from .providers.llm.router import build_router
from .providers.search.base import SearchError, SearchProvider
from .providers.search.provider import get_search_provider
from .schemas.evidence import EvidenceRow

app = typer.Typer(
    add_completion=False,
    help="Search intelligence -> buying-cycle detection -> prioritized GTM actions.",
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _fail(message: str) -> None:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


@app.command()
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Path to YAML/JSON config."),
    output: Path = typer.Option("output", "--output", "-o", help="Output directory."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    """Run the full 8-stage pipeline: search -> evidence -> analysis -> GTM plan."""
    _setup_logging(verbose)
    try:
        cfg = load_config(config)
        router = build_router(cfg.llm)
        search = get_search_provider(cfg)
        Pipeline(cfg, router, search, output_dir=output).run()
    except (ConfigError, LLMError, SearchError) as exc:
        _fail(str(exc))


@app.command()
def analyze(
    input: Path = typer.Option(
        "output/evidence.json", "--input", "-i", help="Path to evidence.json."
    ),
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Optional config. Without one, analysis runs with mock providers.",
    ),
    output: Path = typer.Option("output", "--output", "-o", help="Output directory."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    """Re-run stages 5-8 (signals -> analysis -> GTM -> summary) on saved evidence."""
    _setup_logging(verbose)
    if not input.exists():
        _fail(f"Evidence file not found: {input}. Run `demand-radar run` first.")
    try:
        data = json.loads(input.read_text(encoding="utf-8"))
        rows = [EvidenceRow(**r) for r in data]
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        _fail(f"Could not parse {input}: {exc}")
        return
    if not rows:
        _fail(f"{input} contains no evidence rows.")
    try:
        if config is not None:
            cfg = load_config(config)
        else:
            typer.secho(
                "No --config given: analyzing with mock LLM (synthetic output).",
                fg=typer.colors.YELLOW,
                err=True,
            )
            cfg = _demo_config()
        router = build_router(cfg.llm)
        search = _search_provider_for_metadata(cfg)
        Pipeline(cfg, router, search, output_dir=output).analyze_only(rows)
    except (ConfigError, LLMError, SearchError) as exc:
        _fail(str(exc))


@app.command()
def demo(
    config: Path = typer.Option(
        None,
        "--config",
        "-c",
        help="Optional config to shape the demo. Providers are forced to mock, "
        "so no credentials are used even if the file names live ones.",
    ),
    output: Path = typer.Option("output", "--output", "-o", help="Output directory."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    """Run end-to-end with mock search + mock LLM. No API keys required."""
    _setup_logging(verbose)
    bar = "-" * 60
    typer.secho(
        f"{bar}\nDEMO MODE — synthetic data from MockSearchProvider and "
        f"MockLLMProvider.\nNothing below is a real market finding.\n{bar}",
        fg=typer.colors.YELLOW,
    )
    if config is not None:
        try:
            loaded = load_config(config)
            cfg = loaded.model_copy(
                update={
                    "search": loaded.search.model_copy(
                        update={"provider": "mock"}
                    ),
                    "llm": LLMConfig(provider="mock", routing_mode="static"),
                }
            )
        except ConfigError as exc:
            _fail(str(exc))
            return
        typer.secho(
            f"Config '{config}' supplies brand, keywords, competitors and themes.\n"
            "Search results and all LLM text remain synthetic — the findings "
            f"below are NOT about {cfg.brand_name}.",
            fg=typer.colors.YELLOW,
        )
    else:
        cfg = _demo_config()
    router = build_router(cfg.llm)
    search = get_search_provider(cfg)
    Pipeline(cfg, router, search, output_dir=output).run()


class _UnusedSearchProvider(SearchProvider):
    """Records the configured provider name without needing its credentials.

    ``analyze`` replays stages 5-8 over saved evidence and never searches, so
    requiring live search credentials just to label the run would be wrong.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def search(self, query: str, limit: int = 10) -> list[dict]:
        raise SearchError("analyze does not search; it reuses saved evidence.")


def _search_provider_for_metadata(cfg: RadarConfig) -> SearchProvider:
    """Build the configured provider, or a name-only stand-in if it can't init."""
    try:
        return get_search_provider(cfg)
    except SearchError:
        return _UnusedSearchProvider(cfg.search.provider)


def _demo_config() -> RadarConfig:
    """The ElevenLabs example configuration with all providers mocked."""
    return RadarConfig(
        brand_name="ElevenLabs",
        primary_markets=["North America"],
        base_keywords=[
            "enterprise voice AI",
            "voice agents",
            "AI contact center",
            "AI phone agent",
            "multilingual voice AI",
            "voice AI compliance",
            "voice infrastructure",
        ],
        competitors=[
            "OpenAI", "PlayAI", "Speechify", "WellSaid Labs", "PolyAI", "Deepgram",
        ],
        icp_roles=[
            "Head of CX",
            "Contact Center Operations",
            "Director of Product",
            "Head of Localization",
            "Head of Compliance",
        ],
        search={"provider": "mock", "results_per_query": 8},
        llm={"provider": "mock", "routing_mode": "static"},
    )


def main() -> None:
    # Load .env before any provider reads os.environ. The README tells users
    # to put credentials in .env, so the CLI has to honor that. Real
    # environment variables win (override=False) — an explicit `export` or a
    # CI secret must beat a stale file on disk.
    load_dotenv(find_dotenv(usecwd=True), override=False)
    app()


if __name__ == "__main__":
    main()
