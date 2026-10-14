"""Regression: a Mini App mirror cannot fabricate futures milestones with malformed bars."""
import io
import json
import os
import time
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_signal_track as track  # noqa: E402


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class MirrorValidation(unittest.TestCase):
    def setUp(self):
        self.now = 1791980000
        self.bar = {"time": self.now - 60, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1}

    def get(self, bars, source="binance_futures", status="DATA_OK"):
        data = {"source": source, "data_status": status, "candles": bars}
        with patch.dict(os.environ, {"OFFICE_TRACK_MIRROR": "1"}), \
             patch("time.time", return_value=self.now), \
             patch("urllib.request.urlopen", return_value=Response(data)):
            return track._mirror_candles("BTCUSDT", "1m", 30)

    def test_valid_futures(self):
        self.assertEqual(len(self.get([self.bar])), 1)

    def test_wrong_venue_rejected(self):
        self.assertIsNone(self.get([self.bar], source="binance_spot"))

    def test_stale_rejected(self):
        self.assertIsNone(self.get([{**self.bar, "time": self.now - 3600}]))

    def test_future_rejected(self):
        self.assertIsNone(self.get([{**self.bar, "time": self.now + 100}]))

    def test_invalid_ohlc_rejected(self):
        self.assertIsNone(self.get([{**self.bar, "low": 12}]))

    def test_unsorted_rejected(self):
        self.assertIsNone(self.get([self.bar, {**self.bar, "time": self.now - 120}]))

    def test_mirror_off_by_default(self):
        with patch.dict(os.environ, {"OFFICE_TRACK_MIRROR": "0"}), \
             patch("urllib.request.urlopen", side_effect=AssertionError("must not call")):
            self.assertIsNone(track._mirror_candles("BTCUSDT", "1m", 30))


if __name__ == "__main__":
    unittest.main()
