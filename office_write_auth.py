"""Авторизація записів Mini App (облік угод). Fail-closed: без налаштування запис вимкнено.

Два способи (достатньо одного):
1. Telegram WebApp initData: підпис HMAC-SHA256 за схемою Telegram (ключ = HMAC("WebAppData", bot_token)),
   свіжість `auth_date`, і `user.id` з OFFICE_OWNER_TG_IDS (через кому). Токен бота береться з
   OFFICE_WEBAPP_BOT_TOKEN або TG_BOT_TOKEN; у відповіді/логах він не з’являється.
2. Ключ запису OFFICE_WRITE_KEY (≥ 16 символів) у заголовку X-Office-Write-Key — для браузера поза Telegram.

Захист від CSRF: запис можливий лише через POST з JSON і нестандартним заголовком авторизації
(браузер не додасть його крос-домено без CORS; сервер CORS не вмикає). Обмеження: розмір тіла,
частота невдалих спроб за IP. Ордерів модуль не торкається.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import parse_qsl

MAX_BODY = 16 * 1024
INITDATA_MAX_AGE = 24 * 3600
FAIL_LIMIT = 15
FAIL_WINDOW = 600.0
_FAILS: Dict[str, list] = {}


def _bot_token() -> str:
    return (os.getenv("OFFICE_WEBAPP_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or "").strip()


def _owner_ids() -> set:
    out = set()
    for part in (os.getenv("OFFICE_OWNER_TG_IDS") or "").replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def _write_key() -> str:
    k = (os.getenv("OFFICE_WRITE_KEY") or "").strip()
    return k if len(k) >= 16 else ""


def config_status() -> Dict[str, Any]:
    """Що налаштовано (без значень секретів)."""
    tg = bool(_bot_token() and _owner_ids())
    key = bool(_write_key())
    return {"write_enabled": tg or key, "telegram_initdata": tg, "write_key": key,
            "hint": None if (tg or key) else
            "Запис вимкнено. Задайте OFFICE_OWNER_TG_IDS (+ токен бота) для Telegram або OFFICE_WRITE_KEY (≥16 символів) у змінних web-сервісу."}


def verify_init_data(init_data: str, *, now: Optional[float] = None) -> Tuple[bool, str, Optional[int]]:
    token, owners = _bot_token(), _owner_ids()
    if not token or not owners:
        return False, "telegram_auth_not_configured", None
    if not init_data or len(init_data) > 4096:
        return False, "no_init_data", None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    got = pairs.pop("hash", "")
    if not got:
        return False, "no_hash", None
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got):
        return False, "bad_signature", None
    try:
        age = (now if now is not None else time.time()) - int(pairs.get("auth_date", "0"))
    except ValueError:
        return False, "bad_auth_date", None
    if age < -60 or age > INITDATA_MAX_AGE:
        return False, "init_data_expired", None
    try:
        uid = int(json.loads(pairs.get("user", "{}")).get("id"))
    except Exception:
        return False, "no_user", None
    if uid not in owners:
        return False, "not_owner", uid
    return True, "ok", uid


def _throttled(ip: str, now: float) -> bool:
    hits = [t for t in _FAILS.get(ip, []) if now - t < FAIL_WINDOW]
    _FAILS[ip] = hits
    return len(hits) >= FAIL_LIMIT


def _fail(ip: str, now: float) -> None:
    _FAILS.setdefault(ip, []).append(now)
    if len(_FAILS) > 2000:
        _FAILS.clear()


def authorize(headers: Mapping[str, str], *, client_ip: str = "", now: Optional[float] = None) -> Tuple[bool, str]:
    """(разрешено, код причини). Порівняння секретів — у сталий час."""
    t = time.time() if now is None else now
    cfg = config_status()
    if not cfg["write_enabled"]:
        return False, "write_disabled"
    if _throttled(client_ip, t):
        return False, "rate_limited"
    hdr = {k.lower(): v for k, v in headers.items()}
    if cfg["write_key"]:
        supplied = hdr.get("x-office-write-key", "")
        if supplied and hmac.compare_digest(supplied.encode(), _write_key().encode()):
            return True, "ok_key"
    init = hdr.get("x-telegram-init-data", "")
    if init and cfg["telegram_initdata"]:
        ok, why, _uid = verify_init_data(init, now=t)
        if ok:
            return True, "ok_telegram"
        _fail(client_ip, t)
        return False, why
    _fail(client_ip, t)
    return False, "unauthorized"
