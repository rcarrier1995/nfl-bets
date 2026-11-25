"""Consensus moneyline from The Odds API (free tier, 500 credits/month).

Switches on only when the ODDS_API_KEY secret exists; otherwise the app keeps using ESPN's
single sportsbook line. One call = 1 credit (h2h, up to 10 named books). Schedule: engine/quota.py
(every 20 min while games are live, 30 min in the 2 h before kickoff, 9 AM + 6 PM CT otherwise, Refresh taps).
About 320 calls a month plus taps; never when fewer than 25 credits remain. Results live in state/odds.json (committed, so usage survives runs).

Each book's two moneylines are de-vigged; the consensus win chance is the average, with
Pinnacle (the sharpest book) counted twice. It is turned into an equivalent home spread so the
rest of the model (weather, fresh injuries) works unchanged.
"""
import json
import math
import os
import urllib.parse
import urllib.request
from datetime import timedelta

from . import config as C
from .fetch import load_json, save_json, iso, now_utc, HEALTH

FILE = os.path.join(C.STATE, "odds.json")
URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
BOOKS = "pinnacle,draftkings,fanduel,betmgm,caesars,espnbet,betrivers,fanatics,bovada,betonlineag"
MIN_LEFT = 25
LIVE_MIN, PRE_MIN = 20, 30     # minutes between pulls while games are live / in the 2 h before kickoff

FULL = {"Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
        "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
        "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
        "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
        "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
        "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
        "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG", "New York Jets": "NYJ",
        "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
        "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN",
        "Washington Commanders": "WSH"}


def _key():
    return os.environ.get("ODDS_API_KEY", "").strip()


def _imp(price):
    """American odds -> implied probability (with vig)."""
    price = float(price)
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def consensus_from(events):
    """[(api event)] -> {(away, home): {"pHome": 0-1, "books": n, "pinnacle": bool}}"""
    out = {}
    for ev in events or []:
        home, away = FULL.get(ev.get("home_team")), FULL.get(ev.get("away_team"))
        if not home or not away:
            continue
        ps, w, pin = [], [], False
        best = {}   # Sports Book mode: the best real moneyline per team across the books, and where
        for bk in ev.get("bookmakers", []):
            m = next((m for m in bk.get("markets", []) if m.get("key") == "h2h"), None)
            if not m:
                continue
            pr = {FULL.get(o.get("name")): o.get("price") for o in m.get("outcomes", [])}
            if home not in pr or away not in pr or None in (pr[home], pr[away]):
                continue
            ph, pa = _imp(pr[home]), _imp(pr[away])
            ps.append(ph / (ph + pa))
            for t in (home, away):
                if t not in best or _imp(pr[t]) < _imp(best[t]["odds"]):
                    best[t] = {"odds": int(round(float(pr[t]))), "book": bk.get("title") or bk.get("key")}
            sharp = bk.get("key") == "pinnacle"
            pin = pin or sharp
            w.append(2.0 if sharp else 1.0)
        if ps:
            out[f"{away}@{home}"] = {"pHome": round(sum(p * x for p, x in zip(ps, w)) / sum(w), 4),
                                     "books": len(ps), "pinnacle": pin, "kickoff": ev.get("commence_time"),
                                     "pMin": round(min(ps), 4), "pMax": round(max(ps), 4), "best": best}
    return out


def spread_from_p(p_home):
    """Win chance -> equivalent home spread in the model's own scale (negative = home favoured)."""
    p = min(max(p_home, 0.005), 0.995)
    # inverse normal CDF (Acklam-style via erfinv approximation)
    z = math.sqrt(2) * _erfinv(2 * p - 1)
    return round(-z * C.SIGMA / C.SHRINK, 2)


def _erfinv(x):
    a = 0.147
    ln = math.log(1 - x * x)
    t = 2 / (math.pi * a) + ln / 2
    return math.copysign(math.sqrt(math.sqrt(t * t - ln / a) - t), x)


def _due(st, now, games):
    """Quota plan in engine/quota.py: every 20 min while games are live, 30 min in the 2 h before a kickoff,
    9 AM + 6 PM Central otherwise, a Refresh tap any time (30 min apart). Never when fewer than 25 credits remain."""
    if st.get("left") is not None and st["left"] < MIN_LEFT:
        return False
    from .board import parse_dt
    from . import quota as Q
    last = parse_dt(st["fetchedAt"]) if st.get("fetchedAt") else None
    return Q.due(last, now, games, LIVE_MIN, PRE_MIN)


def refresh(games, now=None):
    """Fetch if due and a key exists. Returns the consensus dict (possibly from the last fetch)."""
    now = now or now_utc()
    st = load_json(FILE, {}) or {}
    key = _key()
    st["enabled"] = bool(key)
    if key and _due(st, now, games):
        q = urllib.parse.urlencode({"apiKey": key, "markets": "h2h", "oddsFormat": "american", "bookmakers": BOOKS})
        try:
            req = urllib.request.Request(f"{URL}?{q}", headers={"User-Agent": "nfl-bets"})
            with urllib.request.urlopen(req, timeout=25) as r:
                body = json.loads(r.read())
                left = r.headers.get("x-requests-remaining")
                used = r.headers.get("x-requests-used")
            st.update({"fetchedAt": iso(now), "games": consensus_from(body),
                       "left": int(float(left)) if left else None, "used": int(float(used)) if used else None,
                       "error": None})
            HEALTH.ok("odds")
        except Exception as e:  # keep last good consensus
            st["error"] = str(e)[:200]
            HEALTH.fail("odds", e)
    save_json(FILE, st, compact=True)
    # only trust a consensus fetched within 12 h
    from .board import parse_dt
    fa = parse_dt(st.get("fetchedAt")) if st.get("fetchedAt") else None
    if not fa or now - fa > timedelta(hours=12):
        return {}
    return {k: {**v, "at": st["fetchedAt"]} for k, v in (st.get("games") or {}).items()}


def live_attach(g, cons, kickoff, now):
    """Info only (live prices tested fair, 2026-11-25): while a game is on, show the sportsbooks' current
    consensus next to the Robinhood price when they are 3c+ apart. Needs a pull made after kickoff, <25 min old."""
    from .board import parse_dt
    for side in ("away", "home"):
        g["teams"][side]["liveBookLine"] = None
    if g.get("state") != "in" or not kickoff:
        return
    cs = (cons or {}).get(f"{g['away']}@{g['home']}")
    at = parse_dt(cs["at"]) if cs and cs.get("at") else None
    if not at or at <= kickoff or now - at > timedelta(minutes=25):
        return
    for side in ("away", "home"):
        c = g["teams"][side]
        pct = round((cs["pHome"] if side == "home" else 1 - cs["pHome"]) * 100)
        if c.get("price") is None:
            continue
        d = round(c["price"] - pct)
        if abs(d) >= 3:
            c["liveBookLine"] = (f"Sportsbooks now ({cs['books']}): {c['team']} {pct}% · Robinhood {abs(d)}¢ "
                                 + ("dearer" if d > 0 else "cheaper"))
