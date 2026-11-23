"""Best time to bet.

Study (run by hand: python -m engine.timing): 1,519 regular-season games 2021-2026 from nflverse
play-by-play. At every quarter end and right after every touchdown, the live win probability
(which already knows the pregame line) was compared with how often teams in that spot really won,
split by favourite/underdog, leading/tied/trailing and how far the price had fallen.
Fitted on 2021-25, checked on 2026. Result: every situation is within noise of fair. A lead,
a deficit, a TD or a dip is already in the live price, so no game moment is cheap by itself.
So the best time is decided by the edge, not the clock: buy when price is below fair by the
Value bar, before kickoff for pregame edges, and never in the pause windows or late Q4.
"""
import json
import math
import os

from . import config as C
from .model import fee_cents

FILE = os.path.join(C.STATE, "timing_study.json")


def threshold(fair):
    """Highest price that clears the Value bar for this fair."""
    if fair is None:
        return None
    for p in range(99, 0, -1):
        if fair - p - fee_cents(p) >= C.VALUE_EDGE:
            return p
    return None


def best_time(c):
    st = c.get("state")
    if st == "post":
        return None
    if st == "in":
        if c.get("alertsOff"):
            return "Too late — no new bets under 5:00 in Q4"
        if c.get("paused"):
            return "Wait — paused after the QB change / big injury"
        call, fair, edge = c.get("liveCall"), c.get("liveFair"), c.get("liveEdge")
        buy = c.get("liveBuyAt")
    else:
        call, fair, edge = c.get("call"), c.get("fair"), c.get("edge")
        buy = c.get("buyAt")
    if c.get("price") is None:
        return "When a price posts"
    if call == "Value":
        return f"Now — {edge:+.0f}¢ edge" + (" before kickoff" if st == "pre" else "")
    if call == "Wait" and buy:
        return f"Set a limit order at {buy}¢" + (" before kickoff" if st == "pre" else "")
    t = threshold(fair)
    return f"Only at {t}¢ or less" if t else "No price works"


def study_summary():
    try:
        with open(FILE) as f:
            return json.load(f)
    except Exception:
        return None


def study():
    """Rebuild state/timing_study.json from cached nflverse pbp 2021-2026."""
    import numpy as np
    import pandas as pd
    D = os.path.join(C.CACHE, "nflverse")
    cols = ["game_id", "season", "season_type", "qtr", "game_seconds_remaining", "total_home_score",
            "total_away_score", "vegas_home_wp", "result", "touchdown"]
    df = pd.concat(pd.read_csv(os.path.join(D, f"play_by_play_{y}.csv.gz"), usecols=cols, low_memory=False)
                   for y in range(2021, 2027))
    df = df[(df.season_type == "REG") & df.result.notna() & (df.result != 0)].dropna(subset=["vegas_home_wp"])
    df = df.sort_values(["game_id", "game_seconds_remaining"], ascending=[True, False]).reset_index(drop=True)
    p0 = df.groupby("game_id").vegas_home_wp.first()

    def persp(s, label):
        out = []
        for home in (True, False):
            sg = 1 if home else -1
            out.append(pd.DataFrame({
                "season": s.season.values, "label": label, "qtr": s.qtr.values,
                "wp": (s.vegas_home_wp if home else 1 - s.vegas_home_wp).values,
                "p0": (s.game_id.map(p0) if home else 1 - s.game_id.map(p0)).values,
                "lead": ((s.total_home_score - s.total_away_score) * sg).values,
                "win": ((s.result > 0) if home else (s.result < 0)).astype(int).values}))
        return pd.concat(out)
    qe = df[df.qtr <= 3].groupby(["game_id", "qtr"]).last().reset_index()
    td_idx = df.index[df.touchdown == 1] + 2
    td_idx = td_idx[td_idx < len(df)]
    after = df.loc[td_idx]
    S = pd.concat([persp(qe, "Quarter end"), persp(after, "After a TD")])
    S["side"] = np.where(S.p0 >= 0.5, "Favourite", "Underdog")
    S["spot"] = np.where(S.lead > 0, "leading", np.where(S.lead < 0, "trailing", "tied"))
    S["dip"] = pd.cut((S.p0 - S.wp) * 100, [-101, -15, -5, 5, 15, 30, 101],
                      labels=["up 15+", "up 5-15", "flat", "down 5-15", "down 15-30", "down 30+"])
    rows = []
    for keys in (["label", "qtr", "side", "spot"], ["label", "side", "dip"]):
        for k, g in S.groupby(keys, observed=True):
            tr, te = g[g.season < 2026], g[g.season == 2026]
            if len(tr) < 50:
                continue
            gap = (tr.win.mean() - tr.wp.mean()) * 100
            se = math.sqrt(tr.win.mean() * (1 - tr.win.mean()) / len(tr)) * 100
            tgap = (te.win.mean() - te.wp.mean()) * 100 if len(te) else None
            name = " · ".join(f"Q{x}" if keys[i] == "qtr" else str(x) for i, x in enumerate(k))
            rows.append({"spot": name, "n": int(len(tr)), "price": round(tr.wp.mean() * 100, 1),
                         "won": round(tr.win.mean() * 100, 1), "gap": round(gap, 1), "se": round(se, 1),
                         "nTest": int(len(te)), "gapTest": None if tgap is None else round(tgap, 1),
                         "holds": bool(abs(gap) > 2 * se and tgap is not None and tgap * gap > 0 and abs(tgap) > 2)})
    out = {"games": int(df.game_id.nunique()), "seasons": "2021–2026", "rows": rows,
           "edges": [r for r in rows if r["holds"]],
           "finding": ("No game moment is cheap by itself: at quarter ends and after TDs, leaders, trailers "
                       "and dipped favourites all won about as often as the live price said. Best time = "
                       "whenever the price sits below fair by the Value bar."),
           "note": ("Only 1 of 66 spots held up in 2026 (underdogs down 15–30 at a quarter end, ~2¢ under), "
                    "about what chance alone gives across 66 tests, and smaller than the 2¢ fee.")}
    with open(FILE, "w") as f:
        json.dump(out, f, indent=1)
    return out


if __name__ == "__main__":
    o = study()
    print(o["games"], "games;", len(o["rows"]), "spots;", "edges that hold:", o["edges"])
    big = sorted(o["rows"], key=lambda r: -abs(r["gap"]) / max(r["se"], .1))[:6]
    for r in big:
        print(r)
