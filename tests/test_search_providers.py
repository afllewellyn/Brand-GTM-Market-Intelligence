"""DataForSEO adapter parsing/auth behavior and credential-safety rules."""

import pytest

from demand_radar.config import ConfigError, load_config
from demand_radar.providers.search.base import SearchError
from demand_radar.providers.search.dataforseo import DataForSEOSearchProvider


def _live_response():
    return {
        "status_code": 20000,
        "status_message": "Ok.",
        "tasks": [
            {
                "status_code": 20000,
                "result": [
                    {
                        "items": [
                            {
                                "type": "organic",
                                "title": "Enterprise voice AI pricing",
                                "description": "Cost and ROI breakdown.",
                                "url": "https://example.com/pricing",
                            },
                            {"type": "people_also_ask", "title": "PAA box"},
                            {
                                "type": "organic",
                                "title": "Voice AI compliance guide",
                                "description": "SOC 2 and GDPR notes.",
                                "url": "https://example.com/compliance",
                            },
                        ]
                    }
                ],
            }
        ],
    }


def test_dataforseo_requires_env_credentials(monkeypatch):
    monkeypatch.delenv("DATAFORSEO_LOGIN", raising=False)
    monkeypatch.delenv("DATAFORSEO_PASSWORD", raising=False)
    with pytest.raises(SearchError, match="DATAFORSEO_LOGIN"):
        DataForSEOSearchProvider()


def test_dataforseo_parses_only_organic_items():
    results = DataForSEOSearchProvider._parse(_live_response(), limit=10)
    assert len(results) == 2
    assert results[0] == {
        "title": "Enterprise voice AI pricing",
        "snippet": "Cost and ROI breakdown.",
        "url": "https://example.com/pricing",
    }


def test_dataforseo_respects_limit():
    assert len(DataForSEOSearchProvider._parse(_live_response(), limit=1)) == 1


def test_dataforseo_api_error_raises():
    with pytest.raises(SearchError, match="40100"):
        DataForSEOSearchProvider._parse(
            {"status_code": 40100, "status_message": "Auth failed."}, limit=5
        )


def test_config_rejects_inline_api_key(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text(
        "brand_name: TestCo\n"
        "base_keywords:\n  - thing\n"
        "search:\n  provider: mock\n  api_key: sk-live-oops\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="environment variables"):
        load_config(p)


def test_config_rejects_nested_password(tmp_path):
    p = tmp_path / "cfg.yaml"
    p.write_text(
        "brand_name: TestCo\n"
        "base_keywords:\n  - thing\n"
        "llm:\n  provider: mock\n  password: hunter2\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="credential"):
        load_config(p)


def test_example_config_uses_dataforseo():
    cfg = load_config("config/example.yaml")
    assert cfg.search.provider == "dataforseo"
    assert cfg.search.location_code == 2840


def test_retry_does_not_sleep_after_final_attempt(monkeypatch):
    """All attempts are made, but the loop must not back off before giving up.

    Sleeping after the last attempt delays the failure by the full backoff
    with nothing left to retry — pure latency on every dead query.
    """
    import requests

    from demand_radar.providers.search import dataforseo as mod

    attempts, sleeps = [], []
    monkeypatch.setattr(mod.time, "sleep", sleeps.append)

    def boom(*args, **kwargs):
        attempts.append(1)
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(mod.requests, "post", boom)

    provider = DataForSEOSearchProvider(login="u", password="p", retries=2)
    with pytest.raises(SearchError, match="refused"):
        provider.search("voice ai pricing")

    assert len(attempts) == 3, "should still make 1 initial + 2 retry attempts"
    assert sleeps == [1, 2], "must back off between attempts only, not after the last"
