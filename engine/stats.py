"""nflverse-derived tables: team rankings/EPA, player_prior, backup_map, top-10 lists.

Built weekly in the Thursday pregame refresh (prior-week stats don't change mid-game);
backup_map is rebuilt in the Sunday 10:30 inactives refresh. Live code only looks up.
"""
import os
import re

from . import config as C
from .fetch import nflverse_csv, read_csv, save_json, load_json, iso

TABLES = os.path.join(C.STATE, "tables.json")


def abbrev(full):
    """'Josh Sweat' -> 'J.Sweat' (nflverse/ESPN play-by-play style)."""
    if not isinstance(full, str) or not full.strip():
        return ""
    parts = [p for p in re.split(r"\s+", full.strip()) if p]
    parts = [p for p in parts if p.rstrip(".").upper() not in ("JR", "SR", "II", "III", "IV", "V")]
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0][0]}.{' '.join(parts[1:])}"


def norm_name(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def load_frames(season):
    p = nflverse_csv("stats_player", f"stats_player_week_{season}.csv.gz")
    t = nflverse_csv("stats_team", f"stats_team_week_{season}.csv.gz")
    s = nflverse_csv("snap_counts", f"snap_counts_{season}.csv.gz")
    d = nflverse_csv("depth_charts", f"depth_charts_{season}.csv")
    r = nflverse_csv("rosters", f"roster_{season}.csv")
    return read_csv(p), read_csv(t), read_csv(s), read_csv(d), read_csv(r)


def team_tables(t, before_week):
    """Pass off / Run off / Pass def / Run def: EPA/play, yds/g and rank (# of 32)."""
    if t is None or len(t) == 0:
        return {}
    t = t[(t.season_type == "REG") & (t.week < before_week)].copy()
    if len(t) == 0:
        return {}
    t["team"] = t["team"].map(C.espn_abbr)
    t["opponent_team"] = t["opponent_team"].map(C.espn_abbr)
    t["dropbacks"] = t["attempts"].fillna(0) + t["sacks_suffered"].fillna(0)
    cols = ["passing_epa", "rushing_epa", "dropbacks", "carries", "passing_yards", "rushing_yards", "attempts"]
    off = t.groupby("team")[cols].sum()
    games = t.groupby("team")["game_id"].nunique()
    # what each team ALLOWED = the opponent's offensive rows
    dfn = t.groupby("opponent_team")[cols].sum()
    out = {}
    for team in off.index:
        g = int(games.get(team, 0))
        if g == 0:
            continue
        o = off.loc[team]
        d = dfn.loc[team] if team in dfn.index else None
        rec = {
            "games": g,
            "passOff": {"epa": _div(o.passing_epa, o.dropbacks), "ypg": _div(o.passing_yards, g)},
            "runOff": {"epa": _div(o.rushing_epa, o.carries), "ypg": _div(o.rushing_yards, g)},
            "runShare": _div(o.carries, o.carries + o.dropbacks),
            "passShare": _div(o.dropbacks, o.carries + o.dropbacks),
            "playsPerGame": _div(o.carries + o.dropbacks, g),
            "offEpaPerPlay": _div(o.passing_epa + o.rushing_epa, o.carries + o.dropbacks),
        }
        if d is not None:
            rec["passDef"] = {"epa": _div(d.passing_epa, d.dropbacks), "ypg": _div(d.passing_yards, g)}
            rec["runDef"] = {"epa": _div(d.rushing_epa, d.carries), "ypg": _div(d.rushing_yards, g)}
            rec["defEpaPerPlay"] = _div(d.passing_epa + d.rushing_epa, d.carries + d.dropbacks)
        out[team] = rec
    # ranks: offense high EPA = #1; defense low EPA allowed = #1
    for key, desc in (("passOff", True), ("runOff", True), ("passDef", False), ("runDef", False)):
        vals = [(tm, r[key]["epa"]) for tm, r in out.items() if key in r and r[key]["epa"] is not None]
        vals.sort(key=lambda x: x[1], reverse=desc)
        for i, (tm, _) in enumerate(vals):
            out[tm][key]["rank"] = i + 1
    return out


def _div(a, b):
    try:
        a, b = float(a), float(b)
        return round(a / b, 4) if b else None
    except Exception:
        return None


DEF_COLS = ["def_tackles_solo", "def_tackles_with_assist", "def_sacks", "def_pass_defended",
            "def_qb_hits", "def_interceptions", "def_tackles_for_loss"]


def player_prior(p, snaps, before_week):
    """(team|abbrev) -> reliance, EPA/play, plays, snap %, games. Cumulative BEFORE the week."""
    if p is None or len(p) == 0:
        return {}, {}
    p = p[(p.season_type == "REG") & (p.week < before_week)].copy()
    p["team"] = p["team"].map(C.espn_abbr)
    for c in DEF_COLS + ["targets", "carries", "attempts", "sacks_suffered", "passing_epa",
                         "receiving_epa", "rushing_epa"]:
        if c in p:
            p[c] = p[c].fillna(0)
    p["defplays"] = p[DEF_COLS].sum(axis=1)
    p["dropbacks"] = p["attempts"] + p["sacks_suffered"]
    agg = p.groupby(["player_id", "team"]).agg(
        name=("player_name", "last"), full=("player_display_name", "last"), pos=("position", "last"),
        games=("week", "nunique"), targets=("targets", "sum"), carries=("carries", "sum"),
        attempts=("attempts", "sum"), dropbacks=("dropbacks", "sum"), defplays=("defplays", "sum"),
        passing_epa=("passing_epa", "sum"), receiving_epa=("receiving_epa", "sum"),
        rushing_epa=("rushing_epa", "sum")).reset_index()
    team_t = p.groupby("team").agg(targets=("targets", "sum"), carries=("carries", "sum"),
                                   defplays=("defplays", "sum"))
    snap = {}
    if snaps is not None and len(snaps):
        s = snaps[(snaps.week < before_week)].copy()
        s["team"] = s["team"].map(C.espn_abbr)
        for (team, player), g in s.groupby(["team", "player"]):
            pos = str(g.position.iloc[-1])
            col = "defense_pct" if C.POS_GROUP.get(pos, pos) in ("DL", "LB", "CB", "S") else "offense_pct"
            vals = g[col][g[col] > 0]
            snap[(team, norm_name(player))] = {
                "pct": round(float(vals.mean()), 3) if len(vals) else None,
                "games50": int((g[col] >= 0.5).sum())}
    out = {}
    for r in agg.itertuples():
        grp = C.POS_GROUP.get(str(r.pos), str(r.pos))
        tt = team_t.loc[r.team] if r.team in team_t.index else None
        rel, plays, epa, label = None, 0, None, ""
        if grp in ("WR", "TE"):
            rel = _div(r.targets, tt.targets) if tt is not None else None
            plays, epa, label = int(r.targets), _div(r.receiving_epa, r.targets), "target share"
        elif grp == "RB":
            rs = _div(r.carries, tt.carries) or 0
            ts = _div(r.targets, tt.targets) or 0
            rel = max(rs, ts)
            plays = int(r.carries + r.targets)
            epa = _div(r.rushing_epa + r.receiving_epa, r.carries + r.targets)
            label = "rush share" if rs >= ts else "target share"
        elif grp == "QB":
            rel, plays, epa, label = 1.0, int(r.dropbacks), _div(r.passing_epa, r.dropbacks), "QB"
        elif grp in ("DL", "LB", "CB", "S"):
            rel = _div(r.defplays, tt.defplays) if tt is not None else None
            plays, label = int(r.defplays), "def-play share"
        sn = snap.get((r.team, norm_name(r.full)), {})
        early = int(r.games) < 2
        out[f"{r.team}|{r.name}"] = {
            "id": r.player_id, "name": r.name, "full": r.full, "pos": grp, "games": int(r.games),
            "reliance": None if early else rel, "relianceLabel": label, "plays": plays,
            "epaPerPlay": epa, "targets": int(r.targets), "carries": int(r.carries),
            "attempts": int(r.attempts), "snapPct": sn.get("pct"), "games50": sn.get("games50", 0),
            "early": early,
            "rawEpa": float(r.passing_epa if grp == "QB" else r.receiving_epa if grp in ("WR", "TE")
                            else r.rushing_epa + r.receiving_epa if grp == "RB" else 0),
        }
    add_grades(out, agg)
    # league top-10 by cumulative EPA before the week (QB min 20 att; WR rec EPA; RB rush+rec EPA)
    top = {}
    for grp, cond in (("QB", lambda v: v["attempts"] >= 20), ("WR", lambda v: True), ("RB", lambda v: True)):
        cands = [(k, v) for k, v in out.items() if v["pos"] == grp and not v["early"] and cond(v)]
        cands.sort(key=lambda kv: kv[1]["rawEpa"], reverse=True)
        for i, (k, v) in enumerate(cands[:10]):
            out[k]["top10"] = i + 1
            top.setdefault(grp, []).append({"key": k, "rank": i + 1, "epa": round(v["rawEpa"], 1)})
    return out, top


GRADE_PRIOR = {"QB": 150, "WR": 40, "TE": 40, "RB": 60}
GRADE_MIN = {"QB": 60, "WR": 15, "TE": 10, "RB": 25, "DL": 3, "LB": 3, "CB": 3, "S": 3}


def add_grades(out, agg):
    """Our own 0-100 player grades from free nflverse data (percentile among same-position peers).
    Offense: shrunk EPA per play (small samples pulled to the position average).
    Defense: tackles + impact plays per game (sacks, QB hits, TFL, passes defended, INTs) - playmaking
    only; coverage and blocking aren't in free data, so OL gets no grade and DBs are partial."""
    from collections import defaultdict
    pools = defaultdict(list)
    for k, v in out.items():
        g = v["pos"]
        if g in GRADE_PRIOR and v["plays"] >= GRADE_MIN[g] and v["epaPerPlay"] is not None:
            pools[g].append((k, v["epaPerPlay"], v["plays"]))
        elif g in ("DL", "LB", "CB", "S") and v["games"] >= 3:
            pools[g].append((k, v["plays"] / max(v["games"], 1), v["games"]))
    for g, rows in pools.items():
        if len(rows) < 8:
            continue
        if g in GRADE_PRIOR:
            mu = sum(e * n for _, e, n in rows) / sum(n for _, _, n in rows)
            vals = [(k, (e * n + mu * GRADE_PRIOR[g]) / (n + GRADE_PRIOR[g])) for k, e, n in rows]
        else:
            vals = [(k, x) for k, x, _ in rows]
        vals.sort(key=lambda kv: kv[1])
        for i, (k, _) in enumerate(vals):
            out[k]["grade"] = round(100 * (i + 0.5) / len(vals))
            out[k]["gradeOf"] = len(vals)
            out[k]["gradeBasis"] = "EPA/play" if g in GRADE_PRIOR else "impact plays/game"


def key_players(p, before_week):
    """By-player matchup context per team (real nflverse numbers, rank among league peers)."""
    if p is None or len(p) == 0:
        return {}
    p = p[(p.season_type == "REG") & (p.week < before_week)].copy()
    p["team"] = p["team"].map(C.espn_abbr)
    for c in DEF_COLS + ["targets", "carries", "attempts", "sacks_suffered", "passing_epa", "receiving_epa",
                         "rushing_epa", "receiving_yards", "rushing_yards", "passing_yards"]:
        if c in p:
            p[c] = p[c].fillna(0)
    a = p.groupby(["team", "player_name"]).agg(
        pos=("position", "last"), g=("week", "nunique"), att=("attempts", "sum"), sk=("sacks_suffered", "sum"),
        pepa=("passing_epa", "sum"), pyd=("passing_yards", "sum"), tg=("targets", "sum"), repa=("receiving_epa", "sum"),
        ryd=("receiving_yards", "sum"), car=("carries", "sum"), ruepa=("rushing_epa", "sum"), ruyd=("rushing_yards", "sum"),
        sacks=("def_sacks", "sum"), hits=("def_qb_hits", "sum"), pd=("def_pass_defended", "sum"),
        ints=("def_interceptions", "sum"), tfl=("def_tackles_for_loss", "sum")).reset_index()
    a["grp"] = a["pos"].map(lambda x: C.POS_GROUP.get(str(x), str(x)))
    qb = a[(a.grp == "QB") & (a.att >= 100)].copy()
    qb["v"] = qb.pepa / (qb.att + qb.sk)
    rc = a[a.grp.isin(["WR", "TE"]) & (a.tg >= 20)].copy()
    rc["v"] = rc.repa / rc.tg
    rb = a[(a.grp == "RB") & (a.car >= 40)].copy()
    rb["v"] = rb.ruepa / rb.car
    pr = a[a.grp.isin(["DL", "LB"])].copy()
    pr["v"] = pr.sacks + 0.5 * pr.hits
    cv = a[a.grp.isin(["CB", "S"])].copy()
    cv["v"] = cv.pd + 2 * cv.ints
    for df in (qb, rc, rb, pr, cv):
        df["rank"] = df["v"].rank(ascending=False, method="min").astype(int)
    out = {}
    def put(team, key, row, txt):
        out.setdefault(team, {})[key] = {"name": row.player_name, "rank": int(row["rank"]), "of": None, "txt": txt}
    for team in a.team.unique():
        t = qb[qb.team == team].sort_values("att", ascending=False)
        if len(t):
            r = t.iloc[0]; put(team, "QB", r, f"{r.v:+.2f} EPA/db · {r.pyd / max(1, r.g):.0f} yds/g"); out[team]["QB"]["of"] = len(qb)
        t = rc[rc.team == team].sort_values("tg", ascending=False)
        if len(t):
            r = t.iloc[0]; put(team, "WR1", r, f"{int(r.tg)} tgt · {r.v:+.2f} EPA/tgt · {r.ryd / max(1, r.g):.0f} yds/g"); out[team]["WR1"]["of"] = len(rc)
        t = rb[rb.team == team].sort_values("car", ascending=False)
        if len(t):
            r = t.iloc[0]; put(team, "RB1", r, f"{int(r.car)} car · {r.v:+.2f} EPA/car · {r.ruyd / max(1, r.g):.0f} yds/g"); out[team]["RB1"]["of"] = len(rb)
        t = pr[pr.team == team].sort_values("v", ascending=False)
        if len(t):
            r = t.iloc[0]; put(team, "Rush", r, f"{r.sacks:.1f} sacks · {int(r.hits)} QB hits"); out[team]["Rush"]["of"] = len(pr)
        t = cv[cv.team == team].sort_values("v", ascending=False)
        if len(t):
            r = t.iloc[0]; put(team, "Cover", r, f"{int(r.pd)} PD · {int(r.ints)} INT"); out[team]["Cover"]["of"] = len(cv)
    return out


def backup_map(depth, prior, kickoff_iso=None):
    """Starter (pos_rank 1) -> backup (next pos_rank, same team/group/slot) from the depth
    snapshot closest BEFORE kickoff. Gate info only (proven / unproven)."""
    if depth is None or len(depth) == 0:
        return {}
    d = depth
    if kickoff_iso:
        dd = d[d.dt < kickoff_iso]
        d = dd if len(dd) else d
    latest = d.groupby("team")["dt"].transform("max")
    d = d[d.dt == latest].copy()
    d["team"] = d["team"].map(C.espn_abbr)
    by_id = {v["id"]: k for k, v in prior.items()}
    out = {}
    for (team, grp_id, slot), g in d.groupby(["team", "pos_grp", "pos_slot"]):
        g = g.sort_values("pos_rank")
        if len(g) == 0 or int(g.pos_rank.iloc[0]) != 1:
            continue
        st = g.iloc[0]
        grp = C.POS_GROUP.get(str(st.pos_abb), str(st.pos_abb))
        skey = by_id.get(st.gsis_id) or f"{team}|{abbrev(st.player_name)}"
        sab = skey.split("|", 1)[1]
        if f"{team}|{sab}" in out:
            continue
        entry = {"starter": st.player_name, "pos": grp, "slot": str(st.pos_abb), "asOf": str(st["dt"])}
        if len(g) > 1:
            b = g.iloc[1]
            bkey = by_id.get(b.gsis_id) or f"{team}|{abbrev(b.player_name)}"
            bp = prior.get(bkey, {})
            sp = prior.get(skey, {})
            entry["backup"] = {"name": b.player_name, "key": bkey, "plays": bp.get("plays", 0),
                               "epaPerPlay": bp.get("epaPerPlay"), "snapPct": bp.get("snapPct"),
                               "games50": bp.get("games50", 0), "attempts": bp.get("attempts", 0)}
            entry["gate"] = backup_gate(grp, sp, bp)
        else:
            entry["backup"] = None
            entry["gate"] = {"proven": False, "halve": False, "note": "no backup on chart — full impact"}
        out[f"{team}|{sab}"] = entry
    return out


def backup_gate(grp, sp, bp):
    """Proven backup halves the impact; unproven = full impact. Never invent a number."""
    plays = bp.get("plays", 0) or 0
    se, be = sp.get("epaPerPlay"), bp.get("epaPerPlay")
    gap = None if se is None or be is None else round(se - be, 3)
    if grp == "QB":
        proven = (bp.get("attempts", 0) or 0) >= 50 and gap is not None and gap <= 0.10
        return {"proven": proven, "halve": proven, "gap": gap,
                "note": "proven backup QB" if proven else "unproven backup QB"}
    if grp in ("DL", "LB", "CB", "S"):
        proven = plays >= 20 and (bp.get("games50", 0) or 0) >= 3
        return {"proven": proven, "halve": proven, "gap": None,
                "note": "proven backup" if proven else "unproven backup"}
    if plays < 5:
        return {"proven": False, "halve": False, "gap": gap, "note": "unproven backup (<5 plays)"}
    if gap is None:
        return {"proven": False, "halve": False, "gap": None, "note": "backup EPA unmeasured"}
    if plays >= 20 and gap <= 0.10:
        return {"proven": True, "halve": True, "gap": gap, "note": "proven backup"}
    if 5 <= plays < 20 and gap <= 0.05:
        return {"proven": False, "halve": True, "gap": gap, "note": "thin backup, close EPA"}
    return {"proven": False, "halve": False, "gap": gap, "note": "backup gap too big"}


def build_tables(season, week, kickoff_iso=None, rebuild_backup_only=False):
    old = load_json(TABLES, {}) or {}
    p, t, s, d, r = load_frames(season)
    if rebuild_backup_only and old.get("player_prior"):
        prior = old["player_prior"]
        top = old.get("top10", {})
        teams = old.get("teams", {})
    else:
        teams = team_tables(t, week)
        prior, top = player_prior(p, s, week)
    bmap = backup_map(d, prior, kickoff_iso)
    roster = {}
    if r is not None and len(r):
        rr = r.copy()
        rr["team"] = rr["team"].map(C.espn_abbr)
        for x in rr.itertuples():
            pos = C.POS_GROUP.get(str(x.depth_chart_position), C.POS_GROUP.get(str(x.position), str(x.position)))
            roster[f"{x.team}|{abbrev(x.full_name)}"] = {"pos": pos, "full": x.full_name, "espn": str(x.espn_id).split(".")[0]}
    try:
        kp = key_players(p, week) if p is not None else old.get("keyPlayers", {})
    except Exception:
        kp = old.get("keyPlayers", {})
    tables = {"season": season, "week": week, "builtAt": iso(), "teams": teams, "player_prior": prior, "keyPlayers": kp,
              "top10": top, "backup_map": bmap, "roster": roster,
              "ok": bool(teams) and bool(prior)}
    if not tables["ok"] and old.get("ok"):
        old["staleNote"] = "nflverse refresh failed — using last good tables"
        return old
    save_json(TABLES, tables, compact=True)
    return tables


def load_tables():
    t = load_json(TABLES, {}) or {}
    t["_injHist"] = load_json(os.path.join(C.STATE, "injury_history.json"), {}) or {}
    return t
