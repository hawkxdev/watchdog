"""Config loading and validation tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from watchdog.config import (
    AppConfig,
    DatabaseConfig,
    GeneralConfig,
    MonitorConfig,
    TelegramConfig,
    load_config,
)


def write_toml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / 'config.toml'
    p.write_text(content)
    return p


MINIMAL_TOML = """\
[database]
dsn = "postgresql://user:pass@localhost/watchdog_test"

[telegram]
bot_token = "mytoken"
chat_id = "-100456"

[[monitors]]
id = "api"
name = "Production API"
type = "http"
target = "https://api.example.com/health"
"""


class TestGeneralConfig:
    def test_defaults(self) -> None:
        cfg = GeneralConfig()
        assert cfg.check_interval == 60
        assert cfg.failure_threshold == 3
        assert cfg.success_threshold == 2
        assert cfg.retention_days == 30

    def test_custom_values(self) -> None:
        cfg = GeneralConfig(
            check_interval=30,
            failure_threshold=5,
            retention_days=7,
        )
        assert cfg.check_interval == 30
        assert cfg.failure_threshold == 5
        assert cfg.retention_days == 7

    def test_check_interval_must_be_positive(
        self,
    ) -> None:
        with pytest.raises(ValidationError, match='check_interval'):
            GeneralConfig(check_interval=0)

    def test_failure_threshold_must_be_positive(
        self,
    ) -> None:
        with pytest.raises(ValidationError, match='failure_threshold'):
            GeneralConfig(failure_threshold=0)

    def test_success_threshold_must_be_positive(
        self,
    ) -> None:
        with pytest.raises(ValidationError, match='success_threshold'):
            GeneralConfig(success_threshold=0)

    def test_retention_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match='retention_days'):
            GeneralConfig(retention_days=0)


class TestDatabaseConfig:
    def test_valid(self) -> None:
        cfg = DatabaseConfig(dsn='postgresql://u:p@localhost/db')
        assert cfg.dsn == 'postgresql://u:p@localhost/db'
        assert cfg.min_pool_size == 2
        assert cfg.max_pool_size == 10

    def test_dsn_required(self) -> None:
        with pytest.raises(ValidationError):
            DatabaseConfig()  # type: ignore[call-arg]

    def test_custom_pool_sizes(self) -> None:
        cfg = DatabaseConfig(
            dsn='postgresql://localhost/db',
            min_pool_size=1,
            max_pool_size=5,
        )
        assert cfg.min_pool_size == 1
        assert cfg.max_pool_size == 5


class TestTelegramConfig:
    def test_valid(self) -> None:
        cfg = TelegramConfig(bot_token='123:abc', chat_id='-100123')
        assert cfg.bot_token == '123:abc'
        assert cfg.chat_id == '-100123'
        assert cfg.enabled is True

    def test_can_disable(self) -> None:
        cfg = TelegramConfig(
            bot_token='tok',
            chat_id='-1',
            enabled=False,
        )
        assert cfg.enabled is False

    def test_bot_token_required(self) -> None:
        with pytest.raises(ValidationError):
            TelegramConfig(chat_id='-100')  # type: ignore[call-arg]

    def test_chat_id_required(self) -> None:
        with pytest.raises(ValidationError):
            TelegramConfig(bot_token='tok')  # type: ignore[call-arg]


class TestMonitorConfig:
    def test_http_monitor_defaults(self) -> None:
        cfg = MonitorConfig(
            id='api',
            name='API',
            type='http',
            target='https://x.com',
        )
        assert cfg.id == 'api'
        assert cfg.type == 'http'
        assert cfg.expected_status == 200
        assert cfg.timeout == 10
        assert cfg.enabled is True
        assert cfg.interval is None

    def test_ping_monitor(self) -> None:
        cfg = MonitorConfig(
            id='vps',
            name='VPS',
            type='ping',
            target='10.0.0.1',
        )
        assert cfg.type == 'ping'

    def test_heartbeat_monitor(self) -> None:
        cfg = MonitorConfig(
            id='cron',
            name='Cron',
            type='heartbeat',
            target='backup',
        )
        assert cfg.type == 'heartbeat'

    def test_interval_override(self) -> None:
        cfg = MonitorConfig(
            id='x',
            name='X',
            type='http',
            target='https://x.com',
            interval=120,
        )
        assert cfg.interval == 120

    def test_invalid_type(self) -> None:
        with pytest.raises(ValidationError, match='type'):
            MonitorConfig(id='x', name='X', type='ftp', target='x')

    def test_id_required(self) -> None:
        with pytest.raises(ValidationError):
            MonitorConfig(name='X', type='http', target='x')  # type: ignore[call-arg]

    def test_name_required(self) -> None:
        with pytest.raises(ValidationError):
            MonitorConfig(id='x', type='http', target='x')  # type: ignore[call-arg]

    def test_can_disable(self) -> None:
        cfg = MonitorConfig(
            id='x',
            name='X',
            type='http',
            target='x',
            enabled=False,
        )
        assert cfg.enabled is False


class TestLoadConfig:
    def test_minimal_toml(self, tmp_path: Path) -> None:
        path = write_toml(tmp_path, MINIMAL_TOML)
        cfg = load_config(str(path))
        assert isinstance(cfg, AppConfig)
        assert cfg.telegram.bot_token == 'mytoken'
        assert (
            cfg.database.dsn
            == 'postgresql://user:pass@localhost/watchdog_test'
        )
        assert len(cfg.monitors) == 1
        assert cfg.monitors[0].id == 'api'

    def test_general_defaults_applied(self, tmp_path: Path) -> None:
        path = write_toml(tmp_path, MINIMAL_TOML)
        cfg = load_config(str(path))
        assert cfg.general.check_interval == 60
        assert cfg.general.retention_days == 30

    def test_general_override(self, tmp_path: Path) -> None:
        toml = (
            '[general]\n'
            'check_interval = 30\n'
            'retention_days = 7\n\n' + MINIMAL_TOML
        )
        path = write_toml(tmp_path, toml)
        cfg = load_config(str(path))
        assert cfg.general.check_interval == 30
        assert cfg.general.retention_days == 7

    def test_multiple_monitors(self, tmp_path: Path) -> None:
        toml = (
            MINIMAL_TOML
            + """\

[[monitors]]
id = "vps"
name = "VPS Berlin"
type = "ping"
target = "10.0.0.1"

[[monitors]]
id = "backup"
name = "Nightly Backup"
type = "heartbeat"
target = "nightly"
"""
        )
        path = write_toml(tmp_path, toml)
        cfg = load_config(str(path))
        assert len(cfg.monitors) == 3
        types = {m.type for m in cfg.monitors}
        assert types == {'http', 'ping', 'heartbeat'}

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(str(tmp_path / 'missing.toml'))

    def test_invalid_toml_syntax(self, tmp_path: Path) -> None:
        path = tmp_path / 'bad.toml'
        path.write_text('[[monitors\n')
        with pytest.raises(Exception):
            load_config(str(path))

    def test_missing_required_section(self, tmp_path: Path) -> None:
        path = write_toml(
            tmp_path,
            '[general]\ncheck_interval = 60\n',
        )
        with pytest.raises(Exception):
            load_config(str(path))


class TestEnvVarExpansion:
    def test_expands_bot_token(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('WATCHDOG_TOKEN', 'secret-token')
        toml = """\
[database]
dsn = "postgresql://localhost/db"

[telegram]
bot_token = "${WATCHDOG_TOKEN}"
chat_id = "-100"

[[monitors]]
id = "x"
name = "X"
type = "http"
target = "https://x.com"
"""
        path = write_toml(tmp_path, toml)
        cfg = load_config(str(path))
        assert cfg.telegram.bot_token == 'secret-token'

    def test_expands_dsn(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv('WATCHDOG_DB', 'postgresql://u:p@localhost/db')
        toml = """\
[database]
dsn = "${WATCHDOG_DB}"

[telegram]
bot_token = "tok"
chat_id = "-1"

[[monitors]]
id = "x"
name = "X"
type = "http"
target = "https://x.com"
"""
        path = write_toml(tmp_path, toml)
        cfg = load_config(str(path))
        assert cfg.database.dsn == 'postgresql://u:p@localhost/db'

    def test_missing_env_var_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv('WATCHDOG_MISSING', raising=False)
        toml = """\
[database]
dsn = "postgresql://localhost/db"

[telegram]
bot_token = "${WATCHDOG_MISSING}"
chat_id = "-1"

[[monitors]]
id = "x"
name = "X"
type = "http"
target = "https://x.com"
"""
        path = write_toml(tmp_path, toml)
        with pytest.raises(KeyError, match='WATCHDOG_MISSING'):
            load_config(str(path))

    def test_plain_values_not_expanded(self, tmp_path: Path) -> None:
        path = write_toml(tmp_path, MINIMAL_TOML)
        cfg = load_config(str(path))
        assert cfg.telegram.bot_token == 'mytoken'
