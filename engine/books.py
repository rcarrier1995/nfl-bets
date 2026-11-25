"""Three more free sportsbook feeds (Rick, 2026-11-25), INFO ONLY: none changes Buy / Wait / Pass.

  PinnWire    Pinnacle's own moneyline (the sharpest book). Secret PINNWIRE_API_KEY (free: 100 calls/day).
  OddsPapi    300+ books incl. Pinnacle (30 s delay); we read Pinnacle + DraftKings + FanDuel. Secret ODDSPAPI_API_KEY
              (free: 250 calls/month).
  TheRundown  DraftKings, FanDuel, BetMGM moneylines, 5 min behind. Secret RUNDOWN_API_KEY (free: 20,000 data points/day).

Each feed is off until its secret exists, is called only while a game starts within 8 days, and is spaced so it
stays inside its free limit. Prices are de-vigged into a win % per team. If a feed fails its slot stays empty
(never guessed). Card shows one line only when the sharp book (Pinnacle) is 3c+ away from the Robinhood price.
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from . import config as C
from .fetch import load_json, save_json, iso, HEALTH

STATE_FILE = os.path.join(C.STATE, "books.json")
GAP = 3                      # cents between the sharp line and Robinhood before the card shows it
EVERY = {"pinnwire": 20, "oddspapi": 240, "rundown": 10}     # minutes between calls in game/pregame windows (quota.py)
KEYS = {"pinnwire": "PINNWIRE_API_KEY", "oddspapi": "ODDSPAPI_API_KEY", "rundown": "RUNDOWN_API_KEY"}
UA = "nfl-bets-assistant/1.0 (personal, read-only)"


def _get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _p_dec(d):
    try:
        d = float(d)
        return 1 / d if d > 1 else None
    except (TypeError, ValueError):
        return None


def _p_us(a):
    try:
        a = float(str(a).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if abs(a) < 100:
        return None
    return 100 / (a + 100) if a > 0 else -a / (-a + 100)


def _devig(pa, ph):
    if pa is None or ph is None or pa + ph <= 0:
        return None
    return round(pa / (pa + ph) * 100, 1), round(ph / (pa + ph) * 100, 1)


class Teams:
    """Find the ESPN abbreviation inside any book's team name ('Green Bay Packers', 'Packers', 'GB')."""

    def __init__(self, nick):
        self.nick = {a: n.lower() for a, n in nick.items() if n}

    def find(self, *names):
        for s in names:
            s = (s or "").strip()
            if not s:
                continue
            if s.upper() in self.nick:
                return s.upper()
            low = s.lower()
            hits = [a for a, n in self.nick.items() if n in low]
            if len(hits) == 1:
                return hits[0]
        return None


# ---------------- the three feeds: each returns {frozenset(away, home): {away: pct, home: pct}} ----------------
def pinnwire(key, T):
    d = _get(f"https://pinnwire.com/kit/v1/prematch/fixtures?sport_id=5", {"x-api-key": key})
    out = {}
    for e in d.get("events") or []:
        if "NFL" not in str(e.get("league_name") or "").upper():
            continue
        a, h = T.find(e.get("away")), T.find(e.get("home"))
        ml = ((e.get("periods") or {}).get("num_0") or {}).get("money_line") or {}
        p = _devig(_p_dec(ml.get("away")), _p_dec(ml.get("home")))
        if a and h and p:
            out[frozenset((a, h))] = {"Pinnacle": {a: p[0], h: p[1]}}
    return out


def oddspapi(key, T, st):
    base = "https://api.oddspapi.io/v4"
    q = lambda path, **kw: f"{base}/{path}?" + urllib.parse.urlencode({**kw, "apiKey": key})   # noqa
    tid = st.get("oddspapiNfl")
    if not tid:          # one-time lookup of the NFL league id (costs 1 call)
        for t in _get(q("tournaments", sportId=14)) or []:
            if str(t.get("tournamentName", "")).strip().upper() == "NFL":
                tid = t.get("tournamentId")
                break
        if not tid:
            raise ValueError("NFL league not found")
        st["oddspapiNfl"] = tid
    books = {"pinnacle+30": "Pinnacle", "draftkings": "DraftKings", "fanduel": "FanDuel"}
    rows = _get(q("odds-by-tournaments", tournamentIds=tid, bookmaker=",".join(books)))
    out = {}
    for f in rows if isinstance(rows, list) else []:
        a = T.find(f.get("participant2Name"), f.get("participant2Abbr"))   # assumed: participant1 = home (checked live)
        h = T.find(f.get("participant1Name"), f.get("participant1Abbr"))
        if not (a and h):
            continue
        for slug, name in books.items():
            m = (((f.get("bookmakerOdds") or {}).get(slug) or {}).get("markets") or {}).get("141") or {}
            oc = list((m.get("outcomes") or {}).values())
            if len(oc) != 2:
                continue
            pr = [((o.get("players") or {}).get("0") or {}).get("price") for o in oc]
            p = _devig(_p_dec(pr[1]), _p_dec(pr[0]))       # outcome order 1 (participant1), 2 (participant2)
            if p:
                out.setdefault(frozenset((a, h)), {})[name] = {a: p[0], h: p[1]}
    return out


def rundown(key, T, dates):
    out = {}
    for i, ds in enumerate(dates):
        if i:
            time.sleep(1.2)           # free plan: 1 request a second
        d = _get(f"https://therundown.io/api/v2/sports/2/events/{ds}?market_ids=1&affiliate_ids=19,23,22"
                 f"&main_line=true&offset=360", {"X-TheRundown-Key": key})
        for e in d.get("events") or []:
            teams = e.get("teams") or []
            ab = {("home" if t.get("is_home") else "away"): T.find(t.get("mascot"), t.get("abbreviation"), t.get("name"))
                  for t in teams}
            ids = {t.get("team_id"): ("home" if t.get("is_home") else "away") for t in teams}
            if not (ab.get("away") and ab.get("home")):
                continue
            for m in e.get("markets") or []:
                if m.get("market_id") != 1:
                    continue
                by_book = {}
                for part in m.get("participants") or []:
                    side = ids.get(part.get("id"))
                    for ln in (part.get("lines") or [])[:1]:
                        for aff, pz in (ln.get("prices") or {}).items():
                            if side and abs(float(pz.get("price") or 0)) >= 100:
                                by_book.setdefault(aff, {})[side] = _p_us(pz.get("price"))
                names = {"19": "DraftKings", "23": "FanDuel", "22": "BetMGM"}
                for aff, sides in by_book.items():
                    p = _devig(sides.get("away"), sides.get("home"))
                    if p and aff in names:
                        out.setdefault(frozenset((ab["away"], ab["home"])), {})[names[aff]] = \
                            {ab["away"]: p[0], ab["home"]: p[1]}
    return out


# ---------------- refresh + attach ----------------
def refresh(nick, games, now):
    """Call each switched-on feed when due (schedule in quota.py). Returns merged {game: {book: {...}}}."""
    from . import quota as Q
    games = Q.norm(games)
    kickoffs = [k for k, s in games if s == "pre"]
    st = load_json(STATE_FILE, {}) or {}
    soon = any(k and timedelta(0) < k - now < timedelta(days=8) for k in kickoffs)
    T = Teams(nick)
    dates = sorted({k.astimezone(C.CT).strftime("%Y-%m-%d") for k in kickoffs if k and timedelta(0) < k - now < timedelta(days=8)})
    for name, env in KEYS.items():
        key = (os.environ.get(env) or "").strip()
        s = st.setdefault(name, {})
        s["on"] = bool(key)
        if not key or not soon:
            continue
        last = s.get("at")
        last = datetime.fromisoformat(last.replace("Z", "+00:00")) if last else None
        if not Q.due(last, now, games, EVERY[name], EVERY[name]):
            continue
        try:
            data = (pinnwire(key, T) if name == "pinnwire" else oddspapi(key, T, st) if name == "oddspapi"
                    else rundown(key, T, dates))
            s.update({"at": iso(now), "ok": True, "games": len(data), "data": {"|".join(sorted(k)): v for k, v in data.items()}})
            s.pop("error", None)
            HEALTH.ok(name, f"{len(data)} games")
        except Exception as e:  # noqa
            s.update({"at": iso(now), "ok": False, "error": str(e)[:200]})
            HEALTH.fail(name, e)
    save_json(STATE_FILE, st)
    merged = {}
    for name in KEYS:
        s = st.get(name) or {}
        if not s.get("on") or not s.get("data"):
            continue
        okat = s.get("at") if s.get("ok") else None
        if not okat:
            continue
        for k, books in s["data"].items():
            for b, v in books.items():
                merged.setdefault(frozenset(k.split("|")), {}).setdefault(b, v)
    return merged


def attach(g, merged):
    """c['books'] = {book: win %}; c['sharpLine'] when Pinnacle is 3c+ away from the Robinhood price."""
    books = merged.get(frozenset((g["away"], g["home"]))) or {}
    for side in ("away", "home"):
        c = g["teams"][side]
        c["books"] = {b: v.get(c["team"]) for b, v in books.items() if v.get(c["team"]) is not None} or None
        c["sharpLine"] = None
        pin = (c["books"] or {}).get("Pinnacle")
        if g["state"] == "pre" and pin is not None and c.get("price") is not None:
            d = round(c["price"] - pin)
            if abs(d) >= GAP:
                c["sharpLine"] = (f"Pinnacle (sharpest book) gives {c['team']} {pin:.0f}% · Robinhood {abs(d)}¢ "
                                  + ("dearer" if d > 0 else "cheaper"))
