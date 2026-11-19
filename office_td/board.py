"""Щоденне «Табло» відкритих угод ІНТРАДЕЙ і СВІНГ (картинка в Telegram о 09:00 за Києвом, лише інформація).
Рядок на кожну ВІДКРИТУ угоду: монета і напрям, смужка часу (СВІНГ 10 діб, ІНТРАДЕЙ 48 год), зараз R/$ за останнім закриттям M1, підказка (СВІНГ ≥+2R: беззбиток з ціною; закриття за часом завтра).
Угорі секції: відкрито, зараз $, стопів поспіль, результат за 7 діб ($10/R; стоп = −1R, ціль/час — за ціною події, комісії не враховано).
Вимкнути: BOARD=0; година: BOARD_HOUR (Київ, за замовчуванням 9). Ордерів немає."""
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

DDL = "CREATE TABLE IF NOT EXISTS br_board_log (day TEXT PRIMARY KEY, sent_ts DOUBLE PRECISION NOT NULL, n_open INTEGER)"
TERMINAL = {"SL", "TP1", "TP2", "TP3", "AMBIGUOUS", "CANCEL"}
CLOSED = ("SL", "TP1", "TP2", "TP3", "TIMEOUT")
ROWS_PER_IMAGE = 22


def enabled() -> bool:
    return os.getenv("BOARD", "1").strip().lower() in ("1", "true", "yes", "on")


def _kyiv(now: float):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(now, ZoneInfo("Europe/Kyiv"))


def _r(row: Dict[str, Any], price: float) -> float:
    side = 1 if row["direction"] == "LONG" else -1; risk = abs(float(row["entry"]) - float(row["sl"]))
    return side * (price - float(row["entry"])) / risk if risk > 0 else 0.0


async def compute(db: str, fetch: Callable, now: Optional[float] = None) -> Dict[str, Any]:
    from office_br import card, store
    now = time.time() if now is None else now
    out: Dict[str, Any] = {"SW": {"open": [], "week": 0.0, "streak": 0, "closed7": 0}, "TD": {"open": [], "week": 0.0, "streak": 0, "closed7": 0}}
    prices: Dict[str, Optional[float]] = {}
    closed: Dict[str, List[tuple]] = {"SW": [], "TD": []}
    for row in store.rows(db, "WHERE status IN ('SENT', 'SL', 'TP1', 'TP2', 'TP3', 'TIMEOUT')"):
        if not card.is_td(row):
            continue
        k = "SW" if card.is_swing(row) else "TD"; evs = store.events(db, row["sig_id"]); lv = {e["level"]: e for e in evs}
        if "ENTRY" not in lv:
            continue
        if row["status"] == "SENT" and not (set(lv) & TERMINAL):
            out[k]["open"].append((row, float(lv["ENTRY"]["touched_ts"])))
        elif row["status"] in CLOSED:
            term = next((e for e in sorted(evs, key=lambda e: e["touched_ts"], reverse=True) if e["level"] in TERMINAL | {"TIMEOUT"}), None)
            if term is None:
                continue
            px = term.get("price")
            if px is None:
                continue
            r = -1.0 if term["level"] == "SL" else _r(row, float(px))
            closed[k].append((float(term["touched_ts"]), r, term["level"]))
    for k in ("SW", "TD"):
        cl = sorted(closed[k], reverse=True)
        s = 0
        for _, _, lvl in cl:
            if lvl != "SL": break
            s += 1
        out[k]["streak"] = s
        wk = [r for ts, r, _ in cl if ts >= now - 7 * 86400]
        out[k]["week"] = 10 * sum(wk); out[k]["closed7"] = len(wk)
    for k in ("SW", "TD"):
        rows = []
        for row, ent_ts in out[k]["open"]:
            sym = row["symbol"]
            if sym not in prices:
                try:
                    cs = await asyncio.to_thread(fetch, sym, "1m", 5, closed_only=True)
                    prices[sym] = float(cs[-1]["close"]) if isinstance(cs, list) and cs else None
                except Exception:  # noqa: BLE001
                    prices[sym] = None
            px = prices[sym]; r_now = _r(row, px) if px is not None else None
            hold_h = card.hold_hours(row); age_h = max(0.0, (now - ent_ts) / 3600)
            rows.append({"sym": sym.replace("USDT", ""), "dir": row["direction"], "seq": int(row["seq"]), "r": r_now, "age_h": age_h, "hold_h": hold_h, "entry": float(row["entry"]),
                         "strategy": k, "note": _note(row, r_now, age_h, hold_h)})
        rows.sort(key=lambda x: -x["age_h"])
        out[k]["rows"] = rows
        out[k]["now_usd"] = 10 * sum(x["r"] for x in rows if x["r"] is not None)
    return out


def _note(row: Dict[str, Any], r_now: Optional[float], age_h: float, hold_h: int) -> str:
    from office_br import card
    if r_now is None:
        return "ціна недоступна"
    if card.is_swing(row) and r_now >= 2.0:
        return f"стоп → беззбиток {card._n(float(row['entry']), row['symbol'])}"
    if hold_h - age_h <= (24 if card.is_swing(row) else 6):
        return "скоро закриття за часом"
    return ""


def _usd(x: float) -> str:
    return ("+" if x >= 0 else "−") + f"${abs(x):,.0f}".replace(",", " ")


def _fmt_r(x: float) -> str:
    return f"{x:+.1f}".replace(".", ",").replace("-", "−")


def render(data: Dict[str, Any], out_dir: str, now: Optional[float] = None) -> List[str]:
    """Одна компактна картинка: вгорі підсумок і «що зробити сьогодні», далі плитки угод (4 в ряд, колір = плюс/мінус, найкращі першими). Без смужок і дрібного тексту."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle
    BG, CARD, TXT, MUT, YEL, BLU, GRN, RED = "#101418", "#1b222b", "#f2f4f7", "#9aa4b2", "#ffd500", "#0057b7", "#2ecc71", "#ff5a5f"
    now = time.time() if now is None else now; stamp = _kyiv(now).strftime("%d.%m %H:%M")
    COLS = 4; TW, TH, GAP = 22.4, 12.5, 1.2
    acts: List[str] = []
    for k in ("SW", "TD"):
        for r in data[k]["rows"]:
            if r["note"].startswith("стоп"): acts.append(f"{r['sym']} {'▲' if r['dir'] == 'LONG' else '▼'}  {r['note']}")
    for k in ("SW", "TD"):
        for r in data[k]["rows"]:
            if r["note"].startswith("скоро"): acts.append(f"{r['sym']} {'▲' if r['dir'] == 'LONG' else '▼'}  закрити за часом {'завтра' if k == 'SW' else 'скоро'}")
    acts = acts[:6]
    nrows = {k: (len(data[k]["rows"]) + COLS - 1) // COLS for k in ("SW", "TD")}
    height = 17 + 21 + (8 + 5.2 * max(1, len(acts)) + 3) + sum(7 + nrows[k] * (TH + GAP) + 4 for k in ("SW", "TD") if data[k]["rows"]) + 6
    fig = plt.figure(figsize=(7.2, height * 0.0725), dpi=150, facecolor=BG); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(height, 0); ax.axis("off")
    def t(x, y, s, size=12, c=TXT, w="normal", ha="left"): ax.text(x, y, s, color=c, fontsize=size, fontweight=w, ha=ha, va="center")
    ax.add_patch(Rectangle((0, 0), 100, 14, fc=BLU)); ax.add_patch(Rectangle((0, 0), 100, 7, fc=YEL))
    t(5, 3.5, "ТАБЛО УГОД", 19, "#2a2200", "bold"); t(95, 3.5, stamp, 12, "#2a2200", "bold", "right"); t(5, 10.5, "відкриті угоди · ціни за останньою хвилиною", 10.5, "#ffffff")
    y = 17
    for j, (k, nm, col) in enumerate((("SW", "СВІНГ", "#4d9bff"), ("TD", "ІНТРАДЕЙ", YEL))):
        d = data[k]; x = 4 + j * 47; ax.add_patch(FancyBboxPatch((x, y), 45, 18, boxstyle="round,pad=0,rounding_size=1.2", fc=CARD, ec="none")); ax.add_patch(Rectangle((x, y), 45, 0.8, fc=col, ec="none"))
        up = sum(1 for r in d["rows"] if r["r"] is not None and r["r"] > 0); dn = sum(1 for r in d["rows"] if r["r"] is not None and r["r"] < 0)
        t(x + 3, y + 4.5, nm, 12.5, col, "bold"); t(x + 42, y + 4.5, f"відкрито {len(d['rows'])}", 10.5, TXT, "bold", "right")
        nu = d["now_usd"]; t(x + 3, y + 11, _usd(nu), 17, GRN if nu >= 0 else RED, "bold"); t(x + 3, y + 15.2, f"зараз · ▲{up} ▼{dn}", 8, MUT)
        wk = d["week"]; t(x + 42, y + 11, _usd(wk), 12.5, GRN if wk >= 0 else RED, "bold", "right"); t(x + 42, y + 15.2, f"7 діб · стопів {d['streak']}", 8, MUT, ha="right")
    y += 21
    bh = 8 + 5.2 * max(1, len(acts)); ax.add_patch(FancyBboxPatch((4, y), 92, bh, boxstyle="round,pad=0,rounding_size=1.2", fc="#2a2200", ec=YEL, lw=1.2))
    t(7, y + 4, "ЩО ЗРОБИТИ СЬОГОДНІ", 11, YEL, "bold")
    if acts:
        for q, a in enumerate(acts): t(7, y + 9.5 + q * 5.2, "•  " + a, 10.3, TXT)
    else: t(7, y + 9.5, "нічого терміново", 10.3, MUT)
    y += bh + 3
    for k, nm, col in (("SW", "СВІНГ · кожна плитка = одна угода", "#4d9bff"), ("TD", "ІНТРАДЕЙ", YEL)):
        rows = sorted(data[k]["rows"], key=lambda r: -(r["r"] if r["r"] is not None else -99))
        if not rows: continue
        t(5, y + 3, nm, 11.5, col, "bold"); y += 7
        for q, r in enumerate(rows):
            cx = 4 + (q % COLS) * (TW + GAP); cy = y + (q // COLS) * (TH + GAP); rr = r["r"]
            bgc = "#183324" if (rr is not None and rr >= 0.3) else ("#3a1d22" if (rr is not None and rr <= -0.3) else CARD); tc = GRN if (rr is not None and rr >= 0.3) else (RED if (rr is not None and rr <= -0.3) else MUT)
            ax.add_patch(FancyBboxPatch((cx, cy), TW, TH, boxstyle="round,pad=0,rounding_size=1.2", fc=bgc, ec="none"))
            t(cx + 1.8, cy + 3.3, f"{r['sym']} {'▲' if r['dir'] == 'LONG' else '▼'}", 11.2, TXT, "bold")
            t(cx + 1.8, cy + 7.6, "—" if rr is None else _fmt_r(rr) + "R", 13, tc, "bold"); t(cx + TW - 1.5, cy + 7.6, "" if rr is None else _usd(10 * rr), 8.4, tc, ha="right")
            when = f"день {min(int(r['age_h'] // 24) + 1, 10)}" if k == "SW" else f"{int(r['age_h'])} год"
            t(cx + 1.8, cy + 10.7, when, 7.6, MUT)
        y += ((len(rows) + COLS - 1) // COLS) * (TH + GAP) + 4
    t(50, height - 3, "Спостереження, не гарантія прибутку · комісії не враховано", 8, MUT, ha="center")
    p = os.path.join(out_dir, f"board_{int(now)}_1.png"); fig.savefig(p, facecolor=BG); plt.close(fig)
    return [p]


async def daily(db: str, fetch: Callable, send_image: Callable, now: Optional[float] = None) -> int:
    """Один раз на добу після BOARD_HOUR за Києвом. Повертає кількість надісланих картинок. Ніколи не кидає."""
    if not enabled():
        return 0
    now = time.time() if now is None else now
    try:
        from office_bridge import _execute, _fetchone
        loc = _kyiv(now)
        if loc.hour < int(os.getenv("BOARD_HOUR", "9")):
            return 0
        day = loc.strftime("%Y-%m-%d"); _execute(db, DDL)
        if _fetchone(db, "SELECT 1 FROM br_board_log WHERE day = ?", (day,)):
            return 0
        data = await compute(db, fetch, now)
        if not data["SW"]["rows"] and not data["TD"]["rows"]:
            _execute(db, "INSERT INTO br_board_log(day, sent_ts, n_open) VALUES (?,?,?) ON CONFLICT DO NOTHING", (day, now, 0)); return 0
        import tempfile
        sent = 0
        with tempfile.TemporaryDirectory() as td:
            for p in await asyncio.to_thread(render, data, td, now):
                mid = await send_image(p, "Табло угод СВІНГ і ІНТРАДЕЙ", {"seq": 0, "symbol": "", "direction": "", "sig_id": "BOARD|" + day})
                if mid: sent += 1
        if sent:
            _execute(db, "INSERT INTO br_board_log(day, sent_ts, n_open) VALUES (?,?,?) ON CONFLICT DO NOTHING", (day, now, len(data["SW"]["rows"]) + len(data["TD"]["rows"])))
            print(f"[board] надіслано табло {day}: {sent} картинок", flush=True)
        return sent
    except Exception as exc:  # noqa: BLE001
        print(f"[board] {type(exc).__name__}: {exc}", flush=True)
        return 0
