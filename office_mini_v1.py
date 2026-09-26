"""Mini App v1: лише читання (як GGShot). Без кнопок ордерів.

Вкладки: Головна, Сигнали, Сканер, Мої позиції (/position), Статистика.
Немає даних → DATA_UNAVAILABLE. Не змінює ATR/Edge/MIN_RR.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from office_bridge import (
    is_confirmed_position_row,
    signal_get_active,
    _fetchall,
)
from office_signal_stats import DATA_UNAVAILABLE, build_stats_report

def _db() -> str:
    return os.getenv("OFFICE_DB_PATH", "office_bridge.db")


def _status_ua(st: Any) -> str:
    u = str(st or "").upper()
    if u in ("WATCHING", "WAIT"):
        return "чекаємо"
    if u in ("HIT_TP1", "TP1"):
        return "TP1"
    if u in ("HIT_TP2", "TP2", "CLOSED", "EXPIRED", "STOPPED", "HIT_SL"):
        return "закрито"
    if u in ("ACTIVE", "HIT_ENTRY"):
        return "активний"
    return u.lower() or "чекаємо"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def key_levels(symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """Рівні з активних сигналів / журналу. Не вигадуємо."""
    out: Dict[str, Any] = {"symbol": symbol.upper(), "data_status": DATA_UNAVAILABLE, "levels": {}}
    try:
        from office_bridge import signal_get_latest_by_symbol

        row = signal_get_latest_by_symbol(_db(), symbol)
    except Exception:
        row = None
    if not row:
        return out
    lv = {
        "entry_low": _f(row.get("entry_low")),
        "entry_high": _f(row.get("entry_high")),
        "sl": _f(row.get("sl")),
        "tp1": _f(row.get("tp1")),
        "tp2": _f(row.get("tp2")),
    }
    if not any(v is not None for v in lv.values()):
        return out
    out["data_status"] = "DATA_OK"
    out["levels"] = lv
    return out


def home_payload() -> Dict[str, Any]:
    from office_mini_app import build_live_state

    live = build_live_state()
    btc = live.get("btc") or {}
    regime = None
    try:
        from office_market_state import market_state_get

        st = market_state_get(_db(), "BTCUSDT") or {}
        regime = st.get("regime")
    except Exception:
        regime = None
    active = []
    try:
        for r in signal_get_active(_db()):
            if str(r.get("status") or "").upper() == "WATCHING":
                continue
            active.append(
                {
                    "symbol": r.get("symbol"),
                    "direction": r.get("direction"),
                    "status": _status_ua(r.get("status")),
                    "entry_low": r.get("entry_low"),
                    "entry_high": r.get("entry_high"),
                    "sl": r.get("sl"),
                    "tp1": r.get("tp1"),
                    "rr": r.get("rr"),
                }
            )
    except Exception:
        active = []
    lv = key_levels("BTCUSDT")
    return {
        "ok": True,
        "readonly": True,
        "btc": {
            "price": btc.get("price"),
            "change_24h": btc.get("change_24h"),
            "regime": regime,
            "data_status": "DATA_OK" if btc.get("price") is not None else DATA_UNAVAILABLE,
        },
        "market_mode": regime or live.get("sessions", {}).get("active") or DATA_UNAVAILABLE,
        "levels": lv,
        "active_signals": active,
        "sessions": live.get("sessions"),
        "gex": None,
        "orders": False,
    }


def signals_payload() -> Dict[str, Any]:
    cards: List[Dict[str, Any]] = []
    try:
        rows = _fetchall(
            _db(),
            """
            SELECT signal_id, symbol, direction, entry_low, entry_high, sl, tp1, tp2, rr,
                   status, ts_created, outcome, analysis_note
            FROM office_signals
            ORDER BY ts_created DESC
            LIMIT 40
            """,
            (),
        )
    except Exception:
        rows = []
    for r in rows:
        cards.append(
            {
                "signal_id": r[0],
                "symbol": r[1],
                "direction": r[2],
                "timeframe": "H1",
                "entry_low": r[3],
                "entry_high": r[4],
                "sl": r[5],
                "tp": r[6],
                "tp2": r[7],
                "rr": r[8],
                "status": _status_ua(r[9]),
                "status_raw": r[9],
                "chart_url": f"/api/v1/chart.png?symbol={r[1]}",
                "note": str(r[12] or "")[:240],
            }
        )
    return {
        "ok": True,
        "readonly": True,
        "data_status": "DATA_OK" if cards else DATA_UNAVAILABLE,
        "cards": cards,
    }


def scanner_payload() -> Dict[str, Any]:
    """Топ-кандидати зі збереженого market_state. Без алертів."""
    try:
        rows = _fetchall(
            _db(),
            """
            SELECT symbol, regime, signal_json, office_decision, data_quality, ts_updated
            FROM market_state
            ORDER BY ts_updated DESC
            LIMIT 40
            """,
            (),
        )
    except Exception:
        rows = []
    cands = []
    for r in rows:
        sig = {}
        try:
            obj = json.loads(str(r[2] or "{}"))
            if isinstance(obj, dict):
                sig = obj
        except Exception:
            sig = {}
        score = sig.get("score") or sig.get("pump_score") or sig.get("ict_score")
        if score is None and not sig:
            continue
        cands.append(
            {
                "symbol": r[0],
                "score": score,
                "rsi": sig.get("rsi") or sig.get("rsi_h1"),
                "pump": sig.get("pump_score"),
                "dump": sig.get("dump_score"),
                "regime": r[1],
                "decision": r[3],
                "quality": r[4],
            }
        )
    cands.sort(key=lambda x: float(x.get("score") or 0), reverse=True)
    return {
        "ok": True,
        "readonly": True,
        "alerts": False,
        "data_status": "DATA_OK" if cands else DATA_UNAVAILABLE,
        "candidates": cands[:15],
    }


def positions_payload() -> Dict[str, Any]:
    """Лише /position, окремо від сигналів."""
    try:
        rows = _fetchall(
            _db(),
            """
            SELECT trade_id, symbol, direction, status, entry_price, stop_loss, take_profit,
                   pnl_pct, entry_reason, setup_name, ts_open_utc
            FROM trade_journal
            ORDER BY ts_open_utc DESC
            LIMIT 80
            """,
            (),
        )
    except Exception:
        rows = []
    live = []
    for r in rows:
        if not is_confirmed_position_row(r[8], r[9], r[0]):
            continue
        live.append(
            {
                "trade_id": r[0],
                "symbol": r[1],
                "direction": r[2],
                "status": r[3],
                "entry": r[4],
                "sl": r[5],
                "tp": r[6],
                "pnl_pct": r[7],
                "source": "/position",
            }
        )
    return {
        "ok": True,
        "readonly": True,
        "kind": "position_only",
        "data_status": "DATA_OK" if live else DATA_UNAVAILABLE,
        "positions": live,
        "note": "Сигнали офісу сюди не потрапляють.",
    }


def stats_payload() -> Dict[str, Any]:
    rep = build_stats_report(_db())
    return {
        "ok": bool(rep.get("ok")),
        "readonly": True,
        "data_status": rep.get("data_status"),
        "message": rep.get("message"),
        "one_liner": rep.get("one_liner"),
        "n": rep.get("n"),
    }


def render_chart_png(symbol: str) -> Dict[str, Any]:
    from office_chart_png import render_signal_chart, chart_levels
    from office_market_data import fetch_candles

    sym = str(symbol or "BTCUSDT").upper()
    m15 = fetch_candles(sym, "15m", 96) or []
    h1 = fetch_candles(sym, "1h", 48) or []
    lv = {}
    try:
        from office_bridge import signal_get_latest_by_symbol

        row = signal_get_latest_by_symbol(_db(), sym) or {}
        lv = chart_levels(
            sl=row.get("sl"),
            tp1=row.get("tp1"),
            tp2=row.get("tp2"),
            entry_low=row.get("entry_low"),
            entry_high=row.get("entry_high"),
        )
    except Exception:
        lv = {}
    return render_signal_chart(symbol=sym, candles_m15=m15, candles_h1=h1, levels=lv)


def html_v1() -> str:
    return """<!doctype html>
<html lang="uk"><head>
<meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>AI Office · Mini App v1</title>
<style>
:root{--bg:#070b12;--card:#121826;--line:#243044;--txt:#e8eef8;--mut:#8aa0b8;--ok:#3dd68c;--bad:#ff5d73;--acc:#7c9cff}
*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,sans-serif;background:var(--bg);color:var(--txt)}
nav{display:flex;gap:6px;padding:10px 12px;background:#0c1220;border-bottom:1px solid var(--line);position:sticky;top:0}
nav button{background:#1a2333;border:1px solid var(--line);color:var(--txt);border-radius:8px;padding:8px 10px;font-size:13px}
nav button.on{background:var(--acc);color:#081018;font-weight:700}
.wrap{padding:12px;max-width:920px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;margin:0 0 10px}
.mut{color:var(--mut);font-size:12px}.row{display:flex;gap:8px;flex-wrap:wrap}
.kpi{flex:1;min-width:120px}.ok{color:var(--ok)}.bad{color:var(--bad)}
img.ch{width:100%;border-radius:8px;border:1px solid var(--line);background:#000}
h2{font-size:16px;margin:0 0 8px}h1{font-size:18px;margin:0 0 8px}
table{width:100%;border-collapse:collapse;font-size:12px}td,th{border-bottom:1px solid var(--line);padding:6px;text-align:left}
.banner{font-size:11px;color:var(--mut);margin-bottom:8px}
</style></head><body>
<nav>
<button data-tab="home" class="on">Головна</button>
<button data-tab="signals">Сигнали</button>
<button data-tab="scan">Сканер</button>
<button data-tab="pos">Мої позиції</button>
<button data-tab="stats">Статистика</button>
</nav>
<div class="wrap">
<div class="banner">Лише читання. Кнопок ордерів немає. Немає даних → DATA_UNAVAILABLE.</div>
<div id="app">…</div>
</div>
<script>
const $ = id => document.getElementById(id);
const app = $('app');
function una(v){ return (v===null||v===undefined||v==='') ? 'DATA_UNAVAILABLE' : v; }
async function j(url){ const r = await fetch(url); return r.json(); }
async function home(){
  const d = await j('/api/v1/home');
  const b = d.btc||{};
  const lv = (d.levels&&d.levels.levels)||{};
  const sig = (d.active_signals||[]).map(s=>`<div class="card">${s.symbol} ${s.direction} · ${s.status}<div class="mut">вхід ${una(s.entry_low)}–${una(s.entry_high)} SL ${una(s.sl)} TP ${una(s.tp1)} RR ${una(s.rr)}</div></div>`).join('') || '<div class="mut">DATA_UNAVAILABLE — активних сигналів немає</div>';
  app.innerHTML = `<h1>Головна</h1>
  <div class="row">
    <div class="card kpi"><div class="mut">BTC</div><b>${una(b.price)}</b><div class="mut">24h ${una(b.change_24h)}%</div></div>
    <div class="card kpi"><div class="mut">Режим</div><b>${una(d.market_mode)}</b></div>
    <div class="card kpi"><div class="mut">Сесія</div><b>${una((d.sessions||{}).active)}</b></div>
  </div>
  <div class="card"><h2>Ключові рівні BTC</h2>
    <div class="mut">Entry ${una(lv.entry_low)}–${una(lv.entry_high)} · SL ${una(lv.sl)} · TP1 ${una(lv.tp1)}</div>
    <div class="mut">GEX: ${una(d.gex)}</div>
  </div>
  <h2>Активні сигнали</h2>${sig}`;
}
async function signals(){
  const d = await j('/api/v1/signals');
  const cards = (d.cards||[]).map(c=>`<div class="card">
    <b>${c.symbol}</b> ${c.timeframe} ${c.direction} · ${c.status}
    <div class="mut">зона ${una(c.entry_low)}–${una(c.entry_high)} · SL ${una(c.sl)} · TP ${una(c.tp)} · RR ${una(c.rr)}</div>
    <img class="ch" alt="chart" src="${c.chart_url}"/>
  </div>`).join('') || `<div class="mut">${una(d.data_status)}</div>`;
  app.innerHTML = `<h1>Сигнали</h1>${cards}`;
}
async function scan(){
  const d = await j('/api/v1/scanner');
  const rows = (d.candidates||[]).map(c=>`<tr><td>${c.symbol}</td><td>${una(c.score)}</td><td>${una(c.rsi)}</td><td>${una(c.pump)}/${una(c.dump)}</td></tr>`).join('');
  app.innerHTML = `<h1>Сканер</h1><div class="mut">Без алертів. ${d.data_status||''}</div>
  <div class="card"><table><tr><th>Монета</th><th>Score</th><th>RSI</th><th>PUMP/DUMP</th></tr>${rows||'<tr><td colspan=4>DATA_UNAVAILABLE</td></tr>'}</table></div>`;
}
async function pos(){
  const d = await j('/api/v1/positions');
  const rows = (d.positions||[]).map(p=>`<div class="card"><b>${p.symbol}</b> ${p.direction} ${p.status}
    <div class="mut">entry ${una(p.entry)} SL ${una(p.sl)} PnL ${una(p.pnl_pct)} · лише /position</div></div>`).join('');
  app.innerHTML = `<h1>Мої позиції</h1><div class="mut">${d.note||''}</div>${rows||'<div class="mut">DATA_UNAVAILABLE — немає /position</div>'}`;
}
async function stats(){
  const d = await j('/api/v1/stats');
  app.innerHTML = `<h1>Статистика</h1><div class="card"><pre style="white-space:pre-wrap">${d.message||'DATA_UNAVAILABLE'}</pre></div>`;
}
const tabs = {home, signals, scan, pos, stats};
document.querySelectorAll('nav button').forEach(b=>{
  b.onclick=()=>{
    document.querySelectorAll('nav button').forEach(x=>x.classList.remove('on'));
    b.classList.add('on');
    tabs[b.dataset.tab]();
  };
});
home();
</script></body></html>
"""
