"""Five extra free feeds (Rick, 2026-11-25). All INFO ONLY: none of them changes Buy / Wait / Pass.

  Polymarket   second prediction market (gamma-api, no key). Flags when Robinhood/Kalshi is 3c+ off it.
  ESPN FPI     ESPN's own win chance, from the game summary we already fetch (predictor block).
  ESPN news    league news feed; injury / lineup headlines matched to a team, pushed for starting QBs.
  Practice     nflverse injuries file (official Wed/Thu/Fri practice report), saved once per day so we
               can show "DNP Wed, Limited Thu" for starters. Starting QB not practising -> one push.
  Kalshi money volume per check, "money moving" note when price moves 3c+ in an hour on heavy trading.

Backtests (research/feeds-study, 2021-26 incl. playoffs, fit 2021-24, check 2025-26):
  FPI: worse than the closing moneyline (Brier .223 vs .211); any blend makes it worse; siding with FPI
       when it disagrees lost ~5c a bet in both periods -> shown as a second opinion only.
  Practice: QB limited/DNP -3.5c (fit, 0.7 SE), many DNPs +0.4c / -4.7c -> nothing holds; info only.
  Polymarket / volume / news: no free history to test against the timing that matters; we save our own
  history (state/poly_history.json, state/volume_history.json) for a later study, like the Kalshi-lag one.
Never invents data: a feed that fails leaves its slot empty (the card shows "unavailable" in Details).
"""
import csv
import io
import json
import os
import re
from datetime import datetime, timedelta, timezone

from . import config as C
from .fetch import _get, cached, load_json, save_json, iso, HEALTH
from .stats import abbrev

POLY_URL = "https://gamma-api.polymarket.com/events?series_id=12185&closed=false&limit=50&offset={off}"
POLY_TO_ESPN = {"LA": "LAR", "WAS": "WSH", "JAC": "JAX"}
POLY_GAP = 3            # cents: show the Polymarket line only when Robinhood is this far off it
POLY_HIST = os.path.join(C.STATE, "poly_history.json")
NEWS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=50"
NEWS_HOURS = 24
PRACTICE_FILE = os.path.join(C.STATE, "practice.json")
VOL_HIST = os.path.join(C.STATE, "volume_history.json")
FPI_GAP = 10            # pts between ESPN FPI and the price before Details adds a note
MONEY_MOVE = 3          # cents in the last hour
MONEY_SHARE = 0.25      # ...with at least this share of the day's trading in that hour
MONEY_MIN = 5000        # ...and at least this many contracts


def _ct_now(now):
    return now.astimezone(C.CT)


def _dt(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T"))
    except Exception:
        return None


# ---------------- Polymarket ----------------
def _gz_get(url):
    """Gamma serves big pages gzip-only; urllib needs the header and manual unzip."""
    import gzip
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "nfl-bets-assistant/1.0 (personal, read-only)",
                                               "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=25) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
    return json.loads(body)


def poly_index():
    """{frozenset(away, home): {"at": kickoff, away: {...}, home: {...}}} from Polymarket moneyline markets.
    Per team: ask (buy price, cents), mid, vol24. Empty dict if the feed fails."""
    def go():
        out = []
        for off in (0, 50, 100):
            page = _gz_get(POLY_URL.format(off=off))
            if not isinstance(page, list):
                raise ValueError(f"unexpected reply: {str(page)[:120]}")
            for e in page:
                for m in e.get("markets") or []:
                    if m.get("sportsMarketType") == "moneyline" and m.get("slug") == e.get("slug") and not m.get("closed"):
                        out.append({k: m.get(k) for k in ("slug", "outcomes", "outcomePrices", "bestBid", "bestAsk",
                                                          "volume24hr", "gameStartTime")})
            if len(page) < 50:
                break
        return out
    rows, _ = cached("polymarket", "nfl", go)
    idx = {}
    for m in rows or []:
        parts = (m.get("slug") or "").split("-")       # nfl-gb-la-2026-11-26
        if len(parts) < 6 or parts[0] != "nfl":
            continue
        a, h = (POLY_TO_ESPN.get(p.upper(), p.upper()) for p in parts[1:3])
        try:
            bid, ask = float(m["bestBid"]), float(m["bestAsk"])     # first outcome = away team
        except (TypeError, ValueError, KeyError):
            continue
        if not (0 < bid <= ask < 1) or ask - bid > 0.10:
            continue    # no real two-sided market: leave it out rather than guess
        vol = m.get("volume24hr")
        idx[frozenset((a, h))] = {"at": _dt(m.get("gameStartTime")),
                                  a: {"ask": round(ask * 100, 1), "mid": round((bid + ask) * 50, 1), "vol24": vol},
                                  h: {"ask": round((1 - bid) * 100, 1), "mid": round(100 - (bid + ask) * 50, 1), "vol24": vol}}
    return idx


def poly_attach(g, idx, kickoff, now):
    """c['poly'] = {ask, mid} and c['polyLine'] when Robinhood is 3c+ off it. Saves a small history."""
    p = idx.get(frozenset((g["away"], g["home"])))
    if p and kickoff and p.get("at") and abs((p["at"] - kickoff).total_seconds()) > 2 * 86400:
        p = None
    for side in ("away", "home"):
        c = g["teams"][side]
        c["poly"] = c["polyLine"] = None
        if not p or g["state"] == "post":
            continue
        q = p.get(c["team"])
        if not q:
            continue
        c["poly"] = {"ask": q["ask"], "mid": q["mid"]}
        if c.get("price") is None:
            continue
        d = round(c["price"] - q["ask"])
        if abs(d) >= POLY_GAP:
            c["polyLine"] = (f"Polymarket has {c['team']} at {q['ask']:.0f}¢ · Robinhood {abs(d)}¢ "
                             + ("dearer" if d > 0 else "cheaper — Kalshi may be lagging"))
    if p and g["state"] != "post":
        hist = load_json(POLY_HIST, {}) or {}
        a, h = g["teams"]["away"], g["teams"]["home"]
        row = [iso(now), a.get("price"), (a.get("poly") or {}).get("ask"), h.get("price"), (h.get("poly") or {}).get("ask")]
        rows = hist.setdefault(g["id"], [])
        if not rows or rows[-1][1:] != row[1:]:
            rows.append(row)
        cut = iso(now - timedelta(days=60))
        for k in list(hist):
            if not hist[k] or hist[k][-1][0] < cut:
                hist.pop(k, None)
        save_json(POLY_HIST, hist, compact=True)


# ---------------- ESPN FPI (matchup predictor, already in the summary) ----------------
def fpi_attach(g, summary):
    pr = (summary or {}).get("predictor") or {}
    vals = {}
    for k, side in (("homeTeam", "home"), ("awayTeam", "away")):
        try:
            vals[side] = float((pr.get(k) or {}).get("gameProjection"))
        except (TypeError, ValueError):
            pass
    for side in ("away", "home"):
        c = g["teams"][side]
        c["fpi"] = vals.get(side) if len(vals) == 2 else None
        # Details only (never on the card front): FPI lost to the market in the backtest, so a big
        # disagreement is a note, not a signal
        c["fpiNote"] = None
        if c["fpi"] is not None and c.get("price") is not None and g["state"] == "pre" and abs(c["fpi"] - c["price"]) >= FPI_GAP:
            c["fpiNote"] = "far from the price; in tests the market was right more"


# ---------------- ESPN news ----------------
NEWS_RE = re.compile(r"\b(ruled out|out for|won't play|will not play|won't start|will not start|to miss|miss(es)? |"
                     r"inactive|doubtful|questionable|bench(ed|ing)?|to start|will start|starting|start at qb|"
                     r"injur|concussion|torn|placed on ir|suspend|activated|returns?|limited|did not practice|dnp)\b", re.I)


def news_feed(team_ids):
    """team_ids: {espn team id: abbr}. Returns {team: [ {id, at, headline, athletes:[names]} ]} for the last 24h,
    injury / lineup headlines only, newest first. {} if the feed fails."""
    d, _ = cached("espn-news", "nfl", lambda: _get(NEWS_URL, timeout=15, tries=2))
    out = {}
    now = datetime.now(timezone.utc)
    for a in (d or {}).get("articles") or []:
        if a.get("type") == "Media":
            continue        # videos repeat the stories
        at = _dt(a.get("published"))
        text = f"{a.get('headline') or ''} {a.get('description') or ''}"
        if not at or now - at > timedelta(hours=NEWS_HOURS) or not NEWS_RE.search(text):
            continue
        cats = a.get("categories") or []
        teams = {team_ids.get(str(x.get("teamId"))) for x in cats if x.get("type") == "team"} - {None}
        names = [x.get("description") for x in cats if x.get("type") == "athlete" and x.get("description")]
        for t in teams:
            out.setdefault(t, []).append({"id": a.get("id"), "at": iso(at), "headline": (a.get("headline") or "")[:140],
                                          "athletes": names})
    for t in out:
        out[t].sort(key=lambda x: x["at"], reverse=True)
    return out


def news_attach(g, news, tables):
    bm = tables.get("backup_map") or {}
    for side in ("away", "home"):
        c = g["teams"][side]
        items = news.get(c["team"]) or []
        c["news"] = items[:2] or None
        # starting QB named in the story -> marks it for the push
        for it in items:
            it["qb"] = any((bm.get(f"{c['team']}|{abbrev(n)}") or {}).get("pos") == "QB" for n in it["athletes"])


# ---------------- Practice reports (nflverse injuries file, saved daily) ----------------
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHORT = {"Did Not Participate In Practice": "DNP", "Limited Participation in Practice": "Limited",
         "Full Participation in Practice": "Full"}


def practice_update(season, week, now):
    """Download the season's injury/practice file (about every 3 h) and record today's practice status per
    player for this week. Returns the saved {team|player: {...}} for the week, or None if never available."""
    st = load_json(PRACTICE_FILE, {}) or {}
    wk = f"{season}-w{week}"
    if st.get("week") != wk:
        st = {"week": wk, "players": {}, "at": None}
    last = _dt(st.get("at"))
    if last is None or now - last > timedelta(hours=3):
        try:
            body = _get(f"{C.NFLVERSE}/injuries/injuries_{season}.csv", timeout=60, raw=True, tries=2)
            rows = list(csv.DictReader(io.StringIO(body.decode("utf-8", "replace"))))
            day = DAYS[_ct_now(now).weekday()]
            for r in rows:
                if str(r.get("week")) != str(week) or r.get("season_type") not in ("REG", "POST"):
                    continue
                ps = SHORT.get(r.get("practice_status") or "")
                if not ps:
                    continue
                team = C.NFLVERSE_TO_ESPN.get(r["team"], r["team"])
                key = f"{team}|{abbrev(r.get('full_name'))}"
                p = st["players"].setdefault(key, {"name": r.get("full_name"), "pos": r.get("position"), "days": {}})
                p["days"][day] = ps
                p["injury"] = r.get("practice_primary_injury") or r.get("report_primary_injury") or ""
                p["report"] = r.get("report_status") or ""
            st["at"] = iso(now)
            HEALTH.ok("practice")
        except Exception as e:
            HEALTH.fail("practice", e)
            if not st.get("at"):
                save_json(PRACTICE_FILE, st, compact=True)
                return None
        save_json(PRACTICE_FILE, st, compact=True)
    return st["players"]


def practice_attach(g, players, tables):
    """Starters who missed or were limited at practice this week: [{player, pos, line, qb, dnp}]."""
    bm = tables.get("backup_map") or {}
    for side in ("away", "home"):
        c = g["teams"][side]
        if players is None:
            c["practice"] = None       # feed never loaded: Details shows "unavailable"
            continue
        out = []
        for key, p in players.items():
            if not key.startswith(c["team"] + "|") or key not in bm:
                continue
            days = [(d, p["days"][d]) for d in DAYS if d in p["days"]]
            if not any(s in ("DNP", "Limited") for _, s in days):
                continue
            out.append({"player": p["name"], "pos": bm[key].get("pos") or p.get("pos"),
                        "line": ", ".join(f"{s} {d}" for d, s in days),
                        "qb": bm[key].get("pos") == "QB", "dnp": days[-1][1] == "DNP" if days else False,
                        "injury": p.get("injury") or ""})
        out.sort(key=lambda x: (not x["qb"], not x["dnp"]))
        c["practice"] = out


# ---------------- Kalshi money moving ----------------
def volume_attach(g, prices, now):
    """Keep [utc, awayAsk, awayVol, homeAsk, homeVol] per check (lifetime contracts traded); flag a 3c+ move in
    the last hour that came with a big share of the day's trading."""
    if g["state"] == "post":
        return
    hist = load_json(VOL_HIST, {}) or {}
    a, h = g["teams"]["away"], g["teams"]["home"]
    pa, ph = prices.get(a["team"]) or {}, prices.get(h["team"]) or {}
    row = [iso(now), a.get("price"), pa.get("vol"), h.get("price"), ph.get("vol")]
    rows = hist.setdefault(g["id"], [])
    if not rows or rows[-1][1:] != row[1:]:
        rows.append(row)
    cut = iso(now - timedelta(days=21))
    for k in list(hist):
        if not hist[k] or hist[k][-1][0] < cut:
            hist.pop(k, None)
    hist[g["id"]] = rows[-400:]
    save_json(VOL_HIST, hist, compact=True)
    t0 = iso(now - timedelta(minutes=60))
    base = None
    for r in rows:
        if r[0] > t0:
            break
        base = r
    for side, c, pr, i in (("away", a, pa, 1), ("home", h, ph, 3)):
        c["moneyLine"] = None
        if not base or None in (base[i], row[i], base[i + 1], row[i + 1]):
            continue
        move, traded, day = row[i] - base[i], row[i + 1] - base[i + 1], pr.get("vol24")
        if abs(move) >= MONEY_MOVE and traded >= MONEY_MIN and day and traded >= MONEY_SHARE * day:
            c["moneyLine"] = (f"Money moving: {c['team']} {'up' if move > 0 else 'down'} {abs(move):.0f}¢ in the last hour "
                              f"on {traded:,.0f} contracts")


# ---------------- pushes (called from run.py) ----------------
def feed_alerts(board, rs, now, send):
    """One push per item: a news story naming a starting QB, or a starting QB missing practice. First run only
    records what's already there (no flood). Games within 4 days, not final."""
    sent = rs.setdefault("feedSent", {})
    seed = not rs.get("feedSeeded")
    for g in board["games"]:
        if g["state"] == "post":
            continue
        ko = _dt(g.get("kickoff"))
        if g["state"] == "pre" and (not ko or (ko - now).total_seconds() > 4 * 86400):
            continue
        for side in ("away", "home"):
            c = g["teams"][side]
            items = []
            for n in c.get("news") or []:
                if n.get("qb"):
                    items.append((f"news|{n['id']}|{c['team']}", f"News: {n['headline']}"))
            for p in c.get("practice") or []:
                if p["qb"] and p["dnp"]:
                    items.append((f"prac|{g['id']}|{p['player']}|{p['line']}",
                                  f"{c['team']} QB {p['player']} did not practice ({p['line']})"))
            for key, head in items:
                if key in sent:
                    continue
                sent[key] = iso(now)
                if seed:
                    continue
                px = f"{c['team']} {c['price']:.0f}c" if c.get("price") is not None else c["team"]
                send(head[:120], f"{g['short']} · {px}\nInfo only: check the price before you buy.", priority="high")
    rs["feedSeeded"] = True
    if len(sent) > 600:
        rs["feedSent"] = dict(list(sent.items())[-600:])
