"""Live games: scores, clock, possession, live fair, dips, 20% payout rule, pauses, quarter snapshots."""
from datetime import datetime, timedelta

from . import config as C
from . import injuries as I
from . import model as M
from .fetch import iso

TO_TYPES = ("Interception", "Fumble Recovery (Opponent)", "Fumble Return Touchdown", "Sack Opp Fumble Recovery")


def _team_ids(ev):
    m = {}
    for t in ev["competitions"][0]["competitors"]:
        m[t["team"]["id"]] = C.espn_abbr(t["team"]["abbreviation"])
    return m


def _prob_home(ev, summary):
    sit = ev["competitions"][0].get("situation") or {}
    pr = ((sit.get("lastPlay") or {}).get("probability")) or {}
    if pr.get("homeWinPercentage") is not None:
        return pr["homeWinPercentage"], pr.get("tiePercentage") or 0
    wp = (summary or {}).get("winprobability") or []
    if wp:
        return wp[-1].get("homeWinPercentage"), wp[-1].get("tiePercentage") or 0
    return None, 0


def live_update(g, summary, ev, tables, live_state, snap, now):
    gid = g["id"]
    ls = live_state.setdefault(gid, {"prices": {}, "tds": {}, "alertsSent": [], "quarters": []})
    ids = _team_ids(ev)
    comp = ev["competitions"][0]
    sit = comp.get("situation") or {}
    g["possession"] = ids.get(sit.get("possession"))
    g["downDist"] = sit.get("shortDownDistanceText") or sit.get("downDistanceText")
    g["redZone"] = sit.get("isRedZone")
    period = g.get("period") or 0
    secs = I.seconds_left(period, g.get("clock") or "0:00") if g["state"] == "in" else 0
    margin = abs((g["score"]["away"] or 0) - (g["score"]["home"] or 0))
    plays = I.parse_plays(summary) if summary else []
    final = g["state"] == "post"

    # ---- turnovers by team & quarter ----
    tos = {g["away"]: {}, g["home"]: {}}
    for p in plays:
        if any(t in p["type"] for t in TO_TYPES) and p.get("team"):
            tm = C.espn_abbr(p["team"])
            if tm in tos:
                tos[tm][p["q"]] = tos[tm].get(p["q"], 0) + 1
    for blk in ((summary or {}).get("boxscore") or {}).get("teams", []):
        tm = C.espn_abbr(blk["team"]["abbreviation"])
        for s in blk.get("statistics", []):
            if s.get("name") == "turnovers":
                try:
                    tot = int(s["displayValue"])
                    if tm in tos and tot > sum(tos[tm].values()):
                        tos[tm]["?"] = tot - sum(tos[tm].values())
                except Exception:
                    pass
    to_tot = {t: sum(v.values()) for t, v in tos.items()}

    # ---- TDs (for "just scored" and the dip reference) ----
    td_count = {g["away"]: 0, g["home"]: 0}
    for sp in (summary or {}).get("scoringPlays") or []:
        if "Touchdown" in ((sp.get("type") or {}).get("text") or ""):
            tm = ids.get((sp.get("team") or {}).get("id"))
            if tm in td_count:
                td_count[tm] += 1
    for tm, n in td_count.items():
        if tm not in ls["tds"]:
            ls["tds"][tm] = {"n": n, "at": None}   # first look: don't treat old TDs as "just scored"
            continue
        prevn = ls["tds"][tm].get("n", 0)
        if n > prevn:
            ls["tds"][tm] = {"n": n, "at": iso(now)}
        elif tm not in ls["tds"]:
            ls["tds"][tm] = {"n": n, "at": None}

    # ---- injuries, QB changes ----
    inj_events = I.track_injuries(plays, period, final, C.espn_abbr)
    passers = I.passers_by_quarter(plays, C.espn_abbr)
    impacts = {g["away"]: [], g["home"]: []}
    inj_live = []
    for e in inj_events:
        if e["team"] not in impacts:
            continue
        e["opp"] = g["home"] if e["team"] == g["away"] else g["away"]
        im = I.impact(e, tables, I.seconds_left(e["q"], e["clock"]))
        im["state"] = e["state"]
        im["confirmedQ"] = e["confirmedQ"]
        inj_live.append(im)
        if e["state"] == "confirmed" and im["starter"]:
            impacts[e["team"]].append(im)
    qb = {}
    for tm in (g["away"], g["home"]):
        starter, ch = I.qb_change(passers, tm, tables)
        qb[tm] = {"starter": starter, "change": ch}
        if ch:
            bm = (tables.get("backup_map") or {}).get(f"{tm}|{ch['from']}") or {}
            gate = bm.get("gate") or {}
            sl = I.seconds_left(ch["q"], "7:30")
            pts = C.QB_OUT_PTS * I.time_factor(sl) / (2 if gate.get("halve") else 1)
            already = any(i.get("isQB") for i in impacts[tm])
            if not already:
                impacts[tm].append({"team": tm, "name": ch["from"], "pos": "QB", "isQB": True, "q": ch["q"],
                                    "impact": round(max(pts, -4.0), 2), "tf": I.time_factor(sl), "gate": gate,
                                    "confirmedQ": ch["q"], "starter": True, "base": C.QB_OUT_PTS, "rf": 1, "mf": 1,
                                    "relianceText": "QB change (play-by-play, lag)", "state": "confirmed",
                                    "full": ch["from"], "flags": []})
    g["injLive"] = inj_live
    g["qb"] = qb
    g["turnovers"] = to_tot

    # ---- quarter snapshots (score, leader, weather, injuries, turnovers, QB) ----
    lines = g.get("linescores") or {}
    quarters = []
    nq = max(len(lines.get("away") or []), len(lines.get("home") or []))
    ca = ch_ = 0
    kick = None
    try:
        kick = datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00"))
    except Exception:
        pass
    for q in range(1, nq + 1):
        qa = (lines.get("away") or [None] * q)[q - 1] if len(lines.get("away") or []) >= q else None
        qh = (lines.get("home") or [None] * q)[q - 1] if len(lines.get("home") or []) >= q else None
        ca += qa or 0
        ch_ += qh or 0
        wq = None
        if g.get("weather") and kick:
            hrs = g["weather"]["hours"]
            target = min(5, int(q * 0.8))   # rough hour offset of each quarter
            row = next((h for h in hrs if h["rel"] == target), None)
            if row:
                wq = f"{row['temp']:.0f}°F · gusts {row['gust']:.0f}" if row.get("gust") is not None else f"{row['temp']:.0f}°F"
        quarters.append({"q": q, "away": qa, "home": qh, "cumAway": ca, "cumHome": ch_,
                         "leader": g["away"] if ca > ch_ else g["home"] if ch_ > ca else "Tied",
                         "weather": wq if not g.get("indoor") else "Indoors",
                         "injuries": [f"{i['team']} {i['pos']} {i['name']}" + (" (back)" if i["state"] == "returned" else "")
                                      for i in inj_live if i["q"] == q],
                         "turnovers": {g["away"]: tos[g["away"]].get(q, 0), g["home"]: tos[g["home"]].get(q, 0)},
                         "qb": {tm: ", ".join((passers.get(tm) or {}).get(q, [])) for tm in (g["away"], g["home"])}})
    g["quarters"] = quarters
    ls["quarters"] = quarters
    ls["injLive"] = inj_live

    # ---- live fair & calls & alerts ----
    ph, tie = _prob_home(ev, summary)
    alerts = []
    for side in ("away", "home"):
        c = g["teams"][side]
        tm, opp = c["team"], c["opp"]
        hist = ls["prices"].setdefault(tm, [])
        if c.get("price") is not None and (not hist or hist[-1][1] != c["price"]):
            hist.append([iso(now), c["price"]])
            del hist[:-60]
        if g["state"] != "in":
            continue
        if ph is None:
            c["liveFair"] = None
        else:
            p = ph if side == "home" else 1 - ph - tie
            c["liveFair"] = round(100 * (p + tie / 2), 1)
        lines_ = []
        pause_dip, pause_vw = False, False
        # injury formula
        imp = I.combine(impacts[tm]) if impacts[tm] else 0.0
        cut = 0.0
        for im in impacts[tm]:
            tag = "QB" if im.get("isQB") else im["pos"]
            lines_.append({"text": f"{tag} {im['name']} out — impact {im['impact']:+.1f} pt", "detail": im, "kind": "inj"})
        if impacts[tm]:
            if abs(imp) >= 1.5:
                cut += abs(imp) * C.PTS_TO_CENTS
                if period <= max(i["confirmedQ"] for i in impacts[tm]):
                    pause_dip = True
            if abs(imp) >= 2.0:
                pause_vw = True
        # NextQFactor: top-10 (prior-week EPA) or any confirmed-out QB -> next quarter only
        nq_cut = 0.0
        for im in impacts[tm]:
            if (im.get("top10") or im.get("isQB")) and period == im["confirmedQ"] + 1:
                pts = -1.5 if im.get("isQB") else -1.0
                nq_cut += abs(pts) * C.PTS_TO_CENTS
                pause_dip = True
                lines_.append({"text": f"⭐ Next-quarter dip {pts:+.1f} pt ({im['name']})", "kind": "nextq",
                               "detail": {"pts": pts, "q": period}})
        # QB change pause rules
        chg = qb[tm]["change"]
        if chg:
            garbage = chg["q"] >= 4 and margin >= 21
            if not garbage and (chg["q"] <= 3 or margin < 14):
                pause_dip = pause_vw = True
                lines_.append({"text": f"⏸ QB change Q{chg['q']} — alerts paused", "kind": "pause"})
        if to_tot.get(tm, 0) >= 2:
            lines_.append({"text": f"{to_tot[tm]} turnovers — downgrade, no dip buy", "kind": "to"})
        c["liveCuts"] = {"injury": round(cut, 1), "nextQ": round(nq_cut, 1), "impactPts": imp}
        if c["liveFair"] is not None:
            c["liveFair"] = round(max(0.0, c["liveFair"] - cut - nq_cut), 1)
        cl = M.classify(c["liveFair"], c.get("price"))
        live_call = cl["call"]
        if to_tot.get(tm, 0) >= 2:
            live_call = {"Value": "Wait", "Wait": "Pass"}.get(live_call, live_call)
        late = period >= 5 or (period == 4 and secs < 300)
        if pause_vw and live_call in ("Value", "Wait"):
            live_call = "Pass"
            lines_.append({"text": "⏸ Big injury — Value/Wait paused rest of game", "kind": "pause"})
        c["liveCall"], c["liveEdge"], c["liveBuyAt"] = live_call, cl["edge"], cl["buyAt"]
        if live_call == "Wait":
            c["liveBuyAt"] = cl["buyAt"]
        # TD dip line + 20% payout rule
        otd = ls["tds"].get(opp, {})
        ref = c.get("pregamePrice")
        if otd.get("at"):
            before = [p for t, p in hist if t < otd["at"]]
            if before:
                ref = before[-1]
        ttd = ls["tds"].get(tm, {})
        c["justScoredTD"] = bool(ttd.get("at") and now - datetime.fromisoformat(ttd["at"].replace("Z", "+00:00")) < timedelta(minutes=15))
        oppTD = bool(otd.get("at") and now - datetime.fromisoformat(otd["at"].replace("Z", "+00:00")) < timedelta(minutes=20))
        price = c.get("price")
        c["dipRef"] = ref
        if price is not None and ref is not None and price < ref and not late:
            c["dipLine"] = f"Dip alert: now {price:.0f}¢, was {ref:.0f}¢"
        payout_up = None
        if price is not None and ref is not None and ref < 100:
            payout_up = (100 - price) / (100 - ref) - 1
        c["payoutUp"] = None if payout_up is None else round(payout_up * 100, 1)
        lopsided = (g.get("spreadPts") or 0) >= C.LOPSIDED_SPREAD
        c["liveLines"] = lines_
        c["paused"] = pause_dip or pause_vw
        if late:
            c["alertsOff"] = "late Q4"
            continue
        if (cl["edge"] or -99) >= C.VALUE_EDGE and payout_up is not None and payout_up >= 0.20 and lopsided \
                and not pause_dip and to_tot.get(tm, 0) < 2 and live_call == "Value":
            alerts.append({"key": c["key"], "type": "dip", "team": tm, "game": g["short"], "price": price,
                           "profit": round(100 - price, 1), "confidence": c["confidence"]["level"],
                           "why": f"Payout +{payout_up * 100:.0f}% after {'opp TD' if oppTD else 'drop'} · {cl['edge']:.0f}¢ under fair",
                           "q": period})
    g["alerts"] = alerts
    return g
