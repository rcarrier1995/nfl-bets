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


def sell_check(fair, bid, fee=None):
    """Sell (if you own it): the price you'd get now (bid) is >= 15c above fair after fees.
    Back-tested live 2024-26 (market win % vs our own model, first signal per team per game):
    +3.5c, +10.0c, +1.9c per contract vs holding to the end."""
    if fair is None or bid is None or bid <= 0:
        return None
    fee = fee_cents(bid) if fee is None else fee
    edge = round(bid - fair - fee, 1)
    return {"bid": bid, "edge": edge} if edge >= C.VALUE_EDGE else None


CAL_DEFAULT = {"50": 1.0, "60": 1.0, "70": 1.0, "80": 1.0, "90": 1.0}  # 5-season check: calibrated


GRADE_CUTS = ((75, "A"), (60, "B"), (45, "C"))
GRADE_TESTED = {"A": 84, "B": 67, "C": 54, "F": 32}      # backtest win % per grade, 1,521 games 2021-26
COMBO_CUTS = ((33, "A"), (15, "B"), (7, "C"))            # combo hit chance: 1 in 3, 1 in 7, 1 in 14


def grade(p, cuts=GRADE_CUTS):
    """Letter grade for a win chance in percent. Never invents: None -> None."""
    if p is None:
        return None
    for lo, g in cuts:
        if p >= lo:
            return g
    return "F"


def confidence(fair, edge=None, completeness=1.0, calib=None):
    """Win chance for this team, in plain levels. It is confidence the TEAM WINS, not that the bet is good
    (Buy / Wait / Pass says that). Letter grade (Rick 2026-11-23): A = 75%+ to win, B = 60-75%,
    C = 45-60%, F = under 45%. Checked on 1,521 games 2021-26 (both teams, ties dropped):
    A won 84%, B 67%, C 54%, F 32%."""
    if fair is None:
        return {"score": 0, "level": "F", "win": None, "drivers": [{"k": "Win chance", "v": 0}]}
    level = grade(fair)
    out = {"score": int(round(fair)), "level": level, "win": round(fair, 1),
           "drivers": [{"k": "Win chance", "v": round(fair)}], "max": {"Win chance": 100}}
    if completeness < 1:
        out["missing"] = True
    return out


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
