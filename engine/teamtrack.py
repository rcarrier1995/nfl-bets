"""Team tracker (Rick 2026-11-27: "keep track and try to learn what we can about each team. Every year is a
new year and holds more weight than past years").

For every team, from free nflverse data (games.csv finals + play-by-play scores) and the app's own graded games:
  - how often the app's pick is right when it picks them, and how often they beat it when it picks against them
  - wins vs what the app's chances expected, overall and home / away
  - comebacks (won after trailing going into the 4th) and blown leads (lost after leading going into the 4th)
Each season counts half as much as the one after it (this season 1, last 0.5, two ago 0.25 ...).

INFO ONLY. backtest() checks whether a team's "beats the app" number would have improved fair values on
later games (2022-now, playoffs in, this season weighted double). Prices only change if Rick turns it on
after it passes; the weekly run just records the result. Nothing is invented: missing data = left out.
"""
import os

from . import config as C
from . import model as M
from .fetch import iso, load_json, save_json, nflverse_csv

OUT = os.path.join(C.STATE, "team_track.json")
DECAY = 0.5        # each older season counts half the next one
FIRST = 2021
K_SHRINK = 8.0     # residual shrinks toward 0 with fewer games: n / (n + 8)
SEASON_W = 2.0     # backtest: this season's games count double


def _games(season):
    import pandas as pd
    g = pd.read_csv(nflverse_csv("schedules", "games.csv"))
    g = g[(g.season >= FIRST) & (g.season <= season) & (g.game_type != "PRE") & g.result.notna() & g.spread_line.notna()].copy()
    g["home"] = g.home_team.map(C.espn_abbr)
    g["away"] = g.away_team.map(C.espn_abbr)
    g["pHome"] = g.spread_line.apply(lambda m: M.fair_pair(float(m))[0])
    return g.sort_values(["season", "week", "gameday"]).reset_index(drop=True)


def _q4_scores(season):
    """game_id -> (away, home) score going into the 4th quarter, from play-by-play. {} when files are missing."""
    import pandas as pd
    out = {}
    for y in range(FIRST, season + 1):
        try:
            d = pd.read_csv(nflverse_csv("pbp", f"play_by_play_{y}.csv.gz"), low_memory=False,
                            usecols=["game_id", "qtr", "total_home_score", "total_away_score"])
        except Exception as e:
            print("teamtrack pbp", y, "missing:", e)
            continue
        q = d[d.qtr == 4].groupby("game_id").first()
        for gid, r in q.iterrows():
            out[gid] = (r.total_away_score, r.total_home_score)
    return out


def _app_fairs(L):
    """ESPN game id -> home fair the app actually used (graded games), so this season uses real app picks."""
    out = {}
    for r in (L.get("graded") or {}).values():
        c = r.get("calls") or {}
        f = (c.get(r.get("home")) or {}).get("fair")
        if f is not None:
            out[str(r["key"]).split("|")[-1]] = f
    return out


def _blank():
    return {"w": 0.0, "n": 0.0, "exp": 0.0, "pickN": 0, "pickRight": 0, "dogN": 0, "dogWon": 0,
            "homeN": 0, "homeW": 0, "homeExp": 0.0, "awayN": 0, "awayW": 0, "awayExp": 0.0,
            "comebacks": 0, "blown": 0, "games": 0}


def build(L=None, season=None):
    from . import learning as LR
    L = L if L is not None else LR.load()
    g = _games(season or 2100)
    season = season or int(g.season.max())
    q4 = _q4_scores(season)
    app = _app_fairs(L)
    per = {}   # (team, season) -> stats
    for r in g.itertuples():
        ph = app.get(str(r.espn).split(".")[0], r.pHome) if r.espn == r.espn else r.pHome
        res = float(r.result)
        for tm, opp, is_home, p in ((r.home, r.away, True, ph), (r.away, r.home, False, 100 - ph)):
            s = per.setdefault((tm, int(r.season)), _blank())
            won = 1.0 if (res > 0) == is_home and res != 0 else 0.5 if res == 0 else 0.0
            s["games"] += 1
            s["n"] += 1
            s["w"] += won
            s["exp"] += p / 100
            if p >= 50:
                s["pickN"] += 1
                s["pickRight"] += won == 1.0
            else:
                s["dogN"] += 1
                s["dogWon"] += won == 1.0
            side = "home" if is_home else "away"
            s[side + "N"] += 1
            s[side + "W"] += won == 1.0
            s[side + "Exp"] += p / 100
            sc = q4.get(r.game_id)
            if sc is not None:
                mine, theirs = (sc[1], sc[0]) if is_home else (sc[0], sc[1])
                if mine < theirs and won == 1.0:
                    s["comebacks"] += 1
                if mine > theirs and won == 0.0:
                    s["blown"] += 1
    teams = sorted({t for t, _ in per})
    rows = {}
    for t in teams:
        cur = per.get((t, season)) or _blank()
        wsum = wres = wn = 0.0
        hres = ares = hn = an = 0.0
        for (tm, y), s in per.items():
            if tm != t:
                continue
            w = DECAY ** (season - y)
            wres += w * (s["w"] - s["exp"])
            wn += w * s["n"]
            hres += w * (s["homeW"] - s["homeExp"])
            hn += w * s["homeN"]
            ares += w * (s["awayW"] - s["awayExp"])
            an += w * s["awayN"]
            wsum += w
        rows[t] = {"team": t, "season": season, "games": cur["games"],
                   "record": f"{int(cur['w'])}-{cur['games'] - int(round(cur['w']))}",
                   "appRight": cur["pickRight"], "appPicked": cur["pickN"],
                   "upsets": cur["dogWon"], "dogGames": cur["dogN"],
                   "home": f"{cur['homeW']}-{cur['homeN'] - cur['homeW']}", "away": f"{cur['awayW']}-{cur['awayN'] - cur['awayW']}",
                   "vsApp": round(100 * (cur["w"] - cur["exp"]) / cur["n"], 1) if cur["n"] else None,
                   "vsAppWeighted": round(100 * wres / wn, 1) if wn else None,
                   "homeVsApp": round(100 * hres / hn, 1) if hn else None,
                   "awayVsApp": round(100 * ares / an, 1) if an else None,
                   "comebacks": cur["comebacks"], "blown": cur["blown"]}
        rows[t]["line"] = team_line(rows[t])
    return rows


def team_line(r):
    """One short line per team for the Learning tab."""
    bits = [r["record"]]
    if r["appPicked"]:
        bits.append(f"app right {r['appRight']} of {r['appPicked']} when picking them")
    if r["upsets"]:
        bits.append(f"{r['upsets']} upset win{'s' if r['upsets'] != 1 else ''}")
    if r["comebacks"]:
        bits.append(f"{r['comebacks']} 4th-quarter comeback{'s' if r['comebacks'] != 1 else ''}")
    if r["blown"]:
        bits.append(f"{r['blown']} blown 4th-quarter lead{'s' if r['blown'] != 1 else ''}")
    v = r.get("vsAppWeighted")
    if v is not None and abs(v) >= 5:
        bits.append(f"wins {abs(v):.0f}% {'more' if v > 0 else 'less'} than our chances (this year counted most)")
    bits.append(f"home {r['home']}, away {r['away']}")
    return f"{r['team']}: " + " · ".join(bits)


# ---------- backtest: would a team's "beats the app" number have helped later games? ----------
def backtest(season=None, ks=(0.25, 0.5, 1.0), split=False):
    """Walk every game in order. Before each game, each team's residual = decay-weighted (wins - expected)
    per game from ALL earlier games, shrunk by n/(n+K). Adjust home fair by k*(resid_home - resid_away).
    Pass = better Brier weighted (this season x2) AND not worse this season AND better in 2022-24 and 2025-now."""
    import numpy as np
    g = _games(season or 2100)
    season = season or int(g.season.max())
    hist = {}   # team -> list of (season, resid, side)
    rows = []
    for r in g.itertuples():
        def res(t, side=None):
            num = den = 0.0
            for y, x, sd in hist.get(t, []):
                if split and side and sd != side:
                    continue
                w = DECAY ** (int(r.season) - y)
                num += w * x
                den += w
            if den == 0:
                return 0.0
            return (num / den) * (den / (den + K_SHRINK))
        rh, ra = res(r.home, "home"), res(r.away, "away")
        p = r.pHome / 100
        out = 1.0 if r.result > 0 else 0.5 if r.result == 0 else 0.0
        if r.season >= 2022:
            rows.append((int(r.season), p, rh - ra, out))
        hist.setdefault(r.home, []).append((int(r.season), out - p, "home"))
        hist.setdefault(r.away, []).append((int(r.season), (1 - out) - (1 - p), "away"))
    S = np.array([x[0] for x in rows])
    P = np.array([x[1] for x in rows])
    D = np.array([x[2] for x in rows])
    O = np.array([x[3] for x in rows])
    W = np.where(S == season, SEASON_W, 1.0)

    def br(pp, m=None):
        e = (pp - O) ** 2
        return float(np.average(e[m], weights=W[m])) if m is not None else float(np.average(e, weights=W))
    early, late, cur = S <= 2024, S >= 2025, S == season
    base = {"all": br(P), "2022-24": br(P, early), "2025-now": br(P, late), "season": br(P, cur)}
    tests = []
    for k in ks:
        Q = np.clip(P + k * D, 0.01, 0.99)
        got = {"all": br(Q), "2022-24": br(Q, early), "2025-now": br(Q, late), "season": br(Q, cur)}
        ok = got["all"] < base["all"] and got["season"] <= base["season"] and got["2022-24"] < base["2022-24"] and got["2025-now"] < base["2025-now"]
        tests.append({"k": k, **{kk: round(v, 5) for kk, v in got.items()}, "passed": bool(ok)})
    return {"games": int(len(rows)), "season": season, "split": split, "base": {k: round(v, 5) for k, v in base.items()},
            "tests": tests, "passed": any(t["passed"] for t in tests), "at": iso()}


def week_notes(L, season, week, rows):
    """Recap: one short line on the team the app missed worst this week (if any), with its season line."""
    recs = [r for r in (L.get("graded") or {}).values() if r.get("season") == season and r.get("week") == week
            and not r.get("right") and not r.get("tie")]
    if not recs:
        return None
    r = max(recs, key=lambda x: x.get("pickFair") or 0)
    t = rows.get(r["pick"])
    w = r.get("winner")
    q3 = next((q for q in r.get("quarters") or [] if q.get("q") == 3), None)
    how = ""
    if q3:
        lead = (q3["cumHome"] - q3["cumAway"]) * (1 if r["pick"] == r["home"] else -1)
        if lead > 0:
            how = f"; {r['pick']} led by {lead} into the 4th"
    s = f"Team note: {w} beat {r['pick']} ({r['pickFair']:.0f}%, {M.grade(r['pickFair'])}){how}"
    if t:
        s += f". {r['pick']} this year: {t['record']}, {t['blown']} blown 4th-quarter lead{'s' if t['blown'] != 1 else ''}"
    return s + "."


def run(L=None, season=None, with_backtest=True):
    rows = build(L, season)
    prev = load_json(OUT, {}) or {}
    out = {"at": iso(), "teams": rows, "decay": DECAY,
           "backtest": prev.get("backtest")}
    if with_backtest:
        try:
            out["backtest"] = {"overall": backtest(season), "homeAway": backtest(season, split=True)}
        except Exception as e:
            print("team backtest failed:", e)
    bt = out.get("backtest") or {}
    passed = any((bt.get(k) or {}).get("passed") for k in ("overall", "homeAway"))
    out["status"] = ("Passed the backtest: ready to use in prices once Rick says yes." if passed else
                     "Info only: a team's past results vs our chances did not improve later picks in the backtest.")
    save_json(OUT, out)
    return out


if __name__ == "__main__":
    import json
    o = run()
    print(o["status"])
    print(json.dumps(o["backtest"], indent=1))
    for t in sorted(o["teams"].values(), key=lambda r: -(r["vsAppWeighted"] or 0))[:40]:
        print(t["line"])
