"""Expert picks — public pages only (Rick OK'd CBS 2026-11-23; NFL.com robots.txt allows /news/).

Sources
  CBS Sports expert picks table (7 experts): straight-up with the moneyline at pick time, and ATS.
  NFL.com weekly picks article (5 editors): pick, predicted score, the game's moneyline, and one
  editor's written reason per game ("Why X picked the Y").

Every pick is graded with ESPN's final scores (not the sites' own labels) and backtested at the price
the moneyline implied: profit per 1-unit pick, favorites vs underdogs. Experts are ranked by that
profit (ROI) once they have MIN_PICKS graded picks; the top SHOW are shown. Re-ranked every run,
so the list changes as results come in.
Context only: expert picks never move our fair price unless they prove they beat the line.
"""
import html as H
import json
import re
import time
import urllib.request

from . import config as C
from .fetch import load_json, save_json, iso, HEALTH, espn_scoreboard

FILE = f"{C.STATE}/experts.json"
PAST = f"{C.STATE}/experts_past.json"   # earlier seasons (2025 from NFL.com + archived CBS pages), read once
CBS_URL = "https://www.cbssports.com/nfl/picks/experts/{kind}/{week}/"
CBS_KINDS = {"su": "straight-up", "ats": "against-the-spread"}
NFL_URLS = ["https://www.nfl.com/news/nfl-picks-week-{week}-{season}-nfl-season",
            "https://www.nfl.com/news/nfl-week-{week}-picks-upset-and-score-predictions-matchup-breakdowns-for-every-game"]
UA = {"User-Agent": "Mozilla/5.0 (compatible; nfl-bets-assistant/1.0; personal, read-only)"}
FIX = {"WAS": "WSH", "AZ": "ARI", "LA": "LAR"}     # site -> ESPN abbreviations
REFRESH_H = 3              # re-read the current week at most every 3 hours
MIN_PICKS = 40             # graded picks needed before an expert can be ranked
SHOW = 5                   # Rick: narrow to the best 5, keep narrowing as results come in


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "ignore")


def _t(s):
    return FIX.get(s, s)


def _text(s):
    return re.sub(r"\s+", " ", H.unescape(re.sub(r"<[^>]+>", "", s))).strip()


# ---------------- CBS ----------------
def parse_cbs(page):
    first = re.findall(r'AuthorHeadshotAndName-firstName">([^<]*)<', page)
    last = re.findall(r'AuthorHeadshotAndName-lastName">([^<]*)<', page)
    experts = [H.unescape(f"{a} {b}").strip() for a, b in zip(first, last)]
    games = []
    for row in page.split("TableBase-bodyTr")[1:]:
        if not re.search(r'gametracker/[a-z]+/NFL_\d{8}_[A-Z]+@[A-Z]+/', row):
            continue
        abbr = re.findall(r'GameMatchup-teamAbbr">([A-Z]+)<', row)
        if len(abbr) < 2:
            continue
        g = {"away": _t(abbr[0]), "home": _t(abbr[1]), "picks": {}}
        cells = re.findall(r'TableExpertPicks-badge--[a-z]+".*?TableExpertPicks-pick">\s*([A-Z]+)\s*([+-]?[\d.]+|PK|EVEN)?\s*</p>', row, re.S)
        if cells and len(cells) == len(experts):
            for name, (team, line) in zip(experts, cells):
                g["picks"][name] = {"team": _t(team), "line": line or None}
        else:
            for cfg, txt in re.findall(r"class=\"BetButton[^\"]*\"[^>]*data-config='([^']*)'.*?BetButton-text\">\s*([^<]*?)\s*</div>", row, re.S):
                try:
                    name = json.loads(cfg)["meta"]["bets"][0]["expertLabel"]
                except Exception:  # noqa
                    continue
                parts = txt.split()
                if parts:
                    g["picks"][name] = {"team": _t(parts[0]), "line": parts[1] if len(parts) > 1 else None}
        games.append(g)
    return {"experts": experts, "games": games}


# ---------------- NFL.com ----------------
def parse_nfl(page, season, week):
    """-> {"experts": [...], "games": [{away, home, ml: {team: line}, picks: {name: {team, score}}, reasons: {name: text}}]}
    Empty if the page isn't this season/week."""
    parts = page.split(">AUTHOR PICKS<")
    games, experts = [], []
    for i in range(1, len(parts)):
        pre, sec = parts[i - 1][-8000:], parts[i]
        gl = re.findall(rf'nfl\.com/games/[a-z0-9-]+-at-[a-z0-9-]+-{season}-reg-(\d+)', pre)
        if not gl or int(gl[-1]) != int(week):
            continue
        logos = re.findall(r'clubs/logos/([A-Z]+)"', pre)
        if len(logos) < 2:
            continue
        away, home = _t(logos[-2]), _t(logos[-1])
        g = {"away": away, "home": home, "picks": {}, "reasons": {}, "ml": {}}
        ml = re.findall(r'MONEYLINE:\s*</strong>\s*([^<]*)', pre)
        if ml:
            m = re.findall(r'([+-]\d+)', ml[-1])
            if len(m) == 2:
                g["ml"] = {away: m[0], home: m[1]}
        body = sec.split("Why ", 1)
        for name, alt, abbr, score in re.findall(
                r'lg:max-xl:hidden">([^<]+)</span>.*?<img alt="([^"]*)" src="[^"]*clubs/logos/([A-Z]+)".*?Predicted score: ([0-9-]+)',
                body[0], re.S):
            name = H.unescape(name).strip()
            g["picks"][name] = {"team": _t(abbr), "score": score}
            if name not in experts:
                experts.append(name)
        if len(body) > 1:
            m = re.match(r'(\w+) picked the ([^:<]+):(.*?)(?=<h2|>AUTHOR PICKS<|$)', body[1], re.S)
            if m:
                first = m.group(1)
                who = next((n for n in g["picks"] if n.split()[0] == first), None)
                if who:
                    txt = _text(m.group(3))
                    g["reasons"][who] = txt[:600] + ("…" if len(txt) > 600 else "")
        games.append(g)
    return {"experts": experts, "games": games}


# ---------------- fetch / update ----------------
def _fetch_cbs(wk, week):
    for k, kind in CBS_KINDS.items():
        p = parse_cbs(_get(CBS_URL.format(kind=kind, week=week)))
        if p["games"]:
            wk.setdefault("cbs", {})[k] = p
        time.sleep(2)


def _fetch_nfl(wk, season, week):
    for u in NFL_URLS:
        try:
            p = parse_nfl(_get(u.format(week=week, season=season)), season, week)
        except Exception:  # noqa  (404 for the other slug)
            p = None
        time.sleep(2)
        if p and p["games"]:
            wk["nfl"] = p
            return


def _results(season, week):
    sb, _ = espn_scoreboard(week=week, season=season)
    out = {}
    for ev in (sb or {}).get("events", []):
        if ev["status"]["type"]["state"] != "post":
            continue
        comp = ev["competitions"][0]
        t = {c["homeAway"]: (c["team"]["abbreviation"], int(c.get("score") or 0)) for c in comp["competitors"]}
        (a, sa), (h, sh) = t["away"], t["home"]
        out[f"{a}@{h}"] = a if sa > sh else h if sh > sa else "TIE"
    return out


def update(season, week, now, rs):
    """Backfill weeks 1..week once; re-read the current week every REFRESH_H hours and last week until graded."""
    st = load_json(FILE, {}) or {}
    if st.get("season") != season:
        st = {"season": season, "weeks": {}, "results": {}}
    st.setdefault("results", {})
    at = rs.setdefault("expertsAt", {})
    for w in range(1, int(week) + 1):
        key = f"{season}-w{w}"
        wk = st["weeks"].setdefault(key, {})
        res = st["results"].get(key) or {}
        n_games = len(((wk.get("cbs") or {}).get("su") or {}).get("games", []))
        graded = n_games and len(res) >= n_games
        if w < week and wk.get("cbs") and (graded or w < week - 1):
            if not wk.get("nfl") and not wk.get("nflTried"):
                try:
                    _fetch_nfl(wk, season, w)
                except Exception as e:  # noqa
                    HEALTH.fail("nfl-experts", e)
                wk["nflTried"] = True
            continue
        if w == week and at.get(key) and (now.timestamp() - at[key]) < REFRESH_H * 3600:
            continue
        try:
            _fetch_cbs(wk, w)
            HEALTH.ok("cbs-experts")
        except Exception as e:  # never block the board
            HEALTH.fail("cbs-experts", e)
        try:
            _fetch_nfl(wk, season, w)
            HEALTH.ok("nfl-experts")
        except Exception as e:
            HEALTH.fail("nfl-experts", e)
        try:
            st["results"][key] = _results(season, w)
        except Exception as e:
            HEALTH.fail("expert-results", e)
        at[key] = now.timestamp()
    st["stats"] = stats(st)
    st["at"] = iso(now)
    save_json(FILE, st, compact=True)
    return st


# ---------------- backtest ----------------
def ml_price(line):
    """American moneyline -> price in cents (vig included: what a bettor actually paid)."""
    try:
        x = float(line)
    except (TypeError, ValueError):
        return None
    return 100 * -x / (-x + 100) if x < 0 else 100 * 100 / (x + 100)


def picks(st):
    """Every straight-up pick with the moneyline price of the picked side and of the other side."""
    out = []
    for key, wk in (st.get("weeks") or {}).items():
        su = ((wk.get("cbs") or {}).get("su") or {}).get("games", [])
        nfl = (wk.get("nfl") or {}).get("games", [])
        lines = {}
        for g in su:
            for p in g["picks"].values():
                if p.get("line"):
                    lines[(g["away"], g["home"], p["team"])] = p["line"]
        for g in nfl:
            for t, l in g.get("ml", {}).items():
                lines.setdefault((g["away"], g["home"], t), l)
        for src, games in (("CBS", su), ("NFL.com", nfl)):
            for g in games:
                for name, p in g["picks"].items():
                    other = g["home"] if p["team"] == g["away"] else g["away"]
                    out.append({"week": key, "expert": name, "source": src, "away": g["away"], "home": g["home"],
                                "team": p["team"], "price": ml_price(lines.get((g["away"], g["home"], p["team"]))),
                                "oppPrice": ml_price(lines.get((g["away"], g["home"], other)))})
    return out


def _blank():
    return {"n": 0, "w": 0, "priced": 0, "profit": 0.0, "fav": [0, 0, 0.0], "dog": [0, 0, 0.0]}


def _add(s, price, win):
    s["n"] += 1
    s["w"] += win
    if price is None:
        return
    pnl = (100 - price) / price if win else -1.0
    s["priced"] += 1
    s["profit"] += pnl
    b = s["fav" if price >= 50 else "dog"]
    b[0] += 1
    b[1] += win
    b[2] += pnl


def _finish(s):
    s["pct"] = round(100 * s["w"] / s["n"], 1) if s["n"] else None
    s["roi"] = round(100 * s["profit"] / s["priced"], 1) if s["priced"] else None
    s["profit"] = round(s["profit"], 2)
    for k in ("fav", "dog"):
        s[k][2] = round(s[k][2], 2)
    if s.get("impliedSum") is not None and s["priced"]:
        s["implied"] = round(s.pop("impliedSum") / s["priced"], 1)
    return s


def stats(st):
    """Per expert: W-L, favorites vs underdogs (picks, wins, units), profit per 1-unit pick (ROI) at the
    listed moneyline. Baselines: always the favorite / always the underdog. 'Experts agree': every
    expert (8+) on one side — does it win more than its price says?"""
    past = (load_json(PAST, {}) or {}).get("seasons") or {}
    allw, res = {}, {}
    for ps in past.values():
        allw.update(ps.get("weeks") or {})
        res.update(ps.get("results") or {})
    allw.update(st.get("weeks") or {})
    res.update(st.get("results") or {})
    ex, base, agree, seen, by_game = {}, {"fav": _blank(), "dog": _blank()}, {}, set(), {}
    for p in picks({"weeks": allw}):
        r = (res.get(p["week"]) or {}).get(f"{p['away']}@{p['home']}")
        if r is None or r == "TIE":
            continue
        win = r == p["team"]
        s = ex.setdefault(p["expert"], dict(_blank(), source=p["source"], byWeek={}))
        _add(s, p["price"], win)
        ss = s.setdefault("bySeason", {}).setdefault(p["week"].split("-")[0], _blank())
        _add(ss, p["price"], win)
        bw = s["byWeek"].setdefault(p["week"], [0, 0])
        bw[0] += 1
        bw[1] += win
        g = (p["week"], p["away"], p["home"])
        by_game.setdefault(g, []).append((p, r))
        if g not in seen and p["price"] is not None and p["oppPrice"] is not None:
            seen.add(g)
            other = p["home"] if p["team"] == p["away"] else p["away"]
            for team, pr in ((p["team"], p["price"]), (other, p["oppPrice"])):
                _add(base["fav" if pr >= 50 else "dog"], pr, r == team)
    for g, ps in by_game.items():
        if len(ps) < 8:
            continue
        r = ps[0][1]
        votes = {}
        for p, _ in ps:
            votes[p["team"]] = votes.get(p["team"], 0) + 1
        maj = max(votes, key=votes.get)
        tag = "all" if len(votes) == 1 else "split"
        price = next((p["price"] for p, _ in ps if p["team"] == maj and p["price"] is not None), None)
        a = agree.setdefault(tag, dict(_blank(), impliedSum=0.0))
        _add(a, price, r == maj)
        if price is not None:
            a["impliedSum"] += price
    for s in list(ex.values()) + list(base.values()) + list(agree.values()):
        _finish(s)
        for v in (s.get("bySeason") or {}).values():
            _finish(v)
    cur = str(st.get("season") or "")
    ranked = sorted([n for n, s in ex.items() if s["n"] >= MIN_PICKS and s["roi"] is not None
                     and (not cur or cur in (s.get("bySeason") or {}))],      # still picking this season
                    key=lambda n: (-ex[n]["roi"], -ex[n]["pct"]))
    for i, n in enumerate(ranked):
        ex[n]["rank"] = i + 1
    # underdog experts: of the top SHOW, the 3 with the most underdog profit (8+ underdog picks)
    dogs = sorted([n for n in ranked[:SHOW] if ex[n]["dog"][0] >= 8], key=lambda n: -ex[n]["dog"][2])[:3]
    dg = _blank()
    for g, ps in by_game.items():
        for p, r in ps:
            if p["expert"] in dogs and p["price"] is not None and p["price"] < 50:
                _add(dg, p["price"], r == p["team"])
                break    # one bet per underdog pick, even if two of them made it
    _finish(dg)
    return {"experts": ex, "baseline": base, "agree": agree, "top": ranked[:SHOW], "count": len(ex),
            "dogExperts": dogs, "dogGroup": dg,
            "seasons": sorted({k.split("-")[0] for k in allw}),
            "sources": ["CBS Sports expert picks", "NFL.com weekly picks"] + (["2025 CBS pages via the Internet Archive"] if past else [])}


# ---------------- board ----------------
def for_board(st, games):
    """Attach the top experts' picks (and any written reason) to each game this week."""
    stt = st.get("stats") or {}
    top, ex = stt.get("top") or [], stt.get("experts") or {}
    weeks = sorted((st.get("weeks") or {}).items(), key=lambda kv: int(kv[0].split("-w")[1]))
    if not weeks:
        return
    cur = weeks[-1][1]
    idx = {}
    for k, src in (("su", ((cur.get("cbs") or {}).get("su") or {})), ("ats", ((cur.get("cbs") or {}).get("ats") or {})),
                   ("nfl", (cur.get("nfl") or {}))):
        for g in src.get("games", []):
            idx.setdefault((g["away"], g["home"]), {})[k] = g
    for g in games:
        a, h = g["teams"]["away"]["team"], g["teams"]["home"]["team"]
        m = idx.get((a, h))
        if not m:
            continue
        allp = {}
        for k in ("su", "nfl"):
            for n, p in ((m.get(k) or {}).get("picks") or {}).items():
                allp[n] = p["team"]
        nfl = m.get("nfl") or {}
        rows = []
        for n in top:
            if n not in allp:
                continue
            ats = ((m.get("ats") or {}).get("picks") or {}).get(n)
            s = ex.get(n, {})
            rows.append({"name": n, "rank": s.get("rank"), "team": allp[n], "roi": s.get("roi"), "pct": s.get("pct"),
                         "ats": ats and f"{ats['team']} {ats.get('line') or ''}".strip(),
                         "score": ((nfl.get("picks") or {}).get(n) or {}).get("score")})
        cnt = {t: sum(1 for v in allp.values() if v == t) for t in (a, h)}
        sp = g.get("spreadHome")
        dog = None if sp in (None, 0) else (a if sp < 0 else h)
        dpk = [n for n in (stt.get("dogExperts") or []) if dog and allp.get(n) == dog]
        g["experts"] = {"top": rows, "count": cnt, "n": len(allp), "dog": dog, "dogPicks": dpk,
                        "reasons": [{"name": n, "team": allp.get(n), "text": t} for n, t in (nfl.get("reasons") or {}).items()],
                        "agree": next((t for t, c in cnt.items() if c == len(allp) and c >= 8), None)}


def tag_legs(board):
    """'Experts agree' tag on combo legs whose team every expert picked (tag only: in 2026 Weeks 1-11
    unanimous picks won about what their price said, so they don't change the combo search)."""
    agree = {(g["id"], g["experts"]["agree"]) for g in board.get("games", []) if (g.get("experts") or {}).get("agree")}
    if not agree:
        return
    cb = board.get("combos") or {}
    legs = list(cb.get("pool") or [])
    for cat in ("standard", "combined", "safer"):
        for r in (cb.get(cat) or {}).values():
            for k in ("combo", "closest"):
                legs += (r.get(k) or {}).get("legs", [])
    for l in legs:
        if (l.get("gameId"), l.get("team")) in agree and "Experts agree" not in l.setdefault("tags", []):
            l["tags"].append("Experts agree")


def public(st):
    s = st.get("stats") or {}
    rows = [{"name": n, "source": v.get("source"), "rank": v.get("rank"), "w": v["w"], "n": v["n"], "pct": v["pct"],
             "roi": v["roi"], "fav": v["fav"], "dog": v["dog"],
             "bySeason": {k: {"n": x["n"], "w": x["w"], "roi": x["roi"], "dog": x["dog"]} for k, x in (v.get("bySeason") or {}).items()}} for n, v in (s.get("experts") or {}).items()]
    rows.sort(key=lambda r: (r["rank"] or 99, -(r["roi"] or -99)))
    return {"table": rows, "top": s.get("top"), "dogExperts": s.get("dogExperts"), "dogGroup": s.get("dogGroup"), "baseline": s.get("baseline"), "agree": s.get("agree"), "seasons": s.get("seasons"),
            "sources": s.get("sources"), "at": st.get("at"), "minPicks": MIN_PICKS}


def _results_nflverse(season, week):
    """Final scores from nflverse games.csv (ESPN's scoreboard only serves the current season reliably)."""
    from .form import games
    T = games()
    T = T[(T.season == season) & (T.week == week) & ~T.home & T.result.notna()]
    return {f"{r.team}@{r.opp}": (r.team if r.pf > r.pa else r.opp if r.pa > r.pf else "TIE") for r in T.itertuples()}


def build_past(src, season):
    """One-time: parse saved 2025 pages (NFL.com articles + archived CBS tables) and grade with ESPN scores."""
    import os
    out = {"weeks": {}, "results": {}}
    pages = {w: open(os.path.join(src, f"nfl-{w}.html"), encoding="utf-8", errors="ignore").read()
             for w in range(1, 19) if os.path.exists(os.path.join(src, f"nfl-{w}.html"))}
    nfl25 = parse_nfl_2025(pages)
    for w in range(1, 19):
        key = f"{season}-w{w}"
        wk = {}
        for k, kind in CBS_KINDS.items():
            f = os.path.join(src, f"cbs-{kind}-{w}.html")
            if os.path.exists(f):
                p = parse_cbs(open(f, encoding="utf-8", errors="ignore").read())
                if p["games"]:
                    wk.setdefault("cbs", {})[k] = p
        p = parse_nfl(pages[w], season, w) if w in pages else {"games": []}
        if not p["games"]:
            p = nfl25.get(w) or {"games": []}
        if p["games"]:
            wk["nfl"] = p
        if wk:
            out["weeks"][key] = wk
            out["results"][key] = _results_nflverse(season, w)
    st = load_json(PAST, {}) or {}
    st.setdefault("seasons", {})[str(season)] = out
    st["at"] = iso()
    save_json(PAST, st, compact=True)
    return out


def parse_nfl_2025(pages):
    """2025 NFL.com layout: each editor's pick is a team-logo image with an opaque id. Learn id -> team from
    the games each id appears in (a logo only ever shows up in its own team's games), then read the picks.
    pages: {week: html} -> {week: {"experts": [...], "games": [...]}}"""
    from .odds import FULL
    nick = {k.split()[-1]: v for k, v in FULL.items()}
    raw, cand = {}, {}
    for w, page in pages.items():
        authors = {n.split()[0]: n for n in (H.unescape(x).strip() for x in re.findall(r'/author/[^"]+"[^>]*>([^<]+)<', page))}
        secs = page.split("MONEYLINE:")
        out = []
        for i in range(1, len(secs)):
            pre, sec = re.sub(r"<[^>]+>", "|", secs[i - 1][-3000:]), secs[i]
            names = re.findall(r"\|(" + "|".join(re.escape(k) for k in FULL) + r")\|", pre)
            if len(names) < 2:
                continue
            away, home = FULL[names[-2]], FULL[names[-1]]
            mt = re.sub(r"<[^>]+>", " ", sec[:300]).replace("\u2212", "-").split("SPREAD")[0]
            ml = {}
            for nk, v in re.findall(r"([A-Za-z0-9]+)\s*([+-]\d+|EVEN|PK)", mt):
                if nick.get(nk) in (away, home):
                    ml[nick[nk]] = "+100" if v in ("EVEN", "PK") else v
            tb = sec.split("</table>")[0]
            heads = [H.unescape(x).strip() for x in re.findall(r'<th[^>]*>([^<]+)</th>', tb)]
            ids = re.findall(r'<td.*?league/([a-z0-9]+)"', tb, re.S)
            if not heads or len(ids) != len(heads):
                continue
            g = {"away": away, "home": home, "ml": ml if len(ml) == 2 else {}, "ids": dict(zip(heads, ids)),
                 "reasons": {}, "authors": authors}
            m = re.search(r"Why (\w+) picked the ([^:<]+):</strong>(.*?)(?=MONEYLINE:|$)", sec, re.S)
            if m:
                txt = _text(m.group(3).split("<table")[0])
                g["reasons"][authors.get(m.group(1), m.group(1))] = txt[:600] + ("…" if len(txt) > 600 else "")
                t = nick.get(m.group(2).strip().split()[-1])
                who = g["ids"].get(m.group(1))
                if t and who:
                    cand.setdefault(who, []).append({t})      # a known pick pins the logo
            for x in set(ids):
                cand.setdefault(x, []).append({away, home})
            out.append(g)
        raw[w] = out
    logo = {}
    for x, sets in cand.items():
        s = set.intersection(*sets)
        if len(s) == 1:
            logo[x] = s.pop()
    res = {}
    for w, out in raw.items():
        ex, games = [], []
        for g in out:
            picks = {}
            for first, x in g["ids"].items():
                t = logo.get(x)
                if t in (g["away"], g["home"]):
                    name = g["authors"].get(first, first)
                    picks[name] = {"team": t}
                    if name not in ex:
                        ex.append(name)
            games.append({"away": g["away"], "home": g["home"], "ml": g["ml"], "picks": picks, "reasons": g["reasons"]})
        res[w] = {"experts": ex, "games": games}
    return res
