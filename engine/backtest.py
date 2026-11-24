"""Rebuilt winner-pick backtest from free nflverse data (schedules + team EPA).

Rick's original backtest files (~/workspace/nfl-backtest/) are not in the cloud project, so this
re-creates the parts the app needs: per-game Version B picks, Brier, calibration by fair bucket and
by confidence bucket, Value/Wait counts, preferred-price buckets. Market price = devigged moneyline
(Kalshi history isn't free). Live TD-dip, injury-by-quarter and weather-hourly studies are NOT
re-run here; their published numbers are kept as stated.
"""
import os

from . import config as C
from . import model as M
from .fetch import nflverse_csv, read_csv, save_json, load_json, iso
from .stats import team_tables

OUT = os.path.join(C.STATE, "backtest.json")


def ml_prob(ml):
    ml = float(ml)
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def run(season, last_week, local_games=None, local_team=None):
    gpath = local_games or nflverse_csv("schedules", "games.csv")
    tpath = local_team or nflverse_csv("stats_team", f"stats_team_week_{season}.csv.gz")
    g = read_csv(gpath)
    t = read_csv(tpath)
    if g is None or t is None:
        return load_json(OUT)
    g = g[(g.season == season) & (g.game_type == "REG") & (g.week <= last_week) & g.result.notna()]
    rows = []
    tbl_cache = {}
    for r in g.itertuples():
        wk = int(r.week)
        if wk not in tbl_cache:
            tbl_cache[wk] = team_tables(t, wk)
        teams = tbl_cache[wk]
        home, away = C.espn_abbr(r.home_team), C.espn_abbr(r.away_team)
        margin_home = float(r.spread_line)            # nflverse: positive = home favoured
        neutral = str(r.location) == "Neutral"
        adj, _ = M.epa_adjustment(home, away, True, neutral, margin_home, teams)
        indoor = str(r.roof) in ("dome", "closed")
        wx = None
        if not indoor and r.temp == r.temp:
            wx = {"tempMin": float(r.temp), "windMax": float(r.wind) if r.wind == r.wind else None}
        w_h, _ = M.weather_pts(home, away, wx, teams, indoor)
        w_a, _ = M.weather_pts(away, home, wx, teams, indoor)
        fh, fa, _ = M.fair_pair(margin_home + adj + w_h - w_a)
        try:
            ph, pa = ml_prob(r.home_moneyline), ml_prob(r.away_moneyline)
            mh, ma = 100 * ph / (ph + pa), 100 * pa / (ph + pa)
        except Exception:
            mh = ma = None
        hw = r.result > 0
        tie = r.result == 0
        pick_home = fh >= fa
        pf = max(fh, fa)
        right = (pick_home and hw) or (not pick_home and r.result < 0)
        out = 0.5 if tie else float(right)
        calls = {}
        for tm, f, m, won in ((home, fh, mh, hw), (away, fa, ma, r.result < 0)):
            if m is None:
                continue
            cl = M.classify(f, round(m))
            calls[tm] = {"call": cl["call"], "fair": f, "price": round(m), "won": bool(won)}
        conf = M.confidence(pf, max([c.get("fair", 0) - c.get("price", 0) - 2 for c in calls.values()] or [0]), 0.8)
        rows.append({"week": wk, "home": home, "away": away, "pickFair": pf, "right": bool(right), "tie": bool(tie),
                     "brier": round((pf / 100 - out) ** 2, 4), "fav": (mh or 50) >= 50 if pick_home else (ma or 50) >= 50,
                     "calls": calls, "conf": conf["level"]})
    n = len(rows)
    if n == 0:
        return None
    right = sum(x["right"] for x in rows)
    by_week = {}
    for x in rows:
        b = by_week.setdefault(x["week"], [0, 0])
        b[0] += x["right"]
        b[1] += 1
    cal = []
    for lo, hi in ((50, 60), (60, 70), (70, 80), (80, 101)):
        rs = [x for x in rows if lo <= x["pickFair"] < hi]
        if rs:
            cal.append({"bucket": f"{lo}–{hi if hi < 101 else 100}", "lo": lo,
                        "pred": round(sum(x["pickFair"] for x in rs) / len(rs), 1),
                        "actual": round(100 * sum(x["right"] for x in rs) / len(rs), 1), "n": len(rs)})
    calc = []
    for lvl in ("F", "C", "B", "A", "A+"):
        rs = [x for x in rows if M.grade(x["pickFair"]) == lvl]
        if rs:
            calc.append({"bucket": lvl, "pred": round(sum(x["pickFair"] for x in rs) / len(rs), 1),
                         "actual": round(100 * sum(x["right"] for x in rs) / len(rs), 1), "n": len(rs)})
    calls = [c for x in rows for c in x["calls"].values()]
    pref = [c for c in calls if c["price"] <= C.PREF_SINGLE and c["fair"] >= 50]
    above = [c for c in calls if c["price"] > C.PREF_SINGLE and c["fair"] >= 50]
    res = {"season": season, "weeks": f"1–{last_week}", "games": n, "right": right,
           "pct": round(100 * right / n, 1), "brier": round(sum(x["brier"] for x in rows) / n, 4),
           "byWeek": {str(k): {"right": v[0], "n": v[1]} for k, v in sorted(by_week.items())},
           "calibration": cal, "calibConf": calc,
           "value": sum(c["call"] == "Value" for c in calls), "wait": sum(c["call"] == "Wait" for c in calls),
           "maxEdge": round(max((c["fair"] - c["price"] - 2 for c in calls), default=0), 1),
           "prefSingles": {"n": len(pref), "won": sum(c["won"] for c in pref)},
           "aboveSingles": {"n": len(above), "won": sum(c["won"] for c in above)},
           "builtAt": iso(), "method": "Rebuilt: nflverse spread + prior-week EPA, devigged moneyline as market proxy",
           "original": {"right": 97, "games": 151, "pct": 64.2, "brierB": 0.2197,
                        "note": "Original backtest (your files): 97/151 = 64.2%; 80%+ favourites won 66.7% (n=12)"}}
    save_json(OUT, res)
    return res


def refresh_backfilled(snaps):
    """Backfilled snapshots (games that started before the app existed) were priced with the model of the day.
    Re-price them from the stored closing spread with the current model, so learning grades the model we use now.
    EPA is not priced (C.EPA_ADJ_WEIGHT = 0), so the spread alone gives the fair. Returns the keys that changed."""
    changed = []
    for key, s in snaps.items():
        if not s.get("backfilled") or s.get("spreadHome") is None or s.get("model") == C.MODEL_TAG:
            continue
        fh, fa, _ = M.fair_pair(-float(s["spreadHome"]))
        for t, f in ((s["home"], fh), (s["away"], fa)):
            x = (s.get("teams") or {}).get(t)
            if x is None:
                continue
            cl = M.classify(f, x.get("price"))
            x.update({"fair": f, "call": cl["call"], "edge": cl["edge"], "buyAt": cl["buyAt"], "fee": cl["fee"],
                      "confidence": M.confidence(f, cl["edge"], 0.6)})
        s["model"] = C.MODEL_TAG
        s["repricedAt"] = iso()
        changed.append(key)
    return changed


def backfill_snapshots(season, week, sb, snaps, local_games=None):
    """For this week's games that started before the app existed: build the pregame snapshot from
    the closing line (nflverse spread + prior-week EPA, devigged moneyline as price proxy), flagged
    'backfilled' so it's never mistaken for a real pre-kickoff Kalshi price."""
    gpath = local_games or nflverse_csv("schedules", "games.csv")
    g = read_csv(gpath)
    from .stats import load_tables
    teams = load_tables().get("teams") or {}
    if g is None:
        return 0
    g = g[(g.season == season) & (g.week == week)]
    n = 0
    for ev in sb.get("events", []):
        comp = ev["competitions"][0]
        ab = {t["homeAway"]: C.espn_abbr(t["team"]["abbreviation"]) for t in comp["competitors"]}
        key = f"{season}-w{week}|{ev['id']}"
        if key in snaps or ev["status"]["type"]["state"] == "pre":
            continue
        row = g[(g.home_team.map(C.espn_abbr) == ab["home"]) & (g.away_team.map(C.espn_abbr) == ab["away"])]
        if not len(row):
            continue
        r = row.iloc[0]
        if r.spread_line != r.spread_line:
            continue
        mh = float(r.spread_line)
        adj, _ = M.epa_adjustment(ab["home"], ab["away"], True, str(r.location) == "Neutral", mh, teams)
        fh, fa, _ = M.fair_pair(mh + adj)
        try:
            ph, pa = ml_prob(r.home_moneyline), ml_prob(r.away_moneyline)
            prh, pra = round(100 * ph / (ph + pa)), round(100 * pa / (ph + pa))
        except Exception:
            prh = pra = None
        tm = {}
        for t, f, p in ((ab["home"], fh, prh), (ab["away"], fa, pra)):
            cl = M.classify(f, p)
            tm[t] = {"fair": f, "price": p, "call": cl["call"], "edge": cl["edge"], "buyAt": cl["buyAt"],
                     "fee": cl["fee"], "confidence": M.confidence(f, cl["edge"], 0.6),
                     "why": "Backfilled from closing line"}
        snaps[key] = {"spreadHome": -mh, "total": r.total_line, "book": "closing", "kickoff": ev.get("date"),
                      "away": ab["away"], "home": ab["home"], "week": week, "season": season, "at": iso(),
                      "backfilled": True, "model": C.MODEL_TAG, "teams": tm}
        n += 1
    return n
