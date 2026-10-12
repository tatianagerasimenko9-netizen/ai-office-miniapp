"""AI Office · покрокова перевірка сценарію (зверху вниз: D1/H4 → H1 → M15 → M5 → M1 → супровід) ЛИШЕ З ФАКТІВ заморожених у знімку READY.

Це схема ВІДОБРАЖЕННЯ, а не твердження, що саме такі кроки дослівно сформулювала Дарія. Для кожного кроку вказано джерела (rule_id у docs/sources/evidence.jsonl) і що саме в ньому НЕ ПІДТВЕРДЖЕНО:
  • старший ТФ задає контекст, молодший підтверджує, а не суперечить — D-HTF-LTF-CONFIRM, D-FRACTAL-TF;
  • «Немає підтвердження — немає угоди», хибний пробій: винос → закріплення/повернення → реакція — D-NO-CONFIRMATION-NO-TRADE, D-FALSE-BREAK;
  • обов'язковий молодший ТФ входу (M1/M5/M15), свічковий тригер входу, люфт для ТФ входу, часткові фіксації — у наданих матеріалах Дарії НЕ ЗНАЙДЕНО (X-NOT-SPECIFIED-DARIA-LTF-ENTRY-TP).
Роль M5/M1 (уточнення точки входу після старшого контексту) — USER_REQUIREMENT власниці за відеорозборами; УМОВИ входу на M5/M1 у доступних текстових джерелах НЕ ПІДТВЕРДЖЕНО, тому крок M5/M1 показує результат безчисельної структурної форми office2/topdown (OUR_IMPLEMENTATION, ГІПОТЕЗА). Для знімків без top-down (старіші READY) M5/M1 лишаються «не вимагається джерелом». Модуль нічого не вирішує і не змінює READY: він лише описує, що перевірено, що ні, і чому вхід ще/вже не доречний.
Умови мають тип (дотик / закриття / ретест), ТФ, ціну і час; скасування сценарію (ЗАКРИТТЯ M15) відокремлене від захисного SL (дотик усередині свічки)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

VERSION = "daria-steps-v1"
M15 = 900.0
MAX_CHASE_R = 0.6            # office2/brain.py: вхід не далі 0.6 R від рівня тригера (та сама величина, що в _late_reason)

SRC = {
    "htf": ["D-HTF-LTF-CONFIRM", "D-FRACTAL-TF"],
    "h1": ["G-LVL-MIRROR", "G-LUFT", "D-LEVEL-STICKING"],
    "m15": ["D-NO-CONFIRMATION-NO-TRADE", "D-FALSE-BREAK", "D-FIB-REACTION-NOT-LIMITS"],
    "ltf": ["X-NOT-SPECIFIED-DARIA-LTF-ENTRY-TP", "D-HTF-STRONG-CANDLE-PULLBACK"],
    "follow": ["D-STOP-STRUCTURE", "G-LUFT"],
}

# статуси кроку: CONFIRMED · NEUTRAL (не підтверджує і не суперечить) · AGAINST · NOT_REQUIRED_BY_SOURCE · UNAVAILABLE


def _utc(ts: Optional[float]) -> Optional[str]:
    return None if ts is None else datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _fnum(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _px(x: Any) -> str:
    v = _fnum(x)
    return "—" if v is None else f"{v:.6g}"


def _tf_row(th: Dict[str, Any], tf: str) -> Optional[Dict[str, Any]]:
    for r in ((th.get("map") or {}).get("tfs") or []):
        if r.get("tf") == tf:
            return r
    return None


def _tf_text(r: Optional[Dict[str, Any]], tf: str) -> Dict[str, Any]:
    if not r or r.get("status") != "USED":
        return {"tf": tf, "state": "UNAVAILABLE", "text": f"{tf}: немає даних"}
    t = r.get("trend_eff") or 0
    way = "вгору" if t > 0 else "вниз" if t < 0 else "діапазон"
    rel = "ЗА напрям" if r.get("with_trade") else "ПРОТИ напрямку" if r.get("against_trade") else "не підтверджує напрям"
    zone = f"{r.get('zone')}" if r.get("zone") else ""
    facts = []
    if r.get("closed_ts"):
        facts.append(f"остання закрита свічка {_utc(r['closed_ts'])}")
    if r.get("last_swing_high") is not None or r.get("last_swing_low") is not None:
        facts.append(f"swing H {_px(r.get('last_swing_high'))} / L {_px(r.get('last_swing_low'))}")
    rg = r.get("range") or {}
    if rg.get("hi") is not None:
        facts.append(f"діапазон {_px(rg.get('lo'))}–{_px(rg.get('hi'))}")
    tail = f" [{'; '.join(facts)}]" if facts else ""
    return {"tf": tf, "state": "WITH" if r.get("with_trade") else "AGAINST" if r.get("against_trade") else "NEUTRAL",
            "text": f"{tf}: {way}, {zone} — {rel}".replace(", —", " —") + tail}


def _evid(snap: Dict[str, Any], needle: str) -> Optional[Dict[str, Any]]:
    for m in (snap.get("evidence") or (snap.get("thesis") or {}).get("evidence") or []):
        if needle.lower() in str(m.get("module") or "").lower():
            return m
    return None


def entry_state(th: Dict[str, Any], price_now: Optional[float]) -> Dict[str, Any]:
    """Де ціна відносно плану ЗАРАЗ. Не наздоганяємо: якщо ціна втекла від входу далі за MAX_CHASE_R — чекати ретест або вважати можливість втраченою."""
    entry, sl = _fnum(th.get("entry")), _fnum(th.get("sl"))
    px = _fnum(price_now)
    if px is None or entry is None or sl is None or entry == sl:
        return {"state": "UNKNOWN", "text": "Поточної ціни немає — стан входу не визначено."}
    long_ = str(th.get("dir") or "LONG").upper() != "SHORT"
    risk = abs(entry - sl)
    trig = _fnum(th.get("trigger_level")) or entry
    chase = ((px - trig) if long_ else (trig - px)) / risk
    z = th.get("entry_zone") or th.get("zone")
    zlo, zhi = (min(z), max(z)) if z and len(z) == 2 else (entry, entry)
    inv = _fnum((th.get("invalidation") or {}).get("price"))
    if (long_ and px <= sl) or ((not long_) and px >= sl):
        return {"state": "SL_ZONE", "text": f"Ціна {_px(px)} уже за захисним SL {_px(sl)} — сценарій зламано, не входити.", "chase_r": round(chase, 2)}
    if chase > MAX_CHASE_R:
        return {"state": "RAN_AWAY", "text": f"Ціна {_px(px)} втекла від входу на {chase:.2f} R (ліміт {MAX_CHASE_R} R): не наздоганяти — чекати ретест зони {_px(zlo)}–{_px(zhi)} або вважати можливість втраченою.", "chase_r": round(chase, 2)}
    if zlo <= px <= zhi:
        return {"state": "IN_ZONE", "text": f"Ціна {_px(px)} у зоні входу {_px(zlo)}–{_px(zhi)}.", "chase_r": round(chase, 2)}
    if (long_ and px > zhi) or ((not long_) and px < zlo):
        return {"state": "ABOVE_ZONE" if long_ else "BELOW_ZONE", "text": f"Ціна {_px(px)} {'вище' if long_ else 'нижче'} зони входу ({chase:.2f} R від тригера): чекати повернення в зону, не переслідувати.", "chase_r": round(chase, 2)}
    return {"state": "TOWARD_INVALIDATION", "text": f"Ціна {_px(px)} {'нижче' if long_ else 'вище'} зони входу, скасування — закриття M15 {'нижче' if long_ else 'вище'} {_px(inv)}.", "chase_r": round(chase, 2)}


def stage_check(th: Dict[str, Any]) -> Dict[str, Any]:
    """Ті самі оцінки старшого контексту, що в build(), але лише з тези (до заморожування знімка): D1/H4 і H1 проти напряму / підтверджують / нейтральні, наявність доказу повернення H1.
    Використовується для shadow-міток (annotate) і для ОПЦІЙНОГО гейта OFFICE2_STAGE_GATE=block (за замовчуванням вимкнено). M5/M1 тут НЕ вимагаються: у наданих джерелах Дарії це НЕ ПІДТВЕРДЖЕНО."""
    rows = {tf: _tf_text(_tf_row(th, tf), tf) for tf in ("D1", "H4", "H1")}
    dh = [rows["D1"], rows["H4"]]
    if all(r["state"] == "UNAVAILABLE" for r in dh):
        d1h4 = "UNAVAILABLE"
    elif any(r["state"] == "AGAINST" for r in dh):
        d1h4 = "AGAINST"
    elif any(r["state"] == "WITH" for r in dh):
        d1h4 = "CONFIRMED"
    else:
        d1h4 = "NEUTRAL"
    h1 = rows["H1"]["state"]
    h1s = "UNAVAILABLE" if h1 == "UNAVAILABLE" else "AGAINST" if h1 == "AGAINST" else "CONFIRMED" if h1 == "WITH" else "NEUTRAL"
    proof = bool((th.get("integral") or {}).get("proof_h1"))
    codes = []
    if d1h4 == "AGAINST":
        codes.append("HTF_AGAINST")
    if h1s == "AGAINST":
        codes.append("H1_AGAINST")
    return {"d1_h4": d1h4, "h1": h1s, "h1_proof": proof, "codes": codes, "texts": {"D1": rows["D1"]["text"], "H4": rows["H4"]["text"], "H1": rows["H1"]["text"]}}


def build(snap: Dict[str, Any], valid_until_ts: Optional[float] = None, price_now: Optional[float] = None) -> Dict[str, Any]:
    th = snap.get("thesis") or {}
    long_ = str(snap.get("direction") or th.get("dir") or "LONG").upper() != "SHORT"
    side = "LONG" if long_ else "SHORT"
    prov = snap.get("data_provenance") or {}
    decided = _fnum(snap.get("decided_ts"))
    closed_ts = _fnum(prov.get("last_closed_bar_close_ts")) or decided
    entry, sl = _fnum(th.get("entry")), _fnum(th.get("sl"))
    tg = th.get("targets") or []
    inv = th.get("invalidation") or {}
    inv_px = _fnum(inv.get("price"))
    risk = abs(entry - sl) if entry is not None and sl is not None else None
    steps: List[Dict[str, Any]] = []
    risks: List[str] = []

    # --- 1. D1 / H4 — старший контекст
    rows = [_tf_text(_tf_row(th, tf), tf) for tf in ("MN", "W1", "D1", "H4")]
    dh = [r for r in rows if r["tf"] in ("D1", "H4")]
    if all(r["state"] == "UNAVAILABLE" for r in dh):
        st1 = "UNAVAILABLE"
    elif any(r["state"] == "AGAINST" for r in dh):
        st1 = "AGAINST"
    elif any(r["state"] == "WITH" for r in dh):
        st1 = "CONFIRMED"
    else:
        st1 = "NEUTRAL"
    obst = (th.get("obstacles_before_tp1") or [])
    room = f"Перша ціль TP1 {_px((tg[0] or {}).get('p'))} ({(tg[0] or {}).get('r', 0):.2f} R, {(tg[0] or {}).get('kind', '')})" if tg else "цілей немає"
    if obst:
        o = obst[0]
        room += f"; перешкода до TP1: {o.get('kind')} {_px(o.get('p'))} ({float(o.get('r') or 0):.2f} R)"
    steps.append({"id": "HTF", "tf": "D1 / H4", "title": "Старший контекст", "status": st1,
                  "checked": "напрямок і структура старших ТФ, положення в діапазоні (premium/discount), простір до наступної перешкоди",
                  "result": "; ".join(r["text"] for r in rows) + ". " + room + ".",
                  "refutes": [r["text"] for r in rows if r["state"] == "AGAINST"],
                  "unknown": ["вага кожного старшого ТФ у рішенні — НЕ ПІДТВЕРДЖЕНО в джерелах (контекст, не числовий поріг)"],
                  "allows_next": st1 != "AGAINST", "sources": SRC["htf"]})
    if st1 in ("NEUTRAL", "AGAINST"):
        risks.append("D1/H4 не підтверджують напрям (" + ("проти" if st1 == "AGAINST" else "діапазон") + ") — сценарій спирається на нижчі ТФ")

    # --- 2. H1 — робоча зона / рівень
    lvl = th.get("level") or {}
    mir = _evid(snap, "mirror")
    mdata = (mir or {}).get("data") or {}
    h1 = _tf_text(_tf_row(th, "H1"), "H1")
    integ = th.get("integral") or snap.get("integral") or {}
    proof = integ.get("proof_h1")
    if not lvl:
        st2 = "UNAVAILABLE"
    elif h1["state"] == "AGAINST":
        st2 = "AGAINST"
    elif h1["state"] == "WITH" or proof:
        st2 = "CONFIRMED"
    else:
        st2 = "NEUTRAL"
    parts = [f"Рівень {lvl.get('kind')} {_px(lvl.get('p'))} (сила {lvl.get('strength')})" if lvl else "рівня немає"]
    if mdata:
        parts.append(f"ретестів {mdata.get('retests')}, барів під рівнем до перетину {mdata.get('bars_below_before')}")
    if inv.get("buffer_basis"):
        parts.append(f"люфт {_px(inv.get('buffer'))} ({inv.get('buffer_basis')})")
    parts.append(h1["text"])
    parts.append("доказ повернення H1: " + ("є" if proof else "немає"))
    steps.append({"id": "H1", "tf": "H1", "title": "Робоча зона", "status": st2,
                  "checked": "звідки виник рівень, скільки реакцій і ретестів, поведінка на рівні, чи H1 не суперечить напрямку",
                  "result": "; ".join(parts) + ".",
                  "refutes": ([h1["text"]] if h1["state"] == "AGAINST" else []) + ([] if proof else ["немає доказу повернення на H1"]),
                  "unknown": ["кількісні пороги «підтиснення» та «якості реакції» — НЕ ПІДТВЕРДЖЕНО (D-LEVEL-STICKING)"],
                  "allows_next": st2 != "AGAINST", "sources": SRC["h1"]})
    if st2 == "AGAINST":
        risks.append("H1 проти напрямку; Brain допустив READY (verdict=" + str(integ.get("verdict")) + ") — це рішення моделі, не підтвердження методикою")
    elif not proof:
        risks.append("немає доказу повернення на H1")

    # --- 3. M15 — підтвердження (закрита свічка)
    seq = th.get("sequence") or snap.get("sequence") or []
    brk = th.get("break") or {}
    zone = th.get("entry_zone") or th.get("zone") or []
    trig = _fnum(th.get("trigger_level"))
    done = [x for x in seq if isinstance(x, dict) and x.get("ok")]
    all_ok = bool(seq) and len(done) == len(seq)
    res3 = [f"{x.get('step')}: {x.get('value')}" for x in seq if isinstance(x, dict)]
    if brk:
        res3.append(f"зсув: закриття {'вище' if long_ else 'нижче'} {_px(brk.get('level'))}, тіло {float(brk.get('body_atr') or 0):.2f} ATR, утримано барів: {brk.get('bars_held')}")
    if zone and len(zone) == 2:
        res3.append(f"ретрейс у зону {_px(min(zone))}–{_px(max(zone))}")
    if trig is not None:
        res3.append(f"тригер: закриття M15 {'вище' if long_ else 'нижче'} {_px(trig)}")
    res3.append(f"рішення прийнято на закритті бару о {_utc(closed_ts)}; після цього момент вхід не переглядається заднім числом")
    steps.append({"id": "M15", "tf": "M15", "title": "Підтвердження", "status": "CONFIRMED" if all_ok else "UNAVAILABLE",
                  "checked": "закрита свічка: подія → зсув структури (закріплення) → ретрейс → тригер; незакриті свічки не підтверджують",
                  "result": "; ".join(res3) + ".", "condition": {"type": "CLOSE", "tf": "M15", "price": trig, "closed_ts": closed_ts, "closed_utc": _utc(closed_ts)},
                  "refutes": [], "unknown": ["форма підтвердження і ТФ для входу — НЕ ПІДТВЕРДЖЕНО в джерелах Дарії; M15-тригер — модель Brain v2.1"],
                  "allows_next": all_ok, "sources": SRC["m15"]})

    # --- 4–5. M5 / M1 — пошук точки входу (top-down). Для старих знімків без topdown — як раніше
    td = th.get("topdown") or snap.get("topdown") or {}
    stg = {x.get("tf"): x for x in (td.get("stages") or [])}
    SMAP = {"CONFIRMS": "CONFIRMED", "NEUTRAL": "NEUTRAL", "CONFLICTS": "AGAINST", "UNAVAILABLE": "UNAVAILABLE"}
    ltf_unknown = ["форма підтвердження і умови входу на M5/M1 у доступних текстових джерелах НЕ ПІДТВЕРДЖЕНО (оригінали відеорозборів недоступні); реалізовано безчисельну структурну форму STRUCT_BREAK_V0 (ГІПОТЕЗА)"]
    if stg.get("M5"):
        x5, x1 = stg["M5"], stg.get("M1") or {}
        steps.append({"id": "M5", "tf": "M5", "title": "Реакція у зоні (підтвердження входу)", "status": SMAP.get(x5.get("state"), "NEUTRAL"),
                      "checked": "чи торкнулась ціна зони входу і чи закрилась M5 за максимумом з моменту дотику (мікро-злам = реакція покупців/продавців у зоні); лише закриті свічки",
                      "result": x5.get("text", ""), "condition": {"type": "CLOSE", "tf": "M5", "closed_ts": x5.get("closed_ts"), "closed_utc": x5.get("closed_utc")},
                      "refutes": ([x5.get("text")] if x5.get("state") in ("NEUTRAL", "CONFLICTS") else []), "unknown": ltf_unknown, "allows_next": x5.get("state") != "CONFLICTS", "sources": SRC["ltf"]})
        steps.append({"id": "M1", "tf": "M1", "title": "Точка входу (ретест)", "status": SMAP.get(x1.get("state"), "NEUTRAL"),
                      "checked": "після підтвердження M5: ретест зламаного рівня на M1 і закриття назад = точна точка входу; без ретесту — лише можливий лімітний рівень",
                      "result": x1.get("text", ""), "condition": {"type": "CLOSE", "tf": "M1", "closed_ts": x1.get("closed_ts"), "closed_utc": x1.get("closed_utc"), "price": x1.get("entry_price")},
                      "refutes": [], "unknown": ltf_unknown, "allows_next": True, "sources": SRC["ltf"]})
        if x5.get("state") in ("NEUTRAL", "CONFLICTS"):
            risks.append("M5 ще не підтвердив вхід у зоні (" + str(x5.get("text")) + ")")
    else:
        m5 = _evid(snap, "m5")
        steps.append({"id": "M5", "tf": "M5", "title": "Ретест (довідково)", "status": "NOT_REQUIRED_BY_SOURCE",
                      "checked": "чи повернулася ціна в зону і чи збережена структура — як ДОДАТКОВИЙ контекст",
                      "result": (f"{m5.get('finding')}" if m5 else "M5 не входить до умов READY (знімок до top-down)."),
                      "refutes": [], "unknown": ltf_unknown, "allows_next": True, "sources": SRC["ltf"]})
        steps.append({"id": "M1", "tf": "M1", "title": "Виконання", "status": "NOT_REQUIRED_BY_SOURCE",
                      "checked": "уточнення ціни входу після всіх обов'язкових підтверджень; M1 не замінює M15",
                      "result": f"Вхід лише в зоні {_px(min(zone)) if zone else '—'}–{_px(max(zone)) if zone else '—'} і не далі {MAX_CHASE_R} R від тригера; вхід заднім числом і погоня за ціною заборонені.",
                      "refutes": [], "unknown": ltf_unknown, "allows_next": True, "sources": SRC["ltf"]})
    ltf_ok = (td.get("ltf") or {}).get("status") == "CONFIRMED" if td else True

    # --- 6. скасування і захист — окремо
    cancel = None
    if inv_px is not None:
        cancel = {"type": "CLOSE", "tf": "M15", "price": inv_px, "side": "нижче" if long_ else "вище",
                  "text": f"Скасування сценарію: ЗАКРИТТЯ M15 {'нижче' if long_ else 'вище'} {_px(inv_px)} (до входу — ідея знімається; після входу — структура зламана).",
                  "basis": inv.get("why"), "source_note": "рівень скасування = екстремум події (sweep/origin) за моделлю Brain; закриття — умова скасування, а не ордер"}
    protective = None
    if sl is not None:
        protective = {"type": "TOUCH", "price": sl, "buffer": inv.get("buffer"), "buffer_basis": inv.get("buffer_basis"),
                      "text": f"Захисний SL {_px(sl)} — реальний стоп-ордер, спрацьовує ДОТИКОМ усередині свічки і може виконатися раніше за скасування; очікування закриття M15 від вибивання не захищає.",
                      "source_note": "SL за структурою з люфтом = медіана проколів рівня (G-LUFT, D-STOP-STRUCTURE); числа люфту — наша реалізація"}
    follow = []
    for i, t in enumerate(tg[:3], 1):
        follow.append(f"TP{i} {_px(t.get('p'))} ({float(t.get('r') or 0):.2f} R, {t.get('kind')})")
    gaps = []
    if len(tg) < 3:
        gaps.append(f"TP{len(tg) + 1}–TP3 відсутні: за картою рівнів немає наступних реальних цілей — не вигадуємо")
    steps.append({"id": "FOLLOW", "tf": "Супровід", "title": "SL, цілі, скасування, строк", "status": "CONFIRMED" if (entry is not None and sl is not None and tg) else "UNAVAILABLE",
                  "checked": "SL, TP1/TP2/TP3, скасування, строк дії",
                  "result": f"Вхід {_px(entry)}, SL {_px(sl)}, " + ", ".join(follow) + (f"; дійсний до {_utc(valid_until_ts)}" if valid_until_ts else "") + ". Події ENTRY / TP / SL / INVALIDATED фіксуються лише за фактичним рухом ціни на ф'ючерсах Binance, без вигаданих часткових закриттів і PnL.",
                  "refutes": [], "unknown": ["часткові фіксації і перенесення стопа — у джерелах Дарії НЕ ПІДТВЕРДЖЕНО"], "gaps": gaps, "allows_next": True, "sources": SRC["follow"]})

    # --- чому НЕ входити зараз / що ще може завадити
    not_now: List[Dict[str, Any]] = []
    es = entry_state(th, price_now)
    if es["state"] in ("RAN_AWAY", "SL_ZONE", "ABOVE_ZONE", "BELOW_ZONE", "TOWARD_INVALIDATION"):
        not_now.append({"tf": "ціна", "type": "ENTRY", "text": es["text"]})
    for t in risks:
        not_now.append({"tf": "контекст", "type": "RISK", "text": t})
    for a in (integ.get("against") or [])[:5]:
        not_now.append({"tf": "ПРОТИ", "type": "AGAINST", "text": str(a)})
    for g in gaps:
        not_now.append({"tf": "цілі", "type": "GAP", "text": g})

    first_fail = next((s for s in steps if s["status"] in ("AGAINST", "UNAVAILABLE")), None)
    verdict = "ALL_REQUIRED_CONFIRMED" if all_ok and st1 != "AGAINST" and st2 != "AGAINST" and ltf_ok else "CHECK_RISKS"
    return {"version": VERSION, "symbol": snap.get("symbol"), "direction": side, "steps": steps, "cancel": cancel, "protective_sl": protective,
            "entry": {"price": entry, "zone": [min(zone), max(zone)] if zone and len(zone) == 2 else None, "max_chase_r": MAX_CHASE_R, "state": es},
            "valid_until_ts": valid_until_ts, "valid_until_utc": _utc(valid_until_ts), "not_now": not_now, "verdict": verdict,
            "first_problem": (first_fail or {}).get("id"),
            "scenario_type": td.get("scenario_type"), "conflicts": td.get("conflicts") or [], "ltf": td.get("ltf"), "topdown_stages": td.get("stages"),
            "note": "Схема відображення; не дослівна послідовність Дарії. Роль M5/M1 — вимога власниці; умови входу на M5/M1 у джерелах НЕ ПІДТВЕРДЖЕНО (форма — наша гіпотеза). Усі ціни й час — з заморожених фактів знімка."}


def telegram_confirmation(snap: Dict[str, Any], fmt=None, stamp=None) -> List[str]:
    """2–3 короткі рядки для Telegram: що підтверджено і де НЕ підтверджено (без вигаданих умов). fmt — форматер ціни, stamp — форматер часу (Київ)."""
    d = build(snap)
    fp = fmt or _px
    by = {s["id"]: s for s in d["steps"]}
    ua = {"CONFIRMED": "підтверджує", "NEUTRAL": "діапазон (без підтвердження)", "AGAINST": "проти", "UNAVAILABLE": "немає даних"}
    out = []
    for key, label in (("HTF", "D1/H4"), ("H1", "H1")):
        s = by.get(key)
        if s:
            out.append(f"{label} — {ua.get(s['status'], s['status'])}")
    m = by.get("M15")
    c = (m or {}).get("condition") or {}
    m5s = by.get("M5")
    if m and m["status"] == "CONFIRMED":
        when = ""
        if c.get("closed_ts"):
            when = f" ({stamp(c['closed_ts']) + ' Київ' if stamp else c.get('closed_utc')})"
        out.append(f"M15 — закриття {'вище' if d['direction'] == 'LONG' else 'нижче'} {fp(c.get('price'))}{when}")
    if m5s and m5s.get("status") in ("CONFIRMED", "NEUTRAL", "AGAINST") and (d.get("ltf") or {}).get("status") not in (None, "OFF"):
        c5 = m5s.get("condition") or {}
        if m5s["status"] == "CONFIRMED":
            w5 = f" ({stamp(c5['closed_ts']) + ' Київ' if stamp else c5.get('closed_utc')})" if c5.get("closed_ts") else ""
            out.append("M5 — підтверджує" + w5)
        else:
            out.append("M5 — ще не підтвердив")
    return out
