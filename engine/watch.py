"""Watch tags: two spots from the combo study that beat the closing price in older AND recent years, but
were found by searching many combinations. They are TAGS ONLY (no price or call change) and are tracked
live here; promote only if they keep holding.

"Elite QB, weak D": the team's starting QB has a career EPA/play (as main passer, every prior game) in
  the top 20%, AND the team's own defence is in the worst 20% for success rate allowed (season to date,
  blended with last season at 4 games' weight). Skipped if the opponent also qualifies.
  Study: 2006-20 397 games won 68.5% at 61c; 2021-26 162 games won 68.5% at 58.5c.
"Their D banged up": the opponent has 2+ key defenders (DL/LB/CB/S who averaged 70%+ of defensive snaps
  in their earlier games this season) listed Out or Doubtful.
  Study: 2013-20 172 games 59% at 52c; 2021-24 113 games 60% at 55c; 2025-26 43 games 67% at 56c.
Cutoffs are the 2006-2020 80th percentiles.
"""
import os

import numpy as np

from . import config as C
from .fetch import load_json, save_json, iso
from .form import D, _fx, _norm, games

FILE = os.path.join(C.STATE, "watch.json")
LOG = os.path.join(C.STATE, "watch_log.json")
BASE = os.path.join(C.STATE, "qb_career_base.json")
QB_CUT = 0.1734        # career qb_epa per play, 80th pct 2006-20
DSR_CUT = 0.45         # defensive success rate allowed, 80th pct 2006-20 (higher = worse)
KEY_SNAP = 0.70
FEE = 2
TAGS = {"eqwd": "Elite QB, weak D", "dbu": "Their D banged up"}
DEF_POS = {"DE", "DT", "NT", "DL", "LB", "OLB", "ILB", "MLB", "CB", "S", "FS", "SS", "SAF", "DB"}


def _pbp(years):
    import pandas as pd
    cols = ["game_id", "season_type", "posteam", "defteam", "pass", "rush", "success", "qb_epa", "passer_player_id",
            "passer_player_name"]
    fr = []
    for y in years:
        p = os.path.join(D, f"play_by_play_{y}.csv.gz")
        if os.path.exists(p):
            x = pd.read_csv(p, usecols=lambda c: c in cols, low_memory=False)
            x["season"] = y
            fr.append(x[x.season_type.isin(["REG", "POST"]) & ((x["pass"] == 1) | (x["rush"] == 1))])
    P = pd.concat(fr)
    P["posteam"], P["defteam"] = _fx(P.posteam), _fx(P.defteam)
    return P


def _short(name):
    """'Drake Maye' / 'D.Maye' -> 'dmaye' (pbp names are initial.last)."""
    kp = (name or "").replace(".", " ").split()
    return _norm(kp[0][0] + kp[-1]) if len(kp) >= 2 else _norm(name)


def build(season):
    import pandas as pd
    P = _pbp(range(2021, season + 1))
    pa = P[P["pass"] == 1]
    box = pd.DataFrame({"qb_epa": pa.groupby(["game_id", "posteam"]).qb_epa.mean(),
                        "passer": pa.groupby(["game_id", "posteam"]).passer_player_id.agg(
                            lambda s: s.mode().iloc[0] if s.notna().any() else None)}).reset_index().dropna()
    base = (load_json(BASE, {}) or {}).get("qb") or {}
    qb = {k: list(v) for k, v in base.items()}
    for r in box.itertuples():
        q = qb.setdefault(r.passer, [0.0, 0])
        q[0] += float(r.qb_epa)
        q[1] += 1
    names = {}
    for (i, n), c in pa.groupby(["passer_player_id", "passer_player_name"]).size().items():
        k = _short(n)
        if c > names.get(k, ("", 0))[1]:
            names[k] = (i, int(c))
    # defensive success rate allowed: this season to date blended with last season (4 games' weight)
    sr = P.groupby(["season", "game_id", "defteam"]).success.mean().reset_index()
    cur, prev = sr[sr.season == season], sr[sr.season == season - 1]
    lg = float(sr.success.mean())
    dsr = {}
    for t in set(cur.defteam) | set(prev.defteam):
        c = cur[cur.defteam == t].success
        pv = prev[prev.defteam == t].success
        prior = float(pv.mean()) if len(pv) else lg
        dsr[t] = round((float(c.sum()) + prior * 4) / (len(c) + 4), 4)
    out = {"at": iso(), "season": season, "qb": {k: [round(v[0] / v[1], 4), v[1]] for k, v in qb.items() if v[1]},
           "names": {k: v[0] for k, v in names.items()}, "dsr": dsr, "cuts": {"qb": QB_CUT, "dsr": DSR_CUT}}
    save_json(FILE, out, compact=True)
    return out


def _key_defenders(season, team, week):
    """Players who averaged 70%+ defensive snaps in 2+ of this team's earlier games this season."""
    import pandas as pd
    p = os.path.join(D, f"snap_counts_{season}.csv.gz")
    if not os.path.exists(p):
        return {}
    s = pd.read_csv(p)
    s["team"] = _fx(s.team)
    s = s[(s.team == team) & (s.week < week) & s.position.isin(DEF_POS) & (s.game_type == "REG")]
    out = {}
    for n, x in s.groupby("player"):
        if len(x) >= 2 and x.defense_pct.mean() >= KEY_SNAP:
            out[_norm(n)] = n
    return out


def for_board(board):
    st = load_json(FILE, {}) or {}
    if not st.get("qb"):
        return
    season, week = board.get("season"), board.get("week")
    T = games()
    T = T[(T.season == season) & (T.week == week)]
    starter = {r.team: (r.qb, r.qbn) for r in T.itertuples()}
    kd = {}
    for g in board.get("games", []):
        info = {}
        for side in ("away", "home"):
            t = g["teams"][side]["team"]
            qid, qn = starter.get(t, (None, None))
            bq = ((g.get("form") or {}).get(t) or {}).get("backupQB")
            if bq and bq.get("backup"):          # starter Out/Doubtful: use the backup
                qn = bq["backup"]
                qid = st["names"].get(_short(qn))
            q = st["qb"].get(qid) if isinstance(qid, str) else None
            info[t] = {"qbName": qn, "qbEpa": q and q[0], "qbGames": q and q[1], "dsr": st["dsr"].get(t)}
        a, h = g["teams"]["away"]["team"], g["teams"]["home"]["team"]
        flag = {t: bool(v["qbEpa"] is not None and v["qbEpa"] >= QB_CUT and v["dsr"] is not None and v["dsr"] >= DSR_CUT)
                for t, v in info.items()}
        tags = []
        for t, o in ((a, h), (h, a)):
            v = info[t]
            if flag[t] and not flag[o]:
                tags.append({"team": t, "tag": TAGS["eqwd"],
                             "why": f"{v['qbName']} career {v['qbEpa']:+.2f} EPA/play (top 20%), {t} D allows {100 * v['dsr']:.0f}% success (worst 20%)"})
            if o not in kd:
                kd[o] = _key_defenders(season, o, week)
            outs = [i["player"] for i in g.get("injuries") or [] if i.get("team") == o and i.get("status") in ("Out", "Doubtful")
                    and _norm(i.get("player")) in kd[o]]
            if len(outs) >= 2:
                tags.append({"team": t, "tag": TAGS["dbu"], "why": f"{o} without {len(outs)} key defenders: {', '.join(outs)}"})
        if tags:
            g["watch"] = tags
        else:
            g.pop("watch", None)


def tag_legs(board):
    w = {(g["id"], x["team"]): x["tag"] for g in board.get("games", []) for x in g.get("watch") or []}
    if not w:
        return
    cb = board.get("combos") or {}
    legs = list(cb.get("pool") or [])
    for cat in ("standard", "combined", "safer"):
        for r in (cb.get(cat) or {}).values():
            for k in ("combo", "closest"):
                legs += (r.get(k) or {}).get("legs", [])
    for l in legs:
        for (gid, t), tag in w.items():
            if l.get("gameId") == gid and l.get("team") == t and tag not in l.setdefault("tags", []):
                l["tags"].append(tag)


def track(board):
    """Log every tagged team with its last price before kickoff; grade when final. -> public summary."""
    lg = load_json(LOG, {}) or {}
    rows = lg.setdefault("rows", {})
    for g in board.get("games", []):
        for x in g.get("watch") or []:
            k = f"{board.get('season')}-w{board.get('week')}|{g['id']}|{x['team']}|{x['tag']}"
            side = "away" if g["teams"]["away"]["team"] == x["team"] else "home"
            c = g["teams"][side]
            if k not in rows and g.get("state") != "pre":
                continue     # only log tags that were known before kickoff
            r = rows.setdefault(k, {"tag": x["tag"], "team": x["team"], "game": g.get("short"), "why": x["why"]})
            if g.get("state") == "pre":
                if c.get("price") is not None:
                    r["price"] = c["price"]
                r["why"] = x["why"]
        for k, r in rows.items():
            if r.get("won") is None and f"|{g['id']}|" in k and g.get("state") == "post" and g.get("result"):
                if r.get("price") is None and g["teams"]["away" if g["teams"]["away"]["team"] == r["team"] else "home"].get("pregamePrice") is not None:
                    r["price"] = g["teams"]["away" if g["teams"]["away"]["team"] == r["team"] else "home"]["pregamePrice"]
                r["won"] = None if g["result"].get("tie") else g["result"].get("winner") == r["team"]
    lg["at"] = iso()
    save_json(LOG, lg, compact=True)
    out = {}
    for tag in TAGS.values():
        xs = [r for r in rows.values() if r["tag"] == tag and r.get("won") is not None and r.get("price")]
        n = len(xs)
        w = sum(1 for r in xs if r["won"])
        net = sum((100 - r["price"] - FEE) if r["won"] else -(r["price"] + FEE) for r in xs)
        out[tag] = {"n": n, "w": w, "price": round(float(np.mean([r["price"] for r in xs])), 1) if n else None,
                    "netPer": round(net / n, 1) if n else None}
    return {"live": out, "study": {
        TAGS["eqwd"]: "2006–20: 397 games won 68.5% at 61¢ avg. 2021–26: 162 games won 68.5% at 58.5¢ (about +8¢ after fee).",
        TAGS["dbu"]: "2013–20: 172 games won 59% at 52¢. 2021–24: 113 games 60% at 55¢. 2025–26: 43 games 67% at 56¢."}}
