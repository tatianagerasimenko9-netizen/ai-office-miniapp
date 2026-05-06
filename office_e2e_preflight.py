#!/usr/bin/env python3
"""
MASTER п.17: звірка fingerprint БД між relay (лог) / локальним рядком і Mini App.
MASTER п.20: підготовка до E2E — переконатися, що UI дивиться на ту саму БД.

Запуск локально (або в CI), з тими самими змінними що й сервіси:

  # Варіант A — порівняти Mini App з fingerprint з логів relay (найпростіше для Render):
  set RELAY_FINGERPRINT_EXPECTED=c78e00696e638425
  set OFFICE_MINI_URL=https://your-mini-app.onrender.com
  py -3 office_e2e_preflight.py

  # Варіант B — порівняти Mini App з локальним DATABASE_URL (як у Dashboard Render):
  set DATABASE_URL=postgresql://...
  set OFFICE_MINI_URL=https://your-mini-app.onrender.com
  py -3 office_e2e_preflight.py

  # Явні прапорці:
  py -3 office_e2e_preflight.py --relay-fingerprint c78e00696e638425 --mini-url https://...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _db_target() -> str:
    return (
        os.getenv("DATABASE_URL", "").strip()
        or os.getenv("OFFICE_DB_PATH", "office_bridge.db").strip()
        or "office_bridge.db"
    )


def _fetch_mini_identity(mini_base: str, timeout: float = 30.0) -> dict[str, object]:
    url = mini_base.rstrip("/") + "/api/summary"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "office-e2e-preflight"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    di = data.get("db_identity")
    if not isinstance(di, dict):
        return {}
    return di


def main() -> int:
    os.environ.setdefault("PYTHONUTF8", "1")
    try:
        from office_bridge import office_db_identity
    except ImportError:
        print("[preflight][FAIL] не знайдено office_bridge (запускайте з кореня ai-office-miniapp).", file=sys.stderr)
        return 2

    ap = argparse.ArgumentParser(description="Звірка DB fingerprint Office (п.17).")
    ap.add_argument(
        "--mini-url",
        default=os.getenv("OFFICE_MINI_URL", "").strip(),
        help="URL Mini App (без /api/summary), або OFFICE_MINI_URL",
    )
    ap.add_argument(
        "--relay-fingerprint",
        default=os.getenv("RELAY_FINGERPRINT_EXPECTED", "").strip(),
        help="16 hex з логів relay [relay] DB identity, або RELAY_FINGERPRINT_EXPECTED",
    )
    args = ap.parse_args()

    db_raw = _db_target()
    ident = office_db_identity(db_raw)
    fp_local = str(ident.get("fingerprint") or "?")
    back_local = str(ident.get("backend") or "?")

    print(f"[preflight] Локальний рядок БД ({back_local}) → fingerprint: {fp_local}")
    if not os.getenv("DATABASE_URL", "").strip():
        print("[preflight] Підказка: DATABASE_URL не задано — локальний fingerprint може бути для SQLite office_bridge.db.")

    rc = 0

    relay_fp = (args.relay_fingerprint or "").strip().lower()
    if relay_fp:
        if relay_fp != fp_local.lower():
            print(
                f"[preflight][WARN] relay-fingerprint ({relay_fp}) ≠ локальний ({fp_local.lower()}). "
                "Якщо ви не експортували той самий DATABASE_URL, що на relay — це очікувано; для п.17 достатньо зіставити relay з Mini App."
            )
        else:
            print("[preflight][OK] relay-fingerprint збігається з локальним DATABASE_URL/OFFICE_DB_PATH.")

    mini_url = args.mini_url.strip()
    if not mini_url:
        print("[preflight] Немає --mini-url / OFFICE_MINI_URL — перевірку Mini App пропущено.")
        print("[preflight] Задайте OFFICE_MINI_URL і повторіть для автоматичної перевірки п.17.")
        return rc

    try:
        mini_di = _fetch_mini_identity(mini_url)
    except urllib.error.HTTPError as exc:
        print(f"[preflight][FAIL] Mini App HTTP {exc.code}: {mini_url}/api/summary", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[preflight][FAIL] Mini App недоступний ({mini_url}): {exc}", file=sys.stderr)
        return 1

    mini_fp = str(mini_di.get("fingerprint") or "")
    mini_back = str(mini_di.get("backend") or "?")
    print(f"[preflight] Mini App ({mini_back}) fingerprint: {mini_fp or '—'}")

    if not mini_fp:
        print("[preflight][FAIL] у відповіді Mini App немає db_identity.fingerprint", file=sys.stderr)
        return 1

    ref = relay_fp if relay_fp else fp_local.lower()
    target_desc = "relay (лог)" if relay_fp else "локальний DATABASE_URL"

    if mini_fp.lower() != ref:
        print(
            f"[preflight][FAIL] Mini App fingerprint ≠ {target_desc}. "
            "Перевірте однаковість DATABASE_URL на Web (Mini App) і Worker (relay) у Render.",
            file=sys.stderr,
        )
        return 1

    print(f"[preflight][OK] Mini App збігається з {target_desc} — MASTER п.17 виконано (автоматично).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
