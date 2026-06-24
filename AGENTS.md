# AGENTS.md

## Cursor Cloud specific instructions

This is a pure Python 3.12 project (deps in `requirements.txt`, installed by the startup update script). There is no Node, Docker, Makefile, or pytest suite.

### Use `python3`, not `python`
Only `python3` is on PATH in this environment. Docs/RUNBOOK use `python` — substitute `python3` (e.g. `python3 -u office_mini_app.py`).

### Services (all use Python stdlib `http.server`; no Flask/FastAPI)
| Service | Start command | Default bind | Role |
|---------|---------------|--------------|------|
| Mini App (Web) | `python3 -u office_mini_app.py` | `127.0.0.1:8790` (`OFFICE_MINI_HOST`/`OFFICE_MINI_PORT`) | Browser UI + JSON API (`/api/summary`, `/api/review_draft`) + TradingView webhook (`POST /api/webhook/tradingview`) |
| Dashboard (Web, simpler MVP) | `python3 -u office_dashboard.py` | `127.0.0.1:8787` (`OFFICE_DASH_HOST`/`OFFICE_DASH_PORT`) | Read-only HTML tables of decisions/tasks/events/journal |
| Office relay / runtime (Worker) | `python3 -u office_multibot_bootstrap.py` | n/a | Telegram relay + multi-agent decision engine (the core product) |

### Database is zero-setup by default (SQLite)
- With no `DATABASE_URL`, the apps use a local SQLite file `office_bridge.db` (override path via `OFFICE_DB_PATH`). The Mini App auto-creates/initializes the schema on startup, so no manual DB step is needed for local dev.
- `scripts/init_db.py` is **only** for Postgres mode and requires `DATABASE_URL` (otherwise it exits 1). Use Postgres only when you need relay + Mini App to share state reliably; both must point at the same DB (a fingerprint check enforces this).

### What can / cannot run end-to-end here
- The **Mini App and Dashboard run fully locally** with no secrets. A complete "take action" smoke test: `POST /api/webhook/tradingview` to insert a signal, then see it in `office_events` (Dashboard) / the SQLite `tv_signals` table.
- The **relay (`office_multibot_bootstrap.py`) cannot run end-to-end without Telegram credentials**: `TG_API_ID`, `TG_API_HASH`, `TG_BOT_TOKEN`, plus `MAIN_CHAT_ID` and `OFFICE_CHAT_ID`. First-time config is interactive (`RELAY_INTERACTIVE=1`/`RELAY_FORCE_SETUP=1`); it writes `office_relay_config.json` (gitignored) and a Telethon `*.session` file.
- **External APIs are network-restricted in this VM and degrade gracefully:** Binance market data (`office_market_data.py`) returns empty dicts (no key needed in prod), and Anthropic LLM (`ANTHROPIC_API_KEY`, optional) falls back to heuristic agent replies. These are not blockers for local dev.

### Tests / lint
- No formal test runner. The "tests" are manual scripts: `python3 scripts/test_parse_signal_levels.py` (offline, returns exit 1 on failure) and `python3 scripts/test_llm_daryna.py` (offline heuristic). `python3 scripts/test_market_data.py` needs Binance access (empty output here).
- No configured linter; `python3 -m compileall <files>` is a quick syntax check.
