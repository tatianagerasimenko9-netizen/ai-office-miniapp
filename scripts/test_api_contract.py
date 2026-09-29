#!/usr/bin/env python3
"""HTTP contract test for Mini App 2.0 endpoints (real server, temp SQLite, fixture candles). Offline.

Every /api/v2 response: 200 + JSON (or a JSON 500 with an honest error), no truthy order/authorization flags,
no float tails or exponent notation in any display string, hostile params never crash the server.
"""
import json
import os
import re
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

from office_bridge import init_office_db, log_event, signal_upsert  # noqa: E402

TAIL = re.compile(r"\d\.\d{9,}|\d[eE][+-]\d{2}\b")
FLAG_KEYS = ("orders", "order_authorized", "opens_position", "auto_trading", "is_signal")


def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in FLAG_KEYS and v not in (False, None):
                raise AssertionError(f"{path}/{k} must not be truthy: {v!r}")
            walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, f"{path}[{i}]")
    elif isinstance(node, str) and TAIL.search(node) and "sha" not in path and "_at" not in path and "ts" not in path.split("/")[-1]:
        # ISO timestamps and hashes are exempt; display strings must not carry float tails.
        if not re.match(r"^\d{4}-\d{2}-\d{2}T", node) and not re.fullmatch(r"[0-9a-f]{8,}", node):
            raise AssertionError(f"float tail/exponent in string at {path}: {node!r}")


def main():
    tmp = tempfile.mkdtemp()
    db = str(Path(tmp) / "c.db")
    init_office_db(db)
    signal_upsert(db, signal_id="c-1", symbol="PEPEUSDT", direction="LONG", entry_low=0.0000123,
                  entry_high=0.0000125, sl=0.0000118, tp1=0.0000140, tp2=None, rr=None, status="WATCHING",
                  analysis_note="Чекаю ретесту\nЩо скасує: закриття нижче 0.0000118")
    signal_upsert(db, signal_id="c-2", symbol="ETHUSDT", direction="SHORT", entry_low=2662.0000000001,
                  entry_high=2668.0, sl=2686.0000000002, tp1=2628.0, tp2=2616.0, rr=None, status="ACTIVE", analysis_note="")
    log_event(db, "RISK_SHADOW_REVIEW", {"symbol": "ETHUSDT", "would_veto": True, "reasons": ["EXECUTION_NOT_VERIFIED"]}, "c-2")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    env = {**os.environ, "OFFICE_DB_PATH": db, "OFFICE_MINI_FIXTURE": "1", "OFFICE_MINI_PORT": str(port),
           "OFFICE_MINI_HOST": "127.0.0.1", "DATABASE_URL": ""}
    proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "office_mini_app.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close(); break
            except OSError:
                time.sleep(0.2)

        def get(path):
            try:
                with urllib.request.urlopen(base + path, timeout=20) as r:
                    return r.status, r.headers.get("Content-Type", ""), r.read()
            except urllib.error.HTTPError as e:
                return e.code, e.headers.get("Content-Type", ""), e.read()

        ok_paths = [
            "/api/v2/home", "/api/v2/overview", "/api/v2/scenarios?watching=1", "/api/v2/scenario?id=c-1",
            "/api/v2/scenario?id=c-2", "/api/v2/candles?symbol=ETHUSDT&tf=H1&limit=50", "/api/v2/scanner",
            "/api/v2/journal?kind=scenarios", "/api/v2/journal?kind=audit", "/api/v2/journal?kind=positions",
            "/api/v2/positions", "/api/v2/settings", "/api/v2/risk", "/api/v2/session?symbol=BTCUSDT",
        ]
        for path in ok_paths:
            code, ctype, body = get(path)
            assert code == 200 and "application/json" in ctype, (path, code, ctype)
            data = json.loads(body)
            assert isinstance(data, dict) and ("ok" in data or "scenarios" in data or "marks" in data), (path, list(data)[:5])
            walk(data, path)

        det = json.loads(get("/api/v2/scenario?id=c-2")[2])
        assert det["ok"] and det["scenario"]["display"]["sl"] == "2 686" and det["scenario"]["display"]["zone"] == "2 662–2 668", det["scenario"]["display"]
        assert det["execution"]["order_authorized"] is False
        peb = json.loads(get("/api/v2/scenario?id=c-1")[2])["scenario"]["display"]
        assert peb["sl"] == "0.000012" or peb["sl"] == "0.0000118" or peb["sl"].startswith("0.00001"), peb
        risk = json.loads(get("/api/v2/risk")[2])
        assert risk["equity"]["value"] is None and risk["shadow"] and risk["vetoes"] == []

        # Hostile / malformed input: JSON answer, server stays alive.
        hostile = [
            "/api/v2/scenario?id=" + urllib.parse.quote("../../etc/passwd"),
            "/api/v2/scenario?id=" + urllib.parse.quote("' OR 1=1 --"),
            "/api/v2/scenario?id=" + urllib.parse.quote("x" * 5000),
            "/api/v2/candles?symbol=" + urllib.parse.quote("BTC;DROP TABLE") + "&tf=zzz&limit=abc",
            "/api/v2/session?symbol=" + urllib.parse.quote("<script>alert(1)</script>"),
            "/api/v2/journal?kind=" + urllib.parse.quote("../x"),
            "/api/v2/nope",
        ]
        for path in hostile:
            code, ctype, body = get(path)
            assert code in (200, 500) and "application/json" in ctype, (path, code, ctype)
            data = json.loads(body)
            assert data.get("ok") in (False, True) or "scenarios" in data, (path, data)
            walk(data, path)
        assert get("/api/v2/home")[0] == 200, "server died after hostile input"
        tables = subprocess.run([sys.executable, "-c",
                                 f"import sqlite3;print(sqlite3.connect({db!r}).execute(\"select count(*) from office_signals\").fetchone()[0])"],
                                capture_output=True, text=True).stdout.strip()
        assert tables == "2", "database must be untouched by hostile params"
    finally:
        proc.terminate()
    # Database outage: DB-backed endpoints answer 503 (UI shows an error state, not "no scenarios");
    # candles/session/settings do not need the database and keep working.
    bad_db = str(Path(tmp) / "missing-dir" / "x.db")
    s2 = socket.socket(); s2.bind(("127.0.0.1", 0)); port2 = s2.getsockname()[1]; s2.close()
    env2 = {**env, "OFFICE_DB_PATH": bad_db, "OFFICE_MINI_PORT": str(port2)}
    proc2 = subprocess.Popen([sys.executable, "-u", str(ROOT / "office_mini_app.py")], env=env2,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port2), 0.2).close(); break
            except OSError:
                time.sleep(0.2)
        for path in ("/api/v2/scenarios", "/api/v2/journal?kind=scenarios", "/api/v2/risk", "/api/v2/home"):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port2}{path}", timeout=20)
                raise AssertionError(f"{path}: expected 503 when the database is down")
            except urllib.error.HTTPError as e:
                assert e.code == 503, (path, e.code)
                body = json.loads(e.read())
                assert body["data_status"] == "DB_UNAVAILABLE" and body["ok"] is False, body
        for path in ("/api/v2/settings", "/api/v2/candles?symbol=ETHUSDT&tf=H1&limit=30"):
            with urllib.request.urlopen(f"http://127.0.0.1:{port2}{path}", timeout=20) as r:
                assert r.status == 200, path
    finally:
        proc2.terminate()
    print("OK API contract: every /api/v2 endpoint, no truthy order flags, no float tails, hostile input survives")


if __name__ == "__main__":
    main()
