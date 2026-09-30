"""Replay контрольних кейсів на реальних свічках (лише читання: нічого не пишеться в Telegram і не торгує).
Свічки — з архіву data.binance.vision (він НЕ рахується в ліміт API; IP спільний із живим Левом і ботами власниці). REST fapi — лише запасний шлях
при used_weight_1m < 600 і з паузою між запитами; інакше replay чесно пише «немає даних».

Ядро: крок 15 хв, `office_trade_manager.advise/reentry` бачать лише ЗАКРИТІ свічки до поточного кроку (без підглядання в майбутнє).
Вхід моделюється на першій свічці після `start`, що торкнулась ціни входу. Окремо для кожного кейсу перевіряється шлюз плану
(`office_lev_watch.check_plan`: геометрія, RR після комісій, мінімальна ціль) — так видно, чи новий формат пропустив би цей план.
Вердикт кейсу — лише те, що перевіряє код: replay виконався на реальних даних, у хронології немає слів про «закрито» без підтвердження
виконання, жодна порада не повторилась. Кейси — реальні входи з журналу (JOURNAL_OPEN) за 2026-09-29; BTC range — діапазон без угоди (див. docs)."""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

CASES: Dict[str, Dict[str, Any]] = {
    "AKE": {"symbol": "AKEUSDT", "side": "LONG", "entry": 0.030477832, "sl": 0.029552060, "tp1": 0.031866490, "tp2": None, "start": "2026-09-29T16:35:00Z",
            "note": "AKE: вхід власниці з журналу 16:35 UTC, пізніше ціна пішла вгору"},
    "LONGXIA": {"symbol": "龙虾USDT", "side": "LONG", "entry": 0.07990707, "sl": 0.07238825, "tp1": 0.0911853, "tp2": None, "start": "2026-09-29T12:06:00Z",
                "note": "LONGXIA (龙虾): великий рух; ведення до кінця руху"},
    "LSK": {"symbol": "LSKUSDT", "side": "LONG", "entry": 0.31337862, "sl": 0.303548935, "tp1": 0.3281231475, "tp2": None, "start": "2026-09-29T16:24:00Z",
            "note": "LSK: RR ≈1,40 після комісій — за новими правилами план має бути відхилений"},
    "ENA": {"symbol": "ENAUSDT", "side": "LONG", "entry": 0.25765633, "sl": 0.251630415, "tp1": 0.2666952025, "tp2": None, "start": "2026-09-29T17:08:00Z",
            "note": "ENA: серія скасувань/перезапусків плану — тут лише ведення угоди"},
}
TF_SEC = {"15m": 900, "1h": 3600, "4h": 14400}
FORBIDDEN = ("закрито", "закрита", "закрили", "угоду закрито")


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def _ts(r: Dict[str, Any]) -> float:
    return datetime.fromisoformat(str(r["ts"]).replace("Z", "+00:00")).timestamp()


VISION_URL = "https://data.binance.vision/data/futures/um/daily/klines/{sym}/15m/{sym}-15m-{day}.zip"
WEIGHT_LIMIT = 600          # REST-запасний шлях лише при used_weight_1m нижче цього (IP спільний із живим Левом і ботами власниці)
REST_GAP_SEC = 1.0          # і з розтягуванням запитів у часі


def _vision_zip(url: str) -> bytes:
    import urllib.request

    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "office-replay/1"}), timeout=60).read()


def from_vision(symbol: str, start: datetime, end: datetime, getter: Optional[Callable[[str], bytes]] = None) -> Dict[str, Any]:
    """15-хв свічки з архіву data.binance.vision (НЕ рахується в ліміт API). Є лише завершені доби; відсутні дні пропускаємо й повідомляємо."""
    import io
    import urllib.parse
    import zipfile
    from datetime import timedelta

    get = getter or _vision_zip
    rows: List[Dict[str, Any]] = []
    missing: List[str] = []
    d = start.date()
    while d <= end.date():
        url = VISION_URL.format(sym=urllib.parse.quote(symbol), day=d.isoformat())
        try:
            z = zipfile.ZipFile(io.BytesIO(get(url)))
            for line in z.read(z.namelist()[0]).decode().splitlines():
                p = line.split(",")
                if p and p[0].isdigit():
                    rows.append({"ts": _iso(int(p[0]) / 1000), "open": float(p[1]), "high": float(p[2]), "low": float(p[3]), "close": float(p[4]), "volume": float(p[5])})
        except Exception:  # noqa: BLE001
            missing.append(d.isoformat())
        d += timedelta(days=1)
    rows.sort(key=lambda r: r["ts"])
    return {"15m": rows, "missing_days": missing}


def resample(m15: List[Dict[str, Any]], sec: int) -> List[Dict[str, Any]]:
    buckets: Dict[int, Dict[str, Any]] = {}
    for r in m15:
        b = int(_ts(r) // sec * sec)
        x = buckets.setdefault(b, {"ts": _iso(b), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": 0.0})
        x["high"] = max(x["high"], r["high"])
        x["low"] = min(x["low"], r["low"])
        x["close"] = r["close"]
        x["volume"] += r.get("volume") or 0.0
    return [buckets[k] for k in sorted(buckets)]


def _rest_allowed() -> bool:
    """Запасний REST лише коли вага IP вільна: used_weight_1m відомий і нижче WEIGHT_LIMIT (невідомо = не ризикуємо)."""
    try:
        from office_market_data import source_health

        used = source_health().get("used_weight_1m")
        return used is not None and int(used) < WEIGHT_LIMIT
    except Exception:  # noqa: BLE001
        return False


def load_data(symbol: str, fetch: Optional[Callable[..., Any]] = None, start: Optional[datetime] = None, end: Optional[datetime] = None,
              getter: Optional[Callable[[str], bytes]] = None) -> Dict[str, Any]:
    """Свічки для replay. Порядок: (1) `fetch` — лише для тестів; (2) архів data.binance.vision (не їсть ліміт API; 1г і 4г збираємо з 15м);
    (3) якщо архіву за потрібні дні нема — REST fapi, але тільки при used_weight_1m < 600 і з паузою між запитами, інакше чесно без даних."""
    import time as _time
    from datetime import timedelta

    if fetch is not None:
        out: Dict[str, Any] = {}
        for tf, n in (("15m", 500), ("1h", 500), ("4h", 300)):
            rows = fetch(symbol, tf, n)
            out[tf] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        out["source"] = "fetch"
        return out
    end = end or datetime.now(timezone.utc)
    start = (start or end) - timedelta(days=3)       # контекст для H1/H4 до входу
    v = from_vision(symbol, start, end, getter)
    m15 = v["15m"]
    if m15:
        return {"15m": m15, "1h": resample(m15, 3600), "4h": resample(m15, 14400), "source": "vision", "missing_days": v["missing_days"]}
    if not _rest_allowed():
        return {"15m": [], "1h": [], "4h": [], "source": "none", "missing_days": v["missing_days"],
                "note": "архів data.binance.vision недоступний, а used_weight_1m невідомий або ≥ 600 — REST не чіпаємо, щоб не вибити ліміт IP"}
    from office_market_data import fetch_candles

    out = {"source": "rest", "missing_days": v["missing_days"]}
    for tf, n in (("15m", 500), ("1h", 500), ("4h", 300)):
        rows = fetch_candles(symbol, tf, n)
        out[tf] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        _time.sleep(REST_GAP_SEC)
    return out


def plan_gate(case: Dict[str, Any]) -> Optional[str]:
    """Чи пропустив би новий формат цей план (None — пропустив; інакше причина відхилення)."""
    from office_lev_watch import check_plan

    return check_plan(case["symbol"], case["side"], {"entry": case["entry"], "sl": case["sl"], "tp1": case["tp1"]},
                      case["entry"] * 0.999, case["entry"] * 1.001)


def replay(case: Dict[str, Any], data: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    import office_trade_manager as TM

    m15 = data.get("15m") or []
    if not m15:
        return {"ok": False, "status": "NO_DATA", "note": "немає свічок — replay не виконано (нічого не вигадуємо)"}
    long_ = str(case["side"]).upper() != "SHORT"
    entry, start = float(case["entry"]), datetime.fromisoformat(case["start"].replace("Z", "+00:00")).timestamp()
    fill_t = None
    for r in m15:
        t = _ts(r)
        if t + 900 > start and float(r["low"]) <= entry <= float(r["high"]):   # включно зі свічкою, у якій угоду відкрито (вона могла початись раніше за start)
            fill_t = t + 900
            break
    if fill_t is None:
        return {"ok": True, "status": "NOT_FILLED", "note": f"ціна не торкнулась входу {entry} після {case['start']} (дані до {m15[-1]['ts']})", "timeline": []}
    pos = {"symbol": case["symbol"], "direction": str(case["side"]).upper(), "entry": entry, "sl": case["sl"], "tp1": case["tp1"], "tp2": case.get("tp2"),
           "opened_at": _iso(fill_t)}
    sent: Dict[str, float] = {}
    stop_ts = None
    timeline: List[Dict[str, str]] = []
    mfe = mae = 0.0
    t = fill_t
    last_t = _ts(m15[-1]) + 900
    while t <= last_t:
        def cut(rows: List[Dict[str, Any]], sec: int, _t: float = t) -> List[Dict[str, Any]]:
            return [r for r in rows if _ts(r) + sec <= _t]

        m, h1, h4 = cut(m15, 900), cut(data.get("1h") or [], 3600), cut(data.get("4h") or [], 14400)
        if not m:
            t += 900
            continue
        px = float(m[-1]["close"])
        r0 = m[-1]
        mfe = max(mfe, ((float(r0["high"]) - entry) if long_ else (entry - float(r0["low"]))) / entry * 100)
        mae = max(mae, ((entry - float(r0["low"])) if long_ else (float(r0["high"]) - entry)) / entry * 100)
        evs = TM.advise(pos, h1=h1, m15=m, h4=h4, sent=set(sent), now_ts=t, price=px)
        if "STOP_PRICE" in sent and not evs:
            re_ = TM.reentry(pos, m15=m, h4=h4, sent=set(sent), now_ts=t, stop_alert_ts=stop_ts)
            evs = [re_] if re_ else []
        order = {"STOP_PRICE": 0, "END_STRUCTURE_H4": 1, "END_STRUCTURE": 1, "BREAKEVEN": 2, "TP1": 3, "TP2": 4}
        for ev in sorted(evs, key=lambda e: order.get(e["code"].split(":")[0], 9))[:1]:
            sent[ev["code"]] = t
            if ev["code"] == "STOP_PRICE":
                stop_ts = t
            timeline.append({"ts": _iso(t), "code": ev["code"], "text": ev["text"]})
        if "STOP_PRICE" in sent and "REENTRY" not in sent and t - sent["STOP_PRICE"] > 8 * 3600:
            break
        if "END_STRUCTURE" in sent or "END_STRUCTURE_H4" in sent:
            break
        t += 900
    return {"ok": True, "status": "FILLED", "filled_at": _iso(fill_t), "timeline": timeline, "mfe_pct": round(mfe, 2), "mae_pct": round(mae, 2),
            "last_price": m15[-1]["close"], "data_until": m15[-1]["ts"]}


def verdict(case_key: str, res: Dict[str, Any], gate: Optional[str]) -> Dict[str, Any]:
    """Що саме перевірено кодом і чи пройдено. Кейс ведення без заповненого входу НЕ пройдено (нічого не перевірено); кейс LSK — лише за шлюзом плану."""
    checks: List[Dict[str, Any]] = []
    checks.append({"name": "replay виконано на реальних свічках", "ok": bool(res.get("ok")) and res.get("status") not in ("NO_DATA", "ERROR")})
    tl = res.get("timeline") or []
    codes = [x["code"] for x in tl]
    if case_key != "LSK":
        checks.append({"name": "вхід заповнено — ведення було що перевіряти", "ok": res.get("status") == "FILLED"})
        case = CASES.get(case_key) or {}
        if res.get("status") == "FILLED" and case.get("entry"):
            need = abs(float(case["tp1"]) - float(case["entry"])) / float(case["entry"]) * 100.0
            if float(res.get("mfe_pct") or 0) >= need:   # ціна дійшла до цілі 1 → порада «ціль 1» мусить бути
                checks.append({"name": "ціль 1 досягнута → є порада по цілі 1", "ok": any(c.startswith("TP1") for c in codes)})
    checks.append({"name": "жодна порада не повторилась", "ok": len(codes) == len(set(codes))})
    checks.append({"name": "немає «закрито» без підтвердження виконання", "ok": not any(w in x["text"].lower() for x in tl for w in FORBIDDEN)})
    if case_key == "LSK":
        checks.append({"name": "план LSK (RR≈1,40) відхилено шлюзом нового формату", "ok": bool(gate)})
    return {"passed": all(c["ok"] for c in checks), "checks": checks}


def run_case(key: str, fetch: Optional[Callable[..., Any]] = None, getter: Optional[Callable[[str], bytes]] = None) -> Dict[str, Any]:
    case = CASES[key]
    try:
        gate = plan_gate(case)
    except Exception as exc:  # noqa: BLE001
        gate = f"шлюз не відпрацював: {type(exc).__name__}"
    try:
        st = datetime.fromisoformat(case["start"].replace("Z", "+00:00"))
        data = load_data(case["symbol"], fetch, start=st, end=st + timedelta(days=2), getter=getter)
        res = replay(case, data)
        res["source"] = data.get("source")
        if data.get("missing_days"):
            res["missing_days"] = data["missing_days"]
        if data.get("note"):
            res["note"] = data["note"]
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "status": "ERROR", "note": f"{type(exc).__name__}: {exc}"}
    return {"case": key, "symbol": case["symbol"], "note": case["note"], "gate": gate or "план пройшов би шлюз (геометрія, RR після комісій, мінімальна ціль)",
            "gate_rejected": bool(gate), "result": res, "verdict": verdict(key, res, gate)}


def format_report(r: Dict[str, Any]) -> List[str]:
    res = r["result"]
    lines = [f"[replay] == {r['case']} {r['symbol']} · {r['note']}", f"[replay] шлюз плану: {r['gate']}",
             f"[replay] стан: {res.get('status')} {res.get('filled_at') or res.get('note') or ''} · джерело свічок: {res.get('source')}"
             + (f" · днів без архіву: {', '.join(res['missing_days'])}" if res.get('missing_days') else "")]
    for x in res.get("timeline") or []:
        lines.append(f"[replay] {x['ts']}  {x['text']}")
    if res.get("status") == "FILLED":
        lines.append(f"[replay] MFE {res['mfe_pct']}% · MAE {res['mae_pct']}% · подій {len(res['timeline'])} · остання ціна {res['last_price']} · дані до {res['data_until']}")
    v = r["verdict"]
    lines.append(f"[replay] вердикт {r['case']}: {'ПРОЙДЕНО' if v['passed'] else 'НЕ ПРОЙДЕНО'} — " + "; ".join(f"{'✓' if c['ok'] else '✗'} {c['name']}" for c in v["checks"]))
    return lines


def run_all(keys: Optional[List[str]] = None, fetch: Optional[Callable[..., Any]] = None, printer: Callable[[str], None] = print,
            getter: Optional[Callable[[str], bytes]] = None) -> List[Dict[str, Any]]:
    out = []
    for k in keys or list(CASES):
        r = run_case(k, fetch, getter)
        for ln in format_report(r):
            printer(ln)
        out.append(r)
        time.sleep(0.2)
    return out
