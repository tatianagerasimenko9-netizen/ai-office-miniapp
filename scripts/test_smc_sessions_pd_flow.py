#!/usr/bin/env python3
"""SMC: DST (Київ/Нью-Йорк), NYM, killzones (source-clock vs канонічні), Judas, AMD, session levels; PD/OTE; order flow/HRLR/LRLR proxy."""
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.smc import core as K  # noqa: E402
from office2.smc import fixtures as FX  # noqa: E402
from office2.smc import flow as FL  # noqa: E402
from office2.smc import pd as PD  # noqa: E402
from office2.smc import sessions as SS  # noqa: E402
from office2.smc import view as V  # noqa: E402

UTC = timezone.utc


def u(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC).timestamp()


def test_nym_follows_us_dst_not_fixed_0800():
    # зима США (EST, UTC-5): північ NY = 05:00 UTC; літо (EDT): 04:00 UTC
    assert SS.nym_utc(u(2026, 1, 15, 12)) == u(2026, 1, 15, 5)
    assert SS.nym_utc(u(2026, 7, 15, 12)) == u(2026, 7, 15, 4)
    # тижні розбіжності DST: США вже EDT (з 8.03.2026), Європа ще зимова (до 29.03.2026)
    t = u(2026, 3, 20, 12)
    assert SS.nym_utc(t) == u(2026, 3, 20, 4)
    kyiv = datetime.fromtimestamp(SS.nym_utc(t), UTC).astimezone(SS.KYIV)
    assert kyiv.hour == 6 and kyiv.utcoffset().total_seconds() == 2 * 3600          # 06:00 Київ (EET), а не 07:00/08:00
    # після переходу Європи на літній час NYM = 07:00 Київ
    k2 = datetime.fromtimestamp(SS.nym_utc(u(2026, 4, 10, 12)), UTC).astimezone(SS.KYIV)
    assert k2.hour == 7
    # пізня осінь: Європа вже зимова (з 25.10), США ще EDT до 1.11 → NYM 06:00 Київ; з 1.11 (EST) → 07:00 Київ
    assert datetime.fromtimestamp(SS.nym_utc(u(2026, 10, 28, 12)), UTC).astimezone(SS.KYIV).hour == 6
    assert datetime.fromtimestamp(SS.nym_utc(u(2026, 11, 5, 12)), UTC).astimezone(SS.KYIV).hour == 7


def test_kyiv_text_kyiv_first_utc_in_brackets():
    s = SS.kyiv_text(u(2026, 10, 9, 10, 45))
    assert s == "09.10 13:45 Київ (UTC 10:45)", s
    assert SS.kyiv_text(u(2026, 1, 9, 10, 45)) == "09.01 12:45 Київ (UTC 10:45)"


def test_source_vs_canonical_windows_are_separate_and_not_a_gate():
    d = date(2026, 7, 10)
    s0, s1 = SS.source_window_utc(d, "LONDON")          # 03:00–07:00 «UTC+3» → 00:00–04:00 UTC
    assert (s0, s1) == (u(2026, 7, 10, 0), u(2026, 7, 10, 4))
    c0, c1 = SS.canonical_window_utc(d, "LONDON")       # 02:00–05:00 NY (EDT) → 06:00–09:00 UTC
    assert (c0, c1) == (u(2026, 7, 10, 6), u(2026, 7, 10, 9))
    w = SS.window_view(u(2026, 7, 10, 7, 0))
    assert "UTC+3" in w["source_clock"] and w["canonical_windows"]["LONDON"]["inside"] and not w["source_windows"]["LONDON"]["inside"]
    # DST: той самий NY-вікно в січні зсувається на годину в UTC
    j0, _ = SS.canonical_window_utc(date(2026, 1, 12), "LONDON")
    assert j0 == u(2026, 1, 12, 7)


def _day_bars(day_utc_start, rows_fn, n=96 * 2):
    t = day_utc_start + 900 * np.arange(n, dtype=float)
    o = np.zeros(n); h = np.zeros(n); l = np.zeros(n); c = np.zeros(n)
    for k in range(n):
        o[k], h[k], l[k], c[k] = rows_fn(k, float(t[k]))
    return {"t": t, "o": o, "h": h, "l": l, "c": c, "v": np.ones(n)}


def test_judas_bear_forming_judas_confirmed():
    nym = u(2026, 1, 15, 5)                                   # EST
    t0 = nym - 3600 * 5
    def rows(k, t):
        x = (t - nym) / 900.0                                  # бари від NYM
        if x < -1: return (100, 100.4, 99.6, 100)
        if x < 0: return (100, 100.4, 99.6, 100)
        if x < 4: p = 100 + 0.6 * x; return (p, p + 0.8, p - 0.2, p + 0.5)     # прокол вгору над NYM
        if x < 8: p = 102.5 - 0.7 * (x - 4); return (p, p + 0.2, p - 0.8, p - 0.6)  # повернення нижче NYM
        p = 99.5 - 0.5 * (x - 8); return (p, p + 0.2, p - 0.7, p - 0.5)
    b = _day_bars(t0, rows, n=70)
    for now, want in ((nym + 900 * 3, "FORMING"), (nym + 900 * 8, "JUDAS")):
        j = SS.judas(b, now)
        assert j["state"] == want and j["dir"] == "SHORT", (now, j)
    jc = SS.judas(b, nym + 900 * 20, window_h=6)
    assert jc["state"] == "CONFIRMED" and jc["dir"] == "SHORT"
    # відсутній бар NYM → NO_DATA, не вигадуємо
    assert SS.judas({k: v[40:] for k, v in b.items()}, nym + 900 * 3)["state"] == "NO_DATA"


def test_judas_no_lookahead():
    nym = u(2026, 1, 15, 5)
    def rows(k, t):
        x = (t - nym) / 900.0
        if x < 0: return (100, 100.3, 99.7, 100)
        if x < 3: p = 100 + 0.7 * x; return (p, p + 0.6, p - 0.1, p + 0.4)
        p = 102 - 0.8 * (x - 3); return (p, p + 0.2, p - 0.7, p - 0.5)
    b = _day_bars(nym - 3600, rows, n=40)
    now = nym + 900 * 3
    cut = {k: v[:int((now - b["t"][0]) // 900)] for k, v in b.items()}
    assert SS.judas(b, now)["state"] == SS.judas(cut, now)["state"]


def test_amd_manipulation_then_distribution():
    d = date(2026, 1, 15)
    a0, a1 = SS.canonical_window_utc(d + __import__("datetime").timedelta(days=0), "ASIA")
    def rows(k, t):
        if t < a1: return (100, 100.6 if (k % 3 == 0) else 100.4, 99.4 if (k % 3 == 1) else 99.6, 100)       # діапазон 99.4–100.6
        x = (t - a1) / 900.0
        if x < 3: return (100, 101.3, 100, 100.2)               # прокол high з поверненням
        if x < 5: return (100.2, 100.3, 99.2, 99.3)             # закриття нижче low азійського діапазону → D
        return (99.3, 99.5, 98.5, 98.8)
    b = _day_bars(a0 - 3600, rows, n=80)
    r = SS.amd(b, a1 + 900 * 6)
    assert r["stage"] == "D" and r["dir"] == "SHORT", r
    assert SS.amd(b, a1 + 900 * 2)["stage"] in ("M", "A", "NO_RANGE")


def test_session_levels_known_after_session_end_only():
    nym = u(2026, 1, 15, 5)
    b = FX.bars([(100, 101, 99, 100)] * 400, t0=nym - 86400)
    now = float(b["t"][-1]) + 900
    lv = SS.session_levels(b, now)
    assert lv and all(x["conf"] < len(b["t"]) and b["t"][x["conf"]] >= 0 for x in lv)
    for x in lv:
        assert x["kind"].endswith(("_H", "_L"))


def test_pd_ote_and_stale_anchor():
    dr = PD.dealing_range(100.0, 200.0, 10, 50, 60)
    assert dr["eq"] == 150.0 and PD.zone_of(120, dr) == "DISCOUNT" and PD.zone_of(180, dr) == "PREMIUM"
    o = PD.ote(dr, "LONG")
    assert abs(o["zone"][0] - 121.0) < 1e-9 and abs(o["zone"][1] - 138.0) < 1e-9 and abs(o["sweet"] - 129.5) < 1e-9
    s = PD.ote(dr, "SHORT")
    assert abs(s["zone"][0] - 162.0) < 1e-9 and abs(s["sweet"] - 170.5) < 1e-9
    old = PD.dealing_range(100.0, 200.0, 10, 50, 1000)
    assert old["stale"] and PD.ote(old, "LONG")["stale_anchor"]


def test_order_flow_and_hrlr_lrlr_proxy():
    b = FX.uptrend()
    v = V.analyze_view(b)
    of = FL.order_flow(v["structure"], v["fvg"])
    assert of["proxy"] and of["state"] in ("BULL_FLOW", "WEAK_BULL")
    straight = FX.zigzag([100, 130], per_leg=20)
    chop = FX.zigzag([100, 104, 100, 104, 100, 104, 100, 104, 101], per_leg=4)
    assert FL.path_resistance(straight, 0, 19)["label"] == "LRLR"
    assert FL.path_resistance(chop, 0, len(chop["t"]) - 1)["label"] == "HRLR"


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
