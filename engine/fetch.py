"""Free data feeds with background health tracking and last-good-data fallback."""
import gzip
import io
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config as C

HEALTH_FILE = os.path.join(C.STATE, "health.json")
UA = {"User-Agent": "nfl-bets-assistant/1.0 (personal, read-only)"}


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt=None):
    return (dt or now_utc()).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj, compact=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        if compact:
            json.dump(obj, f, separators=(",", ":"), default=str)
        else:
            json.dump(obj, f, indent=1, default=str)
    os.replace(tmp, path)


class Health:
    """Records each feed's last success/failure. Never shown in main views."""

    def __init__(self):
        self.data = load_json(HEALTH_FILE, {}) or {}

    def ok(self, feed, note=""):
        d = self.data.setdefault(feed, {})
        d.update({"ok": True, "lastOk": iso(), "note": note, "fails": 0})

    def fail(self, feed, err):
        d = self.data.setdefault(feed, {})
        d.update({"ok": False, "lastFail": iso(), "error": str(err)[:200], "fails": d.get("fails", 0) + 1})

    def save(self):
        save_json(HEALTH_FILE, self.data)


HEALTH = Health()


def _get(url, timeout=25, raw=False, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read()
            return body if raw else json.loads(body)
        except Exception as e:  # noqa
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def cached(feed, key, fn):
    """Run fn(); on success cache result; on failure return last good copy (flagged stale)."""
    path = os.path.join(C.CACHE, f"{feed}_{key}.json")
    try:
        val = fn()
        save_json(path, {"at": iso(), "val": val}, compact=True)
        HEALTH.ok(feed)
        return val, False
    except Exception as e:
        HEALTH.fail(feed, e)
        old = load_json(path)
        if old:
            return old["val"], True
        return None, True


# ---------- ESPN (unofficial) ----------
# Playoffs: ESPN calls them season type 3, weeks 1-5 (4 = Pro Bowl). Inside the app they continue the
# regular-season count like nflverse does (19 Wild Card, 20 Divisional, 21 Conference, 22 Super Bowl), so
# playoff games never share keys, records or saved state with regular-season weeks 1-5.
POST_WEEK = {1: 19, 2: 20, 3: 21, 5: 22}
ESPN_POST = {v: k for k, v in POST_WEEK.items()}
LAST_WEEK = 22
WEEK_NAMES = {19: "Wild Card", 20: "Divisional", 21: "Conference", 22: "Super Bowl"}


def week_label(week):
    """'Week 12' in the regular season, the round name in the playoffs."""
    try:
        w = int(week)
    except (TypeError, ValueError):
        return "Week ?"
    return WEEK_NAMES.get(w, f"Week {w}")


def _app_week(season_obj, week_obj):
    typ = (season_obj or {}).get("type")
    n = (week_obj or {}).get("number")
    if typ == 3 and n is not None:
        return POST_WEEK.get(int(n))   # None for the Pro Bowl
    return n


def normalize_scoreboard(sb):
    """Rewrite ESPN playoff week numbers to the app's 19-22, drop the Pro Bowl (AFC vs NFC, no market)."""
    if not isinstance(sb, dict):
        return sb
    if not (sb.get("season") or {}).get("type") and sb.get("events"):   # some ESPN replies only tag the events
        sb["season"] = {**(sb.get("season") or {}), **{k: v for k, v in (sb["events"][0].get("season") or {}).items() if k in ("year", "type")}}
    if (sb.get("season") or {}).get("type") == 3 and isinstance(sb.get("week"), dict) and not sb["week"].get("espn"):
        n = sb["week"].get("number")
        sb["week"] = {**sb["week"], "espn": n, "number": POST_WEEK.get(int(n)) if n is not None else None}
    evs = []
    for ev in sb.get("events") or []:
        if isinstance(ev.get("week"), dict) and (ev.get("season") or {}).get("type") == 3 and not ev["week"].get("espn"):
            n = ev["week"].get("number")
            ev["week"] = {**ev["week"], "espn": n, "number": POST_WEEK.get(int(n)) if n is not None else None}
        if (ev.get("season") or {}).get("type") == 3 and (ev.get("week") or {}).get("number") is None:
            continue   # Pro Bowl
        comp = ((ev.get("competitions") or [{}])[0].get("competitors")) or []
        if any(str((c.get("team") or {}).get("abbreviation") or "TBD").upper() == "TBD" for c in comp):
            continue   # playoff placeholder (teams not known yet)
        evs.append(ev)
    if "events" in sb:
        sb["events"] = evs
    return sb


def espn_scoreboard(dates=None, week=None, season=None):
    q = []
    if dates:
        q.append(f"dates={dates}")
    if week:
        w = int(week)
        q += [f"week={ESPN_POST[w]}", "seasontype=3"] if w in ESPN_POST else [f"week={w}", "seasontype=2"]
    if season:
        q.append(f"season={season}")
    url = C.ESPN_SCOREBOARD + ("?" + "&".join(q) if q else "")
    key = f"sb_{dates or ''}{week or ''}"
    val, stale = cached("espn", key, lambda: _get(url))
    return normalize_scoreboard(val), stale


def current_scoreboard():
    """ESPN's default scoreboard stays on the old week until about Wednesday. Once every game of that week
    is final, move on to the next regular-season week (Rick 2026-11-24: app said Week 11 on Tuesday)."""
    sb, stale = espn_scoreboard()
    try:
        typ = (((sb or {}).get("season") or {}).get("type"))
        yr = ((sb or {}).get("season") or {}).get("year")
        if typ == 3 and ((sb or {}).get("week") or {}).get("number") is None:   # Pro Bowl week -> Super Bowl
            sb2, st2 = espn_scoreboard(week=LAST_WEEK, season=yr)
            if sb2 and sb2.get("events"):
                return sb2, st2
        ev = (sb or {}).get("events") or []
        wk = ((sb or {}).get("week") or {}).get("number")
        last = max((e.get("date") or "") for e in ev) if ev else ""
        # wait 16h after the last kickoff so the final game is graded and shown as Final first
        done_long = bool(last) and datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00")) > timedelta(hours=16)
        if ev and wk and typ in (2, 3) and int(wk) < LAST_WEEK and done_long and all(e["status"]["type"]["state"] == "post" for e in ev):
            nxt, st2 = espn_scoreboard(week=int(wk) + 1, season=yr)
            if nxt and nxt.get("events"):
                return nxt, st2
    except Exception as e:
        print("week rollover check failed:", e)
    return sb, stale


def espn_summary(event_id):
    return cached("espn", f"sum_{event_id}", lambda: _get(f"{C.ESPN_SUMMARY}?event={event_id}"))


# ---------- Kalshi public (no auth) ----------
def kalshi_events():
    def go():
        out, cursor = [], ""
        for _ in range(5):
            url = C.KALSHI_EVENTS + (f"&cursor={cursor}" if cursor else "")
            d = _get(url)
            out += d.get("events", [])
            cursor = d.get("cursor") or ""
            if not cursor:
                break
        return out
    return cached("kalshi", "events", go)


# ---------- Open-Meteo (no key) ----------
def kalshi_day_range(ticker, start_ts, end_ts):
    """(low, high) traded price in cents for one Kalshi market between two unix times, from its
    public 1-minute candles. None if no trades or the call fails (never guessed)."""
    series = ticker.split("-")[0]
    url = (f"{C.KALSHI_BASE}/series/{series}/markets/{ticker}/candlesticks"
           f"?start_ts={int(start_ts)}&end_ts={int(end_ts)}&period_interval=1")
    try:
        d = _get(url, timeout=15, tries=2)
    except Exception:
        return None
    lo = hi = None
    for c in d.get("candlesticks") or []:
        p = c.get("price") or {}
        try:
            l, h = float(p.get("low_dollars")) * 100, float(p.get("high_dollars")) * 100
        except (TypeError, ValueError):
            continue
        if float(c.get("volume_fp") or 0) <= 0:
            continue
        lo = l if lo is None else min(lo, l)
        hi = h if hi is None else max(hi, h)
    return None if lo is None else (round(lo, 1), round(hi, 1))


def weather_batch(points):
    """points: list of (lat, lon). One call for all stadiums. Forecast API incl. past day."""
    if not points:
        return [], False
    lat = ",".join(f"{p[0]:.4f}" for p in points)
    lon = ",".join(f"{p[1]:.4f}" for p in points)
    url = (f"{C.OPEN_METEO}?latitude={lat}&longitude={lon}"
           "&hourly=temperature_2m,wind_speed_10m,wind_gusts_10m,precipitation,weather_code"
           "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
           "&timezone=UTC&past_days=2&forecast_days=8")

    def go():
        d = _get(url, timeout=40)
        return d if isinstance(d, list) else [d]
    return cached("weather", "batch", go)


# ---------- nflverse GitHub releases ----------
def nflverse_csv(tag, fname):
    """Download a release file into state/cache (weekly). Returns local path or None."""
    import pandas as pd  # noqa
    path = os.path.join(C.CACHE, "nflverse", fname)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        body = _get(f"{C.NFLVERSE}/{tag}/{fname}", timeout=120, raw=True)
        with open(path, "wb") as f:
            f.write(body)
        HEALTH.ok("nflverse", fname)
    except Exception as e:
        HEALTH.fail("nflverse", f"{fname}: {e}")
        if not os.path.exists(path):
            return None
    return path


def read_csv(path, **kw):
    import pandas as pd
    if path is None:
        return None
    if path.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            return pd.read_csv(io.BytesIO(f.read()), low_memory=False, **kw)
    return pd.read_csv(path, low_memory=False, **kw)
