"""TOML config loading and validation."""

import os
import pathlib
import re
import tomllib
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MONITOR_ID_PATTERN = r'^[a-z0-9_-]{1,100}$'

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
    heartbeat_port: int = Field(default=8080, ge=1, le=65535)

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

    id: str = Field(pattern=MONITOR_ID_PATTERN)
    name: str = Field(min_length=1, max_length=200)
    type: Literal['http', 'ping', 'heartbeat']
    target: str
    interval: int | None = None
    enabled: bool = True
    expected_status: int | None = 200
    timeout: int | None = 10

    @field_validator('timeout', 'interval')
    @classmethod
    def _positive_optional(cls, v: int | None, info: Any) -> int | None:
        """Validate optional positive int."""
        if v is not None and v <= 0:
            raise ValueError(f'{info.field_name} must be positive')
        limits = {'timeout': 300, 'interval': 86400}
        limit = limits.get(info.field_name)
        if v is not None and limit and v > limit:
            raise ValueError(f'{info.field_name} must be <= {limit}')
        return v

    @model_validator(mode='after')
    def _validate_target(self) -> 'MonitorConfig':
        """Validate target per monitor type."""
        if self.type == 'http' and not self.target.startswith(
            ('http://', 'https://')
        ):
            raise ValueError(
                'http monitor target must start with http:// or https://'
            )
        return self


class AppConfig(BaseModel):
    """Root application config."""

    general: GeneralConfig = GeneralConfig()
    database: DatabaseConfig
    telegram: TelegramConfig
    monitors: list[MonitorConfig]


def load_config(path: str) -> AppConfig:
    """Load and validate TOML config."""
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f'Config file not found: {path}')

    with open(p, 'rb') as fh:
        raw = tomllib.load(fh)

    expanded = _expand_dict(raw)
    return AppConfig.model_validate(expanded)
