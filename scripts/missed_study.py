#!/usr/bin/env python3
"""Пропущені можливості: які структурні рухи (визначені ПО СВІЧКАХ ретроспективно, без стратегічних порогів власниці) система мала чи не мала в картках.
Визначення руху — ТЕХНІЧНА ГІПОТЕЗА (не правило з джерел): 15m-півот (фрактал ±6 барів), після якого за ≤8 год ціна проходить ≥K·ATR(H1) у бік руху,
не відкотившись від півота проти руху більше ніж на 1·ATR(H1) (тобто «стоп 1 ATR за півотом, ціль K ATR» існував ретроспективно). K=2,3,4 для чутливості.
Покриття: READY (доставлені) та картки радара (WATCH/BLOCKED) того ж символу й напрямку за вікном [півот−4 год; півот+3 год] = «заздалегідь/вчасно»,
далі до кінця руху = «пізно». Ретроспективні рухи НЕ є торговим сигналом — це міра охоплення, не обіцянка прибутку.
Використання: python scripts/missed_study.py scripts/fixtures/cards_2026-10-12.txt [OUT.json]"""
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import binance_vision_fetch as BV  # noqa: E402

UNIVERSE = ("BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT DOGEUSDT ADAUSDT AVAXUSDT LINKUSDT DOTUSDT LTCUSDT NEARUSDT OPUSDT SUIUSDT UNIUSDT ETCUSDT FILUSDT HBARUSDT TIAUSDT SEIUSDT "
            "1000PEPEUSDT 1000SHIBUSDT FETUSDT RUNEUSDT ALGOUSDT WLDUSDT ONDOUSDT JUPUSDT").split()
FRACTAL, HORIZON, PRE, POST = 6, 32, 4 * 3600, 3 * 3600


def parse_cards(path):
    txt = Path(path).read_text()
    radar, ready = [], []
    for line in txt.splitlines():
        if line.startswith("RADAR="):
            for it in line[6:].split(";"):
                p = it.split(",")
                if len(p) >= 5:
                    radar.append({"sym": p[0] + "USDT", "dir": "LONG" if p[1] == "L" else "SHORT", "ts": int(p[2]), "kind": p[3], "paper": p[4], "r": float(p[5]) if len(p) > 5 and p[5] else None})
        elif line.startswith("READY="):
            for it in line[6:].split(";"):
                p = it.split(",")
                if len(p) >= 4:
                    ready.append({"sym": p[0] + "USDT", "dir": "LONG" if p[1] == "L" else "SHORT", "ts": int(p[2])})
    return radar, ready


def atr_h1(m15):
    """ATR(14) по H1, побудований із 15m; значення на кожен 15m-бар (лише закриті H1 до цього бару)."""
    n = len(m15["c"]) // 4 * 4
    h = m15["h"][:n].reshape(-1, 4).max(1)
    l = m15["l"][:n].reshape(-1, 4).min(1)
    c = m15["c"][:n].reshape(-1, 4)[:, -1]
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    a = np.full(len(tr), np.nan)
    for i in range(14, len(tr)):
        a[i] = tr[i - 13:i + 1].mean()
    out = np.full(len(m15["c"]), np.nan)
    for i in range(len(a)):
        out[i * 4:(i + 1) * 4] = a[i - 1] if i > 0 else np.nan     # лише ЗАКРИТИЙ попередній H1
    return out


def find_moves(m15, k):
    h, l, t = m15["h"], m15["l"], m15["t"]
    atr = atr_h1(m15)
    moves, i, n = [], FRACTAL, len(t)
    while i < n - HORIZON:
        a = atr[i]
        if not (a == a) or a <= 0:
            i += 1
            continue
        found = False
        if l[i] == l[i - FRACTAL:i + FRACTAL + 1].min():            # півот-низ → LONG
            ext, j_end, ok = l[i], i, False
            for j in range(i + 1, min(n, i + HORIZON + 1)):
                if l[j] < l[i] - 1.0 * a:
                    break
                if h[j] - l[i] >= k * a:
                    ok = True
                    j_end = j
                    break
            if ok:
                moves.append({"t0": float(t[i]), "t1": float(t[j_end]), "dir": "LONG", "a": float(a), "px": float(l[i])})
                i, found = j_end, True
        if not found and h[i] == h[i - FRACTAL:i + FRACTAL + 1].max():   # півот-верх → SHORT
            ok, j_end = False, i
            for j in range(i + 1, min(n, i + HORIZON + 1)):
                if h[j] > h[i] + 1.0 * a:
                    break
                if h[i] - l[j] >= k * a:
                    ok, j_end = True, j
                    break
            if ok:
                moves.append({"t0": float(t[i]), "t1": float(t[j_end]), "dir": "SHORT", "a": float(a), "px": float(h[i])})
                i, found = j_end, True
        if not found:
            i += 1
    return moves


def cover(mv, cards, sym):
    best = None
    for c in cards:
        if c["sym"] != sym or c["dir"] != mv["dir"]:
            continue
        if mv["t0"] - PRE <= c["ts"] <= mv["t0"] + POST:
            return "вчасно", c
        if mv["t0"] + POST < c["ts"] <= mv["t1"]:
            best = best or ("пізно", c)
    return best or ("нема", None)


def main(cards_path, out="missed_study.json"):
    radar, ready = parse_cards(cards_path)
    t_ready0 = min(r["ts"] for r in ready)
    t_radar0 = min(r["ts"] for r in radar)
    d1 = date(2026, 10, 11)
    d0 = datetime.fromtimestamp(t_ready0, timezone.utc).date()
    L = []
    P = L.append
    P(f"# Пропущені можливості (ретроспективна міра охоплення) · READY з {d0}, радар з {datetime.fromtimestamp(t_radar0, timezone.utc):%d.%m %H:%M} UTC · свічки до {d1} 23:59 UTC")
    res = {}
    data = {}
    for s in UNIVERSE:
        a = BV.fetch(s, "15m", d0 - timedelta(days=3), d1)
        if a:
            data[s] = a
    for k in (2.0, 3.0, 4.0):
        moves_all = []
        for s, a in data.items():
            for mv in find_moves(a, k):
                if mv["t0"] >= t_ready0 and mv["t1"] <= datetime(2026, 10, 12, tzinfo=timezone.utc).timestamp():
                    mv["sym"] = s
                    moves_all.append(mv)
        cr, cd = Counter(), Counter()
        for mv in moves_all:
            c1, _ = cover(mv, ready, mv["sym"])
            cr[c1] += 1
            if mv["t0"] >= t_radar0:
                c2, card = cover(mv, radar + ready, mv["sym"])
                cd[c2] += 1
        n, nr = len(moves_all), sum(cd.values())
        P(f"\n## K={k:g} ATR(H1) · рухів у вікні READY: {n}")
        P(f"READY доставлено вчасно/пізно/нема: {cr['вчасно']}/{cr['пізно']}/{cr['нема']}  (recall вчасно {100.0 * cr['вчасно'] / max(1, n):.0f}%, з пізніми {100.0 * (cr['вчасно'] + cr['пізно']) / max(1, n):.0f}%)")
        if nr:
            P(f"З початку радара (рухів {nr}): READY+радар вчасно/пізно/нема: {cd['вчасно']}/{cd['пізно']}/{cd['нема']}")
        res[str(k)] = {"moves": n, "ready": dict(cr), "radar_window": dict(cd)}
        if k == 3.0:
            by_dir = Counter(m["dir"] for m in moves_all)
            P(f"Напрями рухів: {dict(by_dir)}; доставлених READY за той самий період: LONG {sum(1 for r in ready if r['dir'] == 'LONG')}, SHORT {sum(1 for r in ready if r['dir'] == 'SHORT')}")
            miss = [m for m in moves_all if m["t0"] >= t_radar0 and cover(m, radar + ready, m["sym"])[0] == "нема"]
            P(f"Рухи K=3 у вікні радара БЕЗ жодної картки (WATCH/BLOCKED/READY): {len(miss)}")
            for m in sorted(miss, key=lambda x: x["t0"])[:25]:
                P(f"  {m['sym']:<12} {m['dir']:<5} {datetime.fromtimestamp(m['t0'], timezone.utc):%d.%m %H:%M}→{datetime.fromtimestamp(m['t1'], timezone.utc):%H:%M}  {abs(m['px']) and (k * m['a'] / m['px'] * 100):.2f}% від півота")
            late = [(m, cover(m, radar + ready, m["sym"])) for m in moves_all if m["t0"] >= t_radar0]
            kinds = Counter()
            for m, (c, card) in late:
                if card:
                    kinds[(c, card.get("kind", "R"))] += 1
            P("Картки, що охопили рухи K=3 у вікні радара (стан/тип): " + ", ".join(f"{a}/{b}: {v}" for (a, b), v in sorted(kinds.items())))
    # прецизійність: частка карток радара, що збіглися з рухом K=3 (вчасно)
    P("\n## Прецизійність карток: частка WATCH/BLOCKED/READY, за якими ретроспективно був рух K=3 того ж напрямку у наступні 8 год")
    mv3 = defaultdict(list)
    for s, a in data.items():
        for mv in find_moves(a, 3.0):
            mv3[(s, mv["dir"])].append(mv)

    def hit(c):
        for mv in mv3.get((c["sym"], c["dir"]), []):
            if mv["t0"] - PRE <= c["ts"] <= mv["t0"] + POST:
                return True
        return False
    T_END = datetime(2026, 10, 11, 16, tzinfo=timezone.utc).timestamp()

    def base_prob(c, t_a, t_b):
        """Імовірність випадкового збігу: частка часу [t_a,t_b], коли для (символ,напрям) діє вікно руху K=3 (об'єднання вікон)."""
        wins = sorted((mv["t0"] - PRE, mv["t0"] + POST) for mv in mv3.get((c["sym"], c["dir"]), []))
        tot, cur_a, cur_b = 0.0, None, None
        for a_, b_ in wins:
            a_, b_ = max(a_, t_a), min(b_, t_b)
            if b_ <= a_:
                continue
            if cur_b is None or a_ > cur_b:
                if cur_b is not None:
                    tot += cur_b - cur_a
                cur_a, cur_b = a_, b_
            else:
                cur_b = max(cur_b, b_)
        if cur_b is not None:
            tot += cur_b - cur_a
        return tot / max(1.0, t_b - t_a)
    for lab, cards in (("WATCH", [c for c in radar if c["kind"] == "W"]), ("BLOCKED лімiт 3 SL", [c for c in radar if c["kind"] == "L"]), ("BLOCKED кластер ALT", [c for c in radar if c["kind"] == "C"]), ("READY", ready)):
        sub = [c for c in cards if c["ts"] <= datetime(2026, 10, 11, 16, tzinfo=timezone.utc).timestamp()]
        if sub:
            t_a = t_ready0 if lab == "READY" else t_radar0
            exp = sum(base_prob(c, t_a, T_END) for c in sub)
            P(f"{lab:<22} карток {len(sub):<4} зі збігом з рухом K=3: {sum(1 for c in sub if hit(c))} ({100.0 * sum(1 for c in sub if hit(c)) / len(sub):.0f}%); очікувано за ВИПАДКОВОГО часу: {exp:.1f} ({100.0 * exp / len(sub):.0f}%)")
    txt = "\n".join(L)
    print(txt)
    Path(out).write_text(json.dumps({"report": txt, "summary": res}, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "missed_study.json")
