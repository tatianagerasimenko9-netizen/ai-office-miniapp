"""Offline tests for causal B&R dataset and grouped time split."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br.learning_dataset import build_row, chronological_split

def test_frozen_features_and_hash():
    signal = {"sig_id":"s1","symbol":"BTCUSDT","direction":"LONG","confirm_ts":1000}
    source = {"breakout_strength":1.4, "extra_future_data":999}
    row = build_row(signal, source, observed_at=1000)
    assert "extra_future_data" not in row["features"]
    assert row["label"] is None and row["mode"] == "SHADOW_ONLY"
    assert row["row_hash"] == build_row(signal, source, observed_at=1000)["row_hash"]

def test_no_lookahead_observation():
    signal = {"sig_id":"s1","symbol":"BTCUSDT","direction":"LONG","confirm_ts":1000}
    try:
        build_row(signal, {}, observed_at=999)
        assert False
    except ValueError:
        pass

def test_grouped_chronological_split():
    rows = [{"sig_id":str(i)+"a","confirm_ts":float(i)} for i in range(10)]
    rows += [{"sig_id":str(i)+"b","confirm_ts":float(i)} for i in range(10)]
    parts = chronological_split(rows)
    assert [len(parts[k]) for k in ("train","validation","test")] == [12,4,4]
    sets = [set(r["confirm_ts"] for r in parts[k]) for k in ("train","validation","test")]
    assert not (sets[0]&sets[1] or sets[1]&sets[2] or sets[0]&sets[2])

def test_outcome_timestamp_must_follow_features():
    signal = {"sig_id":"s1","symbol":"BTCUSDT","direction":"LONG","confirm_ts":1000}
    for kwargs in ({"label":"SL"}, {"label":"SL","label_observed_at":999}):
        try:
            build_row(signal, {}, observed_at=1000, **kwargs)
            assert False
        except ValueError:
            pass
    row = build_row(signal, {}, observed_at=1000, label="SL", label_observed_at=1060)
    assert row["label"] == "SL" and row["label_observed_at"] == 1060


if __name__ == "__main__":
    for name, fn in sorted(globals().copy().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
