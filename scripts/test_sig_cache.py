#!/usr/bin/env python3
"""Кеш важких читань office_signals: попадання, скидання записом через _execute, ізоляція копій, вимкнення TTL=0; відсутність зависань доставки Office2 (окремі пули)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_bridge as OB


def _db(td):
    db = str(Path(td) / "c.db")
    OB.init_office_db(db)
    return db


def _ins(db, sid, status="WATCHING", note="scenario_id=S1"):
    OB._execute(db, "INSERT INTO office_signals(signal_id, symbol, direction, status, ts_created, ts_updated, analysis_note) VALUES (?,?,?,?,?,?,?)",
                (sid, "AAAUSDT", "LONG", status, "2026-10-10T00:00:00+00:00", "2026-10-10T00:00:00+00:00", note))


def test_cache_hit_and_write_invalidation():
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        _ins(db, "a")
        OB._SIG_CACHE_STATS.update(hits=0, misses=0)
        assert len(OB.signal_get_active(db)) == 1
        assert len(OB.signal_get_active(db)) == 1
        assert OB._SIG_CACHE_STATS["hits"] == 1 and OB._SIG_CACHE_STATS["misses"] == 1
        _ins(db, "b")                                            # запис через _execute скидає кеш → одразу видно новий рядок
        assert len(OB.signal_get_active(db)) == 2
        OB.signal_update(db, signal_id="a", status="EXPIRED")
        assert [r["signal_id"] for r in OB.signal_get_active(db)] == ["b"]
        assert len(OB.signal_get_scenarios(db)) == 2


def test_cache_returns_independent_copies():
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        _ins(db, "a")
        r1 = OB.signal_get_active(db)
        r1[0]["status"] = "MUTATED"
        r1.append({"signal_id": "x"})
        r2 = OB.signal_get_active(db)
        assert len(r2) == 1 and r2[0]["status"] == "WATCHING"


def test_cache_disabled_with_zero_ttl():
    with tempfile.TemporaryDirectory() as td:
        db = _db(td)
        _ins(db, "a")
        old = OB._SIG_CACHE_TTL
        OB._SIG_CACHE_TTL = 0
        try:
            OB._SIG_CACHE_STATS.update(hits=0, misses=0)
            OB.signal_get_active(db)
            OB.signal_get_active(db)
            assert OB._SIG_CACHE_STATS["hits"] == 0
        finally:
            OB._SIG_CACHE_TTL = old


def test_delivery_uses_separate_pick_pool():
    from office2 import delivery as D
    assert D.O2_PICK_EXECUTOR is not D.O2_EXECUTOR and D.O2_TRACK_EXECUTOR is not D.O2_EXECUTOR
    assert D.O2_PICK_EXECUTOR._max_workers >= 2


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)
    print("OK")
