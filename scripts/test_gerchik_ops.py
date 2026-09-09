#!/usr/bin/env python3
"""Офлайн-перевірка балів Герчика (шар Б)."""
from office_gerchik_kernel import gerchik_ops_from_facts, interpret_gerchik_ops


def _ok(name: str, cond: bool) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {name}")
    print("ok", name)


def main() -> None:
    empty = gerchik_ops_from_facts(
        day_used_pct=None,
        near_level=False,
        sweep_or_false_break=False,
        impulse_bos=False,
        atr_unknown=True,
    )
    _ok("empty score None", empty["gerchik_ops_score"] is None)

    strong = gerchik_ops_from_facts(
        day_used_pct=40.0,
        near_level=True,
        sweep_or_false_break=True,
        impulse_bos=True,
        volume_spike=True,
        m15_confirm=True,
    )
    _ok("strong 10", strong["gerchik_ops_score"] == 10)
    _ok("band strong", interpret_gerchik_ops(10) == "strong")

    skip = gerchik_ops_from_facts(
        day_used_pct=90.0,
        near_level=False,
        sweep_or_false_break=False,
        impulse_bos=False,
    )
    _ok("skip band", skip["gerchik_ops_band"] == "skip")
    _ok("atr veto", skip["gerchik_atr_trend_veto"] is True)

    mid = gerchik_ops_from_facts(
        day_used_pct=50.0,
        near_level=True,
        sweep_or_false_break=False,
        impulse_bos=True,
    )
    _ok("mid 5", mid["gerchik_ops_score"] == 5)  # 2+2+1
    print("ALL PASS")


if __name__ == "__main__":
    main()
