#!/usr/bin/env python3
"""Linear Regression Channel: математика Office = еталон Pine; логіка подій Pine (еталон) перевірена на тестових послідовностях;
відсутні в Office можливості позначені (MISSING) і не вдають, що існують."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrc_parity as lp  # noqa: E402
import office_regression_channel as oc  # noqa: E402

FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


# 1) математика: slope, intercept, endy, dev, межі — збігаються з еталоном на всіх синтетичних послідовностях
for kind in lp.KINDS:
    closes = lp.seq(kind)
    for end in range(99, len(closes), 40):
        d = lp.compare_window(closes[end - 99: end + 1])
        check(max(d.values()) < 1e-9, f"{kind} end={end}: розбіжність {max(d.values()):.2e}")

# 2) події Pine на еталоні (поведінка оригіналу)
H = lp.pine_series(lp.seq("H_up_channel_down_break"))
brk = [r for r in H if r["ooc"] == 0]
check(brk, "H: у висхідному каналі закриття нижче нижньої межі дає outofchannel=0")
check(all(r["ooc"] in (0, -1) for r in H), "H: для висхідного каналу значення лише 0 або -1")
first = brk[0]
check(first["kept_broken"] and first["kept_broken"]["line_index"] == 0 and first["kept_broken"]["which"] == "нижня",
      f"H: на першому барі пробою лишається ОДНА лінія — нижня (синій пунктир): {first['kept_broken']}")
check(all(r["kept_broken"] is None for r in brk[1:]), "H: на наступних барах пробою стара лінія вже не зберігається (лише на переході -1 → x)")
I = lp.pine_series(lp.seq("I_down_channel_up_break"))
brk2 = [r for r in I if r["ooc"] == 2]
check(brk2 and brk2[0]["kept_broken"]["line_index"] == 2 and brk2[0]["kept_broken"]["which"] == "верхня", "I: у низхідному каналі пробій вгору зберігає верхню лінію")
import numpy as np  # noqa: E402

t_ = np.arange(300, dtype=float)
J = lp.pine_series(list(100 + 0.1 * t_ + np.where(t_ > 250, 0.9 * (t_ - 250), 0)))   # без шуму: інакше випадкові виходи за ±2σ теж дають пробій (так працює й оригінал)
check(all(r["ooc"] == -1 for r in J), "J: рух У НАПРЯМКУ каналу (вгору у висхідному) пробоєм не вважається (асиметричне правило)")
A = lp.pine_series(list(100 + 0.1 * t_))
check(not any(r["ooc"] >= 0 for r in A), "A: рівномірний ріст без шуму — пробою немає")
An = lp.pine_series(lp.seq("A_rising"))
print(f"  із шумом N(0;0,15) у висхідному каналі: {sum(1 for r in An if r['ooc'] == 0)} барів з outofchannel=0 із {len(An)} (випадкові виходи за −2σ, як і в оригіналі)")
F = lp.pine_series(lp.seq("F_neg_to_pos"))
check(any(r["trend_up"] for r in F) and not any(r["trend_dn"] for r in F), "F: зміна нахилу з мінусового на плюсовий дає Up trend")
G = lp.pine_series(lp.seq("G_pos_to_neg"))
check(any(r["trend_dn"] for r in G), "G: зміна нахилу з плюса на мінус дає Down trend")
check({r["arrow"] for r in An} <= {"⇑", "⇗"}, "A: стрілки висхідного нахилу ⇑/⇗")
check({r["arrow"] for r in lp.pine_series(lp.seq("B_falling"))} <= {"⇓", "⇘"}, "B: стрілки низхідного нахилу ⇓/⇘")
# alertcondition(outofchannel): неявне приведення int→bool у Pine v4 — 0 → false, будь-яке інше (і -1, і 2) → true
check(all(r["alert_channel_broken_as_pine_casts"] is True for r in J), "поведінка alertcondition: при outofchannel=-1 умова true (особливість оригіналу, НЕ перевірено в TradingView)")

# 3) Office: що є і чого немає (інформаційно; тест не падає, коли з'явиться)
MISSING = [n for n in ("outofchannel", "slope_momentum", "trend_change", "broken_channels") if not hasattr(oc, n)]
print("MISSING у office_regression_channel:", ", ".join(MISSING))

# 4) довжина вікна: 40 (теги READY) і 96 (знімок #119) ≠ 100 (еталон/Mini App)
closes = lp.seq("G_pos_to_neg")[:260]
rows = [{"ts": f"2026-01-01T{(i // 4) % 24:02d}:{(i % 4) * 15:02d}:00+00:00", "open": c, "high": c + 0.2, "low": c - 0.2, "close": c} for i, c in enumerate(closes)]
slopes = {}
for label, nbars in (("теги READY (40 свічок)", 40), ("знімок #119 (96 свічок)", 96), ("Mini App/еталон (≥101)", 120)):
    sub = rows[-nbars:]
    n = min(100, len(sub) - 1)                 # як у office_regression_channel.tags_for і в office_ready_evidence.build
    ch = oc.regression_channel(sub, length=n, deviation=2.0)
    slopes[label] = (n, ch["slope"])
    print(f"  {label:28} length={n:3d} slope={ch['slope']:+.5f}")
check(slopes["теги READY (40 свічок)"][0] == 39 and slopes["знімок #119 (96 свічок)"][0] == 95 and slopes["Mini App/еталон (≥101)"][0] == 100,
      f"довжини каналу в різних місцях Office: {[v[0] for v in slopes.values()]}")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)
