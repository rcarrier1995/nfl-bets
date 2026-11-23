"""Builds the board: every game, both teams, pregame calls, live calls, combos, Top 3."""
import math
import os
from datetime import datetime, timedelta, timezone

from . import config as C
from zoneinfo import ZoneInfo
CT_TZ = ZoneInfo("America/Chicago")
from . import combos as CB
from . import injuries as I
from . import model as M
from . import signals as SG
from . import profiles as PF
from .fetch import (espn_scoreboard, espn_summary, kalshi_events, kalshi_day_range, weather_batch, load_json,
                    save_json, iso, now_utc, HEALTH)
from .stats import abbrev, load_tables

LIVE_FILE = os.path.join(C.STATE, "live.json")
SNAP_FILE = os.path.join(C.STATE, "snapshots.json")      # pregame snapshots + Thursday baseline
PREV_BOARD = os.path.join(C.DOCS_DATA, "board.json")
FIXED_DOMES = {"ATL", "DET", "LV", "LAC", "LAR", "MIN", "NO"}


def parse_dt(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    if len(s) == 22 and s[-6] == "+" and s.count(":") == 2:   # 2026-11-22T21:25+00:00
        s = s[:16] + ":00" + s[16:]
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


# ---------------- Kalshi ----------------
def kalshi_index(events):
    """frozenset(teams) -> list of {occ, prices{team: {...}}}. Price = yes ask (buy price)."""
    idx = {}
    for ev in events or []:
        prices = {}
        occ = None
        for m in ev.get("markets", []):
            code = m.get("ticker", "").rsplit("-", 1)[-1]
            team = C.KALSHI_TO_ESPN.get(code, code)
            ask = _cents(m.get("yes_ask_dollars"))
            bid = _cents(m.get("yes_bid_dollars"))
            last = _cents(m.get("last_price_dollars"))
            step = 1.0
            try:
                step = float(m.get("price_ranges", [{}])[0].get("step", "0.01")) * 100
            except Exception:
                pass
            prices[team] = {"ask": ask if ask and ask > 0 else None, "bid": bid, "last": last, "ticker": m.get("ticker"),
                            "tick": step, "status": m.get("status"), "result": m.get("result")}
            occ = occ or parse_dt(m.get("occurrence_datetime") or m.get("expected_expiration_time"))
        if len(prices) == 2:
            idx.setdefault(frozenset(prices), []).append({"occ": occ, "prices": prices})
    return idx


def _cents(v):
    try:
        return round(float(v) * 100, 2)
    except Exception:
        return None


def match_kalshi(idx, a, h, kickoff):
    cands = idx.get(frozenset((a, h))) or []
    if not cands:
        return None
    if kickoff:
        cands = sorted(cands, key=lambda c: abs((c["occ"] - kickoff).total_seconds()) if c["occ"] else 9e9)
        if cands[0]["occ"] and abs((cands[0]["occ"] - kickoff).total_seconds()) > 4 * 86400:
            return None
    return cands[0]["prices"]


# ---------------- Weather ----------------
def game_point(home, venue):
    city = ((venue or {}).get("address") or {}).get("city", "")
    name = (venue or {}).get("fullName", "")
    for k, v in C.VENUE_OVERRIDES.items():
        if k in city or k in name:
            return v
    return C.STADIUMS.get(home)


def weather_window(wx, kickoff):
    """Hourly kickoff-1h to +5h: temp, sustained wind, gusts, precip."""
    if not wx or not kickoff or "hourly" not in wx:
        return None
    h = wx["hourly"]
    rows = []
    for i, t in enumerate(h.get("time", [])):
        dt = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        if kickoff - timedelta(hours=1) <= dt <= kickoff + timedelta(hours=5):
            rows.append({"t": t[11:16], "rel": round((dt - kickoff).total_seconds() / 3600), "temp": _v(h, "temperature_2m", i),
                         "wind": _v(h, "wind_speed_10m", i), "gust": _v(h, "wind_gusts_10m", i),
                         "precip": _v(h, "precipitation", i), "code": _v(h, "weather_code", i)})
    if not rows:
        return None
    vals = lambda k: [r[k] for r in rows if r[k] is not None]  # noqa
    return {"hours": rows, "tempMin": min(vals("temp"), default=None), "tempMax": max(vals("temp"), default=None),
            "windMax": max(vals("wind"), default=None), "gustMax": max(vals("gust"), default=None),
            "precip": round(sum(vals("precip")), 2) if vals("precip") else None}


def _v(h, k, i):
    try:
        v = h[k][i]
        return None if v is None else round(float(v), 1)
    except Exception:
        return None


def wx_line(w, indoor):
    if indoor:
        return "Indoors"
    if not w:
        return None
    bits = []
    if w.get("tempMin") is not None:
        bits.append(f"{w['tempMin']:.0f}°F")
    if w.get("windMax") is not None:
        bits.append(f"wind {w['windMax']:.0f}")
    if w.get("gustMax") is not None:
        bits.append(f"gusts {w['gustMax']:.0f} mph")
    if w.get("precip"):
        bits.append(f"rain {w['precip']:.2f}\"")
    return " · ".join(bits)


# ---------------- Injuries (current only) ----------------
def current_injuries(summary, team, tables):
    out = []
    for blk in (summary or {}).get("injuries") or []:
        if C.espn_abbr((blk.get("team") or {}).get("abbreviation")) != team:
            continue
        for inj in blk.get("injuries", []):
            status = inj.get("status") or ""
            if status not in ("Out", "Doubtful", "Questionable", "Injured Reserve"):
                continue
            if status == "Injured Reserve":
                continue   # long-term, already priced; not a "current bet" injury
            a = inj.get("athlete") or {}
            full = a.get("displayName") or a.get("fullName") or ""
            ab = abbrev(full)
            pos_raw = ((a.get("position") or {}).get("abbreviation") or "")
            pos = C.POS_GROUP.get(pos_raw, pos_raw)
            key = f"{team}|{ab}"
            starter = key in (tables.get("backup_map") or {})
            prior = (tables.get("player_prior") or {}).get(key, {})
            out.append({"team": team, "player": full, "short": ab, "pos": pos, "status": status,
                        "starter": starter, "detail": ((inj.get("details") or {}).get("type") or ""),
                        "top10": prior.get("top10"), "grade": prior.get("grade")})
    return out


# ---------------- Team-level matchup bars ----------------
def matchup(team, tables):
    t = (tables.get("teams") or {}).get(team)
    if not t:
        return None   # UI shows "Rankings unavailable"
    return {k: t.get(k) for k in ("passOff", "runOff", "passDef", "runDef")} | {"runShare": t.get("runShare"),
            "players": (tables.get("keyPlayers") or {}).get(team)}


# ---------------- Build ----------------
def build(now=None, extra_shrink=1.0, calib=None, sb_override=None):
    now = now or now_utc()
    tables = load_tables()
    teams_tbl = tables.get("teams") or {}
    sb, sb_stale = (sb_override, False) if sb_override else espn_scoreboard()
    if not sb:
        return None
    kev, k_stale = kalshi_events()
    kidx = kalshi_index(kev)
    live_state = load_json(LIVE_FILE, {}) or {}
    snaps = load_json(SNAP_FILE, {}) or {}
    prev = load_json(PREV_BOARD, {}) or {}
    prev_calls = {c["key"]: c for c in prev.get("calls", [])}

    events = sb.get("events", [])
    season = (sb.get("season") or {}).get("year")
    week = (sb.get("week") or {}).get("number")

    # weather for open-air games not yet final (one batched call)
    pts, pt_idx = [], {}
    for ev in events:
        comp = ev["competitions"][0]
        home = _side(comp, "home")
        st = ev["status"]["type"]["state"]
        if st == "post" or _indoor(comp, home):
            continue
        p = game_point(home, comp.get("venue"))
        if p:
            pt_idx[ev["id"]] = len(pts)
            pts.append(p)
    wx_all, wx_stale = weather_batch(pts) if pts else ([], False)

    from .odds import refresh as odds_refresh
    cons = odds_refresh([parse_dt(ev.get("date")) for ev in events if ev["status"]["type"]["state"] == "pre"], now)
    games, calls, legs_pool, alerts = [], [], [], []
    for ev in events:
        g = build_game(ev, tables, kidx, wx_all, pt_idx, live_state, snaps, prev_calls, now, extra_shrink, calib, cons)
        games.append(g)
        for side in ("away", "home"):
            c = g["teams"][side]
            calls.append(c)
        alerts += g.get("alerts", [])

    # never act on an old price: if the price feed failed and the last good copy is > 12 min old,
    # live calls drop to Pass, dip alerts are dropped, and run.py sends no price pushes.
    if k_stale:
        kat = (load_json(os.path.join(C.CACHE, "kalshi_events.json"), {}) or {}).get("at")
        age = (now - parse_dt(kat)).total_seconds() / 60 if kat else 999
        if age > 12:
            alerts = []
            for c in calls:
                c["priceStale"] = round(age)
                c["sell"] = None
                if c.get("state") == "in" and c.get("liveCall") in ("Value", "Wait"):
                    c["liveCall"] = "Pass"
                    c.setdefault("liveLines", []).insert(0, {"text": f"⏸ Price feed delayed {age:.0f} min — no live calls until it's back", "kind": "pause"})
    games.sort(key=lambda g: (g["kickoff"] or ""))
    # Combos: live + scheduled (never final), both sides, all calls incl. Pass
    pool = []
    for g in games:
        if g["state"] == "post":
            continue
        a, h = g["teams"]["away"], g["teams"]["home"]
        fa, fh = _combo_fair(a), _combo_fair(h)
        if None in (fa, fh) or not a.get("price") or not h.get("price"):
            continue
        pool.append((_leg(g, a, fa), _leg(g, h, fh)))
    std = CB.search(pool)
    combined_legs = [l for pair in pool for l in pair
                     if (l.get("fair") or 0) >= C.SHOE_IN or l.get("lopsided") or l.get("tdDip")]
    comb = CB.search_legs(combined_legs)

    from .lag import record_and_detect
    from .timing import best_time
    record_and_detect({"games": games}, now)
    for c in calls:
        c["bestTime"] = best_time(c)
    top3 = top_three([c for c in calls if c.get("state") == "pre"])
    save_json(LIVE_FILE, live_state, compact=True)
    save_json(SNAP_FILE, snaps, compact=True)
    feeds_stale = {"espn": sb_stale, "kalshi": k_stale, "weather": wx_stale}
    HEALTH.save()
    return {
        "generatedAt": iso(now), "season": season, "week": week,
        "games": games, "calls": calls, "top3": top3,
        "combos": {"standard": std, "combined": comb, "pool": [l for pair in pool for l in pair],
                   "poolGames": len(pool)},
        "alerts": alerts, "feedsStale": feeds_stale, "tablesBuiltAt": tables.get("builtAt"),
    }


def _combo_fair(c):
    return c.get("liveFair") if c.get("state") == "in" else c.get("fair")


def _leg(g, c, fair):
    leg = {"gameId": g["id"], "team": c["team"], "opp": c["opp"], "fair": fair, "price": c["price"],
           "call": c.get("liveCall") if c.get("state") == "in" else c.get("call"),
           "label": g["short"], "state": g["state"], "lopsided": abs(g.get("spreadPts") or 0) >= C.LOPSIDED_SPREAD
           and (c.get("spreadMargin") or 0) > 0, "tdDip": bool(c.get("justScoredTD"))}
    leg["tags"] = CB.leg_label(leg)
    return leg


def _side(comp, ha):
    for t in comp["competitors"]:
        if t["homeAway"] == ha:
            return C.espn_abbr(t["team"]["abbreviation"])
    return None


def _indoor(comp, home):
    v = comp.get("venue") or {}
    if v.get("indoor"):
        return True
    return home in FIXED_DOMES and not comp.get("neutralSite")


def build_game(ev, tables, kidx, wx_all, pt_idx, live_state, snaps, prev_calls, now, extra_shrink, calib, cons=None):
    comp = ev["competitions"][0]
    st = ev["status"]
    state = st["type"]["state"]           # pre / in / post
    kickoff = parse_dt(ev.get("date"))
    away, home = _side(comp, "away"), _side(comp, "home")
    comps = {t["homeAway"]: t for t in comp["competitors"]}
    indoor = _indoor(comp, home)
    neutral = bool(comp.get("neutralSite"))
    gid = ev["id"]
    gkey = f"{season_key(ev)}|{gid}"
    summary = None
    need_summary = state == "in" or (state == "pre" and kickoff and kickoff - now < timedelta(days=8)) or \
        (state == "post" and gid in live_state and not live_state[gid].get("summaryFinal"))
    if need_summary:
        summary, _ = espn_summary(gid)
    # odds: scoreboard first, else summary pickcenter
    odds = (comp.get("odds") or [None])[0] or ((summary or {}).get("pickcenter") or [None])[0]
    spread_home = None
    total = None
    book = None
    if odds and odds.get("spread") is not None:
        try:
            spread_home = float(odds["spread"])
            total = odds.get("overUnder")
            book = (odds.get("provider") or {}).get("name")
        except Exception:
            spread_home = None
    espn_spread = spread_home
    cs = (cons or {}).get(f"{away}@{home}") if state == "pre" else None
    if cs:   # sharper: many-book consensus moneyline, as an equivalent spread
        from .odds import spread_from_p
        spread_home = spread_from_p(cs["pHome"])
        book = f"Consensus of {cs['books']} books" + (" incl. Pinnacle" if cs.get("pinnacle") else "")
    snap = snaps.get(gkey, {})
    if spread_home is None and snap.get("spreadHome") is not None:
        spread_home, total, book = snap["spreadHome"], snap.get("total"), snap.get("book")
    wx = None
    if not indoor and gid in pt_idx and pt_idx[gid] < len(wx_all or []):
        wx = weather_window(wx_all[pt_idx[gid]], kickoff)
    if wx is None and snap.get("wx"):
        wx = snap["wx"]
    prices = match_kalshi(kidx, away, home, kickoff) or {}
    inj = {away: current_injuries(summary, away, tables), home: current_injuries(summary, home, tables)}
    if summary is None and snap.get("inj"):
        inj = snap["inj"]

    g = {"id": gid, "key": gkey, "away": away, "home": home, "short": f"{away} @ {home}",
         "kickoff": ev.get("date"), "state": state, "detail": st["type"].get("shortDetail"),
         "period": st.get("period"), "clock": st.get("displayClock"),
         "score": {"away": _int(comps["away"].get("score")), "home": _int(comps["home"].get("score"))},
         "linescores": {s: [_int(x.get("displayValue")) for x in (comps[s].get("linescores") or [])] for s in ("away", "home")},
         "venue": (comp.get("venue") or {}).get("fullName"), "indoor": indoor, "neutral": neutral,
         "situation": SG.tags(g_season(ev), away, home) + SG.venue_tags(away, home, indoor, neutral, wx),
         "logos": {away: comps["away"]["team"].get("logo"), home: comps["home"]["team"].get("logo")},
         "colors": {away: "#" + (comps["away"]["team"].get("color") or "334155"),
                    home: "#" + (comps["home"]["team"].get("color") or "334155")},
         "spreadHome": spread_home, "total": total, "book": book, "espnSpread": espn_spread,
         "spreadPts": None if spread_home is None else abs(spread_home),
         "weather": wx, "weatherLine": wx_line(wx, indoor),
         "injuries": inj[away] + inj[home],
         "keyInjuries": len([i for i in inj[away] + inj[home] if i["starter"] and i["status"] in ("Out", "Doubtful")]),
         "matchup": {away: matchup(away, tables), home: matchup(home, tables)},
         "matchupLines": PF.matchup_lines(away, home),
         "grades": {away: PF.scores(away), home: PF.scores(home)}}
    # line move since we first saw the game, and how far the books disagree (context only)
    first = snap.get("open") if snap.get("open") is not None else espn_spread
    g["openSpread"] = first
    if first is not None and espn_spread is not None and abs(espn_spread - first) >= 0.5:
        fav = home if espn_spread - first < 0 else away
        g["lineMoveLine"] = f"Line moved {abs(espn_spread - first):.1f} pts toward {fav} since it opened here ({first:+.1f} → {espn_spread:+.1f} {home})"
    if cs and cs.get("pMin") is not None and cs.get("books", 0) >= 3:
        lo, hi = round(cs["pMin"] * 100), round(cs["pMax"] * 100)
        g["bookRangeLine"] = (f"Books agree: {home} {lo}–{hi}%" if hi - lo <= 3 else
                              f"Books disagree: {home} {lo}–{hi}% across {cs['books']} books")
    if neutral and spread_home is not None:
        pass  # spread already neutral-site; HFA dropped in EPA margin

    # ----- pregame calls (frozen at kickoff from the snapshot) -----
    teams = {}
    pre_fair = {}
    margin_home = None if spread_home is None else -spread_home
    for side, team, opp, is_home in (("away", away, home, False), ("home", home, away, True)):
        teams[side] = {"team": team, "opp": opp, "side": side, "gameId": gid, "key": f"{gkey}|{team}",
                       "name": C.TEAM_NAMES.get(team, team), "state": state}
    if margin_home is not None:
        adj_h, adj_detail = M.epa_adjustment(home, away, True, neutral, margin_home, tables.get("teams", {}))
        w_h, w_why_h = M.weather_pts(home, away, wx, tables.get("teams", {}), indoor)
        w_a, w_why_a = M.weather_pts(away, home, wx, tables.get("teams", {}), indoor)
        th = snap.get("thursday") or {}
        b_inj = th.get("inj") if th else None
        move = None
        if th and th.get("spreadHome") is not None and (espn_spread if espn_spread is not None else spread_home) is not None:
            move = (espn_spread if espn_spread is not None else spread_home) - th["spreadHome"]
        i_h, n_h = M.injury_pts(inj[home], b_inj, move)
        i_a, n_a = M.injury_pts(inj[away], b_inj, move)
        g_h, g_why = PF.adjust_pts(away, home)    # only grades that beat the line in the weekly study
        pts_home = margin_home + adj_h + (w_h - w_a) + (i_h - i_a) + g_h
        f_h, f_a, shrink = M.fair_pair(pts_home, extra_shrink)
        pre_fair = {home: f_h, away: f_a}
        parts = {home: {"spread": margin_home, "epa": adj_h, "epaDetail": adj_detail, "weather": w_h - w_a,
                        "weatherWhy": w_why_h or w_why_a, "inj": i_h - i_a, "injNotes": n_h, "oppInjNotes": n_a,
                        "grades": g_h, "gradesWhy": g_why, "pts": round(pts_home, 2), "shrink": shrink},
                 away: {"spread": -margin_home, "epa": -adj_h, "epaDetail": adj_detail, "weather": w_a - w_h,
                        "weatherWhy": w_why_a or w_why_h, "inj": i_a - i_h, "injNotes": n_a, "oppInjNotes": n_h,
                        "grades": -g_h, "gradesWhy": g_why, "pts": round(-pts_home, 2), "shrink": shrink}}
    else:
        parts = {}
    for side in ("away", "home"):
        c = teams[side]
        team = c["team"]
        pr = prices.get(team) or {}
        price = pr.get("ask")
        c["price"] = price
        c["bid"] = pr.get("bid")
        c["sell"] = None
        c["tick"] = pr.get("tick", 1.0)
        c["fair"] = pre_fair.get(team)
        p = parts.get(team, {})
        c["spreadMargin"] = p.get("spread")
        c["parts"] = {k: v for k, v in p.items() if k not in ("injNotes", "oppInjNotes")}
        c["injNotes"], c["oppInjNotes"] = p.get("injNotes", []), p.get("oppInjNotes", [])
        c["weatherWhy"] = None
        if p.get("weather"):
            c["weatherWhy"] = p["weatherWhy"] if p["weather"] > 0 else f"{p['weatherWhy']} favors {c['opp']} run game"
        if state == "pre":
            cl = M.classify(c["fair"], price)
            c.update(cl)
            if cl["call"] == "Pass":
                c["sell"] = M.sell_check(c["fair"], c["bid"])
        else:
            # pregame call is frozen at kickoff: use the last pregame snapshot
            s = (snap.get("teams") or {}).get(team, {})
            for k in ("fair", "call", "edge", "buyAt", "fee", "confidence", "why"):
                if k in s:
                    c[k] = s[k]
            c.setdefault("call", "Pass")
            c.setdefault("fee", M.fee_cents(price))
            c["pregamePrice"] = s.get("price")
        completeness = sum([price is not None, c["fair"] is not None, bool(teams_ok(tables, team)),
                            summary is not None or bool(snap.get("inj")), indoor or wx is not None]) / 5.0
        if "confidence" not in c or state == "pre":
            c["confidence"] = M.confidence(c["fair"], c.get("edge"), completeness, calib)
        if "why" not in c or state == "pre":
            c["why"] = M.why_line(c)
        c["profit"] = None if price is None else round(100 - price, 2)
        c["reasons"] = reasons(c, g, tables)
        # price move vs last board
        pc = prev_calls.get(c["key"], {})
        c["prevPrice"] = pc.get("price") if pc.get("price") != price else pc.get("prevPrice")
        c["priceAt"] = iso(now)
        c["priceChangedAt"] = iso(now) if pc.get("price") != price else pc.get("priceChangedAt", iso(now))
        # today's low / high price (Central day), from our own checks
        day = now.astimezone(CT_TZ).strftime("%Y-%m-%d")
        c["dayDate"], c["dayLo"], c["dayHi"] = day, price, price
        if pc.get("dayDate") == day:
            vals = [v for v in (pc.get("dayLo"), pc.get("dayHi"), price) if v is not None]
            if vals:
                c["dayLo"], c["dayHi"] = min(vals), max(vals)
        # on game day (and during the game) use Kalshi's own traded low / high since midnight CT
        kick = parse_dt(ev.get("date"))
        if pr.get("ticker") and kick and state != "post" and (state == "in" or kick.astimezone(CT_TZ).strftime("%Y-%m-%d") == day):
            mid = kick.astimezone(CT_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            rg = kalshi_day_range(pr["ticker"], mid.timestamp(), now.timestamp())
            if rg:
                vals = [v for v in (c["dayLo"], c["dayHi"], rg[0], rg[1]) if v is not None]
                c["dayLo"], c["dayHi"] = min(vals), max(vals)
    g["teams"] = teams

    # snapshot every pregame fair/price/call before kickoff
    if state == "pre":
        snaps[gkey] = {"spreadHome": spread_home, "total": total, "book": book, "wx": wx, "inj": inj,
                       "kickoff": ev.get("date"), "away": away, "home": home, "week": g_week(ev),
                       "season": g_season(ev), "at": iso(now),
                       "teams": {teams[s]["team"]: {k: teams[s].get(k) for k in
                                 ("fair", "price", "call", "edge", "buyAt", "fee", "confidence", "why")}
                                 for s in ("away", "home")},
                       "thursday": snap.get("thursday"),
                       "open": snap.get("open") if snap.get("open") is not None else espn_spread}
    # live
    if state in ("in", "post") and summary is not None or state == "in":
        from .live import live_update
        live_update(g, summary, ev, tables, live_state, snaps.get(gkey, {}), now)
    elif gid in live_state:
        g["quarters"] = live_state[gid].get("quarters", [])
        g["injLive"] = live_state[gid].get("injLive", [])
    if state == "post":
        g["result"] = result(g, snaps.get(gkey, {}))
        if gid in live_state and summary is not None:
            live_state[gid]["summaryFinal"] = True
    g["changes"] = changes_since_thursday(g, snaps.get(gkey, {}))
    return g


def teams_ok(tables, team):
    return (tables.get("teams") or {}).get(team)


def season_key(ev):
    return f"{g_season(ev)}-w{g_week(ev)}"


def g_season(ev):
    return (ev.get("season") or {}).get("year")


def g_week(ev):
    return (ev.get("week") or {}).get("number")


def _int(x):
    try:
        return int(float(x))
    except Exception:
        return None


def reasons(c, g, tables):
    """Short labels only, for the Full breakdown."""
    r = []
    p = c.get("parts") or {}
    if p.get("spread") is not None:
        r.append(f"Line {c['team']} {p['spread']:+.1f}")
    if p.get("epa"):
        r.append(f"EPA adj {p['epa']:+.1f} pts")
    if p.get("weather"):
        r.append(f"Weather {p['weather']:+.1f} pts")
    if p.get("inj"):
        r.append(f"Injuries {p['inj']:+.1f} pts")
    mu, mo = (g.get("matchup") or {}).get(c["team"]), (g.get("matchup") or {}).get(c["opp"])
    if mu and mo:
        try:
            if mu["passOff"]["rank"] and mo["passDef"]["rank"]:
                r.append(f"Pass off #{mu['passOff']['rank']} vs def #{mo['passDef']['rank']}")
            if mu["runOff"]["rank"] and mo["runDef"]["rank"]:
                r.append(f"Run off #{mu['runOff']['rank']} vs def #{mo['runDef']['rank']}")
        except Exception:
            pass
    return r


def result(g, snap):
    a, h = g["score"]["away"], g["score"]["home"]
    if a is None or h is None:
        return None
    winner = g["away"] if a > h else g["home"] if h > a else None
    t = snap.get("teams") or {}
    fa = (t.get(g["away"]) or {}).get("fair")
    fh = (t.get(g["home"]) or {}).get("fair")
    pick = None if fa is None or fh is None else (g["home"] if fh >= fa else g["away"])
    return {"winner": winner, "tie": a == h, "final": f"{g['away']} {a} — {g['home']} {h}", "pick": pick,
            "right": None if pick is None else (pick == winner)}


def changes_since_thursday(g, snap):
    th = snap.get("thursday")
    if not th:
        return []
    out = []
    for side in ("away", "home"):
        c = g["teams"][side]
        b = (th.get("teams") or {}).get(c["team"], {})
        if b.get("price") is not None and c.get("price") is not None and abs(b["price"] - c["price"]) >= 1:
            out.append(f"{c['team']} price {b['price']:.0f}¢ → {c['price']:.0f}¢")
        if b.get("call") and b.get("call") != c.get("call"):
            out.append(f"{c['team']} call {b['call']} → {c['call']}")
        if b.get("fair") is not None and c.get("fair") is not None and abs(b["fair"] - c["fair"]) >= 1:
            out.append(f"{c['team']} fair {b['fair']:.0f}¢ → {c['fair']:.0f}¢")
    old = {(i["team"], i["player"], i["status"]) for i in th.get("inj", [])}
    for i in g.get("injuries", []):
        if i["starter"] and (i["team"], i["player"], i["status"]) not in old:
            out.append(f"{i['team']} {i['pos']} {i['short']} now {i['status']}")
    if th.get("wxLine") and g.get("weatherLine") and th["wxLine"] != g["weatherLine"] and not g["indoor"]:
        out.append(f"Weather {th['wxLine']} → {g['weatherLine']}")
    return out


def top_three(calls):
    """Value first, then biggest edge, then confidence. Fewer when fewer qualify."""
    q = [c for c in calls if c.get("call") in ("Value", "Wait") and c.get("price") is not None]
    q.sort(key=lambda c: (c["call"] != "Value", -(c.get("edge") or 0), -c["confidence"]["score"]))
    return [c["key"] for c in q[:3]]


def set_thursday_baseline(board):
    snaps = load_json(SNAP_FILE, {}) or {}
    for g in board["games"]:
        if g["state"] != "pre" or g["key"] not in snaps:
            continue
        s = snaps[g["key"]]
        s["thursday"] = {"at": board["generatedAt"], "inj": [i for i in g["injuries"] if i["starter"]],
                         "spreadHome": g.get("espnSpread") if g.get("espnSpread") is not None else g.get("spreadHome"),
                         "wxLine": g.get("weatherLine"),
                         "teams": {g["teams"][x]["team"]: {k: g["teams"][x].get(k) for k in ("fair", "price", "call")}
                                   for x in ("away", "home")}}
    save_json(SNAP_FILE, snaps, compact=True)
