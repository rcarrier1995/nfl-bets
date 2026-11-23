"""Head-to-head history: every meeting of this week's opponents in this season and last season
(nflverse games.csv + play-by-play): score by quarter, how it started, result vs the line, QBs/coaches,
key player lines, and what's different now (QB, coach).

study() tests whether the last meeting (within two seasons) says anything the closing line doesn't:
the last meeting's margin vs the line and "won the last meeting", against this game's result vs the
line and the moneyline win %. Fit 2006-2020, check 2021+. Context only unless it holds.
"""
import math
import os

import numpy as np

from . import config as C
from .fetch import load_json, save_json, iso
from .form import games, pbp, _spot, _holds, FIX, _norm

FILE = os.path.join(C.STATE, "h2h.json")
STUDY = os.path.join(C.STATE, "h2h_study.json")


def _meetings(T, a, h, season, before_day=None):
    m = T[(T.team == a) & (T.opp == h) & (T.season >= season - 1) & T.result.notna()]
    if before_day is not None:
        m = m[m.day < before_day]
    return m.sort_values("day")


def _game_detail(P, gid, team, opp):
    """Quarter scores, leader after each quarter, first score, key player lines — from play-by-play."""
    g = P[P.game_id == gid]
    if not len(g):
        return {}
    home = g.home_team.iloc[0]
    q = {}
    for qq in (1, 2, 3, 4):
        x = g[g.qtr <= qq]
        if len(x):
            hs, as_ = int(x.total_home_score.max()), int(x.total_away_score.max())
            q[qq] = (hs, as_) if team == home else (as_, hs)
    quarters = []
    prev = (0, 0)
    for qq in (1, 2, 3, 4):
        if qq in q:
            quarters.append([q[qq][0] - prev[0], q[qq][1] - prev[1]])
            prev = q[qq]
    sc = g[(g.sp == 1)].sort_values("game_seconds_remaining", ascending=False)
    first = None
    if len(sc):
        r = sc.iloc[0]
        scorer = r.td_team if isinstance(r.td_team, str) else r.posteam
        kind = "TD" if r.touchdown == 1 else "FG" if r.get("field_goal_result") == "made" else "score"
        first = f"{FIX.get(scorer, scorer)} {kind} in Q{int(r.qtr)}"
    lead = []
    for qq in (1, 2, 3):
        if qq in q:
            d = q[qq][0] - q[qq][1]
            lead.append(team if d > 0 else opp if d < 0 else "tied")
    players = {}
    for side, t in (("team", team), ("opp", opp)):
        x = g[g.posteam == t]
        lines = []
        pa = x[x.pass_attempt == 1].dropna(subset=["passer_player_name"])
        if len(pa):
            top = pa.passer_player_name.value_counts().index[0]
            y = pa[pa.passer_player_name == top]
            lines.append(f"{top} {int(y.complete_pass.sum())}/{int((y.sack != 1).sum())}, {int(y.passing_yards.fillna(0).sum())} yds, "
                         f"{int(y.pass_touchdown.sum())} TD, {int(y.interception.sum())} INT, {int(y.sack.sum())} sacks")
        ru = x.dropna(subset=["rusher_player_name"])
        if len(ru):
            s = ru.groupby("rusher_player_name").agg(n=("rushing_yards", "size"), y=("rushing_yards", "sum"), td=("rush_touchdown", "sum"))
            r = s.sort_values("y", ascending=False).iloc[0]
            lines.append(f"{s.sort_values('y', ascending=False).index[0]} {int(r.n)} car, {int(r.y)} yds" + (f", {int(r.td)} TD" if r.td else ""))
        rc = x.dropna(subset=["receiver_player_name"])
        if len(rc):
            s = rc.groupby("receiver_player_name").agg(c=("complete_pass", "sum"), y=("receiving_yards", "sum"), td=("pass_touchdown", "sum"))
            r = s.sort_values("y", ascending=False).iloc[0]
            lines.append(f"{s.sort_values('y', ascending=False).index[0]} {int(r.c)} rec, {int(r.y)} yds" + (f", {int(r.td)} TD" if r.td else ""))
        to = int(x.interception.sum() + x.fumble_lost.sum())
        players[t] = {"lines": lines, "turnovers": to}
    return {"quarters": quarters, "leaders": lead, "first": first, "players": players}


def build(season, week):
    T = games()
    cur = T[(T.season == season) & T.week.isin([week, week + 1])]
    P = pbp([season - 1, season], ["game_id", "season_type", "home_team", "posteam", "qtr", "total_home_score", "total_away_score",
                                    "sp", "td_team", "touchdown", "field_goal_result", "game_seconds_remaining", "pass_attempt",
                                    "passer_player_name", "complete_pass", "passing_yards", "pass_touchdown", "interception", "sack",
                                    "rusher_player_name", "rushing_yards", "rush_touchdown", "receiver_player_name",
                                    "receiving_yards", "fumble_lost"])
    out = {"at": iso(), "season": season, "week": week, "games": {}}
    for r in cur.itertuples():
        if r.team > r.opp:      # each pair once, keyed both ways
            continue
        ms = _meetings(T, r.team, r.opp, season, before_day=r.day)
        rows = []
        for m in ms.itertuples():
            d = _game_detail(P, m.game_id, r.team, r.opp)
            cov = m.cvr
            rows.append({"season": int(m.season), "week": int(m.week), "date": m.day.strftime("%Y-%m-%d"), "gameId": m.game_id,
                         "score": [int(m.pf), int(m.pa)], "home": bool(m.home),
                         "favBy": None if np.isnan(m.spread) else float(m.spread) * (1 if m.home else -1),
                         "vsLine": None if np.isnan(cov) else round(float(cov), 1),
                         "qb": [m.qbn, _opp_row(T, m).qbn], "coach": [m.coach, _opp_row(T, m).coach], **d})
        now = {"qb": [r.qbn if isinstance(r.qbn, str) else None, _opp_row(T, r).qbn],
               "coach": [r.coach, _opp_row(T, r).coach]}
        out["games"][f"{r.team}|{r.opp}"] = {"teams": [r.team, r.opp], "meetings": rows, "now": now}
    save_json(FILE, out, compact=True)
    return out


def _opp_row(T, m):
    x = T[(T.game_id == m.game_id) & (T.team == m.opp)]
    return x.iloc[0] if len(x) else m


def for_board(board, latest_qb=None):
    st = load_json(FILE, {}) or {}
    G = st.get("games") or {}
    for g in board.get("games", []):
        a, h = g["teams"]["away"]["team"], g["teams"]["home"]["team"]
        rec = G.get(f"{a}|{h}") or G.get(f"{h}|{a}")
        if not rec or not rec["meetings"]:
            continue
        t0 = rec["teams"][0]
        flip = t0 != a
        ms = []
        for m in rec["meetings"]:
            s = m["score"][::-1] if flip else m["score"]
            win = a if s[0] > s[1] else h if s[1] > s[0] else None
            lead = [(h if x == t0 else a if x != "tied" else "tied") if flip else x for x in m.get("leaders") or []]
            q = [x[::-1] for x in m.get("quarters") or []] if flip else (m.get("quarters") or [])
            vs = m.get("vsLine")
            if vs is not None and flip:
                vs = -vs
            fb = m.get("favBy")
            ms.append({"favBy": None if fb is None else (-fb if flip else fb), "season": m["season"], "week": m["week"], "date": m["date"], "score": s, "winner": win,
                       "quarters": q, "leaders": lead, "first": m.get("first"), "players": m.get("players"),
                       "awayCovered": None if vs is None else (vs > 0 if vs != 0 else None), "vsLine": vs,
                       "qb": m["qb"][::-1] if flip else m["qb"], "coach": m["coach"][::-1] if flip else m["coach"]})
        now = rec.get("now") or {}
        nq = (now.get("qb") or [None, None])
        nc = (now.get("coach") or [None, None])
        if flip:
            nq, nc = nq[::-1], nc[::-1]
        # newest known starter from the board (injuries/backups), else games.csv
        changes = []
        last = ms[-1]
        for i, t in enumerate((a, h)):
            if latest_qb and latest_qb.get(t):
                nq[i] = latest_qb[t]
            if nq[i] and last["qb"][i] and _norm(nq[i]) != _norm(last["qb"][i]):
                changes.append(f"{t} QB then {last['qb'][i]}, now {nq[i]}")
            if nc[i] and last["coach"][i] and nc[i] != last["coach"][i]:
                changes.append(f"{t} coach then {last['coach'][i]}, now {nc[i]}")
        g["h2h"] = {"meetings": ms, "changes": changes}


def study():
    T = games()
    T = T[T.result.notna()].sort_values("day")
    prev = {}
    rows = []
    for r in T.itertuples():
        k = (r.team, r.opp)
        last = prev.get(k)
        if last is not None and r.season - last[0] <= 1:
            rows.append((r.Index, last[1], last[2]))
        prev[k] = (r.season, r.pf - r.pa, r.cvr)
    import pandas as pd
    L = pd.DataFrame(rows, columns=["i", "lastMargin", "lastCvr"]).set_index("i")
    X = T.join(L, how="inner")
    fit, chk = (X.season >= 2006) & (X.season <= 2020), X.season >= 2021
    out = []
    for name, m in (("Won the last meeting", X.lastMargin > 0), ("Won the last meeting by 14+", X.lastMargin >= 14),
                    ("Lost the last meeting by 14+", X.lastMargin <= -14), ("Covered the last meeting by 10+", X.lastCvr >= 10),
                    ("Missed the line last meeting by 10+", X.lastCvr <= -10)):
        a, b = _spot(name, X[m & fit]), _spot(name, X[m & chk])
        out.append({"spot": name, "fit": a, "check": b, "holds": _holds(a, b)})
    from .profiles import _ols
    o1, o2 = _ols(X[fit].lastCvr.values, X[fit].cvr.values), _ols(X[chk].lastCvr.values, X[chk].cvr.values)
    res = {"at": iso(), "rows": out, "held": [r["spot"] for r in out if r["holds"]],
           "slope": None if not o1 else {"fit": [round(o1[0], 3), round(o1[1], 3), o1[2]],
                                         "check": None if not o2 else [round(o2[0], 3), round(o2[1], 3), o2[2]]}}
    save_json(STUDY, res)
    return res
