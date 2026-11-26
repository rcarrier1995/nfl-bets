"""Kalshi price history + 'slow price' detector.

Every board build appends a row per pregame game when the sportsbook line or a Kalshi ask
changes: [utc, spreadHome, awayAsk, homeAsk]. Kept for 21 days. This is the free record of
Kalshi prices the backtest never had.

Slow price: the sportsbook spread moved >= LAG_MIN_PTS in the last LAG_WINDOW minutes and
the Kalshi ask for the team the line moved toward rose by less than half of what that move
is worth. That is the realistic edge source (the model itself matches the sportsbook).
"""
import math
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
        g["hist"] = rows[-150:]        # for the price-and-line chart on the card
        lag = detect(rows, now)
        for side, c in (("away", a), ("home", h)):
            c.pop("lag", None)
            c.pop("lineCheck", None)
            if not lag:
                line_check(g, c, side, rows, now)
        if lag:
            c = a if lag["side"] == "away" else h
            c["lag"] = lag["note"]
            if c.get("call") in ("Value", "Wait"):
                c["why"] = lag["note"]          # the one why-line: this is the reason it's cheap
            lags.append(c["key"])
    save_json(FILE, hist, compact=True)
    return lags


FROZEN_HOURS = 6      # ESPN line unchanged this long while Kalshi moved = the line is probably behind the news
FROZEN_MOVE = 4       # cents Kalshi moved against the team in that time
CHECK_EDGE = 8        # "buy under" leaves this much edge if Kalshi's own price is the right one


def line_check(g, c, side, rows, now):
    """Pregame guard (Rick, 2026-11-23): a 15c+ gap usually means a stale single-book line after news.
    When the line looks stale, a Buy becomes 'Check the line · buy under X' (a Wait at X), and sends no Buy push.
    Stale = no many-book consensus, or the line hasn't moved for 6h while this team's Kalshi price fell 4c+.
    X assumes Kalshi is right: its mid minus 8c minus fees, so it never says to chase."""
    if c.get("call") != "Value" or c.get("price") is None:
        return
    why = []
    if not str(g.get("book") or "").startswith("Consensus"):
        why.append(f"only one sportsbook line ({g.get('book') or 'ESPN'}), no consensus")
    i = 3 if side == "home" else 2
    t0 = now - timedelta(hours=FROZEN_HOURS)
    old = [r for r in rows if (parse_dt(r[0]) or now) <= t0]
    base = old[-1] if old else None
    if base and None not in (base[1], g.get("spreadHome"), base[i]) and abs(g["spreadHome"] - base[1]) < 0.5 \
            and base[i] - c["price"] >= FROZEN_MOVE:
        why.append(f"line unchanged {FROZEN_HOURS}h while Kalshi fell {base[i] - c['price']:.0f}¢")
    if not why:
        return
    mid = (c["price"] + c["bid"]) / 2 if c.get("bid") else c["price"]
    x = int(math.floor(mid - CHECK_EDGE - (c.get("fee") or 2)))
    c["lineCheck"] = {"why": "; ".join(why), "buyUnder": x if x >= 1 else None}
    if x >= 1 and c["price"] <= x:
        return                         # cheap even if Kalshi is right: keep the Buy
    c["call"] = "Wait"
    c["buyAt"] = x if x >= 1 else None
    c["why"] = f"Check the line: {'; '.join(why)}" + (f". Buy under {x}¢" if x >= 1 else "")


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
    move = cur[1] - base[1]               # negative = home became a bigger favorite
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
