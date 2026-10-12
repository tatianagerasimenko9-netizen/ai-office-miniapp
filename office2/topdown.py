"""AI Office · top-down аналіз сценарію: D1 → H4 → H1 → M15 → M5 → M1 (лише ЗАКРИТІ свічки ≤ now).

Три речі, які Brain раніше мав лише частково:
  1. ТИП сценарію — продовження / розворот / діапазон — і оцінка суперечностей між ТФ ВІДПОВІДНО ДО ТИПУ (універсального правила «молодший ТФ = старший» немає).
     Суперечності ніколи не ховаються: кожна має серйозність (info/warn), чи вона очікувана для цього типу, і чому Brain усе-таки допустив сценарій.
  2. M5 і M1 як частина пошуку ВХОДУ (а не лише супровід): M5 підтверджує реакцію ціни в зоні, M1 уточнює точку входу (ретест зламаного рівня).
  3. Кожен ТФ має факти з часом закриття останньої свічки та рівнями.

ДЖЕРЕЛА І МЕЖІ (SOURCE_RULES): принцип «старший ТФ → контекст/зона/напрямок → молодші ТФ → точніша точка входу на M5/M1» — USER_REQUIREMENT власниці за відеорозборами
(D-HTF-STRONG-CANDLE-PULLBACK). УМОВИ входу на M5/M1 у доступних текстових джерелах НЕ ПІДТВЕРДЖЕНО (оригінали відео та кадри недоступні в репозиторії). Тому форма M5/M1 нижче —
безчисельна структурна (OUR_IMPLEMENTATION, ГІПОТЕЗА, версія STRUCT_BREAK_V0): жодних ATR-порогів, лише відносні порівняння свічок і два технічні параметри (вікно = 2 бари M15
навколо тригера; фрактал n=2 не використовується). Коли з'являться кадри/текст розборів — замінюється лише функція `ltf_confirm`.
Тип сценарію (продовження/розворот/діапазон) — НАША класифікація (ГІПОТЕЗА): джерела таких термінів як правил не дають.
Режим: OFFICE2_LTF_MODE = off | annotate (за замовчуванням: лише показ і shadow-мітки) | gate (READY вимагає підтвердження M5; інакше WAIT 4/4)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import numpy as np

VERSION = "topdown-v1"
LTF_FORM = "STRUCT_BREAK_V0"
LTF_WINDOW_M15 = 2            # вікно пошуку дотику зони: бар тригера + попередній (технічний параметр, ГІПОТЕЗА)
M5, M1 = 300.0, 60.0
SOURCE_CLASS = "USER_REQUIREMENT (роль M5/M1) + OUR_IMPLEMENTATION (форма входу); умови M5/M1 у джерелах НЕ ПІДТВЕРДЖЕНО"
TYPE_NOTE = "тип сценарію — наша класифікація (ГІПОТЕЗА), не правило з джерел"


def mode() -> str:
    v = os.getenv("OFFICE2_LTF_MODE", "annotate").strip().lower()
    return v if v in ("off", "annotate", "gate") else "annotate"


def _utc(ts: Optional[float]) -> Optional[str]:
    return None if ts is None else datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%d.%m %H:%M UTC")


def _px(x: Any) -> str:
    try:
        return "—" if x is None else f"{float(x):.6g}"
    except (TypeError, ValueError):
        return "—"


def _cut(bars: Optional[Dict[str, Any]], width: float, now: float) -> Optional[Dict[str, np.ndarray]]:
    """Лише бари, ЗАКРИТІ до now (open + width ≤ now). Решта — майбутнє або свічка, що формується, — відкидається."""
    if not isinstance(bars, dict) or "t" not in bars or len(bars["t"]) == 0:
        return None
    t = np.asarray(bars["t"], dtype=float)
    m = t + width <= now + 1e-9
    if not m.any():
        return None
    return {k: np.asarray(bars[k])[m] for k in ("t", "o", "h", "l", "c") if k in bars}


def _mirror(b: Dict[str, np.ndarray], sg: int) -> Dict[str, np.ndarray]:
    if sg > 0:
        return b
    return {"t": b["t"], "o": -b["o"], "h": -b["l"], "l": -b["h"], "c": -b["c"]}


# ------------------------------------------------------------------ M5 / M1: пошук входу всередині зони
def ltf_confirm(direction: str, zone: Optional[List[float]], sl: Optional[float], now: float, m5: Optional[Dict[str, Any]], m1: Optional[Dict[str, Any]],
                window_m15: int = LTF_WINDOW_M15) -> Dict[str, Any]:
    """Форма STRUCT_BREAK_V0 (ГІПОТЕЗА, безчисельна), LONG-координати (SHORT — дзеркало):
      M5-контакт: у вікні [now − window·15хв, now] існує закритий бар M5, що торкнувся зони входу (low ≤ верх зони), і закрився вище SL;
      M5-підтвердження: ПЕРШИЙ наступний закритий бар M5 із закриттям ВИЩЕ найвищого high усіх барів M5 від контакту (мікро-злам структури = реакція покупців у зоні);
      M1-вхід: після закриття цього бару M5 — перше закриття M1 вище зламаного рівня ПІСЛЯ повернення (ретест) до нього; нема ретесту → WAIT_RETEST (рівень = можливий лімітний вхід).
    Лише закриті бари ≤ now; нічого з майбутнього."""
    base = {"form": LTF_FORM, "source_class": SOURCE_CLASS, "window_m15": window_m15}
    if direction not in ("LONG", "SHORT") or not zone or len(zone) != 2 or sl is None:
        return dict(base, status="UNAVAILABLE", text="немає зони входу/SL для перевірки на M5/M1", m5=None, m1=None)
    sg = 1 if direction == "LONG" else -1
    z = sorted([float(zone[0]), float(zone[1])])
    z_hi_v = z[1] if sg > 0 else -z[0]            # «верх» зони в LONG-координатах
    sl_v = sg * float(sl)
    m5c = _cut(m5, M5, now)
    if m5c is None or len(m5c["t"]) < 4:
        return dict(base, status="UNAVAILABLE", text="M5 недоступні", m5=None, m1=None)
    v5 = _mirror(m5c, sg)
    t0 = now - window_m15 * 900.0
    idx = np.flatnonzero(v5["t"] >= t0 - 1e-9)
    if len(idx) < 2:
        return dict(base, status="UNAVAILABLE", text="у вікні замало барів M5", m5=None, m1=None)
    if any(v5["l"][i] <= sl_v + 1e-12 for i in idx):         # захисний SL торкаються дотиком: торкнули — сценарій уже зламано
        return dict(base, status="INVALID", text="на M5 у вікні ціна торкнулась SL: сценарій зламано, вхід не підтверджується", m5={"contact": None}, m1=None)
    contact = next((int(i) for i in idx if v5["l"][i] <= z_hi_v + 1e-12), None)
    if contact is None:
        return dict(base, status="NOT_IN_ZONE", text=f"на M5 у вікні {window_m15 * 15} хв немає дотику зони входу {_px(z[0])}–{_px(z[1])}", m5={"contact": None}, m1=None)
    c_ts = float(v5["t"][contact] + M5)
    for j in range(contact + 1, len(v5["t"])):
        ref_v = float(v5["h"][contact:j].max())
        if v5["c"][j] > ref_v:
            conf_ts = float(v5["t"][j] + M5)
            m5i = {"contact_ts": c_ts, "contact_utc": _utc(c_ts), "ref_level": sg * ref_v, "confirm_ts": conf_ts, "confirm_utc": _utc(conf_ts), "confirm_close": sg * float(v5["c"][j])}
            m1i = _m1_entry(m1, sg, ref_v, conf_ts, sl_v, now)
            txt = (f"M5: дотик зони о {_utc(c_ts)}, закриття {'вище' if sg > 0 else 'нижче'} {_px(sg * ref_v)} о {_utc(conf_ts)} (мікро-злам після дотику)")
            if m1i.get("state") == "RETEST_ENTRY":
                txt += f"; M1: ретест {_px(sg * ref_v)} і закриття назад о {_utc(m1i['entry_ts'])} → точка входу {_px(m1i['entry_price'])}"
            elif m1i.get("state") == "WAIT_RETEST":
                txt += f"; M1: ретесту {_px(sg * ref_v)} ще не було (можливий лімітний рівень входу)"
            return dict(base, status="CONFIRMED", text=txt, m5=m5i, m1=m1i)
    return dict(base, status="PENDING", text=f"M5: дотик зони о {_utc(c_ts)}, але закриття {'вище' if sg > 0 else 'нижче'} максимуму з моменту дотику ще немає", m5={"contact_ts": c_ts, "contact_utc": _utc(c_ts), "confirm_ts": None}, m1=None)


def _m1_entry(m1: Optional[Dict[str, Any]], sg: int, ref_v: float, conf_ts: float, sl_v: float, now: float) -> Dict[str, Any]:
    m1c = _cut(m1, M1, now)
    if m1c is None or len(m1c["t"]) < 3:
        return {"state": "UNAVAILABLE", "note": "M1 недоступні"}
    v1 = _mirror(m1c, sg)
    touched = False
    for k in np.flatnonzero(v1["t"] >= conf_ts - 1e-9):
        if v1["c"][k] <= sl_v:
            return {"state": "INVALID", "note": "M1 закрився за SL"}
        if v1["l"][k] <= ref_v:
            touched = True
        if touched and v1["c"][k] > ref_v:
            ts = float(v1["t"][k] + M1)
            return {"state": "RETEST_ENTRY", "entry_ts": ts, "entry_utc": _utc(ts), "entry_price": sg * float(v1["c"][k]), "retest_level": sg * ref_v}
    return {"state": "WAIT_RETEST", "retest_level": sg * ref_v, "note": "ретест зламаного рівня на M1 ще не відбувся"}


# ------------------------------------------------------------------ тип сценарію та суперечності
def _rel(r: Optional[Dict[str, Any]]) -> str:
    if not r or r.get("status") != "USED":
        return "NA"
    return "WITH" if r.get("with_trade") else "AGAINST" if r.get("against_trade") else "NEUTRAL"


def scenario_type(th: Dict[str, Any]) -> Dict[str, Any]:
    rows = {r.get("tf"): r for r in ((th.get("map") or {}).get("tfs") or [])}
    d1, h4, h1, w1 = (_rel(rows.get(x)) for x in ("D1", "H4", "H1", "W1"))
    long_ = str(th.get("dir") or "LONG").upper() != "SHORT"
    if d1 == "NA" and h4 == "NA":
        return {"type": "UNKNOWN", "label": "тип не визначено", "why": "D1/H4 недоступні", "note": TYPE_NOTE}
    if d1 == "AGAINST" or (d1 != "WITH" and h4 == "AGAINST"):
        who = "D1 і H4" if (d1 == "AGAINST" and h4 == "AGAINST") else ("D1" if d1 == "AGAINST" else "H4")
        return {"type": "REVERSAL", "label": "розворот", "why": f"напрям {'LONG' if long_ else 'SHORT'} проти {who}: це спроба розвороту від ліквідності/рівня, а не продовження", "note": TYPE_NOTE}
    if d1 == "WITH" or h4 == "WITH":
        pull = " (H4 проти — відкат усередині D1-тренду)" if (d1 == "WITH" and h4 == "AGAINST") else ""
        return {"type": "CONTINUATION", "label": "продовження тренду", "why": "старший тренд (D1/H4) за напрямом" + pull, "note": TYPE_NOTE}
    z = (rows.get("H4") or {}).get("zone")
    edge_ok = (z == "discount") if long_ else (z == "premium")
    return {"type": "RANGE", "label": "діапазон (від межі)", "why": f"D1/H4 без тренду; H4-діапазон: ціна в {'discount' if z == 'discount' else 'premium' if z == 'premium' else 'невизначеній'} половині — "
            + ("вхід від правильної межі" if edge_ok else "вхід НЕ від правильної межі діапазону"), "edge_ok": bool(edge_ok), "note": TYPE_NOTE}


def conflicts(th: Dict[str, Any], stype: Dict[str, Any], ltf: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Усі суперечності між ТФ — із типом, серйозністю і поясненням, чому сценарій усе-таки допущено. Нічого не ховається."""
    rows = {r.get("tf"): r for r in ((th.get("map") or {}).get("tfs") or [])}
    integ = th.get("integral") or {}
    proof = bool(integ.get("proof_h1"))
    out: List[Dict[str, Any]] = []
    t = stype.get("type")
    allow = "Brain не блокує за самою суперечністю ТФ: старші ТФ — контекст; блок лише для контртренду від ЛОКАЛЬНОГО рівня без доказу повернення на H1"

    def add(tf: str, sev: str, expected: bool, text: str, why: str) -> None:
        out.append({"tf": tf, "severity": sev, "expected_for_type": expected, "text": text, "why_allowed": why})

    for tf in ("W1", "D1", "H4", "H1"):
        r = rows.get(tf)
        if _rel(r) != "AGAINST":
            continue
        if tf == "W1":
            add(tf, "info", t == "REVERSAL", "W1 проти напряму (макро-контекст)", allow)
        elif tf in ("D1", "H4"):
            if t == "REVERSAL":
                add(tf, "info" if proof else "warn", True, f"{tf} проти напряму — для розвороту це очікувано; доказ повернення на H1: {'є' if proof else 'НЕМАЄ'}", allow)
            elif t == "CONTINUATION":
                add(tf, "info", True, f"{tf} проти напряму всередині іншого старшого тренду (відкат)", allow)
            else:
                add(tf, "warn", False, f"{tf} проти напряму", allow)
        else:  # H1
            if t == "CONTINUATION":
                add(tf, "warn" if not proof else "info", True, "H1 проти напряму: для продовження це відкат, але він ще не завершений" + ("" if proof else " (доказу повернення на H1 немає)"), allow)
            elif t == "REVERSAL":
                add(tf, "warn" if not proof else "info", False, "H1 ще проти напряму розвороту" + ("" if proof else "; доказу повернення на H1 немає"), allow)
            else:
                add(tf, "warn" if not proof else "info", True, "H1 проти напряму в діапазоні: структура H1 ще не розвернулась від межі" + ("" if proof else "; доказу повернення на H1 немає"), allow)
    if t == "RANGE" and stype.get("edge_ok") is False:
        add("H4", "warn", False, "діапазон: вхід не від правильної межі (LONG має бути в discount, SHORT — в premium)", allow)
    loc = (integ.get("location") or {}).get("class")
    if loc == "LOCAL" and t == "REVERSAL":
        add("рівень", "warn", False, "розворот від ЛОКАЛЬНОГО рівня (не старшої ліквідності)", "умовний блок Brain: без доказу H1 це WAIT; тут доказ є" if proof else allow)
    if integ.get("level_retest_after_acceptance"):
        add("M15", "info", False, "повторний тест вже прийнятого рівня (не свіжий grab ліквідності)", "клас LATE_SWEEP показується, але не блокує (різниці в replay немає)")
    if ltf is not None and ltf.get("status") == "INVALID":
        add("M5", "warn", False, str(ltf.get("text")), "SL торкнуто після рішення: сценарій зламано (картку не слід вважати актуальною)")
    if ltf is not None and ltf.get("status") in ("PENDING", "NOT_IN_ZONE"):
        add("M5", "warn", False, f"підтвердження входу на M5 ще немає ({ltf.get('text')})", "у режимі annotate M5/M1 лише показуються; у режимі gate такий сценарій чекає (WAIT 4/4)")
    return out


# ------------------------------------------------------------------ збірка
def _tf_stage(tf: str, role: str, r: Optional[Dict[str, Any]], sg_long: bool) -> Dict[str, Any]:
    if not r or r.get("status") != "USED":
        return {"tf": tf, "role": role, "state": "UNAVAILABLE", "text": f"{tf}: немає даних"}
    rel = _rel(r)
    st = "CONFIRMS" if rel == "WITH" else "CONFLICTS" if rel == "AGAINST" else "NEUTRAL"
    tr = r.get("trend_eff") or 0
    way = "вгору" if tr > 0 else "вниз" if tr < 0 else "діапазон"
    rg = r.get("range") or {}
    facts = []
    if r.get("closed_ts"):
        facts.append(f"остання закрита свічка {_utc(r['closed_ts'])}")
    facts.append(f"swing H {_px(r.get('last_swing_high'))} / L {_px(r.get('last_swing_low'))}")
    if rg.get("hi") is not None:
        facts.append(f"діапазон {_px(rg.get('lo'))}–{_px(rg.get('hi'))}, {r.get('zone') or '—'}")
    return {"tf": tf, "role": role, "state": st, "closed_ts": r.get("closed_ts"), "closed_utc": _utc(r.get("closed_ts")), "trend": way,
            "levels": {"swing_high": r.get("last_swing_high"), "swing_low": r.get("last_swing_low"), "range_lo": rg.get("lo"), "range_hi": rg.get("hi")},
            "text": f"{tf}: {way} — {'ЗА' if rel == 'WITH' else 'ПРОТИ' if rel == 'AGAINST' else 'не підтверджує'} напрям [" + "; ".join(facts) + "]"}


def analyze(th: Dict[str, Any], direction: str, now: float, m5_fetch: Optional[Callable[[], Any]] = None, m1_fetch: Optional[Callable[[], Any]] = None) -> Dict[str, Any]:
    """th — теза після assess (має map/integral/entry_zone/sl). Повертає блок для знімка READY: тип, ТФ-етапи, суперечності, M5/M1."""
    sg_long = direction != "SHORT"
    rows = {r.get("tf"): r for r in ((th.get("map") or {}).get("tfs") or [])}
    stype = scenario_type(th)
    ltf: Dict[str, Any]
    if mode() == "off":
        ltf = {"status": "OFF", "form": LTF_FORM, "text": "перевірку M5/M1 вимкнено (OFFICE2_LTF_MODE=off)", "source_class": SOURCE_CLASS, "m5": None, "m1": None}
    else:
        try:
            m5 = m5_fetch() if m5_fetch else None
        except Exception:  # noqa: BLE001
            m5 = None
        try:
            m1 = m1_fetch() if m1_fetch else None
        except Exception:  # noqa: BLE001
            m1 = None
        try:
            ltf = ltf_confirm(direction, th.get("entry_zone") or th.get("zone"), th.get("sl"), now, m5, m1)
        except Exception as exc:  # noqa: BLE001
            ltf = {"status": "UNAVAILABLE", "form": LTF_FORM, "text": f"помилка перевірки M5/M1: {type(exc).__name__}", "source_class": SOURCE_CLASS, "m5": None, "m1": None}
    stages = [_tf_stage("D1", "контекст і напрям", rows.get("D1"), sg_long), _tf_stage("H4", "контекст, діапазон", rows.get("H4"), sg_long), _tf_stage("H1", "робоча зона / доказ повернення", rows.get("H1"), sg_long)]
    seq = th.get("sequence") or []
    ok = bool(seq) and all(isinstance(x, dict) and x.get("ok") for x in seq)
    trig = th.get("trigger_level")
    stages.append({"tf": "M15", "role": "підтвердження сценарію", "state": "CONFIRMS" if ok else "NEUTRAL", "closed_ts": now, "closed_utc": _utc(now),
                   "text": "M15: " + ("подія → зсув структури → ретрейс у зону → тригер (закриття) виконано" if ok else "ланцюг не завершено") + f"; рішення на закритті свічки {_utc(now)}; зона {_px((th.get('entry_zone') or [None, None])[0])}–{_px((th.get('entry_zone') or [None, None])[-1])}"})
    st5 = {"CONFIRMED": "CONFIRMS", "PENDING": "NEUTRAL", "NOT_IN_ZONE": "NEUTRAL", "INVALID": "CONFLICTS", "UNAVAILABLE": "UNAVAILABLE", "OFF": "UNAVAILABLE"}.get(ltf.get("status"), "NEUTRAL")
    stages.append({"tf": "M5", "role": "реакція у зоні (підтвердження входу)", "state": st5, "closed_ts": (ltf.get("m5") or {}).get("confirm_ts"), "closed_utc": (ltf.get("m5") or {}).get("confirm_utc"),
                   "text": "M5: " + str(ltf.get("text")), "form": LTF_FORM, "source_class": SOURCE_CLASS})
    m1i = ltf.get("m1") or {}
    st1 = "CONFIRMS" if m1i.get("state") == "RETEST_ENTRY" else ("UNAVAILABLE" if m1i.get("state") in (None, "UNAVAILABLE") else "NEUTRAL")
    stages.append({"tf": "M1", "role": "точка входу (ретест)", "state": st1, "closed_ts": m1i.get("entry_ts"), "closed_utc": m1i.get("entry_utc"), "entry_price": m1i.get("entry_price"), "retest_level": m1i.get("retest_level"),
                   "text": "M1: " + ({"RETEST_ENTRY": f"ретест {_px(m1i.get('retest_level'))} і закриття назад о {m1i.get('entry_utc')}: точка входу {_px(m1i.get('entry_price'))}",
                                       "WAIT_RETEST": f"ретесту {_px(m1i.get('retest_level'))} ще не було — можливий лімітний вхід на цьому рівні", "INVALID": "M1 закрився за SL — вхід не доречний"}.get(m1i.get("state"), "немає підтвердження M5, точка входу не уточнюється")),
                   "form": LTF_FORM, "source_class": SOURCE_CLASS})
    cons = conflicts(th, stype, ltf if mode() != "off" else None)
    return {"version": VERSION, "mode": mode(), "scenario_type": stype, "stages": stages, "conflicts": cons, "ltf": ltf, "decided_ts": now,
            "note": "Суперечності між ТФ показуються завжди, оцінюються за типом сценарію й самі нічого не блокують. Форма входу на M5/M1 — OUR_IMPLEMENTATION (ГІПОТЕЗА)."}


def summary_line(td: Optional[Dict[str, Any]]) -> Optional[str]:
    """Один короткий рядок для Telegram: тип + головні суперечності."""
    if not td:
        return None
    st = (td.get("scenario_type") or {}).get("label")
    warns = [c for c in (td.get("conflicts") or []) if c.get("severity") == "warn"]
    parts = [f"тип: {st}"] if st else []
    if warns:
        parts.append("⚠ " + "; ".join(c["text"].split(":")[0].split(" — ")[0] for c in warns[:2]))
    ltf = (td.get("ltf") or {}).get("status")
    if ltf == "CONFIRMED":
        parts.append("M5 підтверджує")
    elif ltf in ("PENDING", "NOT_IN_ZONE"):
        parts.append("M5 ще не підтвердив")
    return " · ".join(parts) or None
