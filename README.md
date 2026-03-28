# Watchdog

Self-hosted server monitoring service. Checks your servers and alerts via Telegram when something goes down.

## Features

- **Ping (ICMP)** -- server reachability check without root privileges
- **HTTP(s)** -- endpoint availability, status codes, response time
- **Heartbeat** -- dead man's switch for cron jobs and background workers
- **Telegram alerts** -- instant notifications on state changes (down/recovery)
- **TOML config** -- monitors defined in a config file, no web UI required
- **PostgreSQL storage** -- check history and incident log with automatic retention

## Quick Start

```bash
git clone https://github.com/hawkxdev/watchdog.git
cd watchdog/apps/watchdog
uv sync
cp config.example.toml config.toml   # edit with your monitors
uv run python -m watchdog
```

## Configuration

```toml
[general]
retention_days = 30

[notifications.telegram]
bot_token = "${WATCHDOG_TELEGRAM_TOKEN}"
chat_id = "${WATCHDOG_TELEGRAM_CHAT_ID}"

[[monitors]]
name = "Production API"
type = "http"
target = "https://api.example.com/health"
interval = 60
expected_status = 200
failure_threshold = 3

[[monitors]]
name = "VPS Berlin"
type = "ping"
target = "192.168.1.100"
interval = 30

[[monitors]]
name = "Nightly Backup"
type = "heartbeat"
interval = 86400
grace = 3600
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WATCHDOG_TELEGRAM_TOKEN` | Yes | Telegram Bot API token (from @BotFather) |
| `WATCHDOG_TELEGRAM_CHAT_ID` | Yes | Telegram chat/group ID for alerts |
| `WATCHDOG_DATABASE_URL` | Yes | PostgreSQL connection string |

## How It Works

Each monitor runs as an independent asyncio task with its own check interval.

State transitions trigger alerts:

```
UP --> fail x3 --> DOWN  (sends "DOWN" alert)
DOWN --> success x2 --> UP  (sends "RECOVERY" alert)
```

Heartbeat monitors work as a dead man's switch: your cron job pings Watchdog's HTTP endpoint. If no ping arrives within `interval + grace`, the monitor transitions to DOWN.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12+, asyncio |
| HTTP checks | [httpx](https://www.python-httpx.org/) (async) |
| ICMP ping | [icmplib](https://github.com/ValentinBELYN/icmplib) (no root) |
| Storage | PostgreSQL via [asyncpg](https://github.com/MagicStack/asyncpg) |
| Config | TOML ([tomllib](https://docs.python.org/3/library/tomllib.html), stdlib) |
| Validation | [pydantic](https://docs.pydantic.dev/) v2 |
| Notifications | Telegram Bot API via httpx |

## Deployment

### systemd (recommended)

```ini
[Unit]
Description=Watchdog Monitoring Service
After=network-online.target

[Service]
Type=notify
User=watchdog
WorkingDirectory=/opt/watchdog
ExecStart=/opt/watchdog/.venv/bin/python -m watchdog
Restart=on-failure
RestartSec=10
WatchdogSec=60

[Install]
WantedBy=multi-user.target
```

### Docker

```bash
docker compose up -d
```

## Project Structure

```
apps/watchdog/
├── src/watchdog/
│   ├── __init__.py
│   ├── __main__.py        # entrypoint
│   ├── config.py           # TOML config loading + pydantic models
│   ├── checkers/           # ping, http, heartbeat check implementations
│   ├── scheduler.py        # asyncio monitor loop
│   ├── state.py            # UP/DOWN state machine
│   ├── storage.py          # PostgreSQL operations
│   └── notifications.py    # Telegram alerting
├── tests/
├── config.example.toml
└── pyproject.toml
```

## License

MIT

## Acknowledgements

Architecture informed by studying:
- [Healthchecks.io](https://github.com/healthchecks/healthchecks) -- state machine and heartbeat patterns
- [Uptime Kuma](https://github.com/louislam/uptime-kuma) -- feature scope reference
- [Gatus](https://github.com/TwiN/gatus) -- config-as-code approach
