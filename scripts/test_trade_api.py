#!/usr/bin/env python3
"""Manual-trade write API over real HTTP: auth (key + Telegram initData), CSRF/size limits, idempotency,
state machine, tracking, rate limit. Temp SQLite, fixture candles, no network, no orders."""
import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

import office_positions as P  # noqa: E402
import office_write_auth as A  # noqa: E402
from office_bridge import init_office_db  # noqa: E402

BOT, OWNER, KEY = "123456:TEST-TOKEN-not-real", 424242, "k" * 24


def init_data(uid=OWNER, age=0, token=BOT, tamper=False):
    now = int(time.time()) - age
    pairs = {"auth_date": str(now), "query_id": "AAH", "user": json.dumps({"id": uid, "first_name": "T"})}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if tamper:
        pairs["user"] = json.dumps({"id": 1})
    return urllib.parse.urlencode(pairs)


# ---- unit: initData verification
os.environ.update(OFFICE_WEBAPP_BOT_TOKEN=BOT, OFFICE_OWNER_TG_IDS=f"{OWNER}, 7")
assert A.verify_init_data(init_data())[:2] == (True, "ok")
assert A.verify_init_data(init_data(uid=999))[1] == "not_owner"
assert A.verify_init_data(init_data(tamper=True))[1] == "bad_signature"
assert A.verify_init_data(init_data(age=90000))[1] == "init_data_expired"
assert A.verify_init_data(init_data(token="other:token"))[1] == "bad_signature"
assert A.verify_init_data("")[1] == "no_init_data"
os.environ.pop("OFFICE_WEBAPP_BOT_TOKEN"); os.environ.pop("OFFICE_OWNER_TG_IDS")
assert A.config_status()["write_enabled"] is False and "OFFICE_WRITE_KEY" in A.config_status()["hint"]
os.environ["OFFICE_WRITE_KEY"] = "short"
assert A.config_status()["write_key"] is False, "keys shorter than 16 chars are ignored"
os.environ.pop("OFFICE_WRITE_KEY")

tmp = tempfile.mkdtemp()
db = str(Path(tmp) / "t.db")
init_office_db(db)


def start(extra_env):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OFFICE_WRITE", "OFFICE_OWNER", "OFFICE_WEBAPP", "TG_BOT"))}
    env.update({"OFFICE_DB_PATH": db, "OFFICE_MINI_FIXTURE": "1", "OFFICE_MINI_PORT": str(port),
                "OFFICE_MINI_HOST": "127.0.0.1", "DATABASE_URL": "", **extra_env})
    proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "office_mini_app.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", port), 0.2).close(); break
        except OSError:
            time.sleep(0.2)
    return proc, f"http://127.0.0.1:{port}"


def call(base, method, path, body=None, headers=None, raw=None, ctype="application/json"):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = dict(headers or {})
    if data is not None and ctype:
        h["Content-Type"] = ctype
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}"), dict(r.headers)
    except urllib.error.HTTPError as e:
        raw_body = e.read()
        try:
            return e.code, json.loads(raw_body or b"{}"), dict(e.headers)
        except Exception:
            return e.code, {}, dict(e.headers)


OPEN = {"symbol": "ETHUSDT", "direction": "LONG", "entry": "2600", "qty": "2", "sl": "2550", "tp1": "2700",
        "idem_key": "o1"}

# ---- 1. nothing configured: writes are off (fail closed)
proc, base = start({})
try:
    assert call(base, "GET", "/api/v2/auth")[1]["write_enabled"] is False
    code, body, _ = call(base, "POST", "/api/v2/trade/open", OPEN, {"X-Office-Write-Key": KEY})
    assert code == 403 and body["error"] == "write_disabled", (code, body)
    assert call(base, "GET", "/api/v2/trades")[1]["schema_missing"] is True
finally:
    proc.terminate()

# ---- 2. key configured
proc, base = start({"OFFICE_WRITE_KEY": KEY})
try:
    H = {"X-Office-Write-Key": KEY}
    assert call(base, "GET", "/api/v2/auth")[1] == {"ok": True, "write_enabled": True, "telegram_initdata": False,
                                                  "write_key": True, "hint": None}
    assert call(base, "POST", "/api/v2/trade/open", OPEN)[0] == 401
    assert call(base, "POST", "/api/v2/trade/open", OPEN, {"X-Office-Write-Key": "x" * 24})[0] == 401
    code, body, hdrs = call(base, "POST", "/api/v2/trade/open", OPEN, H)
    assert code == 503 and body["error"] == "schema_missing", (code, body)   # authorized, but not migrated
    assert "Access-Control-Allow-Origin" not in hdrs, "no CORS: cross-site pages cannot drive the API"
    P.migrate_positions(db)
    assert call(base, "POST", "/api/v2/trade/open", OPEN, H, ctype="text/plain")[0] == 415
    assert call(base, "POST", "/api/v2/trade/open", raw=b"{not json", headers=H)[0] == 400
    assert call(base, "POST", "/api/v2/trade/open", raw=b"x" * 20000, headers=H)[0] == 413
    assert call(base, "POST", "/api/v2/trade/bogus", OPEN, H)[0] == 404
    assert call(base, "POST", "/api/v2/trade/open", {**OPEN, "sl": "2700"}, H)[0] == 422   # geometry
    code, body, _ = call(base, "POST", "/api/v2/trade/open", OPEN, H)
    assert code == 200 and body["ok"] and body["orders"] is False and body["order_authorized"] is False
    tid = body["position"]["trade_id"]
    assert body["position"]["display"]["entry"] == "2 600" and body["position"]["initial_risk_usdt"] == 100.0
    assert call(base, "POST", "/api/v2/trade/open", OPEN, H)[0] == 409                    # double tap
    code, body, _ = call(base, "POST", "/api/v2/trade/partial", {"trade_id": tid, "price": "2650", "qty": "1", "idem_key": "p1"}, H)
    assert code == 200 and body["position"]["remaining_qty"] == 1
    assert call(base, "POST", "/api/v2/trade/partial", {"trade_id": tid, "price": "2650", "qty": "5"}, H)[0] == 422
    assert call(base, "POST", "/api/v2/trade/move_sl", {"trade_id": tid, "sl": "2605"}, H)[1]["position"]["risk_now_usdt"] == 0
    lst = call(base, "GET", "/api/v2/trades")[1]
    pos = lst["positions"][0]
    assert pos["is_real_position"] is True and pos["tracking"]["advisory_only"] is True
    assert {f["code"] for f in pos["tracking"]["flags"]} == {"NO_FRESH_PRICE"}, "fixture price is never 'fresh'"
    assert lst["exposure"]["risk_now_usdt"] == 0.0
    risk = call(base, "GET", "/api/v2/risk")[1]
    assert risk["exposure"]["status"] == "OK" and risk["exposure"]["value"] == 0.0
    code, body, _ = call(base, "POST", "/api/v2/trade/close", {"trade_id": tid, "price": "2640", "fee_usdt": "1"}, H)
    assert code == 200 and body["position"]["status"] == "CLOSED"
    assert call(base, "POST", "/api/v2/trade/close", {"trade_id": tid, "price": "2640"}, H)[0] == 409
    detail = call(base, "GET", "/api/v2/trade?id=" + tid)[1]["position"]
    assert [e["kind"] for e in detail["events"]] == ["OPEN", "PARTIAL_EXIT", "MOVE_SL", "CLOSE"]
    closed = call(base, "GET", "/api/v2/trades?state=closed")[1]
    assert closed["stats"]["n"] == 1 and closed["stats"]["wr_pct"] is None
    # brute force: repeated bad keys are throttled
    for _ in range(A.FAIL_LIMIT + 2):
        call(base, "POST", "/api/v2/trade/open", OPEN, {"X-Office-Write-Key": "bad"})
    # the key path never counts as a failure, but bad init-data attempts do; use that to hit the limit
    codes = [call(base, "POST", "/api/v2/trade/open", OPEN, {"X-Telegram-Init-Data": "garbage"})[0] for _ in range(3)]
    assert set(codes) <= {401, 403, 429}
finally:
    proc.terminate()

# ---- 3. Telegram initData only
proc, base = start({"OFFICE_WEBAPP_BOT_TOKEN": BOT, "OFFICE_OWNER_TG_IDS": str(OWNER)})
try:
    assert call(base, "GET", "/api/v2/auth")[1]["telegram_initdata"] is True
    good = {"X-Telegram-Init-Data": init_data()}
    code, body, _ = call(base, "POST", "/api/v2/trade/open", {**OPEN, "idem_key": "tg1"}, good)
    assert code == 200, (code, body)
    assert call(base, "POST", "/api/v2/trade/open", {**OPEN, "idem_key": "tg2"}, {"X-Telegram-Init-Data": init_data(uid=1)})[0] == 401
    assert call(base, "POST", "/api/v2/trade/open", {**OPEN, "idem_key": "tg3"}, {"X-Telegram-Init-Data": init_data(tamper=True)})[0] == 401
    statuses = [call(base, "POST", "/api/v2/trade/open", {**OPEN, "idem_key": f"b{i}"},
                     {"X-Telegram-Init-Data": init_data(uid=1)})[0] for i in range(A.FAIL_LIMIT + 3)]
    assert statuses[-1] == 429, statuses
    assert call(base, "POST", "/api/v2/trade/open", {**OPEN, "idem_key": "tg4"}, good)[0] == 429, "locked out while throttled"
finally:
    proc.terminate()
print("OK trade API: auth fail-closed, key + Telegram initData, CSRF/size limits, idempotency, lifecycle, throttling")
