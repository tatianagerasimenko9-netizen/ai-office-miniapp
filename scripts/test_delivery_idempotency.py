#!/usr/bin/env python3
"""Ідемпотентна доставка: Telegram прийняв повідомлення, але клієнт отримав таймаут (випадок IO 05.10). Без мережі."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_delivery as D  # noqa: E402


class FakeChat:
    """Чат: send() додає повідомлення; режими: ok / accept_then_timeout / lose_then_timeout / clean_error."""

    def __init__(self):
        self.msgs = []
        self.mode = "ok"
        self.next_id = 9000
        self.probe_works = True

    async def send(self, text):
        mode = self.mode
        if mode == "clean_error":
            return False, "telegram photo: Bad Request: wrong file", None
        if mode == "accept_then_timeout":
            self.next_id += 1
            self.msgs.append((self.next_id, text))
            return False, "exception: TimeoutError: ", None
        if mode == "lose_then_timeout":
            return False, "exception: TimeoutError: ", None
        self.next_id += 1
        self.msgs.append((self.next_id, text))
        return True, "ok", self.next_id

    async def reconcile(self, text, t0):
        if not self.probe_works:
            raise D.ReconcileUnavailable("no history")
        for mid, t in self.msgs:
            if t == text:
                return mid
        return None


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s


def mk(clock):
    return D.DeliveryLedger(ttl=900, hold_sec=120, settle_sec=3, clock=clock, sleep=clock.sleep)


def run(coro):
    return asyncio.run(coro)


def test_accept_then_timeout_no_duplicate():
    async def go():
        c, clk = FakeChat(), Clock()
        led = mk(clk)
        c.mode = "accept_then_timeout"
        key = D.delivery_key("CONFIRM", "SCN|IOUSDT|SHORT|H1|x", -100, 5, "txt")
        out = await led.deliver(key, lambda: c.send("txt"), lambda t0: c.reconcile("txt", t0))
        assert out.ok and out.reconciled and out.msg_id == 9001, out
        assert len(c.msgs) == 1, c.msgs            # головне: ОДНЕ повідомлення, не два
        out2 = await led.deliver(key, lambda: c.send("txt"), lambda t0: c.reconcile("txt", t0))
        assert out2.ok and out2.suppressed and len(c.msgs) == 1
    run(go())


def test_lost_then_timeout_resend_once():
    async def go():
        c, clk = FakeChat(), Clock()
        led = mk(clk)
        c.mode = "lose_then_timeout"

        async def attempt():
            if led.stats["ambiguous"] >= 1:
                c.mode = "ok"   # другий запит проходить
            return await c.send("t")
        out = await led.deliver("k", attempt, lambda t0: c.reconcile("t", t0))
        assert out.ok and len(c.msgs) == 1 and led.stats["resent_proven"] == 1, (out, c.msgs, led.stats)
    run(go())


def test_reconcile_unavailable_holds_then_flags():
    async def go():
        c, clk = FakeChat(), Clock()
        led = mk(clk)
        c.mode = "accept_then_timeout"
        c.probe_works = False
        out = await led.deliver("k", lambda: c.send("t"), lambda t0: c.reconcile("t", t0))
        assert not out.ok and out.ambiguous and len(c.msgs) == 1       # без другої копії
        clk.t += 30
        out = await led.deliver("k", lambda: c.send("t"), lambda t0: c.reconcile("t", t0))
        assert not out.ok and out.ambiguous and len(c.msgs) == 1 and led.stats["held"] == 2
        c.probe_works = True   # звірка з'явилась → знаходимо, не шлемо
        out = await led.deliver("k", lambda: c.send("t"), lambda t0: c.reconcile("t", t0))
        assert out.ok and out.reconciled and len(c.msgs) == 1
    run(go())


def test_hold_expires_resend_flagged():
    async def go():
        c, clk = FakeChat(), Clock()
        led = mk(clk)
        c.mode = "lose_then_timeout"
        c.probe_works = False
        out = await led.deliver("k", lambda: c.send("t"), lambda t0: c.reconcile("t", t0))
        assert out.ambiguous and len(c.msgs) == 0
        clk.t += 200   # hold минув: звірка досі неможлива → один повтор із позначкою
        c.mode = "ok"
        out = await led.deliver("k", lambda: c.send("t"), lambda t0: c.reconcile("t", t0))
        assert out.ok and out.resent_unverified and len(c.msgs) == 1 and led.stats["resent_unverified"] == 1
    run(go())


def test_clean_error_allows_fallback_and_is_not_ledgered_as_sent():
    async def go():
        c, clk = FakeChat(), Clock()
        led = mk(clk)
        c.mode = "clean_error"
        out = await led.deliver("k", lambda: c.send("t"), lambda t0: c.reconcile("t", t0))
        assert not out.ok and not out.ambiguous and led.state_of("k") == "failed"
        c.mode = "ok"   # запасний шлях/повтор того ж ключа дозволений
        out = await led.deliver("k", lambda: c.send("t"), lambda t0: c.reconcile("t", t0))
        assert out.ok and len(c.msgs) == 1
    run(go())


def test_concurrent_same_key_single_send():
    async def go():
        c, clk = FakeChat(), Clock()
        led = mk(clk)
        outs = await asyncio.gather(*[led.deliver("k", lambda: c.send("t"), lambda t0: c.reconcile("t", t0)) for _ in range(4)])
        assert len(c.msgs) == 1 and sum(1 for o in outs if o.suppressed) == 3, (c.msgs, outs)
    run(go())


def test_is_ambiguous():
    assert D.is_ambiguous("exception: ")                              # старий формат (IO)
    assert D.is_ambiguous("exception: TimeoutError: ")
    assert D.is_ambiguous("exception: ServerDisconnectedError: x")
    assert not D.is_ambiguous("exception: ClientConnectorError: cannot connect")   # до відправки
    assert not D.is_ambiguous("exception: FileNotFoundError: x.png")
    assert not D.is_ambiguous("telegram photo: Bad Request")
    assert not D.is_ambiguous("http 429: {}")
    assert not D.is_ambiguous("ok")


def test_transport_does_not_retry_ambiguous_and_reports_type():
    import office_relay_wizard as W

    class Sess:
        def __init__(self, exc):
            self.calls = 0
            self.exc = exc

        def post(self, *a, **k):
            self.calls += 1
            raise self.exc

    async def go():
        se = Sess(asyncio.TimeoutError())
        ok, reason, mid = await W.send_via_bot_api(se, "t", 1, "x", reply_markup={"inline_keyboard": []}, retries=2, timeout_sec=1)
        assert not ok and se.calls == 1 and D.is_ambiguous(reason) and "TimeoutError" in reason, (se.calls, reason)   # без повтору: Telegram міг прийняти
        class ClientConnectorError(Exception):   # як aiohttp.ClientConnectorError: з'єднання не встановлено
            pass
        se2 = Sess(ClientConnectorError("refused"))
        ok, reason, mid = await W.send_via_bot_api(se2, "t", 1, "x", reply_markup={"inline_keyboard": []}, retries=2, timeout_sec=1)
        assert se2.calls == 3 and not D.is_ambiguous(reason), (se2.calls, reason)   # збій ДО відправки: повтор безпечний
        se3 = Sess(asyncio.TimeoutError())
        ok, reason, mid = await W.send_via_bot_photo(se3, "t", 1, __file__)
        assert not ok and D.is_ambiguous(reason) and "TimeoutError" in reason, reason   # раніше: порожній `exception: `
    asyncio.run(go())


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
