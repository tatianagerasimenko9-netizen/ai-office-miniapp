from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


DB_PATH = os.getenv("OFFICE_DB_PATH", "office_bridge.db")
HOST = os.getenv("OFFICE_MINI_HOST", "127.0.0.1")
PORT = int(os.getenv("OFFICE_MINI_PORT", "8790"))


def q(sql: str, params: tuple = ()) -> list[tuple]:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(sql, params).fetchall()


def safe_json_list(raw: str) -> list[str]:
    try:
        arr = json.loads(raw or "[]")
        if isinstance(arr, list):
            return [str(x) for x in arr if str(x).strip()]
    except Exception:
        pass
    return []


def get_data() -> dict:
    rows_decisions = q(
        """
        SELECT ts_utc, signal_id, symbol, action
        FROM office_decisions
        ORDER BY id DESC
        LIMIT 20
        """
    )
    rows_journal = q(
        """
        SELECT ts_open_utc, ts_close_utc, symbol, direction, status, outcome, pnl_pct, r_multiple, mistake_tags_json, review_note
        FROM trade_journal
        ORDER BY ts_open_utc DESC
        LIMIT 40
        """
    )
    rows_events = q(
        """
        SELECT ts_utc, event_type, signal_id, payload_json
        FROM office_events
        ORDER BY id DESC
        LIMIT 40
        """
    )

    wins = 0
    losses = 0
    be = 0
    pnl_sum = 0.0
    r_vals: list[float] = []
    mistakes: dict[str, int] = {}
    for r in rows_journal:
        outcome = str(r[5] or "").upper()
        if outcome == "WIN":
            wins += 1
        elif outcome == "LOSS":
            losses += 1
        elif outcome == "BE":
            be += 1
        try:
            pnl_sum += float(r[6] or 0.0)
        except Exception:
            pass
        try:
            if r[7] is not None:
                r_vals.append(float(r[7]))
        except Exception:
            pass
        for t in safe_json_list(str(r[8] or "[]")):
            k = t.strip().lower()
            if k:
                mistakes[k] = mistakes.get(k, 0) + 1

    total = wins + losses + be
    wr = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else 0.0
    avg_r = (sum(r_vals) / len(r_vals)) if r_vals else 0.0

    return {
        "now_utc": datetime.utcnow().isoformat(),
        "kpi": {
            "total": total,
            "wins": wins,
            "losses": losses,
            "be": be,
            "wr_pct": round(wr, 2),
            "pnl_sum_pct": round(pnl_sum, 2),
            "avg_r": round(avg_r, 2),
        },
        "decisions": [
            {"ts_utc": r[0], "signal_id": r[1], "symbol": r[2], "action": r[3]}
            for r in rows_decisions
        ],
        "journal": [
            {
                "ts_open_utc": r[0],
                "ts_close_utc": r[1],
                "symbol": r[2],
                "direction": r[3],
                "status": r[4],
                "outcome": r[5],
                "pnl_pct": r[6],
                "r_multiple": r[7],
                "mistakes": safe_json_list(str(r[8] or "[]")),
                "review_note": r[9] or "",
            }
            for r in rows_journal
        ],
        "events": [
            {"ts_utc": r[0], "event_type": r[1], "signal_id": r[2], "payload_json": str(r[3] or "{}")}
            for r in rows_events
        ],
        "mistakes_top": [
            {"tag": k, "count": v}
            for k, v in sorted(mistakes.items(), key=lambda x: (-x[1], x[0]))[:8]
        ],
    }


def html() -> str:
    return """<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Office Mini App</title>
  <style>
    body { font-family: Arial, sans-serif; background:#0f172a; color:#e2e8f0; margin:0; }
    .wrap { padding:14px; max-width:1280px; margin:0 auto; }
    h1 { margin:0 0 8px 0; font-size:22px; }
    .row { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:12px; }
    .card { background:#1e293b; border:1px solid #334155; border-radius:10px; padding:10px; min-width:130px; }
    .muted { color:#94a3b8; font-size:12px; }
    .grid { display:grid; grid-template-columns:2fr 1fr; gap:12px; }
    .panel { background:#111827; border:1px solid #334155; border-radius:10px; padding:10px; }
    table { width:100%; border-collapse:collapse; }
    th,td { border:1px solid #334155; padding:6px; font-size:12px; text-align:left; }
    th { background:#1f2937; }
    input,select,button { background:#1f2937; color:#e2e8f0; border:1px solid #334155; border-radius:6px; padding:6px; }
    #tv { height:520px; }
    .ok { color:#22c55e; }
    .bad { color:#ef4444; }
  </style>
</head>
<body>
<div class="wrap">
  <h1>AI Trading Desk · Mini App Live</h1>
  <div class="muted">Живий графік + журнал + помилки (простий режим)</div>

  <div class="row">
    <div class="card">Символ<br><input id="symbol" value="BTCUSDT" style="width:110px;" /></div>
    <div class="card">TF<br>
      <select id="tf">
        <option value="5">5m</option>
        <option value="15" selected>15m</option>
        <option value="60">1h</option>
        <option value="240">4h</option>
      </select>
    </div>
    <div class="card">BTC 24h<br><b id="btc24">...</b></div>
    <div class="card">SYMBOL 24h<br><b id="sym24">...</b></div>
    <div class="card">Оновити<br><button onclick="reloadAll()">Refresh</button></div>
  </div>

  <div class="grid">
    <div class="panel">
      <div id="tv"></div>
    </div>
    <div class="panel">
      <div><b>Desk KPI</b></div>
      <div id="kpi" class="muted">loading...</div>
      <hr />
      <div><b>Top mistakes</b></div>
      <table id="mistakes"></table>
    </div>
  </div>

  <div class="panel" style="margin-top:12px;">
    <b>Останні рішення</b>
    <table id="decisions"></table>
  </div>

  <div class="panel" style="margin-top:12px;">
    <b>Журнал угод</b>
    <table id="journal"></table>
  </div>
</div>

<script src="https://s3.tradingview.com/tv.js"></script>
<script>
let widget = null;
function loadTV() {
  const sym = (document.getElementById('symbol').value || 'BTCUSDT').toUpperCase();
  const tf = document.getElementById('tf').value;
  const tvsym = "BINANCE:" + sym;
  if (widget && widget.remove) {
    widget.remove();
  }
  document.getElementById('tv').innerHTML = "";
  widget = new TradingView.widget({
    autosize: true,
    symbol: tvsym,
    interval: tf,
    timezone: "Etc/UTC",
    theme: "dark",
    style: "1",
    locale: "en",
    container_id: "tv",
    studies: ["BB@tv-basicstudies", "MAExp@tv-basicstudies", "MAExp@tv-basicstudies"]
  });
}

async function fetchTicker(symbol) {
  const url = "https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=" + encodeURIComponent(symbol);
  const r = await fetch(url);
  if (!r.ok) throw new Error("ticker " + r.status);
  return await r.json();
}

function fmtPct(v) {
  const n = Number(v || 0);
  const cls = n >= 0 ? "ok" : "bad";
  return '<span class="' + cls + '">' + (n >= 0 ? '+' : '') + n.toFixed(2) + '%</span>';
}

async function loadTickers() {
  const sym = (document.getElementById('symbol').value || 'BTCUSDT').toUpperCase();
  try {
    const [btc, alt] = await Promise.all([fetchTicker('BTCUSDT'), fetchTicker(sym)]);
    document.getElementById('btc24').innerHTML = fmtPct(btc.priceChangePercent);
    document.getElementById('sym24').innerHTML = fmtPct(alt.priceChangePercent);
  } catch (e) {
    document.getElementById('btc24').textContent = 'err';
    document.getElementById('sym24').textContent = 'err';
  }
}

function t(id, html) { document.getElementById(id).innerHTML = html; }

async function loadOffice() {
  const r = await fetch('/api/summary');
  const d = await r.json();
  t('kpi',
    'Угод: <b>' + d.kpi.total + '</b><br>' +
    'W/L/BE: <b>' + d.kpi.wins + '/' + d.kpi.losses + '/' + d.kpi.be + '</b><br>' +
    'WR: <b>' + d.kpi.wr_pct.toFixed(1) + '%</b><br>' +
    'PnL sum: <b>' + (d.kpi.pnl_sum_pct >= 0 ? '+' : '') + d.kpi.pnl_sum_pct.toFixed(2) + '%</b><br>' +
    'Avg R: <b>' + (d.kpi.avg_r >= 0 ? '+' : '') + d.kpi.avg_r.toFixed(2) + '</b>'
  );

  t('mistakes',
    '<tr><th>Тег</th><th>К-сть</th></tr>' +
    (d.mistakes_top || []).map(x => '<tr><td>' + x.tag + '</td><td>' + x.count + '</td></tr>').join('')
  );

  t('decisions',
    '<tr><th>Час</th><th>Сигнал</th><th>Символ</th><th>Дія</th></tr>' +
    (d.decisions || []).slice(0, 12).map(x =>
      '<tr><td>' + x.ts_utc + '</td><td>' + x.signal_id + '</td><td>' + x.symbol + '</td><td><b>' + x.action + '</b></td></tr>'
    ).join('')
  );

  t('journal',
    '<tr><th>Open</th><th>Symbol</th><th>Side</th><th>Outcome</th><th>PnL</th><th>R</th><th>Mistakes</th><th>Нотатка</th></tr>' +
    (d.journal || []).slice(0, 16).map(x =>
      '<tr><td>' + (x.ts_open_utc || '') + '</td><td>' + x.symbol + '</td><td>' + x.direction + '</td><td>' + (x.outcome || '') + '</td>' +
      '<td>' + (x.pnl_pct == null ? '' : ((Number(x.pnl_pct)>=0?'+':'') + Number(x.pnl_pct).toFixed(2) + '%')) + '</td>' +
      '<td>' + (x.r_multiple == null ? '' : ((Number(x.r_multiple)>=0?'+':'') + Number(x.r_multiple).toFixed(2) + 'R')) + '</td>' +
      '<td>' + (x.mistakes || []).slice(0,3).join(', ') + '</td><td>' + (x.review_note || '') + '</td></tr>'
    ).join('')
  );
}

async function reloadAll() {
  loadTV();
  await loadTickers();
  await loadOffice();
}

document.getElementById('symbol').addEventListener('change', reloadAll);
document.getElementById('tf').addEventListener('change', reloadAll);
reloadAll();
setInterval(loadTickers, 7000);
setInterval(loadOffice, 9000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path == "/api/summary":
            body = json.dumps(get_data(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/":
            body = html().encode("utf-8")
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
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"mini-app: http://{HOST}:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()

