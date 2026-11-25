"""Problem alerts to Rick's phone (review 2026-11-25). One push when something breaks, one when it's back.

  tick      the engine crashed 3 runs in a row (loop.yml calls `python -m engine.alarm tick ok|fail`)
  feed-*    the price or score feed has been down 20+ min while a game is on or starts within 3h
  data      the common-sense checks put calls on hold (engine/sanity.py)
State lives in state/alarm.json so each problem buzzes once, not every 6 minutes.
"""
import os
import sys
from datetime import timedelta

from . import config as C
from . import push as P
from .fetch import load_json, save_json, iso, now_utc

FILE = os.path.join(C.STATE, "alarm.json")
TICK_FAILS = 3
FEED_MIN = 20
FEEDS = {"kalshi": "Price feed (Kalshi)", "espn": "Scores feed (ESPN)"}


def _load():
    return load_json(FILE, {}) or {}


def raise_(name, title, body, st=None):
    st = st if st is not None else _load()
    on = st.setdefault("on", {})
    if name not in on:
        if P.send(title, body, tags="warning", priority="high"):
            on[name] = iso()
        else:
            print(f"[alarm not sent] {title}")
    save_json(FILE, st)


def clear(name, title, body="", st=None):
    st = st if st is not None else _load()
    on = st.setdefault("on", {})
    if name in on:
        P.send(title, body or "All good again.", tags="white_check_mark")
        on.pop(name, None)
    save_json(FILE, st)


def tick_result(ok):
    st = _load()
    if ok:
        st["tickFails"] = 0
        clear("tick", "App is updating again", st=st)
        return
    st["tickFails"] = st.get("tickFails", 0) + 1
    st["lastFail"] = iso()
    if st["tickFails"] >= TICK_FAILS:
        raise_("tick", "App problem: updates failing",
               f"The last {st['tickFails']} updates crashed. Prices in the app may be old — check Robinhood before buying. Claude can fix it.",
               st=st)
    else:
        save_json(FILE, st)


def feeds(board, health, now=None):
    """Feed down for 20+ min while it matters (a game live or within 3h)."""
    from .board import parse_dt
    now = now or now_utc()
    soon = any(g.get("state") == "in" or (g.get("state") == "pre" and (parse_dt(g.get("kickoff")) or now + timedelta(days=9)) - now < timedelta(hours=3))
               for g in board.get("games") or [])
    st = _load()
    for f, label in FEEDS.items():
        h = health.get(f) or {}
        last = parse_dt(h.get("lastOk"))
        down = h.get("ok") is False and (not last or now - last > timedelta(minutes=FEED_MIN))
        if down and soon:
            raise_(f"feed-{f}", f"{label} down",
                   f"No fresh data for {int((now - last).total_seconds() // 60) if last else 'a while'} min. Check prices in Robinhood before buying.", st=st)
        elif h.get("ok"):
            clear(f"feed-{f}", f"{label} is back", st=st)


def data(problems):
    if problems:
        raise_("data", "Data looks off — calls on hold", "; ".join(problems)[:300] + "\nNo Buy alerts until it looks right.")
    else:
        clear("data", "Data looks right again", "Calls are back on.")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["tick"]:
        tick_result(a[1:2] == ["ok"])
