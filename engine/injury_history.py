"""Per-player in-game injury research, for EVERY player (not just top-10).

Built weekly from free nflverse play-by-play + player stats + depth charts + rosters. For every
"X was injured during the play" in 2026 it measures, for that player's team:
  - minutes / plays out, returned or not (Q4 'did not return' is censored)
  - points in the REST OF THE QUARTER he went out, vs the team's normal pace
  - points in the NEXT QUARTER, vs the team's per-quarter average
  - after he RETURNED: points in the rest of that quarter and the next quarter
  - team EPA/play while he was out vs earlier in that game (offense: own offense; defenders:
    opponent offense allowed, sign flipped so negative = hurt his team)
  - rest-of-game margin swing
It also measures games he MISSED entirely (team EPA/play with vs without him).

Output (state/injury_history.json) is looked up live by team|name. Honest limits: small n per
player, 'did not return' is a play-by-play observation not a medical report, causality runs both
ways. Player numbers are shrunk 50% and capped before touching a fair value.
"""
import os
import re
from collections import defaultdict

import numpy as np

from . import config as C
from .fetch import nflverse_csv, read_csv, save_json, load_json, iso

OUT = os.path.join(C.STATE, "injury_history.json")
INJ = re.compile(r"\b([A-Z]{2,3})-(\d+)-([A-Z][A-Za-z'\.\-]+(?: [A-Z][A-Za-z'\.\-]+)?) was injured during the play")
RET = re.compile(r"Injury Update: ([A-Z]{2,3})-(\d+)-([A-Z][A-Za-z'\.\-]+(?: [A-Z][A-Za-z'\.\-]+)?) has returned to the game")


def _team(a):
    return C.espn_abbr(a)


def short_name(n):
    """'Ma.Wilson' -> 'M.Wilson' so ESPN live names ('M.Wilson') match nflverse disambiguated ones."""
    m = re.match(r"^([A-Z])[a-z]{0,2}\.(.+)$", n)
    return f"{m.group(1)}.{m.group(2)}" if m else n


def build(season, week=None, local=None):
    """local: dict of fname -> path (tests/offline)."""
    get = (lambda tag, f: (local or {}).get(f) or nflverse_csv(tag, f))
    pbp = read_csv(get("pbp", f"play_by_play_{season}.csv.gz"))
    ps = read_csv(get("stats_player", f"stats_player_week_{season}.csv.gz"))
    dc = read_csv(get("depth_charts", f"depth_charts_{season}.csv"))
    ro = read_csv(get("rosters", f"roster_{season}.csv"))
    if pbp is None or len(pbp) == 0:
        return load_json(OUT)
    cols = ["game_id", "game_date", "week", "home_team", "away_team", "posteam", "defteam", "qtr",
            "game_seconds_remaining", "desc", "play_type", "total_home_score", "total_away_score", "epa"]
    pbp = pbp[[c for c in cols if c in pbp.columns]].copy()
    pbp = pbp[pbp.week < week] if week else pbp
    for c in ("home_team", "away_team", "posteam", "defteam"):
        pbp[c] = pbp[c].map(lambda x: _team(x) if isinstance(x, str) else x)

    # ---- team per-quarter scoring averages (pace baseline) ----
    qpts = defaultdict(list)   # team -> list of points per quarter
    games = {}
    for gid, g in pbp.groupby("game_id", sort=False):
        g = g.sort_values("game_seconds_remaining", ascending=False, kind="stable")
        games[gid] = g
        h, a = g.home_team.iloc[0], g.away_team.iloc[0]
        for q in (1, 2, 3, 4):
            gq = g[g.qtr <= q]
            gp = g[g.qtr <= q - 1]
            hs = (gq.total_home_score.max() if len(gq) else 0) - (gp.total_home_score.max() if len(gp) else 0)
            as_ = (gq.total_away_score.max() if len(gq) else 0) - (gp.total_away_score.max() if len(gp) else 0)
            qpts[h].append(float(np.nan_to_num(hs)))
            qpts[a].append(float(np.nan_to_num(as_)))
    q_avg = {t: float(np.mean(v)) for t, v in qpts.items() if v}

    # ---- name / position / starter lookups ----
    pos_by = {}
    if ps is not None and len(ps):
        x = ps.copy()
        x["team"] = x["team"].map(_team)
        for r in x.itertuples():
            pos_by[(r.team, r.player_name)] = (C.POS_GROUP.get(str(r.position), str(r.position)), r.player_id, r.player_display_name)
    jersey = {}
    if ro is not None and len(ro):
        y = ro.copy()
        y["team"] = y["team"].map(_team)
        for r in y.itertuples():
            try:
                jersey[(r.team, int(r.jersey_number))] = (C.POS_GROUP.get(str(r.depth_chart_position), C.POS_GROUP.get(str(r.position), str(r.position))), r.gsis_id, r.full_name)
            except Exception:
                pass
    starters = {}
    if dc is not None and len(dc):
        d = dc[dc.pos_rank == 1][["dt", "team", "gsis_id"]].copy()
        d["team"] = d["team"].map(_team)
        for t, g in d.groupby("team"):
            starters[t] = sorted(((str(dt), set(gg.gsis_id)) for dt, gg in g.groupby("dt")), key=lambda z: z[0])

    def is_starter(team, gsis, date):
        snaps = starters.get(team) or []
        best = None
        for dt, ids in snaps:
            if dt[:10] <= date:
                best = ids
        return None if best is None else gsis in best

    # ---- events ----
    events = []
    for gid, g in games.items():
        rows = g.to_dict("records")
        h, a = rows[0]["home_team"], rows[0]["away_team"]
        date = str(rows[0].get("game_date"))
        open_ev = {}
        for i, p in enumerate(rows):
            desc = p.get("desc") or ""
            for m in RET.finditer(desc):
                k = (_team(m.group(1)), m.group(3))
                if k in open_ev:
                    e = open_ev.pop(k)
                    e["returned"] = True
                    e["retIdx"] = i
            for m in INJ.finditer(desc):
                team, jn, nm = _team(m.group(1)), int(m.group(2)), m.group(3)
                info = pos_by.get((team, nm)) or jersey.get((team, jn)) or (None, None, nm)
                e = {"gid": gid, "week": int(p["week"]), "date": date, "team": team, "opp": a if team == h else h,
                     "home": team == h, "name": nm, "short": short_name(nm), "jersey": jn, "pos": info[0],
                     "gsis": info[1], "full": info[2], "q": int(p["qtr"]), "gsr": float(p["game_seconds_remaining"] or 0),
                     "idx": i, "returned": False}
                e["starter"] = is_starter(team, info[1], date) if info[1] else None
                qs = e["gsr"] - max(0, (4 - min(e["q"], 4)) * 900) if e["q"] <= 4 else 0
                e["clock"] = f"{int(qs // 60)}:{int(qs % 60):02d}"
                open_ev[(team, nm)] = e
                events.append(e)
        for e in [x for x in events if x["gid"] == gid]:
            _measure(e, rows, q_avg)

    # ---- games missed entirely (team EPA/play with vs without) ----
    sn = read_csv(get("snap_counts", f"snap_counts_{season}.csv.gz"))
    without = _games_missed(pbp, ps, sn)

    # ---- aggregate per player and per position (ALL players) ----
    by_player = defaultdict(list)
    for e in events:
        by_player[f"{e['team']}|{e['short']}"].append(_slim(e))
    players = {}
    for k, evs in by_player.items():
        players[k] = {"events": evs, "summary": _summ(evs)}
    for k, w in without.items():
        players.setdefault(k, {"events": [], "summary": _summ([])})["without"] = w
    by_pos = {}
    for grp in ("QB", "WR", "TE", "RB", "OL", "DL", "LB", "CB", "S", "ST"):
        evs = [e for e in events if e["pos"] == grp]
        key = [e for e in evs if e.get("starter") and not e["returned"]]
        by_pos[grp] = {"all": _summ(evs), "key": _summ(key)}
    tot = len(events)
    ret = sum(e["returned"] for e in events)
    res = {"season": season, "throughWeek": (week - 1) if week else None, "builtAt": iso(),
           "headline": {"out": tot, "returned": ret, "pctReturned": round(100 * ret / tot, 1) if tot else None,
                        "medianMinOut": _med([e["minOut"] for e in events if e["returned"] and e["minOut"] is not None]),
                        "keyNonQB": sum(1 for e in events if e.get("starter") and not e["returned"] and e["pos"] != "QB")},
           "byQuarter": {str(q): {"out": sum(e["q"] == q for e in events),
                                  "returned": sum(e["q"] == q and e["returned"] for e in events)} for q in (1, 2, 3, 4, 5)},
           "byPosition": by_pos, "players": players, "qAvg": q_avg}
    save_json(OUT, res, compact=True)
    return res


def _score(rows, i, team, home):
    i = max(0, min(i, len(rows) - 1))
    r = rows[i]
    s = r["total_home_score"] if home else r["total_away_score"]
    o = r["total_away_score"] if home else r["total_home_score"]
    return float(np.nan_to_num(s)), float(np.nan_to_num(o))


def _qend_idx(rows, start, q):
    j = start
    while j + 1 < len(rows) and rows[j + 1]["qtr"] == q:
        j += 1
    return j


def _measure(e, rows, q_avg):
    i, q, team, home = e["idx"], e["q"], e["team"], e["home"]
    avg = q_avg.get(team, 5.5)
    s0, o0 = _score(rows, i, team, home)
    qe = _qend_idx(rows, i, q)
    s1, _ = _score(rows, qe, team, home)
    frac = max(0.0, min(1.0, (e["gsr"] - max(0, (4 - min(q, 4)) * 900)) / 900)) if q <= 4 else 0
    e["restQPts"] = s1 - s0
    e["restQExp"] = round(avg * frac, 2)
    e["restQDelta"] = round(e["restQPts"] - e["restQExp"], 2)
    # next quarter
    if qe + 1 < len(rows) and rows[qe + 1]["qtr"] == q + 1:
        nqe = _qend_idx(rows, qe + 1, q + 1)
        sn, _ = _score(rows, nqe, team, home)
        e["nextQPts"] = sn - s1
        e["nextQDelta"] = round(e["nextQPts"] - avg, 2)
    else:
        e["nextQPts"] = e["nextQDelta"] = None
    sf, of = _score(rows, len(rows) - 1, team, home)
    e["swing"] = (sf - s0) - (of - o0)
    # time & plays out
    end = e.get("retIdx", len(rows) - 1)
    e["minOut"] = round((e["gsr"] - float(rows[end]["game_seconds_remaining"] or 0)) / 60, 1) if e["returned"] else None
    off = e["pos"] in ("QB", "WR", "TE", "RB", "OL")
    def epa_rng(a, b):
        xs = [r["epa"] for r in rows[a:b] if r.get("epa") == r.get("epa") and r.get("epa") is not None and
              r.get("play_type") in ("pass", "run") and (r["posteam"] == team if off else r["posteam"] == e["opp"])]
        return (float(np.mean(xs)), len(xs)) if xs else (None, 0)
    before, nb = epa_rng(0, i)
    during, nd = epa_rng(i + 1, end + 1)
    e["playsOut"] = nd
    if before is not None and during is not None and nb >= 8 and nd >= 5:
        d = during - before
        e["epaDelta"] = round(d if off else -d, 3)   # negative = hurt his team
    else:
        e["epaDelta"] = None
    # after return: rest of that quarter + next quarter
    if e["returned"]:
        ri = e["retIdx"]
        rq = rows[ri]["qtr"]
        sr, _ = _score(rows, ri, team, home)
        rqe = _qend_idx(rows, ri, rq)
        se, _ = _score(rows, rqe, team, home)
        e["afterRetRestQ"] = se - sr
        if rqe + 1 < len(rows) and rows[rqe + 1]["qtr"] == rq + 1:
            nqe = _qend_idx(rows, rqe + 1, rq + 1)
            sn, _ = _score(rows, nqe, team, home)
            e["afterRetNextQDelta"] = round((sn - se) - avg, 2)
        else:
            e["afterRetNextQDelta"] = None


def _slim(e):
    keep = ("week", "opp", "q", "clock", "returned", "minOut", "playsOut", "restQPts", "restQDelta", "nextQPts", "nextQDelta",
            "swing", "epaDelta", "afterRetRestQ", "afterRetNextQDelta", "starter", "pos", "full")
    return {k: e.get(k) for k in keep}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 2) if xs else None


def _med(xs):
    xs = [x for x in xs if x is not None]
    return round(float(np.median(xs)), 1) if xs else None


def _summ(evs):
    n = len(evs)
    return {"n": n, "returned": sum(1 for e in evs if e["returned"]),
            "medMinOut": _med([e.get("minOut") for e in evs]),
            "restQDelta": _mean([e.get("restQDelta") for e in evs]),
            "nextQDelta": _mean([e.get("nextQDelta") for e in evs if not e["returned"] or (e.get("minOut") or 0) > 15]),
            "nextQDeltaAll": _mean([e.get("nextQDelta") for e in evs]),
            "swing": _mean([e.get("swing") for e in evs]),
            "epaDelta": _mean([e.get("epaDelta") for e in evs]),
            "epaPlays": int(sum((e.get("playsOut") or 0) for e in evs if e.get("epaDelta") is not None)),
            "afterRetNextQDelta": _mean([e.get("afterRetNextQDelta") for e in evs if e["returned"]])}


def _games_missed(pbp, ps, snaps=None):
    """For players who played >=3 games: team offensive (or defensive) EPA/play in games he missed
    vs games he played. Needs >=1 missed game; the app shows n so small samples are obvious."""
    if ps is None or len(ps) == 0:
        return {}
    plays = pbp[pbp.play_type.isin(["pass", "run"]) & pbp.epa.notna()]
    off = plays.groupby(["posteam", "week"]).epa.mean()
    dfn = plays.groupby(["defteam", "week"]).epa.mean()
    weeks_by_team = defaultdict(set)
    for (t, w) in off.index:
        weeks_by_team[t].add(int(w))
    from .stats import abbrev
    snap_weeks = {}
    if snaps is not None and len(snaps):
        sn = snaps.copy()
        sn["team"] = sn["team"].map(_team)
        sn = sn[(sn.offense_snaps.fillna(0) + sn.defense_snaps.fillna(0)) > 0]
        for (team, player), g in sn.groupby(["team", "player"]):
            snap_weeks[(team, short_name(abbrev(player)))] = set(int(w) for w in g.week)
    x = ps.copy()
    x["team"] = x["team"].map(_team)
    out = {}
    for (team, name), g in x.groupby(["team", "player_name"]):
        played = snap_weeks.get((team, short_name(name))) or set(int(w) for w in g.week)
        tw = weeks_by_team.get(team, set())
        missed = sorted(w for w in tw - played if w > min(played, default=99))
        if len(played) < 3 or not missed:
            continue
        grp = C.POS_GROUP.get(str(g.position.iloc[-1]), str(g.position.iloc[-1]))
        series = dfn if grp in ("DL", "LB", "CB", "S") else off
        with_ = [series.get((team, w)) for w in played if (team, w) in series.index]
        wo = [series.get((team, w)) for w in missed if (team, w) in series.index]
        if not with_ or not wo:
            continue
        d = float(np.mean(wo) - np.mean(with_))
        if grp in ("DL", "LB", "CB", "S"):
            d = -d
        out[f"{team}|{short_name(name)}"] = {"missed": len(wo), "played": len(with_), "epaDelta": round(d, 3),
                                             "weeksMissed": missed[:8]}
    return out


def lookup(hist, team, name):
    if not hist:
        return None
    p = hist.get("players") or {}
    return p.get(f"{team}|{short_name(name)}") or p.get(f"{team}|{name}")


def player_factor(rec, secs_left):
    """Player-specific layer (Rick's request): measured team EPA/play change while THIS player was
    out (prior in-game exits, or whole games missed), converted to points over the remaining
    plays, shrunk 50%, capped at -1.0 pt, never a reward. Needs >=20 plays-out or >=2 games missed."""
    if not rec:
        return 0.0, None
    s = rec.get("summary") or {}
    w = rec.get("without") or {}
    d, src = None, None
    if s.get("epaDelta") is not None and (s.get("epaPlays") or 0) >= 20:
        d, src = s["epaDelta"], f"in-game exits, {s['epaPlays']} plays"
    elif w.get("missed", 0) >= 2:
        d, src = w["epaDelta"], f"{w['missed']} games missed"
    if d is None:
        return 0.0, None
    plays_left = 31.0 * max(0, secs_left) / 3600.0    # ~31 offensive (or defensive) snaps per team-half... per game ~62
    pts = 0.5 * d * plays_left * 2
    pts = max(-1.0, min(0.0, pts))
    return round(pts, 2), src
