"""The authorization gate before any run that bills an account.

This is the only thing between a subcommand and someone's card, so these
tests are weighted toward the paths that must refuse.
"""

import sys

import pytest
import typer

from demand_radar import cli
from demand_radar.config import load_config


def _live():
    return load_config("config/example.yaml")


def _mock():
    return cli._demo_config()


def test_mock_providers_never_prompt(monkeypatch, capsys):
    """demo cannot spend, so it must not ask — or warn."""
    monkeypatch.setattr(
        typer, "confirm", lambda *a, **k: pytest.fail("must not prompt for mock run")
    )
    cli._confirm_spend(_mock(), "demo", assume_yes=False)
    assert "THIS WILL SPEND MONEY" not in capsys.readouterr().out


def test_non_interactive_without_yes_refuses(monkeypatch):
    """Cron and CI have nobody to ask; silence is not consent."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(typer.Exit) as exc:
        cli._confirm_spend(_live(), "run", assume_yes=False)
    assert exc.value.exit_code == 1


def test_declining_stops_before_any_call(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: False)
    with pytest.raises(typer.Exit):
        cli._confirm_spend(_live(), "run", assume_yes=False)


def test_prompt_defaults_to_no(monkeypatch):
    """Hitting enter must decline, not authorize."""
    seen = {}

    def _capture(_msg, default=None, **k):
        seen["default"] = default
        return default

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(typer, "confirm", _capture)
    with pytest.raises(typer.Exit):
        cli._confirm_spend(_live(), "run", assume_yes=False)
    assert seen["default"] is False


def test_accepting_proceeds(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: True)
    cli._confirm_spend(_live(), "run", assume_yes=False)


def test_yes_authorizes_without_a_tty(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    cli._confirm_spend(_live(), "run", assume_yes=True)
    out = capsys.readouterr().out
    assert "THIS WILL SPEND MONEY" in out, "the warning is still shown"
    assert "Authorized by --yes" in out


def test_analyze_does_not_imply_search_spend(monkeypatch, capsys):
    """analyze replays saved evidence and issues no search requests."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: True)
    cli._confirm_spend(_live(), "analyze", assume_yes=False, uses_search=False)
    assert "replays saved evidence" in capsys.readouterr().out


def test_banner_names_the_credentials_and_their_source(monkeypatch, capsys):
    """Naming the .env path is how you notice keys you did not mean to use."""
    monkeypatch.setitem(cli._CREDENTIAL_SOURCES, "ANTHROPIC_API_KEY", "/repo/.env")
    cli._confirm_spend(_live(), "run", assume_yes=True)
    out = capsys.readouterr().out
    assert "Billed to whoever owns these credentials" in out
    assert "ANTHROPIC_API_KEY" in out and "/repo/.env" in out


def test_shell_environment_is_distinguished_from_the_dotenv_file(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SERPER_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setattr(cli, "find_dotenv", lambda **k: str(env_file))

    cli._load_credentials()

    assert cli._CREDENTIAL_SOURCES["ANTHROPIC_API_KEY"] == "the shell environment"
    assert cli._CREDENTIAL_SOURCES["SERPER_API_KEY"] == str(env_file)
