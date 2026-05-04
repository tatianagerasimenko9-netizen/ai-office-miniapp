from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


DB_PATH = os.getenv("OFFICE_DB_PATH", "office_bridge.db")
HOST = os.getenv("OFFICE_DASH_HOST", "127.0.0.1")
PORT = int(os.getenv("OFFICE_DASH_PORT", "8787"))


def q(sql: str, params: tuple = ()) -> list[tuple]:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(sql, params).fetchall()


def _safe_json(value: str) -> dict:
    try:
        obj = json.loads(value or "{}")
        return obj if isinstance(obj, dict) else {"raw": value}
    except Exception:
        return {"raw": value}


def _safe_json_list(value: str) -> list[str]:
    try:
        obj = json.loads(value or "[]")
        if isinstance(obj, list):
            return [str(x) for x in obj if str(x).strip()]
    except Exception:
        pass
    return []


def _mistakes_top(rows_journal: list[tuple]) -> list[dict]:
    acc: dict[str, int] = {}
    for r in rows_journal:
        tags = _safe_json_list(str(r[10] or "[]"))
        for t in tags:
            k = t.strip().lower()
            if not k:
                continue
            acc[k] = acc.get(k, 0) + 1
    items = sorted(acc.items(), key=lambda x: (-x[1], x[0]))[:8]
    return [{"tag": k, "count": v} for k, v in items]


def _fmt_pct(value: object) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):+.2f}%"
    except Exception:
        return ""


def _fmt_r(value: object) -> str:
    if value is None:
        return ""
    try:
        return f"{float(value):+.2f}R"
    except Exception:
        return ""


def get_summary() -> dict:
    now = datetime.utcnow().isoformat()
    rows_tasks = q(
        """
        SELECT task_id, title, assignee, status, ts_utc
        FROM office_tasks
        ORDER BY id DESC
        LIMIT 25
        """
    )
    rows_decisions = q(
        """
        SELECT signal_id, symbol, action, ts_utc
        FROM office_decisions
        ORDER BY id DESC
        LIMIT 25
        """
    )
    rows_events = q(
        """
        SELECT event_type, signal_id, payload_json, ts_utc
        FROM office_events
        ORDER BY id DESC
        LIMIT 25
        """
    )
    rows_messages = q(
        """
        SELECT signal_id, turn_idx, agent_key, message, ts_utc
        FROM office_messages
        ORDER BY id DESC
        LIMIT 40
        """
    )
    rows_journal = q(
        """
        SELECT trade_id, ts_open_utc, ts_close_utc, symbol, direction, status, outcome, pnl_pct, r_multiple, exit_reason, mistake_tags_json
        FROM trade_journal
        ORDER BY ts_open_utc DESC
        LIMIT 30
        """
    )

    counts = {
        "tasks_open": sum(1 for r in rows_tasks if str(r[3]) == "OPEN"),
        "tasks_progress": sum(1 for r in rows_tasks if str(r[3]) == "IN_PROGRESS"),
        "tasks_review": sum(1 for r in rows_tasks if str(r[3]) == "REVIEW"),
        "tasks_done": sum(1 for r in rows_tasks if str(r[3]) == "DONE"),
        "tasks_blocked": sum(1 for r in rows_tasks if str(r[3]) == "BLOCKED"),
    }
    return {
        "now_utc": now,
        "counts": counts,
        "tasks": [
            {"task_id": r[0], "title": r[1], "assignee": r[2], "status": r[3], "ts_utc": r[4]}
            for r in rows_tasks
        ],
        "decisions": [
            {"signal_id": r[0], "symbol": r[1], "action": r[2], "ts_utc": r[3]}
            for r in rows_decisions
        ],
        "events": [
            {
                "event_type": r[0],
                "signal_id": r[1],
                "payload": _safe_json(r[2]),
                "ts_utc": r[3],
            }
            for r in rows_events
        ],
        "messages": [
            {"signal_id": r[0], "turn_idx": r[1], "agent_key": r[2], "message": r[3], "ts_utc": r[4]}
            for r in rows_messages
        ],
        "journal": [
            {
                "trade_id": r[0],
                "ts_open_utc": r[1],
                "ts_close_utc": r[2],
                "symbol": r[3],
                "direction": r[4],
                "status": r[5],
                "outcome": r[6],
                "pnl_pct": r[7],
                "r_multiple": r[8],
                "exit_reason": r[9],
                "mistakes": _safe_json_list(r[10]),
            }
            for r in rows_journal
        ],
        "mistakes_top": _mistakes_top(rows_journal),
    }


def html_page(data: dict) -> str:
    counts = data["counts"]
    rows_dec = "".join(
        f"<tr><td>{d['ts_utc']}</td><td>{d['signal_id']}</td><td>{d['symbol']}</td><td><b>{d['action']}</b></td></tr>"
        for d in data["decisions"][:12]
    )
    rows_tasks = "".join(
        f"<tr><td>{t['ts_utc']}</td><td>{t['task_id']}</td><td>{t['assignee']}</td><td>{t['status']}</td><td>{t['title']}</td></tr>"
        for t in data["tasks"][:12]
    )
    rows_events = "".join(
        f"<tr><td>{e['ts_utc']}</td><td>{e['event_type']}</td><td>{e['signal_id'] or ''}</td><td>{json.dumps(e['payload'], ensure_ascii=False)[:180]}</td></tr>"
        for e in data["events"][:12]
    )
    rows_journal = "".join(
        f"<tr><td>{j['ts_open_utc']}</td><td>{j['symbol']}</td><td>{j['direction']}</td><td>{j['status']}</td><td>{j['outcome'] or ''}</td><td>{_fmt_pct(j['pnl_pct'])}</td><td>{_fmt_r(j['r_multiple'])}</td><td>{j['exit_reason'] or ''}</td><td>{', '.join(j['mistakes'][:3])}</td></tr>"
        for j in data["journal"][:15]
    )
    rows_mistakes = "".join(
        f"<tr><td>{m['tag']}</td><td>{m['count']}</td></tr>"
        for m in data["mistakes_top"]
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta http-equiv="refresh" content="10" />
  <title>AI Office Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; background:#10141c; color:#eef2ff; margin:20px; }}
    .cards {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px; }}
    .card {{ background:#1a2130; padding:12px; border-radius:8px; min-width:130px; }}
    table {{ width:100%; border-collapse:collapse; background:#151b28; margin-bottom:16px; }}
    th,td {{ border:1px solid #2c3448; padding:8px; font-size:12px; text-align:left; }}
    th {{ background:#20283a; }}
    h2 {{ margin-top:24px; }}
    .muted {{ color:#94a3b8; font-size:12px; }}
  </style>
</head>
<body>
  <h1>AI Office Dashboard (MVP)</h1>
  <div class="muted">UTC: {data['now_utc']} · DB: {DB_PATH}</div>
  <div class="cards">
    <div class="card">OPEN<br><b>{counts['tasks_open']}</b></div>
    <div class="card">IN_PROGRESS<br><b>{counts['tasks_progress']}</b></div>
    <div class="card">REVIEW<br><b>{counts['tasks_review']}</b></div>
    <div class="card">DONE<br><b>{counts['tasks_done']}</b></div>
    <div class="card">BLOCKED<br><b>{counts['tasks_blocked']}</b></div>
  </div>

  <h2>Latest Decisions</h2>
  <table><tr><th>Time</th><th>Signal</th><th>Symbol</th><th>Action</th></tr>{rows_dec}</table>

  <h2>Task Workflow</h2>
  <table><tr><th>Time</th><th>Task ID</th><th>Assignee</th><th>Status</th><th>Title</th></tr>{rows_tasks}</table>

  <h2>Office Events</h2>
  <table><tr><th>Time</th><th>Event</th><th>Signal</th><th>Payload</th></tr>{rows_events}</table>

  <h2>Trade Journal</h2>
  <table><tr><th>Open Time</th><th>Symbol</th><th>Side</th><th>Status</th><th>Outcome</th><th>PnL</th><th>R</th><th>Exit Reason</th><th>Mistakes</th></tr>{rows_journal}</table>

  <h2>Top Mistakes (Recent)</h2>
  <table><tr><th>Tag</th><th>Count</th></tr>{rows_mistakes}</table>

  <div class="muted">Auto refresh: every 10 seconds</div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        p = urlparse(self.path)
        if p.path == "/api/summary":
            data = get_summary()
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if p.path == "/":
            data = get_summary()
            body = html_page(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def main() -> None:
    if not os.path.exists(DB_PATH):
        print(f"[warn] DB file not found yet: {DB_PATH}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"dashboard: http://{HOST}:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

