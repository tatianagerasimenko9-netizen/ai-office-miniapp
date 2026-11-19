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


def render(data: Dict[str, Any], out_dir: str, now: Optional[float] = None) -> List[str]:
    """Малює табло: одна або кілька PNG (ROWS_PER_IMAGE рядків на картинку)."""
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Rectangle
    BG, CARD, TXT, MUT, YEL, BLU, GRN, RED = "#101418", "#1b222b", "#f2f4f7", "#9aa4b2", "#ffd500", "#0057b7", "#2ecc71", "#ff5a5f"
    now = time.time() if now is None else now; stamp = _kyiv(now).strftime("%d.%m.%Y %H:%M")
    items: List[tuple] = []
    for k, nm, col in (("SW", "СВІНГ", "#4d9bff"), ("TD", "ІНТРАДЕЙ", YEL)):
        d = data[k]; items.append(("head", k, nm, col, d))
        if not d["rows"]: items.append(("empty", k))
        for r in d["rows"]: items.append(("row", k, r))
    pages: List[List[tuple]] = [[]]; n = 0
    for it in items:
        if it[0] == "row":
            if n >= ROWS_PER_IMAGE: pages.append([]); n = 0
            n += 1
        pages[-1].append(it)
    paths = []
    for pi, page in enumerate(pages):
        height = 22 + sum(26 if it[0] == "head" else (9 if it[0] == "empty" else 10.2) for it in page) + 8
        fig = plt.figure(figsize=(7.2, height * 0.0725), dpi=150, facecolor=BG); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(height, 0); ax.axis("off")
        def t(x, y, s, size=12, c=TXT, w="normal", ha="left"): ax.text(x, y, s, color=c, fontsize=size, fontweight=w, ha=ha, va="center")
        ax.add_patch(Rectangle((0, 0), 100, 14, fc=BLU)); ax.add_patch(Rectangle((0, 0), 100, 7, fc=YEL))
        t(5, 3.5, "ТАБЛО УГОД" + (f" · {pi + 1}/{len(pages)}" if len(pages) > 1 else ""), 18, "#2a2200", "bold"); t(5, 10.5, f"{stamp} за Києвом · відкриті угоди СВІНГ і ІНТРАДЕЙ", 10.5, "#ffffff")
        y = 18
        for it in page:
            if it[0] == "head":
                _, k, nm, col, d = it
                ax.add_patch(Rectangle((4, y), 92, 0.7, fc=col, ec="none")); t(5, y + 4.5, nm, 14, col, "bold")
                t(95, y + 4.5, f"відкрито {len(d['rows'])}", 11, TXT, "bold", "right")
                nu = d["now_usd"]; st = d["streak"]; wk = d["week"]
                for j, (lab, val, c) in enumerate([("зараз", _usd(nu), GRN if nu >= 0 else RED), ("стопів поспіль", str(st), RED if st >= 3 else TXT), (f"за 7 діб ({d['closed7']} закр.)", _usd(wk), GRN if wk >= 0 else RED)]):
                    x = 5 + j * 30.5; t(x, y + 11.5, lab, 8.6, MUT); t(x, y + 16.5, val, 13, c, "bold")
                y += 26
            elif it[0] == "empty":
                t(8, y + 3, "відкритих угод немає", 10.5, MUT); y += 9
            else:
                _, k, r = it; rr = r["r"]
                col = MUT if rr is None else (GRN if rr >= 0.3 else (RED if rr <= -0.3 else MUT))
                ax.add_patch(FancyBboxPatch((4, y), 92, 9.2, boxstyle="round,pad=0,rounding_size=1.0", fc=CARD, ec="none")); ax.add_patch(Rectangle((4, y), 1.4, 9.2, fc=col, ec="none"))
                t(8, y + 3.3, f"{r['sym']} {'▲' if r['dir'] == 'LONG' else '▼'}", 11.5, TXT, "bold"); t(8, y + 7.0, r["note"] or f"№{r['seq']}", 8.2, "#ffb703" if r["note"] else MUT)
                if k == "SW":
                    day = int(r["age_h"] // 24) + 1; total = 10; lab = f"день {min(day, total)} із {total}"; on = min(day, total)
                else:
                    total = 8; on = min(total, int(r["age_h"] // 6) + 1); lab = f"{int(r['age_h'])} год із 48"
                t(52, y + 3.2, lab, 9, TXT, ha="center")
                w = 28 / total
                for q in range(total): ax.add_patch(Rectangle((38 + q * w, y + 5.2), w * 0.82, 1.5, fc=(YEL if q < on else "#33404d"), ec="none"))
                if rr is None: t(94, y + 4.6, "—", 11, MUT, ha="right")
                else: t(94, y + 3.2, f"{rr:+.1f}R".replace("+-", "−"), 11.5, col, "bold", "right"); t(94, y + 7.0, _usd(10 * rr), 8.6, col, ha="right")
                y += 10.2
        t(50, height - 3, "Спостереження, не гарантія прибутку · R за останнім закриттям M1", 8.2, MUT, ha="center")
        p = os.path.join(out_dir, f"board_{int(now)}_{pi + 1}.png"); fig.savefig(p, facecolor=BG); plt.close(fig); paths.append(p)
    return paths


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
