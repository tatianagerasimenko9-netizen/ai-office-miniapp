"""Аналітик READY: 12-пунктний розбір сценарію з фактів, що вже є в тезі на момент рішення (без нових порогів і без нових даних).

Що це: шар «намиста» — картки методик (rule_id з docs/sources/evidence.jsonl), зв'язки між ними (підтверджує / суперечить / доповнює / пояснює / уточнює)
і структурований розбір для людини та для навчання. Нічого не вигадує: кожне твердження — це поле теза (integral, alignment, map, topdown, stops, quality)
або арифметика від рівнів сценарію (R). Те, що не є джерелом, позначено ГІПОТЕЗА.

Вплив на рішення (OFFICE2_ANALYST):
  off       — вимкнено;
  annotate  — розбір зберігається у snapshot і в таблиці office2_analyst, READY не змінюється;
  critical  — (за замовчуванням) READY → NO_TRADE лише за КРИТИЧНИМ дефектом плану: немає SL/розміру/походження даних, SL з неправильного боку входу.
Другорядні суперечності (premium/discount, CVD, відносна сила, перешкода до TP1…) критичними не є: вони знижують оцінку якості (grade) і
записуються разом з результатом угоди — висновки про їхню користь робляться лише на незалежних спостереженнях (тижневий розбір).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Mapping, Optional

VERSION = "analyst-1"

# Модуль доказів Brain → картки реєстру 82 (лише за змістом: що саме перевіряє модуль).
MODULE_CARDS: Dict[str, List[str]] = {
    "OB / FVG / OTE (premium-discount)": ["S-OTE-PD", "S-OB", "S-FVG", "S-RANGE"],
    "Gerchik mirror level + люфт": ["G-LVL-MIRROR", "G-LUFT"],
    "Wyckoff (spring/upthrust, тест)": ["D-WYCKOFF-CONTEXT"],
    "Bulkowski (формалізовані фігури)": ["G-FIGURES-UNMAPPED"],
    "regression channel": ["G-CHANNEL"],
    "volume / taker-delta / CVD": ["D-VOLUME-PRICE"],
    "Strong Candle (наша реалізація sc-ours-1)": ["D-CANDLE-STRENGTH"],
    "M5/M1 тригер": ["D-HTF-LTF-CONFIRM"],
    "HTF MN/W1/4D/3D/D1/H4/H1": ["D-FRACTAL-TF"],
}
# Ребра «намиста»: (картка A, картка B, зв'язок за змістом карток). Знак підтвердження/суперечності обчислюється з конкретного сигналу.
EDGES = [
    ("S-OTE-PD", "S-RANGE", "уточнює"),
    ("S-OTE-PD", "G-LVL-MIRROR", "доповнює"),
    ("D-VOLUME-PRICE", "D-CANDLE-STRENGTH", "підтверджує"),
    ("D-HTF-LTF-CONFIRM", "D-FRACTAL-TF", "пояснює"),
    ("G-LVL-MIRROR", "D-FALSE-BREAK", "доповнює"),
    ("G-FIGURES-UNMAPPED", "G-CHANNEL", "доповнює"),
    ("D-WYCKOFF-CONTEXT", "D-VOLUME-PRICE", "пояснює"),
    ("G-RR-MIN3", "D-STOP-STRUCTURE", "уточнює"),
]


def load_tactic_table() -> dict:
    """Таблиця «корзина перешкоди → тактика» з office2/tactic_table.json. Файл з'являється лише після того, як replay підтвердив перевагу (verdict ADOPT_TABLE) — інакше порожньо → T0."""
    import json as _json
    from pathlib import Path as _P

    f = _P(__file__).with_name("tactic_table.json")
    try:
        j = _json.loads(f.read_text(encoding="utf-8"))
        return j.get("table") if j.get("verdict") == "ADOPT_TABLE" else {}
    except (OSError, ValueError):
        return {}


def compact_chain(method_chain: Mapping[str, Any]) -> Dict[str, Any]:
    """Ланцюг 82 карток (DATA → HTF → РІВНІ/ЛІКВІДНІСТЬ → ПОВЕДІНКА → СЦЕНАРІЙ → ВХІД → РИЗИК → СУПРОВІД) у стислому вигляді для розбору READY.
    FAIL = умова картки порушена, PASS = виконана, UNKNOWN = немає даних (НЕ підтвердження), N/A = за межами застосування. Розрив ланцюга = перша фаза з порушеннями."""
    phases = []
    for g in method_chain.get("phases") or []:
        c = {"PASS": [], "FAIL": [], "UNKNOWN": 0, "NOT_APPLICABLE": 0}
        for it in g.get("rules") or []:
            st = it.get("status")
            if st in ("PASS", "FAIL"):
                c[st].append(it["rule_id"])
            elif st in c:
                c[st] += 1
        phases.append({"phase": g.get("phase"), "pass": c["PASS"], "fail": c["FAIL"], "unknown": c["UNKNOWN"], "na": c["NOT_APPLICABLE"]})
    first_break = next((p["phase"] for p in phases if p["fail"]), None)
    return {"phases": phases, "counts": method_chain.get("counts"), "first_break": first_break,
            "activated": sum(len(p["pass"]) + len(p["fail"]) for p in phases), "total": sum(len(p["pass"]) + len(p["fail"]) + p["unknown"] + p["na"] for p in phases)}


def mode() -> str:
    v = os.environ.get("OFFICE2_ANALYST", "critical").strip().lower()
    return v if v in ("off", "annotate", "critical") else "critical"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _px(v: Any) -> str:
    x = _f(v)
    if x is None:
        return "—"
    return f"{x:.5f}".rstrip("0").rstrip(".") if abs(x) < 1 else f"{x:.4f}".rstrip("0").rstrip(".")


def _r(price: float, entry: float, sl: float, direction: str) -> Optional[float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    gain = (entry - price) if direction == "SHORT" else (price - entry)
    return round(gain / risk, 2)


def critical_defects(th: Mapping[str, Any]) -> List[str]:
    """Дефекти, за яких сценарій неможливо виконати/виміряти. Не пороги, а структурна коректність плану."""
    out: List[str] = []
    d = th.get("dir")
    entry, sl = _f(th.get("entry")), _f(th.get("sl"))
    if entry is None or sl is None:
        out.append("немає входу або SL")
    elif (d == "LONG" and sl >= entry) or (d == "SHORT" and sl <= entry):
        out.append("SL з неправильного боку входу")
    if not th.get("targets"):
        out.append("немає жодної цілі")
    sz = th.get("sizing") or {}
    if not sz or _f(sz.get("risk_usd")) in (None, 0.0) or _f(sz.get("notional_usd")) is None:
        out.append("не визначено розмір позиції/ризик")
    return out


def _sign(finding: str, supports: Any) -> int:
    try:
        return int(supports)
    except (TypeError, ValueError):
        return 0


def analyze(th: Mapping[str, Any], hyps: Optional[List[Mapping[str, Any]]] = None, chain: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    d = str(th.get("dir") or "")
    entry, sl = _f(th.get("entry")), _f(th.get("sl"))
    ig = th.get("integral") or {}
    f_for, f_against = list(ig.get("for") or []), list(ig.get("against") or [])
    td = th.get("topdown") or {}
    stype = (td.get("scenario_type") or {})
    stages = td.get("stages") or []
    zone = th.get("entry_zone") or th.get("zone")
    ev = th.get("evidence") or []
    mp = th.get("map") or {}
    ev_counts = th.get("evidence_counts") or {}

    # --- 1-2 гіпотези
    ev_cls = (th.get("event") or {}).get("class")
    lvl = th.get("level") or {}
    primary = (f"{d}: {th.get('reason') or 'послідовність подія → зсув → ретрейс → тригер'}"
               + (f"; рівень {lvl.get('kind')} {_px(lvl.get('p'))}" if lvl else "")
               + (f"; клас події {ev_cls}" if ev_cls else ""))
    alt = []
    if ev_cls == "LATE_SWEEP":
        pr = (th.get("event") or {}).get("prior") or {}
        alt.append(f"ГІПОТЕЗА: це не новий збір ліквідності, а повторний тест прийнятого рівня ({pr.get('closes_beyond')} із {pr.get('bars')} попередніх закриттів були за ним) — можливе продовження руху за рівнем")
    if stype.get("type") == "RANGE":
        alt.append("ГІПОТЕЗА: діапазон — рух до протилежної межі, якщо вхід не від правильної межі діапазону" if stype.get("edge_ok") is False else "діапазон: торгівля від межі до межі")
    if not alt:
        alt.append("ГІПОТЕЗА: протилежний напрям ставати основним, якщо інвалідація спрацює (див. п.9)")

    # --- 6 найближча перешкода
    obst = (th.get("obstacles_before_tp1") or [])
    near = obst[0] if obst else None
    # --- 11 рівні
    tgt = []
    for t in th.get("targets") or []:
        tp = _f(t.get("p"))
        tgt.append({"kind": t.get("kind"), "p": tp, "r": (_r(tp, entry, sl, d) if None not in (tp, entry, sl) else _f(t.get("r")))})
    tp1_r = tgt[0]["r"] if tgt else None

    # --- 7-8 підтверджено / ні
    confirmed = [f"{s.get('tf')}: {s.get('text', '')[:140]}" for s in stages if s.get("state") == "CONFIRMS"]
    pending = [f"{s.get('tf')}: {s.get('text', '')[:140]}" for s in stages if s.get("state") not in ("CONFIRMS", None) and s.get("tf") in ("M5", "M1", "H1", "H4", "D1")]
    unavailable = [e.get("module") for e in ev if e.get("status") == "NOT_CONNECTED"]
    m1 = (td.get("ltf") or {}).get("m1") or {}

    # --- 10 чому зараз / чекати (арифметика від зони та ретесту)
    now_or_wait: Dict[str, Any] = {"decision": "ENTER_NOW", "why": []}
    alt_entry = None
    if zone and entry is not None and sl is not None:
        lo, hi = float(zone[0]), float(zone[1])
        mid = (lo + hi) / 2
        beyond = (d == "LONG" and entry > hi) or (d == "SHORT" and entry < lo)
        if beyond:
            now_or_wait["why"].append(f"вхід {_px(entry)} за межею зони {_px(lo)}–{_px(hi)} (закриття тригера, не ціна в зоні)")
        if m1.get("state") == "WAIT_RETEST":
            now_or_wait["why"].append(f"M1: ретест {_px(m1.get('retest_level'))} ще не відбувся")
        # альтернативний лімітний вхід: середина зони (ГІПОТЕЗА, арифметика R на тих самих SL/TP)
        if (d == "LONG" and mid < entry) or (d == "SHORT" and mid > entry):
            alt_entry = {"price": round(mid, 6), "basis": "середина зони входу (ГІПОТЕЗА)",
                         "tp_r": [(_r(t["p"], mid, sl, d) if t["p"] is not None else None) for t in tgt]}
        if m1.get("state") == "RETEST_ENTRY":
            now_or_wait["why"].append(f"M1: ретест {_px(m1.get('retest_level'))} відбувся, точка входу {_px(m1.get('entry_price'))}")
    # --- вага суперечностей
    against_n, for_n = len(f_against), len(f_for)
    key_contra = f_against[0] if f_against else None
    rr_src = None
    if tp1_r is not None:
        rr_src = {"rule": "G-RR-MIN3", "source_min": 3.0, "tp1_r": tp1_r, "met": tp1_r >= 3.0,
                  "note": "джерело (Герчик): план R:R ≥ 3; у Brain не примусово (NOT_ENFORCED_IN_BRAIN)"}
    obstacle_r = _f((near or {}).get("r"))
    flags: List[str] = []
    if key_contra:
        flags.append("HAS_CONTRADICTIONS")
    if obstacle_r is not None and tp1_r is not None and obstacle_r < 1.0:
        flags.append("OBSTACLE_LT_1R")
    if rr_src and not rr_src["met"]:
        flags.append("RR_BELOW_SOURCE_MIN")
    if stype.get("edge_ok") is False:
        flags.append("RANGE_WRONG_EDGE")
    st = th.get("stops") or {}
    if st and all(((st.get(k) or {}).get("justified") is False) for k in ("v1", "v2", "v3") if k in st):
        flags.append("STOP_NOT_JUSTIFIED")
    if m1.get("state") == "WAIT_RETEST":
        flags.append("M1_RETEST_PENDING")
    if ev_counts.get("against", 0) > ev_counts.get("for", 0) or against_n > for_n:
        flags.append("AGAINST_GT_FOR")
    critical = critical_defects(th)
    # --- узгодженість з активними гіпотезами рушія (HYPOTHESIS, SHADOW): лише мітка й журнал, на оцінку grade не впливає (користь для READY не доведена)
    hyp_al = None
    if hyps is not None:
        same = [h for h in hyps if h.get("direction") == d]
        opp = [h for h in hyps if h.get("direction") in ("LONG", "SHORT") and h.get("direction") != d]
        hyp_al = {"same": [f"{h.get('family')} ({h.get('stage')})" for h in same], "opposite": [f"{h.get('family')} ({h.get('stage')})" for h in opp],
                  "net": ("MIXED" if same and opp else "SUPPORTS" if same else "CONFLICTS" if opp else "NONE"),
                  "note": "гіпотези — додатковий шар доказів (SHADOW); READY вони не змінюють"}
        if hyp_al["net"] in ("CONFLICTS", "MIXED"):
            flags.append("HYP_OPPOSITE_ACTIVE")
        elif hyp_al["net"] == "SUPPORTS":
            flags.append("HYP_SUPPORTS")

    # --- картки та зв'язки
    cards: Dict[str, int] = {}
    for e in ev:
        for cid in MODULE_CARDS.get(str(e.get("module")), []):
            s = _sign("", e.get("supports"))
            if e.get("status") == "USED":
                cards[cid] = s if cid not in cards or cards[cid] == 0 else cards[cid]
    if rr_src:
        cards["G-RR-MIN3"] = 1 if rr_src["met"] else -1
    if st:
        cards["D-STOP-STRUCTURE"] = -1 if "STOP_NOT_JUSTIFIED" in flags else 1
    links = []
    for a, b, rel in EDGES:
        if a in cards and b in cards:
            sa, sb = cards[a], cards[b]
            if sa == 0 or sb == 0:
                continue
            links.append({"a": a, "b": b, "relation": rel if sa == sb else "суперечить", "signs": [sa, sb]})

    if chain:
        for ph in chain.get("phases") or []:
            for rid in ph.get("pass") or []:
                cards.setdefault(rid, 1)
            for rid in ph.get("fail") or []:
                cards.setdefault(rid, -1)
    grade = "A"
    penal = sum(1 for f in flags if f in ("OBSTACLE_LT_1R", "RR_BELOW_SOURCE_MIN", "RANGE_WRONG_EDGE", "STOP_NOT_JUSTIFIED", "AGAINST_GT_FOR", "M1_RETEST_PENDING"))
    if critical:
        grade = "X"
    elif penal >= 3:
        grade = "C"
    elif penal >= 1:
        grade = "B"
    if critical:
        verdict = "CRITICAL_PROBLEM"
    elif alt_entry and "RR_BELOW_SOURCE_MIN" in flags and (tp1_r or 0) < 1.5:
        verdict = "PREFER_BETTER_ENTRY"
    elif penal >= 3:
        verdict = "CAUTION"
    else:
        verdict = "CONFIRM"
    if verdict in ("PREFER_BETTER_ENTRY", "CAUTION"):
        now_or_wait["decision"] = "ENTER_ON_LIMIT" if alt_entry else "WAIT"

    follow = [f"TP{i + 1} {_px(t['p'])} ({t['r']}R)" for i, t in enumerate(tgt)]
    follow += [f"перешкода {o.get('kind')} {_px(o.get('p'))} на {round(_f(o.get('r')) or 0, 2)}R" for o in obst[:3]]
    try:
        from office2 import tactic as _TC

        tactic = _TC.advise(th, load_tactic_table())
    except Exception as exc:  # noqa: BLE001
        tactic = {"tactic": "T0_enter_now", "reason": f"недоступно: {type(exc).__name__}", "table_used": False, "options": {}}
    return {
        "tactic": tactic,
        "version": VERSION, "mode": mode(), "role": "ANALYST_ADVISORY",
        "hypothesis": {"primary": primary, "alternative": alt},
        "for": f_for, "against": f_against, "key_contradiction": key_contra,
        "nearest_obstacle": near, "confirmed": confirmed, "not_confirmed": pending, "unavailable": unavailable,
        "invalidation": th.get("invalidation"), "now_or_wait": now_or_wait, "alt_entry": alt_entry,
        "levels": {"entry": entry, "sl": sl, "zone": zone, "targets": tgt, "risk_pct": _f(th.get("risk_pct"))},
        "follow_up": follow, "rr_source_check": rr_src, "flags": flags, "critical": critical,
        "grade": grade, "verdict": verdict, "would_block_advisory": [f for f in ("STOP_NOT_JUSTIFIED", "HYP_OPPOSITE_ACTIVE") if f in flags], "hypotheses": hyp_al,
        "cards": cards, "links": links, "chain82": chain,
        "note": "Розбір складено лише з фактів сценарію на момент рішення; пороги не вигадувались; ГІПОТЕЗА позначена. Результат угоди сюди не потрапляє.",
    }


# ---------------------------------------------------------------- persistence / learning
DDL = ("""CREATE TABLE IF NOT EXISTS office2_analyst (
    scenario_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, created_ts DOUBLE PRECISION NOT NULL,
    grade TEXT, verdict TEXT, flags TEXT, cards_json TEXT, record_json TEXT, version TEXT)""",)
_READY: set = set()


def _ensure(db: str) -> None:
    if db in _READY:
        return
    from office_bridge import _execute

    for q in DDL:
        _execute(db, q)
    _READY.add(db)


def persist(db: str, scenario_id: str, sym: str, direction: str, now: float, rec: Mapping[str, Any]) -> None:
    from office_bridge import _execute

    _ensure(db)
    _execute(db, "INSERT INTO office2_analyst(scenario_id, symbol, direction, created_ts, grade, verdict, flags, cards_json, record_json, version) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
             (scenario_id, sym, direction, now, rec.get("grade"), rec.get("verdict"), ",".join(rec.get("flags") or []),
              json.dumps(rec.get("cards") or {}), json.dumps(rec, ensure_ascii=False, default=str), VERSION))


def list_records(db: str, limit: int = 50) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    _ensure(db)
    rows = _fetchall(db, "SELECT scenario_id, symbol, direction, created_ts, grade, verdict, flags, record_json FROM office2_analyst ORDER BY created_ts DESC LIMIT ?", (int(limit),))
    out = []
    for sid, sym, dr, ts, gr, vd, fl, rj in rows:
        try:
            rec = json.loads(rj)
        except (TypeError, ValueError):
            rec = {}
        out.append({"scenario_id": sid, "symbol": sym, "direction": dr, "created_ts": ts, "grade": gr, "verdict": vd, "flags": (fl or "").split(",") if fl else [], "record": rec})
    return out


def weekly_review(db: str, now: float, days: float = 7.0) -> Dict[str, Any]:
    """Тижневий розбір: розбори аналітика × paper-результати (scope LIVE). Лише описова статистика; правил не змінює, висновки — кандидати на незалежну перевірку."""
    from office_bridge import _fetchall

    _ensure(db)
    try:
        from office2 import paper as _PP

        _PP._ensure(db)      # LEFT JOIN потребує таблиці paper-позицій навіть у порожній БД
    except Exception:  # noqa: BLE001
        pass
    since = now - days * 86400
    rows = _fetchall(db, """SELECT a.scenario_id, a.symbol, a.direction, a.grade, a.verdict, a.flags, a.cards_json,
        p.status, p.close_reason, p.r_a, p.mfe_r, p.mae_r, p.btc, p.session, p.postmortem_json
        FROM office2_analyst a LEFT JOIN office2_paper_position p ON p.scenario_id = a.scenario_id
        WHERE a.created_ts >= ?""", (since,))
    items = []
    for r in rows:
        items.append({"id": r[0], "sym": r[1], "dir": r[2], "grade": r[3], "verdict": r[4], "flags": (r[5] or "").split(",") if r[5] else [],
                      "cards": json.loads(r[6] or "{}"), "status": r[7], "close": r[8], "r": r[9], "mfe": r[10], "mae": r[11], "btc": r[12], "session": r[13]})
    closed = [i for i in items if i["r"] is not None]

    def agg(sel):
        rs = [i["r"] for i in sel if i["r"] is not None]
        return {"n": len(sel), "closed": len(rs), "mean_r": round(sum(rs) / len(rs), 3) if rs else None,
                "tp_share": round(sum(1 for i in sel if i["r"] is not None and i["r"] > 0) / len(rs), 3) if rs else None}

    by_flag = {}
    for fl in sorted({f for i in items for f in i["flags"]}):
        by_flag[fl] = {"with": agg([i for i in items if fl in i["flags"]]), "without": agg([i for i in items if fl not in i["flags"]])}
    by_grade = {g: agg([i for i in items if i["grade"] == g]) for g in ("A", "B", "C", "X")}
    card_stats = {}
    for cid in sorted({c for i in items for c in i["cards"]}):
        card_stats[cid] = {"for": agg([i for i in items if i["cards"].get(cid) == 1]), "against": agg([i for i in items if i["cards"].get(cid) == -1])}
    return {"period_days": days, "signals": len(items), "closed": len(closed), "overall": agg(items), "by_grade": by_grade, "by_flag": by_flag, "by_card": card_stats,
            "caveat": "Описова статистика на малій вибірці; жодне правило не змінюється за одним тижнем — кандидати перевіряються на наступних незалежних спостереженнях.",
            "version": VERSION}
