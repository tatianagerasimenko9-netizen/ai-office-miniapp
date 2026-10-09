#!/usr/bin/env python3
"""Затримка READY → Telegram: пул з'єднань PostgreSQL, адаптивний старт циклу, очікування короткого backoff Binance, хронологія в мс, відсікання STALE/MISSED/INVALIDATED
із закриттям сценарію, паралельна доставка без повторів, перцентилі. Без мережі."""
import asyncio
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_office2_brain2 as T  # noqa: E402
import office_bridge as OB  # noqa: E402
import office_ready_card as card  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2 import delivery as DL  # noqa: E402
from office2 import engine as EN  # noqa: E402
from office2 import live as LV  # noqa: E402
from office2 import stats as ST  # noqa: E402


# ---------------------------------------------------------------- пул з'єднань
class _Cur:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q, p=()):
        if self.conn.dead:
            raise FakePG.OperationalError("SSL SYSCALL error: EOF detected")
        self.conn.queries.append(q)
        self.rows = [(1,)]

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self):
        self.closed = False
        self.dead = False
        self.queries = []

    def cursor(self):
        return _Cur(self)

    def execute(self, q):
        if self.dead:
            raise FakePG.OperationalError("dead")
        self.queries.append(q)

    def close(self):
        self.closed = True


class FakePG:
    class OperationalError(Exception):
        pass

    class InterfaceError(Exception):
        pass

    made = []

    @classmethod
    def connect(cls, dsn, autocommit=False, connect_timeout=None):
        assert autocommit is True and connect_timeout
        c = _Conn()
        cls.made.append(c)
        return c


def test_pg_pool_reuses_connections_and_survives_dead_ones():
    orig = OB.psycopg
    OB.psycopg = FakePG
    OB._PG_POOL.clear()
    for k in OB._PG_STATS:
        OB._PG_STATS[k] = 0
    FakePG.made.clear()
    dsn = "postgresql://u:p@h/db"
    try:
        for _ in range(20):                                              # 20 запитів → одне з'єднання, а не 20
            OB._fetchone(dsn, "SELECT 1")
        OB._execute(dsn, "UPDATE x SET y = ?", (1,))
        OB._fetchall(dsn, "SELECT * FROM x")
        assert len(FakePG.made) == 1 and OB.pg_pool_stats()["reuses"] >= 21, (len(FakePG.made), OB.pg_pool_stats())
        FakePG.made[0].dead = True                                       # з'єднання вмерло на боці сервера
        assert OB._fetchone(dsn, "SELECT 1") == (1,)                     # читання прозоро повторюється на новому з'єднанні
        assert len(FakePG.made) == 2 and OB.pg_pool_stats()["retries"] == 1
        FakePG.made[1].dead = True
        try:
            OB._execute(dsn, "INSERT INTO x VALUES (?)", (1,))
            raise AssertionError("запис на мертвому з'єднанні не повторюється (щоб не задвоїти)")
        except FakePG.OperationalError:
            pass
        OB._PG_POOL[dsn] = [(c, time.monotonic() - 999) for c in OB._PG_POOL.get(dsn, [])]
        assert OB._fetchone(dsn, "SELECT 1") == (1,)                     # завислу в пулі перевіряємо SELECT 1 і відкидаємо мертву
        # паралельні потоки не ділять одне з'єднання одночасно
        OB._PG_POOL.clear()
        out = []

        def work():
            for _ in range(10):
                out.append(OB._fetchone(dsn, "SELECT 1"))

        ths = [threading.Thread(target=work) for _ in range(4)]
        [t.start() for t in ths]
        [t.join() for t in ths]
        assert len(out) == 40 and OB.pg_pool_stats()["idle"] <= OB._PG_MAX_IDLE
    finally:
        OB.psycopg = orig
        OB._PG_POOL.clear()


# ---------------------------------------------------------------- адаптивний старт і backoff
def test_wait_bar_closed_polls_until_bar_is_available():
    bar_close = 1_800_000_000.0
    calls = {"n": 0}

    class F:
        def _get(self, url, params):
            calls["n"] += 1
            if calls["n"] < 3:
                return [[int((bar_close - 1800) * 1000)], [int((bar_close - 900) * 1000)]]          # закритий бар ще не віддано
            return [[int((bar_close - 900) * 1000)], [int(bar_close * 1000)]]

    clock = {"t": 0.0}
    waited = LV.wait_bar_closed(F(), bar_close, sleep=lambda s: clock.__setitem__("t", clock["t"] + s), clock=lambda: clock["t"])
    assert calls["n"] == 3 and 1.5 <= waited <= 3.5, (calls, waited)                     # ~2 с замість фіксованих 20
    never = {"t": 0.0}

    class Dead:
        def _get(self, url, params):
            raise RuntimeError("net")

    w2 = LV.wait_bar_closed(Dead(), bar_close, sleep=lambda s: never.__setitem__("t", never["t"] + s), clock=lambda: never["t"])
    assert w2 >= LV.BAR_PROBE_MAX_SEC - 1                                                    # межа очікування: цикл не зависає


def test_feed_waits_short_binance_backoff_but_not_long():
    import office_market_data as MD

    feed = LV.Feed(pause=0)
    saved = (MD._BACKOFF_UNTIL, MD.hard_backoff_left, MD._http_get_json, time.sleep)
    slept = []
    seen_priority = []
    try:
        MD.hard_backoff_left = lambda: 4.0

        def get(url, params):
            seen_priority.append(bool(getattr(MD._PRIORITY, "on", False)))
            return [["ok"]]

        MD._http_get_json = get
        time.sleep = lambda s: slept.append(s)
        assert feed._default_get("u", {}) == [["ok"]] and slept and 4.0 <= slept[0] <= 5.5       # коротка пауза 429 перечекана, символи не пропущені
        assert seen_priority == [True] and not getattr(MD._PRIORITY, "on", False)                # запит Brain іде як «життя READY» (м'яка пауза ваги його не блокує), прапорець знято після
        MD.hard_backoff_left = lambda: 200.0
        try:
            feed._default_get("u", {})
            raise AssertionError("довгий backoff має перервати")
        except RuntimeError as e:
            assert "backoff" in str(e)
    finally:
        MD.hard_backoff_left, MD._http_get_json, time.sleep = saved[1], saved[2], saved[3]


# ---------------------------------------------------------------- доставка
class Sent:
    def __init__(self, delay=0.0):
        self.calls = []
        self.delay = delay

    async def __call__(self, event_type, text, **kw):
        self.calls.append((time.time(), text, kw))
        if self.delay:
            await asyncio.sleep(self.delay)
        return 9000 + len(self.calls)


def _make_pending(syms=("XUSDT",), long=True):
    c, seq = T.closes_long()
    td = tempfile.mkdtemp()
    db = os.path.join(td, "o2.db")
    OB.init_office_db(db)
    EN.init_db(db)
    st = lambda b: {"price": float(b["c"][-1]), "ret_1h": 0.3, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}  # noqa: E731
    EN.CYCLE_TIMES.clear()
    for sym in syms:
        for upto in (seq["sweep"], seq["top"], seq["bear_in_zone"], seq["trigger"]):
            b, ctx = T.mk(c, upto)
            now = float(b["t"][-1] + 900)
            if upto == seq["trigger"]:
                EN.CYCLE_TIMES.update(bar_close=now, wake=time.time() - 3.0, bar_ready=time.time() - 2.0, cycle_start=time.time() - 2.0, fetch_done=time.time() - 1.0)
            EN.step_symbol(db, sym, ctx, st(b), {"btc_ret_1h": 0.1, "eth_ret_1h": 0.1, "breadth_up_1h": 0.5, "n_alts": 20}, {"coin_ret_1h": 0.3, "rs_vs_btc_1h": 0.2, "rs_vs_btc_4h": 0.1}, now, None)
    created = OB._fetchone(db, "SELECT MIN(created_ts) FROM office2_live_signal")[0]
    return db, b, created


def _candles(b):
    return [{"ts": dt.datetime.fromtimestamp(float(b["t"][i]), tz=dt.timezone.utc).isoformat(), "open": float(b["o"][i]), "high": float(b["h"][i]), "low": float(b["l"][i]), "close": float(b["c"][i]),
             "volume": 100.0, "src": "binance_futures"} for i in range(len(b["t"]) - 96, len(b["t"]))]


def test_delivery_uses_decision_candles_not_rest_and_records_ms_timeline():
    orig = B.all_levels
    B.all_levels = lambda ctx, now: T.LEVELS
    try:
        db, b, created = _make_pending()
        snap = json.loads(OB._fetchone(db, "SELECT snapshot_json FROM office2_live_signal")[0])
        assert len(snap["chart_candles"]) == 96 and snap["latency"]["bar_close"] and snap["latency"]["fetch_done"], list(snap)
        seen = []

        def fetch(sym, tf, lim):
            seen.append((tf, lim))
            return _candles(b) if tf == "15m" else _candles(b)[-int(lim):]

        sent = Sent()
        n = asyncio.run(DL.deliver_pending(db, sent, fetch, card.render, "TRADE_UPDATE", now=created + 25, log=lambda m: None))
        assert n == 1 and all(tf != "15m" for tf, _ in seen), seen                         # графік із свічок рішення; REST лише для перевірки актуальності (1m)
        ev = OB._fetchone(db, "SELECT payload_json FROM office_events WHERE event_type = 'OFFICE2_READY_SENT'")[0]
        tm = json.loads(ev)["timing"]
        for k in ("wake_ms", "bar_wait_ms", "fetch_ms", "brain_ms", "queue_ms", "late_check_ms", "chart_ms", "render_ms", "send_ms", "bar_to_sent_ms", "decision_to_sent_ms"):
            assert k in tm and tm[k] is not None, (k, tm)
        assert "⏱" not in sent.calls[0][1]                                                  # вчасно: позначки про запізнення немає
        lat = ST.latency(db, now=time.time())
        assert lat["delivered_n"] == 1 and lat["new_format_n"] == 1 and lat["stages"]["send_ms"]["n"] == 1 and "p95" in lat["stages"]["send_ms"]
    finally:
        B.all_levels = orig


def test_late_delivery_is_marked_and_stale_or_missed_closes_scenario():
    orig = B.all_levels
    B.all_levels = lambda ctx, now: T.LEVELS
    try:
        db, b, created = _make_pending()
        sent = Sent()
        n = asyncio.run(DL.deliver_pending(db, sent, lambda s_, tf, lim: _candles(b)[-int(lim):], card.render, "TRADE_UPDATE", now=created + 300, log=lambda m: None))
        assert n == 1 and "⏱ Рішення було о" in sent.calls[0][1] and "доставлено через 5 хв" in sent.calls[0][1], sent.calls[0][1]      # запізнення не приховується
        # STALE: доставка пізніше за ліміт → не шлемо, сценарій закрито з причиною
        db2, b2, created2 = _make_pending()
        sent2 = Sent()
        n2 = asyncio.run(DL.deliver_pending(db2, sent2, lambda s_, tf, lim: _candles(b2)[-int(lim):], card.render, "TRADE_UPDATE", now=created2 + DL.STALE_PENDING_SEC + 5, log=lambda m: None))
        row = OB._fetchone(db2, "SELECT status, last_error FROM office2_live_signal")
        sc = OB._fetchone(db2, "SELECT state, reason FROM office2_live_scenario")
        tr = OB._fetchall(db2, "SELECT to_state, version FROM office2_live_transition WHERE to_state = 'MISSED'")
        assert n2 == 0 and not sent2.calls and row[0] == "SUPPRESSED" and row[1].startswith("STALE") and sc[0] == "MISSED" and sc[1].startswith("STALE") and tr, (row, sc, tr)
        # MISSED: ціна втекла далеко за рівень тригера
        db3, b3, created3 = _make_pending()
        th = json.loads(OB._fetchone(db3, "SELECT snapshot_json FROM office2_live_signal")[0])["thesis"]
        run_away = _candles(b3)[-4:]
        for r in run_away:
            r["high"] = th["entry"] + 30 * th["risk"]
            r["close"] = th["entry"] + 29 * th["risk"]
            r["ts"] = dt.datetime.fromtimestamp(created3 + 20, tz=dt.timezone.utc).isoformat()
        sent3 = Sent()
        n3 = asyncio.run(DL.deliver_pending(db3, sent3, lambda s_, tf, lim: _candles(b3)[:-4] + run_away if tf == "1m" else _candles(b3), card.render, "TRADE_UPDATE", now=created3 + 30, log=lambda m: None))
        sc3 = OB._fetchone(db3, "SELECT state, reason FROM office2_live_scenario")
        assert n3 == 0 and not sent3.calls and sc3[0] in ("MISSED", "INVALIDATED"), (n3, sc3)
        assert OB._fetchone(db3, "SELECT status FROM office2_live_signal")[0] == "SUPPRESSED"
    finally:
        B.all_levels = orig


def test_inflight_signals_are_not_sent_twice_and_slow_one_does_not_block():
    orig = B.all_levels
    B.all_levels = lambda ctx, now: T.LEVELS
    try:
        db, b, created = _make_pending(("XUSDT", "YUSDT"))
        sent = Sent(delay=1.2)

        async def two_overlapping_passes():
            f = lambda s_, tf, lim: _candles(b)[-int(lim):]                       # noqa: E731
            p1 = asyncio.ensure_future(DL.deliver_pending(db, sent, f, card.render, "TRADE_UPDATE", now=created + 20, log=lambda m: None))
            await asyncio.sleep(0.4)
            p2 = asyncio.ensure_future(DL.deliver_pending(db, sent, f, card.render, "TRADE_UPDATE", now=created + 21, log=lambda m: None))   # наступний прохід, поки перші ще відправляються
            return await asyncio.gather(p1, p2)

        r = asyncio.run(two_overlapping_passes())
        assert sorted(r) == [0, 2] and len(sent.calls) == 2, (r, len(sent.calls))      # другий прохід нічого не відправив повторно; обидва сигнали пішли паралельно
        assert abs(sent.calls[1][0] - sent.calls[0][0]) < 1.0, "відправки мають стартувати майже одночасно"
        assert OB._fetchone(db, "SELECT COUNT(*) FROM office2_live_signal WHERE status = 'DELIVERED'")[0] == 2 and not DL._INFLIGHT
    finally:
        B.all_levels = orig


def test_old_lev_ingestion_runs_in_background_and_does_not_hold_the_cycle():
    """Спостереження за рішеннями старого Лева (свічки Binance по 3–4 с на монету поза universe) не входить у критичний шлях бару → READY."""
    td = tempfile.mkdtemp()
    db = os.path.join(td, "o2.db")
    OB.init_office_db(db)
    LV.init_db(db)
    started, finished = [], []

    def slow(db_, feed_, now_, states_, mc_, state_):
        started.append(time.time())
        time.sleep(0.8)
        finished.append(time.time())
        return 3

    orig = LV._ingest_old_lev
    LV._ingest_old_lev = slow
    try:
        feed = LV.Feed(getter=lambda url, params: [], pause=0)
        t0 = time.time()
        res = LV.cycle(db, feed, 1_800_000_000.0, {"last_plan_id": 0}, ["XUSDT"], old_lev_background=True)
        dur = time.time() - t0
        assert dur < 0.6 and res["old_lev"] == 0 and "brain_s" in res and "slow_ms" in res, (dur, res)      # цикл повернувся, поки фон ще працює
        time.sleep(1.2)
        assert started and finished                                                                         # фон відпрацював
        res2 = LV.cycle(db, feed, 1_800_000_900.0, {"last_plan_id": 0}, ["XUSDT"], old_lev_background=False)
        assert res2["old_lev"] == 3                                                                         # синхронний режим (тести/реплей) як і раніше
    finally:
        LV._ingest_old_lev = orig


def test_latency_percentiles_and_targets():
    td = tempfile.mkdtemp()
    db = os.path.join(td, "o2.db")
    OB.init_office_db(db)
    EN.init_db(db)
    for i, (d2s, b2s) in enumerate(((4000, 20000), (6000, 28000), (9000, 33000), (30000, 80000))):
        OB.log_event(db, "OFFICE2_READY_SENT", {"scenario_id": f"O2|a{i}|1", "timing": {"decision_to_sent_ms": d2s, "bar_to_sent_ms": b2s, "send_ms": d2s - 1000, "queue_ms": 100}}, f"O2|a{i}|1")
    lat = ST.latency(db)
    assert lat["stages"]["decision_to_sent_ms"]["p50"] == 7500.0 and lat["stages"]["decision_to_sent_ms"]["p99"] == 29370.0 and lat["stages"]["decision_to_sent_ms"]["max"] == 30000.0
    assert lat["within_target"] == {"decision_to_sent": (3, 4), "bar_to_sent": (2, 4)}, lat["within_target"]       # чесно: ціль досягнуто не завжди


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
