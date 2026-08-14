"""Configuration loading and validation (Pydantic v2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class LLMTaskConfig(BaseModel):
    """Model + reasoning settings for a single pipeline task."""

    model: str = "claude-sonnet-5"
    reasoning_level: Literal["low", "medium", "high"] = "medium"


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "mock"] = "anthropic"
    routing_mode: Literal["static", "adaptive"] = "static"
    tasks: dict[str, LLMTaskConfig] = Field(default_factory=dict)

    def task(self, name: str) -> LLMTaskConfig:
        """Return the config for a task, falling back to defaults."""
        return self.tasks.get(name, LLMTaskConfig())


class SearchConfig(BaseModel):
    """Search settings. Credentials are NEVER part of configuration —
    they come from environment variables only (see .env.example)."""

    model_config = {"extra": "forbid"}

    provider: Literal["mock", "serper", "dataforseo"] = "mock"
    results_per_query: int = Field(default=10, ge=1, le=50)
    # DataForSEO locale settings (ignored by other providers)
    language_code: str = "en"
    location_code: int = 2840  # United States


class RadarConfig(BaseModel):
    """Top-level run configuration."""

    brand_name: str
    primary_markets: list[str] = Field(default_factory=lambda: ["North America"])
    base_keywords: list[str] = Field(min_length=1)
    competitors: list[str] = Field(default_factory=list)
    icp_roles: list[str] = Field(default_factory=list)
    timeframe: str = "weekly"
    results_per_query: int = Field(default=10, ge=1, le=50)
    themes_file: str | None = None

    search: SearchConfig = Field(default_factory=SearchConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

    @field_validator("brand_name")
    @classmethod
    def brand_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("brand_name must not be blank")
        return v.strip()


class ConfigError(RuntimeError):
    """Raised when a configuration file cannot be loaded or validated."""


def load_config(path: str | Path) -> RadarConfig:
    """Load a YAML or JSON config file and validate it."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw) if p.suffix == ".json" else yaml.safe_load(raw)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not parse {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{p} did not contain a mapping at the top level")
    _reject_inline_credentials(data, p)
    try:
        return RadarConfig(**data)
    except Exception as exc:  # pydantic.ValidationError
        raise ConfigError(f"Invalid configuration in {p}:\n{exc}") from exc


# Keys that look like credentials. Config files are meant to be shared and
# committed; secrets belong in environment variables only.
_CREDENTIAL_KEYS = {
    "api_key", "apikey", "api-key", "key", "token", "secret", "password",
    "login", "anthropic_api_key", "serper_api_key", "dataforseo_login",
    "dataforseo_password",
}


def _reject_inline_credentials(data: dict, path: Path, trail: str = "") -> None:
    """Refuse to load a config that embeds credential-like fields.

    This makes configs safe to share and commit by construction: API keys
    can only come from environment variables (see .env.example).
    """
    for key, value in data.items():
        where = f"{trail}.{key}" if trail else str(key)
        if str(key).lower() in _CREDENTIAL_KEYS:
            raise ConfigError(
                f"{path}: config field '{where}' looks like a credential. "
                "API keys and passwords are never read from config files — "
                "set them as environment variables instead (see .env.example)."
            )
        if isinstance(value, dict):
            _reject_inline_credentials(value, path, where)
