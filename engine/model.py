"""Version B pricing model — the one unified algorithm. Prices and fair values in cents."""
import math

from . import config as C


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fee_cents(price):
    """Round-trip-safe fee estimate Rick pays on Robinhood, per contract, in cents.
    Commission k*P*(1-P) (k=10%, 5% with Gold) capped at 1c and rounded up per trade, plus an
    exchange fee up to 1c. Both round up to 1c for any price strictly between 0 and 100, so the
    app uses 2c unless the computed value is lower (it never is at a 1c tick)."""
    if price is None:
        return 2.0
    p = max(0.0, min(1.0, price / 100.0))
    if p <= 0 or p >= 1:
        return 0.0
    commission = min(1.0, math.ceil(100 * 0.10 * p * (1 - p) * 100) / 100)  # cents, cap 1c
    exchange = min(1.0, math.ceil(100 * 0.07 * p * (1 - p) * 100) / 100)    # cents, cap 1c
    # each rounds up to a whole cent per trade
    return float(math.ceil(commission) + math.ceil(exchange))


def epa_adjustment(team, opp, is_home, neutral, spread_margin, teams):
    """EPA-implied margin vs the sportsbook margin; take half the gap, cap +/-3 pts.
    Returns (adj_pts, detail) or (0, None) when EPA data is missing (never invented)."""
    a, b = teams.get(team), teams.get(opp)
    if not a or not b or a.get("defEpaPerPlay") is None or b.get("defEpaPerPlay") is None:
        return 0.0, None
    plays = ((a.get("playsPerGame") or 62) + (b.get("playsPerGame") or 62)) / 2
    net = 0.5 * ((a["offEpaPerPlay"] + b["defEpaPerPlay"]) - (b["offEpaPerPlay"] + a["defEpaPerPlay"]))
    hfa = 0.0 if neutral else (C.HOME_FIELD if is_home else -C.HOME_FIELD)
    epa_margin = net * plays + hfa
    raw = C.EPA_ADJ_WEIGHT * (epa_margin - spread_margin)
    adj = max(-C.EPA_ADJ_CAP, min(C.EPA_ADJ_CAP, raw))
    return round(adj, 2), {"epaMargin": round(epa_margin, 1), "raw": round(raw, 2), "capped": abs(raw) > C.EPA_ADJ_CAP}


def weather_pts(team, opp, wx, teams, indoor):
    """+1.0 to +1.5 pts to the run-heavy team if open-air wind >=15 mph or temp <=35F."""
    if indoor or not wx:
        return 0.0, None
    wind, temp, gust = wx.get("windMax"), wx.get("tempMin"), wx.get("gustMax")
    windy = wind is not None and wind >= C.WEATHER_WIND
    cold = temp is not None and temp <= C.WEATHER_TEMP
    if not (windy or cold):
        return 0.0, None
    a, b = teams.get(team, {}), teams.get(opp, {})
    ra, rb = a.get("runShare"), b.get("runShare")
    if ra is None or rb is None or ra <= rb:
        return 0.0, None
    pts = 1.5 if (windy and cold) or (wind or 0) >= 20 or (gust or 0) >= 30 else 1.0
    why = f"Wind {wind:.0f} mph" if windy else f"{temp:.0f}°F"
    return pts, why


def injury_pts(team_inj, baseline_inj=None, line_move=None):
    """Pregame: QB Out -3.5; >=2 WR/CB Out -1. Current injuries only, starters only.
    The sportsbook line already moves on injury news, so the points are applied ONLY when the
    news is fresh: the player wasn't out at the Thursday baseline AND the line hasn't moved
    >= 2 pts since. Otherwise it's shown as 'priced in' (no double counting)."""
    pts, notes = 0.0, []
    base = {(i.get("team"), i.get("player")) for i in (baseline_inj or []) if i.get("status") == "Out"}
    moved = line_move is not None and abs(line_move) >= C.LINE_MOVE_PRICED

    def fresh(i):
        return baseline_inj is not None and (i.get("team"), i.get("player")) not in base and not moved
    qb = [i for i in team_inj if i["pos"] == "QB" and i["status"] == "Out" and i.get("starter")]
    if qb:
        if fresh(qb[0]):
            pts += C.QB_OUT_PTS
            notes.append(f"QB {qb[0]['short']} out")
        else:
            notes.append(f"QB {qb[0]['short']} out (priced in)")
    wrcb = [i for i in team_inj if i["pos"] in ("WR", "CB") and i["status"] == "Out" and i.get("starter")]
    if len(wrcb) >= 2:
        if any(fresh(i) for i in wrcb):
            pts += C.WRCB_OUT_PTS
            notes.append(f"{len(wrcb)} WR/CB out")
        else:
            notes.append(f"{len(wrcb)} WR/CB out (priced in)")
    return pts, notes


def fair_pair(pts_a, extra_shrink=1.0):
    """pts_a = team A's adjusted margin (pts). Returns fair cents for A and B (sum 100)."""
    s = C.SHRINK * extra_shrink
    p = phi(pts_a * s / C.SIGMA)
    if p > 0.65 or p < 0.35:
        s = C.SHRINK_FAV * extra_shrink
        p = phi(pts_a * s / C.SIGMA)
    fa = round(100 * p, 1)
    return fa, round(100 - fa, 1), s


def classify(fair, price, fee=None):
    """Value now (>=15c after fees) / Wait for a dip (8-15c) / Pass."""
    if fair is None or price is None:
        return {"call": "Pass", "edge": None, "buyAt": None, "fee": fee_cents(price)}
    fee = fee_cents(price) if fee is None else fee
    edge = round(fair - price - fee, 1)
    if edge >= C.VALUE_EDGE:
        return {"call": "Value", "edge": edge, "buyAt": int(math.floor(price)), "fee": fee}
    if edge >= C.WAIT_EDGE:
        return {"call": "Wait", "edge": edge, "buyAt": int(math.floor(fair - C.VALUE_EDGE - fee)), "fee": fee}
    return {"call": "Pass", "edge": edge, "buyAt": None, "fee": fee}


CAL_DEFAULT = {"50": 1.0, "60": 1.0, "70": 1.0, "80": 1.0, "90": 1.0}  # 5-season check: calibrated


def confidence(fair, edge, completeness, calib=None):
    """0-100 + Low/Med/High from fair probability, edge after fees, calibration, completeness.
    Not a guarantee: in the backtest 80%+ favourites won only 66.7%."""
    calib = calib or CAL_DEFAULT
    drivers = []
    if fair is None:
        return {"score": 0, "level": "Low", "drivers": [{"k": "Fair", "v": 0}]}
    s_fair = min(1.0, abs(fair - 50) / 30.0) * 30
    s_edge = max(0.0, min(1.0, (edge or 0) / C.VALUE_EDGE)) * 30
    bucket = str(min(90, max(50, int(max(fair, 100 - fair) // 10 * 10))))
    rel = calib.get(bucket, 1.0)
    s_cal = 20 * rel
    s_data = 20 * completeness
    score = int(round(s_fair + s_edge + s_cal + s_data))
    level = "High" if score >= 65 else "Med" if score >= 40 else "Low"
    drivers = [{"k": "Fair", "v": round(s_fair)}, {"k": "Edge", "v": round(s_edge)},
               {"k": "Calib", "v": round(s_cal)}, {"k": "Data", "v": round(s_data)}]
    return {"score": score, "level": level, "drivers": drivers, "max": {"Fair": 30, "Edge": 30, "Calib": 20, "Data": 20}}


def why_line(c):
    """Exactly one short why-it-matters line."""
    if c.get("fair") is None:
        return "No sportsbook line yet"
    if c.get("price") is None:
        return "Price unavailable"
    for n in c.get("injNotes", []):
        if n.startswith("QB") and "priced in" not in n:
            return f"{n} — {abs(C.QB_OUT_PTS):g} pts"
    for n in c.get("oppInjNotes", []):
        if n.startswith("QB") and "priced in" not in n:
            return f"Opp {n} — +{abs(C.QB_OUT_PTS):g} pts"
    if c.get("weatherWhy"):
        return c["weatherWhy"] if "favors" in c["weatherWhy"] else f"{c['weatherWhy']} — run game edge"
    e, call = c.get("edge"), c.get("call")
    if e is None:
        return "No pregame snapshot"
    if call == "Value":
        return f"{e:.0f}¢ under fair after fees"
    if call == "Wait":
        return f"{e:.0f}¢ under fair — wait for {c['buyAt']}¢"
    over = c["price"] - c["fair"]
    if over > 0:
        return f"Priced {over:.0f}¢ above fair"
    return f"Only {e:.0f}¢ edge after fees"
