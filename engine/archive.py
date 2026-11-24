"""Permanent season price archive (data logging only: never changes a pick).

Asked for by the research thread (2026-11-24) to test, after 3-4 weeks of data:
  - does Kalshi overreact in-game (price vs score/quarter), and
  - do early buys beat the closing price.

state/price_archive.json, one entry per game, kept for the whole season:
  {"<gameId>": {"season", "week", "away", "home", "kickoff",
                "pre":  [[t, awayAsk, homeAsk, spreadHome, total, awayFair, homeFair], ...],
                "live": [[t, period, clock, awayScore, homeScore, awayAsk, homeAsk, awayLiveFair, homeLiveFair], ...],
                "final": [awayScore, homeScore] or None}}
A row is added only when something in it changed, so it stays small. Early price = first "pre" row,
closing price = last "pre" row before kickoff. Only real fetched values are stored (None if missing).
"""
import os

from . import config as C
from .fetch import load_json, save_json, iso

FILE = os.path.join(C.STATE, "price_archive.json")


def _num(x):
    try:
        return None if x is None else round(float(x), 2)
    except Exception:
        return None


def _score(g, side):
    s = (g.get("score") or {}).get(side)
    return None if s is None else int(s)


def record(board, now):
    A = load_json(FILE, {}) or {}
    t = iso(now)
    games = (board.get("games") or []) + (board.get("nextWeek") or [])
    for g in games:
        gid = str(g.get("id") or "")
        if not gid:
            continue
        a, h = (g.get("teams") or {}).get("away") or {}, (g.get("teams") or {}).get("home") or {}
        e = A.setdefault(gid, {"season": board.get("season"), "week": board.get("week") if g in (board.get("games") or []) else (board.get("week") or 0) + 1,
                               "away": g.get("away"), "home": g.get("home"), "kickoff": g.get("kickoff"),
                               "pre": [], "live": [], "final": None})
        e["kickoff"] = g.get("kickoff") or e.get("kickoff")
        st = g.get("state")
        if st == "pre":
            sp = g.get("espnSpread") if g.get("espnSpread") is not None else g.get("spreadHome")
            row = [t, _num(a.get("price")), _num(h.get("price")), _num(sp), _num(g.get("total")), _num(a.get("fair")), _num(h.get("fair"))]
            if row[1] is None and row[2] is None:
                continue
            if not e["pre"] or e["pre"][-1][1:] != row[1:]:
                e["pre"].append(row)
        elif st == "in":
            row = [t, g.get("period"), g.get("clock"), _score(g, "away"), _score(g, "home"),
                   _num(a.get("price")), _num(h.get("price")), _num(a.get("liveFair")), _num(h.get("liveFair"))]
            if not e["live"] or e["live"][-1][1:] != row[1:]:
                e["live"].append(row)
        elif st == "post" and e.get("final") is None and _score(g, "away") is not None:
            e["final"] = [_score(g, "away"), _score(g, "home")]
    save_json(FILE, A, compact=True)
    return A
