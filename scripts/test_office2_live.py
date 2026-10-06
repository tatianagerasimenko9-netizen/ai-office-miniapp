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
        assert text.startswith("OFFICE2 · LIVE BETA\n🟢 LONG · X") and "Чому:" in text and "Вхід:" in text and "Стоп:" in text and "TP1:" in text and "Ризик: 10 $" in text and "⏳ до" in text
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
        assert "РИНОК НА МОМЕНТ СИГНАЛУ".lower() in WV.html().lower() or "Ринок на момент сигналу" in WV.html()
        assert "Ринок зараз" in WV.html() and "Що змінилося" in WV.html()
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


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
