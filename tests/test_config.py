"""Configuration loading and validation."""

from pathlib import Path

import pytest

from demand_radar.config import ConfigError, load_config


def test_load_valid_yaml(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text(
        "brand_name: TestCo\n"
        "base_keywords:\n  - thing one\n"
        "search:\n  provider: mock\n"
        "llm:\n  provider: mock\n",
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.brand_name == "TestCo"
    assert cfg.llm.task("trend_analysis").reasoning_level == "medium"


def test_missing_file_raises():
    with pytest.raises(ConfigError, match="not found"):
        load_config("does/not/exist.yaml")


def test_missing_required_field_raises(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text("brand_name: TestCo\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid configuration"):
        load_config(p)


def test_malformed_yaml_raises(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text("brand_name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Could not parse"):
        load_config(p)


def test_example_config_is_valid():
    """The shipped example is a template, so it must load AND stay generic —
    it is the first file a new user copies for their own brand."""
    cfg = load_config("config/example.yaml")
    assert cfg.brand_name == "Example Corp"
    assert cfg.llm.routing_mode == "static"
    assert len(cfg.competitors) == 3
    text = Path("config/example.yaml").read_text(encoding="utf-8").lower()
    assert "elevenlabs" not in text


def test_analyze_does_not_require_search_credentials(monkeypatch):
    """`analyze` replays saved evidence and never searches.

    Requiring live search credentials just to label the run would block a
    legitimate offline re-analysis, so the provider name falls back to the
    configured value when the real provider cannot initialize.
    """
    from demand_radar.providers.search.provider import provider_for_metadata
    from demand_radar.config import load_config

    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)

    cfg = load_config("config/example.yaml")
    provider = provider_for_metadata(cfg)

    assert provider.name == "dataforseo", "run metadata must still name the provider"
