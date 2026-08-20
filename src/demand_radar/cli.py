"""Command-line interface for Enterprise Demand Radar."""

from __future__ import annotations

import json
import logging
import os
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


#: Credentials the pipeline can spend against, and where each was found.
#: Populated in main() so the pre-flight can show *whose* keys are loaded — a
#: .env left in a working copy spends silently otherwise.
_CREDENTIAL_VARS = (
    "ANTHROPIC_API_KEY",
    "DATAFORSEO_LOGIN",
    "DATAFORSEO_PASSWORD",
    "SERPER_API_KEY",
)
_CREDENTIAL_SOURCES: dict[str, str] = {}


def _load_credentials() -> None:
    """Load .env, recording which variables came from it rather than the shell.

    Real environment variables win (override=False) — an explicit `export` or
    a CI secret must beat a stale file on disk.
    """
    preexisting = {v for v in _CREDENTIAL_VARS if os.environ.get(v)}
    path = find_dotenv(usecwd=True)
    load_dotenv(path, override=False)
    _CREDENTIAL_SOURCES.clear()
    for var in _CREDENTIAL_VARS:
        if not os.environ.get(var):
            continue
        _CREDENTIAL_SOURCES[var] = (
            "the shell environment" if var in preexisting else (path or ".env")
        )


def _confirm_spend(
    cfg: RadarConfig, action: str, assume_yes: bool, *, uses_search: bool = True
) -> None:
    """Require an explicit, visible authorization before billing anyone.

    `demo` is free and `run`/`analyze` are not, but nothing separated them at
    the moment of spending except which subcommand was typed — and with
    credentials loaded from .env automatically, a billed run needed no visible
    act of consent. Mock providers cannot spend, so they pass straight through.
    """
    if cfg.llm.provider == "mock" and cfg.search.provider == "mock":
        return

    bar = "=" * 64
    lines = [
        "",
        bar,
        f"THIS WILL SPEND MONEY — {action}",
        bar,
        f"  LLM provider:    {cfg.llm.provider}",
        "  Search provider: "
        + (cfg.search.provider if uses_search else "not used (replays saved evidence)"),
    ]
    if _CREDENTIAL_SOURCES:
        lines.append("  Billed to whoever owns these credentials:")
        for name, origin in sorted(_CREDENTIAL_SOURCES.items()):
            lines.append(f"    {name:<24} from {origin}")
    lines.append(bar)
    typer.echo("\n".join(lines))

    if assume_yes:
        typer.secho("Authorized by --yes. Proceeding.\n", fg=typer.colors.YELLOW)
        return

    # A cron job or CI step has nobody to ask, so consent cannot be inferred
    # from silence — stopping is the only safe reading.
    if not sys.stdin.isatty():
        _fail(
            "Refusing to spend without confirmation in a non-interactive session.\n"
            "  Pass --yes to authorize, or run `demand-radar demo` to exercise "
            "the full pipeline for free."
        )

    if not typer.confirm("Proceed?", default=False):
        _fail(
            "Aborted before any call was made — nothing was spent.\n"
            "  `demand-radar demo` runs the same pipeline on mock providers."
        )


@app.command()
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Path to YAML/JSON config."),
    output: Path = typer.Option("output", "--output", "-o", help="Output directory."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Authorize spending without prompting."
    ),
) -> None:
    """Run the full 8-stage pipeline: search -> evidence -> analysis -> GTM plan."""
    _setup_logging(verbose)
    try:
        cfg = load_config(config)
        _confirm_spend(cfg, "demand-radar run", yes)
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
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Authorize spending without prompting."
    ),
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
        _confirm_spend(cfg, "demand-radar analyze", yes, uses_search=False)
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


#: Taxonomy for the demo's voice-AI market. Lives in the package, not in
#: config/, because config/ holds files users copy for their own brand and
#: nothing there should be tied to one market.
DEMO_THEMES_FILE = Path(__file__).parent / "demo_themes.yaml"


def _demo_config() -> RadarConfig:
    """The ElevenLabs example configuration with all providers mocked.

    Demo mode is the one place a real brand appears in a run: its output is
    banner-labeled synthetic, so a recognizable market makes the worked
    example easier to follow than an invented one would. Everything a user
    copies to run their own brand is market-agnostic.
    """
    return RadarConfig(
        brand_name="ElevenLabs",
        themes_file=str(DEMO_THEMES_FILE),
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
    # Credentials load before any provider reads os.environ, and before the
    # pre-flight needs to report where they came from.
    _load_credentials()
    app()


if __name__ == "__main__":
    main()
