"""READ-ONLY навчання й експорт моделі TD-V1 у office_td/model_v1.json (запускається у GitHub Actions на історії Binance).
Навчання: 2022–2023 (як у перевіреній схемі); поріг сигналу = 97-й перцентиль оцінок на 2024 (поза навчанням); далі друкуються підсумки ФІКСОВАНОГО порогу по 2024/2025/2026.
Використання: td_export_model.py CANDLES_DIR SYMS COST OUT_JSON"""
import sys, os, json
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "docs", "handoff", "br-profitability", "strategy_search"))
CD, SYMS, COST, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
sys.argv = ["x", CD, SYMS, COST]
import ml_discover2 as md
from sklearn.ensemble import HistGradientBoostingRegressor
from office_td import model as tm

def main():
    b = md.load_h1("BTCUSDT"); bc = b.close.to_numpy(float)
    btc = pd.DataFrame({"r4": np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]], "r24": np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]}, index=b.open_time.to_numpy(float))
    parts = [r for s in md.SYMS for r in [md.rows_for(s, md.load_h1(s), btc)] if r is not None]
    df = pd.concat(parts).reset_index(drop=True); df["year"] = pd.to_datetime(df.t, unit="s").dt.year
    X = [c for c in df.columns if c not in ("t", "r", "side", "sym", "year", "ent", "sl")]
    tr, va = df[df.year <= 2023], df[df.year == 2024]
    m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=250, min_samples_leaf=500, l2_regularization=5.0, random_state=7).fit(tr[X], tr.r)
    thr = float(np.quantile(m.predict(va[X]), 0.97))
    spec = tm.export_sklearn(m, X, thr, meta={"trained": "2022-2023", "threshold_from": "2024, 97-й перцентиль", "cost": float(COST), "symbols": md.SYMS})
    mm = tm.Model(spec)
    samp = df.sample(3000, random_state=1); a = m.predict(samp[X]); bb = np.array([mm.predict_row(list(r)) for r in samp[X].to_numpy()])
    print("перевірка експорту: макс. різниця sklearn vs чистий Python =", float(np.abs(a - bb).max())); assert np.abs(a - bb).max() < 1e-4
    with open(OUT, "w", encoding="utf-8") as f: json.dump(spec, f, ensure_ascii=False, separators=(",", ":"))
    print(f"модель записано: {OUT}, {os.path.getsize(OUT)//1024} КБ, дерев {len(spec['trees'])}, ознак {len(X)}, поріг {thr:.4f}")
    print(f"\nФІКСОВАНИЙ поріг {thr:.4f} (із 2024); комісія {float(COST)*100:.2f}%; H1-база, дедуплікація 12 год; $ при $10 ризику на угоду:")
    for y in (2024, 2025, 2026):
        z = df[df.year == y].copy(); z["s"] = m.predict(z[X]); sel = md.dedupe(z[z.s >= thr])
        print(f"   {y}: сигналів {len(sel)} ({len(sel)/ (365 if y<2026 else 300):.1f}/добу), R/угоду {sel.r.mean():+.3f}, $ {10*sel.r.sum():+,.0f}")
    print("\n##### ПІДСУМОК td_export завершено")
main()
