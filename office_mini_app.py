from __future__ import annotations

import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from office_bridge import office_db_identity

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None  # type: ignore[assignment]


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
DB_PATH = os.getenv("OFFICE_DB_PATH", "office_bridge.db")
HOST = os.getenv("OFFICE_MINI_HOST", "127.0.0.1")
PORT = int(os.getenv("OFFICE_MINI_PORT", "8790"))


def _is_pg() -> bool:
    s = str(DATABASE_URL or "").strip().lower()
    return s.startswith("postgres://") or s.startswith("postgresql://")


def _db_target_for_identity() -> str:
    """Той самий рядок підключення, що й у relay (`DATABASE_URL` або шлях SQLite)."""
    if _is_pg():
        return DATABASE_URL
    return DB_PATH


def q(sql: str, params: tuple = ()) -> list[tuple]:
    if _is_pg():
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is set")
        qry = sql.replace("?", "%s")
        with psycopg.connect(DATABASE_URL) as conn:  # type: ignore[arg-type]
            with conn.cursor() as cur:
                cur.execute(qry, params)
                rows = cur.fetchall()
        return [tuple(r) for r in rows]
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


def safe_json_objects(raw: str) -> list[dict]:
    try:
        arr = json.loads(raw or "[]")
        if isinstance(arr, list):
            return [x for x in arr if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _parse_ts_close(s: object) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _f_or_none(x: object) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except Exception:
        return None


def build_live_overlays(chart_symbol: str) -> dict[str, object]:
    """
    Рівні з trade_journal для символу на графіку (backlog: live overlays у Mini App).
    """
    cs = chart_symbol.strip().upper()
    open_trade: dict[str, object] | None = None
    last_closed: dict[str, object] | None = None

    try:
        if cs:
            rows = q(
                """
                SELECT trade_id, symbol, direction, entry_price, stop_loss, take_profit,
                       ts_open_utc, setup_name, timeframe
                FROM trade_journal
                WHERE status = 'OPEN' AND UPPER(symbol) = ?
                ORDER BY ts_open_utc DESC
                LIMIT 1
                """,
                (cs,),
            )
        else:
            rows = q(
                """
                SELECT trade_id, symbol, direction, entry_price, stop_loss, take_profit,
                       ts_open_utc, setup_name, timeframe
                FROM trade_journal
                WHERE status = 'OPEN'
                ORDER BY ts_open_utc DESC
                LIMIT 1
                """,
                (),
            )
        if rows:
            r = rows[0]
            open_trade = {
                "trade_id": str(r[0] or ""),
                "symbol": str(r[1] or ""),
                "direction": str(r[2] or ""),
                "entry_price": _f_or_none(r[3]),
                "stop_loss": _f_or_none(r[4]),
                "take_profit": _f_or_none(r[5]),
                "ts_open_utc": str(r[6] or ""),
                "setup_name": str(r[7] or ""),
                "timeframe": str(r[8] or ""),
            }
    except Exception:
        open_trade = None

    try:
        if cs:
            rows_c = q(
                """
                SELECT trade_id, entry_price, exit_price, stop_loss, take_profit, outcome, ts_close_utc
                FROM trade_journal
                WHERE status = 'CLOSED' AND UPPER(symbol) = ?
                ORDER BY ts_close_utc DESC
                LIMIT 1
                """,
                (cs,),
            )
            if rows_c:
                x = rows_c[0]
                last_closed = {
                    "trade_id": str(x[0] or ""),
                    "entry_price": _f_or_none(x[1]),
                    "exit_price": _f_or_none(x[2]),
                    "stop_loss": _f_or_none(x[3]),
                    "take_profit": _f_or_none(x[4]),
                    "outcome": str(x[5] or ""),
                    "ts_close_utc": str(x[6] or ""),
                }
    except Exception:
        last_closed = None

    return {
        "chart_symbol": cs,
        "open_trade": open_trade,
        "last_closed_hint": last_closed,
    }


def build_review_draft(trade_id: str | None) -> dict[str, object]:
    """
    Чернета stop-review українською (One-Click Review): для Telegram / нотатки / подальшого запису в журнал.
    """
    tid_in = (trade_id or "").strip()
    sel = """
        SELECT trade_id, symbol, direction, status, outcome, pnl_pct, r_multiple,
               entry_price, stop_loss, take_profit, exit_price,
               mistake_tags_json, review_note, ts_open_utc, ts_close_utc,
               setup_name, timeframe, entry_reason, exit_reason
        FROM trade_journal
        """
    row: tuple | None = None
    try:
        if tid_in:
            rows = q(sel + " WHERE trade_id = ? LIMIT 1", (tid_in,))
            row = rows[0] if rows else None
        if row is None:
            rows = q(
                sel + " WHERE status = 'CLOSED' AND UPPER(TRIM(COALESCE(outcome,''))) = 'LOSS' ORDER BY ts_close_utc DESC LIMIT 1",
                (),
            )
            row = rows[0] if rows else None
        if row is None:
            rows = q(sel + " WHERE status = 'CLOSED' ORDER BY ts_close_utc DESC LIMIT 1", ())
            row = rows[0] if rows else None
        if row is None:
            rows = q(sel + " WHERE status = 'OPEN' ORDER BY ts_open_utc DESC LIMIT 1", ())
            row = rows[0] if rows else None
    except Exception:
        row = None

    if row is None:
        return {"ok": False, "error": "no_trade", "draft_ua": "", "trade_id": ""}

    (
        tid,
        symbol,
        direction,
        status,
        outcome,
        pnl_pct,
        r_mult,
        entry_p,
        sl_p,
        tp_p,
        exit_p,
        mist_raw,
        rev_note,
        ts_o,
        ts_c,
        setup_n,
        tf,
        ent_rs,
        ex_rs,
    ) = row
    tags = safe_json_list(str(mist_raw or "[]"))
    tags_txt = ", ".join(tags) if tags else "—"

    def fmtp(label: str, v: object) -> str:
        x = _f_or_none(v)
        return f"{label}: {x:.6g}" if x is not None else f"{label}: —"

    try:
        pnl_s = f"{float(pnl_pct or 0):+.2f}%"
    except Exception:
        pnl_s = str(pnl_pct or "—")
    try:
        r_s = f"{float(r_mult or 0):+.2f}R" if r_mult is not None else "—"
    except Exception:
        r_s = str(r_mult or "—")

    lines = [
        "📋 STOP-REVIEW · чернетка (AI Office Mini App)",
        f"trade_id: {tid}",
        f"Статус: {status} · Символ: {symbol} · Сторона: {direction}",
        f"Результат: {outcome or '—'} · PnL {pnl_s} · R {r_s}",
        f"Відкрито: {ts_o or '—'} · Закрито: {ts_c or '—'}",
        fmtp("Entry", entry_p),
        fmtp("SL", sl_p),
        fmtp("TP", tp_p),
        fmtp("Exit", exit_p),
        f"Сетап / TF: {str(setup_n or '—')} / {str(tf or '—')}",
        f"Причина входу (з журналу): {str(ent_rs or '—')}",
        f"Причина виходу (з журналу): {str(ex_rs or '—')}",
        f"Теги помилок (вже в журналі): {tags_txt}",
        f"Існуюча нотатка review: {str(rev_note or '—')}",
        "",
        "—— Заповни нижче ——",
        "Що пішло не так / що повторилося:",
        "- ",
        "",
        "Що змінюємо наступного разу (1–3 пункти):",
        "1. ",
        "2. ",
        "",
        "(Далі: встав у чат офісу або допиши review_note через процес закриття угоди.)",
    ]
    draft = "\n".join(lines)
    return {
        "ok": True,
        "trade_id": str(tid or ""),
        "draft_ua": draft,
        "had_existing_note": bool(str(rev_note or "").strip()),
    }


def build_risk_heatmap(*, limit_rows: int = 400, min_decided: int = 2, top_n: int = 18) -> dict[str, object]:
    """
    Спрощений risk heatmap: по символам із закритих угод (останні limit_rows записів журналу).
    Чим вища частка LOSS серед WIN+LOSS, тим «гарячіший» ризик у таблиці.
    """
    try:
        rows = q(
            """
            SELECT symbol, outcome, pnl_pct
            FROM trade_journal
            WHERE status = 'CLOSED' AND outcome IS NOT NULL AND TRIM(COALESCE(outcome, '')) <> ''
            ORDER BY ts_close_utc DESC
            LIMIT ?
            """,
            (limit_rows,),
        )
    except Exception:
        rows = []

    agg: dict[str, dict[str, float]] = defaultdict(
        lambda: {"w": 0.0, "l": 0.0, "be": 0.0, "pnl_sum": 0.0, "n": 0.0}
    )
    for sym, outcome, pnl_pct in rows:
        su = str(sym or "").upper().strip()
        if not su:
            continue
        o = str(outcome or "").upper().strip()
        bucket = agg[su]
        bucket["n"] += 1
        try:
            bucket["pnl_sum"] += float(pnl_pct or 0.0)
        except Exception:
            pass
        if o == "WIN":
            bucket["w"] += 1
        elif o == "LOSS":
            bucket["l"] += 1
        elif o == "BE":
            bucket["be"] += 1

    out_rows: list[dict[str, object]] = []
    for sym, st in agg.items():
        w, l, be_ct = int(st["w"]), int(st["l"]), int(st["be"])
        decided = w + l
        if decided < min_decided:
            continue
        loss_share = (l / decided) if decided else 0.0
        wr_pct = (w / decided * 100.0) if decided else 0.0
        ntot = int(st["n"])
        avg_pnl = (st["pnl_sum"] / ntot) if ntot else 0.0
        out_rows.append(
            {
                "symbol": sym,
                "total": ntot,
                "wins": w,
                "losses": l,
                "be": be_ct,
                "wr_pct": round(wr_pct, 1),
                "loss_share": round(loss_share, 3),
                "avg_pnl_pct": round(avg_pnl, 3),
            }
        )

    out_rows.sort(key=lambda x: (-int(x["losses"]), -float(x["loss_share"]), -int(x["total"])))
    out_rows = out_rows[:top_n]

    return {
        "limit_rows": limit_rows,
        "min_decided": min_decided,
        "rows": out_rows,
        "hint_ua": "Зеленіші комірки — менша частка лоссів серед вирішених WIN/LOSS; червоніші — обережніше з символом.",
    }


def get_data(
    *,
    symbol_filter: str = "",
    action_filter: str = "",
    agent_filter: str = "",
    chart_symbol: str = "",
) -> dict:
    sym_f = symbol_filter.strip().upper()
    act_f = action_filter.strip().upper()
    ag_f = agent_filter.strip().lower()

    rows_decisions_raw = q(
        """
        SELECT ts_utc, signal_id, symbol, action, decisions_json
        FROM office_decisions
        ORDER BY id DESC
        LIMIT 120
        """
    )
    rows_journal_raw = q(
        """
        SELECT trade_id, ts_open_utc, ts_close_utc, symbol, direction, status, outcome, pnl_pct, r_multiple, mistake_tags_json, review_note
        FROM trade_journal
        ORDER BY ts_open_utc DESC
        LIMIT 100
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
    rows_culture = q(
        """
        SELECT ts_close_utc, symbol, outcome, pnl_pct
        FROM trade_journal
        WHERE status = 'CLOSED' AND ts_close_utc IS NOT NULL AND TRIM(ts_close_utc) <> ''
        ORDER BY ts_close_utc DESC
        LIMIT 220
        """
    )

    agent_stats: dict[str, dict[str, int]] = {}
    for r in rows_decisions_raw:
        for d in safe_json_objects(str(r[4] or "[]")):
            ak = str(d.get("agent") or "").strip().lower()
            if not ak:
                continue
            st = agent_stats.setdefault(ak, {"appeared": 0, "approved": 0, "rejected": 0, "other": 0})
            st["appeared"] += 1
            dec = str(d.get("decision") or "").strip().upper()
            if dec == "APPROVED":
                st["approved"] += 1
            elif dec == "REJECTED":
                st["rejected"] += 1
            else:
                st["other"] += 1

    agent_kpi = sorted(
        (
            {
                "agent": k,
                "appeared": v["appeared"],
                "approved": v["approved"],
                "rejected": v["rejected"],
                "other": v["other"],
            }
            for k, v in agent_stats.items()
        ),
        key=lambda x: (-x["appeared"], x["agent"]),
    )

    rows_decisions: list[tuple] = []
    for r in rows_decisions_raw:
        sym = str(r[2] or "").upper()
        act = str(r[3] or "").upper()
        if sym_f and sym_f not in sym:
            continue
        if act_f and act_f not in act:
            continue
        if ag_f:
            agents_in = [str(x.get("agent") or "").lower() for x in safe_json_objects(str(r[4] or "[]"))]
            if not any(ag_f in a for a in agents_in if a):
                continue
        rows_decisions.append(r)

    rows_journal: list[tuple] = []
    for r in rows_journal_raw:
        if sym_f and sym_f not in str(r[3] or "").upper():
            continue
        rows_journal.append(r)

    wins = 0
    losses = 0
    be = 0
    pnl_sum = 0.0
    r_vals: list[float] = []
    mistakes: dict[str, int] = {}
    for r in rows_journal:
        outcome = str(r[6] or "").upper()
        if outcome == "WIN":
            wins += 1
        elif outcome == "LOSS":
            losses += 1
        elif outcome == "BE":
            be += 1
        try:
            pnl_sum += float(r[7] or 0.0)
        except Exception:
            pass
        try:
            if r[8] is not None:
                r_vals.append(float(r[8]))
        except Exception:
            pass
        for t in safe_json_list(str(r[9] or "[]")):
            k = t.strip().lower()
            if k:
                mistakes[k] = mistakes.get(k, 0) + 1

    total = wins + losses + be
    wr = (wins / (wins + losses) * 100.0) if (wins + losses) > 0 else 0.0
    avg_r = (sum(r_vals) / len(r_vals)) if r_vals else 0.0

    now = datetime.now(timezone.utc)
    d7 = now - timedelta(days=7)
    d14 = now - timedelta(days=14)
    best_trade: dict | None = None
    sym_wins: dict[str, int] = {}
    for ts_c, sym, out, pnl in rows_culture:
        dt = _parse_ts_close(ts_c)
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        try:
            p = float(pnl or 0.0)
        except Exception:
            p = 0.0
        if dt >= d7:
            if best_trade is None or p > float(best_trade.get("pnl_pct") or 0.0):
                best_trade = {"symbol": str(sym or ""), "pnl_pct": round(p, 4), "ts_close_utc": str(ts_c or "")}
        if dt >= d14 and str(out or "").upper() == "WIN":
            su = str(sym or "").upper().strip()
            if su:
                sym_wins[su] = sym_wins.get(su, 0) + 1

    leaderboard = [
        {"symbol": k, "wins_14d": v} for k, v in sorted(sym_wins.items(), key=lambda x: (-x[1], x[0]))[:10]
    ]

    overlays = build_live_overlays(chart_symbol)
    risk_heatmap = build_risk_heatmap()

    return {
        "now_utc": datetime.now(timezone.utc).isoformat(),
        "filters": {"symbol": sym_f, "action": act_f, "agent": ag_f, "chart": chart_symbol.strip().upper()},
        "db_identity": office_db_identity(_db_target_for_identity()),
        "kpi": {
            "total": total,
            "wins": wins,
            "losses": losses,
            "be": be,
            "wr_pct": round(wr, 2),
            "pnl_sum_pct": round(pnl_sum, 2),
            "avg_r": round(avg_r, 2),
        },
        "agent_kpi": agent_kpi,
        "culture": {
            "trade_of_week": best_trade,
            "leaderboard_wins_14d": leaderboard,
        },
        "overlays": overlays,
        "risk_heatmap": risk_heatmap,
        "decisions": [
            {"ts_utc": r[0], "signal_id": r[1], "symbol": r[2], "action": r[3]}
            for r in rows_decisions
        ],
        "journal": [
            {
                "trade_id": str(r[0] or ""),
                "ts_open_utc": r[1],
                "ts_close_utc": r[2],
                "symbol": r[3],
                "direction": r[4],
                "status": r[5],
                "outcome": r[6],
                "pnl_pct": r[7],
                "r_multiple": r[8],
                "mistakes": safe_json_list(str(r[9] or "[]")),
                "review_note": r[10] or "",
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
    .overlay-band { font-size:11px; margin-bottom:8px; line-height:1.35; }
    .overlay-ruler-wrap { position:relative; height:14px; background:#1e293b; border-radius:6px; border:1px solid #334155; margin-top:6px; }
    .overlay-mark { position:absolute; top:0; width:3px; height:100%; border-radius:1px; transform:translateX(-50%); }
    .om-sl { background:#ef4444; }
    .om-entry { background:#eab308; }
    .om-tp { background:#22c55e; }
    .om-mark { background:#f8fafc; box-shadow:0 0 0 1px #334155; z-index:2; }
    .overlay-legend { display:flex; flex-wrap:wrap; gap:8px; margin-top:4px; font-size:10px; color:#94a3b8; }
    .ocr-btn { cursor:pointer; font-size:13px; padding:2px 8px; border-radius:6px; background:#334155; border:1px solid #475569; color:#e2e8f0; }
    .ocr-btn:hover { background:#475569; }
    #reviewToast { margin-top:8px; min-height:18px; }
    td.heat-cell { text-align:center; font-weight:600; }
  </style>
</head>
<body>
<div class="wrap">
  <h1>AI Trading Desk · Mini App Live</h1>
  <div class="muted">Живий графік + журнал + помилки (простий режим)</div>
  <div id="dbfinger" class="muted" style="margin-top:6px;">DB …</div>

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

  <div class="row">
    <div class="card">Фільтр символ<br><input id="filterSymbol" placeholder="BTCUSDT" style="width:110px;" /></div>
    <div class="card">Дія<br><input id="filterAction" placeholder="SKIP" style="width:90px;" /></div>
    <div class="card">Агент<br><input id="filterAgent" placeholder="lev" style="width:90px;" /></div>
    <div class="card">Застосувати<br><button onclick="reloadAll()">OK</button></div>
  </div>

  <div class="grid">
    <div class="panel">
      <div><b>Live overlay</b> <span class="muted">(рівні з журналу + mark з Binance)</span></div>
      <div id="overlayBar" class="overlay-band muted">…</div>
      <div id="tv"></div>
    </div>
    <div class="panel">
      <div><b>Desk KPI</b></div>
      <div id="kpi" class="muted">loading...</div>
      <hr />
      <div><b>Top mistakes</b></div>
      <table id="mistakes"></table>
      <hr />
      <div><b>KPI по ролях</b></div>
      <table id="agentkpi"></table>
      <hr />
      <div><b>Культура (7д / 14д)</b></div>
      <div id="culture" class="muted">…</div>
    </div>
  </div>

  <div class="panel" style="margin-top:12px;">
    <b>Risk heatmap</b> <span class="muted" id="heatmapHint">з журналу (останні закриті)</span>
    <table id="heatmap"></table>
  </div>

  <div class="panel" style="margin-top:12px;">
    <b>Останні рішення</b>
    <table id="decisions"></table>
  </div>

  <div class="panel" style="margin-top:12px;">
    <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
      <b>Журнал угод</b>
      <button type="button" class="ocr-btn" onclick="copyReviewDraft('')" title="Чернета для останнього LOSS (або останньої закритої)">One-click review · останній LOSS</button>
      <span id="reviewToast" class="muted"></span>
    </div>
    <table id="journal"></table>
  </div>
</div>

<script src="https://s3.tradingview.com/tv.js"></script>
<script>
let widget = null;
window._deskOverlays = null;
window._lastMark = null;

function renderOverlayBar() {
  const el = document.getElementById('overlayBar');
  const ov = window._deskOverlays;
  const mark = window._lastMark;
  if (!el) return;
  if (!ov) {
    el.textContent = 'Завантаження overlay…';
    return;
  }
  const ot = ov.open_trade;
  const sym = (document.getElementById('symbol').value || 'BTCUSDT').toUpperCase();
  if (!ot || !ot.entry_price) {
    el.innerHTML =
      '<span class="muted">Немає OPEN угоди з цінами в журналі для <b>' + sym + '</b>. ' +
      'Остання закрита (підказка): ' + formatClosedHint(ov.last_closed_hint) + '</span>';
    return;
  }
  const e = Number(ot.entry_price);
  const sl = ot.stop_loss != null ? Number(ot.stop_loss) : null;
  const tp = ot.take_profit != null ? Number(ot.take_profit) : null;
  const prices = [e];
  if (sl != null && sl > 0) prices.push(sl);
  if (tp != null && tp > 0) prices.push(tp);
  if (mark != null && mark > 0) prices.push(mark);
  let lo = Math.min.apply(null, prices);
  let hi = Math.max.apply(null, prices);
  if (hi <= lo) { hi = lo * 1.001; lo = lo * 0.999; }
  function pct(p) { return ((p - lo) / (hi - lo)) * 100; }
  let ruler =
    '<div class="overlay-ruler-wrap">' +
    (sl != null && sl > 0 ? '<div class="overlay-mark om-sl" style="left:' + pct(sl).toFixed(2) + '%" title="SL"></div>' : '') +
    '<div class="overlay-mark om-entry" style="left:' + pct(e).toFixed(2) + '%" title="Entry"></div>' +
    (tp != null && tp > 0 ? '<div class="overlay-mark om-tp" style="left:' + pct(tp).toFixed(2) + '%" title="TP"></div>' : '') +
    (mark != null && mark > 0 ? '<div class="overlay-mark om-mark" style="left:' + pct(mark).toFixed(2) + '%" title="Mark"></div>' : '') +
    '</div>';
  let leg =
    '<div class="overlay-legend">' +
    '<span>side <b>' + (ot.direction || '') + '</b></span>' +
    '<span>entry <b>' + e.toFixed(4) + '</b></span>' +
    (sl != null ? '<span class="bad">SL ' + sl.toFixed(4) + '</span>' : '') +
    (tp != null ? '<span class="ok">TP ' + tp.toFixed(4) + '</span>' : '') +
    (mark != null && mark > 0 ? '<span>mark <b>' + mark.toFixed(4) + '</b></span>' : '') +
    '</div>';
  el.innerHTML =
    '<div><b>' + (ot.symbol || sym) + '</b> · OPEN <span class="muted">' + (ot.trade_id || '') + '</span></div>' +
    ruler + leg;
}

function formatClosedHint(h) {
  if (!h || !h.ts_close_utc) return '—';
  return (h.outcome || '') + ' @ ' + (h.exit_price != null ? Number(h.exit_price).toFixed(4) : '?');
}

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
    window._lastMark = alt.lastPrice != null ? Number(alt.lastPrice) : null;
    renderOverlayBar();
  } catch (e) {
    document.getElementById('btc24').textContent = 'err';
    document.getElementById('sym24').textContent = 'err';
    window._lastMark = null;
  }
}

function t(id, html) { document.getElementById(id).innerHTML = html; }

function officeApiQuery() {
  const p = new URLSearchParams();
  const fs = (document.getElementById('filterSymbol').value || '').trim();
  const fa = (document.getElementById('filterAction').value || '').trim();
  const fag = (document.getElementById('filterAgent').value || '').trim();
  const chart = (document.getElementById('symbol').value || '').trim();
  if (fs) p.set('symbol', fs);
  if (fa) p.set('action', fa);
  if (fag) p.set('agent', fag);
  if (chart) p.set('chart', chart);
  const s = p.toString();
  return s ? ('?' + s) : '';
}

async function loadOffice() {
  const r = await fetch('/api/summary' + officeApiQuery());
  const d = await r.json();
  window._deskOverlays = d.overlays || null;
  renderOverlayBar();
  const di = d.db_identity || {};
  const fp = di.fingerprint || '?';
  const back = di.backend || '?';
  document.getElementById('dbfinger').textContent =
    'БД: ' + back + ' · fingerprint ' + fp + ' (має збігатися з логом relay [relay] DB identity)';
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

  t('agentkpi',
    '<tr><th>Агент</th><th>Реплік</th><th>OK</th><th>Reject</th><th>Інш</th></tr>' +
    (d.agent_kpi || []).map(x =>
      '<tr><td>' + x.agent + '</td><td>' + x.appeared + '</td><td>' + x.approved + '</td><td>' + x.rejected + '</td><td>' + x.other + '</td></tr>'
    ).join('')
  );

  const tw = (d.culture && d.culture.trade_of_week) || null;
  const lb = (d.culture && d.culture.leaderboard_wins_14d) || [];
  const twTxt = tw
    ? ('Trade 7д: ' + tw.symbol + ' · PnL ' + (tw.pnl_pct >= 0 ? '+' : '') + Number(tw.pnl_pct).toFixed(2) + '% · ' + tw.ts_close_utc)
    : 'Trade 7д: немає даних';
  const lbTxt = lb.length
    ? ('Топ WIN 14д: ' + lb.map(x => x.symbol + '×' + x.wins_14d).join(', '))
    : 'Топ WIN 14д: немає';
  t('culture', twTxt + '<br/>' + lbTxt);

  const hm = d.risk_heatmap || {};
  const hmRows = hm.rows || [];
  const hmHint = document.getElementById('heatmapHint');
  if (hmHint && hm.hint_ua) hmHint.textContent = hm.hint_ua;
  function heatStyle(ls) {
    const x = Math.max(0, Math.min(1, Number(ls) || 0));
    const hue = 120 * (1 - x);
    return 'background:hsla(' + hue + ',62%,22%,0.92);color:#f8fafc;';
  }
  t('heatmap',
    '<tr><th>Символ</th><th>Всього</th><th>W</th><th>L</th><th>BE</th><th>WR%</th><th>L/(W+L)</th><th>Avg PnL%</th><th>Ризик</th></tr>' +
    (hmRows.length ? hmRows.map(function(r) {
      const ls = r.loss_share;
      return '<tr><td><b>' + r.symbol + '</b></td><td>' + r.total + '</td><td class="ok">' + r.wins + '</td><td class="bad">' + r.losses + '</td><td>' + r.be + '</td><td>' + r.wr_pct + '</td><td>' + ls + '</td><td>' + r.avg_pnl_pct + '</td>' +
        '<td class="heat-cell" style="' + heatStyle(ls) + '">' + Math.round(100 * ls) + '%</td></tr>';
    }).join('') : '<tr><td colspan="9" class="muted">Недостатньо закритих угод для heatmap (мінімум ' + (hm.min_decided || 2) + ' вирішених WIN/LOSS по символу).</td></tr>')
  );

  t('decisions',
    '<tr><th>Час</th><th>Сигнал</th><th>Символ</th><th>Дія</th></tr>' +
    (d.decisions || []).slice(0, 12).map(x =>
      '<tr><td>' + x.ts_utc + '</td><td>' + x.signal_id + '</td><td>' + x.symbol + '</td><td><b>' + x.action + '</b></td></tr>'
    ).join('')
  );

  t('journal',
    '<tr><th>Review</th><th>Open</th><th>Symbol</th><th>Side</th><th>Outcome</th><th>PnL</th><th>R</th><th>Mistakes</th><th>Нотатка</th></tr>' +
    (d.journal || []).slice(0, 16).map(x =>
      '<tr><td><button type="button" class="ocr-btn" onclick="copyReviewDraft(' + JSON.stringify(x.trade_id || '') + ')">📋</button></td>' +
      '<td>' + (x.ts_open_utc || '') + '</td><td>' + x.symbol + '</td><td>' + x.direction + '</td><td>' + (x.outcome || '') + '</td>' +
      '<td>' + (x.pnl_pct == null ? '' : ((Number(x.pnl_pct)>=0?'+':'') + Number(x.pnl_pct).toFixed(2) + '%')) + '</td>' +
      '<td>' + (x.r_multiple == null ? '' : ((Number(x.r_multiple)>=0?'+':'') + Number(x.r_multiple).toFixed(2) + 'R')) + '</td>' +
      '<td>' + (x.mistakes || []).slice(0,3).join(', ') + '</td><td>' + (x.review_note || '') + '</td></tr>'
    ).join('')
  );
}

async function copyReviewDraft(tradeId) {
  const toast = document.getElementById('reviewToast');
  try {
    const q = tradeId ? ('?trade_id=' + encodeURIComponent(tradeId)) : '';
    const r = await fetch('/api/review_draft' + q);
    const d = await r.json();
    if (!d.ok) {
      if (toast) toast.textContent = 'Немає угоди в журналі для review.';
      return;
    }
    await navigator.clipboard.writeText(d.draft_ua);
    if (toast) toast.textContent = 'Скопійовано в буфер: ' + (d.trade_id || '') + ' (встав у Telegram / нотатки)';
  } catch (e) {
    if (toast) toast.textContent = 'Помилка clipboard або API: ' + e;
  }
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
    def do_HEAD(self) -> None:
        u = urlparse(self.path)
        if u.path in ("/", "/api/summary", "/api/review_draft"):
            self.send_response(200)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()

    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path == "/api/review_draft":
            qs = parse_qs(u.query)
            tid = (qs.get("trade_id") or [""])[0].strip()
            body = json.dumps(build_review_draft(tid or None), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/api/summary":
            qs = parse_qs(u.query)

            def _first(name: str) -> str:
                v = qs.get(name)
                return (v[0] if v else "").strip()

            body = json.dumps(
                get_data(
                    symbol_filter=_first("symbol"),
                    action_filter=_first("action"),
                    agent_filter=_first("agent"),
                    chart_symbol=_first("chart"),
                ),
                ensure_ascii=False,
            ).encode("utf-8")
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
    if (not _is_pg()) and (not os.path.exists(DB_PATH)):
        print(f"[warn] DB file not found yet: {DB_PATH}")
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"mini-app: http://{HOST}:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()

