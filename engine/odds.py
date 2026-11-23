"""Consensus moneyline from The Odds API (free tier, 500 credits/month).

Switches on only when the ODDS_API_KEY secret exists; otherwise the app keeps using ESPN's
single sportsbook line. One call = 1 credit (h2h, up to 10 named books). Refresh: every 3 h,
every 45 min when a game kicks off within 3 h, never when fewer than 25 credits remain.
About 300 calls a month. Results live in state/odds.json (committed, so usage survives runs).

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
        for bk in ev.get("bookmakers", []):
            m = next((m for m in bk.get("markets", []) if m.get("key") == "h2h"), None)
            if not m:
                continue
            pr = {FULL.get(o.get("name")): o.get("price") for o in m.get("outcomes", [])}
            if home not in pr or away not in pr or None in (pr[home], pr[away]):
                continue
            ph, pa = _imp(pr[home]), _imp(pr[away])
            ps.append(ph / (ph + pa))
            sharp = bk.get("key") == "pinnacle"
            pin = pin or sharp
            w.append(2.0 if sharp else 1.0)
        if ps:
            out[f"{away}@{home}"] = {"pHome": round(sum(p * x for p, x in zip(ps, w)) / sum(w), 4),
                                     "books": len(ps), "pinnacle": pin, "kickoff": ev.get("commence_time"),
                                     "pMin": round(min(ps), 4), "pMax": round(max(ps), 4)}
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


def _due(st, now, kickoffs):
    last = st.get("fetchedAt")
    if st.get("left") is not None and st["left"] < MIN_LEFT:
        return False
    if not last:
        return True
    from .board import parse_dt
    age = now - parse_dt(last)
    soon = any(k and timedelta(0) < k - now < timedelta(hours=3) for k in kickoffs)
    return age >= (timedelta(minutes=45) if soon else timedelta(hours=3))


def refresh(kickoffs, now=None):
    """Fetch if due and a key exists. Returns the consensus dict (possibly from the last fetch)."""
    now = now or now_utc()
    st = load_json(FILE, {}) or {}
    key = _key()
    st["enabled"] = bool(key)
    if key and _due(st, now, kickoffs):
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
    return st.get("games") or {}
