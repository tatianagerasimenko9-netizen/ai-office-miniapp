"""Детектор Breakout & Retest на ЗАКРИТИХ барах (без майбутнього): рівень → пробій закриттям → ретест → підтвердження відбою → SL/цілі/скасування.
Усі числа — у HYP і є ГІПОТЕЗОЮ (джерело порогів НЕ ПІДТВЕРДЖЕНО). Чиста функція, без I/O."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

HYP: Dict[str, Any] = {
    "pivot_k": 3,              # ГІПОТЕЗА: бар — свінг, якщо він екстремум серед k барів з обох боків
    "lookback": 96,            # ГІПОТЕЗА: рівень не старіший за 96 барів M15 (24 год)
    "atr_n": 14,               # стандартний ATR(14) (не поріг методики)
    "retest_window": 24,       # ГІПОТЕЗА: ретест протягом 24 барів після пробою
    "retest_tol_atr": 0.30,    # ГІПОТЕЗА: «торкання рівня» = у межах 0,30 ATR від нього
    "confirm_window": 4,       # ГІПОТЕЗА: підтвердження відбою протягом 4 барів після торкання
    "sl_buffer_atr": 0.10,     # ГІПОТЕЗА: SL за екстремумом ретесту − 0,10 ATR
    "min_risk_atr": 0.30,      # ГІПОТЕЗА: відсікає надто вузький стоп
    "max_risk_atr": 3.00,      # ГІПОТЕЗА: відсікає надто широкий стоп
    "r_targets": (1.0, 2.0, 3.0),   # ГІПОТЕЗА: запасні цілі в R, коли немає структурних
    "min_struct_target_r": 0.8,     # ГІПОТЕЗА: структурна ціль має бути не ближче 0,8R
    "min_risk_pct": None,           # ГІПОТЕЗА (варіант V2): мінімальна відстань до SL у % від входу, щоб комісія+прослизання (0,15%) не з'їдали R
}


def atr(h: Sequence[float], l: Sequence[float], c: Sequence[float], i: int, n: int) -> float:
    lo = max(1, i - n + 1)
    trs = [max(h[j] - l[j], abs(h[j] - c[j - 1]), abs(l[j] - c[j - 1])) for j in range(lo, i + 1)]
    return sum(trs) / len(trs) if trs else 0.0


def pivots(h: Sequence[float], l: Sequence[float], upto: int, k: int) -> List[Dict[str, Any]]:
    """Підтверджені свінги: індекс p підтверджений, лише коли p + k ≤ upto (немає look-ahead)."""
    out = []
    for p in range(k, upto - k + 1):
        if all(h[p] > h[p - j] and h[p] >= h[p + j] for j in range(1, k + 1)):
            out.append({"i": p, "p": float(h[p]), "type": "H"})
        if all(l[p] < l[p - j] and l[p] <= l[p + j] for j in range(1, k + 1)):
            out.append({"i": p, "p": float(l[p]), "type": "L"})
    return out


def _targets(direction: str, entry: float, risk: float, piv: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    sg = 1 if direction == "LONG" else -1
    struct = sorted((x["p"] for x in piv if sg * (x["p"] - entry) >= cfg["min_struct_target_r"] * risk), key=lambda p: sg * (p - entry))
    out: List[Dict[str, Any]] = []
    for p in struct:
        # Distinct structural price levels only: duplicate pivots are not new TPs.
        if any(p == target["p"] for target in out):
            continue
        out.append({"p": p, "src": "structure"})
        if len(out) >= 3:
            break
    for r in cfg["r_targets"]:
        if len(out) >= 3:
            break
        p = entry + sg * r * risk
        if all(abs(p - o["p"]) > 0.25 * risk for o in out):
            out.append({"p": p, "src": f"R{r:g} (ГІПОТЕЗА)"})
    out.sort(key=lambda o: sg * (o["p"] - entry))
    return out[:3]


def scan(t: Sequence[float], o: Sequence[float], h: Sequence[float], l: Sequence[float], c: Sequence[float], cfg: Optional[Dict[str, Any]] = None, start: int = 0) -> List[Dict[str, Any]]:
    """Усі завершені послідовності пробій→ретест→підтвердження на барах [start..]. Сигнал належить бару підтвердження і використовує лише бари ≤ його."""
    cfg = dict(HYP, **(cfg or {}))
    k, n = cfg["pivot_k"], len(c)
    sigs: List[Dict[str, Any]] = []
    used: set = set()
    for i in range(max(start, k * 2 + cfg["atr_n"]), n):
        a = atr(h, l, c, i, cfg["atr_n"])
        if a <= 0:
            continue
        piv = [x for x in pivots(h, l, i, k) if i - cfg["lookback"] <= x["i"]]
        # пробій на барі i: перше закриття за рівнем (попередній бар закрився по інший бік)
        for x in piv:
            key = (x["type"], x["i"])
            if key in used:
                continue
            L = x["p"]
            up = x["type"] == "H" and c[i] > L >= c[i - 1]
            dn = x["type"] == "L" and c[i] < L <= c[i - 1]
            if not (up or dn):
                continue
            # рівень уже пробивали закриттям після свінгу → не «перший» пробій
            if any((c[j] > L) if x["type"] == "H" else (c[j] < L) for j in range(x["i"] + 1, i)):
                used.add(key)
                continue
            used.add(key)
            direction = "LONG" if up else "SHORT"
            res = _follow(direction, L, i, t, o, h, l, c, cfg, piv)
            if res:
                res.update({"level": L, "level_i": x["i"], "level_ts": float(t[x["i"]]), "break_i": i, "break_ts": float(t[i])})
                sigs.append(res)
    sigs.sort(key=lambda s: s["confirm_i"])
    return sigs


def _follow(direction: str, L: float, bi: int, t, o, h, l, c, cfg, piv) -> Optional[Dict[str, Any]]:
    """Після пробою на барі bi: ретест (торкання зони рівня без закриття назад за рівень) → підтвердження відбою. Закриття назад за рівень = скасування."""
    sg = 1 if direction == "LONG" else -1
    n = len(c)
    for j in range(bi + 1, min(n, bi + 1 + cfg["retest_window"])):
        a = atr(h, l, c, j, cfg["atr_n"])
        tol = cfg["retest_tol_atr"] * a
        if sg * (c[j] - L) < 0:
            return None                                   # скасування: закриття назад за рівнем до підтвердження
        touched = (l[j] <= L + tol) if sg > 0 else (h[j] >= L - tol)
        if not touched:
            continue
        ext = l[j] if sg > 0 else h[j]
        for q in range(j, min(n, j + 1 + cfg["confirm_window"])):
            if sg * (c[q] - L) < 0:
                return None
            ext = min(ext, l[q]) if sg > 0 else max(ext, h[q])
            bounce = (c[q] > o[q]) if sg > 0 else (c[q] < o[q])
            if bounce and sg * (c[q] - L) > 0:
                aq = atr(h, l, c, q, cfg["atr_n"])
                entry = float(c[q])
                sl = ext - cfg["sl_buffer_atr"] * aq if sg > 0 else ext + cfg["sl_buffer_atr"] * aq
                risk = abs(entry - sl)
                if risk < cfg["min_risk_atr"] * aq or risk > cfg["max_risk_atr"] * aq or sg * (entry - sl) <= 0:
                    return None
                if cfg.get("min_risk_pct") and risk / entry < cfg["min_risk_pct"]:
                    return None
                tg = _targets(direction, entry, risk, [x for x in piv], cfg)
                return {"direction": direction, "retest_i": j, "retest_ts": float(t[j]), "confirm_i": q, "confirm_ts": float(t[q]), "entry": entry, "sl": float(sl),
                        "risk": float(risk), "atr": float(aq), "retest_extreme": float(ext), "targets": tg}
        return None
    return None
