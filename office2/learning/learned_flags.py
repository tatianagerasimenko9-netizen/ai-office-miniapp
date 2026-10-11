"""Shadow-позначки READY за ознаками, що пройшли незалежну перевірку (feature-study, 11.10: Brain replay 29 монет × 3 вікна × 14 днів, N=1936 рішень).
ВАЖЛИВО: це ПОЗНАЧКИ, не фільтри. Вони нічого не блокують у LIVE; їхній ефект рахується окремо на нових paper-результатах
(скільки SL було б уникнуто, скільки прибуткових входів втрачено, як змінився чистий результат). Вмикати як фільтр — лише за рішенням власниці.

Критерій відбору (заданий ДО перегляду нових даних): клітинка STABLE_NEGATIVE (однаковий знак у train і test, |середнє| ≥ 0.10 R в обох, CI з поправкою Бонферроні
не містить 0) І гірша за решту вибірки не менш ніж на 0.10 R. Загальне середнє replay теж від'ємне (−0.115 R), тому «просто від'ємна клітинка» ознакою не вважається."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

VERSION = "lf-1"

# id → (опис, предикат на features.extract(), доказ з feature-study)
RULES: Dict[str, Dict[str, Any]] = {
    "WEEKEND": {"label": "вихідні (сб–нд UTC)", "pred": lambda f: f.get("weekend") is True,
                "evidence": {"n": 622, "mean_r": -0.323, "rest_mean_r": -0.018, "train": -0.365, "test": -0.267, "source": "feature-study run 38133925197"}},
    "COST_HEAVY": {"label": "витрати ≥ 0.25 R (малий стоп)", "pred": lambda f: f.get("cost_heavy") is True,
                   "evidence": {"n": 144, "mean_r": -0.478, "rest_mean_r": -0.087, "train": -0.576, "test": -0.380, "source": "feature-study run 38133925197"}},
    "OFF_HOURS": {"label": "сесія OFF_HOURS", "pred": lambda f: f.get("session") == "OFF_HOURS",
                  "evidence": {"n": 198, "mean_r": -0.286, "rest_mean_r": -0.097, "train": -0.313, "test": -0.244, "source": "feature-study run 38133925197"}},
}
# RS_FLAT (rs_1h=FLAT, n=347, −0.219 vs −0.094) теж пройшла критерій, але потребує відносної сили до BTC на момент READY, якої немає у знімку paper-позиції: додається окремо.


def flags_for(th: Dict[str, Any], ts: float) -> List[str]:
    from office2.learning import features as FT

    try:
        f = FT.extract(th, float(ts), None, None)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for rid, r in RULES.items():
        try:
            if r["pred"](f):
                out.append(rid)
        except Exception:  # noqa: BLE001
            continue
    return out


def _effect(rows: List[Dict[str, Any]], rid: str) -> Dict[str, Any]:
    done = [x for x in rows if x.get("pnl_a") is not None]
    fl = [x for x in done if rid in (x.get("_flags") or [])]
    sl = [x for x in fl if x["pnl_a"] <= 0]
    tp = [x for x in fl if x["pnl_a"] > 0]
    base = sum(x["pnl_a"] for x in done)
    flagged = sum(x["pnl_a"] for x in fl)
    out = {"resolved": len(done), "flagged": len(fl), "sl_avoided": len(sl), "tp_lost": len(tp),
           "net_usd_all": round(base, 2), "net_usd_flagged": round(flagged, 2), "net_usd_without_flagged": round(base - flagged, 2),
           "effect_usd": round(-flagged, 2)}
    out["verdict"] = ("INSUFFICIENT: n<30 — це спостереження, не підтвердження" if len(fl) < 30 else
                      ("ПІДТВЕРДЖУЄТЬСЯ на нових даних (позначка відсіює збиток)" if flagged < 0 else "НЕ підтверджується на нових даних"))
    return out


def evaluate(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Прямий (forward) ефект позначок за paper-результатами (модель A). rows: dict з pnl_a, learned_flags (список id) — окремо за scope."""
    res: Dict[str, Any] = {"version": VERSION, "rules": {}, "note": "ефект «якби цих угод не брали»; фільтри LIVE не змінено"}
    for rid, r in RULES.items():
        e = {"label": r["label"], "evidence": r["evidence"], "by_scope": {}}
        for sc in sorted({x.get("scope") or "?" for x in rows}):
            e["by_scope"][sc] = _effect([x for x in rows if (x.get("scope") or "?") == sc], rid)
        res["rules"][rid] = e
    return res
