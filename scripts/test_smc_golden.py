#!/usr/bin/env python3
"""Golden-покриття 40 навчальних схем SM Trader: реєстр зображень (sha256, 40 із «41» запитаних), кожна схема прив'язана до розділу джерела і до виконуваного тесту-фікстури.
Фікстури — синтетичні OHLC за конфігурацією схеми (якісні), не реальні ціни і не backtest."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import test_smc_blocks as TB  # noqa: E402
import test_smc_imbalance as TI  # noqa: E402
import test_smc_liquidity as TL  # noqa: E402
import test_smc_models as TM  # noqa: E402
import test_smc_sessions_pd_flow as TS  # noqa: E402
import test_smc_structure as TST  # noqa: E402
from office2.smc import core as K  # noqa: E402
from office2.smc import fixtures as FX  # noqa: E402
from office2.smc import flow as FL  # noqa: E402
from office2.smc import liquidity as LQ  # noqa: E402
from office2.smc import pd as PD  # noqa: E402
from office2.smc import sources as SRC  # noqa: E402
from office2.smc import structure as ST  # noqa: E402
from office2.smc import view as V  # noqa: E402


def g_mss_valid_vs_invalid():
    ok = ST.analyze(FX.mss_confirm())
    assert any(e["kind"] == "MSS" for e in ok["events"])                         # схема 10 ліворуч
    bad = ST.analyze(FX.zigzag([100, 110, 104, 118, 111, 117, 108], per_leg=4))  # схема 10 праворуч: «нет обновления максимума» → злам внутрішнього мінімуму ≠ MSS
    assert not any(e["kind"] == "MSS" for e in bad["events"])


def g_ote_with_ob():
    b = FX.reversal_long()
    v = V.analyze_view(b)
    ob = [o for o in v["ob_demand"] if o["conf"] > 60][0]
    dr = PD.dealing_range(98.6, 112.5, 66, 71, len(b["t"]) - 1)
    o = PD.ote(dr, "LONG")
    assert ob["zone"][1] >= o["zone"][0] - 5 and abs(o["levels"]["0.705"] - o["sweet"]) < 1e-9 and set(o["levels"]) == {"0.5", "0.62", "0.705", "0.79"}   # сітка схеми 12


def g_liquidity_types():
    b = FX.zigzag([100, 110, 102, 110.1, 101, 110.05, 103, 109, 102.5, 108, 103.5], per_leg=3)
    a = K.atr_arr(b, 5)
    hs, ls = ST.swings(b, 1)
    lv = LQ.swing_levels(b, hs, ls, a, eq_tol_atr=0.2)
    kinds = {x["kind"] for x in lv}
    assert {"EQH", "SWING_H", "SWING_L"} <= kinds                                  # EQH/EQL і swing points
    rg = ST.detect_range(b, hs, ls, a)
    assert rg and {x["kind"] for x in LQ.range_levels(rg, 10)} == {"RANGE_H", "RANGE_L"}   # межі range
    tl = LQ.trendline_levels([{"i": 3, "conf": 4, "p": 110.0}, {"i": 9, "conf": 10, "p": 108.0}], [{"i": 4, "conf": 5, "p": 100.0}, {"i": 10, "conf": 11, "p": 102.0}], 20)
    assert {x["kind"] for x in tl} == {"TL_H", "TL_L"}                              # трендова ліквідність


def g_order_flow():
    up, dn = V.analyze_view(FX.uptrend()), V.analyze_view(FX.downtrend())
    assert FL.order_flow(up["structure"], up["fvg"])["state"] in ("BULL_FLOW", "WEAK_BULL")
    assert FL.order_flow(dn["structure"], dn["fvg"])["state"] in ("BEAR_FLOW", "WEAK_BEAR")


def g_ob_usage_two_blocks_supply_with_liquidity():
    m = K.mirror(FX.reversal_long())
    v = V.analyze_view(m)                                                          # SHORT-сценарій у LONG-координатах дзеркала: demand OB у mirror = supply у реальності
    assert any(o["liquidity_taken"] for o in v["ob_demand"])


GOLDEN = {
    "swing_3candle": TST.test_swing_three_candles_and_negative, "uptrend_structure": TST.test_uptrend_bms_chain_and_labels, "downtrend_structure": TST.test_downtrend_bms_chain,
    "range_deviation": TST.test_range_and_deviation, "bms_chain": TST.test_uptrend_bms_chain_and_labels, "mss_confirm": TST.test_mss_then_confirm, "mss_valid_vs_invalid": g_mss_valid_vs_invalid,
    "not_mss_correction": TST.test_correction_break_is_not_mss, "ote_with_ob": g_ote_with_ob, "fvg_basic": TI.test_fvg_geometry_and_efficient_negative, "liquidity_types": g_liquidity_types,
    "order_flow": g_order_flow, "hrlr_lrlr": TS.test_order_flow_and_hrlr_lrlr_proxy, "bull_ob": TB.test_bull_ob_requires_engulfing_and_mt_lifecycle, "bear_ob": TB.test_bear_ob_is_exact_mirror,
    "ob_levels": TB.test_ob_wick_mode_for_small_body_long_wicks, "ob_usage": g_ob_usage_two_blocks_supply_with_liquidity, "breaker_block": TB.test_breaker_vs_mitigation_profiles,
    "mitigation_block": TB.test_breaker_vs_mitigation_profiles, "mb_vs_bb": TB.test_breaker_vs_mitigation_profiles, "rejection_block": TB.test_rejection_block_bull_wick_on_ssl,
    "raid_sweep": TL.test_fresh_raid_reclaim_in_two_bars, "sfp": TL.test_sfp_same_bar_close_back, "stb_bts": TB.test_stb_zone_between_sweep_extreme_and_mss_level,
    "sponsored_candle": TB.test_sponsored_two_variants_unverified, "reversal_type1": TM.test_reversal_long_full_sequence_ready, "rev_vs_cont": TM.test_continuation_needs_two_ms_and_aligned_bias,
}


def test_registry_has_40_images_with_hashes_and_discrepancy_noted():
    reg = json.loads((ROOT / "fixtures/smc/sm_trader/registry.json").read_text(encoding="utf8"))
    assert reg["count"] == reg["available"] == 40 and reg["requested"] == 41 and "41-ша відсутня" in reg["note"] and "4 піддіаграми" in reg["note"]
    assert [i["n"] for i in reg["images"]] == list(range(1, 41))
    for i in reg["images"]:
        f = ROOT / "fixtures/smc/sm_trader" / i["file"]
        assert f.exists() and f.stat().st_size > 5000, f
        assert len(i["sha256_original_png"]) == 64 and i["section"] in SRC.section_ids()
    assert any(d["id"] == "D-07" for d in SRC.DISCREPANCIES)


def test_every_scheme_is_mapped_to_a_runnable_golden_check():
    seen = set()
    for it in SRC.IMAGES:
        fx = it.get("fixture")
        if fx is None:
            assert it.get("note"), f"схема {it['n']} без фікстури має пояснення (неалгоритмізовано)"
            continue
        assert fx in GOLDEN, f"схема {it['n']}: немає golden-перевірки «{fx}»"
        if fx not in seen:
            GOLDEN[fx]()
            seen.add(fx)
    assert len(SRC.IMAGES) == 40 and len(seen) >= 25


def test_sources_cover_all_toc_sections_and_discrepancies():
    ids = SRC.section_ids()
    assert len(ids) == len(set(ids)) and {"S09.2", "S12", "S18", "S19", "S20", "S21", "S24", "S25", "S26", "S27", "S29"} <= set(ids)
    assert {d["id"] for d in SRC.DISCREPANCIES} >= {"D-01", "D-02", "D-03", "D-04", "D-05", "D-07", "D-08"}


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
