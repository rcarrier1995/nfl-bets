"""Watch tags: four spots from the combo study that beat the closing price in older AND recent years, but
were found by searching many combinations. They are TAGS ONLY (no price or call change) and are tracked
live here; promote only if they keep holding.

"Elite QB, weak D": the team's starting QB has a career EPA/play (as main passer, every prior game) in
  the top 20%, AND the team's own defence is in the worst 20% for success rate allowed (season to date,
  blended with last season at 4 games' weight). Skipped if the opponent also qualifies.
  Study: 2006-20 397 games won 68.5% at 61c; 2021-26 162 games won 68.5% at 58.5c.
"Their D banged up": the opponent has 2+ key defenders (DL/LB/CB/S who averaged 70%+ of defensive snaps
  in their earlier games this season) listed Out or Doubtful.
  Study: 2013-20 172 games 59% at 52c; 2021-24 113 games 60% at 55c; 2025-26 43 games 67% at 56c.
"QB + WR1 beat their secondary": the starting QB (career EPA) and WR1 (most targets, career EPA per
  target) both rank 8+ places (of 32) above the opponent's pass D, and the team is priced 65-80c.
"Hot streak overpriced": QB 3+ straight 250-yd games, or RB1 / WR1 2+ straight 100-yd games. These teams
  were priced 4-9c too high, so the OTHER side is slightly better value (tracked on the other side).
Tags show before and during games (in-game exits count toward "Their D banged up").
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
TAGS = {"eqwd": "Elite QB, weak D", "dbu": "Their D banged up", "qbwr": "QB + WR1 beat their secondary",
        "hot": "Hot streak overpriced", "wrout": "Key WR out", "dogx": "Underdog experts pick"}
DEF_POS = {"DE", "DT", "NT", "DL", "LB", "OLB", "ILB", "MLB", "CB", "S", "FS", "SS", "SAF", "DB"}


def _pbp(years):
    import pandas as pd
    cols = ["game_id", "season_type", "posteam", "defteam", "pass", "rush", "success", "qb_epa", "passer_player_id",
            "passer_player_name", "receiver_player_id", "receiver_player_name", "epa"]
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
    # pass D: EPA per pass play allowed, same blend
    pe = pa.groupby(["season", "game_id", "defteam"]).epa.mean().reset_index()
    cur, prev = pe[pe.season == season], pe[pe.season == season - 1]
    lg = float(pe.epa.mean())
    pdef = {}
    for t in set(cur.defteam) | set(prev.defteam):
        c, pv = cur[cur.defteam == t].epa, prev[prev.defteam == t].epa
        pdef[t] = round((float(c.sum()) + (float(pv.mean()) if len(pv) else lg) * 4) / (len(c) + 4), 4)
    # receivers: career EPA per target (2005-2020 base + 2021 on); WR1 = most targets for the team this season
    tg = pa[pa.receiver_player_id.notna() & pa.epa.notna()]
    wr = {k: list(v) for k, v in ((load_json(BASE, {}) or {}).get("wr") or {}).items()}
    for i, x in tg.groupby("receiver_player_id").epa.agg(["sum", "size"]).iterrows():
        w = wr.setdefault(i, [0.0, 0])
        w[0] += float(x["sum"])
        w[1] += int(x["size"])
    lead = {}
    cs = tg[tg.season == season].groupby(["posteam", "receiver_player_id", "receiver_player_name"]).size().reset_index(name="n")
    for t, x in cs.groupby("posteam"):
        lead[t] = [[r.receiver_player_id, r.receiver_player_name, int(r.n)] for r in x.sort_values("n", ascending=False).head(3).itertuples()]
    out = {"at": iso(), "season": season, "qb": {k: [round(v[0] / v[1], 4), v[1]] for k, v in qb.items() if v[1]},
           "names": {k: v[0] for k, v in names.items()}, "dsr": dsr, "passD": pdef, "wrLead": lead,
           "wr": {r[0]: [round(wr[r[0]][0] / wr[r[0]][1], 4), wr[r[0]][1]] for v in lead.values() for r in v if wr.get(r[0], [0, 0])[1]},
           "streaks": _streaks(season), "cuts": {"qb": QB_CUT, "dsr": DSR_CUT}}
    save_json(FILE, out, compact=True)
    return out


def _streaks(season):
    """Consecutive most-recent games this season: QB 250+ pass yds, RB 100+ rush yds, WR/TE 100+ rec yds.
    Also each team's RB1 / WR1 by yards so far."""
    import pandas as pd
    p = os.path.join(D, f"stats_player_week_{season}.csv.gz")
    if not os.path.exists(p):
        return {}
    s = pd.read_csv(p, usecols=lambda c: c in ("player_id", "player_display_name", "position", "week", "season_type", "team",
                                               "passing_yards", "rushing_yards", "receiving_yards"), low_memory=False)
    s = s[s.season_type == "REG"].sort_values("week")
    s["team"] = _fx(s.team)

    def run(v, cut):
        n = 0
        for x in v[::-1]:
            if x >= cut:
                n += 1
            else:
                break
        return n
    out = {"players": {}, "rb1": {}, "wr1": {}}
    for (pid, t), x in s.groupby(["player_id", "team"]):
        nm, pos = x.player_display_name.iloc[-1], x.position.iloc[-1]
        r = {"name": nm, "team": t, "pass250": run(x.passing_yards.fillna(0).values, 250),
             "rush100": run(x.rushing_yards.fillna(0).values, 100), "rec100": run(x.receiving_yards.fillna(0).values, 100)}
        if r["pass250"] >= 3 or r["rush100"] >= 2 or r["rec100"] >= 2:
            out["players"][pid] = r
    for t, x in s.groupby("team"):
        rb = x[x.position == "RB"].groupby("player_id").rushing_yards.sum()
        wr = x[x.position.isin(["WR", "TE"])].groupby("player_id").receiving_yards.sum()
        if len(rb):
            out["rb1"][t] = rb.idxmax()
        if len(wr):
            out["wr1"][t] = wr.idxmax()
    return out


_SNAPS = {}


def _snaps(season):
    import pandas as pd
    if season not in _SNAPS:
        p = os.path.join(D, f"snap_counts_{season}.csv.gz")
        s = pd.read_csv(p) if os.path.exists(p) else pd.DataFrame(columns=["team", "week", "position", "game_type", "player",
                                                                           "defense_pct", "offense_pct"])
        s["team"] = _fx(s.team) if len(s) else s.team
        _SNAPS[season] = s
    return _SNAPS[season]


def _key_players(season, team, week, pos, col):
    """Players who averaged 70%+ of snaps (col) in 2+ of this team's earlier games this season."""
    s = _snaps(season)
    s = s[(s.team == team) & (s.week < week) & s.position.isin(pos) & (s.game_type == "REG")]
    out = {}
    for n, x in s.groupby("player"):
        if len(x) >= 2 and x[col].mean() >= KEY_SNAP:
            out[_norm(n)] = n
    return out


def _key_defenders(season, team, week):
    return _key_players(season, team, week, DEF_POS, "defense_pct")


# Tested edge before fee in recent years (win % minus price, 2021-26), from the combo study.
EDGE = {"eqwd": 6, "dbu": 5, "qbwr": 3, "dogx": 0}   # shrunk for selection luck (combo study Round 9c).
# dogx = 0: the experts were chosen on the same picks (+6% on 112, z ~0.5), so it's info only until live results say otherwise
FADE = {"hot": 3, "wrout": 3}   # shrunk edges (research README Round 9c: hot fade +3; key WR out ~4c raw in both eras)
# note: live results are graded against the ask (about 1c above the de-vigged price the study used), so live edges read ~1c low
LEARN_K = 150      # live games needed before our own results count as much as the study


def edges():
    """Edge per tag in cents, learned cautiously: the study's (shrunk) edge blended with how the tag has
    actually done since we started tracking it, weighted LEARN_K study games vs n live games.
    Good tags: tagged team's win % minus price. Fade tags: the other side's win % minus price."""
    lg = load_json(LOG, {}) or {}
    out = {}
    for k, tag in TAGS.items():
        prior = EDGE.get(k, FADE.get(k, 0))
        xs = [r for r in (lg.get("rows") or {}).values() if r["tag"] == tag and r.get("won") is not None and r.get("price")]
        if xs:
            live = sum(100 * r["won"] - r["price"] for r in xs) / len(xs)
            out[k] = round((prior * LEARN_K + live * len(xs)) / (LEARN_K + len(xs)), 1)
        else:
            out[k] = prior
    return out
FADE_EDGE = 3      # the other side of a hot streak: +1 to +5c, small
GAP = 5            # a leg counts for the watch-tag combo when the tested win % beats its price by 5c+


def _pct_rank(vals, higher_better=True):
    """{team: value} -> {team: 0-32 percentile rank, 32 = best} (as in the study: rank within the week)."""
    xs = {t: v for t, v in vals.items() if v is not None}
    n = len(xs)
    out = {}
    for t, v in xs.items():
        if higher_better:
            k = sum(1 for u in xs.values() if u < v) + (sum(1 for u in xs.values() if u == v) + 1) / 2
        else:
            k = sum(1 for u in xs.values() if u > v) + (sum(1 for u in xs.values() if u == v) + 1) / 2
        out[t] = 32 * k / n
    return out


def _price(c):
    for k in ("price", "pregamePrice"):
        if c.get(k) is not None:
            return c[k]
    return c.get("fair")


def for_board(board, games_list=None, week=None, early=False):
    """Tag this week's games, or (early=True) next week's with the injury report and prices known so far."""
    st = load_json(FILE, {}) or {}
    if not st.get("qb"):
        return
    season, week = board.get("season"), week or board.get("week")
    T = games()
    T = T[(T.season == season) & (T.week == week)]
    starter = {r.team: (r.qb, r.qbn) for r in T.itertuples()}
    gms = [g for g in (board.get("games", []) if games_list is None else games_list) if g.get("state") in ("pre", "in", "post")]
    info = {}
    for g in gms:
        out_names = {_norm(i.get("player")) for i in g.get("injuries") or [] if i.get("status") in ("Out", "Doubtful")}
        for side in ("away", "home"):
            c = g["teams"][side]
            t = c["team"]
            qid, qn = starter.get(t, (None, None))
            bq = ((g.get("form") or {}).get(t) or {}).get("backupQB")
            if bq and bq.get("backup"):          # starter Out/Doubtful: use the backup
                qn = bq["backup"]
                qid = st["names"].get(_short(qn))
            q = st["qb"].get(qid) if isinstance(qid, str) else None
            wr1 = next((r for r in (st.get("wrLead") or {}).get(t, []) if _short(r[1]) not in {_short(n) for n in out_names}), None)
            w = (st.get("wr") or {}).get(wr1[0]) if wr1 else None
            info[t] = {"qbId": qid, "qbName": qn, "qbEpa": q and q[0], "dsr": st["dsr"].get(t), "passD": (st.get("passD") or {}).get(t),
                       "wr1": wr1 and wr1[1], "wrEpa": w[0] if w and w[1] >= 40 else None, "price": _price(c)}
    rq = _pct_rank({t: v["qbEpa"] for t, v in info.items()})
    rw = _pct_rank({t: v["wrEpa"] for t, v in info.items()})
    rd = _pct_rank({t: v["passD"] for t, v in info.items()}, higher_better=False)
    sk = st.get("streaks") or {}
    kd, kw = {}, {}
    for g in gms:
        a, h = g["teams"]["away"]["team"], g["teams"]["home"]["team"]
        flag = {t: bool(info[t]["qbEpa"] is not None and info[t]["qbEpa"] >= QB_CUT and info[t]["dsr"] is not None
                        and info[t]["dsr"] >= DSR_CUT) for t in (a, h)}
        tags = []
        for t, o in ((a, h), (h, a)):
            v = info[t]
            if flag[t] and not flag[o]:
                tags.append({"team": t, "tag": TAGS["eqwd"], "kind": "good", "qb": v["qbName"],
                             "why": f"{v['qbName']} career {v['qbEpa']:+.2f} EPA/play (top 20%), {t} D allows {100 * v['dsr']:.0f}% success (worst 20%)"})
            # key defenders out: final injury report, plus confirmed in-game exits
            if o not in kd:
                kd[o] = _key_defenders(season, o, week)
            outs = [i["player"] for i in g.get("injuries") or [] if i.get("team") == o and i.get("status") in ("Out", "Doubtful")
                    and _norm(i.get("player")) in kd[o]]
            live = [i.get("full") or i.get("name") for i in g.get("injLive") or [] if i.get("team") == o
                    and str(i.get("state", "")).startswith("confirmed") and _norm(i.get("full") or i.get("name")) in kd[o]]
            live = [n for n in live if _norm(n) not in {_norm(x) for x in outs}]
            if len(outs) + len(live) >= 2:
                tags.append({"team": t, "tag": TAGS["dbu"], "kind": "good", "inGame": bool(live), "n": len(outs) + len(live),
                             "why": f"{o} without {len(outs) + len(live)} key defenders: {', '.join(outs + [n + ' (left the game)' for n in live])}"})
            # QB and WR1 both clearly better than the secondary they face, priced 65-80c
            if t in rq and t in rw and o in rd and v["price"] is not None and 65 <= v["price"] <= 80 \
                    and rq[t] - rd[o] >= 8 and rw[t] - rd[o] >= 8:
                tags.append({"team": t, "tag": TAGS["qbwr"], "kind": "good", "qb": v["qbName"], "wr": v["wr1"],
                             "why": f"{v['qbName']} and {v['wr1']} both rank well above {o}'s pass D, priced {v['price']:.0f}¢"})
            # hot streak: priced a bit too high, the other side is slightly better value
            hot = []
            qp = (sk.get("players") or {}).get(v["qbId"]) if isinstance(v["qbId"], str) else None
            if qp and qp["pass250"] >= 3:
                hot.append(f"{qp['name']} {qp['pass250']} straight 250-yd games")
            for k, key, lbl in (("rb1", "rush100", "rushing"), ("wr1", "rec100", "receiving")):
                pp = (sk.get("players") or {}).get((sk.get(k) or {}).get(t))
                if pp and pp[key] >= 2 and _norm(pp["name"]) not in {_norm(i.get("player")) for i in g.get("injuries") or []
                                                                     if i.get("team") == t and i.get("status") in ("Out", "Doubtful")}:
                    hot.append(f"{pp['name']} {pp[key]} straight 100-yd {lbl} games")
            if hot:
                tags.append({"team": t, "tag": TAGS["hot"], "kind": "fade",
                             "why": f"{'; '.join(hot)}. Hot teams have been priced 4–9¢ too high, so {o} is slightly better value"})
        for t, o in ((a, h), (h, a)):
            if t not in kw:
                kw[t] = _key_players(season, t, week, {"WR"}, "offense_pct")
            wo = [i["player"] for i in g.get("injuries") or [] if i.get("team") == t and i.get("status") in ("Out", "Doubtful")
                  and _norm(i.get("player")) in kw[t]]
            if wo:
                tags.append({"team": t, "tag": TAGS["wrout"], "kind": "fade", "players": wo,
                             "why": f"{', '.join(wo)} out (key WR). Teams missing a key WR have been priced about 4¢ too high, so {o} is slightly better value"})
        e = g.get("experts") or {}
        if e.get("dogPicks") and e.get("dog") in (a, h):
            tags.append({"team": e["dog"], "tag": TAGS["dogx"], "kind": "good",
                         "why": f"Picked by our underdog experts ({', '.join(n.split()[-1] for n in e['dogPicks'])}): +6% a pick over 2 seasons, small sample"})
        for x in tags:
            x["opp"] = h if x["team"] == a else a
            k = next(k for k, v in TAGS.items() if v == x["tag"])
            c = g["teams"]["away" if x["team"] == a else "home"]
            if g.get("state") == "pre" and k in EDGE and info[x["team"]]["price"] is not None:
                x["price"] = round(info[x["team"]]["price"])
                x["est"] = min(97, x["price"] + edges()[k])
            if k in FADE and g.get("state") == "pre":
                o = h if x["team"] == a else a
                if info[o]["price"] is not None:
                    x["oppPrice"] = round(info[o]["price"])
        pen = {}
        for x in tags:
            k = next(k for k, v in TAGS.items() if v == x["tag"])
            if k in FADE:
                pen[x["team"]] = max(pen.get(x["team"], 0), edges()[k])
        for x in tags:
            if x.get("est") is not None and x["team"] in pen:
                x["est"] -= pen[x["team"]]          # the same team is also overpriced (hot streak / key WR out)
                x["netOfHot"] = True
        for x in tags:
            if early:
                x["early"] = True
        if tags:
            g["watch"] = tags
        else:
            g.pop("watch", None)


def leg_estimates(board, games_list=None):
    """{(gameId, team): (tested win %, price, [tags])} for pregame legs: tag edge added to the price.
    Several tags on one leg: the biggest edge only (not added up)."""
    out = {}
    for g in (board.get("games", []) if games_list is None else games_list):
        if g.get("state") != "pre":
            continue
        for x in g.get("watch") or []:
            if x.get("est") is not None:
                k = (g["id"], x["team"])
                e = out.get(k)
                tags = (e[2] if e else []) + [x["tag"]]
                out[k] = (max(x["est"], e[0] if e else 0), x["price"], tags)
            elif x.get("oppPrice") is not None:
                o = next(t for t in (g["teams"]["away"]["team"], g["teams"]["home"]["team"]) if t != x["team"])
                k = (g["id"], o)
                e = out.get(k)
                kk = next(k2 for k2, v in TAGS.items() if v == x["tag"])
                out[k] = (max(min(97, x["oppPrice"] + edges()[kk]), e[0] if e else 0), x["oppPrice"], (e[2] if e else []) + [f"Other side of {x['team']} ({x['tag'].lower()})"])
    return out


def next_pool(games_list):
    """Legs for next week's games (early prices), same shape as the combo pool."""
    out = []
    for g in games_list or []:
        for side in ("away", "home"):
            c = g["teams"][side]
            if c.get("price") and c.get("fair") is not None and g.get("state") == "pre":
                out.append({"gameId": g["id"], "team": c["team"], "opp": c["opp"], "fair": c["fair"], "price": c["price"],
                            "call": c.get("call"), "label": g.get("short"), "state": "pre", "tags": []})
    return out


def watch_combos(board, games_list=None, pool=None):
    """Combos built only from legs whose tested win % beats their price by GAP+ (most likely to win first).
    Info only: shows the combined tested win % next to the combined price."""
    import math
    from . import config as CC
    from .combos import sanitize
    est = leg_estimates(board, games_list)
    pool = pool if pool is not None else ((board.get("combos") or {}).get("pool") or [])
    legs = []
    for l in pool:
        e = est.get((l.get("gameId"), l.get("team")))
        if e and l.get("price") and e[0] - e[1] >= GAP:
            x = sanitize(dict(l))
            x["est"] = min(97, l["price"] + (e[0] - e[1]))      # edge applied to the live leg price
            x["watchTags"] = e[2]
            legs.append(x)
    legs.sort(key=lambda l: -l["est"])
    seen, one = set(), []
    for l in legs:                      # one side per game
        if l["gameId"] not in seen:
            seen.add(l["gameId"])
            one.append(l)
    legs = one
    out = {"legs": len(legs), "gap": GAP}
    for k in range(2, min(len(legs), 6) + 1):
        sel = legs[:k]
        hit = math.prod(l["est"] / 100 for l in sel) * 100
        cost = math.prod(l["price"] / 100 for l in sel) * 100 * CC.combo_markup(k)
        out[str(k)] = {"size": k, "combo": {"size": k, "legs": sel, "hit": round(math.prod(l["fair"] / 100 for l in sel) * 100, 2)},
                       "est": round(hit, 1), "cost": round(cost, 1)}
    return out


def tag_legs(board):
    cb = board.get("combos")
    if cb is None:
        return
    cb["watch"] = watch_combos(board)
    nw = board.get("nextWeek") or []
    cb["watchNext"] = watch_combos(board, nw, next_pool(nw))
    w = {}
    for g in board.get("games", []):
        for x in g.get("watch") or []:
            w.setdefault((g["id"], x["team"]), []).append(x["tag"])
    legs = list(cb.get("pool") or [])
    for cat in ("standard", "combined", "safer", "watch"):
        for r in (cb.get(cat) or {}).values():
            if isinstance(r, dict):
                for k in ("combo", "closest"):
                    legs += (r.get(k) or {}).get("legs", [])
    for l in legs:
        for tag in w.get((l.get("gameId"), l.get("team")), []):
            if tag not in l.setdefault("tags", []):
                l["tags"].append(tag)


def track(board):
    """Log every tagged team (for 'Hot streak overpriced', the other side) with its last price before
    kickoff; grade when final. -> public summary."""
    lg = load_json(LOG, {}) or {}
    rows = lg.setdefault("rows", {})
    for g in board.get("games", []):
        side_of = {g["teams"][s]["team"]: s for s in ("away", "home")}
        for x in g.get("watch") or []:
            k = f"{board.get('season')}-w{board.get('week')}|{g['id']}|{x['team']}|{x['tag']}"
            if k not in rows and g.get("state") != "pre":
                continue     # only log tags that were known before kickoff
            bet = x["team"] if x.get("kind") != "fade" else next(t for t in side_of if t != x["team"])
            r = rows.setdefault(k, {"tag": x["tag"], "team": x["team"], "bet": bet, "game": g.get("short")})
            if g.get("state") == "pre":
                if g["teams"][side_of[bet]].get("price") is not None:
                    r["price"] = g["teams"][side_of[bet]]["price"]
                r["why"] = x["why"]
        for k, r in rows.items():
            bet = r.get("bet", r["team"])
            if r.get("won") is None and f"|{g['id']}|" in k and g.get("state") == "post" and g.get("result") and bet in side_of:
                if r.get("price") is None:
                    r["price"] = g["teams"][side_of[bet]].get("pregamePrice")
                r["won"] = None if g["result"].get("tie") else g["result"].get("winner") == bet
    lg["at"] = iso()
    save_json(LOG, lg, compact=True)
    out = {}
    for tag in TAGS.values():
        xs = [r for r in rows.values() if r["tag"] == tag and r.get("won") is not None and r.get("price")]
        n = len(xs)
        w = sum(1 for r in xs if r["won"])
        net = sum((100 - r["price"] - FEE) if r["won"] else -(r["price"] + FEE) for r in xs)
        out[tag] = {"n": n, "w": w, "price": round(float(np.mean([r["price"] for r in xs])), 1) if n else None,
                    "netPer": round(net / n, 1) if n else None, "fade": tag in (TAGS["hot"], TAGS["wrout"])}
    return {"live": out, "study": STUDY, "edges": {TAGS[k]: v for k, v in edges().items()},
            "prior": {TAGS[k]: EDGE.get(k, FADE.get(k)) for k in TAGS}, "learnK": LEARN_K}


STUDY = {
    TAGS["eqwd"]: "Our rebuild of the rule (career QB EPA top 20%, own D success allowed worst 20%): 2006–20 397 games won 68.5% at 61¢; "
                  "2021–26 162 games won 68.5% at 58.5¢. The research write-up's version (150 games, 71% at 59¢) used a slightly different cut. Edge used: +6¢ (shrunk).",
    TAGS["dbu"]: "2013–20: 172 games won 59% at 52¢. 2021–24: 113 games 60% at 55¢. 2025–26: 43 games 67% at 56¢.",
    TAGS["qbwr"]: "Priced 65–80¢: 2013–20 247 games won 82% at 73¢. 2021–24 114 games 80%. 2025–26 53 games 83% (about +4 to +8¢).",
    TAGS["wrout"]: "Team missing a key WR (70%+ snaps): priced about 4¢ too high in 2013–20 and 2021–26 (309 / 248 games). Tracked on the other side.",
    TAGS["dogx"]: "Underdog picks by our 3 best underdog experts: 50 of 112 won, +6% a pick over 2025–26. Small sample.",
    TAGS["hot"]: "Teams on a hot player streak were priced 4–9¢ too high (QB 3+ straight 250-yd games, RB1 or WR1 2+ straight "
                 "100-yd games). Betting the other side: +1 to +5¢, small. Tracked on the other side.",
}
