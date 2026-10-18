from office_br.quality_shadow import evaluate


def test_missing_context_is_not_a_pass():
    x = evaluate({"entry": 100, "sl": 99, "direction": "LONG"})
    assert not x["eligible_shadow"]
    assert "HTF_DIRECTION_UNAVAILABLE" in x["unknown"]


def test_trend_obstacle_spread_and_duplicates():
    c = {"entry": 100, "sl": 99, "direction": "LONG"}
    x = evaluate(c, htf_direction="SHORT", obstacle_r=0.8, spread_bps=15, sibling_levels=[100.2])
    assert set(x["reasons"]) == {"COUNTERTREND", "NEAR_HTF_OBSTACLE", "WIDE_SPREAD", "OVERLAPPING_LEVEL"}


def test_clean_candidate_only_in_shadow():
    x = evaluate({"entry": 100, "sl": 99, "direction": "LONG"}, htf_direction="LONG", obstacle_r=2, spread_bps=4)
    assert x["eligible_shadow"] and x["mode"] == "SHADOW_ONLY"


def test_invalid_risk():
    assert not evaluate({"entry": 100, "sl": 100, "direction": "SHORT"})["eligible_shadow"]
