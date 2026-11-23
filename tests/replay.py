"""Replay the Week 11 Sunday-evening slate captured at 00:35 UTC on 23 Nov 2026 (LV@DEN and JAX@NYG
live, MIN@SF tonight, CIN@WSH tomorrow) through the real pipeline, writing to an output folder."""
import gzip
import json
import os
import shutil
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from engine import board as B, fetch, config as C  # noqa

FX = os.path.join(HERE, "fixtures")


def fx(name):
    p = os.path.join(FX, name + ".gz")
    if not os.path.exists(p):
        return None
    with gzip.open(p) as f:
        return json.load(f)


def replay(out_dir=None):
    sb = fx("week11_sb.json")
    k = fx("week11_kalshi.json")
    B.kalshi_events = lambda: (k["events"], False)
    B.espn_summary = lambda gid: (fx(f"sum_{gid}.json"), False)
    B.weather_batch = lambda pts: ([], False)
    # isolate state
    tmp = os.path.join(out_dir or "/tmp/nflbets-replay", "state")
    os.makedirs(tmp, exist_ok=True)
    B.LIVE_FILE = os.path.join(tmp, "live.json")
    B.SNAP_FILE = os.path.join(tmp, "snaps.json")
    B.PREV_BOARD = os.path.join(tmp, "prev.json")
    now = datetime(2026, 11, 23, 0, 35, tzinfo=timezone.utc)
    b = B.build(now, sb_override=sb)
    if out_dir:
        d = os.path.join(out_dir, "data")
        os.makedirs(d, exist_ok=True)
        b["nextCheck"] = "Next check: Sun 11pm"
        b["banners"] = {"weekly": None, "windows": []}
        b["push"] = {"topic": None, "lastNote": None}
        b["health"] = {}
        b["feedNotes"] = []
        with open(os.path.join(d, "board.json"), "w") as f:
            json.dump(b, f, default=str)
        src = os.path.join(C.DOCS_DATA, "learning.json")
        if os.path.exists(src):
            shutil.copy(src, os.path.join(d, "learning.json"))
        for fn in os.listdir(os.path.join(C.ROOT, "docs")):
            p = os.path.join(C.ROOT, "docs", fn)
            if os.path.isfile(p):
                shutil.copy(p, os.path.join(out_dir, fn))
    return b


if __name__ == "__main__":
    b = replay(sys.argv[1] if len(sys.argv) > 1 else None)
    r = b["combos"]["standard"]["4"]
    print("pool games:", b["combos"]["poolGames"], "4-leg:", r.get("checked"), r.get("combo", r.get("closest")))
