#!/usr/bin/env python3
"""Office 2.0 LIVE BETA: мозок (теза A/B, структурний SL, цілі, no-chase), відсутність lookahead, стани WATCH→WAIT→READY, портфельний ризик, outbox,
доставка (Telegram-картка + запис плану), lifecycle (TP/SL), ідемпотентність і рестарт. Без мережі."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import o2live_synth as S  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2 import delivery as DL  # noqa: E402
from office2 import engine as EN  # noqa: E402
from office2 import features as F  # noqa: E402


def ctx_at(m15):
    return B.build_full_ctx(m15, F.resample(m15, 4 * 3600), F.resample(m15, 86400), F.resample(m15, 7 * 86400, offset=F.WEEK_OFFSET))


def extend(bars, tail):
    """Додає бари в кінець, НЕ змінюючи жодного існуючого (інакше тест lookahead порівнював би різні історії)."""
    t = S._bars_from_closes(np.r_[bars["c"][-1], tail], start_t=float(bars["t"][-1]))
    return {k: np.r_[bars[k], t[k][1:]] for k in ("t", "o", "h", "l", "c", "v", "tbv")}


def mirror_bars(bars):
    return {"t": bars["t"], "o": 200.0 - bars["o"], "h": 200.0 - bars["l"], "l": 200.0 - bars["h"], "c": 200.0 - bars["c"], "v": bars["v"], "tbv": bars["tbv"]}


def now_of(b):
    return float(b["t"][-1] + 900)


def test_movr_long_ready_with_structural_sl_and_real_targets():
    bars, _ = S.build()
    seq = []
    for tail in ([], [103.6], [103.6, 103.8], [103.6, 103.8, 103.9]):
        b = extend(bars, tail) if tail else bars
        th = B.pullback_break(ctx_at(b), "LONG", now_of(b))
        seq.append(th["state"] if th else None)
    assert seq == ["WAIT", "WAIT", "READY_CANDIDATE", "READY_CANDIDATE"], seq     # злам без утримання — ще WAIT; READY лише після утримання
    b = extend(bars, [103.6, 103.8, 103.9])
    ctx = ctx_at(b)
    d = B.decide(B.pullback_break(ctx, "LONG", now_of(b)), ctx, now_of(b))
    assert d["state"] == "READY", d
    assert d["sl"] < d["entry"] < d["targets"][0]["p"]
    inv = d["invalidation"]["price"]
    assert d["sl"] < inv and d["invalidation"]["buffer"] > 0 and ("проколів" in d["invalidation"]["buffer_basis"] or "fallback" in d["invalidation"]["buffer_basis"])   # SL нижче структурної інвалідації на доказовий буфер
    assert d["targets"][0]["r"] >= B.MIN_TP1_R and d["targets"][0]["kind"]                                                           # ціль = реальний рівень, не RR
    assert abs(d["risk"] - (d["entry"] - d["sl"])) < 1e-9 and abs(d["sizing"]["notional_usd"] - 10.0 / (d["risk"] / d["entry"])) < 1e-6


def test_movr_short_mirror():
    bars, _ = S.build()
    b = mirror_bars(extend(bars, [103.6, 103.8, 103.9]))
    ctx = ctx_at(b)
    th = B.pullback_break(ctx, "SHORT", now_of(b))
    assert th and th["state"] == "READY_CANDIDATE", th
    d = B.decide(th, ctx, now_of(b))
    assert d["state"] == "READY" and d["sl"] > d["entry"] > d["targets"][0]["p"], d


def test_no_chase_missed_and_zone_broken():
    bars, _ = S.build()
    far = extend(bars, [103.6, 103.8, 105.4, 106.5])      # ціна втекла далеко від рівня пробою
    ctx = ctx_at(far)
    th = B.pullback_break(ctx, "LONG", now_of(far))
    d = B.decide(th, ctx, now_of(far))
    assert d["state"] in ("MISSED", "NO_TRADE"), d
    broke = extend(bars, [99.5, 99.0, 98.8, 98.6, 98.5, 98.5, 98.4, 98.5])                    # дно відкату пробило зону origin
    th = B.pullback_break(ctx_at(broke), "LONG", now_of(broke))
    assert th and th["state"] == "INVALIDATED", th


def test_no_lookahead_decision_identical_with_future_bars():
    bars, _ = S.build()
    b = extend(bars, [103.6, 103.8, 103.9])
    now = now_of(b)
    ctx1 = ctx_at(b)
    fut = extend(b, [90.0, 80.0, 120.0, 130.0])           # майбутнє, яке на момент now не існувало
    ctx2 = ctx_at(fut)
    for d in ("LONG", "SHORT"):
        a = B.decide(B.pullback_break(ctx1, d, now) or {"state": None}, ctx1, now)
        c = B.decide(B.pullback_break(ctx2, d, now) or {"state": None}, ctx2, now)
        assert json.dumps(EN._clean(a), sort_keys=True) == json.dumps(EN._clean(c), sort_keys=True), d
    p1, p2 = B.context_pack(ctx1, now), B.context_pack(ctx2, now)
    assert json.dumps(EN._clean(p1), sort_keys=True) == json.dumps(EN._clean(p2), sort_keys=True)


def test_choch_requires_trend():
    flat = S._bars_from_closes(100 + 0.001 * np.arange(300) * ((-1) ** np.arange(300)))
    ls = B.local_structure(flat, now_of(flat), 900)
    assert ls["trend"] == 0 and ls["event"] is None            # без тренду CHoCH/BOS не називаємо


def _mc(btc=-0.7):
    return {"btc_ret_1h": btc, "eth_ret_1h": -0.4, "breadth_up_1h": 0.4, "n_alts": 20}


def _st(px):
    return {"price": px, "ret_1h": 0.38, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}


def _rel():
    return {"coin_ret_1h": 0.38, "rs_vs_btc_1h": 1.08, "rs_vs_btc_4h": 0.5}


def _db(td):
    import office_bridge as OB

    db = str(Path(td) / "o2live.db")
    OB.init_office_db(db)
    EN.init_db(db)
    return db


def _drive(db, bars, tails, sym="XUSDT", start_mc=None):
    out = []
    for tail in tails:
        b = extend(bars, tail) if tail else bars
        now = now_of(b)
        out.append(EN.step_symbol(db, sym, ctx_at(b), _st(float(b["c"][-1])), start_mc or _mc(), _rel(), now, None))
    return out


def test_state_machine_watch_wait_ready_and_frozen_snapshot():
    import office_bridge as OB

    bars, _ = S.build()
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        tails = [[], [103.6], [103.6, 103.8], [103.6, 103.8, 103.9], [103.6, 103.8, 103.9, 104.0]]
        _drive(db, bars, tails)
        rid = OB._fetchone(db, "SELECT scenario_id FROM office2_live_scenario WHERE state = 'READY'")[0]
        states = [r[0] for r in OB._fetchall(db, "SELECT to_state FROM office2_live_transition WHERE scenario_id = ? ORDER BY ts ASC", (rid,))]
        assert states == ["WAIT", "READY"], states                                   # сценарій провели WAIT → READY (не стрибок)
        assert OB._fetchone(db, "SELECT COUNT(*) FROM office2_live_transition WHERE to_state = 'MISSED'")[0] >= 1   # пізній вхід по іншій тезі став MISSED, не READY
        sig = OB._fetchall(db, "SELECT scenario_id, status, snapshot_json FROM office2_live_signal")
        assert len(sig) == 1 and sig[0][1] == "PENDING" and sig[0][0].startswith(rid)                     # один READY, повторні цикли не дублюють
        snap = json.loads(sig[0][2])
        assert snap["label"] == "OFFICE2 · LIVE BETA" and snap["evidence_status"] == "UNPROVEN"
        for key in ("thesis", "context", "market_at_signal", "trace", "why"):
            assert key in snap
        assert any("BTC" in t["step"] for t in snap["trace"]) and "відносно" in snap["why"] and "BTC −0,70%" in snap["why"]
        # знімок заморожений: ще цикли (з майбутнім) його не змінюють
        _drive(db, bars, [[103.6, 103.8, 103.9, 104.0, 104.5]])
        sig2 = OB._fetchall(db, "SELECT snapshot_json FROM office2_live_signal")
        assert len(sig2) == 1 and sig2[0][0] == sig[0][2]


def test_portfolio_gate():
    import office_bridge as OB

    now = 1_790_100_000.0
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)

        def put(sid, sym, d, status="DELIVERED"):
            OB._execute(db, "INSERT INTO office2_live_signal(scenario_id, symbol, direction, created_ts, valid_until_ts, status, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?)",
                        (sid, sym, d, now - 100, now + 3600, status, json.dumps({"thesis": {"level": {"p": 1.5}}}), "t"))

        put("O2|a|1", "AAAUSDT", "LONG")
        assert EN.portfolio_gate(db, "AAAUSDT", "SHORT", None, now) == "по цій монеті вже є живий сигнал Office2"
        assert EN.portfolio_gate(db, "BBBUSDT", "LONG", "BBBUSDT|LONG|1.5", now) is None
        put("O2|b|1", "BBBUSDT", "LONG")
        assert "та сама ідея" in (EN.portfolio_gate(db, "CCCUSDT", "LONG", "AAAUSDT|LONG|1.5", now) or "")      # та сама ідея/рівень
        put("O2|c|1", "CCCUSDT", "LONG")
        deny = EN.portfolio_gate(db, "DDDUSDT", "LONG", None, now)
        assert deny and ("кластер" in deny or "альтів" in deny), deny                                           # 4-й альт: ліміт кластера/однонапрямлених
        assert EN.portfolio_gate(db, "BTCUSDT", "LONG", None, now) is None                                      # BTC — окремий кластер
        for i in range(3):                                                         # 3 стопи за добу → стоп
            OB.log_event(db, "SCENARIO_MILESTONE", {"level": "SL", "sent_ts": now - 50 - i}, f"O2|x{i}|1")
        assert "денний ліміт" in (EN.portfolio_gate(db, "BTCUSDT", "LONG", None, now) or "")


class _Sent:
    def __init__(self):
        self.calls = []

    async def __call__(self, event_type, text, **kw):
        self.calls.append((event_type, text, kw))
        return 7000 + len(self.calls)


def _candles(m15, upto=96):
    import datetime as dt

    out = []
    for i in range(len(m15["t"]) - upto, len(m15["t"])):
        out.append({"ts": dt.datetime.fromtimestamp(float(m15["t"][i]), tz=dt.timezone.utc).isoformat(), "open": float(m15["o"][i]), "high": float(m15["h"][i]),
                    "low": float(m15["l"][i]), "close": float(m15["c"][i]), "volume": 100.0, "src": "binance_futures"})
    return out


def test_delivery_end_to_end_and_lifecycle():
    import office_alert_gate as AG
    import office_bridge as OB
    import office_ready_card as card
    import office_signal_track as trk

    bars, _ = S.build()
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        _drive(db, bars, [[103.6], [103.6, 103.8], [103.6, 103.8, 103.9]])
        b = extend(bars, [103.6, 103.8, 103.9])
        sent = _Sent()
        created = OB._fetchone(db, "SELECT created_ts FROM office2_live_signal")[0]
        n = asyncio.run(DL.deliver_pending(db, sent, lambda s, tf, lim: _candles(b), card.render, "TRADE_UPDATE", now=created + 60, log=lambda m: None))
        assert n == 1 and len(sent.calls) == 1
        ev, text, kw = sent.calls[0]
        assert text.startswith("OFFICE2 · LIVE BETA\n🟢 LONG · X") and "Чому:" in text and "READY:" in text and "SL:" in text and "TP1:" in text and "Ризик: 10 $" in text and "⏳ до" in text
        assert not AG.text_grants_entry(text) and not AG.text_instructs_position_change(text), text      # проходить той самий Telegram-шлюз, що й старий READY
        assert kw["intent"] == "CONFIRM" and kw["kind"] == "CONFIRM" and kw["canonical_id"].startswith("O2|")
        assert kw["photo_path"] and Path(kw["photo_path"]).exists()                                        # реальний chart
        st = OB._fetchone(db, "SELECT status, msg_id FROM office2_live_signal")
        assert st == ("DELIVERED", 7001)
        plan = trk.plan_for(db, kw["canonical_id"])
        assert plan and plan["entry"] and plan["sl"] and plan["tp1"] and not plan.get("rejected") and plan["confirm_msg_id"] == 7001
        assert plan["gate"]["office2"]["label"] == "OFFICE2 · LIVE BETA" and plan["gate"]["office2"]["trace"]
        from office2 import webview as WV

        pl = WV.payload(db, now=created + 120)
        sg = pl["signals"][0]
        assert pl["label"] == "OFFICE2 · LIVE BETA" and sg["frozen"]["trace"] and sg["frozen"]["thesis"]["sl"] and sg["status"] == "DELIVERED" and "changed" in sg
        h = WV.html()
        assert "Ринок на момент сигналу" in h and ">Зараз<" in h.replace("<h2>", ">").replace("</h2>", "<") or "<h2>Зараз</h2>" in h
        assert "Що змінилося" in h and "Хід сигналу" in h and "Технічні" in h
        assert sg["status_ua"] == "Надіслано" and sg["lifecycle"] is not None and "chart" in sg
        # рестарт/повтор: другого повідомлення немає
        n2 = asyncio.run(DL.deliver_pending(db, sent, lambda s, tf, lim: _candles(b), card.render, "TRADE_UPDATE", now=created + 90, log=lambda m: None))
        assert n2 == 0 and len(sent.calls) == 1
        # lifecycle: свічки після READY → ENTRY, потім TP1 (математика SL/TP)
        e, sl, tp1 = plan["entry"], plan["sl"], plan["tp1"]
        assert sl < e < tp1
        t0 = float(plan["confirmed_ts"])
        fut = [{"ts": __import__("datetime").datetime.fromtimestamp(t0 + 900 * i, tz=__import__("datetime").timezone.utc).isoformat(), "open": e, "high": e * 1.002, "low": e * 0.999, "close": e * 1.001, "volume": 1.0}
               for i in range(2)]
        fut.append({"ts": __import__("datetime").datetime.fromtimestamp(t0 + 1800, tz=__import__("datetime").timezone.utc).isoformat(), "open": e, "high": tp1 * 1.001, "low": e * 0.999, "close": tp1, "volume": 1.0})
        res = trk.simulate(plan, fut, now_ts=t0 + 4000)
        assert "TP1" in res["reached"] and res["filled_at"] is not None
        slc = [dict(fut[0]), {"ts": fut[1]["ts"], "open": e, "high": e, "low": sl * 0.999, "close": sl, "volume": 1.0}]
        res2 = trk.simulate(plan, slc, now_ts=t0 + 4000)
        assert res2["stopped"] and res2["status"] == "STOP"


def test_delivery_rechecks_chase_and_sl_at_send_time():
    import office_bridge as OB
    import office_ready_card as card

    bars, _ = S.build()
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        _drive(db, bars, [[103.6], [103.6, 103.8], [103.6, 103.8, 103.9]])
        b = extend(bars, [103.6, 103.8, 103.9])
        created = OB._fetchone(db, "SELECT created_ts FROM office2_live_signal")[0]
        sent = _Sent()
        far = _candles(extend(bars, [103.6, 103.8, 103.9, 109.0]))      # ціна втекла вгору за час доставки
        asyncio.run(DL.deliver_pending(db, sent, lambda s, tf, lim: far if tf == "1m" else _candles(b), card.render, "TRADE_UPDATE", now=created + 60, log=lambda m: None))
        r = OB._fetchone(db, "SELECT status, last_error FROM office2_live_signal")
        assert not sent.calls and r[0] == "SUPPRESSED" and "пізній" in r[1], r
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        _drive(db, bars, [[103.6], [103.6, 103.8], [103.6, 103.8, 103.9]])
        created = OB._fetchone(db, "SELECT created_ts FROM office2_live_signal")[0]
        sent = _Sent()
        down = _candles(extend(bars, [103.6, 103.8, 103.9, 99.0]))      # ціна впала за структурний SL
        asyncio.run(DL.deliver_pending(db, sent, lambda s, tf, lim: down, card.render, "TRADE_UPDATE", now=created + 60, log=lambda m: None))
        r = OB._fetchone(db, "SELECT status, last_error FROM office2_live_signal")
        assert not sent.calls and r[0] == "SUPPRESSED" and "SL" in r[1], r


def test_delivery_failure_keeps_pending_and_stale_is_suppressed():
    import office_bridge as OB
    import office_ready_card as card

    bars, _ = S.build()
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        _drive(db, bars, [[103.6], [103.6, 103.8], [103.6, 103.8, 103.9]])
        b = extend(bars, [103.6, 103.8, 103.9])
        created = OB._fetchone(db, "SELECT created_ts FROM office2_live_signal")[0]

        async def fail(*a, **k):
            return None

        asyncio.run(DL.deliver_pending(db, fail, lambda s, tf, lim: _candles(b), card.render, "TRADE_UPDATE", now=created + 30, log=lambda m: None))
        r = OB._fetchone(db, "SELECT status, last_error FROM office2_live_signal")
        assert r[0] == "PENDING" and "не підтвердив" in r[1]
        asyncio.run(DL.deliver_pending(db, fail, lambda s, tf, lim: _candles(b), card.render, "TRADE_UPDATE", now=created + 3600, log=lambda m: None))
        assert OB._fetchone(db, "SELECT status FROM office2_live_signal")[0] == "SUPPRESSED"          # прострочений READY не шлемо із запізненням


def test_cutover_flag_defaults_keep_old_lev():
    import os

    os.environ.pop("OFFICE_OLD_READY_DELIVERY", None)
    src = Path(__file__).resolve().parent.parent.joinpath("office_relay_wizard.py").read_text(encoding="utf-8")
    assert 'os.getenv("OFFICE_OLD_READY_DELIVERY", "1").strip() == "0"' in src     # за замовчуванням старий READY доставляється; вимикається лише явним 0
    assert DL.delivery_enabled() is False


def test_live_cycle_integration_engine_on():
    """live.cycle з увімкненим рушієм на синтетичному фіді: без помилок, стани/сценарії пишуться, Telegram не потрібен."""
    import os
    import office_bridge as OB
    from office2 import live as L
    import test_office2 as T2

    os.environ["OFFICE2_LIVE"] = "1"
    try:
        days = 60
        series = {k: T2.synth(days, seed=sd, sigma=0.0035) for k, sd in (("BTCUSDT", 81), ("ETHUSDT", 82), ("XUSDT", 83), ("YUSDT", 84), ("ZUSDT", 85), ("WUSDT", 86))}
        t_end = float(series["XUSDT"]["t"][-1]) + 60
        clock = {"now": t_end - 8 * 86400}
        series["_now"] = lambda: clock["now"]
        with tempfile.TemporaryDirectory() as td:
            db = _db(td)
            L.init_db(db)
            feed = L.Feed(T2._fake_klines_getter(series), pause=0)
            now = clock["now"] // 900 * 900
            st = {"last_plan_id": 0}
            errs0 = L.stats()["errors"]
            tot = {}
            for _ in range(120):
                now += 900
                clock["now"] = now + 20
                r = L.cycle(db, feed, now, st, [k for k in series if not k.startswith("_")])
                for k, v in (r.get("live") or {}).items():
                    tot[k] = tot.get(k, 0) + v
            assert L.stats()["errors"] == errs0, L.stats()
            assert OB._fetchone(db, "SELECT COUNT(*) FROM office2_shadow_state")[0] >= 120 * 6
            assert OB._fetchone(db, "SELECT COUNT(*) FROM office2_live_scenario")[0] >= 1, tot
            n = OB._fetchone(db, "SELECT COUNT(*) FROM office2_live_scenario WHERE state = 'READY'")[0]
            assert n == OB._fetchone(db, "SELECT COUNT(*) FROM office2_live_signal")[0]       # кожен READY має рівно один outbox-запис
    finally:
        os.environ.pop("OFFICE2_LIVE", None)


def test_capacity_counts_only_really_active_scenarios():
    """Регресія: недоставлені PENDING-«призраки» (доставка лежала) займали ємність і давали «кластер ALT 40$ > 30$»; завершені (SL/EXPIRED) і SUPPRESSED — теж ні."""
    import office_bridge as OB

    now = 1_790_100_000.0
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)

        def put(sid, sym, status, age):
            OB._execute(db, "INSERT INTO office2_live_signal(scenario_id, symbol, direction, created_ts, valid_until_ts, status, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?)",
                        (sid, sym, "LONG", now - age, now + 3600, status, json.dumps({"thesis": {}}), "t"))

        for i, sym in enumerate(("AAAUSDT", "BBBUSDT", "CCCUSDT")):
            put(f"O2|g{i}|1", sym, "PENDING", 3 * 3600)               # давні недоставлені (призраки)
        put("O2|s|1", "SSSUSDT", "SUPPRESSED", 100)
        put("O2|e|1", "EEEUSDT", "DELIVERED", 100)
        OB.log_event(db, "SCENARIO_MILESTONE", {"level": "EXPIRED", "sent_ts": now - 10}, "O2|e|1")   # завершений сценарій
        assert EN.open_signals(db, now) == []
        assert EN.portfolio_gate(db, "DDDUSDT", "LONG", None, now) is None
        put("O2|f|1", "FFFUSDT", "PENDING", 60)                          # свіжий PENDING ще чекає доставки: місце займає
        assert [o["symbol"] for o in EN.open_signals(db, now)] == ["FFFUSDT"]
        deny = EN.portfolio_gate(db, "FFFUSDT", "LONG", None, now)
        assert deny
        for i, sym in enumerate(("HHHUSDT", "IIIUSDT")):
            put(f"O2|d{i}|1", sym, "DELIVERED", 60)
        deny = EN.portfolio_gate(db, "JJJUSDT", "LONG", None, now)
        assert deny and "ємність" in deny and "не твій особистий ризик" in deny, deny


def test_office2_has_own_thread_pool_not_starved():
    """Регресія: доставка Office2 стояла в черзі за довгими задачами загального пулу (рішення 14:32 → відправка 14:53). Власний пул не залежить від нього."""
    import asyncio
    import time as _t
    from office2 import delivery as DL

    async def main():
        loop = asyncio.get_running_loop()
        blockers = [loop.run_in_executor(None, _t.sleep, 1.5) for _ in range(64)]      # забиваємо загальний пул
        t0 = _t.time()
        r = await DL.run_o2(lambda a, b: a + b, 1, 2)
        dt = _t.time() - t0
        starved = None
        await asyncio.gather(*blockers)
        return r, dt, starved

    r, dt, _ = asyncio.run(main())
    assert r == 3 and dt < 0.5, (r, dt)
    import ast

    src = Path(__file__).resolve().parent.parent.joinpath("office2", "delivery.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "deliver_pending")
    assert "to_thread" not in ast.get_source_segment(src, fn)


def test_miniapp_ux_mobile_structure():
    """UX: сигнал першим екраном, сирий trace/JSON лише у «Технічних», службові статуси українською, loading/error/retry."""
    from office2 import webview as WV

    h = WV.html()
    main = h[h.index("function signal(s)"):h.index("function radar()")]
    assert "JSON.stringify" not in main and "trace" not in main.lower() and "old_lev" not in main     # сирі дані не в основному екрані
    assert "function tech()" in h and "Decision trace" in h.split("function tech()")[1]
    for bad in ("UNPROVEN", "DELIVERED", "SUPPRESSED"):
        assert bad not in main, bad
    assert "AbortController" in h and "Повторити" in h and "class=\"sk\"" in h                          # skeleton, таймаут, retry
    assert WV.STATUS_UA["DELIVERED"] == "Надіслано" and WV.STATUS_UA["SUPPRESSED"] == "Не надіслано"
    assert "viewport-fit=cover" in h


def test_miniapp_summary_never_waits_for_binance():
    """Регресія: health-check Render (/api/summary, 5 с) не має чекати на Binance: BTC беремо з кешу, оновлення у фоні."""
    import time as _t
    import office_mini_app as MA

    calls = []

    def slow_refresh():
        calls.append(1)
        _t.sleep(3)
        MA._BTC_CACHE["busy"] = False

    real = MA._btc_refresh
    MA._btc_refresh = slow_refresh
    MA._BTC_CACHE.update(ts=0.0, val=None, busy=False)
    try:
        t0 = _t.time()
        r = MA._btc_cached()
        assert _t.time() - t0 < 0.5 and r["price"] is None            # перший запит не блокується, значення ще немає
        MA._BTC_CACHE.update(ts=_t.time(), val={"price": 100.0, "change_24h": 1.0, "regime": None, "dom": None})
        assert MA._btc_cached()["price"] == 100.0                      # свіжий кеш: без мережі
    finally:
        MA._btc_refresh = real
        MA._BTC_CACHE.update(ts=0.0, val=None, busy=False)


def _sol_snap(sid="O2|solhash|1791300000"):
    return {"symbol": "SOLUSDT", "direction": "SHORT", "valid_until_ts": 1791321600.0, "why": "Sweep PWH і повернення M15 нижче рівня.", "label": "OFFICE2 · LIVE BETA", "brain": "o2-brain-1",
            "thesis": {"id": sid, "kind": "SWEEP_RECLAIM", "entry": 120.99, "trigger_level": 121.53, "sl": 122.02, "level": {"p": 121.53, "kind": "PWH"},
                       "targets": [{"p": 119.0, "r": 1.9, "kind": "LONDON_L"}, {"p": 117.0, "r": 3.9, "kind": "ASIA_L"}], "sizing": {"risk_usd": 10.0}},
            "market_at_signal": {}, "trace": [], "context": {}, "alignment": []}


def test_entry_zone_semantics_telegram_and_miniapp_agree():
    """Регресія (SOL): Telegram показував зону 120,99–121,53, а Mini App — «Вхід 120,99» і SL −0,85% лише від одного краю. Тепер: READY-ціна окремо, зона окремо, ризик/R — діапазон по краях зони; одна математика."""
    from office2 import delivery as DL
    from office2 import levels as LVL

    snap = _sol_snap()
    cap = DL.build_caption(snap)
    assert "READY: 120,99" in cap and "Зона входу: 120,99–121,53" in cap, cap
    assert "Вхід:" not in cap and "SL: 122,02 · ризик 0,40–0,85%" in cap, cap
    v = LVL.view_from_thesis(snap["thesis"])
    assert v["ready_price"] == 120.99 and v["zone"] == [120.99, 121.53]
    assert abs(v["sl_pct"][1] - (122.02 - 120.99) / 120.99 * 100) < 1e-9 and abs(v["sl_pct"][0] - (122.02 - 121.53) / 121.53 * 100) < 1e-9
    t1 = v["targets"][0]       # R від кожного краю: від 121,53 R більший, ніж від 120,99
    assert abs(t1["r"][0] - (120.99 - 119.0) / (122.02 - 120.99)) < 1e-9 and abs(t1["r"][1] - (121.53 - 119.0) / (122.02 - 121.53)) < 1e-9
    assert "TP1: 119" in cap and "…+" in cap
    # без зони (тригер = READY-ціна): одне число, без діапазонів
    th2 = dict(snap["thesis"], trigger_level=120.99)
    cap2 = DL.build_caption(dict(snap, thesis=th2))
    assert "Зона входу" not in cap2 and "SL: 122,02 · ризик 0,85%" in cap2 and "…" not in cap2, cap2
    # Mini App отримує ті самі числа з того самого модуля
    from office2 import webview as WV
    import office_bridge as OB

    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        OB._execute(db, "INSERT INTO office2_live_signal(scenario_id, symbol, direction, created_ts, valid_until_ts, status, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?)",
                    ("O2|solhash|1791300000", "SOLUSDT", "SHORT", 1791300000.0, 1791321600.0, "DELIVERED", json.dumps(snap), "t"))
        pl = WV.payload(db, now=1791300500.0, focus="O2|solhash|1791300000")
        assert pl["signals"][0]["levels"] == json.loads(json.dumps(v))
    h = WV.html()
    assert "READY" in h and "Зона входу" in h and "Вхід</span>" not in h


def test_lifecycle_button_opens_parent_scenario():
    """Регресія: «📊 Сценарій» під TP1/SL мала id події («…|ct|TP1») → «Сигнал не знайдено». Тепер релей передає scenario_id батька; сервер також розв'язує старі посилання подій за БД."""
    import ast
    from office2 import webview as WV
    import office_bridge as OB

    src = Path(__file__).resolve().parent.parent.joinpath("office_relay_wizard.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "monitor_scenario_milestones")
    body = ast.get_source_segment(src, fn)
    assert 'link_scenario_id=str(m["scenario_id"])' in body
    assert src.count("scenario_id=link_scenario_id or scenario_id") == 2        # і текстова, і фото-відправка
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        for k in range(25):          # батьківський сценарій старший за «останні 20»
            sid = f"O2|h{k:02d}|{1791200000 + k * 900}"
            OB._execute(db, "INSERT INTO office2_live_signal(scenario_id, symbol, direction, created_ts, valid_until_ts, status, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?)",
                        (sid, f"C{k}USDT", "SHORT", 1791200000.0 + k * 900, 1791300000.0, "DELIVERED", json.dumps(_sol_snap(sid)), "t"))
        parent = "O2|h00|1791200000"
        OB.log_event(db, "SCENARIO_MILESTONE", {"scenario_id": parent, "level": "TP1", "touched_ts": 1791200900.0, "sent_ts": 1791200950.0, "price": 119.0}, parent)
        OB.log_event(db, "SCENARIO_MILESTONE", {"scenario_id": parent, "level": "SL", "touched_ts": 1791201900.0, "sent_ts": 1791201950.0, "price": 122.02}, parent)
        for ev_id in (parent, parent + "|1791200000.0|TP1", parent + "|1791200000.0|SL"):      # прямий id та id lifecycle-подій
            pl = WV.payload(db, now=1791202000.0, focus=ev_id)
            assert pl["focus"] == parent and pl["focus_found"], ev_id
            top = pl["signals"][0]
            assert top["id"] == parent and [m["level"] for m in top["lifecycle"]] == ["TP1", "SL"]       # «Хід сигналу» актуальний
        pl = WV.payload(db, now=1791202000.0, focus="O2|nope|1")                      # невідомий id: чесно «не знайдено», але загальний список завантажується окремо
        assert pl["focus_found"] is False and pl["focus"] == "" and len(pl["signals"]) == 20
    h = WV.html()
    assert "Не вдалося знайти цей сценарій" in h


def test_runtime_guard_and_delivery_timing():
    """Стійкість worker: пул потоків ≥8, memory guard не падає, delivery пише тайминги етапів, старий Лев після cutover — тихий і рідший."""
    import ast
    import office_runtime_guard as RG

    assert RG.default_executor_workers() >= 8
    r = RG.rss_mb()
    assert r is None or r > 10
    assert RG.trim_memory() in (True, False)
    root = Path(__file__).resolve().parent.parent
    src = root.joinpath("office_relay_wizard.py").read_text(encoding="utf-8")
    assert "set_default_executor" in src and "start_memory_guard" in src
    body = ast.get_source_segment(src, next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "monitor_scenario_milestones"))
    assert "_legacy_quiet" in body and "OFFICE_OLD_READY_DELIVERY" in body and "300" in body
    dsrc = root.joinpath("office2", "delivery.py").read_text(encoding="utf-8")
    for k in ("pickup_s", "late_check_s", "fetch_s", "render_s", "send_s", "emit_to_sent_s"):
        assert k in dsrc, k
    assert "emitted_wall_ts" in root.joinpath("office2", "engine.py").read_text(encoding="utf-8")


def test_stats_outcomes_and_against_buckets():
    """Накопичення LIVE BETA: стан/R з frozen-знімка і lifecycle, розріз за кількістю ПРОТИ (0/1/2+); SL до TP = −1R; результат сценарію ≠ особиста угода."""
    from office2 import stats as ST
    from office2 import webview as WV
    import office_bridge as OB

    with tempfile.TemporaryDirectory() as td:
        db = _db(td)

        def put(sid, sym, against, miles, status="DELIVERED"):
            snap = _sol_snap(sid)
            snap["symbol"] = sym
            snap["alignment_summary"] = {"for": 1, "against": against, "neutral": 0}
            OB._execute(db, "INSERT INTO office2_live_signal(scenario_id, symbol, direction, created_ts, valid_until_ts, status, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?)",
                        (sid, sym, "SHORT", 1791300000.0, 1791321600.0, status, json.dumps(snap), "t"))
            for lvl, ts in miles:
                OB.log_event(db, "SCENARIO_MILESTONE", {"scenario_id": sid, "level": lvl, "touched_ts": ts, "sent_ts": ts + 30, "price": 1.0}, sid)

        put("O2|a|1", "AAAUSDT", 0, [("ENTRY", 1791300060.0), ("TP1", 1791300600.0)])                     # TP1 → +1,9 R
        put("O2|b|1", "BBBUSDT", 2, [("ENTRY", 1791300060.0), ("SL", 1791300900.0)])                      # SL → −1 R
        put("O2|c|1", "CCCUSDT", 1, [("ENTRY", 1791300060.0), ("TP1", 1791300600.0), ("SL", 1791301200.0)])  # TP1, потім SL
        put("O2|d|1", "DDDUSDT", 1, [])                                                                    # чекає входу
        put("O2|e|1", "EEEUSDT", 0, [("EXPIRED", 1791320000.0)])                                           # входу не було
        put("O2|f|1", "FFFUSDT", 3, [], status="SUPPRESSED")
        st = ST.collect(db)
        t = st["total"]
        assert t["ready"] == 6 and t["delivered"] == 5 and t["not_sent"] == 1 and t["tp"] == 2 and t["sl"] == 1 and t["waiting_entry"] == 1 and t["expired"] == 1, t
        b = st["by_against"]
        assert b["0"]["n"] == 2 and b["0"]["closed"] == 1 and abs(b["0"]["sum_r"] - 1.9) < 1e-9
        assert b["1"]["n"] == 2 and b["2+"]["n"] == 1 and abs(b["2+"]["sum_r"] + 1.0) < 1e-9
        by = {i["id"]: i for i in st["items"]}
        assert by["O2|a|1"]["state"] == "TP1" and by["O2|c|1"]["state"] == "TP1→SL" and by["O2|a|1"]["time_to_entry_s"] == 60.0 and by["O2|a|1"]["order"] == ["ENTRY", "TP1"]
        pl = WV.payload(db, now=1791301500.0)
        assert pl["stats"]["total"]["delivered"] == 5
    assert "накопичено" in WV.html() and "Не підключено" in WV.html()


def test_brain_modules_audit_is_honest():
    from office2 import brain as B

    m = B.MODULES
    assert set(m) >= {"active", "context_only", "research", "unavailable_today"}
    blob = " ".join(m["unavailable_today"]).lower()
    for must in ("m5/m1", "order book", "gex", "ob / breaker"):
        assert must in blob, must
    assert not any("OI/funding" in x for x in m["active"])        # FLOW не в рішенні


def test_loop_lag_watchdog_reports_blocker_and_scan_is_nonblocking():
    """Синхронні мережеві виклики в proactive_market_scan блокували цикл подій після рестарту (доставка Office2 чекала 10+ хв). Тепер вони в потоках; сторожовий потік показує блокувальника."""
    import asyncio
    import re
    import time as _t
    import office_runtime_guard as RG

    logs = []

    async def main():
        loop = asyncio.get_running_loop()
        RG.start_loop_lag_watchdog(loop, log=logs.append, threshold_sec=0.6, period_sec=0.2)
        await asyncio.sleep(0.5)
        _t.sleep(1.6)                  # імітація синхронного блокування циклу
        await asyncio.sleep(0.5)

    asyncio.run(main())
    assert any("[loop-lag]" in x and "test_office2_live.py" in x for x in logs), logs
    src = Path(__file__).resolve().parent.parent.joinpath("office_relay_wizard.py").read_text(encoding="utf-8")
    a, b = src.index("async def proactive_market_scan"), src.index("async def monitor_proactive_scanner")
    body = src[a:b]
    assert not re.search(r"(?<![\w.])(?<!to_thread, )(fetch_candles|fetch_top_movers|fetch_atr_context|fetch_market_regime|compute_gerchik_ops|fetch_liquidations_proxy|fetch_open_interest)\(", re.sub(r"(from|import)[^\n]*\n", "", body)), "синхронний мережевий виклик у async-сканері"
    assert "start_loop_lag_watchdog" in src


def test_btc_case_noise_stop_and_room_to_first_real_target_are_no_trade():
    """Регресія (BTC 06.10): SHORT READY зі стопом 0,67 ATR(M15) (всередині шуму) і реальним рівнем NY_L на 0,71 R до TP1 → через хвилини SL. Тепер: NO TRADE з числами, стоп не розширюємо і не стискаємо."""
    bars, _ = S.build()
    b = extend(bars, [103.6, 103.8, 103.9])
    ctx = ctx_at(b)
    now = now_of(b)
    base = B.pullback_break(ctx, "LONG", now)
    ok = B.decide(dict(base), ctx, now)
    assert ok["state"] == "READY" and ok["quality"]["risk_atr15"] >= B.MIN_STOP_ATR15 and ok["quality"]["first_target_r"] >= B.MIN_TP1_R
    k = F.last_closed(ctx["m15"], 900, now)
    entry, a15 = float(ctx["m15"]["c"][k]), float(ctx["atr15"][k])
    tight = dict(base, sl=entry - 0.67 * a15, trigger_level=entry)                       # стоп у межах однієї свічки
    d = B.decide(tight, ctx, now)
    assert d["state"] == "NO_TRADE" and "всередині нормального шуму" in d["reason"] and d["quality"]["risk_atr15"] < 1.0, d
    risk = entry - float(base["sl"])
    real_levels = [{"p": entry + 0.7 * risk, "side": "high", "kind": "NEW_YORK_H", "known": 0.0, "strength": 1}, {"p": entry + 3.0 * risk, "side": "high", "kind": "PDH", "known": 0.0, "strength": 2}]
    orig = B.all_levels
    try:
        B.all_levels = lambda c, n: real_levels
        d2 = B.decide(dict(base), ctx, now)
        assert d2["state"] == "NO_TRADE" and "до першої реальної цілі NEW_YORK_H" in d2["reason"] and abs(d2["quality"]["first_target_r"] - 0.7) < 1e-6, d2
        B.all_levels = lambda c, n: [dict(real_levels[0], kind="M15SW"), real_levels[1]]   # дрібний M15-свінг — не перешкода
        d3 = B.decide(dict(base), ctx, now)
        assert d3["state"] == "READY" and d3["targets"][0]["kind"] == "PDH", d3
    finally:
        B.all_levels = orig


def test_late_guard_catches_sl_touched_before_delivery():
    """Регресія (BTC): SL торкнули о 18:01, а READY відправили о 18:02 — гарда дивилась лише на останню ціну. Тепер дивиться на high/low усіх 1m-свічок від моменту рішення."""
    from office2 import delivery as DL

    snap = {"decided_ts": 1000.0, "thesis": {"entry": 100.0, "sl": 101.0, "trigger_level": 100.2}}
    def mk(ts, o, h, l, c):
        return {"ts": ts, "open": o, "high": h, "low": l, "close": c}
    rows = [mk(940.0, 100, 100.3, 99.9, 100.1), mk(1000.0, 100, 100.4, 99.8, 100.0), mk(1060.0, 100.0, 101.2, 99.9, 100.1), mk(1120.0, 100.1, 100.2, 99.7, 99.9)]   # хвилина 1060: high ≥ SL, далі ціна повернулась
    why = DL._late_reason(snap, lambda s, tf, n: rows, "BTCUSDT", "SHORT", now=1200.0)
    assert why and "торкнулась структурного SL" in why, why
    ok_rows = [mk(1000.0, 100, 100.4, 99.8, 100.0), mk(1060.0, 100.0, 100.5, 99.9, 100.1)]
    assert DL._late_reason(snap, lambda s, tf, n: ok_rows, "BTCUSDT", "SHORT", now=1200.0) is None
    old = [mk(940.0, 100, 101.5, 99.9, 100.1)] + ok_rows                                  # свічка ДО рішення з high ≥ SL не рахується
    assert DL._late_reason(snap, lambda s, tf, n: old, "BTCUSDT", "SHORT", now=1200.0) is None


def test_relay_delivery_task_has_all_names():
    """Регресія: у production monitor_office2_delivery падав NameError (fetch_candles імпортується локально в інших функціях relay)."""
    import ast

    src = Path(__file__).resolve().parent.parent.joinpath("office_relay_wizard.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "monitor_office2_delivery")
    body = ast.get_source_segment(src, fn)
    assert "from office_market_data import fetch_candles as _o2_fetch" in body and "fetch_candles, _o2card" not in body
    assert "deliver_pending(db_path, send_proactive, _o2_fetch," in body


def test_alignment_labels_against_and_for():
    from office2 import align as AL

    # FIL SHORT: монета сильніша за BTC на +0,29 п.п. → ПРОТИ SHORT; BTC −0,34% → ЗА SHORT
    it = AL.alignment("SHORT", {"btc_ret_1h": -0.34, "breadth_up_4h": 0.3}, {"rs_vs_btc_1h": 0.29}, {"H4": {"trend": -1}, "D1": {"trend": 1}})
    by = {i["factor"]: i for i in it}
    assert by["відносна сила vs BTC (1г)"]["verdict"] == "ПРОТИ SHORT" and "відносна сила: ПРОТИ SHORT" in by["відносна сила vs BTC (1г)"]["text"]
    assert by["BTC за годину"]["verdict"] == "ЗА SHORT" and by["breadth альтів 4г"]["verdict"] == "ЗА SHORT"
    assert by["тренд H4"]["verdict"] == "ЗА SHORT" and by["тренд D1"]["verdict"] == "ПРОТИ SHORT"
    assert AL.alignment("LONG", {}, {"rs_vs_btc_1h": 0.05})[0]["verdict"] == "НЕЙТРАЛЬНО"
    assert AL.summary(it) == {"for": 3, "against": 2, "neutral": 0}


def test_miniapp_opens_office2_scenario_ids():
    """Регресія: Mini App показував «Сценарій недоступний» для O2|… (сценарій є лише в office2_live_signal)."""
    import office_mini_v2 as MV
    import office_ready_card as card
    import office_bridge as OB
    from office2 import webview as WV

    sid = "O2|abc123|1791291600"
    r = MV.scenario_detail(sid)
    assert not r["ok"] and r["redirect"].startswith("/office2?id=O2%7Cabc123%7C")
    html = Path(__file__).resolve().parent.parent.joinpath("office_web", "mini_v2.html").read_text(encoding="utf-8")
    assert "startsWith('O2|')" in html and "d.redirect" in html and "location.href='/office2?id='" in html
    bars, _ = S.build()
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        _drive(db, bars, [[103.6], [103.6, 103.8], [103.6, 103.8, 103.9]])
        real = OB._fetchone(db, "SELECT scenario_id FROM office2_live_signal")[0]
        pl = WV.payload(db, focus=real)
        assert pl["focus_found"] and pl["signals"][0]["id"] == real
        al = pl["signals"][0]["frozen"]["alignment"]
        assert al and any(a["verdict"].startswith(("ЗА", "ПРОТИ", "НЕЙТРАЛЬНО")) for a in al)
        assert not WV.payload(db, focus="O2|нема|1")["focus_found"]
        assert "FQ" in WV.html() and "Чому" in WV.html() and "alignment" in WV.html()


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
