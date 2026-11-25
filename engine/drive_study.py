"""Live drive studies (run by hand: python -m engine.drive_study).

Uses free nflverse play-by-play, 2016 to now, regular season and playoffs (no preseason).
Fitted on 2016-2022, checked on 2023 to now.

1. Score chance: how often a drive ends in a TD or a field goal, by field spot, down and distance.
   Written to docs/data/drive_odds.json for the live field ("This drive: TD 38% · FG 21%").
2. Big swing: after a play that moves the live win % by 10+ points, did the team that gained win
   as often as the new win % said? (Over- or under-reaction.) One swing per game: counting every
   swing looks like a big over-reaction (-5 to -13 pts) but that's see-saw games counted many times.
3. Hold off: while the other team is in the red zone, was the live win % fair, and how far does it
   usually move by the end of that drive?

The live win % here is nflverse's model (it knows the pregame line), a stand-in for the market.
Kalshi's own live price history isn't free for past seasons, so a Kalshi lag can only be measured
from our own saved prices (state/price_history.json) as weeks go by.
"""
import json
import math
import os
from datetime import date as _date

from . import config as C

FILE = os.path.join(C.STATE, "drive_study.json")
ODDS = os.path.join(C.DOCS, "data", "drive_odds.json") if hasattr(C, "DOCS") else os.path.join(
    os.path.dirname(C.STATE), "docs", "data", "drive_odds.json")
CUR = _date.today().year if _date.today().month >= 8 else _date.today().year - 1
FIRST, SPLIT = 2016, 2023
COLS = ["game_id", "season", "season_type", "qtr", "half_seconds_remaining", "game_seconds_remaining",
        "posteam", "defteam", "home_team", "yardline_100", "down", "ydstogo", "fixed_drive",
        "fixed_drive_result", "vegas_home_wp", "result", "play_type"]


def ybin(y):
    for hi in (5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
        if y <= hi:
            return hi
    return 100


def dbin(d):
    return "1-3" if d <= 3 else "4-6" if d <= 6 else "7-10" if d <= 10 else "11+"


def load(D=None):
    import pandas as pd
    from .fetch import nflverse_csv
    out = []
    for y in range(FIRST, CUR + 1):
        p = os.path.join(D, f"pbp_{y}.csv.gz") if D else nflverse_csv("pbp", f"play_by_play_{y}.csv.gz")
        if p and os.path.exists(p):
            out.append(pd.read_csv(p, usecols=COLS, low_memory=False))
    df = pd.concat(out)
    df = df[df.season_type.isin(["REG", "POST"])]
    return df.sort_values(["game_id", "game_seconds_remaining"], ascending=[True, False]).reset_index(drop=True)


def calib(win, wp):
    n = len(win)
    if not n:
        return None
    w, p = float(win.mean()), float(wp.mean())
    return {"n": int(n), "price": round(p * 100, 1), "won": round(w * 100, 1), "gap": round((w - p) * 100, 1),
            "se": round(math.sqrt(max(w * (1 - w), 1e-9) / n) * 100, 1)}


def holds(tr, te):
    return bool(tr and te and abs(tr["gap"]) > 2 * tr["se"] and te["gap"] * tr["gap"] > 0 and abs(te["gap"]) > 2)


def study(D=None):
    import numpy as np
    df = load(D)
    plays = df[df.down.between(1, 4) & df.yardline_100.notna() & df.posteam.notna()
               & df.play_type.isin(["run", "pass"])].copy()

    # ---- 1. score chance table ----
    sc = plays[(plays.half_seconds_remaining >= 120) & plays.fixed_drive_result.notna()].copy()
    sc["td"] = (sc.fixed_drive_result == "Touchdown").astype(int)
    sc["fg"] = (sc.fixed_drive_result == "Field goal").astype(int)
    sc["yb"] = sc.yardline_100.map(ybin)
    sc["db"] = [("goal" if y <= d else dbin(d)) for y, d in zip(sc.yardline_100, sc.ydstogo)]
    table, err = {}, {"model": 0.0, "base": 0.0, "n": 0}
    tr, te = sc[sc.season < SPLIT], sc[sc.season >= SPLIT]
    base_td = tr.td.mean()
    for (yb, dn, db), g in sc.groupby(["yb", "down", "db"]):
        if len(g) < 40:
            continue
        table[f"{yb}|{int(dn)}|{db}"] = [round(g.td.mean() * 100), round(g.fg.mean() * 100), int(len(g))]
    # out-of-sample check: table fitted on 2016-22 vs a flat average, on 2023+
    fit = tr.groupby(["yb", "down", "db"]).td.mean()
    pr = te.set_index(["yb", "down", "db"]).index.map(lambda k: fit.get(k, base_td))
    err["model"] = round(float(((np.array(pr) - te.td.values) ** 2).mean()), 4)
    err["base"] = round(float(((base_td - te.td.values) ** 2).mean()), 4)
    err["n"] = int(len(te))
    os.makedirs(os.path.dirname(ODDS), exist_ok=True)
    with open(ODDS, "w") as f:
        json.dump({"seasons": f"{FIRST}–{CUR}", "note": "drive ends in TD / FG, % · key = yards to end zone bucket|down|distance",
                   "t": table}, f, separators=(",", ":"))

    # ---- per-play home win % change ----
    w = df.dropna(subset=["vegas_home_wp"]).copy()
    w = w[w.result.notna() & (w.result != 0)]
    w["prev"] = w.groupby("game_id").vegas_home_wp.shift(1)
    w["d"] = w.vegas_home_wp - w.prev
    w["homewin"] = (w.result > 0).astype(int)

    # ---- 2. big swing ----
    rows = []
    sw = w[w.d.abs() >= 0.10].copy()
    up = sw.d > 0     # gainer = home if home wp went up
    sw["gwp"] = np.where(up, sw.vegas_home_wp, 1 - sw.vegas_home_wp)
    sw["gwin"] = np.where(up, sw.homewin, 1 - sw.homewin)
    sw["late"] = sw.game_seconds_remaining < 600
    for name, m in [("All 10+ point swings", slice(None)),
                    ("Swing 10-20 points", sw.d.abs() < 0.2), ("Swing 20+ points", sw.d.abs() >= 0.2),
                    ("Swing, before the last 10 min", ~sw.late), ("Swing, last 10 min", sw.late)]:
        g = sw[m].groupby("game_id").head(1)   # first such swing per game: counting every swing over-weights see-saw games
        a, b = calib(g[g.season < SPLIT].gwin, g[g.season < SPLIT].gwp), calib(g[g.season >= SPLIT].gwin, g[g.season >= SPLIT].gwp)
        if a:
            rows.append({"test": "Big swing", "spot": name, "fit": a, "check": b, "holds": holds(a, b)})

    # ---- 3. hold off while the other team is in the red zone ----
    rz = w[w.down.between(1, 4) & (w.yardline_100 <= 20) & w.posteam.notna()].copy()
    rz = rz.groupby(["game_id", "fixed_drive"]).head(1)                 # first red-zone snap of each drive
    defhome = rz.defteam == rz.home_team
    rz["dwp"] = np.where(defhome, rz.vegas_home_wp, 1 - rz.vegas_home_wp)
    rz["dwin"] = np.where(defhome, rz.homewin, 1 - rz.homewin)
    nxt = w.groupby(["game_id", "fixed_drive"]).vegas_home_wp.last().rename("endwp")
    rz = rz.join(nxt, on=["game_id", "fixed_drive"])
    rz["move"] = (np.where(defhome, rz.endwp, 1 - rz.endwp) - rz.dwp) * 100
    for name, m in [("Other team in the red zone", slice(None)), ("Red zone, last 10 min", rz.game_seconds_remaining < 600)]:
        g = rz[m]
        a, b = calib(g[g.season < SPLIT].dwin, g[g.season < SPLIT].dwp), calib(g[g.season >= SPLIT].dwin, g[g.season >= SPLIT].dwp)
        mv = g.move.dropna()
        rows.append({"test": "Hold off", "spot": name, "fit": a, "check": b, "holds": holds(a, b),
                     "moveDown": round(float(mv[mv < 0].mean()), 1) if (mv < 0).any() else None,
                     "moveUp": round(float(mv[mv > 0].mean()), 1) if (mv > 0).any() else None,
                     "pctDown": round(float((mv < -1).mean() * 100))})
    out = {"games": int(df.game_id.nunique()), "seasons": f"{FIRST}–{CUR} (regular season + playoffs)",
           "split": f"fit {FIRST}–{SPLIT - 1}, checked {SPLIT}–{CUR}", "scoreChance": err, "rows": rows,
           "edges": [r for r in rows if r["holds"]]}
    with open(FILE, "w") as f:
        json.dump(out, f, indent=1)
    return out


if __name__ == "__main__":
    import sys
    print(json.dumps(study(sys.argv[1] if len(sys.argv) > 1 else None), indent=1)[:6000])
