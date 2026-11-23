"""Closing line value: did our calls beat the price at kickoff?

The first time a team is a pregame Value or Wait call we record its price (state/clv.json).
After kickoff we look up the last price before kickoff in state/price_history.json.
CLV = kickoff price - our price (positive = we got in cheaper than the market closed).
Beating the close over many calls is the best early sign that calls are sharp, long before
win/loss records mean anything.
"""
import os

from . import config as C
from .fetch import load_json, save_json, iso

FILE = os.path.join(C.STATE, "clv.json")
HIST = os.path.join(C.STATE, "price_history.json")


def update(board, now):
    from .board import parse_dt
    d = load_json(FILE, {}) or {}
    calls = d.setdefault("calls", {})
    for g in board["games"]:
        for side in ("away", "home"):
            c = g["teams"][side]
            if g["state"] == "pre" and c.get("call") in ("Value", "Wait") and c.get("price") and c["key"] not in calls:
                calls[c["key"]] = {"at": iso(now), "gameId": g["id"], "side": side, "team": c["team"], "opp": c["opp"],
                                   "call": c["call"], "price": c["price"], "buyAt": c.get("buyAt"),
                                   "kickoff": g.get("kickoff"), "week": g.get("week")}
    hist = load_json(HIST, {}) or {}
    for k, r in calls.items():
        if r.get("close") is not None:
            continue
        ko = parse_dt(r.get("kickoff"))
        if not ko or now < ko:
            continue
        rows = [x for x in hist.get(r["gameId"], []) if (parse_dt(x[0]) or now) <= ko]
        px = rows[-1][2 if r["side"] == "away" else 3] if rows else None
        if px is None:
            r["close"] = None
            r["noClose"] = True
            continue
        r["close"] = px
        # a Wait call only counts if its drop price was actually reached before kickoff
        entry = r["price"]
        if r["call"] == "Wait":
            hit = [x[2 if r["side"] == "away" else 3] for x in rows if x[2 if r["side"] == "away" else 3] is not None
                   and r.get("buyAt") is not None and x[2 if r["side"] == "away" else 3] <= r["buyAt"]]
            entry = min(hit) if hit else None
        r["entry"] = entry
        r["clv"] = None if entry is None else round(px - entry, 1)
    graded = [r for r in calls.values() if r.get("clv") is not None]
    d["summary"] = {"n": len(graded), "avg": round(sum(r["clv"] for r in graded) / len(graded), 1) if graded else None,
                    "beat": sum(1 for r in graded if r["clv"] > 0), "same": sum(1 for r in graded if r["clv"] == 0),
                    "recent": sorted(graded, key=lambda r: r["at"])[-12:], "since": min((r["at"] for r in calls.values()), default=None)}
    if len(calls) > 600:
        d["calls"] = dict(sorted(calls.items(), key=lambda kv: kv[1]["at"])[-600:])
    save_json(FILE, d, compact=True)
    return d["summary"]
