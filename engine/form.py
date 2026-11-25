"""Form, streaks, coach tendencies and QB profiles (free nflverse data: games.csv 1999+, play-by-play 2021+).

study()  tests each idea against the price (moneyline win % and the closing spread):
  streaks (won/lost N straight, blowouts), turnovers/INTs last game, coach aggressiveness
  (pass rate over expected, pace, no-huddle, 4th-down go rate, 2-pt tries, Q4 aggression when
  trailing/leading, also live: trailing at half), backup-QB starts (experience, rust, first start
  for the team), and whether QB traits repeat year to year (quarter splits, sack rate, INT rate).
  Fit years vs check years; something only "holds" if it is > 2.5 SE in the fit years and the same
  way at > 1.5 SE in the check years. Nothing here moves prices unless it holds.
build()  writes current team form, coach ranks (#1-32) and QB profiles for the board.
"""
import math
import os

import numpy as np

from . import config as C
from .fetch import load_json, save_json, iso

D = os.path.join(C.CACHE, "nflverse")
STUDY = os.path.join(C.STATE, "form_study.json")
PROF = os.path.join(C.STATE, "form_profiles.json")
FIX = {"OAK": "LV", "SD": "LAC", "STL": "LAR", "LA": "LAR", "WAS": "WSH", "JAC": "JAX"}
DB_PER_GAME = 36          # league-typical dropbacks per game, to turn an EPA gap into points
REPL_EPA = -0.12          # replacement-level QB EPA/dropback (what we shrink thin samples toward)
SHRINK_DB = 300           # dropbacks of evidence before we trust a QB's own EPA half-way


def _fx(s):
    return s.map(lambda x: FIX.get(x, x))


def _imp(m):
    m = np.asarray(m, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(m < 0, -m / (-m + 100), 100 / (m + 100))


def games():
    import pandas as pd
    g = pd.read_csv(os.path.join(D, "games.csv"))
    g = g[g.game_type == "REG"].copy()
    g["home_team"], g["away_team"] = _fx(g.home_team), _fx(g.away_team)
    rows = []
    for side, o in (("home", "away"), ("away", "home")):
        x = g[["game_id", "season", "week", "gameday", "result", "spread_line", f"{side}_team", f"{o}_team", f"{side}_qb_id",
               f"{side}_qb_name", f"{side}_coach", f"{side}_moneyline", f"{o}_moneyline", f"{side}_score", f"{o}_score"]].copy()
        x.columns = ["game_id", "season", "week", "day", "result", "spread", "team", "opp", "qb", "qbn", "coach", "ml", "oml", "pf", "pa"]
        s = 1 if side == "home" else -1
        x["home"] = side == "home"
        x["cvr"] = s * (x.result - x.spread)
        x["win"] = np.where(x.result.isna(), np.nan, (s * x.result > 0).astype(float) + 0.5 * (x.result == 0))
        a, b = _imp(x.ml), _imp(x.oml)
        x["p"] = a / (a + b)
        rows.append(x)
    T = pd.concat(rows).sort_values(["day", "game_id"]).reset_index(drop=True)
    T["day"] = pd.to_datetime(T.day)
    return T


def team_form(T):
    """Per team-game, what was known before kickoff: streak, last 3/5, last margin."""
    out = []
    for (team, season), grp in T.sort_values("day").groupby(["team", "season"]):
        streak, res, mg = 0, [], []
        for i, r in grp.iterrows():
            out.append((i, streak, sum(res[-5:]) if len(res) >= 5 else np.nan, sum(res[-3:]) if len(res) >= 3 else np.nan,
                        mg[-1] if mg else np.nan))
            if np.isnan(r.win):
                continue
            w = r.win
            streak = (streak + 1 if streak > 0 else 1) if w == 1 else ((streak - 1 if streak < 0 else -1) if w == 0 else 0)
            res.append(w)
            mg.append(r.pf - r.pa)
    import pandas as pd
    F = pd.DataFrame(out, columns=["i", "streak", "w5", "w3", "mlast"]).set_index("i")
    return T.join(F)


def pbp(years, cols):
    import pandas as pd
    fr = []
    for y in years:
        p = os.path.join(D, f"play_by_play_{y}.csv.gz")
        if os.path.exists(p):
            x = pd.read_csv(p, usecols=lambda c: c in cols, low_memory=False)
            fr.append(x[x.season_type == "REG"])
    P = pd.concat(fr)
    for c in ("posteam", "defteam", "home_team", "away_team"):
        if c in P:
            P[c] = _fx(P[c])
    return P


def _spot(name, s, kind="win"):
    s = s[s.p.notna() & s.win.notna()] if kind == "win" else s[s.cvr.notna()]
    if len(s) < 25:
        return None
    if kind == "win":
        d = s.win.mean() - s.p.mean()
        se = math.sqrt((s.p * (1 - s.p)).sum()) / len(s)
        return {"n": len(s), "won": round(100 * s.win.mean(), 1), "price": round(100 * s.p.mean(), 1),
                "diff": round(100 * d, 1), "se": round(100 * se, 1), "z": round(d / se, 2) if se else 0,
                "vsLine": round(s.cvr.mean(), 2)}
    return None


def _holds(a, b):
    return bool(a and b and abs(a["z"]) > 2.5 and a["z"] * b["z"] > 0 and abs(b["z"]) > 1.5)


def study():
    T = team_form(games())
    T = T[T.result.notna()]
    fit, chk = (T.season >= 2006) & (T.season <= 2020), T.season >= 2021
    rows = []

    def add(group, name, m, tf=fit, tc=chk, note=""):
        a, b = _spot(name, T[m & tf]), _spot(name, T[m & tc])
        rows.append({"group": group, "spot": name, "fit": a, "check": b, "holds": _holds(a, b), "note": note})

    add("Streaks", "Won 3+ in a row", T.streak >= 3)
    add("Streaks", "Won 5+ in a row", T.streak >= 5)
    add("Streaks", "Lost 3+ in a row", T.streak <= -3)
    add("Streaks", "Lost last game by 20+", T.mlast <= -20)
    add("Streaks", "Won last game by 20+", T.mlast >= 20)
    # turnovers (pbp 2021+): fit 2021-24, check 2025-26
    P = pbp(range(2021, 2100), ["game_id", "season_type", "posteam", "interception", "fumble_lost"])
    to = P.groupby(["game_id", "posteam"]).agg(ints=("interception", "sum"), fl=("fumble_lost", "sum")).reset_index()
    to["to"] = to.ints + to.fl
    T2 = T.merge(to.rename(columns={"posteam": "team"}), on=["game_id", "team"]).sort_values("day")
    T2["intsLast"] = T2.groupby(["team", "season"]).ints.shift(1)
    T2["to3"] = T2.groupby(["team", "season"]).to.transform(lambda s: s.shift(1).rolling(3).sum())
    f2, c2 = T2.season <= 2024, T2.season >= 2025
    for name, m in (("Threw 2+ INTs last game", T2.intsLast >= 2), ("Threw 3+ INTs last game", T2.intsLast >= 3),
                    ("6+ turnovers in last 3", T2.to3 >= 6), ("0-1 turnovers in last 3", T2.to3 <= 1)):
        a, b = _spot(name, T2[m & f2]), _spot(name, T2[m & c2])
        rows.append({"group": "Turnovers", "spot": name, "fit": a, "check": b, "holds": _holds(a, b), "note": "fit 2021-24, check 2025-26"})
    # backup QB starts
    B = backup_starts(T)
    for name, m in (("Backup QB starting", B.backup), ("Backup's first start for the team", B.backup & B.first),
                    ("Backup with 0 career starts", B.backup & (B.cstarts == 0)),
                    ("Backup with 1-5 career starts", B.backup & B.cstarts.between(1, 5)),
                    ("Backup with 6+ career starts", B.backup & (B.cstarts >= 6)),
                    ("Backup who hadn't started in 1+ year", B.backup & (B.rust >= 365))):
        a, b = _spot(name, B[m & fit.reindex(B.index, fill_value=False)]), _spot(name, B[m & chk.reindex(B.index, fill_value=False)])
        rows.append({"group": "Backup QB", "spot": name, "fit": a, "check": b, "holds": _holds(a, b), "note": ""})
    rows.append(drop_test(B))
    coach = coach_study()
    qbt = qb_trait_reliability()
    out = {"at": iso(), "rows": rows, "coach": coach, "qbTraits": qbt,
           "held": [r["spot"] for r in rows if r["holds"]] + [c["signal"] for c in coach if c.get("holds")]}
    save_json(STUDY, out)
    return out


def backup_starts(T):
    """Mark games where the QB wasn't the team's usual starter (3+ starts that season)."""
    T = T.dropna(subset=["qb"]).copy()
    T["cstarts"] = T.groupby("qb").cumcount()
    T["rust"] = (T.day - T.groupby("qb").day.shift(1)).dt.days
    flag, first = {}, {}
    for (team, season), grp in T.groupby(["team", "season"]):
        cnt, seen = {}, set()
        for i, r in grp.iterrows():
            top = max(cnt, key=cnt.get) if cnt else None
            flag[i] = bool(top and top != r.qb and cnt[top] >= 3)
            first[i] = r.qb not in seen
            seen.add(r.qb)
            cnt[r.qb] = cnt.get(r.qb, 0) + 1
    T["backup"] = T.index.map(flag)
    T["first"] = T.index.map(first)
    return T


def drop_test(B):
    """Backup starts 2022+: our expected drop (usual starter's EPA minus the backup's, both from earlier
    seasons, shrunk) vs what happened against the closing line. Does the line already price it?"""
    P = pbp(range(2021, 2100), ["season", "season_type", "passer_player_id", "qb_dropback", "epa"])
    P = P[P.qb_dropback == 1].dropna(subset=["passer_player_id", "epa"])
    by = P.groupby(["passer_player_id", "season"]).epa.agg(["sum", "count"]).reset_index()

    def prior(pid, season):
        x = by[(by.passer_player_id == pid) & (by.season < season)]
        n, sm = x["count"].sum(), x["sum"].sum()
        return (sm + REPL_EPA * SHRINK_DB) / (n + SHRINK_DB)
    usual = {}
    for (team, season), grp in B.groupby(["team", "season"]):
        cnt = {}
        for i, r in grp.iterrows():
            usual[i] = max(cnt, key=cnt.get) if cnt else None
            cnt[r.qb] = cnt.get(r.qb, 0) + 1
    X = B[B.backup & (B.season >= 2022) & B.result.notna()].copy()
    X["gap"] = [(prior(usual[i], r.season) - prior(r.qb, r.season)) * DB_PER_GAME if usual.get(i) else np.nan for i, r in X.iterrows()]
    X = X.dropna(subset=["gap"])
    big = X[X.gap >= 4]
    a = _spot("Backup expected to be 4+ pts worse (2022+)", big)
    from .profiles import _ols
    o = _ols(X.gap.values, X.cvr.values)
    note = (f"Against the line: {o[0]:+.2f} pts per point of expected drop (SE {o[1]:.2f}, n={o[2]}) — "
            + ("the line already prices it" if abs(o[0] / o[1]) < 2 else "the line misses part of it")) if o else ""
    return {"group": "Backup QB", "spot": "Backup expected to be 4+ pts worse (2022+)", "fit": a, "check": None,
            "holds": False, "note": note}


def coach_frame():
    cols = ["game_id", "season", "season_type", "game_date", "posteam", "home_team", "qtr", "down", "ydstogo", "yardline_100",
            "play_type", "pass_oe", "wp", "score_differential", "game_seconds_remaining", "half_seconds_remaining",
            "two_point_attempt", "extra_point_attempt", "no_huddle", "drive"]
    P = pbp(range(2021, 2100), cols).sort_values(["game_id", "game_seconds_remaining"], ascending=[True, False])
    pl = P[P.play_type.isin(["pass", "run"]) & P.posteam.notna()].copy()
    pl["neu"] = (pl.qtr <= 3) & pl.wp.between(.2, .8) & pl.down.isin([1, 2])
    pl["dt"] = pl.groupby(["game_id", "drive"]).game_seconds_remaining.diff(-1)
    pl.loc[~((pl.qtr <= 3) & pl.wp.between(.2, .8)) | (pl.dt <= 0) | (pl.dt > 60), "dt"] = np.nan
    pl["tr4"] = (pl.qtr == 4) & pl.score_differential.between(-16, -1)
    pl["ld4"] = (pl.qtr == 4) & pl.score_differential.between(1, 16)
    f4 = P[(P.down == 4) & (P.ydstogo <= 3) & (P.yardline_100 <= 65) & (P.half_seconds_remaining > 120)
           & P.play_type.isin(["pass", "run", "punt", "field_goal"]) & P.posteam.notna()].copy()
    f4["go"] = f4.play_type.isin(["pass", "run"]).astype(int)
    tp = P[(P.two_point_attempt == 1) | (P.extra_point_attempt == 1)].dropna(subset=["posteam"])
    import pandas as pd

    def agg(df, val, nm, mask=None):
        d = df if mask is None else df[mask]
        return d.groupby(["game_id", "posteam"])[val].agg(["sum", "count"]).rename(columns={"sum": nm + "_s", "count": nm + "_n"})
    A = pd.concat([agg(pl, "pass_oe", "proe", pl.neu), agg(pl, "dt", "pace"), agg(pl, "pass_oe", "tr4", pl.tr4),
                   agg(pl, "pass_oe", "ld4", pl.ld4), agg(pl, "no_huddle", "nh"), agg(f4, "go", "g4"),
                   agg(tp, "two_point_attempt", "tp")], axis=1).fillna(0).reset_index().rename(columns={"posteam": "team"})
    G = P.groupby("game_id").agg(season=("season", "first"), date=("game_date", "first"), home=("home_team", "first")).reset_index()
    A = A.merge(G, on="game_id").sort_values(["team", "date"])
    return A, P


COACH = [("proe", "Passes more than expected", "pass rate over expected, neutral downs"),
         ("pace", "Plays slow", "seconds per play, neutral game"),
         ("nh", "No-huddle", "no-huddle rate"),
         ("g4", "Goes for it on 4th", "4th-and-short go rate"),
         ("tp", "Goes for 2", "2-point try rate after TDs"),
         ("tr4", "Aggressive when trailing late", "Q4 pass rate over expected when behind"),
         ("ld4", "Keeps passing with a lead", "Q4 pass rate over expected when ahead")]


def coach_study():
    from .profiles import _test
    A, P = coach_frame()
    for nm, *_ in COACH:
        s = A.groupby("team")[nm + "_s"].transform(lambda x: x.shift(1).rolling(17, min_periods=8).sum())
        n = A.groupby("team")[nm + "_n"].transform(lambda x: x.shift(1).rolling(17, min_periods=8).sum())
        A["f_" + nm] = s / n.replace(0, np.nan)
    Tg = games().drop_duplicates("game_id").set_index("game_id")[["result", "spread"]]
    H = A.join(Tg, on="game_id")
    hh, aa = H[H.team == H.home].set_index("game_id"), H[H.team != H.home].set_index("game_id")
    X = hh.join(aa, lsuffix="_h", rsuffix="_a", how="inner")
    X["r"] = X.result_h - X.spread_h
    tr, te = (X.season_h <= 2024).values, (X.season_h >= 2025).values
    out = []
    for nm, label, _ in COACH:
        t = _test(nm, (X["f_" + nm + "_h"] - X["f_" + nm + "_a"]).values, X.r.values, tr, te, "pts", 1)
        if t:
            out.append({k: (float(v) if isinstance(v, (np.floating,)) else v) for k, v in t.items()} | {"label": label, "kind": "pregame vs line"})
    return out


def qb_trait_reliability():
    """Does a QB trait repeat next season? (correlation of season N with N+1, QBs with 200+ dropbacks)."""
    P = pbp(range(2021, 2100), ["season", "season_type", "qtr", "passer_player_id", "qb_dropback", "epa", "sack", "interception"])
    P = P[(P.qb_dropback == 1) & (P.qtr <= 4)].dropna(subset=["passer_player_id", "epa"])
    o = P.groupby(["passer_player_id", "season"]).agg(epa=("epa", "mean"), sk=("sack", "mean"), it=("interception", "mean"),
                                                         n=("epa", "size")).reset_index()
    o = o[o.n >= 200]
    nx = o.copy()
    nx["season"] -= 1
    m = o.merge(nx, on=["passer_player_id", "season"], suffixes=("", "_n"))
    out = {"EPA per dropback": round(m.epa.corr(m.epa_n), 2), "Sack rate": round(m.sk.corr(m.sk_n), 2),
           "INT rate": round(m.it.corr(m.it_n), 2)}
    a = P.groupby(["passer_player_id", "season", "qtr"]).epa.agg(["mean", "count"]).reset_index()
    a = a.merge(o[["passer_player_id", "season", "epa"]], on=["passer_player_id", "season"])
    a = a[a["count"] >= 40]
    a["rel"] = a["mean"] - a["epa"]
    for q in (1, 2, 3, 4):
        x = a[a.qtr == q][["passer_player_id", "season", "rel"]]
        y = x.copy()
        y["season"] -= 1
        mm = x.merge(y, on=["passer_player_id", "season"], suffixes=("", "_n"))
        out[f"Q{q} better/worse than usual"] = round(mm.rel.corr(mm.rel_n), 2)
    out["n"] = int(len(m))
    return out


# ------------------------------------------------------------------ current profiles for the board
def build(season=None):
    T = team_form(games())
    season = season or int(T[T.result.notna()].season.max())
    out = {"at": iso(), "season": season, "teams": {}, "qbs": {}}
    cur = T[(T.season == season) & T.result.notna()].sort_values("day")
    # turnovers this season
    P = pbp([season], ["game_id", "season_type", "posteam", "defteam", "interception", "fumble_lost", "game_date", "qb_dropback", "sack"])
    dbk = P[P.qb_dropback == 1].groupby("defteam").sack.mean()
    rush = dbk.rank(ascending=False, method="min").astype(int)
    to = P.groupby(["game_id", "posteam"]).agg(ints=("interception", "sum"), fl=("fumble_lost", "sum")).reset_index()
    for team, grp in cur.groupby("team"):
        res = [("W" if w == 1 else "L" if w == 0 else "T") for w in grp.win]
        streak = 0
        for r in reversed(res):
            if streak == 0:
                streak = 1 if r == "W" else -1 if r == "L" else 0
                if streak == 0:
                    break
            elif (r == "W") == (streak > 0) and r != "T":
                streak += 1 if streak > 0 else -1
            else:
                break
        last = grp.iloc[-1]
        tg = to[(to.posteam == team)].merge(grp[["game_id", "day"]], on="game_id").sort_values("day")
        out["teams"][team] = {"last5": "".join(res[-5:]), "streak": streak, "w": res.count("W"), "l": res.count("L"), "t": res.count("T"),
                              "lastMargin": int(last.pf - last.pa), "lastOpp": last.opp,
                              "intsLast": int(tg.ints.iloc[-1]) if len(tg) else None,
                              "toLast3": int((tg.ints + tg.fl).tail(3).sum()) if len(tg) >= 3 else None,
                              "coach": last.coach,
                              "passRush": {"rank": int(rush[team]), "rate": round(100 * float(dbk[team]), 1)} if team in rush else None}
    # coach ranks, last 17 games
    A, _ = coach_frame()
    A = A.sort_values("date").groupby("team").tail(17)
    sums = A.groupby("team").sum(numeric_only=True)
    for nm, label, what in COACH:
        v = (sums[nm + "_s"] / sums[nm + "_n"].replace(0, np.nan)).dropna()
        rk = v.rank(ascending=False, method="min").astype(int)
        for team in v.index:
            out["teams"].setdefault(team, {}).setdefault("coachRanks", {})[nm] = {"rank": int(rk[team]), "v": round(float(v[team]), 3),
                                                                                   "label": label, "what": what, "of": int(len(v))}
    out["qbs"] = qb_profiles(T, season)
    save_json(PROF, out, compact=True)
    return out


def qb_profiles(T, season):
    """Every QB who started or threw in 2021+: career starts (1999+), last start, record, EPA/dropback,
    sack and INT rate (2021+ play-by-play), by quarter (flagged: doesn't repeat), by season."""
    P = pbp(range(2021, season + 1), ["season", "season_type", "qtr", "passer_player_id", "passer_player_name", "qb_dropback",
                                       "epa", "sack", "interception", "posteam", "game_id", "qb_hit"])
    P = P[(P.qb_dropback == 1)].dropna(subset=["passer_player_id", "epa"])
    st = T.dropna(subset=["qb"])
    played = st[st.result.notna()]
    starts = played.groupby("qb").agg(n=("game_id", "size"), w=("win", "sum"), last=("day", "max"), name=("qbn", "last"),
                                      team=("team", "last"))
    out = {}
    agg = P.groupby("passer_player_id").agg(db=("epa", "size"), epa=("epa", "mean"), sk=("sack", "mean"), it=("interception", "mean"),
                                            name=("passer_player_name", "last"), team=("posteam", "last"), hit=("qb_hit", "mean"))
    bys = P.groupby(["passer_player_id", "season"]).agg(db=("epa", "size"), epa=("epa", "mean")).reset_index()
    byq = P[P.qtr <= 4].groupby(["passer_player_id", "qtr"]).epa.agg(["mean", "count"]).reset_index()
    lg_sk = float(P.sack.mean())
    for pid in set(agg.index) | set(starts.index):
        a = agg.loc[pid] if pid in agg.index else None
        s = starts.loc[pid] if pid in starts.index else None
        name = (s["name"] if s is not None else None) or (a["name"] if a is not None else pid)
        prof = {"id": pid, "name": name, "starts": int(s["n"]) if s is not None else 0,
                "record": f"{int(s['w'])}-{int(s['n'] - s['w'])}" if s is not None else None,
                "lastStart": s["last"].strftime("%Y-%m-%d") if s is not None else None}
        if a is not None:
            db = int(a["db"])
            shr = (a["epa"] * db + REPL_EPA * SHRINK_DB) / (db + SHRINK_DB)
            prof.update({"db": db, "epa": round(float(a["epa"]), 3), "epaShrunk": round(float(shr), 3),
                         "sackRate": round(100 * float(a["sk"]), 1), "intRate": round(100 * float(a["it"]), 1),
                         "leagueSack": round(100 * lg_sk, 1), "small": db < 200,
                         "bySeason": [[int(r.season), int(r.db), round(float(r.epa), 3)] for r in bys[bys.passer_player_id == pid].itertuples()],
                         "byQ": {int(r.qtr): [round(float(r["mean"]), 3), int(r["count"])] for _, r in byq[byq.passer_player_id == pid].iterrows()}})
        out[name] = prof
    return out


def _norm(n):
    import re
    return re.sub(r"[^a-z]", "", (n if isinstance(n, str) else "").lower().replace(" jr", "").replace(" iii", "").replace(" ii", ""))


def qb_lookup(prof, name):
    q = prof.get("qbs") or {}
    if name in q:
        return q[name]
    n = _norm(name)
    for k, v in q.items():
        if _norm(k) == n:
            return v
    # pbp style "D.Maye"
    parts = (name or "").split()
    if len(parts) >= 2:
        short = _norm(parts[0][0] + parts[-1])
        for k, v in q.items():
            kp = k.replace(".", " ").split()
            if len(kp) >= 2 and _norm(kp[0][0] + kp[-1]) == short:
                return v
    return None


def backup_line(prof, starter, backup, opp_sack_rank=None, today=None):
    """Plain-English profile of a backup QB vs the starter he replaces. Never invents a number:
    anything we don't have is left out."""
    from datetime import date
    s, b = qb_lookup(prof, starter), qb_lookup(prof, backup)
    if not b:
        return {"backup": backup, "starter": starter, "text": f"{backup}: no NFL passing history in our data (2021+) — treat as unproven"}
    bits = []
    bits.append(f"{b['starts']} career start{'s' if b['starts'] != 1 else ''}" + (f" ({b['record']})" if b.get("record") and b["starts"] else ""))
    if b.get("lastStart"):
        d = (today or date.today()) - date.fromisoformat(b["lastStart"])
        bits.append(f"last start {d.days // 365} yr ago" if d.days >= 365 else f"last start {d.days} days ago")
    if b.get("db"):
        bits.append(f"{b['epa']:+.2f} EPA/dropback on {b['db']} dropbacks{' (small sample)' if b['small'] else ''}")
        bits.append(f"sacked on {b['sackRate']}% (league {b['leagueSack']}%)")
    drop = None
    if s and s.get("db") and b.get("db") is not None:
        gap = s["epaShrunk"] - b["epaShrunk"]
        drop = round(gap * DB_PER_GAME, 1)
    return {"backup": backup, "starter": starter, "profile": b, "starterProfile": s, "drop": drop,
            "text": f"{backup}: " + " · ".join(bits)}


def for_board(board, tables):
    """Short context lines per team (form, coach style) and a backup-QB profile when a starting QB is
    Out/Doubtful. Context only: none of these beat the price in testing (see Learning)."""
    prof = load_json(PROF, {}) or {}
    if not prof.get("teams"):
        return
    bmap = (tables or {}).get("backup_map") or {}
    for g in board.get("games", []):
        out = {}
        for side in ("away", "home"):
            c = g["teams"][side]
            t, o = c["team"], c["opp"]
            tp, op = prof["teams"].get(t) or {}, prof["teams"].get(o) or {}
            lines = []
            st = tp.get("streak") or 0
            if st >= 3:
                lines.append(f"Won {st} straight")
            elif st <= -3:
                lines.append(f"Lost {-st} straight")
            if tp.get("lastMargin") is not None and abs(tp["lastMargin"]) >= 20:
                lines.append(f"{'Won' if tp['lastMargin'] > 0 else 'Lost'} by {abs(tp['lastMargin'])} last week vs {tp.get('lastOpp')}")
            if (tp.get("intsLast") or 0) >= 2:
                lines.append(f"Threw {tp['intsLast']} INTs last game")
            if (tp.get("toLast3") or 0) >= 6:
                lines.append(f"{tp['toLast3']} turnovers in the last 3 games")
            coach = []
            for k, r in (tp.get("coachRanks") or {}).items():
                if r["rank"] <= 3:
                    coach.append(f"{r['label']} (#{r['rank']})")
                elif r["rank"] >= r["of"] - 2 and k in ("g4", "proe", "tr4"):
                    coach.append(f"{ {'g4': 'Rarely goes for it on 4th', 'proe': 'Runs more than expected', 'tr4': 'Conservative when trailing late'}[k]} (#{r['rank']})")
            qb = None
            outs = [i for i in g.get("injuries") or [] if i.get("team") == t and i.get("pos") == "QB" and i.get("starter")
                    and i.get("status") in ("Out", "Doubtful")]
            if outs:
                starter = outs[0]["player"]
                bk = next((v for v in bmap.values() if v.get("pos") == "QB" and v.get("starter") and
                           _norm(v["starter"]).endswith(_norm(starter.split()[-1])) and (v.get("backup") or {}).get("key", "").startswith(t + "|")), None)
                if bk is None:
                    bk = next((v for k, v in bmap.items() if k.startswith(t + "|") and v.get("pos") == "QB"), None)
                if bk and bk.get("backup"):
                    qb = backup_line(prof, starter, bk["backup"]["name"])
                    pr = op.get("passRush")
                    if pr:
                        qb["oppRush"] = f"{o} pass rush #{pr['rank']} ({pr['rate']}% sacks per dropback)"
                    qb.pop("starterProfile", None)
            out[t] = {"lines": lines, "coach": coach, "coachName": tp.get("coach"), "record": f"{tp.get('w', 0)}-{tp.get('l', 0)}" + (f"-{tp['t']}" if tp.get("t") else ""),
                      "last5": tp.get("last5"), "backupQB": qb}
        g["form"] = out
