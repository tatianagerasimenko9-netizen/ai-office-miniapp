from office2.bar_annotations import annotate_bars


def _bar(ts, o, h, l, c):
    return dict(ts=ts, open=o, high=h, low=l, close=c)


def test_marks_break_candidate_on_closed_bar():
    bars = [_bar(0, 99, 101, 98, 100.8)]
    out = annotate_bars(bars, level=100, direction="LONG", decision_ts=60, interval_sec=60)
    assert out and "BPR_CANDIDATE" in out[0]["labels"]
    assert out[0]["verified_method"] is False


def test_no_future_bar():
    bars = [_bar(60, 99, 101, 98, 100.8)]
    assert annotate_bars(bars, level=100, direction="LONG", decision_ts=100, interval_sec=60) == []


def test_abnormal_bar_requires_history():
    bars = [_bar(i * 60, 100, 101, 99, 100) for i in range(12)]
    bars.append(_bar(12 * 60, 100, 105, 95, 101))
    out = annotate_bars(bars, level=100, direction="LONG", decision_ts=13 * 60, interval_sec=60)
    assert any("ABNORMAL" in x["labels"] for x in out)
