"""Kalshi price history + 'slow price' detector.

Every board build appends a row per pregame game when the sportsbook line or a Kalshi ask
changes: [utc, spreadHome, awayAsk, homeAsk]. Kept for 21 days. This is the free record of
Kalshi prices the backtest never had.

Slow price: the sportsbook spread moved >= LAG_MIN_PTS in the last LAG_WINDOW minutes and
the Kalshi ask for the team the line moved toward rose by less than half of what that move
is worth. That is the realistic edge source (the model itself matches the sportsbook).
"""
import os
from datetime import timedelta

from . import config as C
from .fetch import load_json, save_json, iso
from .board import parse_dt

FILE = os.path.join(C.STATE, "price_history.json")
LAG_MIN_PTS = 1.0
LAG_WINDOW = 60        # minutes
KEEP_DAYS = 21


def record_and_detect(board, now):
    hist = load_json(FILE, {}) or {}
    cut = now - timedelta(days=KEEP_DAYS)
    for gid in list(hist):
        if not hist[gid] or (parse_dt(hist[gid][-1][0]) or now) < cut:
            hist.pop(gid, None)
    lags = []
    for g in board["games"]:
        if g.get("state") != "pre":
            continue
        a, h = g["teams"]["away"], g["teams"]["home"]
        row = [iso(now), g.get("spreadHome"), a.get("price"), h.get("price")]
        rows = hist.setdefault(g["id"], [])
        if not rows or rows[-1][1:] != row[1:]:
            rows.append(row)
        lag = detect(rows, now)
        for side, c in (("away", a), ("home", h)):
            c.pop("lag", None)
        if lag:
            c = a if lag["side"] == "away" else h
            c["lag"] = lag["note"]
            if c.get("call") in ("Value", "Wait"):
                c["why"] = lag["note"]          # the one why-line: this is the reason it's cheap
            lags.append(c["key"])
    save_json(FILE, hist, compact=True)
    return lags


def detect(rows, now):
    """rows: [utc, spreadHome, awayAsk, homeAsk]; returns {side, note} or None."""
    if len(rows) < 2:
        return None
    cur = rows[-1]
    t0 = now - timedelta(minutes=LAG_WINDOW)
    base = None
    for r in rows:
        d = parse_dt(r[0])
        if d and d >= t0:
            break
        base = r
    base = base or rows[0]
    if None in (cur[1], base[1], cur[2], cur[3], base[2], base[3]):
        return None
    move = cur[1] - base[1]               # negative = home became a bigger favourite
    if abs(move) < LAG_MIN_PTS:
        return None
    side = "home" if move < 0 else "away"
    i = 3 if side == "home" else 2
    want = abs(move) * C.PTS_TO_CENTS
    got = cur[i] - base[i]
    if got >= want / 2:
        return None
    return {"side": side,
            "note": f"Slow price: line moved {abs(move):g} pts their way, Kalshi only {got:+.0f}¢ (≈{want:.0f}¢ expected)"}
