# Watchdog

Self-hosted server monitoring service. Checks your servers and alerts via Telegram when something goes down.

## Features

- **Ping (ICMP)** -- server reachability check without root privileges
- **HTTP(s)** -- endpoint availability, status codes, response time
- **Heartbeat** -- dead man's switch for cron jobs and background workers
- **Telegram alerts** -- instant notifications on state changes (down/recovery)
- **TOML config** -- monitors defined in a config file, no web UI required
- **PostgreSQL storage** -- check history and incident log with automatic retention

## Prerequisites

- [Python 3.12+](https://www.python.org/downloads/)
- [PostgreSQL 14+](https://www.postgresql.org/)
- [uv](https://docs.astral.sh/uv/) package manager

## Quick Start

```bash
git clone https://github.com/hawkxdev/watchdog.git
cd watchdog/apps/watchdog
uv sync
cp config.example.toml config.toml   # edit with your monitors
.venv/bin/python -m watchdog
```

Set required environment variables before running:

```bash
export WATCHDOG_DATABASE_URL="postgresql://user:pass@localhost/watchdog"
export WATCHDOG_TELEGRAM_TOKEN="123456:ABC-..."
export WATCHDOG_TELEGRAM_CHAT_ID="-100123456789"
```

## Configuration

See [`config.example.toml`](config.example.toml) for all options with comments.

```toml
[general]
check_interval = 60
failure_threshold = 3
success_threshold = 2
retention_days = 30

[database]
dsn = "${WATCHDOG_DATABASE_URL}"

[telegram]
bot_token = "${WATCHDOG_TELEGRAM_TOKEN}"
chat_id = "${WATCHDOG_TELEGRAM_CHAT_ID}"

[[monitors]]
id = "production-api"
name = "Production API"
type = "http"
target = "https://api.example.com/health"
interval = 60
expected_status = 200

[[monitors]]
id = "vps-berlin"
name = "VPS Berlin"
type = "ping"
target = "192.168.1.100"
interval = 30

[[monitors]]
id = "nightly-backup"
name = "Nightly Backup"
type = "heartbeat"
target = "nightly-backup"
interval = 86400
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WATCHDOG_DATABASE_URL` | Yes | PostgreSQL connection string |
| `WATCHDOG_TELEGRAM_TOKEN` | Yes | Telegram Bot API token (from @BotFather) |
| `WATCHDOG_TELEGRAM_CHAT_ID` | Yes | Telegram chat/group ID for alerts |
| `CONFIG_PATH` | No | Path to config file (default: `config.toml`) |

## How It Works

Each monitor runs as an independent asyncio task with its own check interval.

State transitions trigger alerts:

```
UP --> fail x3 --> DOWN  (sends "DOWN" alert)
DOWN --> success x2 --> UP  (sends "RECOVERY" alert)
```

### Heartbeat Endpoint

Heartbeat monitors work as a dead man's switch. Your cron job or background worker sends a POST request to Watchdog's HTTP endpoint. If no ping arrives within the expected interval, the monitor transitions to DOWN.

```bash
# From your cron job or script:
curl -X POST http://watchdog-host:8080/nightly-backup

# The monitor ID in the URL must match the monitor's `id` in config.toml
```

Default heartbeat port is `8080` (configurable via `general.heartbeat_port`).

## Deployment

### systemd (recommended)

1. Create a dedicated user:

```bash
sudo useradd --system --no-create-home watchdog
```

2. Deploy the application:

```bash
sudo mkdir -p /opt/watchdog /etc/watchdog
sudo cp -r . /opt/watchdog/
cd /opt/watchdog && uv sync
```

3. Create environment file:

```bash
sudo tee /etc/watchdog/.env << 'EOF'
WATCHDOG_DATABASE_URL=postgresql://watchdog:secret@localhost/watchdog
WATCHDOG_TELEGRAM_TOKEN=123456:ABC-...
WATCHDOG_TELEGRAM_CHAT_ID=-100123456789
EOF
sudo chmod 600 /etc/watchdog/.env
```

4. Install and start the service:

```bash
sudo cp deploy/watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now watchdog
```

5. Check status:

```bash
sudo systemctl status watchdog
sudo journalctl -u watchdog -f
```

The service uses `WatchdogSec=60` -- systemd will restart it automatically if the process becomes unresponsive.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12+, asyncio |
| HTTP checks | [httpx](https://www.python-httpx.org/) (async) |
| ICMP ping | [icmplib](https://github.com/ValentinBELYN/icmplib) (no root) |
| Heartbeat server | [aiohttp](https://docs.aiohttp.org/) |
| Storage | PostgreSQL via [asyncpg](https://github.com/MagicStack/asyncpg) |
| Config | TOML ([tomllib](https://docs.python.org/3/library/tomllib.html), stdlib) |
| Validation | [pydantic](https://docs.pydantic.dev/) v2 |
| Notifications | Telegram Bot API via httpx |

## Project Structure

```
src/watchdog/
├── __init__.py
├── __main__.py        # entrypoint, signal handlers, sd_notify
├── config.py          # TOML config loading + pydantic models
├── checkers/          # ping, http, heartbeat check implementations
├── scheduler.py       # asyncio monitor loops + retention
├── state.py           # UP/DOWN state machine
├── storage.py         # PostgreSQL operations
└── notifications.py   # Telegram alerting
```

## License

MIT -- see [LICENSE](LICENSE).

## Acknowledgements

Architecture informed by studying:
- [Healthchecks.io](https://github.com/healthchecks/healthchecks) -- state machine and heartbeat patterns
- [Uptime Kuma](https://github.com/louislam/uptime-kuma) -- feature scope reference
- [Gatus](https://github.com/TwiN/gatus) -- config-as-code approach
