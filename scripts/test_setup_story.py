#!/usr/bin/env python3
"""Назва сетапу й причини — лише з реальних тегів READY; без запису — чесно «немає»; довільні комбінації. Офлайн."""
import itertools
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_setup_story as SU  # noqa: E402
from office_confluence import FORMAL_TAGS  # noqa: E402

# живі приклади після #112
spx = SU.build(["flag", "fvg_retest"], "inside_zone", "SHORT", rr_net=2.09, rr_weighted=2.65)
assert spx["name"] == "SHORT · повернення до FVG після фігури (прапор)" and "fvg" in spx["objects"] and len(spx["why"]) <= 4, spx
eigen = SU.build(["flag", "level_retest", "channel_edge", "engulf"], "inside_zone", "SHORT")
assert eigen["name"].startswith("SHORT · ретест рівня біля краю каналу") and "поглинання" in eigen["name"] and set(eigen["objects"]) == {"level", "channel"}, eigen
syrup = SU.build(["level_hold", "channel_edge"], "inside_zone", "SHORT", rr_net=7.57, rr_weighted=10.44)
assert syrup["name"] == "SHORT · рівень утримано біля краю каналу" and syrup["why"][0].startswith("Рівень утримано") and any("краю регресійного каналу" in w for w in syrup["why"]), syrup
assert SU.build([], None, "LONG")["name"] is None and SU.build(None, "inside_zone", "LONG")["name"] is None
rt = SU.build([], "retest", "LONG")
assert rt["name"] == "LONG · пробій зони і ретест", rt
assert SU.build(["channel_edge"], "inside_zone", "LONG")["name"] == "LONG · реакція від краю каналу"
# будь-які комбінації формальних тегів: ніколи не падає, ≤4 причини, назва лише з відомих слів, напрям у назві
rnd = random.Random(5)
pool = list(FORMAL_TAGS) + ["flag", "engulf", "sfp", "double_top", "triple_bottom", "head_shoulders"]
for _ in range(300):
    ts = rnd.sample(pool, rnd.randint(1, 4))
    for d in ("LONG", "SHORT"):
        out = SU.build(ts, rnd.choice(["inside_zone", "retest"]), d, rr_net=rnd.choice([None, 1.6, 5.0]))
        assert out["name"] and out["name"].startswith(d + " · ") and 1 <= len(out["why"]) <= 4 and all(o in ("level", "fvg", "block", "candle", "channel") for o in out["objects"]), (ts, out)
print("test_setup_story: OK")
