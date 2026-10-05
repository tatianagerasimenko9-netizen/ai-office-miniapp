#!/usr/bin/env python3
"""Аудит повторних READY / дублікатів / lifecycle за експортом БД (research-only, не торкається runtime).

Джерело правди — таблиця office_events (експорт data/research/ready_events_*.json), НЕ повідомлення Telegram.
Розділяє: нова ідея / повтор після SL / READY, видане при ще активній попередній ідеї / дубль SIGNAL_RESULT /
конфлікт результатів / дубль Telegram-доставки (за прогалинами в msg_id).

Результат плану береться з двох джерел (обидва показуються окремо):
  * lifecycle 1m: SCENARIO_MILESTONE (ENTRY / TP1 / SL) — лише для планів, що мали ENTRY після запуску milestone;
  * SIGNAL_RESULT: офіційна 15m-симуляція (консервативна, зміщена) — перший запис на sid.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

REPEAT_WINDOW = 24 * 3600.0


def fts(x: float) -> str:
    return datetime.fromtimestamp(float(x), timezone.utc).strftime("%m-%d %H:%M")


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (c - h) / d), min(1.0, (c + h) / d)


def load(path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    d = json.load(open(path))
    plans = [dict(zip(d["plan_cols"], r)) for r in d["plans"]]
    events = [dict(zip(d["event_cols"], r)) for r in d["events"]]
    results = [dict(zip(d["result_cols"], r)) for r in d.get("results", [])]
    atr = {r[0]: (r[1], r[2]) for r in d.get("atr", [])}
    return plans, events, results, atr


def build(plans: List[Dict[str, Any]], events: List[Dict[str, Any]], results: List[Dict[str, Any]], atr: Dict[int, Tuple[float, float]]) -> Dict[str, Any]:
    ready: Dict[str, Dict[str, Any]] = {}
    plan_rows: Counter = Counter()
    for p in plans:
        if p["rejected"] == "true":
            continue
        plan_rows[p["sid"]] += 1
        if p["sid"] in ready:
            continue
        parts = p["sid"].split("|")
        ready[p["sid"]] = {"sid": p["sid"], "sym": parts[1], "dir": parts[2], "ct": float(p["ct"]), "entry": float(p["entry"]), "sl": float(p["sl"]),
                           "tp1": float(p["tp1"]), "msg": p["msg_id"], "risk": float(p["risk_pct"]) if p["risk_pct"] else abs(float(p["entry"]) - float(p["sl"])) / float(p["entry"]) * 100,
                           "tags": p["tags"], "align": p["align"], "n_ev": p["n_evidence"], "phase": p["phase_sigma"]}
    ms: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    res: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for x in results:
        res[x["sid"]].append(x)
    sent: Counter = Counter()
    for e in events:
        if e["type"] == "SCENARIO_MILESTONE":
            ms[(e["sid"], e["level"])].append(e)
        elif e["type"] == "TELEGRAM_READY_SENT":
            sent[e["sid"]] += 1
    for sid, r in ready.items():
        ent = ms.get((sid, "ENTRY"))
        r["entered"] = bool(ent)
        r["entry_evt_ts"] = datetime.fromisoformat(ent[0]["ts"]).timestamp() if ent else None
        slm, tpm = ms.get((sid, "SL")), ms.get((sid, "TP1"))
        r["lc"] = "SL" if slm and (not tpm or slm[0]["id"] < tpm[0]["id"]) else "TP1" if tpm else None
        r["lc_ts"] = float(((slm or tpm)[0]["touched_ts"] or 0)) if (slm or tpm) else None
        rr = [x for x in res.get(sid, []) if x["rejected"] == "false" and abs(float(x["confirmed_ts"]) - r["ct"]) < 2.0]
        r["res"] = rr[0]["outcome"] if rr else None
        r["res_n"] = len(rr)
        r["res_conflict"] = len({x["outcome"] for x in rr}) > 1
        r["res_all"] = [x["outcome"] for x in rr]
        r["ttr"] = float(rr[0]["ttr_sec"]) if rr and rr[0]["ttr_sec"] else None
        r["t_res"] = r["ct"] + r["ttr"] if r["ttr"] is not None else None
        r["mfe"] = float(rr[0]["mfe_pct"]) if rr and rr[0]["mfe_pct"] else None
        r["mae"] = float(rr[0]["mae_pct"]) if rr and rr[0]["mae_pct"] else None
        r["atr15"], r["atr1h"] = atr.get(next((int(p["id"]) for p in plans if p["sid"] == sid and p["rejected"] == "false"), -1), (None, None))
    return {"ready": ready, "plan_rows": plan_rows, "sent": sent, "res": res, "ms": ms}


def outcome_of(r: Dict[str, Any]) -> Optional[str]:
    """Клас результату офіційної 15m-симуляції: SL / TP (TP1..TP3) / None (відкрита, таймаут, не виконана)."""
    o = r["res"]
    if o == "STOP":
        return "SL"
    if o in ("TP1", "TP2", "TP3"):
        return "TP"
    return None


def outcome_h(r: Dict[str, Any], H: float, now: float) -> Optional[str]:
    """Фіксований горизонт H сек: SL / TP / нічого; None якщо план молодший за H (ще не можна судити)."""
    if r["ct"] + H > now:
        return None
    o = outcome_of(r)
    if o and r["ttr"] is not None and r["ttr"] <= H:
        return o
    return "нічого"


BURST_MIN = 5.0


def chains(ready: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    by: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in ready.values():
        by[(r["sym"], r["dir"])].append(r)
    out: List[Dict[str, Any]] = []
    for lst in by.values():
        lst.sort(key=lambda x: x["ct"])
        for i, r in enumerate(lst):
            prev = lst[i - 1] if i else None
            row = dict(r)
            row["idx"] = i
            row["gap_min"] = (r["ct"] - prev["ct"]) / 60 if prev else None
            # стан попередньої ідеї НА МОМЕНТ нового READY (час результату = ct + time_to_result)
            if prev is None:
                row["cls"] = "перша"
            elif row["gap_min"] < BURST_MIN:
                row["cls"] = "пачка (<5 хв після попередньої)"
            else:
                po = outcome_of(prev)
                known = prev["t_res"] is not None and prev["t_res"] <= r["ct"]
                if po == "SL" and known:
                    row["cls"] = "після SL"
                elif po == "TP" and known:
                    row["cls"] = "після TP"
                else:
                    row["cls"] = "попередня ще не вирішена"
            row["prev_open_lc"] = bool(prev and prev.get("entry_evt_ts") and prev["entry_evt_ts"] <= r["ct"] and (prev["lc_ts"] is None or prev["lc_ts"] > r["ct"]))
            row["since_sl_min"] = (r["ct"] - prev["t_res"]) / 60 if prev and row["cls"] == "після SL" else None
            row["same_sl"] = bool(prev and abs(prev["sl"] - r["sl"]) / r["sl"] < 0.0005)
            row["tags_changed"] = bool(prev and prev["tags"] != r["tags"])
            row["prev_sid"] = prev["sid"] if prev else None
            out.append(row)
    return sorted(out, key=lambda x: x["ct"])


def rate(rows: List[Dict[str, Any]], H: Optional[float] = None, now: float = 0.0) -> str:
    d = [x for x in ((outcome_h(r, H, now) if H else outcome_of(r)) for r in rows) if x in ("SL", "TP")]
    n = len(d)
    k = sum(1 for x in d if x == "TP")
    if not n:
        return "немає даних (не перевірено)"
    lo, hi = wilson(k, n)
    return f"TP {k}/{n} = {k / n * 100:.0f}% (95% ІВ {lo * 100:.0f}–{hi * 100:.0f}%); SL {n - k}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", required=True)
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    plans, events, results, atr = load(a.events)
    b = build(plans, events, results, atr)
    ready = b["ready"]
    ch = chains(ready)
    now = max(float(p["ct"]) for p in plans)
    L: List[str] = []
    P = L.append
    P("# Аудит повторів / дублікатів / lifecycle (джерело правди: office_events)\n")
    P(f"Вікно: {fts(min(float(p['ct']) for p in plans))}–{fts(now)} UTC. SIGNAL_PLAN: {len(plans)} рядків; READY (rejected=false): {sum(b['plan_rows'].values())} рядків, "
      f"{len(ready)} унікальних sid; пар symbol+direction: {len({(r['sym'], r['dir']) for r in ready.values()})}.\n")

    P("## 1. Дублікати за типами (БД)\n")
    mp = [s for s, n in b["plan_rows"].items() if n > 1]
    P(f"- Той самий sid записаний у SIGNAL_PLAN як READY кілька разів: {len(mp)} ({', '.join(mp[:5])}).")
    rd = [x for x in results if x["rejected"] == "false"]
    rj = [x for x in results if x["rejected"] == "true"]
    P(f"- SIGNAL_RESULT: {len(results)} записів = {len(rd)} для READY + {len(rj)} для ВІДХИЛЕНИХ планів (rejected=true) під тим самим sid — їх не можна змішувати з READY.")
    per: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    for x in rd:
        per[(x["sid"], x["confirmed_ts"])].append(x["outcome"])
    dup = {k: v for k, v in per.items() if len(v) > 1}
    cf = {k: v for k, v in dup.items() if len(set(v)) > 1}
    P(f"- READY-результатів: унікальних (sid, confirmed_ts) {len(per)}; з дубльованими записами {len(dup)} (зайвих записів {sum(len(v) - 1 for v in dup.values())}); "
      f"з конфліктом результатів {len(cf)}: {dict(Counter('/'.join(sorted(set(v))) for v in cf.values()))}.")
    P(f"- TELEGRAM_READY_SENT: sid з кількома записами: {sum(1 for v in b['sent'].values() if v > 1)}; записів усього {sum(b['sent'].values())} (логується з 04.10 20:10 UTC).")
    ids = sorted(int(r["msg"]) for r in ready.values() if r["msg"])
    gaps = [(x, y) for x, y in zip(ids, ids[1:]) if y - x > 1]
    P(f"- Прогалини в confirm_msg_id: {len(gaps)} (повідомлення, яких немає в БД: інші повідомлення Office, лайфсайкл або дубль доставки).")
    seen: Dict[Tuple[str, str, float, float, float], List[Dict[str, Any]]] = defaultdict(list)
    for r in ready.values():
        seen[(r["sym"], r["dir"], r["entry"], r["sl"], r["tp1"])].append(r)
    lit = [v for v in seen.values() if len(v) > 1]
    P(f"- Літеральні дублі READY (той самий symbol/dir/entry/SL/TP1, різні sid): {len(lit)} груп: " + "; ".join(f"{v[0]['sym']} {v[0]['dir']} {', '.join(fts(x['ct']) for x in v)}" for v in lit[:5]))

    P("\n## 2. Класи READY на момент видачі (за попередньою ідеєю тієї ж пари symbol+direction)\n")
    cnt = Counter(r["cls"] for r in ch)
    P("| Клас | N | результат (15m, усі вирішені) | фікс. 12 год |\n|---|---|---|---|")
    for k in ("перша", "пачка (<5 хв після попередньої)", "після SL", "після TP", "попередня ще не вирішена"):
        rows = [r for r in ch if r["cls"] == k]
        P(f"| {k} | {cnt[k]} | {rate(rows)} | {rate(rows, 12 * 3600.0, now)} |")
    aft = [r for r in ch if r["cls"] == "після SL"]
    if aft:
        P(f"\nПісля SL: той самий рівень SL (±0,05%) у {sum(1 for r in aft if r['same_sl'])} із {len(aft)}; теги підтвердження змінились у {sum(1 for r in aft if r['tags_changed'])} із {len(aft)}.")
        d = sorted(r["since_sl_min"] for r in aft)
        P(f"Час від SL до нового READY: p25 {d[len(d) // 4]:.0f} хв, p50 {d[len(d) // 2]:.0f} хв, p75 {d[3 * len(d) // 4]:.0f} хв (N={len(d)}).")
        P("\n| symbol | напрям | READY | через (хв) | той самий SL | теги змінились | результат нового (lifecycle / 15m) |\n|---|---|---|---|---|---|---|")
        for r in aft[:40]:
            P(f"| {r['sym'].replace('USDT', '')} | {r['dir']} | {fts(r['ct'])} | {round(r['since_sl_min'])} | {'так' if r['same_sl'] else 'ні'} | {'так' if r['tags_changed'] else 'ні'} | {r['lc'] or '—'} / {r['res'] or '—'} |")
    pairs = Counter((r["sym"], r["dir"]) for r in ch)
    multi = [k for k, v in pairs.items() if v > 1]
    P(f"\nПар symbol+direction з ≥2 READY: {len(multi)} із {len(pairs)}; READY у таких парах: {sum(pairs[k] for k in multi)} із {len(ch)}.")

    P("\n## 3. Три зрізи (результат: офіційна 15m-симуляція, не 1m replay)\n")
    first = [r for r in ch if r["cls"] == "перша"]
    indep = [r for r in ch if r["cls"] in ("перша", "після TP") or (r["gap_min"] is not None and r["gap_min"] >= 24 * 60)]
    for name, rows in (("Усі READY", ch), ("Перша READY на symbol+direction у вікні", first), ("«Незалежна ідея» (ПРОКСІ: перша, після TP або ≥24 год; structural reset не зберігається)", indep)):
        P(f"- {name}: N={len(rows)}; вирішені: {rate(rows)}; фікс. 12 год: {rate(rows, 12 * 3600.0, now)}")
    P("\nВікно ≈ 31 год: оцінки грубі; висновків про cooldown не роблю.")

    P("\n## 4. Lifecycle-результат (1m SCENARIO_MILESTONE) для планів з ENTRY\n")
    ent = [r for r in ready.values() if r["entered"]]
    c = Counter(r["lc"] or "відкрита" for r in ent)
    P(f"- Плани з ENTRY: {len(ent)}; TP1: {c['TP1']}, SL: {c['SL']}, ще відкриті: {c['відкрита']}.")
    kk = Counter()
    for r in ch:
        if r["entered"] and r["lc"]:
            kk[("перша" if r["cls"] == "перша" else "повтор", r["lc"])] += 1
    P(f"- Перша READY: TP1 {kk[('перша', 'TP1')]}, SL {kk[('перша', 'SL')]}; повторні: TP1 {kk[('повтор', 'TP1')]}, SL {kk[('повтор', 'SL')]}.")

    po = [r for r in ch if r["prev_open_lc"]]
    P(f"- READY, виданих коли попередня ідея тієї ж пари вже була В ПОЗИЦІЇ за lifecycle (ENTRY був, TP1/SL ще ні): {len(po)}; "
      + ", ".join(f"{r['sym'].replace('USDT', '')} {fts(r['ct'])}" for r in po[:10]))
    both = [r for r in ready.values() if r["lc"] and r["res"] and r["lc_ts"] and r["t_res"]]
    agree = [r for r in both if (r["lc"] == "SL") == (outcome_of(r) == "SL")]
    dt = sorted((r["t_res"] - r["lc_ts"]) / 60 for r in both)
    P(f"- Звірка двох симуляторів (lifecycle 1m проти офіційної 15m): планів з обома результатами {len(both)}; клас збігається в {len(agree)}; "
      f"різниця часу результату (15m − lifecycle), хв: min {dt[0]:.0f}, p10 {dt[len(dt) // 10]:.0f}, p50 {dt[len(dt) // 2]:.0f}, p90 {dt[9 * len(dt) // 10]:.0f}, max {dt[-1]:.0f}; "
      f"розбіжність більш ніж на 60 хв: {sum(1 for x in dt if abs(x) > 60)} планів: " + ", ".join(f"{r['sym'].replace('USDT', '')} {(r['t_res'] - r['lc_ts']) / 60:.0f} хв" for r in both if abs(r['t_res'] - r['lc_ts']) > 3600) if both else "- Звірка двох симуляторів: немає даних.")
    P("\n## 5. Перевірені випадки\n")
    for sym in ("IOUSDT", "KAITOUSDT", "JUPUSDT", "ONDOUSDT", "ETCUSDT"):
        for r in ch:
            if r["sym"] == sym:
                P(f"- {sym} {r['dir']} …{r['sid'][-8:]} READY {fts(r['ct'])} вхід {r['entry']} SL {r['sl']:.6g} ({r['risk']:.2f}%) msg {r['msg']} клас «{r['cls']}»; lifecycle {r['lc'] or '—'} {fts(r['lc_ts']) if r['lc_ts'] else ''}; 15m {r['res_all'] or '—'}")

    P("\n## 6. Короткі стопи: stop% / ATR15 / ATR1h / результат (лише плани із заморожених свічок gate.chart)\n")
    P("ATR15 = середнє TR останніх 14 закритих свічок 15m; ATR1h = те саме на годинних барах зі свічок 15m (13 барів). Зі знімка READY, без lookahead.\n")
    P("| symbol | READY | стоп % | стоп/ATR15 | стоп/ATR1h | TP1/SL | 15m результат | до результату (хв) | 3 год | 6 год | 12 год | 24 год |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
    rows6 = [r for r in ch if r["atr15"]]
    rows6.sort(key=lambda r: r["risk"])
    def hz(r: Dict[str, Any], h: float) -> str:
        if r["ct"] + h * 3600 > now:
            return "·"
        o = outcome_h(r, h * 3600.0, now)
        return o or "·"
    for r in rows6:
        sd = abs(r["entry"] - r["sl"])
        td = abs(r["tp1"] - r["entry"])
        P(f"| {r['sym'].replace('USDT', '')} | {fts(r['ct'])} | {r['risk']:.2f} | {sd / r['atr15']:.2f} | {('%.2f' % (sd / r['atr1h'])) if r['atr1h'] else '—'} | {td / sd:.2f} | {r['res'] or '—'} | "
          f"{'—' if r['ttr'] is None else round(r['ttr'] / 60)} | {hz(r, 3)} | {hz(r, 6)} | {hz(r, 12)} | {hz(r, 24)} |")
    P("\n### Групи за стопом (ті ж плани)\n")
    P("| Група | N | вирішені 15m | стоп/ATR15 медіана | база «блукання» P(TP1 раніше SL)=r/(r+t) |\n|---|---|---|---|---|")
    for name, f in (("стоп < 0,7%", lambda r: r["risk"] < 0.7), ("0,7–1,2%", lambda r: 0.7 <= r["risk"] < 1.2), ("≥ 1,2%", lambda r: r["risk"] >= 1.2),
                    ("стоп < 1,5 ATR15", lambda r: abs(r["entry"] - r["sl"]) / r["atr15"] < 1.5), ("1,5–3 ATR15", lambda r: 1.5 <= abs(r["entry"] - r["sl"]) / r["atr15"] < 3),
                    ("≥ 3 ATR15", lambda r: abs(r["entry"] - r["sl"]) / r["atr15"] >= 3)):
        g = [r for r in rows6 if f(r)]
        m = sorted(abs(r["entry"] - r["sl"]) / r["atr15"] for r in g)
        rw = sum(abs(r["entry"] - r["sl"]) / (abs(r["entry"] - r["sl"]) + abs(r["tp1"] - r["entry"])) for r in g) / len(g) if g else 0.0
        P(f"| {name} | {len(g)} | {rate(g)} | {m[len(m) // 2]:.2f} | {rw * 100:.1f}% |" if g else f"| {name} | 0 | — | — | — |")
    out = "\n".join(L)
    print(out)
    if a.md:
        open(a.md, "w").write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
