"""Resting-starters flag (Rick 2026-11-26, idea 7). INFO ONLY: it never changes a price, a call or an alert.

Late in the regular season a team that has locked the conference's #1 seed (ESPN standings clincher "*")
often sits starters. ESPN's free standings feed says who has clinched; we show one short line on both teams'
cards from Week 15 to Week 18. Not backtested: there are only 1-2 such games a season, too few to test, so
it stays a heads-up to check the news before betting.
"""
from . import config as C
from .fetch import _get, cached

URL = "https://site.api.espn.com/apis/v2/sports/football/nfl/standings?season={season}&seasontype=2"
FIRST_WEEK, LAST_WEEK = 15, 18


def parse(d):
    """{team: clincher code} from ESPN standings JSON ('*' #1 seed, 'z' division, 'y'/'x' playoffs, 'e' out)."""
    out = {}
    for conf in (d or {}).get("children") or []:
        for e in ((conf.get("standings") or {}).get("entries")) or []:
            t = C.espn_abbr(((e.get("team") or {}).get("abbreviation")) or "")
            code = next((s.get("displayValue") for s in e.get("stats") or [] if s.get("name") == "clincher"), None)
            if t and code:
                out[t] = code
    return out


def clinchers(season):
    val, _ = cached("standings", str(season), lambda: parse(_get(URL.format(season=season))))
    return val or {}


def lines_for(games, codes):
    """{(gameId, team): line} for pregame games where one side has locked the #1 seed."""
    out = {}
    for g in games:
        if g.get("state") != "pre":
            continue
        for t, o in ((g["away"], g["home"]), (g["home"], g["away"])):
            if codes.get(t) == "*":
                out[(g["id"], t)] = f"{t} has locked the #1 seed: starters may rest. Check the news first (info only)"
                out[(g["id"], o)] = f"{t} has locked the #1 seed: its starters may rest. Check the news first (info only)"
    return out


def attach(board, fetch=clinchers):
    week, season = board.get("week") or 0, board.get("season")
    for c in board.get("calls") or []:
        c.pop("restLine", None)
    if not (FIRST_WEEK <= week <= LAST_WEEK) or not season:
        return 0
    L = lines_for(board.get("games") or [], fetch(season))
    for c in board.get("calls") or []:
        ln = L.get((c.get("gameId"), c.get("team")))
        if ln:
            c["restLine"] = ln
    return len(L)
