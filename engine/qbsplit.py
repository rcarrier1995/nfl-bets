"""Team numbers split by starting QB, plus players who changed teams mid-season (Rick 2026-11-27:
"track numbers separate when QBs change or get benched ... look at current QB records and their past
record of performance", and "same when players get traded").

Free nflverse data only (games.csv starters + weekly player/team stats, 2006-now, regular season + playoffs).
For every team this season: each starting QB's record and the offense's EPA per play in his starts.
For every QB: his own track record (EPA per play on his dropbacks and runs, every team he played for,
each older season counts half the next one, shrunk toward backup level when he has few plays) and
his record as a starter.
Moves: players with real offensive volume who played for one team and then another this season.

Backtest (research/qb-trade-study, 2006-26 with playoffs, learn 2006-18 / check 2019-26):
  - Splitting a team's "wins vs the price" by QB: no help (slopes ~0 in both eras).
  - In games right after a QB change, the new starter's own track record vs the team's blended offense
    leaned the right way: 313 bets won 57% at 52c, about +5c a bet before fees (z 2.1, 16 of 21 seasons up,
    +3 to +6c across 9 settings). Under our bar and found by searching, so INFO ONLY: a tag, no price change.
  - Mid-season moves: the price already handles them (97 moves, no edge, size of the player didn't matter).
Nothing here changes a price unless Rick says yes.
"""
import os

from . import config as C
from .fetch import iso, load_json, save_json, nflverse_csv

FILE = os.path.join(C.STATE, "qb_split.json")
FIRST = 2006
DECAY = 0.5        # each older season counts half the next one
K_EPA = 200.0      # plays of "backup level" mixed into every QB's track record (study setting)
REPL = -0.10       # backup-level EPA per play
LEAN_K = 0.2       # study: fair lean = 0.2 x (QB record - team offense) difference
LEAN_MIN = 2.0     # show the tag when the lean is 2c or more (study cut)

STUDY = ("2006–26 with playoffs: after a QB change, when the new starter's own track record was better (or worse) than "
         "the team's offense that season, that side beat the price by about 5¢ a bet before fees (313 games, won 57% at 52¢, "
         "up in 16 of 21 seasons). Under our proof bar, so info only. Splitting wins vs our price by QB and mid-season "
         "trades showed no edge: the price already handles them.")


def _csv(tag, fname, fresh):
    """Past seasons don't change: use the cached copy when there is one."""
    path = os.path.join(C.CACHE, "nflverse", fname)
    if not fresh and os.path.exists(path):
        return path
    return nflverse_csv(tag, fname)


def _frames(season):
    import pandas as pd
    g = pd.read_csv(_csv("schedules", "games.csv", True), low_memory=False)
    g = g[(g.season >= FIRST) & (g.season <= season) & (g.game_type != "PRE")].copy()
    P, T = [], []
    for y in range(FIRST, season + 1):
        try:
            P.append(pd.read_csv(_csv("stats_player", f"stats_player_week_{y}.csv.gz", y == season), low_memory=False,
                                 usecols=["player_id", "player_display_name", "position", "season", "week", "season_type",
                                          "game_id", "team", "attempts", "sacks_suffered", "carries", "targets",
                                          "passing_epa", "rushing_epa", "receiving_epa"]))
            T.append(pd.read_csv(_csv("stats_team", f"stats_team_week_{y}.csv.gz", y == season), low_memory=False,
                                 usecols=["game_id", "team", "attempts", "sacks_suffered", "carries", "passing_epa", "rushing_epa"]))
        except Exception as e:
            print("qbsplit stats", y, "missing:", e)
    P, T = pd.concat(P), pd.concat(T)
    for c in ("attempts", "sacks_suffered", "carries", "targets", "passing_epa", "rushing_epa", "receiving_epa"):
        if c in P:
            P[c] = P[c].fillna(0)
        if c in T:
            T[c] = T[c].fillna(0)
    return g, P, T


def _won(res, home):
    if res != res:
        return None
    r = res if home else -res
    return 1.0 if r > 0 else 0.5 if r == 0 else 0.0


def _rec(w, l, t=0):
    return f"{w}-{l}" + (f"-{t}" if t else "")


def build(season):
    import pandas as pd
    g, P, T = _frames(season)
    q = P[P.position == "QB"].copy()
    q["plays"] = q.attempts + q.sacks_suffered + q.carries
    q["epa"] = q.passing_epa + q.rushing_epa
    qg = q.groupby(["game_id", "player_id"])[["plays", "epa"]].sum()
    T = T.copy()
    T["plays"] = T.attempts + T.sacks_suffered + T.carries
    T["epa"] = T.passing_epa + T.rushing_epa
    tg = T.groupby(["game_id", "team"])[["plays", "epa"]].sum()
    names = {}
    for r in q.groupby(["player_id", "player_display_name"]).size().reset_index().itertuples():
        names[r.player_id] = r.player_display_name
    qbs, teams = {}, {}
    for r in g.sort_values(["gameday", "game_id"]).itertuples():
        for side in ("home", "away"):
            tm, qid, qn = getattr(r, f"{side}_team"), getattr(r, f"{side}_qb_id"), getattr(r, f"{side}_qb_name")
            if not isinstance(qid, str):
                continue
            tm = C.espn_abbr(tm)
            won = _won(r.result, side == "home")
            if won is None:
                continue
            y = int(r.season)
            Q = qbs.setdefault(qid, {"name": qn, "e": {}, "w": 0, "l": 0, "t": 0})
            Q["name"] = qn or Q["name"]
            Q["w" if won == 1 else "l" if won == 0 else "t"] += 1
            if (r.game_id, qid) in qg.index:
                x = qg.loc[(r.game_id, qid)]
                e = Q["e"].setdefault(y, [0.0, 0.0])
                e[0] += float(x.epa)
                e[1] += float(x.plays)
            if y == season:
                S = teams.setdefault(tm, {"starters": {}, "plays": 0.0, "epa": 0.0, "last": None, "lastWeek": None})
                st = S["starters"].setdefault(qid, {"name": qn, "w": 0, "l": 0, "t": 0, "plays": 0.0, "epa": 0.0, "pts": 0, "g": 0, "weeks": []})
                st["w" if won == 1 else "l" if won == 0 else "t"] += 1
                st["g"] += 1
                st["weeks"].append(int(r.week))
                st["pts"] += int(getattr(r, f"{side}_score") or 0)
                k = (r.game_id, getattr(r, f"{side}_team"))
                if k in tg.index:
                    x = tg.loc[k]
                    st["plays"] += float(x.plays); st["epa"] += float(x.epa)
                    S["plays"] += float(x.plays); S["epa"] += float(x.epa)
                if S["lastWeek"] is None or int(r.week) >= S["lastWeek"]:
                    S["last"], S["lastWeek"] = qid, int(r.week)
    qout = {}
    for qid, Q in qbs.items():
        e = pl = 0.0
        for y, (a, b) in Q["e"].items():
            w = DECAY ** (season - y)
            e += w * a
            pl += w * b
        qout[qid] = {"name": Q["name"], "epa": round((e + REPL * K_EPA) / (pl + K_EPA), 4), "plays": round(pl),
                     "starts": _rec(Q["w"], Q["l"], Q["t"]),
                     "years": sorted(Q["e"])[0] if Q["e"] else None}
    tout = {}
    for tm, S in teams.items():
        sts = []
        for qid, st in sorted(S["starters"].items(), key=lambda kv: -kv[1]["g"]):
            sts.append({"id": qid, "name": st["name"], "g": st["g"], "record": _rec(st["w"], st["l"], st["t"]),
                        "w": st["w"], "l": st["l"], "t": st["t"],
                        "offEpa": round(st["epa"] / st["plays"], 3) if st["plays"] else None,
                        "ppg": round(st["pts"] / st["g"], 1) if st["g"] else None, "weeks": st["weeks"]})
        tout[tm] = {"starters": sts, "offEpa": round(S["epa"] / S["plays"], 3) if S["plays"] else None,
                    "last": S["last"], "lastWeek": S["lastWeek"]}
    out = {"at": iso(), "season": season, "qbs": qout, "teams": tout, "moves": moves(P, season),
           "names": {_short(n): i for i, n in names.items()}, "study": STUDY}
    save_json(FILE, out, compact=True)
    return out


def _short(n):
    import re
    s = re.sub(r"[^a-z ]", "", str(n or "").lower()).split()
    return (s[0][:1] + s[-1]) if len(s) >= 2 else "".join(s)


def moves(P, season):
    """Players with real offensive volume (4+ plays a game, 3+ games) who changed teams this season."""
    S = P[(P.season == season) & P.season_type.isin(["REG", "POST"])].copy()
    S["epa"] = S.passing_epa + S.rushing_epa + S.receiving_epa
    S["vol"] = S.attempts + S.carries + S.targets
    out = []
    for pid, x in S.sort_values("week").groupby("player_id"):
        ts = x.team.tolist()
        for i in range(1, len(ts)):
            if ts[i] == ts[i - 1]:
                continue
            b = x.iloc[:i]
            b = b[b.team == ts[i - 1]]
            a = x.iloc[i:]
            a = a[a.team == ts[i]]
            if len(b) < 3 or b.vol.sum() / len(b) < 4:
                break
            out.append({"name": x.player_display_name.iloc[0], "pos": x.position.iloc[0], "from": C.espn_abbr(ts[i - 1]),
                        "to": C.espn_abbr(ts[i]), "week": int(x.week.iloc[i]),
                        "before": {"g": int(len(b)), "epaPerG": round(float(b.epa.sum() / len(b)), 2)},
                        "after": {"g": int(len(a)), "epaPerG": round(float(a.epa.sum() / len(a)), 2) if len(a) else None}})
            break
    return sorted(out, key=lambda m: -m["week"])


# ---------- board ----------
def _starter(st, T, t, g):
    """This week's starting QB for team t: nflverse's listed starter, or the backup when the starter is Out/Doubtful."""
    bq = ((g.get("form") or {}).get(t) or {}).get("backupQB")
    if bq and bq.get("backup"):
        return st["names"].get(_short(bq["backup"])), bq["backup"]
    r = T.get(t)
    if r:
        return r
    return None, None


def for_board(board, games_list=None, week=None):
    """Adds g["qbs"][team] (QB split) and g["moves"][team] to each pregame game. Returns the tags to show."""
    st = load_json(FILE, {}) or {}
    if not st.get("teams"):
        return
    season, week = board.get("season"), week or board.get("week")
    if st.get("season") != season:
        return
    from .form import D as FD
    import pandas as pd
    try:
        G = pd.read_csv(os.path.join(FD, "games.csv"), low_memory=False)
    except Exception:
        G = pd.read_csv(os.path.join(C.CACHE, "nflverse", "games.csv"), low_memory=False)
    G = G[(G.season == season) & (G.week == week)]
    T = {}
    for r in G.itertuples():
        T[C.espn_abbr(r.home_team)] = (r.home_qb_id, r.home_qb_name)
        T[C.espn_abbr(r.away_team)] = (r.away_qb_id, r.away_qb_name)
    gms = board.get("games", []) if games_list is None else games_list
    for g in gms:
        if g.get("state") not in ("pre", "in", "post"):
            continue
        info = {}
        for side in ("away", "home"):
            t = g["teams"][side]["team"]
            info[t] = qb_info(st, t, *_starter(st, T, t, g))
        if any(info.values()):
            g["qbs"] = {t: v for t, v in info.items() if v}
        mv = {}
        for side in ("away", "home"):
            t = g["teams"][side]["team"]
            m = [x for x in st.get("moves") or [] if t in (x["from"], x["to"]) and (week or 99) - x["week"] <= 8]
            if m:
                mv[t] = [{**x, "dir": "in" if x["to"] == t else "out"} for x in m[:4]]
        if mv:
            g["moves"] = mv
        else:
            g.pop("moves", None)
        lean_tag(g, info)


def _rank_level(v, vals):
    """Where v would rank (#1 best) among vals."""
    if v is None or not vals:
        return None
    return 1 + sum(1 for x in vals if x > v)


def qb_info(st, t, qid, qn):
    tm = (st.get("teams") or {}).get(t)
    if not tm or not qn:
        return None
    offs = [x["offEpa"] for x in st["teams"].values() if x.get("offEpa") is not None]
    cur = {s["id"] for x in st["teams"].values() for s in x["starters"]}
    recs = [v["epa"] for k, v in (st.get("qbs") or {}).items() if k in cur]
    q = (st.get("qbs") or {}).get(qid) if isinstance(qid, str) else None
    me = next((s for s in tm["starters"] if s["id"] == qid), None)
    others = [s for s in tm["starters"] if s["id"] != qid]
    ow = sum(s["w"] for s in others); ol = sum(s["l"] for s in others); ot = sum(s["t"] for s in others)
    new = bool(tm.get("last") and qid != tm["last"])
    return {"qb": qn, "id": qid if isinstance(qid, str) else None, "new": new,
            "firstStart": me is None, "with": me and me["record"], "withEpa": me and me["offEpa"],
            "without": _rec(ow, ol, ot) if others else None,
            "others": [f"{s['name'].split()[-1]} {s['record']}" for s in others],
            "teamEpa": tm.get("offEpa"), "career": q and {"epa": q["epa"], "plays": q["plays"], "starts": q["starts"]},
            "careerRank": q and _rank_level(q["epa"], recs), "careerOf": len(recs),
            "withRank": me and _rank_level(me["offEpa"], offs), "teamRank": _rank_level(tm.get("offEpa"), offs),
            "split": len(tm["starters"]) > 1 or new or me is None,
            "lastQb": next((s["name"] for s in tm["starters"] if s["id"] == tm.get("last")), None) if new else None}


def lean(info_a, info_h):
    """Study lean in cents toward home: 0.2 x ((home QB record - home offense) - (away QB record - away offense)).
    Only when one side has a new starter this week and both numbers exist. None otherwise."""
    if not info_a or not info_h or not (info_a["new"] or info_h["new"]):
        return None
    def d(i):
        if not i["career"]:
            return None
        return i["career"]["epa"] - i["teamEpa"] if i["teamEpa"] is not None else 0.0
    da, dh = d(info_a), d(info_h)
    if da is None or dh is None:
        return None
    return round(100 * LEAN_K * (dh - da), 1)


def lean_tag(g, info):
    a, h = g["teams"]["away"]["team"], g["teams"]["home"]["team"]
    x = lean(info.get(a), info.get(h))
    g.pop("qbLean", None)
    if x is None or abs(x) < LEAN_MIN or g.get("state") != "pre":
        return
    t, o = (h, a) if x > 0 else (a, h)
    g["qbLean"] = {"team": t, "opp": o, "cents": abs(x)}


def tag_for(g):
    """Watch tag for the board (info only, never changes a price)."""
    L = g.get("qbLean")
    if not L:
        return None
    t, o = L["team"], L["opp"]
    qs = g.get("qbs") or {}
    new = [(tm, qs[tm]) for tm in (t, o) if (qs.get(tm) or {}).get("new")]
    bits = []
    for tm, i in new:
        c = i.get("career") or {}
        bits.append(f"new {tm} QB {i['qb']}: track record {c.get('epa', 0):+.2f} EPA/play vs {tm}'s offense {(i.get('teamEpa') or 0):+.2f} this year")
    why = "; ".join(bits) + f". Past QB changes like this leaned {t} by about {L['cents']:.0f}¢ (info only)"
    tm, i = new[0]
    return {"team": t, "kind": "good", "qb": i["qb"], "newTeam": tm, "cents": L["cents"], "why": why[0].upper() + why[1:]}
