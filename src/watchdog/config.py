"""TOML config loading and validation."""

import os
import re
import tomllib
from typing import Any

from pydantic import BaseModel, Field, field_validator

_ENV_VAR_RE = re.compile(r'\$\{([^}]+)\}')


def _expand_env_vars(value: str) -> str:
    """Expand ${VAR} placeholders from env."""

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name not in os.environ:
            raise KeyError(f'Environment variable not set: {var_name}')
        return os.environ[var_name]

    return _ENV_VAR_RE.sub(_replace, value)


def _expand_dict(data: Any) -> Any:
    """Expand env vars recursively."""
    if isinstance(data, dict):
        return {k: _expand_dict(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_expand_dict(item) for item in data]
    if isinstance(data, str):
        return _expand_env_vars(data)
    return data


class GeneralConfig(BaseModel):
    """General monitoring settings."""

    check_interval: int = 60
    failure_threshold: int = 3
    success_threshold: int = 2
    retention_days: int = 30

    @field_validator(
        'check_interval',
        'failure_threshold',
        'success_threshold',
        'retention_days',
    )
    @classmethod
    def _positive(cls, v: int, info: Any) -> int:
        if v <= 0:
            raise ValueError(f'{info.field_name} must be positive')
        return v


class DatabaseConfig(BaseModel):
    """PostgreSQL connection settings."""

    dsn: str
    min_pool_size: int = 2
    max_pool_size: int = 10


class TelegramConfig(BaseModel):
    """Telegram notification settings."""

    bot_token: str
    chat_id: str
    enabled: bool = True


class MonitorConfig(BaseModel):
    """Single monitor definition."""

    id: str = Field(min_length=1, max_length=100, pattern=r'^[a-z0-9_-]+$')
    name: str = Field(min_length=1, max_length=200)
    type: str
    target: str
    interval: int | None = None
    enabled: bool = True
    expected_status: int | None = 200
    timeout: int | None = 10

    @field_validator('type')
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in ('http', 'ping', 'heartbeat'):
            raise ValueError(
                f'type must be http, ping or heartbeat, got: {v!r}'
            )
        return v

    @field_validator('timeout', 'interval')
    @classmethod
    def _positive_optional(cls, v: int | None, info: Any) -> int | None:
        """Validate optional positive int."""
        if v is not None and v <= 0:
            raise ValueError(f'{info.field_name} must be positive')
        return v


class AppConfig(BaseModel):
    """Root application config."""

    general: GeneralConfig = GeneralConfig()
    database: DatabaseConfig
    telegram: TelegramConfig
    monitors: list[MonitorConfig]


def load_config(path: str) -> AppConfig:
    """Load and validate TOML config."""
    import pathlib

    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f'Config file not found: {path}')

    with open(p, 'rb') as fh:
        raw = tomllib.load(fh)

    expanded = _expand_dict(raw)
    return AppConfig.model_validate(expanded)
