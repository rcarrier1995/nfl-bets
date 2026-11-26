"""When the paid-limit odds feeds may call (Rick, 2026-11-25): spend the free quota where it matters.

  Game on (any game live)          every LIVE minutes
  Pregame (2 h before a kickoff)   every PRE minutes
  Any other time                   two check-ins a day, 9 AM and 6 PM Central, only while a game is
                                   still to come this week; nothing after the day's games end
  Refresh button (GitHub)          a pull now, unless the last one was under 30 minutes ago

The Odds API (500/month) comes to ~320 scheduled pulls a month, leaving ~100 for Refresh taps plus a buffer.
"""
import os
from datetime import timedelta

from . import config as C

SLOTS = (9, 18)              # Central-time hours of the quiet-day check-ins
PRE_HOURS = 2
FORCE_GAP = timedelta(minutes=30)


def forced():
    return os.environ.get("NFL_FORCE_ODDS") == "1"


def norm(games):
    """Accept [(kickoff, state)] or plain [kickoff] (treated as upcoming)."""
    return [g if isinstance(g, tuple) else (g, "pre") for g in games or []]


def window(games, now):
    """games = [(kickoff, state)]. 'live', 'pre' or None."""
    games = norm(games)
    if any(s == "in" for _, s in games):
        return "live"
    for k, s in games:
        if s == "pre" and k and -timedelta(minutes=30) < k - now <= timedelta(hours=PRE_HOURS):
            return "pre"
    return None


def due(last, now, games, live_min, pre_min):
    """last = datetime of the last call (or None). True when a call is allowed now."""
    games = norm(games)
    age = (now - last) if last else None
    if forced():
        return age is None or age >= FORCE_GAP
    w = window(games, now)
    if w:
        return age is None or age >= timedelta(minutes=live_min if w == "live" else pre_min)
    if not any(s == "pre" and k and k > now for k, s in games):
        return False                     # nothing left to price this week
    local = now.astimezone(C.CT)
    past = [local.replace(hour=h, minute=0, second=0, microsecond=0) for h in SLOTS if local.hour >= h]
    if not past:
        return False
    return last is None or last < past[-1]
