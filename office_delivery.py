"""Ідемпотентна доставка в Telegram: одна логічна доставка на (повідомлення, місце призначення).

Проблема (05.10, IO): Bot API прийняв sendPhoto, але клієнт отримав таймаут (`exception: ` без тексту) → код вважав доставку невдалою і слав копію
через Telethon → дубль у чаті. Тут:
  * чітка відмова Telegram (HTTP/JSON з помилкою) або збій ДО відправки (з'єднання не встановлено) = «точно не доставлено» → можна запасний шлях;
  * таймаут/обрив після відправки = «неоднозначно» → спершу звірка (чи повідомлення вже в чаті), потім, якщо звірка можлива і нічого немає, один повтор;
  * якщо звірка недоступна — утримуємо (без другої копії) на hold_sec, далі один повтор з позначкою «непідтверджено»;
  * після успіху той самий ключ більше не відправляється (TTL).
Без торгової логіки: лише транспорт.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

# Помилки ДО відправки: запит не міг дійти до Telegram → безпечно пробувати інший шлях.
_CLEAN_EXC = ("FileNotFoundError", "PermissionError", "ClientConnectorError", "ClientConnectorDNSError", "ClientConnectorCertificateError",
              "ClientConnectorSSLError", "InvalidURL", "gaierror", "ConnectionRefusedError", "NoReturn")


class ReconcileUnavailable(Exception):
    """Звірка неможлива (немає прав/останнього id): відповідь «чи доставлено» невідома."""


@dataclass
class Outcome:
    ok: bool
    msg_id: Optional[int]
    reason: str
    ambiguous: bool = False       # доставка могла відбутися, але не підтверджена
    reconciled: bool = False      # знайдено у чаті після таймауту (без повторної відправки)
    suppressed: bool = False      # вже доставлено раніше за цим ключем
    resent_unverified: bool = False


def delivery_key(kind: str, scenario_id: str, chat_id: Any, thread_id: Any, text: str = "") -> str:
    """scenario/plan + тип + призначення (+ короткий хеш тексту, щоб різні події одного сценарію не склеювались)."""
    h = hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()[:10] if text else ""
    return f"{kind}|{scenario_id}|{chat_id}|{thread_id or 0}|{h}"


def is_ambiguous(reason: str) -> bool:
    """True, якщо запит міг дійти до Telegram: `exception: <Type>...` (таймаут/обрив) без відповіді сервера."""
    r = str(reason or "")
    if not r.startswith("exception:"):
        return False   # «telegram: ...», «http NNN», «telegram photo: ...» — сервер відповів помилкою
    tail = r[len("exception:"):].strip()
    typ = tail.split(":", 1)[0].strip() if tail else ""
    if typ in _CLEAN_EXC:
        return False
    return True   # порожній тип (старий формат), TimeoutError, ServerDisconnectedError, ClientOSError, ...


@dataclass
class _State:
    state: str            # accepted | ambiguous | failed
    msg_id: Optional[int]
    t0: float
    updated: float


class DeliveryLedger:
    def __init__(self, ttl: float = 900.0, hold_sec: float = 120.0, settle_sec: float = 3.0,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.ttl = ttl
        self.hold_sec = hold_sec
        self.settle_sec = settle_sec
        self._clock = clock
        self._sleep = sleep
        self._st: Dict[str, _State] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self.stats: Dict[str, int] = {"sent": 0, "suppressed": 0, "reconciled": 0, "ambiguous": 0, "held": 0, "resent_unverified": 0, "clean_fail": 0, "resent_proven": 0}

    def _gc(self) -> None:
        now = self._clock()
        for k in [k for k, v in self._st.items() if now - v.updated > self.ttl]:
            self._st.pop(k, None)
            self._locks.pop(k, None)

    def state_of(self, key: str) -> Optional[str]:
        st = self._st.get(key)
        return st.state if st else None

    async def deliver(self, key: str, attempt: Callable[[], Awaitable[Tuple[bool, str, Optional[int]]]],
                      reconcile: Optional[Callable[[float], Awaitable[Optional[int]]]] = None, max_sends: int = 2) -> Outcome:
        self._gc()
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            st = self._st.get(key)
            if st and st.state == "accepted":
                self.stats["suppressed"] += 1
                return Outcome(True, st.msg_id, "already_delivered", suppressed=True)
            resent_unverified = False
            if st and st.state == "ambiguous":   # попередня спроба була неоднозначною: спершу звіряємо, не шлемо
                found = None
                try:
                    found = await reconcile(st.t0) if reconcile else (_ for _ in ()).throw(ReconcileUnavailable("no reconcile"))
                except ReconcileUnavailable:
                    if self._clock() - st.t0 < self.hold_sec:
                        self.stats["held"] += 1
                        return Outcome(False, None, "ambiguous: delivery unverified, held", ambiguous=True)
                    resent_unverified = True
                if found:
                    self._st[key] = _State("accepted", int(found), st.t0, self._clock())
                    self.stats["reconciled"] += 1
                    return Outcome(True, int(found), "reconciled", reconciled=True)
            sends = 0
            last_reason = ""
            while sends < max_sends:
                sends += 1
                t0 = self._clock()
                ok, reason, mid = await attempt()
                if ok:
                    self._st[key] = _State("accepted", mid, t0, self._clock())
                    self.stats["sent"] += 1
                    if resent_unverified:
                        self.stats["resent_unverified"] += 1
                    return Outcome(True, mid, "ok", resent_unverified=resent_unverified)
                last_reason = reason
                if not is_ambiguous(reason):
                    self._st[key] = _State("failed", None, t0, self._clock())
                    self.stats["clean_fail"] += 1
                    return Outcome(False, None, reason)
                self.stats["ambiguous"] += 1
                await self._sleep(self.settle_sec)
                try:
                    if reconcile is None:
                        raise ReconcileUnavailable("no reconcile")
                    found = await reconcile(t0)
                except ReconcileUnavailable:
                    self._st[key] = _State("ambiguous", None, t0, self._clock())
                    self.stats["held"] += 1
                    return Outcome(False, None, reason, ambiguous=True)
                if found:
                    self._st[key] = _State("accepted", int(found), t0, self._clock())
                    self.stats["reconciled"] += 1
                    return Outcome(True, int(found), "reconciled", reconciled=True)
                self.stats["resent_proven"] += 1   # звірка працює і повідомлення в чаті немає → друга спроба безпечна
            self._st[key] = _State("failed", None, self._clock(), self._clock())
            return Outcome(False, None, f"exhausted: {last_reason}")
