"""Team profiles and matchup grades from free nflverse play-by-play.

What it builds for every team (rolling, last 17 games before each game, so no peeking):
  - Comeback grade: how often the team came back when trailing at half / after 3 quarters,
    versus what the live win chance said at that moment. QB late-game EPA when trailing in Q4.
  - Closer / fader grade: 2nd-half minus 1st-half EPA per play (offense and defense), and
    lead protection (won more or less often than the live price when leading after 3 quarters).
  - Scoring by quarter (for and against).
  - Pass and run offense vs pass and run defense (EPA/play), neutral pass rate (style).
  - Trenches: sack rate allowed vs pass-rush sack rate, rush stuff rate vs run-D stuff rate.
  - Recent form (last 4 vs last 17), schedule-adjusted EPA.
  - Situational: 3rd down %, red-zone TD %, explosive plays, success rate, fumble-recovery luck.
  - Kicker FG% from 40+, coach 4th-down go rate.

study() tests each one, as a matchup (home strength vs away weakness and the reverse):
  * pre-game: against the closing sportsbook line (home margin minus the line),
  * in-game: against the live win chance at half time / after Q3 (nflfastR's line-based model,
    our stand-in for the live market price).
Fit on 2021-2025, checked on 2026. A grade only counts if it is > 2.5 standard errors in the
fit years AND points the same way at > 1.5 standard errors in 2026. Only grades that count
move prices (half the measured size, capped). The rest are context lines.
It re-runs every week (weekly workflow), so a grade can start or stop counting as data arrives.
"""
import json
import math
import os

from . import config as C

FILE = os.path.join(C.STATE, "profiles_study.json")
PROF = os.path.join(C.STATE, "team_profiles.json")
WPFILE = os.path.join(C.STATE, "wp_model.json")
D = os.path.join(C.CACHE, "nflverse")
FIX = {"OAK": "LV", "SD": "LAC", "STL": "LAR", "LA": "LAR", "WAS": "WSH", "JAC": "JAX"}
from datetime import date as _date
CUR = _date.today().year if _date.today().month >= 8 else _date.today().year - 1   # current NFL season
YEARS = range(2021, CUR + 1)
WIN = 17           # rolling games for season-level grades
FORM = 4
CB_WIN = 34        # comeback/lead-protection spots are rare: two seasons
COLS = ["game_id", "season", "season_type", "week", "game_date", "home_team", "away_team", "posteam", "defteam",
        "qtr", "game_seconds_remaining", "half_seconds_remaining", "down", "ydstogo", "yardline_100", "play_type",
        "pass", "rush", "epa", "success", "yards_gained", "sack", "qb_dropback", "third_down_converted",
        "third_down_failed", "fumble", "fumble_lost", "field_goal_attempt", "field_goal_result", "kick_distance",
        "total_home_score", "total_away_score", "vegas_home_wp", "result", "spread_line", "total_line",
        "passer_player_id", "home_timeouts_remaining", "away_timeouts_remaining", "score_differential",
        "first_down", "fixed_drive", "fixed_drive_result", "wp", "weather", "roof"]


def load_pbp(years=YEARS):
    import pandas as pd
    fr = []
    for y in years:
        p = os.path.join(D, f"play_by_play_{y}.csv.gz")
        if os.path.exists(p):
            fr.append(pd.read_csv(p, usecols=lambda c: c in COLS, low_memory=False))
    df = pd.concat(fr, ignore_index=True)
    df = df[df.season_type == "REG"].copy()
    for c in ("home_team", "away_team", "posteam", "defteam"):
        df[c] = df[c].map(lambda x: FIX.get(x, x))
    return df


# ------------------------------------------------------------------ per team-game numbers
def team_games(df):
    """One row per team per game with raw counts (offense and defense)."""
    import numpy as np
    import pandas as pd
    pl = df[(df["pass"] == 1) | (df["rush"] == 1)].dropna(subset=["epa", "posteam"]).copy()
    pl["isp"] = (pl["pass"] == 1).astype(int)
    pl["isr"] = 1 - pl["isp"]
    pl["pepa"] = pl.epa * pl.isp
    pl["repa"] = pl.epa * pl.isr
    pl["expl"] = (((pl.isp == 1) & (pl.yards_gained >= 20)) | ((pl.isr == 1) & (pl.yards_gained >= 10))).astype(int)
    pl["stuff"] = ((pl.isr == 1) & (pl.yards_gained <= 0)).astype(int)
    pl["h1"] = (pl.qtr <= 2).astype(int)
    pl["h2"] = pl.qtr.isin([3, 4]).astype(int)
    pl["e1"] = pl.epa * pl.h1
    pl["e2"] = pl.epa * pl.h2
    neu = (pl.qtr <= 3) & pl.wp.between(0.2, 0.8) & pl.down.isin([1, 2])
    pl["neu"] = neu.astype(int)
    pl["neup"] = (neu & (pl.isp == 1)).astype(int)
    lt = (pl.qtr == 4) & pl.score_differential.between(-16, -1)
    pl["lt"] = lt.astype(int)
    pl["lte"] = pl.epa * pl["lt"]
    pl["fd"] = pl.first_down.fillna(0)
    pl["db"] = pl.qb_dropback.fillna(0)
    pl["sk"] = pl.sack.fillna(0)
    pl["succ"] = pl.success.fillna(0)
    agg = dict(n=("epa", "size"), epa=("epa", "sum"), pn=("isp", "sum"), pe=("pepa", "sum"), rn=("isr", "sum"),
               re=("repa", "sum"), succ=("succ", "sum"), expl=("expl", "sum"), stuff=("stuff", "sum"),
               db=("db", "sum"), sk=("sk", "sum"), n1=("h1", "sum"), e1=("e1", "sum"), n2=("h2", "sum"),
               e2=("e2", "sum"), neu=("neu", "sum"), neup=("neup", "sum"), ltn=("lt", "sum"), lte=("lte", "sum"),
               fd=("fd", "sum"))
    off = pl.groupby(["game_id", "posteam"]).agg(**agg)
    dfn = pl.groupby(["game_id", "defteam"]).agg(**agg)
    off.index.names = dfn.index.names = ["game_id", "team"]
    T = off.add_prefix("o_").join(dfn.add_prefix("d_"), how="outer").fillna(0)
    # 3rd downs
    th = df[df.down == 3].dropna(subset=["posteam"])
    t3 = th.groupby(["game_id", "posteam"]).agg(c=("third_down_converted", "sum"), f=("third_down_failed", "sum"))
    t3.index.names = ["game_id", "team"]
    d3 = th.groupby(["game_id", "defteam"]).agg(c=("third_down_converted", "sum"), f=("third_down_failed", "sum"))
    d3.index.names = ["game_id", "team"]
    T = T.join(t3.add_prefix("o3"), how="left").join(d3.add_prefix("d3"), how="left")
    # red zone: drives that reached the 20, and ended in a TD
    dr = df.dropna(subset=["posteam", "fixed_drive"]).groupby(["game_id", "posteam", "fixed_drive"]).agg(
        mn=("yardline_100", "min"), res=("fixed_drive_result", "last"))
    dr = dr[dr.mn <= 20]
    dr["td"] = (dr.res == "Touchdown").astype(int)
    rz = dr.groupby(level=[0, 1]).agg(rz=("td", "size"), rzt=("td", "sum"))
    rz.index.names = ["game_id", "team"]
    T = T.join(rz.add_prefix("o_"), how="left")
    rzd = rz.copy()
    opp = df.drop_duplicates("game_id").set_index("game_id")[["home_team", "away_team"]]
    rzd = rzd.reset_index()
    rzd["team"] = [opp.at[g, "away_team"] if t == opp.at[g, "home_team"] else opp.at[g, "home_team"]
                   for g, t in zip(rzd.game_id, rzd.team)]
    T = T.join(rzd.set_index(["game_id", "team"]).add_prefix("d_"), how="left")
    # fumbles (own and forced), kicks, 4th downs
    fu = df[df.fumble == 1].dropna(subset=["posteam"])
    of = fu.groupby(["game_id", "posteam"]).agg(fum=("fumble", "sum"), lost=("fumble_lost", "sum"))
    of.index.names = ["game_id", "team"]
    dfu = fu.groupby(["game_id", "defteam"]).agg(fum=("fumble", "sum"), lost=("fumble_lost", "sum"))
    dfu.index.names = ["game_id", "team"]
    T = T.join(of.add_prefix("of_"), how="left").join(dfu.add_prefix("df_"), how="left")
    fg = df[(df.field_goal_attempt == 1) & (df.kick_distance >= 40)].dropna(subset=["posteam"])
    fg = fg.assign(m=(fg.field_goal_result == "made").astype(int)).groupby(["game_id", "posteam"]).agg(
        fga=("m", "size"), fgm=("m", "sum"))
    fg.index.names = ["game_id", "team"]
    T = T.join(fg, how="left")
    f4 = df[(df.down == 4) & (df.ydstogo <= 2) & (df.yardline_100 <= 60) & (df.half_seconds_remaining > 120)
            & df.play_type.isin(["pass", "run", "punt", "field_goal"])].dropna(subset=["posteam"])
    f4 = f4.assign(go=f4.play_type.isin(["pass", "run"]).astype(int)).groupby(["game_id", "posteam"]).agg(
        g4n=("go", "size"), g4=("go", "sum"))
    f4.index.names = ["game_id", "team"]
    T = T.join(f4, how="left").fillna(0).reset_index()
    # game info, points by quarter, spots
    G = game_table(df)
    T = T.merge(G[["game_id", "season", "week", "game_date", "home_team", "away_team"]], on="game_id")
    T["home"] = T.team == T.home_team
    T["opp"] = np.where(T.home, T.away_team, T.home_team)
    for q in (1, 2, 3, 4):
        T[f"pf{q}"] = np.where(T.home, T.game_id.map(G.set_index("game_id")[f"h{q}"]),
                               T.game_id.map(G.set_index("game_id")[f"a{q}"]))
        T[f"pa{q}"] = np.where(T.home, T.game_id.map(G.set_index("game_id")[f"a{q}"]),
                               T.game_id.map(G.set_index("game_id")[f"h{q}"]))
    # comeback / lead protection spots (end of Q2 and Q3): win minus live win chance
    S = spots(df)
    for kind in ("tr", "ld"):
        s = S[S.kind == kind].groupby(["game_id", "team"]).agg(n=("res", "size"), r=("res", "sum"))
        s.columns = [f"{kind}n", f"{kind}r"]
        T = T.merge(s, left_on=["game_id", "team"], right_index=True, how="left")
    T = T.fillna({"trn": 0, "trr": 0, "ldn": 0, "ldr": 0})
    # QB: starter = passer with most dropbacks in the game; QB-level late-trailing EPA
    qb = df[(df.qb_dropback == 1)].dropna(subset=["passer_player_id", "posteam"])
    st = qb.groupby(["game_id", "posteam"]).passer_player_id.agg(lambda x: x.value_counts().index[0])
    st.index.names = ["game_id", "team"]
    T = T.merge(st.rename("qb"), left_on=["game_id", "team"], right_index=True, how="left")
    return T.sort_values(["game_date", "game_id"]).reset_index(drop=True), G, S


def game_table(df):
    import pandas as pd
    g = df.groupby("game_id")
    G = g.agg(season=("season", "first"), week=("week", "first"), game_date=("game_date", "first"),
              home_team=("home_team", "first"), away_team=("away_team", "first"), result=("result", "first"),
              spread_line=("spread_line", "first"), total_line=("total_line", "first"),
              weather=("weather", "first"), roof=("roof", "first")).reset_index()
    q = df[df.qtr <= 4].groupby(["game_id", "qtr"])[["total_home_score", "total_away_score"]].max().unstack()
    q = q.T.groupby(level=0).ffill().T.fillna(0)  # quarter with no change
    for i in (1, 2, 3, 4):
        h = q[("total_home_score", i)] - (q[("total_home_score", i - 1)] if i > 1 else 0)
        a = q[("total_away_score", i)] - (q[("total_away_score", i - 1)] if i > 1 else 0)
        G[f"h{i}"] = G.game_id.map(h)
        G[f"a{i}"] = G.game_id.map(a)
    return G


def spots(df):
    """End of Q2 and Q3: each side's live win chance (nflfastR, line-based), lead, and the
    in-game box (yards/play, first downs per play) up to that moment."""
    import numpy as np
    import pandas as pd
    d = df.dropna(subset=["vegas_home_wp"]).sort_values(["game_id", "game_seconds_remaining"],
                                                         ascending=[True, False])
    d = d[d.result.notna() & (d.result != 0)]
    last = d[d.qtr.isin([2, 3])].groupby(["game_id", "qtr"]).last().reset_index()
    pl = df[((df["pass"] == 1) | (df["rush"] == 1))].dropna(subset=["posteam"])
    box = {}
    for q in (2, 3):
        b = pl[pl.qtr <= q].groupby(["game_id", "posteam"]).agg(y=("yards_gained", "sum"), n=("yards_gained", "size"),
                                                                 fd=("first_down", "sum"))
        box[q] = b
    rows = []
    for home in (True, False):
        tm = last.home_team if home else last.away_team
        op = last.away_team if home else last.home_team
        sg = 1 if home else -1
        wp = last.vegas_home_wp if home else 1 - last.vegas_home_wp
        lead = (last.total_home_score - last.total_away_score) * sg
        win = ((last.result > 0) if home else (last.result < 0)).astype(int)
        r = pd.DataFrame({"game_id": last.game_id, "season": last.season, "qtr": last.qtr, "team": tm, "opp": op,
                          "wp": wp, "lead": lead, "win": win, "home": home})
        rows.append(r)
    S = pd.concat(rows, ignore_index=True)
    S["res"] = S.win - S.wp
    S["kind"] = np.where(S.lead < 0, "tr", np.where(S.lead > 0, "ld", "tie"))
    for side, col in (("team", "t"), ("opp", "o")):
        ys, ns, fs = [], [], []
        for g, tmn, q in zip(S.game_id, S[side], S.qtr):
            b = box[q]
            v = b.loc[(g, tmn)] if (g, tmn) in b.index else None
            ys.append(v.y if v is not None else np.nan)
            ns.append(v.n if v is not None else np.nan)
            fs.append(v.fd if v is not None else np.nan)
        S[col + "y"], S[col + "n"], S[col + "fd"] = ys, ns, fs
    S["ypp_d"] = S.ty / S.tn - S.oy / S.on
    S["fdr_d"] = S.tfd / S.tn - S.ofd / S.on
    return S


# ------------------------------------------------------------------ rolling (pre-game) grades
SUMS = [c for c in ("o_n o_epa o_pn o_pe o_rn o_re o_succ o_expl o_stuff o_db o_sk o_n1 o_e1 o_n2 o_e2 o_neu o_neup "
                    "o_ltn o_lte d_ltn d_lte d_n d_epa d_pn d_pe d_rn d_re d_succ d_expl d_stuff d_db d_sk d_n1 d_e1 d_n2 d_e2 "
                    "o3c o3f d3c d3f o_rz o_rzt d_rz d_rzt of_fum of_lost df_fum df_lost fga fgm g4n g4 "
                    "pf1 pf2 pf3 pf4 pa1 pa2 pa3 pa4").split()]


def _ratio(a, b, prior=0.0, k=0.0):
    import numpy as np
    return (a + prior * k) / np.maximum(b + k, 1e-9)


def grades(T):
    """Adds pre-game grades (prior games only) to the team-game table."""
    import numpy as np
    T = T.copy()
    g = T.groupby("team", sort=False)
    R = {}
    for c in SUMS:
        R[c] = g[c].transform(lambda s: s.shift(1).rolling(WIN, min_periods=1).sum())
    R4 = {c: g[c].transform(lambda s: s.shift(1).rolling(FORM, min_periods=1).sum()) for c in ("o_n", "o_epa", "d_n", "d_epa")}
    for c in ("trn", "trr", "ldn", "ldr"):
        R[c] = g[c].transform(lambda s: s.shift(1).rolling(CB_WIN, min_periods=1).sum())
    T["gp"] = g.cumcount().clip(upper=WIN)
    gp = T.gp.clip(lower=1)
    T["passOff"] = _ratio(R["o_pe"], R["o_pn"], 0.05, 100)
    T["rushOff"] = _ratio(R["o_re"], R["o_rn"], -0.08, 100)
    T["passDef"] = _ratio(R["d_pe"], R["d_pn"], 0.05, 100)       # EPA allowed (higher = worse D)
    T["rushDef"] = _ratio(R["d_re"], R["d_rn"], -0.08, 100)
    T["passRate"] = _ratio(R["o_neup"], R["o_neu"], 0.55, 50)
    T["netEpa"] = _ratio(R["o_epa"], R["o_n"], 0, 100) - _ratio(R["d_epa"], R["d_n"], 0, 100)
    T["form"] = (_ratio(R4["o_epa"], R4["o_n"], 0, 60) - _ratio(R4["d_epa"], R4["d_n"], 0, 60)) - T.netEpa
    T["h2h1"] = (_ratio(R["o_e2"], R["o_n2"], 0, 100) - _ratio(R["d_e2"], R["d_n2"], 0, 100)) - \
                (_ratio(R["o_e1"], R["o_n1"], 0, 100) - _ratio(R["d_e1"], R["d_n1"], 0, 100))
    T["sackAllowed"] = _ratio(R["o_sk"], R["o_db"], 0.065, 150)
    T["sackRate"] = _ratio(R["d_sk"], R["d_db"], 0.065, 150)
    T["stuffAllowed"] = _ratio(R["o_stuff"], R["o_rn"], 0.18, 100)
    T["stuffRate"] = _ratio(R["d_stuff"], R["d_rn"], 0.18, 100)
    T["third"] = _ratio(R["o3c"], R["o3c"] + R["o3f"], 0.39, 40)
    T["thirdD"] = _ratio(R["d3c"], R["d3c"] + R["d3f"], 0.39, 40)
    T["rzTd"] = _ratio(R["o_rzt"], R["o_rz"], 0.56, 20)
    T["rzTdD"] = _ratio(R["d_rzt"], R["d_rz"], 0.56, 20)
    T["expl"] = _ratio(R["o_expl"], R["o_n"], 0.08, 150)
    T["explD"] = _ratio(R["d_expl"], R["d_n"], 0.08, 150)
    T["succ"] = _ratio(R["o_succ"], R["o_n"], 0.44, 150)
    T["succD"] = _ratio(R["d_succ"], R["d_n"], 0.44, 150)
    own = R["of_fum"] - R["of_lost"] + R["df_lost"]
    T["fumLuck"] = _ratio(own, R["of_fum"] + R["df_fum"], 0.5, 10) - 0.5
    T["fg40"] = _ratio(R["fgm"], R["fga"], 0.75, 10)
    T["go4"] = _ratio(R["g4"], R["g4n"], 0.5, 10)
    for q in (1, 2, 3, 4):
        T[f"q{q}For"] = R[f"pf{q}"] / gp
        T[f"q{q}Against"] = R[f"pa{q}"] / gp
    T["comeback"] = R["trr"] / (R["trn"] + 8)       # wins above the live price per trailing spot (shrunk)
    T["comebackN"] = R["trn"]
    T["protect"] = R["ldr"] / (R["ldn"] + 8)
    T["protectN"] = R["ldn"]
    T["lateQbEpa"] = _ratio(R["o_lte"], R["o_ltn"], 0, 40)
    # defense side: Q4 EPA allowed while ahead by 1-16 (stopping comebacks), 2nd-half minus 1st-half EPA allowed
    T["lateDef"] = _ratio(R["d_lte"], R["d_ltn"], 0, 40)
    T["h2D"] = _ratio(R["d_e2"], R["d_n2"], 0, 100) - _ratio(R["d_e1"], R["d_n1"], 0, 100)
    # schedule strength: mean pre-game netEpa of the opponents faced (prior 17)
    key = T.set_index(["game_id", "team"]).netEpa
    T["oppNet"] = [key.get((gid, o), np.nan) for gid, o in zip(T.game_id, T.opp)]
    T["sos"] = g.oppNet.transform(lambda s: s.shift(1).rolling(WIN, min_periods=1).mean())
    T["adjEpa"] = T.netEpa + T.sos.fillna(0)
    # QB-level late-trailing EPA (by starter, two seasons)
    q = T.dropna(subset=["qb"]).groupby("qb", sort=False)
    T.loc[q.o_ltn.obj.index, "qbLtn"] = q.o_ltn.transform(lambda s: s.shift(1).rolling(CB_WIN, min_periods=1).sum())
    T.loc[q.o_lte.obj.index, "qbLte"] = q.o_lte.transform(lambda s: s.shift(1).rolling(CB_WIN, min_periods=1).sum())
    T["qbLate"] = _ratio(T.qbLte.fillna(0), T.qbLtn.fillna(0), 0, 40)
    return T


# matchup features, home perspective: (home strength vs away weakness) - (away strength vs home weakness)
def _m(H, A, f):
    return f(H, A) - f(A, H)


MATCHUPS = {
    "Pass offense vs pass defense": lambda t, o: t.passOff + o.passDef,
    "Run offense vs run defense": lambda t, o: t.rushOff + o.rushDef,
    "Style: pass-heavy offense vs weak pass D": lambda t, o: t.passRate * (t.passOff + o.passDef) + (1 - t.passRate) * (t.rushOff + o.rushDef),
    "Pass rush vs pass protection": lambda t, o: -(t.sackAllowed + o.sackRate),
    "Run blocking vs run-stuffing D": lambda t, o: -(t.stuffAllowed + o.stuffRate),
    "Q1 scoring (for vs opp allowed)": lambda t, o: t.q1For + o.q1Against,
    "Q2 scoring": lambda t, o: t.q2For + o.q2Against,
    "Q3 scoring": lambda t, o: t.q3For + o.q3Against,
    "Q4 scoring": lambda t, o: t.q4For + o.q4Against,
    "2nd-half closer vs fader": lambda t, o: t.h2h1,
    "Comeback grade": lambda t, o: t.comeback,
    "Lead protection": lambda t, o: t.protect,
    "Defense stops comebacks (Q4, ahead)": lambda t, o: -t.lateDef,
    "2nd-half defense (vs 1st half)": lambda t, o: -t.h2D,
    "QB late-game EPA when trailing": lambda t, o: t.qbLate,
    "Recent form (last 4 vs season)": lambda t, o: t.form,
    "Schedule-adjusted EPA": lambda t, o: t.adjEpa,
    "3rd down % vs 3rd down D": lambda t, o: t.third + o.thirdD,
    "Red-zone TD % vs red-zone D": lambda t, o: t.rzTd + o.rzTdD,
    "Explosive plays vs explosive D": lambda t, o: t.expl + o.explD,
    "Success rate vs success D": lambda t, o: t.succ + o.succD,
    "Fumble-recovery luck (regresses)": lambda t, o: t.fumLuck,
    "Kicker 40+ yd FG %": lambda t, o: t.fg40,
    "Coach 4th-down aggressiveness": lambda t, o: t.go4,
}


def game_features(T, G):
    import pandas as pd
    H = T[T.home].set_index("game_id")
    A = T[~T.home].set_index("game_id")
    ids = H.index.intersection(A.index)
    H, A = H.loc[ids], A.loc[ids]
    X = pd.DataFrame(index=ids)
    for k, f in MATCHUPS.items():
        X[k] = _m(H, A, f)
    X["minGp"] = pd.concat([H.gp, A.gp], axis=1).min(axis=1)
    g = G.set_index("game_id").loc[ids]
    X["season"], X["r"] = g.season, g.result - g.spread_line
    X["spread"], X["total"], X["result"] = g.spread_line, g.total_line, g.result
    X["weather"], X["roof"] = g.weather, g.roof
    return X


def _ols(x, y):
    import numpy as np
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 30 or x.std() == 0:
        return None
    xc = x - x.mean()
    b = (xc * (y - y.mean())).sum() / (xc ** 2).sum()
    res = y - y.mean() - b * xc
    se = math.sqrt((res ** 2).sum() / (len(x) - 2) / (xc ** 2).sum())
    return b, se, len(x)


def _test(name, x, y, train, test, unit, scale):
    """slope per 1 SD of x (in `unit`), fit years vs check year."""
    import numpy as np
    sd = np.nanstd(np.asarray(x[train], float))
    a = _ols(x[train] / sd, y[train]) if sd else None
    b = _ols(x[test] / sd, y[test]) if sd else None
    if not a:
        return None
    t_tr = a[0] / a[1]
    t_te = (b[0] / b[1]) if b else None
    holds = bool(abs(t_tr) > 2.5 and t_te is not None and t_te * t_tr > 0 and abs(t_te) > 1.5)
    return {"signal": name, "per1sd": round(a[0] * scale, 2), "z": round(t_tr, 2), "n": a[2],
            "per1sdTest": None if not b else round(b[0] * scale, 2), "zTest": None if t_te is None else round(t_te, 2),
            "nTest": b[2] if b else 0, "unit": unit, "sd": float(sd), "holds": holds}


# ------------------------------------------------------------------ our own live win %
WP_FEATS = ["l0f", "sdm", "sd", "posm", "fpm", "tom", "frac"]


def _wp_X(l0, sd, secs, pos, yl100, to_d):
    """l0: logit pregame home win chance; sd: home lead; secs: game seconds left; pos: +1 home ball,
    -1 away ball; yl100: yards to the end zone for the team with the ball; to_d: home - away timeouts."""
    import numpy as np
    m = np.asarray(secs, float) / 60.0
    frac = m / 60.0
    rt = 1.0 / np.sqrt(m + 1.0)
    fp = (50.0 - np.asarray(yl100, float)) / 50.0          # +1 at the goal line, -1 at own goal
    pos = np.asarray(pos, float)
    return np.column_stack([np.ones_like(m), np.asarray(l0) * frac, np.asarray(sd) * rt, np.asarray(sd),
                            pos * (0.6 + fp) * rt, np.asarray(to_d) * rt * (1 - frac), frac])


def _logit_fit(X, y, iters=30):
    import numpy as np
    w = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ w, -30, 30)))
        W = p * (1 - p) + 1e-6
        H = X.T @ (X * W[:, None]) + 1e-6 * np.eye(len(w))
        w -= np.linalg.solve(H, X.T @ (p - y))
    return w


def wp_study(df):
    import numpy as np
    d = df.dropna(subset=["vegas_home_wp", "posteam", "yardline_100", "spread_line"]).copy()
    d = d[(d.qtr <= 4) & d.result.notna() & (d.result != 0) & (d.game_seconds_remaining > 0)]
    p0 = 0.5 * (1 + np.vectorize(math.erf)(d.spread_line * C.SHRINK / C.SIGMA / math.sqrt(2)))
    l0 = np.log(p0.clip(0.01, 0.99) / (1 - p0.clip(0.01, 0.99)))
    sd = d.total_home_score - d.total_away_score
    pos = np.where(d.posteam == d.home_team, 1, -1)
    to_d = d.home_timeouts_remaining - d.away_timeouts_remaining
    X = _wp_X(l0, sd, d.game_seconds_remaining, pos, d.yardline_100, to_d)
    y = (d.result > 0).astype(float).values
    tr = (d.season < CUR).values
    w = _logit_fit(X[tr][::3], y[tr][::3])
    p = 1 / (1 + np.exp(-(X @ w)))
    te = ~tr
    brier_ours = float(((p[te] - y[te]) ** 2).mean())
    brier_line = float(((d.vegas_home_wp.values[te] - y[te]) ** 2).mean())
    gap = np.abs(p[te] - d.vegas_home_wp.values[te])
    out = {"weights": [float(x) for x in w], "feats": WP_FEATS, "brier": round(brier_ours, 4),
           "brierRef": round(brier_line, 4), "nTest": int(te.sum()), "medianGap": round(float(np.median(gap)) * 100, 1),
           "note": ("Our own live win % from the pregame line, score, time left, who has the ball, field "
                    "position and timeouts. Checked on every play of the current season.")}
    with open(WPFILE, "w") as f:
        json.dump(out, f, indent=1)
    return out


def live_wp(home_pre_p, home_lead, secs_left, home_ball, yl100, to_diff):
    """Our live home win chance (0-1) or None. Uses state/wp_model.json."""
    try:
        import numpy as np
        m = _wp_cache()
        if not m or home_pre_p is None or secs_left is None:
            return None
        p0 = min(max(home_pre_p, 0.01), 0.99)
        X = _wp_X([math.log(p0 / (1 - p0))], [home_lead], [max(secs_left, 0)],
                  [0 if home_ball is None else (1 if home_ball else -1)], [50 if yl100 is None else yl100],
                  [to_diff or 0])
        z = float((X @ np.array(m["weights"]))[0])
        return 1 / (1 + math.exp(-max(min(z, 30), -30)))
    except Exception:
        return None


_wpm = None


def _wp_cache():
    global _wpm
    if _wpm is None:
        try:
            with open(WPFILE) as f:
                _wpm = json.load(f)
        except Exception:
            _wpm = {}
    return _wpm


# ------------------------------------------------------------------ study
def study():
    import numpy as np
    import pandas as pd
    df = load_pbp()
    T, G, S = team_games(df)
    T = grades(T)
    X = game_features(T, G)
    X = X[X.minGp >= 4]
    tr, te = (X.season < CUR).values, (X.season == CUR).values
    rows = []
    for k in MATCHUPS:
        r = _test(k, X[k].values, X.r.values, tr, te, "pts vs line", 1.0)
        if r:
            r["kind"] = "pregame"
            rows.append(r)
    # rain / snow (favourite perspective)
    wx = X.weather.fillna("").str.lower()
    wet = wx.str.contains("rain|snow|shower|sleet|drizzle|flurr") & X.roof.isin(["outdoors", "open"])
    fav = np.sign(X.spread)
    rf = (X.r * fav).values
    for nm, m in (("Rain or snow · favourite", wet.values),):
        a, b = rf[m & tr], rf[m & te]
        if len(a) >= 30:
            se = a.std() / math.sqrt(len(a))
            seb = b.std() / math.sqrt(max(len(b), 1)) if len(b) > 1 else None
            rows.append({"signal": nm, "kind": "pregame", "per1sd": round(float(a.mean()), 2),
                         "z": round(float(a.mean() / se), 2), "n": int(len(a)),
                         "per1sdTest": round(float(b.mean()), 2) if len(b) else None,
                         "zTest": round(float(b.mean() / seb), 2) if seb else None, "nTest": int(len(b)),
                         "unit": "pts vs line (flag)", "holds": bool(abs(a.mean()) > 2.5 * se and seb and
                                                                    b.mean() * a.mean() > 0 and abs(b.mean()) > 1.5 * seb)})
    # in-game: spots vs the live win chance (cents)
    P = T.set_index(["game_id", "team"])
    S = S.join(P[["comeback", "protect", "h2h1", "qbLate", "comebackN", "lateDef", "h2D"]], on=["game_id", "team"])
    So = S.join(P[["comeback", "protect", "h2h1", "qbLate"]].add_prefix("opp_"), on=["game_id", "opp"])
    So = So[So.season >= 2021]
    trs, tes = (So.season < CUR).values, (So.season == CUR).values
    live = [
        ("Comeback grade (trailing at half / after Q3)", So.kind == "tr", So.comeback),
        ("QB late-game EPA (trailing at half / after Q3)", So.kind == "tr", So.qbLate),
        ("Lead protection (leading at half / after Q3)", So.kind == "ld", So.protect - So.opp_comeback),
        ("Defense stops comebacks (leading at half / after Q3)", So.kind == "ld", -So.lateDef),
        ("2nd-half defense (leading at half)", (So.kind == "ld") & (So.qtr == 2), -So.h2D),
        ("2nd-half closer vs fader (at half time)", So.qtr == 2, So.h2h1 - So.opp_h2h1),
        ("Outplaying but trailing: yards/play edge", So.kind == "tr", So.ypp_d),
        ("Outplaying but trailing: first-down rate edge", So.kind == "tr", So.fdr_d),
    ]
    for nm, m, x in live:
        m = m.values
        r = _test(nm, x.values[m], So.res.values[m], trs[m], tes[m], "¢ vs live price", 100.0)
        if r:
            r["kind"] = "live"
            rows.append(r)
    ob = (So.kind == "tr") & (So.ypp_d > 1.0) & (So.fdr_d > 0.03)
    a, b = So.res[ob & trs] * 100, So.res[ob & tes] * 100
    outplay = {"n": int(len(a)), "gap": round(float(a.mean()), 1), "se": round(float(a.std() / math.sqrt(len(a))), 1),
               "nTest": int(len(b)), "gapTest": round(float(b.mean()), 1) if len(b) else None}
    outplay["holds"] = bool(abs(outplay["gap"]) > 2.5 * outplay["se"] and outplay["gapTest"] is not None and
                            outplay["gapTest"] * outplay["gap"] > 0 and len(b) > 30 and
                            abs(b.mean()) > 1.5 * b.std() / math.sqrt(len(b)))
    wp = wp_study(df)
    sig = sigma_study()
    held = [r for r in rows if r["holds"]]
    out = {"builtAt": _now(), "games": int(len(X)), "train": f"2021–{CUR - 1}", "test": str(CUR),
           "rows": sorted(rows, key=lambda r: -abs(r["z"])), "held": [r["signal"] for r in held],
           "outplaying": outplay, "wpModel": {k: wp[k] for k in ("brier", "brierRef", "nTest", "medianGap")},
           "sigma": sig}
    n_pre = sum(1 for r in rows if r["kind"] == "pregame")
    n_live = sum(1 for r in rows if r["kind"] == "live")
    out["finding"] = (
        (f"{len(held)} of {len(rows)} grades beat the line in both samples: {', '.join(out['held'])}. "
         "Those now move prices (half their measured size, capped)." if held else
         f"None of {n_pre} pre-game matchup grades or {n_live} in-game grades beat the line / live price in both "
         "samples. Comebacks, 2nd-half fades, scoring by quarter, pass/run matchups, trenches, form, 3rd down, red "
         "zone, explosives, kicker and 4th-down habits are already in the price. Shown as context only.")
        + f" Teams that were outplaying the leader but trailing won {outplay['gap']:+.1f}¢ vs the live price "
          f"(n={outplay['n']}, {CUR}: {outplay['gapTest']}¢)" + (" — this holds." if outplay["holds"] else " — not enough to act on."))
    with open(FILE, "w") as f:
        json.dump(out, f, indent=1)
    build_profiles(T)
    return out


def sigma_study():
    """Does the game total change how spread-out results are? Fit sigma = 13.5*(total/44)^k."""
    import numpy as np
    import pandas as pd
    g = pd.read_csv(os.path.join(D, "games.csv"), usecols=["season", "game_type", "result", "spread_line", "total_line"])
    g = g[(g.game_type == "REG") & g.result.notna() & g.total_line.notna() & (g.result != 0) & (g.season >= 2006)]
    y = (g.result > 0).astype(float).values
    erf = np.vectorize(math.erf)

    def ll(k, m):
        s = C.SIGMA * (g.total_line.values[m] / 44.0) ** k
        p = 0.5 * (1 + erf(g.spread_line.values[m] * C.SHRINK / s / math.sqrt(2)))
        p = np.clip(p, 1e-4, 1 - 1e-4)
        return float(-(y[m] * np.log(p) + (1 - y[m]) * np.log(1 - p)).mean())
    tr = (g.season <= 2022).values
    te = ~tr
    ks = np.round(np.arange(-0.5, 1.01, 0.05), 2)
    best = min(ks, key=lambda k: ll(k, tr))
    gain_tr = ll(0, tr) - ll(best, tr)
    gain_te = ll(0, te) - ll(best, te)
    # bootstrap-free check: improvement must be positive in the check years, per 1,000 games
    holds = bool(best != 0 and gain_te > 0 and gain_tr > 0.0005)
    return {"k": float(best), "gainFit": round(gain_tr * 1000, 2), "gainTest": round(gain_te * 1000, 2),
            "holds": holds, "nFit": int(tr.sum()), "nTest": int(te.sum()),
            "note": f"Log-loss gain per 1,000 games: fit {gain_tr * 1000:.2f}, check {gain_te * 1000:.2f}."}


def _now():
    from .fetch import iso
    return iso()


# ------------------------------------------------------------------ current profiles (for the app)
def build_profiles(T=None):
    """Latest grades per team (as of the next game), ranked 1-32, saved to state/team_profiles.json."""
    import numpy as np
    if T is None:
        df = load_pbp(range(max(YEARS) - 1, max(YEARS) + 1))
        T, _, _ = team_games(df)
        T = grades(T)
    last = T.sort_values("game_date").groupby("team").tail(1).copy()
    # roll forward one game: grades are "before this game", so recompute including it
    nxt = {}
    fields = ["lateDef", "h2D", "passOff", "rushOff", "passDef", "rushDef", "passRate", "netEpa", "form", "h2h1", "sackAllowed",
              "sackRate", "stuffAllowed", "stuffRate", "third", "thirdD", "rzTd", "rzTdD", "expl", "explD",
              "succ", "succD", "fumLuck", "fg40", "go4", "q1For", "q2For", "q3For", "q4For", "q1Against",
              "q2Against", "q3Against", "q4Against", "comeback", "comebackN", "protect", "protectN", "lateQbEpa",
              "adjEpa", "qbLate"]
    # append a dummy future row per team so the shifted rolling windows include the latest game
    import pandas as pd
    fut = last.copy()
    fut["game_id"] = "next_" + fut.team
    fut["game_date"] = "9999-12-31"
    for c in SUMS + ["trn", "trr", "ldn", "ldr", "o_lte", "o_ltn"]:
        fut[c] = 0
    base = T[[c for c in T.columns if c not in fields + ["gp", "oppNet", "sos", "qbLtn", "qbLte"]]]
    G2 = grades(pd.concat([base, fut[base.columns]], ignore_index=True).sort_values(["game_date", "game_id"]))
    cur = G2[G2.game_id.astype(str).str.startswith("next_")].set_index("team")
    for t, r in cur.iterrows():
        nxt[t] = {f: (None if pd.isna(r[f]) else round(float(r[f]), 4)) for f in fields}
        nxt[t]["season"] = int(last.set_index("team").at[t, "season"])
        nxt[t]["qb"] = None if pd.isna(last.set_index("team").at[t, "qb"]) else last.set_index("team").at[t, "qb"]
    # ranks (1 = best for that team)
    better_low = {"lateDef", "h2D", "passDef", "rushDef", "sackAllowed", "stuffAllowed", "thirdD", "rzTdD", "explD", "succD",
                  "q1Against", "q2Against", "q3Against", "q4Against"}
    F = pd.DataFrame({t: {f: nxt[t][f] for f in fields} for t in nxt}).T.astype(float)
    for f in fields:
        rk = F[f].rank(ascending=f in better_low, method="min", na_option="bottom")
        for t in nxt:
            nxt[t].setdefault("rank", {})[f] = int(rk[t])
    out = {"builtAt": _now(), "teams": nxt}
    with open(PROF, "w") as f:
        json.dump(out, f, indent=1, default=str)
    return out


# ------------------------------------------------------------------ app hooks
_prof = None
_stud = None


def _load():
    global _prof, _stud
    if _prof is None:
        try:
            with open(PROF) as f:
                _prof = json.load(f).get("teams", {})
        except Exception:
            _prof = {}
        try:
            with open(FILE) as f:
                _stud = json.load(f)
        except Exception:
            _stud = {}
    return _prof, _stud


def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def matchup_lines(away, home):
    """Short context lines: one team's strength against the other's weakness (real ranks)."""
    P, _ = _load()
    a, h = P.get(away), P.get(home)
    if not a or not h:
        return []
    out = []

    def edge(t, o, tn, on):
        r, ro = t["rank"], o["rank"]
        # pass / run attack vs the other D
        if r["passOff"] <= 8 and ro["passDef"] >= 25:
            out.append(f"{tn} pass attack ({_ord(r['passOff'])}) vs {on} pass D ({_ord(ro['passDef'])})")
        if r["rushOff"] <= 8 and ro["rushDef"] >= 25:
            out.append(f"{tn} run game ({_ord(r['rushOff'])}) vs {on} run D ({_ord(ro['rushDef'])})")
        if r["sackRate"] <= 6 and ro["sackAllowed"] >= 27:
            out.append(f"{tn} pass rush ({_ord(r['sackRate'])} in sack rate) vs {on} line ({_ord(ro['sackAllowed'])} in sacks allowed)")
        if r["stuffRate"] <= 6 and ro["stuffAllowed"] >= 27:
            out.append(f"{tn} run D stuffs runs ({_ord(r['stuffRate'])}) vs {on} run blocking ({_ord(ro['stuffAllowed'])})")
        if r["q4For"] <= 5 and ro["q4Against"] >= 26:
            out.append(f"{tn} scores most in Q4 ({t['q4For']:.1f}/g) vs {on} Q4 D ({o['q4Against']:.1f} allowed)")
        if r["q1For"] <= 5 and ro["q1Against"] >= 26:
            out.append(f"{tn} fast starter ({t['q1For']:.1f} Q1 pts/g) vs {on} ({o['q1Against']:.1f} allowed)")
    edge(a, h, away, home)
    edge(h, a, home, away)
    for t, tn in ((a, away), (h, home)):
        r = t["rank"]
        if r["h2h1"] >= 29:
            out.append(f"{tn} fades after half time ({_ord(r['h2h1'])} of 32)")
        elif r["h2h1"] <= 4:
            out.append(f"{tn} closes strong in the 2nd half ({_ord(r['h2h1'])})")
        if (t.get("fumLuck") or 0) >= 0.12:
            out.append(f"{tn} lucky on fumbles lately (recovered {50 + t['fumLuck'] * 100:.0f}%) — tends to even out")
    return out[:5]


def comeback_line(team, opp):
    """Live card line when a team is trailing (context unless the study says it holds)."""
    P, _ = _load()
    t = P.get(team)
    if not t:
        return None
    n = int(t.get("comebackN") or 0)
    cb = t.get("comeback") or 0
    rk = t["rank"]["comeback"]
    txt = f"Comeback grade: {_ord(rk)} of 32"
    if n >= 4:
        txt += f" ({cb * 100:+.0f}¢ vs the live price per trailing spot, {n} spots)"
    ql = t.get("lateQbEpa")
    if ql is not None:
        txt += f" · Q4 offense when behind {ql:+.2f} EPA/play"
    return txt


SCORES = [("Comeback", "comeback", "Comes back when behind"),
          ("Holds leads", "protect", "Wins when ahead"),
          ("2nd half", "h2h1", "Gets better after half time"),
          ("2nd-half D", "h2D", "Defense after half time"),
          ("Late D", "lateDef", "Stops comebacks in Q4"),
          ("Q4 scoring", "q4For", "Scores late"),
          ("Pass O", "passOff", "Passing offense"),
          ("Run O", "rushOff", "Running offense"),
          ("Pass D", "passDef", "Stops the pass"),
          ("Run D", "rushDef", "Stops the run"),
          ("Pass rush", "sackRate", "Gets sacks"),
          ("Protection", "sackAllowed", "Protects the QB")]


def scores(team):
    """League rank per grade, 1 = best in the NFL, 32 = worst."""
    P, _ = _load()
    t = P.get(team)
    if not t or not t.get("rank"):
        return []
    return [{"k": k, "r": int(t["rank"][f]), "tip": tip} for k, f, tip in SCORES if f in t["rank"]]


def half_line(team):
    """2nd-half vs 1st-half grade line (context)."""
    P, _ = _load()
    t = P.get(team)
    if not t or t.get("h2h1") is None:
        return None
    rk = t["rank"]["h2h1"]
    if rk <= 6:
        return f"2nd-half grade: {_ord(rk)} of 32 — plays better after half time"
    if rk >= 27:
        return f"2nd-half grade: {_ord(rk)} of 32 — tends to fade after half time"
    return None


def adjust_pts(away, home):
    """Points to add to the home side from grades that held up in the latest weekly study.
    Half their measured size, capped at ±1.5 pts. ([] when nothing holds.)"""
    P, Sx = _load()
    held = [r for r in (Sx or {}).get("rows", []) if r.get("holds") and r.get("kind") == "pregame" and r.get("sd")]
    a, h = P.get(away), P.get(home)
    if not held or not a or not h:
        return 0.0, []
    import pandas as pd
    H, A = pd.Series(h), pd.Series(a)
    tot, why = 0.0, []
    for r in held:
        f = MATCHUPS.get(r["signal"])
        if not f:
            continue
        try:
            x = float(_m(H, A, f)) / r["sd"]
        except Exception:
            continue
        p = 0.5 * r["per1sd"] * x
        tot += p
        why.append(f"{r['signal']} {p:+.1f} pts")
    tot = max(-1.5, min(1.5, tot))
    return tot, why
