"""Free data feeds with background health tracking and last-good-data fallback."""
import gzip
import io
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

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
def espn_scoreboard(dates=None, week=None, season=None):
    q = []
    if dates:
        q.append(f"dates={dates}")
    if week:
        q += [f"week={week}", "seasontype=2"]
    if season:
        q.append(f"season={season}")
    url = C.ESPN_SCOREBOARD + ("?" + "&".join(q) if q else "")
    key = f"sb_{dates or ''}{week or ''}"
    return cached("espn", key, lambda: _get(url))


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
