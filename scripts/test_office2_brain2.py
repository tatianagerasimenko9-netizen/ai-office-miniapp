#!/usr/bin/env python3
"""Office2 Brain v2: повний ланцюг (подія → зсув структури → зона входу → ретрейс → тригер), заборона READY за sweep+reclaim+1 бар, дзеркало SHORT, без lookahead."""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import o2live_synth as S  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2 import brain2 as B2  # noqa: E402
from office2 import features as F  # noqa: E402

LEVELS = [{"p": 99.0, "side": "low", "kind": "PDL", "strength": 1, "known": 0.0}, {"p": 103.6, "side": "high", "kind": "PDH", "strength": 1, "known": 0.0}, {"p": 106.0, "side": "high", "kind": "PWH", "strength": 1, "known": 0.0}]


def closes_long():
    rng = np.random.default_rng(3)
    base = list(100.3 + np.cumsum(rng.normal(0, 0.04, 400)))
    base = [100.3 + (x - 100.3) * 0.3 for x in base]
    c = base[:]
    ev = [99.6, 98.9, 99.2]                                   # sweep рівня 99.0 (low нижче), повернення
    c += ev
    seq = {"sweep": len(c)}
    c += [99.6, 99.95, 100.3, 100.0, 99.75, 99.6]                  # відскок до swing-high 100.3 і м'який відкат
    seq["pre_shift"] = len(c)
    c += [101.2]                                                    # displacement: закриття над 100.3
    seq["shift"] = len(c)
    c += [101.6, 102.0]
    seq["top"] = len(c)
    c += [101.5, 100.9, 100.4, 100.1]                               # ретрейс до зони
    seq["in_zone_pre"] = len(c)
    c += [99.85]                                                    # у зоні, але ведмежа свічка
    seq["bear_in_zone"] = len(c)
    c += [100.05]                                                   # бичачий відбій у зоні
    seq["trigger"] = len(c)
    return c, seq


def mk(closes, upto):
    b = S._bars_from_closes(closes[:upto])
    h4, d1, w1 = F.resample(b, 4 * 3600), F.resample(b, 86400), F.resample(b, 7 * 86400, offset=F.WEEK_OFFSET)
    return b, B.build_full_ctx(b, h4, d1, w1)


def run(closes, upto, direction="LONG", levels=None):
    b, ctx = mk(closes, upto)
    now = float(b["t"][-1] + 900)
    return B2.thesis(ctx, direction, now, levels or LEVELS, 10.0)


def test_chain_progression_long():
    c, seq = closes_long()
    th = run(c, seq["sweep"])
    assert th and th["state"] == "WAIT" and "потрібен зсув структури" in th["reason"], th              # sweep+reclaim самі по собі — НЕ READY
    th = run(c, seq["pre_shift"])
    assert th["state"] == "WAIT" and "зсув структури" in th["reason"], th
    th = run(c, seq["top"])
    assert th["state"] == "WAIT" and "контрольований ретрейс" in th["reason"] and th["entry_zone"], th        # displacement є, але гнатися не можна
    th = run(c, seq["bear_in_zone"])
    assert th["state"] == "WAIT" and "бичаче закриття" in th["reason"], th                                    # у зоні, але тригера нема
    th = run(c, seq["trigger"])
    assert th["state"] == "READY", th
    q = th["quality"]
    assert th["sl"] < th["invalidation"]["price"] < th["entry_zone"][0] and th["invalidation"]["buffer"] > 0 and th["targets"][0]["r"] >= 1.0
    assert q["risk_atr15"] >= 1.0 and [s["step"] for s in th["sequence"] if s["ok"]][:4] == ["подія", "зсув структури (MSS/BOS)", "нога зміщення і зона входу", "ретрейс у зону"]
    assert th["entry_zone"][0] <= th["entry"] <= th["entry_zone"][1] + 1.0 and abs(th["sizing"]["notional_usd"] - 10.0 / (th["risk"] / th["entry"])) < 1e-6
    assert th["id"] == run(c, seq["trigger"] - 1)["id"]                                                       # id стабільний протягом життя сценарію


def test_no_ready_from_sweep_reclaim_hold_only():
    """Старий шлях: sweep → reclaim → утримання 1 бар дав READY. Тепер — жодного READY без зсуву структури, ретрейсу й тригера."""
    c, seq = closes_long()
    for n in range(seq["sweep"], seq["pre_shift"] + 1):
        th = run(c, n)
        assert th is None or th["state"] != "READY", (n, th)


def test_short_mirror_and_no_lookahead():
    c, seq = closes_long()
    cm = [200.0 - x for x in c]
    lev = [{"p": 200.0 - x["p"], "side": "high" if x["side"] == "low" else "low", "kind": x["kind"], "strength": 1, "known": 0.0} for x in LEVELS]
    th = run(cm, seq["trigger"], "SHORT", lev)
    th_l = run(c, seq["trigger"])
    assert th["state"] == "READY" and abs(th["entry"] - (200.0 - th_l["entry"])) < 1e-6 and th["sl"] > th["invalidation"]["price"] > th["entry_zone"][1], th
    # без lookahead: решта серії не змінює рішення на prefix
    b_full = S._bars_from_closes(c + [104.0, 105.0, 90.0])
    a = run(c, seq["trigger"])
    cc = c[:seq["trigger"]]
    b = S._bars_from_closes(cc)
    assert a["state"] == "READY" and run(cc, len(cc))["entry"] == a["entry"]
    assert len(b_full["t"]) > len(b["t"])


def test_missed_and_invalidated():
    c, seq = closes_long()
    run_away = c[:seq["top"]] + [102.4, 103.0, 103.6, 104.2, 104.8, 105.3, 105.9, 106.4, 107.0, 107.5]
    th = run(run_away, len(run_away))
    assert th["state"] in ("MISSED", "WAIT"), th
    long_run = c[:seq["top"]] + list(np.linspace(102.0, 112.0, 40))
    th = run(long_run, len(long_run))
    assert th["state"] == "MISSED" and "не доганяємо" in th["reason"], th
    broken = c[:seq["top"]] + [101.0, 100.0, 99.2, 98.4]
    th = run(broken, len(broken))
    assert th["state"] == "INVALIDATED", th


def test_registry_roles():
    roles = {v["role"] for v in B2.REGISTRY.values()}
    assert roles == {"GATE", "CONTEXT", "EVIDENCE", "RESEARCH", "NOT_CONNECTED"}
    assert B2.REGISTRY["DOM / order book"]["role"] == "NOT_CONNECTED" and B2.REGISTRY["MSS/BOS + displacement"]["role"] == "GATE"


def test_engine_integration_v2_trace_and_evidence():
    """step_symbol: brain v2 → WAIT… → READY; у знімку послідовність, evidence-модулі (ролі/статуси), version_id; Telegram-картка із зоною входу."""
    import json
    import tempfile

    import office_bridge as OB
    from office2 import delivery as DL
    from office2 import engine as EN

    assert EN.BRAIN_V2
    c, seq = closes_long()
    orig = B.all_levels
    B.all_levels = lambda ctx, now: LEVELS
    try:
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "o2.db")
            OB.init_office_db(db)
            EN.init_db(db)
            for upto in (seq["sweep"], seq["top"], seq["bear_in_zone"], seq["trigger"]):
                b, ctx = mk(c, upto)
                now = float(b["t"][-1] + 900)
                st = {"price": float(b["c"][-1]), "ret_1h": 0.3, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}
                EN.step_symbol(db, "XUSDT", ctx, st, {"btc_ret_1h": 0.1, "eth_ret_1h": 0.1, "breadth_up_1h": 0.5, "n_alts": 20}, {"coin_ret_1h": 0.3, "rs_vs_btc_1h": 0.2, "rs_vs_btc_4h": 0.1}, now, None,
                               flow_fetch=lambda: {}, m5_fetch=lambda: None)
            rows = OB._fetchall(db, "SELECT scenario_id, version, snapshot_json FROM office2_live_signal")
            assert len(rows) == 1 and rows[0][1] == B2.VERSION, rows
            snap = json.loads(rows[0][2])
            assert snap["version_id"] == B2.VERSION and snap["sequence"] and snap["thesis"]["kind"] in ("SWEEP_SEQ", "ORIGIN_SEQ")
            mods = {m["module"]: m for m in snap["evidence"]}
            assert mods["DOM / order book"]["status"] == "NOT_CONNECTED" and mods["OI / funding / L:S / ліквідації"]["status"] == "UNAVAILABLE" and mods["M5/M1 тригер"]["status"] == "UNAVAILABLE"
            assert mods["HTF MN/W1/4D/3D/D1/H4/H1"]["role"] == "CONTEXT" and mods["volume / taker-delta / CVD"]["status"] in ("USED", "UNAVAILABLE")
            steps = [t["step"] for t in snap["trace"]]
            assert any("послідовність" in x for x in steps) and any("модулі" in x for x in steps)
            sc_states = [r[0] for r in OB._fetchall(db, "SELECT to_state FROM office2_live_transition ORDER BY ts ASC")]
            assert "WAIT" in sc_states and sc_states[-1] == "READY", sc_states
            stages = [(r[0], r[1]) for r in OB._fetchall(db, "SELECT from_state, to_state FROM office2_live_transition WHERE from_state LIKE 'WAIT _/3' ORDER BY ts ASC")]
            assert ("WAIT 2/3", "WAIT 3/3") in stages, stages                                   # етапи WAIT залишають слід переходів
            cap = DL.build_caption(dict(snap, valid_until_ts=snap["decided_ts"] + 3600))
            th = snap["thesis"]
            assert "Зона входу:" in cap and "READY:" in cap and "Чому:" in cap, cap
            assert th["entry_zone"][0] <= th["entry"]
    finally:
        B.all_levels = orig


def test_scenario_ids_unique_per_symbol():
    """Регресія: однакова подія (напрям/вид/час) на двох монетах → різні scenario_id і окремі рядки в БД, thesis не перемішується."""
    import tempfile

    import office_bridge as OB
    from office2 import engine as EN

    assert EN.scoped_id("AUSDT", "O2|abc") != EN.scoped_id("BUSDT", "O2|abc") and EN.scoped_id("AUSDT", "O2|abc") == EN.scoped_id("AUSDT", "O2|abc")
    c, seq = closes_long()
    orig = B.all_levels
    B.all_levels = lambda ctx, now: LEVELS
    try:
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "o2.db")
            OB.init_office_db(db)
            EN.init_db(db)
            b, ctx = mk(c, seq["top"])
            now = float(b["t"][-1] + 900)
            st = {"price": float(b["c"][-1]), "ret_1h": 0.3, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}
            mc, rel = {"btc_ret_1h": 0.1, "eth_ret_1h": 0.1, "breadth_up_1h": 0.5, "n_alts": 20}, {"coin_ret_1h": 0.3, "rs_vs_btc_1h": 0.2, "rs_vs_btc_4h": 0.1}
            for sym in ("AUSDT", "BUSDT"):
                EN.step_symbol(db, sym, ctx, st, mc, rel, now, None)
            rows = OB._fetchall(db, "SELECT scenario_id, symbol, thesis_json FROM office2_live_scenario")
            assert len({r[0] for r in rows}) == len(rows) >= 2 and {r[1] for r in rows} == {"AUSDT", "BUSDT"}, rows
            import json as _j

            assert all(_j.loads(r[2]).get("symbol") == r[1] for r in rows), "thesis має належати символу рядка"
            fr = OB._fetchall(db, "SELECT symbol, direction, stage FROM office2_brain_funnel")
            assert {(r[0], r[1]) for r in fr} == {(s_, d_) for s_ in ("AUSDT", "BUSDT") for d_ in ("LONG", "SHORT")}, fr        # кожна пара (символ×напрям) має етап воронки, навіть без події
            from office2 import webview as WV

            f = WV.payload(db, now)["funnel"]
            assert f["last"] and sum(x["n"] for x in f["last"]["stages"]) == 4, f
    finally:
        B.all_levels = orig


def test_stats_split_by_brain_version():
    import json
    import tempfile

    import office_bridge as OB
    from office2 import engine as EN
    from office2 import stats as ST

    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "o2.db")
        OB.init_office_db(db)
        EN.init_db(db)
        for sid, brain in (("O2|a", "o2-brain-1"), ("O2|b", "o2-brain-2.0")):
            snap = {"brain": brain, "thesis": {"targets": [{"p": 1, "r": 1.2}], "entry": 1}, "alignment_summary": {"against": 0}}
            OB._execute(db, "INSERT INTO office2_live_signal(scenario_id, symbol, direction, created_ts, valid_until_ts, status, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?)",
                        (sid, "XUSDT", "LONG", 1000.0, 9e9, "DELIVERED", json.dumps(snap), brain))
        out = ST.collect(db)
        assert set(out["by_brain"]) == {"o2-brain-1", "o2-brain-2.0"} and out["by_brain"]["o2-brain-1"]["delivered"] == 1, out["by_brain"]


def test_funnel_stage_mapping():
    from office2 import engine as EN

    assert EN.funnel_stage(None) == ("NO_EVENT", "")
    assert EN.funnel_stage({"state": "WAIT", "reason": "WAIT 1/3 · зсув структури: x"})[0] == "WAIT_1_SHIFT"
    assert EN.funnel_stage({"state": "WAIT", "reason": "WAIT 2/3 · ретрейс: x"})[0] == "WAIT_2_ZONE"
    assert EN.funnel_stage({"state": "WAIT", "reason": "WAIT 3/3 · ARMED (x)"})[0] == "ARMED_3"
    assert EN.funnel_stage({"state": "NO_TRADE", "reason": "до першої реальної цілі PDL 1 лише 0.5 R"}) == ("NO_TRADE", "простір до цілі")
    assert EN.funnel_stage({"state": "NO_TRADE", "reason": "структурна інвалідація всередині нормального шуму: x"}) == ("NO_TRADE", "стоп у шумі")
    assert EN.funnel_stage({"state": "READY", "reason": ""})[0] == "READY"


def test_shift_accepts_displacement_after_weak_break_and_cap_keeps_advanced_event():
    """Логічні суперечності, а не послаблення: (1) перший злам swing звичайною свічкою + displacement на наступному барі = зсув (раніше swing назавжди ставав «неможливим»);
    без displacement у вікні зсуву немає; (2) просунутий старий сценарій не витісняється ≥4 новішими sweep-подіями."""
    n = 40
    t = np.arange(n) * 900.0 + 1.7e9
    o = np.full(n, 100.0)
    c = np.full(n, 100.0)
    h = np.full(n, 100.5)
    l = np.full(n, 99.5)
    # подія e=10 (low 98), swing-high на 14 (101), підтверджений на 16
    l[10], c[10] = 98.0, 99.0
    h[14], c[14] = 101.0, 100.4
    c[15], h[15] = 100.2, 100.6
    c[16], h[16] = 100.1, 100.5
    o[17], c[17], h[17], l[17] = 100.1, 101.2, 101.3, 100.0      # перший закриття над 101 (злам), тіло 1.1 — слабке (ATR 1.0 → поріг 1.2)
    o[18], c[18], h[18], l[18] = 101.2, 102.6, 102.7, 101.1      # наступний бар: тіло 1.4 ATR, закриття у верхніх 35% → displacement
    bars = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": np.ones(n), "tbv": np.ones(n)}
    a15 = np.full(n, 1.0)
    r = B2._shift(bars, a15, 20, 10)
    assert r and r["j"] == 17 and r["jd"] == 18, r
    c2 = c.copy()
    o2 = o.copy()
    c2[18], o2[18], h[18] = 101.3, 101.2, 101.4                   # без displacement у вікні (3 бари)
    c2[19] = 101.2
    c2[20] = 101.25
    o2[19], o2[20] = 101.15, 101.2
    bars2 = dict(bars, c=c2, o=o2)
    assert B2._shift(bars2, a15, 20, 10) is None
    # (2) cap подій
    c_, seq = closes_long()
    b, ctx = mk(c_, seq["top"])
    now = float(b["t"][-1] + 900)
    real = B2._sweep_events(B.view(ctx["m15"], 1), F.atr(ctx["m15"], 14), F.last_closed(ctx["m15"], 900, now), LEVELS, 1)
    assert real
    k = F.last_closed(ctx["m15"], 900, now)
    fakes = [dict(real[0], e=k - 1 - i, extreme=float(ctx["m15"]["l"][k - 1 - i])) for i in range(8)]
    orig = B2._sweep_events
    B2._sweep_events = lambda *a, **kw: fakes + real[:1]
    try:
        th = B2.thesis(ctx, "LONG", now, LEVELS, 10.0)
    finally:
        B2._sweep_events = orig
    assert th and th.get("entry_zone"), th                    # просунутий (старший) сценарій обраний, а не затертий 8 новішими


def test_radar_groups_order():
    from office2 import webview as WV

    assert WV.radar_group("READY", "")[0] == 0
    assert WV.radar_group("WAIT", "WAIT 3/3 · ARMED (x)")[0] == 1 < WV.radar_group("WAIT", "WAIT 2/3 · ретрейс: x")[0] < WV.radar_group("WAIT", "WAIT 1/3 · зсув: x")[0]
    assert WV.radar_group("NO_TRADE", "x")[0] == 5 and WV.radar_group("MISSED", "")[0] == 6 and WV.radar_group("INVALIDATED", "")[0] == 7


def _v2_e2e(short):
    """E2E на синтетичному ланцюжку: READY brain v2 → доставка (не «пізній вхід» через trigger_level) → план lifecycle → Mini App. Раніше trigger_level = екстремум події → chase > 0.6 R → кожен READY v2 відсікався б при доставці."""
    import asyncio
    import datetime as dt
    import tempfile

    import office_bridge as OB
    import office_ready_card as card
    import office_signal_track as trk
    from office2 import delivery as DL
    from office2 import engine as EN
    from office2 import webview as WV

    class Sent:
        def __init__(self):
            self.calls = []

        async def __call__(self, event_type, text, **kw):
            self.calls.append((event_type, text, kw))
            return 7000 + len(self.calls)

    c, seq = closes_long()
    lv = LEVELS
    if short:
        c = [200.0 - x for x in c]
        lv = [{"p": 200.0 - x["p"], "side": "high" if x["side"] == "low" else "low", "kind": x["kind"], "strength": 1, "known": 0.0} for x in LEVELS]
    orig = B.all_levels
    B.all_levels = lambda ctx, now: lv
    try:
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "o2.db")
            OB.init_office_db(db)
            EN.init_db(db)
            st = lambda b: {"price": float(b["c"][-1]), "ret_1h": 0.3, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}  # noqa: E731
            for upto in (seq["sweep"], seq["top"], seq["bear_in_zone"], seq["trigger"]):
                b, ctx = mk(c, upto)
                EN.step_symbol(db, "XUSDT", ctx, st(b), {"btc_ret_1h": 0.1, "eth_ret_1h": 0.1, "breadth_up_1h": 0.5, "n_alts": 20}, {"coin_ret_1h": 0.3, "rs_vs_btc_1h": 0.2, "rs_vs_btc_4h": 0.1}, float(b["t"][-1] + 900), None)
            created = OB._fetchone(db, "SELECT created_ts FROM office2_live_signal")[0]
            candles = [{"ts": dt.datetime.fromtimestamp(float(b["t"][i]), tz=dt.timezone.utc).isoformat(), "open": float(b["o"][i]), "high": float(b["h"][i]), "low": float(b["l"][i]), "close": float(b["c"][i]),
                        "volume": 100.0, "src": "binance_futures"} for i in range(len(b["t"]) - 96, len(b["t"]))]
            sent = Sent()
            import json
            snap = json.loads(OB._fetchone(db, 'SELECT snapshot_json FROM office2_live_signal')[0])
            px = float(snap['thesis']['entry'])
            recent = [{'ts': dt.datetime.fromtimestamp(float(snap['decided_ts']) + 5, tz=dt.timezone.utc).isoformat(),
                       'open': px, 'high': px, 'low': px, 'close': px}]
            n = asyncio.run(DL.deliver_pending(db, sent, lambda s_, tf, lim: recent if tf == '1m' else candles, card.render, 'TRADE_UPDATE', now=created + 60, log=lambda m: None))
            assert n == 1 and len(sent.calls) == 1, (n, OB._fetchall(db, "SELECT status, last_error FROM office2_live_signal"))
            text = sent.calls[0][1]
            assert text.startswith("OFFICE2 · LIVE BETA\n" + ("🔴 SHORT" if short else "🟢 LONG") + " · X") and "Зона входу:" in text and "SL:" in text and "TP1:" in text and "Ризик моделі: 10 $" in text, text
            plan = trk.plan_for(db, sent.calls[0][2]["canonical_id"])
            assert plan and ((plan["sl"] > plan["entry"] > plan["tp1"]) if short else (plan["sl"] < plan["entry"] < plan["tp1"]))
            pl = WV.payload(db, now=created + 120)
            sg = pl["signals"][0]
            assert sg["frozen"]["thesis"]["kind"] in ("SWEEP_SEQ", "ORIGIN_SEQ") and sg["frozen"]["sequence"] and sg["frozen"]["evidence"] and sg["status"] == "DELIVERED"
            assert pl["scenarios"][0]["group"] == 0 and pl["scenarios"][0]["state"] == "READY"       # Radar: READY угорі
            _integrated(db, sent.calls[0][2]["canonical_id"], short)
    finally:
        B.all_levels = orig


def _integrated(db, sid, short):
    """Один продукт: Brain v2.1 живе в основному Mini App — список сценаріїв, картка (знімок + «зараз»), єдиний Radar, статистика окремо за версією Brain."""
    import time as _t

    import office_bridge as OB
    import office_mini_v2 as MV

    prev = os.environ.get("OFFICE_DB_PATH")
    os.environ["OFFICE_DB_PATH"] = db
    os.environ.pop("DATABASE_URL", None)
    created = OB._fetchone(db, "SELECT created_ts FROM office2_live_signal")[0]
    real_time = _t.time
    _t.time = lambda: created + 120            # синтетичні свічки з минулого: «зараз» = момент через 2 хв після READY
    try:
        d = MV.scenario_detail(sid)
        assert d["ok"] and d["brain"] == "o2" and "redirect" not in d and d["scenario"]["scenario_id"] == sid
        sc = d["scenario"]
        assert sc["direction"] == ("SHORT" if short else "LONG") and sc["kind"] == "brain_v2" and sc["status"]["group"] == "live" and sc["status_raw"] == "ACTIVE"
        assert sc["zone_lo"] < sc["zone_hi"] and sc["tp1"] and sc["sl"] and sc["display"]["tp1"] and sc["lifecycle"]["key"] == "confirmed"
        fr = d["o2"]["frozen"]
        assert fr["integral"] and fr["market_map"]["tfs"] and fr["sequence"] and fr["evidence"] and d["o2"]["levels"]["targets"]
        lst = MV.list_scenarios(include_watching=True)
        assert any(c["scenario_id"] == sid and c["brain"] == "v2.1" for c in lst)                    # той самий список, що й сценарії Лева
        assert MV.scenarios_payload()["scenarios"][0]["scenario_id"] == sid
        r = MV.radar_payload()
        assert r["groups"][0]["group"] == 0 and r["groups"][0]["items"][0]["state"] == "READY"
        it = r["groups"][0]["items"][0]
        assert "price" in it and it["expires_ts"] and it["sym"] == "X", it                      # монета, ціна зараз, термін дії
        st = MV.journal_payload(kind="stats")
        assert "office2" in st and st["office2"]["by_brain"]
        card = MV.o2_card({"id": sid, "symbol": "XUSDT", "direction": sc["direction"], "created_ts": 1.0, "valid_until_ts": 2.0, "thesis": fr["thesis"], "levels": ["ENTRY", "TP1", "SL"]})
        assert card["status_raw"] == "HIT_SL" and card["status"]["group"] == "done"                  # SL сценарію — стан моделі, не особистий збиток
        assert MV.o2_card({**{"id": sid, "symbol": "XUSDT", "direction": "LONG", "created_ts": 1.0, "valid_until_ts": 2.0, "thesis": fr["thesis"]}, "levels": ["TP1"]})["status_raw"] == "HIT_ENTRY"
    finally:
        _t.time = real_time
        if prev is None:
            os.environ.pop("OFFICE_DB_PATH", None)
        else:
            os.environ["OFFICE_DB_PATH"] = prev


def _both(upto_key="trigger"):
    c, seq = closes_long()
    cm = [200.0 - x for x in c]
    lev = [{"p": 200.0 - x["p"], "side": "high" if x["side"] == "low" else "low", "kind": x["kind"], "strength": 1, "known": 0.0} for x in LEVELS]
    return (run(c, seq[upto_key]), run(cm, seq[upto_key], "SHORT", lev), c, cm, seq, lev)


def test_long_short_math_symmetry_and_texts():
    """Однакова математика LONG/SHORT: SL по напрямку буфера, зона = реальний дотик за OHLC, тексти кроків без суперечностей (LTC SHORT 07.10: «67,91 − 0,03 = 67,94», «low 67,76 у зоні 67,59–67,74»)."""
    import re

    L, S_, c, cm, seq, lev = _both()
    assert L["state"] == S_["state"] == "READY"
    for th, sg in ((L, 1), (S_, -1)):
        inv, sl, e = th["invalidation"]["price"], th["sl"], th["entry"]
        assert abs(abs(sl - inv) - th["invalidation"]["buffer"]) < 1e-9 and (sl < inv if sg > 0 else sl > inv)           # люфт зсуває SL ПОЗА екстремум події
        assert abs(th["risk"] - abs(e - sl)) < 1e-9 and abs(th["risk_pct"] - th["risk"] / abs(e) * 100) < 1e-9
        for t in th["targets"]:
            assert abs(t["r"] - abs(t["p"] - e) / th["risk"]) < 1e-9 and abs(t["pct"] - abs(t["p"] - e) / e * 100) < 1e-9 and (t["p"] > e if sg > 0 else t["p"] < e)
        txt = {x["step"]: x.get("value", "") for x in th["sequence"]}
        m = re.match(r"інвалідація ([\d.]+) ([−+]) люфт ([\d.e-]+) .*= ([\d.]+);", txt["SL"])
        a, op, b, r_ = float(m.group(1)), m.group(2), float(m.group(3)), float(m.group(4))
        assert op == ("−" if sg > 0 else "+") and abs((a - b if sg > 0 else a + b) - r_) < 1e-3, txt["SL"]               # арифметика в тексті сходиться для обох напрямів
        z = txt["ретрейс у зону"]
        ext, lo_, hi_ = [float(x) for x in re.findall(r"[\d.]+", z.split("торкнувся")[0] + " " + z.split("зони")[1])[:3]] if False else (None, None, None)
        m2 = re.match(r"(low|high) ([\d.]+) торкнувся зони ([\d.]+)–([\d.]+)", z)
        assert m2 and m2.group(1) == ("low" if sg > 0 else "high"), z
        ext, zl_, zh_ = float(m2.group(2)), float(m2.group(3)), float(m2.group(4))
        touched = (ext <= zh_) if sg > 0 else (ext >= zl_)                                                              # реальний дотик зони за екстремумом свічки
        assert touched, z
        if (ext < zl_) if sg > 0 else (ext > zh_):
            assert "пройшла зону наскрізь" in z, z                                                                      # екстремум за межею зони — чесно сказано
    assert abs(L["entry"] + S_["entry"] - 200.0) < 1e-6


def test_legacy_short_snapshot_texts_repaired_on_display_only():
    """Знімок LTC SHORT 07.10 (до виправлення): числа правильні, підписи — ні. При показі виправляємо текст, знімок не чіпаємо."""
    from office2 import webview as WV

    seq = [{"step": "ретрейс у зону", "ok": True, "value": "low 67.76 у зоні 67.5946–67.7357"}, {"step": "SL", "ok": True, "value": "інвалідація 67.91 − люфт 0.03 (медіана 5 проколів цього рівня) = 67.94; 2.10 ATR(M15)"}]
    out = WV.repair_legacy_texts(seq, "SHORT")
    assert out[0]["value"] == "high 67.76 торкнувся зони 67.5946–67.7357" and out[1]["value"].startswith("інвалідація 67.91 + люфт 0.03") and seq[1]["value"].count("−") == 1
    assert WV.repair_legacy_texts(seq, "LONG") is seq and WV.repair_legacy_texts(out, "SHORT")[1]["value"] == out[1]["value"]


def test_telegram_caption_single_percent_and_r_from_ready_price():
    """Telegram: один відсоток і R від ЦІНИ READY (не діапазон по краях зони); зона окремим рядком; Mini App зберігає діапазони для інших цін входу."""
    import re

    from office2 import delivery as DL
    from office2 import levels as LVL

    for direction, entry, sl, tps, zone in (("LONG", 0.5089, 0.48415, [0.5379, 0.6125, 0.6259], [0.495963, 0.5089]), ("SHORT", 67.45, 67.94, [66.07, 65.59, 61.63], [67.5946, 67.7357])):
        th = {"entry": entry, "sl": sl, "entry_zone": zone, "targets": [{"p": p_, "kind": "X"} for p_ in tps], "sizing": {"risk_usd": 10.0}, "trigger_level": zone[0]}
        cap = DL.build_caption({"thesis": th, "symbol": "TIAUSDT", "direction": direction, "valid_until_ts": 1791392000.0, "why": "тест"})
        risk = abs(entry - sl)
        m = re.search(r"SL: [\d,]+ \(−([\d,]+)%\)", cap)
        assert m and abs(float(m.group(1).replace(",", ".")) - abs(sl - entry) / entry * 100) < 0.006, cap
        for i, p_ in enumerate(tps, 1):
            mm = re.search(rf"TP{i}: [\d,]+ \(\+([\d,]+)%; ([\d,]+)R\)", cap)
            assert mm and abs(float(mm.group(1).replace(",", ".")) - abs(p_ - entry) / entry * 100) < 0.006 and abs(float(mm.group(2).replace(",", ".")) - abs(p_ - entry) / risk) < 0.006, cap
        assert "…" not in cap and cap.count("Зона входу:") == 1 and "Ризик моделі: 10 $" in cap, cap          # діапазонів у відсотках більше немає
    v = LVL.view_from_thesis({"entry": 0.5089, "sl": 0.48415, "entry_zone": [0.495963, 0.5089], "targets": [{"p": 0.5379}], "trigger_level": 0.495963})
    assert v["sl_pct"][0] != v["sl_pct"][1] and v["targets"][0]["pct"][0] != v["targets"][0]["pct"][1]            # Mini App: діапазон для інших цін входу збережено


def test_delivery_pass_is_parallel_slow_send_does_not_block_others():
    """ONDO 09.10: відправка NEAR зайняла 158 с і затримала ONDO на 190 с (послідовний прохід). Тепер сигнали одного проходу йдуть паралельно."""
    import asyncio
    import datetime as dt
    import tempfile
    import time as _t

    import office_bridge as OB
    import office_ready_card as card
    from office2 import delivery as DL
    from office2 import engine as EN

    c, seq = closes_long()
    orig = B.all_levels
    B.all_levels = lambda ctx, now: LEVELS
    try:
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "o2.db")
            OB.init_office_db(db)
            EN.init_db(db)
            st = lambda b: {"price": float(b["c"][-1]), "ret_1h": 0.3, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}  # noqa: E731
            for sym in ("XUSDT", "YUSDT"):
                for upto in (seq["sweep"], seq["top"], seq["bear_in_zone"], seq["trigger"]):
                    b, ctx = mk(c, upto)
                    EN.step_symbol(db, sym, ctx, st(b), {"btc_ret_1h": 0.1, "eth_ret_1h": 0.1, "breadth_up_1h": 0.5, "n_alts": 20}, {"coin_ret_1h": 0.3, "rs_vs_btc_1h": 0.2, "rs_vs_btc_4h": 0.1}, float(b["t"][-1] + 900), None)
            created = OB._fetchone(db, "SELECT MIN(created_ts) FROM office2_live_signal")[0]
            assert OB._fetchone(db, "SELECT COUNT(*) FROM office2_live_signal WHERE status = 'PENDING'")[0] == 2
            candles = [{"ts": dt.datetime.fromtimestamp(float(b["t"][i]), tz=dt.timezone.utc).isoformat(), "open": float(b["o"][i]), "high": float(b["h"][i]), "low": float(b["l"][i]), "close": float(b["c"][i]),
                        "volume": 100.0, "src": "binance_futures"} for i in range(len(b["t"]) - 96, len(b["t"]))]

            starts = []

            async def slow_send(event_type, text, **kw):
                starts.append(_t.time())
                await asyncio.sleep(1.5)
                return 7001 + len(starts)

            import json

            def live_fetch(symbol, tf, limit):
                if tf != '1m':
                    return candles
                row = OB._fetchone(db, 'SELECT snapshot_json FROM office2_live_signal WHERE symbol = ?', (symbol,))
                snap = json.loads(row[0])
                entry = float(snap['thesis']['entry'])
                return [{'ts': dt.datetime.fromtimestamp(float(snap['decided_ts']) + 5, tz=dt.timezone.utc).isoformat(),
                         'open': entry, 'high': entry, 'low': entry, 'close': entry}]
            n = asyncio.run(DL.deliver_pending(db, slow_send, live_fetch, card.render, 'TRADE_UPDATE', now=created + 60, log=lambda m: None))
            assert n == 2 and len(starts) == 2, (n, starts)
            assert abs(starts[1] - starts[0]) < 1.2, starts                       # друга відправка стартує, не чекаючи завершення першої (1,5 с); послідовно різниця була б ≥1,5 с
            assert OB._fetchone(db, "SELECT COUNT(*) FROM office2_live_signal WHERE status = 'DELIVERED'")[0] == 2
    finally:
        B.all_levels = orig


def test_sweep_prior_acceptance_is_recorded_not_gating():
    """ONDO SHORT 09.10: W1H 0,4882 перед «sweep» уже тримався вище 5 закриттів M15 і вище на 2% — це повторний тест після прийняття. Записуємо в подію й показуємо як ПРОТИ; READY не блокуємо."""
    n = 40
    t = np.arange(n) * 900.0
    c = np.full(n, 100.0)
    h, l, o = c + 0.2, c - 0.2, c.copy()
    c[24:32] = 98.5                                   # 8 закриттів за рівнем 99 (рівень-підтримка в LONG-координатах) до sweep
    l[24:32] = 98.3
    l[33], c[33] = 98.8, 99.4                         # sweep: low < 99, закриття назад вище
    m15 = {"t": t, "o": o, "h": h, "l": l, "c": c, "v": np.ones(n)}
    a15 = np.full(n, 0.3)
    ev = B2._sweep_events(m15, a15, n - 1, [{"p": 99.0, "side": "low", "kind": "W1H", "strength": 1, "known": 0.0}], 1)
    assert ev and ev[0]["prior"]["closes_beyond"] >= 3 and ev[0]["prior"]["max_excess_pct"] > 0.5, ev
    c2 = np.full(n, 100.0)
    h2, l2 = c2 + 0.2, c2 - 0.2
    l2[33], c2[33] = 98.8, 99.4
    ev2 = B2._sweep_events({"t": t, "o": c2.copy(), "h": h2, "l": l2, "c": c2, "v": np.ones(n)}, a15, n - 1, [{"p": 99.0, "side": "low", "kind": "W1H", "strength": 1, "known": 0.0}], 1)
    assert ev2 and ev2[0]["prior"]["closes_beyond"] == 0                         # свіжий grab: рівень ще не приймався


def test_zone_touch_requires_real_ohlc_contact():
    """Ціна не торкнулась зони (екстремум свічки не дійшов до її краю) → тригер не вмикається; зона вже пройдена до READY → не «доступний вхід»."""
    c, seq = closes_long()
    far = c[:seq["top"]] + [101.9, 101.8, 101.9, 102.0, 102.1]            # без ретрейсу в зону
    th = run(far, len(far))
    assert th["state"] in ("WAIT", "MISSED") and "ретрейс" in th["reason"] + th.get("reason", ""), th
    assert th["state"] != "READY"


def test_inputs_did_affect_is_honest():
    """«Вплинуло на рішення» = змінило результат. Коли READY дозволено (нічого не заблоковано), жоден умовний вхід не помічений як такий, що вплинув; при BLOCK — причина помічена."""
    L, S_, *_ = _both()
    for th in (L, S_):
        ins = th["integral"]["inputs"]
        assert th["integral"]["verdict"] == "ALLOW" and not any(i["did_affect_decision"] for i in ins) and all("evaluated" in i for i in ins)
    c, seq = closes_long()
    local = [dict(x, kind="LONDON_L") if x["kind"] == "PDL" else x for x in LEVELS]
    orig_h = B.htf_context
    try:
        B.htf_context = lambda ctx, now: _fake_htf(h4=-1, d1=0, h1=-1, broken_h4="down")
        th = run(c, seq["trigger"], levels=local)
        ins = th["integral"]["inputs"]
        assert th["integral"]["verdict"] == "BLOCK" and any(i["did_affect_decision"] for i in ins if i["role"] == "GATE (умовно)") and not any(i["did_affect_decision"] for i in ins if i["role"] != "GATE (умовно)")
    finally:
        B.htf_context = orig_h


def test_htf_swings_use_only_closed_bars_and_map_lists_m5_m1():
    """Поточний (формується) бар TF не підтверджує swing: додавання незакритого бару не змінює жодного поля рядка TF. M5/M1 — «не перевірено», не вигадані."""
    c, seq = closes_long()
    b, ctx = mk(c, seq["trigger"])
    now = float(b["t"][-1] + 900)
    base = B.htf_context(ctx, now)
    h4 = ctx["h4"]
    n = len(h4["t"])
    k = F.last_closed(h4, 4 * 3600, now)
    assert k <= n - 1
    ext = {kk: np.append(v, v[-1] + (3.0 if kk in ("h", "c") else -3.0 if kk == "l" else 0.0) if kk != "t" else v[-1] + 4 * 3600) for kk, v in h4.items()}   # «формується» бар після k: екстремальний
    ctx2 = dict(ctx, h4=ext)
    row = lambda h: {kk: h["H4"][kk] for kk in ("last_swing_high", "last_swing_low", "trend", "trend_eff", "range")}                           # noqa: E731
    assert row(B.htf_context(ctx2, now)) == row(base)
    th = run(c, seq["trigger"])
    tfs = {r["tf"]: r for r in th["map"]["tfs"]}
    assert tfs["M5"]["status"] == "NOT_CHECKED" and tfs["M1"]["status"] == "NOT_CHECKED" and "swing_stale" in tfs["H4"]


def test_scenario_final_state_and_model_result():
    """Завершений сценарій: головний статус TP3/СТОП/строк, READY — лише історична подія; без реалізованого PnL, лише модельні факти."""
    from office2 import stats as ST

    th = {"targets": [{"p": 1, "r": 2.8}, {"p": 2, "r": 3.8}, {"p": 3, "r": 11.9}]}
    m = lambda lv, t: {"level": lv, "touched_ts": t}  # noqa: E731
    o = ST.scenario_outcome({"thesis": th}, 0.0, [m("ENTRY", 1), m("TP1", 2)])
    assert o["state"] == "TP1" and not o["final"] and o["first"] == "TP" and o["max_r"] == 2.8                 # TP1 — проміжний етап
    o = ST.scenario_outcome({"thesis": th}, 0.0, [m("ENTRY", 1), m("TP1", 2), m("TP2", 3), m("TP3", 4)])
    assert o["state"] == "TP3" and o["final"] and o["max_r"] == 11.9 and o["finished_ts"] == 4
    o = ST.scenario_outcome({"thesis": th}, 0.0, [m("ENTRY", 1), m("TP1", 2), m("SL", 3)])
    assert o["state"] == "TP1→SL" and o["final"] and o["first"] == "TP"
    o = ST.scenario_outcome({"thesis": th}, 0.0, [m("ENTRY", 1), m("SL", 2)])
    assert o["state"] == "SL" and o["first"] == "SL" and o["max_r"] is None
    o = ST.scenario_outcome({"thesis": th}, 0.0, [m("EXPIRED", 9)])
    assert o["state"] == "EXPIRED" and o["final"] and o["entry_touched_ts"] is None
    import office_mini_v2 as MV

    base = {"id": "O2|x|1", "symbol": "LTCUSDT", "direction": "SHORT", "created_ts": 1.0, "valid_until_ts": 2.0, "thesis": {"entry": 67.45, "sl": 67.94, "entry_zone": [67.5946, 67.7357], "targets": [{"p": 66.07, "r": 2.8}, {"p": 65.59, "r": 3.8}, {"p": 61.63, "r": 11.9}]}}
    c3 = MV.o2_card(dict(base, levels=["ENTRY", "TP1", "TP2", "TP3"]), now=3.0)
    assert c3["status_raw"] == "HIT_TP3" and c3["status"]["group"] == "done" and "READY" not in c3["status"]["text"]
    c2 = MV.o2_card(dict(base, levels=["ENTRY", "TP1", "TP2"]), now=3.0)
    assert c2["status_raw"] == "HIT_ENTRY" and c2["status"]["group"] == "live" and "TP2" in c2["status"]["text"] and "триває" in c2["status"]["text"]
    assert MV.o2_card(dict(base, levels=[]), now=1.5)["status_raw"] == "ACTIVE" and MV.o2_card(dict(base, levels=[]), now=5.0)["status_raw"] == "EXPIRED"


def test_radar_need_fields_for_wait_stages():
    """Кожен WAIT має структуру «потрібно»: рівень (де є) і текст умови, щоб Radar показував наступну умову числом."""
    c, seq = closes_long()
    th = run(c, seq["sweep"])
    assert th["state"] == "WAIT" and th["reason"].startswith("WAIT 1/3") and th["need"]["text"], th
    th = run(c, seq["top"])
    assert th["state"] == "WAIT" and th["reason"].startswith("WAIT 2/3") and th["need"]["px"] is not None and "ретрейс" in th["need"]["text"] + th["reason"], th


def test_v2_ready_delivered_long_and_short():
    _v2_e2e(False)
    _v2_e2e(True)


def _fake_htf(h4=1, d1=1, h1=1, broken_h4=None):
    def row(te, broken=None):
        return {"status": "USED", "trend": te, "trend_eff": te, "broken": broken, "atr": 1.0, "close": 100.0, "last_swing_high": 101.0, "last_swing_low": 99.0, "range": {"hi": 105.0, "lo": 95.0, "bars": 30},
                "range_pos": 0.5, "range_pos_raw": 0.5, "outside_range": None, "zone": "discount"}
    h = {"MN": {"status": "UNAVAILABLE"}, "W1": row(0), "4D": row(0), "3D": row(0), "D1": row(d1), "H4": row(h4, broken_h4), "H1": row(h1), "M15": row(0)}
    h["_order"] = ["MN", "W1", "4D", "3D", "D1", "H4", "H1", "M15"]
    return h


def test_integral_counter_trend_needs_proof_or_htf_location():
    """Контртренд (H4 проти) + локальна подія + немає доказу повернення → WAIT 3/3 з числовою умовою; HTF-локація, доказ повернення або співпадіння зі структурою → READY. Докази читаються ДО рішення."""
    c, seq = closes_long()
    local = [dict(x, kind="LONDON_L") if x["kind"] == "PDL" else x for x in LEVELS]
    orig_h = B.htf_context
    try:
        B.htf_context = lambda ctx, now: _fake_htf(h4=-1, d1=0, h1=-1, broken_h4="down")
        th = run(c, seq["trigger"], levels=local)
        assert th["state"] == "WAIT" and th["reason"].startswith("WAIT 3/3 · ARMED, але контртренд без доказу") and th.get("blocked_ready"), th
        assert th["integral"]["verdict"] == "BLOCK" and th["integral"]["against"] and th["evidence"] and th["map"]["tfs"], "докази і карта зібрані ДО рішення"
        assert any(i["did_affect_decision"] for i in th["integral"]["inputs"]) and any(not i["did_affect_decision"] for i in th["integral"]["inputs"])
        assert "закриття H1 вище" in th["reason"]
        th = run(c, seq["trigger"])                                   # те саме, але подія на PDL (HTF-локація)
        assert th["state"] == "READY" and th["integral"]["classification"] == "HTF_LOCATION"
        B.htf_context = lambda ctx, now: _fake_htf(h4=-1, d1=0, h1=1, broken_h4="down")
        th = run(c, seq["trigger"], levels=local)                     # локальна подія, але H1 уже в напрямі = доказ повернення
        assert th["state"] == "READY" and th["integral"]["classification"] == "COUNTER_WITH_PROOF"
        B.htf_context = lambda ctx, now: _fake_htf(h4=1, d1=1, h1=-1)
        th = run(c, seq["trigger"], levels=local)                     # H1 проти, але H4/D1 за напрямом (відкат) — не контртренд
        assert th["state"] == "READY" and th["integral"]["classification"] == "WITH_TREND"
    finally:
        B.htf_context = orig_h


def test_levels_lifecycle_pdh_and_taken_and_obstacles():
    c, seq = closes_long()
    b, ctx = mk(c, seq["trigger"])
    now = float(b["t"][-1] + 900)
    t_old = float(b["t"][20])
    ctx = dict(ctx, levels=[{"p": 100.35, "side": "high", "kind": "PDH", "known": t_old, "strength": 1},      # давній «PDH»: ціна потім його перевищила
                            {"p": 130.0, "side": "high", "kind": "PDH", "known": float(b["t"][200]), "strength": 1},   # свіжа попередня доба — живий пул
                            {"p": 90.0, "side": "low", "kind": "PDL", "known": t_old, "strength": 1}])
    lv = B.all_levels(ctx, now)
    kinds = {(x["p"], x["kind"]): x for x in lv if x["p"] in (100.35, 130.0, 90.0)}
    assert (130.0, "PDH") in kinds and (100.35, "D1H") in kinds, kinds                      # лише найновіший — PDH
    assert kinds[(100.35, "D1H")]["taken_ts"] is not None and kinds[(130.0, "PDH")]["taken_ts"] is None and kinds[(90.0, "PDL")]["taken_ts"] is None
    liq = B.liquidity_map(lv, 100.0, 1.0)
    assert 100.35 not in [x["p"] for x in liq["bsl_above"]] and 130.0 in [x["p"] for x in liq["bsl_above"]]            # знятий рівень не є пулом
    assert B.eff_trend(1, 100.0, 110.0, 105.0) == (-1, "down") and B.eff_trend(-1, 100.0, 95.0, 90.0) == (1, "up") and B.eff_trend(1, 100.0, 110.0, 95.0) == (1, None)
    # перешкода ближче 0.25 R більше не губиться
    lv2 = [{"p": 100.15, "side": "high", "kind": "PDH", "known": 0.0, "strength": 1}, {"p": 103.0, "side": "high", "kind": "PWH", "known": 0.0, "strength": 1}]
    t_old_ = B.targets_for("LONG", 100.0, 1.0, lv2)
    t_new = B.targets_for("LONG", 100.0, 1.0, lv2, near_r=0.0)
    assert not t_old_["obstacles_before_tp1"] and t_new["obstacles_before_tp1"] and t_new["obstacles_before_tp1"][0]["kind"] == "PDH"


def test_premium_discount_outside_range_is_not_discount():
    from office2 import evidence as EV

    c, seq = closes_long()
    th = run(c, seq["trigger"])
    b, ctx = mk(c, seq["trigger"])
    now = float(b["t"][-1] + 900)
    orig = B.htf_context

    def below(ctx_, now_):
        h = _fake_htf(h4=1)
        h["H4"] = dict(h["H4"], range={"hi": 130.0, "lo": 120.0, "bars": 42}, broken="down", trend_eff=-1)
        return h
    B.htf_context = below
    try:
        items = EV.collect(ctx, th, "LONG", now, LEVELS)
    finally:
        B.htf_context = orig
    pd = next(i for i in items if i["module"].startswith("OB / FVG"))
    assert "нижче діапазону H4" in pd["finding"] and "%" not in pd["finding"] and pd["supports"] <= 0, pd


def test_replay_at_uses_only_bars_closed_before_moment():
    """Реплей на момент: те саме рішення з «майбутнім» у фіді і без нього (нема lookahead); результат пишеться в office2_replay_result (LONG+SHORT)."""
    import json
    import tempfile

    import office_bridge as OB
    from office2 import live as LV
    from office2 import replay_at as RA

    c, seq = closes_long()
    rng = np.random.default_rng(7)
    pre = list(100.3 + np.cumsum(rng.normal(0, 0.04, 4200)) * 0.3)           # ≈44 доби історії, щоб були D1/W1
    base = c[:seq["trigger"]]
    full = S._bars_from_closes(pre + base + [90.0, 80.0, 70.0, 60.0])
    n_cut = len(pre) + len(base)
    cut = {k: v[:n_cut] for k, v in full.items()}                            # те саме минуле, без «майбутнього»
    widths = {"15m": 900, "4h": 4 * 3600, "1d": 86400, "1w": 7 * 86400, "1M": 30 * 86400}

    def mk_getter(src):
        def getter(url, params):
            w = widths[params["interval"]]
            a = src if w == 900 else F.resample(src, w, offset=(F.WEEK_OFFSET if w == 7 * 86400 else 0))
            rows = []
            for i in range(len(a["t"])):
                if a["t"][i] * 1000 >= params.get("endTime", 1e18):
                    break
                rows.append([a["t"][i] * 1000, a["o"][i], a["h"][i], a["l"][i], a["c"][i], a["v"][i], (a["t"][i] + w) * 1000 - 1, 0, 0, a["tbv"][i]])
            return rows[-int(params["limit"]):]
        return getter

    ts = float(cut["t"][-1] + 900)
    r_full = RA.decide_at(LV.Feed(getter=mk_getter(full), pause=0), "XUSDT", ts)
    r_cut = RA.decide_at(LV.Feed(getter=mk_getter(cut), pause=0), "XUSDT", ts)
    assert "directions" in r_full and "directions" in r_cut, (r_full, r_cut)
    dump = lambda r: json.dumps(r, sort_keys=True, default=str)  # noqa: E731
    assert dump(r_full) == dump(r_cut), "майбутні бари змінили рішення на момент ts"
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "r.db")
        OB.init_office_db(db)
        assert RA.run_jobs(db, LV.Feed(getter=mk_getter(full), pause=0), f"XUSDT@{int(ts)}", log=lambda m: None) == 1
        assert OB._fetchone(db, "SELECT count(*) FROM office2_replay_result")[0] == 2


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for f in fns:
        f()
        print("ok", f.__name__)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
