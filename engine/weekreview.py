"""Weekly pick review (Rick 2026-11-27: "use it to learn every week").

Runs once a week, right after the Monday night recap's week is final:
  1. Results by grade (A+ .. F) and by call (Buy / Wait / Pass): won-lost and profit per $1 contract
     at the kickoff price, after fees.
  2. Re-run: the same games through TODAY's engine (same saved kickoff inputs: line, price, injuries,
     weather), so we see if the current version would have called them differently.
  3. Learning: this season's results per grade next to the tested long-run rate, with this season's
     games counted more (Rick 2026-11-26: NFL rules change every year).
Nothing here changes prices on its own. The only automatic price knob is learning.update_shrink, and it
now has to pass backtest_shrink() (every game 2021-now, playoffs in, this season weighted) before it goes live.
Grade weights keep their own gate in the Tuesday re-test. Everything comes from saved data; nothing is invented.
"""
import os

from . import config as C
from . import model as M

SEASON_W = 2.0   # this season's games count double vs older seasons (Rick 2026-11-26)
HIST_N = 100     # the long-run tested rate per grade counts like 100 games of evidence
DRIFT_MIN = 15   # need 15+ picks in a grade this season before calling it off track


def _won(r, team):
    return None if r.get("tie") else r.get("winner") == team


def _net(price, won):
    pay = 50 if won is None else 100 if won else 0
    return pay - price - M.fee_cents(price)


def _add(table, k, price, won):
    o = table.setdefault(k, {"n": 0, "won": 0, "lost": 0, "net": 0.0})
    o["n"] += 1
    o["won"] += won is True
    o["lost"] += won is False
    o["net"] = round(o["net"] + _net(price, won), 1)


def results(recs, calls_of=lambda r: r.get("calls") or {}):
    """Every team side with a kickoff price, by grade (from its fair) and by call. net = cents per contract."""
    by_grade, by_call = {}, {}
    for r in recs:
        for tm, c in calls_of(r).items():
            p, f = c.get("price"), c.get("fair")
            if p is None or f is None:
                continue
            won = _won(r, tm)
            _add(by_grade, M.grade(f), p, won)
            _add(by_call, {"Value": "Buy"}.get(c.get("call"), c.get("call") or "Pass"), p, won)
    return {"byGrade": by_grade, "byCall": by_call}


# ---------- re-run with today's engine ----------
def _tables():
    from .fetch import load_json
    return (load_json(os.path.join(C.STATE, "tables.json"), {}) or {}).get("teams", {})


def rerun_game(r, snap, teams, shrink=1.0):
    """Today's pregame fair + call for one graded game, from its saved kickoff snapshot. None if inputs missing."""
    if not snap or snap.get("spreadHome") is None:
        return None
    from .board import FIXED_DOMES
    from . import profiles as PF
    away, home = r["away"], r["home"]
    margin_home = -snap["spreadHome"]
    indoor = home in FIXED_DOMES
    wx = snap.get("wx")
    adj_h, _ = M.epa_adjustment(home, away, True, False, margin_home, teams)
    w_h, _ = M.weather_pts(home, away, wx, teams, indoor)
    w_a, _ = M.weather_pts(away, home, wx, teams, indoor)
    inj = snap.get("inj") or {}
    th = snap.get("thursday") or {}
    move = snap["spreadHome"] - th["spreadHome"] if th.get("spreadHome") is not None else None
    i_h, _ = M.injury_pts(inj.get(home) or [], th.get("inj") if th else None, move)
    i_a, _ = M.injury_pts(inj.get(away) or [], th.get("inj") if th else None, move)
    try:
        g_h, _ = PF.adjust_pts(away, home)
    except Exception:
        g_h = 0.0
    f_h, f_a, _ = M.fair_pair(margin_home + adj_h + (w_h - w_a) + (i_h - i_a) + g_h, shrink)
    eq = None
    try:
        from . import watch as WT
        eq = WT.eqwd_team(r.get("season"), r.get("week"), away, home, (inj.get(away) or []) + (inj.get(home) or []))
        b = WT.EQWD_BOOST if eq else 0
    except Exception:
        b = 0
    if eq == home:
        f_h, f_a = round(min(99.0, f_h + b), 1), round(max(1.0, f_a - b), 1)
    elif eq == away:
        f_h, f_a = round(max(1.0, f_h - b), 1), round(min(99.0, f_a + b), 1)
    out = {}
    for tm, f in ((home, f_h), (away, f_a)):
        p = ((r.get("calls") or {}).get(tm) or {}).get("price")
        cl = M.classify(f, p)
        out[tm] = {"fair": f, "price": p, "call": cl["call"], "edge": cl["edge"]}
    return out


def _acc(recs, calls_of):
    n = right = 0
    brier = 0.0
    for r in recs:
        cs = calls_of(r)
        fs = {t: c.get("fair") for t, c in cs.items() if c.get("fair") is not None}
        if len(fs) != 2 or r.get("tie"):
            continue
        pick = max(fs, key=fs.get)
        n += 1
        right += r.get("winner") == pick
        brier += (fs[pick] / 100 - (r.get("winner") == pick)) ** 2
    return {"n": n, "right": right, "brier": round(brier / n, 4) if n else None}


def rerun(recs, snaps, shrink=1.0, teams=None):
    teams = _tables() if teams is None else teams
    new = {}
    for r in recs:
        try:
            x = rerun_game(r, snaps.get(r["key"]), teams, shrink)
        except Exception as e:
            print("rerun failed:", r.get("key"), e)
            x = None
        if x:
            new[r["key"]] = x
    used = [r for r in recs if r["key"] in new]
    then = lambda r: r.get("calls") or {}
    now = lambda r: new.get(r["key"], {})
    changed = []
    for r in used:
        for tm, c in now(r).items():
            old = then(r).get(tm) or {}
            if (old.get("call") or "Pass") != c["call"]:
                changed.append({"team": tm, "from": old.get("call") or "Pass", "to": c["call"],
                                "fairThen": old.get("fair"), "fairNow": c["fair"], "won": _won(r, tm)})
    fair_moved = sum(1 for r in used for tm, c in now(r).items()
                     if abs((c["fair"] or 0) - ((then(r).get(tm) or {}).get("fair") or 0)) >= 1)
    return {"games": len(used), "changed": changed, "fairMoved": fair_moved,
            "then": {**results(used, then), **_acc(used, then)},
            "now": {**results(used, now), **_acc(used, now)}}


# ---------- learning: this season weighted more ----------
def season_by_grade(L, season):
    """Pick side only (the team the app picks), this season's graded games."""
    out = {}
    for r in (L.get("graded") or {}).values():
        if r.get("season") != season or r.get("tie"):
            continue
        g = M.grade(r.get("pickFair"))
        o = out.setdefault(g, {"n": 0, "won": 0, "pred": 0.0})
        o["n"] += 1
        o["won"] += bool(r.get("right"))
        o["pred"] += r.get("pickFair") or 0
    rows = {}
    for g, o in out.items():
        tested = M.GRADE_TESTED.get(g)
        act = 100 * o["won"] / o["n"]
        pred = o["pred"] / o["n"]
        w = SEASON_W * o["n"]
        blend = (w * act + HIST_N * tested) / (w + HIST_N) if tested is not None else act
        se = 100 * ((pred / 100) * (1 - pred / 100) / o["n"]) ** 0.5
        off = o["n"] >= DRIFT_MIN and abs(act - pred) > 2 * se
        rows[g] = {"n": o["n"], "won": o["won"], "actual": round(act, 1), "pred": round(pred, 1),
                   "tested": tested, "weighted": round(blend, 1), "offTrack": off}
    return rows


def backtest_shrink(factor, season=None, path=None):
    """Gate for any fair-value change: Brier score of the sportsbook-line fair with and without `factor`
    on every 2021-now game (playoffs in, preseason out), this season counted SEASON_W times.
    Passes only if it is better weighted AND not worse this season. None if the games file is missing."""
    import pandas as pd
    from .fetch import nflverse_csv
    try:
        g = pd.read_csv(path or nflverse_csv("schedules", "games.csv"),
                        usecols=["season", "game_type", "spread_line", "result"])
    except Exception as e:
        print("shrink backtest: no games file:", e)
        return None
    season = season or int(g.season.max())
    g = g[(g.season >= 2021) & (g.season <= season) & g.result.notna() & g.spread_line.notna() & (g.result != 0)]
    if g.empty:
        return None

    def brier(f, rows):
        p = rows.spread_line.apply(lambda m: M.fair_pair(float(m), f)[0] / 100)
        return ((p - (rows.result > 0).astype(float)) ** 2)

    w = (g.season == season).map({True: SEASON_W, False: 1.0})
    base, cand = brier(1.0, g), brier(factor, g)
    cur = g.season == season
    wb, wc = float((base * w).sum() / w.sum()), float((cand * w).sum() / w.sum())
    sb = float(base[cur].mean()) if cur.any() else None
    sc = float(cand[cur].mean()) if cur.any() else None
    ok = wc < wb and (sb is None or sc <= sb)
    return {"factor": factor, "games": int(len(g)), "season": season, "brierBase": round(wb, 5),
            "brierNew": round(wc, 5), "seasonBase": None if sb is None else round(sb, 5),
            "seasonNew": None if sc is None else round(sc, 5), "passed": bool(ok)}


# ---------- the weekly item + one recap line ----------
def _rec(o):
    return f"{o['won']}-{o['lost']}" if o else "0-0"


def learned_line(week_res, rr, season_rows, shrink):
    bits = []
    bg = week_res["byGrade"]
    a = {k: sum(bg.get(g, {}).get(k, 0) for g in ("A+", "A")) for k in ("won", "lost")}
    if a["won"] + a["lost"]:
        bits.append(f"A picks {a['won']}-{a['lost']}")
    if bg.get("B"):
        bits.append(f"B {_rec(bg['B'])}")
    if rr and rr["games"]:
        ch = rr["changed"]
        if not ch:
            bits.append("today's engine: same calls")
        else:
            nb = sum(1 for c in ch if c["to"] == "Value") - sum(1 for c in ch if c["from"] == "Value")
            bits.append(f"today's engine changes {len(ch)} call{'s' if len(ch) != 1 else ''}"
                        + (f" ({'+' if nb > 0 else ''}{nb} Buy)" if nb else ""))
    off = [g for g, r in season_rows.items() if r["offTrack"]]
    if off:
        r = season_rows[off[0]]
        bits.append(f"{off[0]} picks winning {r['actual']:.0f}% vs {r['pred']:.0f}% expected this season, flagged for re-test")
    else:
        bits.append("grades on track")
    s = shrink or {}
    if s.get("factor", 1.0) != 1.0:
        bits.append(f"fairs trimmed ×{s['factor']} (passed backtest)")
    elif s.get("gate") and not s["gate"].get("passed"):
        bits.append("a fair change failed the backtest, so nothing changed")
    else:
        bits.append("no change")
    return "Learned: " + "; ".join(bits) + "."


def review(L, season, week, snaps):
    recs = [r for r in (L.get("graded") or {}).values() if r.get("season") == season and r.get("week") == week]
    if not recs:
        return None
    wk = results(recs)
    try:
        rr = rerun(recs, snaps, (L.get("shrink") or {}).get("factor", 1.0))
    except Exception as e:
        print("weekly re-run failed:", e)
        rr = None
    rows = season_by_grade(L, season)
    return {**wk, "rerun": rr, "seasonGrades": rows, "seasonWeight": SEASON_W,
            "learned": learned_line(wk, rr, rows, L.get("shrink"))}


def attach(L, season, week, snaps):
    """Add the review to that week's weekly item (once). Returns the review or None."""
    item = next((w for w in L.get("weekly") or [] if w.get("season") == season and w.get("week") == week), None)
    if item is None or item.get("review"):
        return None
    rv = review(L, season, week, snaps)
    if rv:
        item["review"] = rv
    return rv


if __name__ == "__main__":   # python -m engine.weekreview 2026 11  -> print a week's review (no save)
    import json
    import sys
    from . import learning as LR
    from .fetch import load_json
    Lx = LR.load()
    sn = load_json(os.path.join(C.STATE, "snapshots.json"), {}) or {}
    print(json.dumps(review(Lx, int(sys.argv[1]), int(sys.argv[2]), sn), indent=1))
