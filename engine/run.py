"""Scheduler + jobs. GitHub Actions calls `python -m engine.run tick` every 10 minutes; the tick
decides (in America/Chicago time, DST-safe) which jobs are due:

  nfl-pregame-weekly   Thu 12:00 CT        full pregame refresh + nflverse tables + Thursday baseline
  inactives            every game day, 90 min before the first kickoff: rebuild backup_map
  game-day alert       every game day 11:00 CT (90 min before kickoff if a game starts before 11:30): one push with
                       A picks, any Buys, top combo under 10c (Rick: 11 AM). Wed/Fri/Sat/Mon/holiday/playoff days too.
  nfl-live-sunday      every 10 min while games are live (any day)
  nfl-window-early     Sun 15:35 CT        early window review (also auto when the window's last game is final)
  nfl-window-late      Sun 18:50 CT
  nfl-window-snf       Sun 23:00 CT
  nfl-learning-monday  Mon 23:45 CT        full weekly learning review after MNF
  light refresh        hourly otherwise    prices/injuries/weather for the board
"""
import os
import sys
from datetime import datetime, timedelta, timezone

from . import board as B
from . import config as C
from . import learning as LR
from . import push as P
from .backtest import run as run_backtest
from .fetch import load_json, save_json, iso, now_utc, HEALTH
from .stats import build_tables, load_tables

RUN = os.path.join(C.STATE, "run.json")
TOP_FILE = os.path.join(C.DOCS_DATA, "board.json")
LEARN_PUB = os.path.join(C.DOCS_DATA, "learning.json")
BT_FILE = os.path.join(C.STATE, "backtest.json")


def ct(now):
    return now.astimezone(C.CT)


def _nflverse_files(season):
    """Download games.csv (daily), play-by-play this + last season, snap counts and player weeks
    (every 3 days) when missing or stale. Kept between runs by the feed cache."""
    import time
    from .fetch import nflverse_csv
    d = os.path.join(C.CACHE, "nflverse")
    need = [("schedules", "games.csv", 1), ("pbp", f"play_by_play_{season}.csv.gz", 3),
            ("pbp", f"play_by_play_{season - 1}.csv.gz", 60), *[("pbp", f"play_by_play_{y}.csv.gz", 365) for y in range(2021, season - 1)],
            ("snap_counts", f"snap_counts_{season}.csv.gz", 3),
            ("stats_player", f"stats_player_week_{season}.csv.gz", 3)]
    for tag, f, days in need:
        p = os.path.join(d, f)
        if not os.path.exists(p) or time.time() - os.path.getmtime(p) > days * 86400:
            nflverse_csv(tag, f)


DIGEST_AT = 11 * 60     # game-day morning alert, 11:00 AM Central (Rick, 2026-11-25)
GAP_PUSH = 8            # cents: sportsbooks' win % above Robinhood's price -> one "Gap" push


def game_days(kickoffs):
    """{'YYYY-MM-DD' (Central): first kickoff that day in minutes after midnight} from kickoff datetimes."""
    days = {}
    for k in kickoffs or ():
        if not k:
            continue
        t = ct(k)
        d, m = t.strftime("%Y-%m-%d"), t.hour * 60 + t.minute
        days[d] = min(days.get(d, m), m)
    return days


def digest_at(first_kick):
    """Game-day alert time: 11 AM; if the first game starts before 11:30 (London, early holiday games),
    90 minutes before it instead."""
    return DIGEST_AT if first_kick >= DIGEST_AT + 30 else max(0, first_kick - 90)


def due_jobs(now, rs, sb_live, week_key, force=(), kickoffs=None):
    t = ct(now)
    wd, hm, date = t.weekday(), t.hour * 60 + t.minute, t.strftime("%Y-%m-%d")
    jobs = set(force)
    if (wd == 3 and hm >= 12 * 60 and rs.get("pregame") != week_key) or not load_tables().get("ok") \
            or load_tables().get("week") != int(week_key.split("-w")[1]):
        jobs.add("pregame")
    if kickoffs is None:   # no schedule passed (old callers): the classic Thursday / Sunday slots
        if wd == 6 and hm >= 10 * 60 + 30 and rs.get("inactives") != date:
            jobs.add("inactives")
        if wd in (3, 6) and DIGEST_AT <= hm < DIGEST_AT + 3 * 60 and rs.get("top3") != date:
            jobs.add("top3")
    else:                  # every day that has a game (Wed, Thu, Fri, Sat, Sun, Mon, holidays, playoffs)
        first = game_days(kickoffs).get(date)
        if first is not None:
            if hm >= first - 90 and rs.get("inactives") != date:
                jobs.add("inactives")
            at = digest_at(first)
            if at <= hm < min(at + 3 * 60, first) and rs.get("top3") != date:
                jobs.add("top3")
    for name, at in (("early", 15 * 60 + 35), ("late", 18 * 60 + 50), ("snf", 23 * 60)):
        if wd == 6 and hm >= at and rs.get(f"window-{name}") != date:
            jobs.add(f"window-{name}")
    season, wk = week_key.split("-w")
    prev_key = f"{season}-w{int(wk) - 1}"
    if ((wd == 0 and hm >= 23 * 60 + 45) or wd in (1, 2)) and rs.get("weekly") not in (week_key, prev_key):
        jobs.add("weekly-check")
    jobs.add("board")   # every tick: prices and calls are never more than one loop (6-10 min) old
    return jobs


def any_live(sb, now):
    for ev in (sb or {}).get("events", []):
        st = ev["status"]["type"]["state"]
        if st == "in":
            return True
        k = B.parse_dt(ev.get("date"))
        if st == "pre" and k and timedelta(0) <= k - now <= timedelta(minutes=20):
            return True
    return False


def next_check(now, kickoffs=None):
    """Next scheduled check, for empty-state hints."""
    t = ct(now)
    slots = [(3, 12, 0, "Thu 12pm"), (6, 15, 35, "Sun 3:35pm"),
             (6, 18, 50, "Sun 6:50pm"), (6, 23, 0, "Sun 11pm"), (0, 23, 45, "Mon 11:45pm")]
    if kickoffs is None:
        slots += [(6, 11, 0, "Sun 11am"), (6, 10, 30, "Sun 10:30am"), (3, 11, 0, "Thu 11am")]
    best = None
    for d, first in game_days(kickoffs).items():   # game-day alert on every real game day
        at = digest_at(first)
        cand = t.replace(year=int(d[:4]), month=int(d[5:7]), day=int(d[8:]), hour=at // 60, minute=at % 60, second=0, microsecond=0)
        if cand > t and (best is None or cand < best[0]):
            best = (cand, cand.strftime("%a ") + cand.strftime("%I:%M%p").lstrip("0").replace(":00", "").lower())
    for wd, h, m, label in slots:
        d = (wd - t.weekday()) % 7
        cand = (t + timedelta(days=d)).replace(hour=h, minute=m, second=0, microsecond=0)
        if cand <= t:
            cand += timedelta(days=7)
        if best is None or cand < best[0]:
            best = (cand, label)
    return f"Next check: {best[1]}"


def _grade(p):
    return next((g for lo, g in ((85, "A+"), (75, "A"), (60, "B"), (45, "C")) if p is not None and p >= lo), "F")


def top3_message(board, now=None):
    """Game-day morning alert: games kicking off today (Central), A/A+ picks, any Buys, the top combo under 10c."""
    now = now or datetime.now(timezone.utc)
    today = ct(now).strftime("%Y-%m-%d")
    todays = {g["id"] for g in board["games"] if g.get("state") == "pre" and B.parse_dt(g.get("kickoff"))
              and ct(B.parse_dt(g["kickoff"])).strftime("%Y-%m-%d") == today}
    calls = [c for c in board["calls"] if c.get("gameId") in todays and c.get("price") is not None
             and not c.get("priceStale") and not c.get("dataHold")]
    lines = []
    for c in sorted([c for c in calls if c.get("call") == "Value"], key=lambda c: -(c.get("edge") or 0)):
        lines.append(f"BUY {c['team']} {c['price']:.0f}c -> win {100 - c['price']:.0f}c · {_grade(c.get('fair'))}")
    aa = sorted([c for c in calls if (c.get("fair") or 0) >= 75 and c.get("call") != "Value"], key=lambda c: -c["fair"])
    if aa:
        lines.append("A picks: " + ", ".join(f"{c['team']} {_grade(c['fair'])} {c['price']:.0f}c" for c in aa))
    for c in calls:
        if c.get("call") == "Wait" and c.get("buyAt"):
            lines.append(f"Wait {c['team']}: buy at {c['buyAt']}c (now {c['price']:.0f}c)")
    cheap = ((board.get("topCombos") or {}).get("thisWeek") or {}).get("cheap") or []
    if cheap:
        k = cheap[0]
        lines.append(f"Top combo under 10c: {'+'.join(l['team'] for l in k['legs'])} ~{k['cost']:.0f}c · hits 1 in {k.get('oneIn', '?')}")
    if lines and todays:
        lines.insert(0, f"{len(todays)} game{'s' if len(todays) > 1 else ''} today")
    return lines if todays else []


def gap_alerts(board, rs):
    """Idea 9: sportsbooks (3+ books, Odds API) give a team 8c+ more than Robinhood's price -> one push per team per price."""
    sent = rs.setdefault("gapSent", {})
    for c in board["calls"]:
        gap = c.get("bookGap")
        if c.get("state") != "pre" or gap is None or gap < GAP_PUSH or c.get("priceStale") or c.get("dataHold"):
            continue
        if sent.get(c["key"]) == round(c["price"]):
            continue
        P.send(f"Gap: {c['team']} {c['price']:.0f}c vs books {c['bookP']:.0f}%",
               f"{c['team']} vs {c['opp']}: sportsbooks give {c['bookP']:.0f}% but Robinhood sells it at {c['price']:.0f}c "
               f"({gap:.0f}c cheaper). Check the price in Robinhood. Call: {'Buy' if c.get('call') == 'Value' else c.get('call')}")
        sent[c["key"]] = round(c["price"])
    if len(sent) > 200:
        rs["gapSent"] = dict(list(sent.items())[-200:])


RECHECK_S = 60


def recheck(cands, board, wait=RECHECK_S):
    """Buy pushes fire only if, about a minute later on freshly fetched data, the Kalshi ask is no higher
    (+1c) and the game hasn't changed: same sportsbook line pregame, same score and quarter live.
    If the re-fetch fails, nothing is sent this tick (it tries again next tick). Returns the keys still good."""
    if not cands:
        return set()
    import time
    from .fetch import _get
    time.sleep(wait)
    try:
        evs = {e["id"]: e for e in (_get(C.ESPN_SCOREBOARD, tries=2) or {}).get("events", [])}
    except Exception as e:
        print("recheck: scoreboard failed", e)
        return set()
    games = {g["id"]: g for g in board["games"]}
    ok = set()
    for c in cands:
        try:
            m = (_get(f"{C.KALSHI_BASE}/markets/{c['ticker']}", tries=2) or {}).get("market") or {}
            ask = round(float(m.get("yes_ask_dollars")) * 100, 2)
        except Exception as e:
            print("recheck: kalshi failed", c.get("key"), e)
            continue
        g, ev = games.get(c.get("gameId")), evs.get(c.get("gameId"))
        if not g or not ev or ask <= 0 or ask > (c["price"] or 0) + 1:
            continue
        comp = ev["competitions"][0]
        if c.get("state") == "pre":
            o = (comp.get("odds") or [{}])[0] or {}
            if g.get("espnSpread") is not None and o.get("spread") is not None and abs(float(o["spread"]) - g["espnSpread"]) >= 0.5:
                continue
        else:
            sc = {t["homeAway"]: str(t.get("score")) for t in comp["competitors"]}
            if sc.get("away") != str(g["score"]["away"]) or sc.get("home") != str(g["score"]["home"]) \
                    or (ev.get("status") or {}).get("period") != g.get("period"):
                continue
        ok.add(c["key"])
    return ok


def feed_notes(board, health):
    """Tell Rick about a feed problem ONLY when it affects a current bet."""
    notes = []
    active = [c for c in board["calls"] if c.get("state") in ("pre", "in")]
    if not active:
        return notes
    st = board.get("feedsStale") or {}
    if st.get("kalshi"):
        notes.append(f"Prices from last good update ({_ago(health.get('kalshi', {}).get('lastOk'))}) — price feed down")
    if st.get("espn"):
        notes.append(f"Scores/odds from last good update ({_ago(health.get('espn', {}).get('lastOk'))})")
    if st.get("weather") and any(g["state"] != "post" and not g["indoor"] for g in board["games"]):
        notes.append("Weather from last good update")
    return notes


def _ago(s):
    if not s:
        return "earlier"
    d = now_utc() - datetime.fromisoformat(s.replace("Z", "+00:00"))
    m = int(d.total_seconds() // 60)
    return f"{m}m ago" if m < 120 else f"{m // 60}h ago"


def weekly_banner(board, L):
    """After MNF: weekly results at the very top until TNF of the next week starts."""
    if not L["weekly"]:
        return None
    w = L["weekly"][-1]
    if w["season"] != board["season"]:
        return None
    started = any(g["state"] != "pre" for g in board["games"])
    if board["week"] == w["week"] or (board["week"] == w["week"] + 1 and not started):
        return {"label": f"{B.week_label(w['week'])}: {w['w']}–{w['l']} · {w['acc']:.0f}%", "week": w["week"], **w}
    return None


def retest_rules(season, week):
    """Section 9/10 re-test rules: if key WR rest-of-game swing stays <= -3.0 with n>=16, raise the
    WR base to -2.5. Otherwise keep the shrunk bases. Logged in state/overrides.json."""
    from .injury_history import build as build_hist
    h = build_hist(season, week + 1) or {}
    wr = ((h.get("byPosition") or {}).get("WR") or {}).get("key") or {}
    ov = load_json(C.OVERRIDES, {}) or {}
    note = f"Week {week} re-test: key WR n={wr.get('n')}, rest-of-game {wr.get('swing')}"
    if (wr.get("n") or 0) >= 16 and wr.get("swing") is not None and wr["swing"] <= -3.0:
        ov.setdefault("basePos", {})["WR"] = -2.5
        note += " -> WR base raised to -2.5"
    else:
        note += " -> bases unchanged"
    ov["note"] = note
    ov["at"] = iso()
    save_json(C.OVERRIDES, ov)


SWING_LOG = os.path.join(C.STATE, "swing_log.json")


def swing_alerts(board, rs, now, thr=15.0):
    """Big swing: ESPN's live win % moved 15+ points since the last check (about 6 min). Info only,
    never a Buy: the push shows ESPN's new number next to the Kalshi price so Rick can look before
    the price moves. Past seasons (engine/drive_study.py): after a late big swing the team that
    gained won ~4 pts less often than the new win % said; too small and too model-specific to act
    on, so every alert is logged in state/swing_log.json and graded when the game ends."""
    last = rs.setdefault("wpLast", {})
    log = load_json(SWING_LOG, []) or []
    by = {g["id"]: g for g in board["games"]}
    for e in log:                                    # grade finished games
        g = by.get(e["gameId"])
        if e.get("won") is None and g and g["state"] == "post" and g.get("score"):
            a, h = g["score"].get("away") or 0, g["score"].get("home") or 0
            if a != h:
                e["won"] = int((h > a) == (e["team"] == g["home"]))
    for g in board["games"]:
        if g["state"] != "in":
            last.pop(g["id"], None)
            continue
        ha, aw = g["teams"]["home"], g["teams"]["away"]
        wp = ha.get("espnWP")
        if wp is None:
            continue
        prev = last.get(g["id"])
        last[g["id"]] = wp
        if prev is None or abs(wp - prev) < thr:
            continue
        gain, lose = (ha, aw) if wp > prev else (aw, ha)
        gf, gt = (prev, wp) if gain is ha else (100 - prev, 100 - wp)
        log.append({"t": iso(now), "gameId": g["id"], "game": g["short"], "q": g.get("period"), "clock": g.get("clock"),
                    "team": gain["team"], "from": round(gf), "to": round(gt), "kalshi": gain.get("price"), "won": None})
        if any(c.get("priceStale") or c.get("alertsOff") for c in (ha, aw)):
            continue
        kp = " · ".join(f"{c['team']} {c['price']:.0f}c" for c in (gain, lose) if c.get("price") is not None)
        P.send(f"Big swing: {gain['team']} {gf:.0f}% -> {gt:.0f}%"[:120],
               f"{g['short']} · ESPN win chance moved {abs(wp - prev):.0f} pts since the last check.\n"
               f"Kalshi: {kp or 'no price'}. Info only: check the price before it moves.")
    save_json(SWING_LOG, log[-500:])


def news_alerts(board, rs, now):
    """Buzz the moment a starter is ruled out (pregame report / inactives) or confirmed out
    in-game, or the QB changes — so Rick can act before the price catches up. One push each.
    First run only records what is already known (no flood of old news)."""
    sent = rs.setdefault("newsSent", {})
    seed = not rs.get("newsSeeded")
    by = {(c["gameId"], c["team"]): c for c in board["calls"]}
    def px(team, gid):
        c = by.get((gid, team)) or {}
        fair = c.get("liveFair") if c.get("state") == "in" else c.get("fair")
        return f"{team} {c['price']:.0f}c (fair {fair:.0f}c)" if c.get("price") is not None and fair is not None else team
    for g in board["games"]:
        if g["state"] == "post":
            continue
        opp = lambda t: g["home"] if t == g["away"] else g["away"]  # noqa
        items = []
        if g["state"] == "pre":
            ko = board_dt(g.get("kickoff"))
            if ko and (ko - now).total_seconds() < 4 * 86400:
                for i in g.get("injuries") or []:
                    if i.get("starter") and i.get("status") in ("Out", "Doubtful"):
                        items.append((f"{g['id']}|{i['team']}|{i['player']}|{i['status']}", i["team"],
                                      f"{i['team']} {i['pos']} {i['player']} {i['status'].upper()}"))
        else:
            for side in ("away", "home"):
                c = g["teams"][side]
                for ln in c.get("liveLines") or []:
                    if ln.get("kind") == "inj" or (ln.get("kind") == "pause" and "QB change" in ln.get("text", "")):
                        items.append((f"{g['id']}|{c['team']}|{ln['text']}", c["team"], f"{c['team']}: {ln['text']}"))
        for key, team, head in items:
            if key in sent:
                continue
            sent[key] = iso(now)
            if seed:
                continue
            P.send(f"News: {head}"[:120], f"{g['short']} · {px(team, g['id'])} · {px(opp(team), g['id'])}\n"
                   "Price may not have caught up yet.", priority="high")
    rs["newsSeeded"] = True
    if len(sent) > 600:
        rs["newsSent"] = dict(list(sent.items())[-600:])


def board_dt(s):
    from .board import parse_dt
    return parse_dt(s)


def tick(force=()):
    now = now_utc()
    rs = load_json(RUN, {}) or {}
    sb, _ = B.current_scoreboard()
    if not sb:
        HEALTH.save()
        print("scoreboard unavailable; nothing to do")
        return
    season = (sb.get("season") or {}).get("year")
    week = (sb.get("week") or {}).get("number")
    wk = f"{season}-w{week}"
    live = any_live(sb, now)
    kicks = [B.parse_dt(e.get("date")) for e in sb.get("events", [])]
    jobs = due_jobs(now, rs, live, wk, force, kickoffs=kicks)
    print("jobs:", sorted(jobs), "live:", live)
    if not jobs:
        return
    if "pregame" in jobs:
        first = min((e.get("date") for e in sb.get("events", []) if e["status"]["type"]["state"] == "pre"), default=None)
        build_tables(season, week, kickoff_iso=first)
        try:
            from .injury_history import build as build_hist
            build_hist(season, week)
        except Exception as e:  # never block the board on research
            print("injury history failed:", e)
        if not os.path.exists(BT_FILE) or rs.get("backtestWeek") != wk:
            run_backtest(season, max(1, week - 1))
            rs["backtestWeek"] = wk
    if "inactives" in jobs:
        first = min((e.get("date") for e in sb.get("events", []) if e["status"]["type"]["state"] == "pre"), default=None)
        build_tables(season, week, kickoff_iso=first, rebuild_backup_only=True)
        rs["inactives"] = ct(now).strftime("%Y-%m-%d")
    if "backfill" in jobs:
        from .backtest import backfill_snapshots
        sn = load_json(B.SNAP_FILE, {}) or {}
        print("backfilled", backfill_snapshots(season, week, sb, sn))
        save_json(B.SNAP_FILE, sn, compact=True)
    L = LR.load()
    backtest = load_json(BT_FILE)
    calib = LR.calib_reliability(L, backtest)
    prev = load_json(TOP_FILE, {}) or {}
    try:   # cloud save: bets + Robinhood combo quotes posted by the app (free ntfy mailbox)
        from .sync import run as sync_run
        sync_run(rs, now)
    except Exception as e:
        print("sync failed:", e)
    board = B.build(now, extra_shrink=L["shrink"].get("factor", 1.0), calib=calib, sb_override=sb)
    if board is None:
        return
    if "pregame" in jobs and (rs.get("pregame") != wk):
        B.set_thursday_baseline(board)
        rs["pregame"] = wk
        rs["pregameAt"] = iso(now)
    try:   # research archive: every game's pregame + in-game prices for the season (logging only)
        from .archive import record as archive_record
        archive_record(board, now)
    except Exception as e:
        print("archive failed:", e)
    try:
        from .clv import update as clv_update
        board["clv"] = clv_update(board, now)
    except Exception as e:
        print("clv failed:", e)
    # learning
    snaps = load_json(B.SNAP_FILE, {}) or {}
    from .backtest import refresh_backfilled
    rep = refresh_backfilled(snaps)
    if rep:
        save_json(B.SNAP_FILE, snaps, compact=True)
        print("re-priced backfilled snapshots:", len(rep), "regraded:", LR.regrade(L, rep))
    LR.audit(board, prev, L)
    LR.log_combos(board, L)
    LR.grade_finals(board, snaps, L)
    forced = [j.split("-", 1)[1] for j in jobs if j.startswith("window-")]
    LR.window_lessons(board, L, force_windows=forced)
    if not os.path.exists(os.path.join(C.STATE, "team_track.json")):   # first run: build this season's team history now
        try:
            from . import teamtrack as TT
            TT.run(L)
        except Exception as e:
            print("team tracker seed failed:", e)
    if L["weekly"] and not L["weekly"][-1].get("review"):   # fill in a week reviewed before this existed (no push)
        try:
            from . import weekreview as WR
            WR.attach(L, L["weekly"][-1]["season"], L["weekly"][-1]["week"], snaps)
        except Exception as e:
            print("weekly review backfill failed:", e)
    for j in jobs:
        if j.startswith("window-"):
            rs[j] = ct(now).strftime("%Y-%m-%d")
    if "weekly-check" in jobs:
        # review the previous (or current, if ESPN hasn't rolled) week once MNF is final
        for wkn in (week, week - 1):
            recs = [g for g in board["games"]] if wkn == week else []
            if wkn == week and recs and not all(g["state"] == "post" for g in recs):
                continue
            item = LR.weekly_review(board, L, season, wkn)
            if item:
                rs["weekly"] = f"{season}-w{wkn}"
                try:   # weekly pick review + re-run through today's engine (Rick 2026-11-27), before the recap
                    from . import weekreview as WR
                    WR.attach(L, season, wkn, snaps)
                except Exception as e:
                    print("weekly review failed:", e)
                try:   # team tracker (Rick 2026-11-27): every team vs our picks, this year weighted most; info only
                    from . import teamtrack as TT
                    tt = TT.run(L, season)
                    note = TT.week_notes(L, season, wkn, tt["teams"])
                    wk_item = next((x for x in L["weekly"] if x.get("season") == season and x.get("week") == wkn), None)
                    if note and wk_item is not None and wk_item.get("review") is not None:
                        wk_item["review"]["teamNote"] = note
                except Exception as e:
                    print("team tracker failed:", e)
                try:   # Monday night recap push (Rick 2026-11-26): once per week, when the week's last game is final
                    from . import recaps as RC
                    RC.recap(L, season, wkn, rs, P.send)
                except Exception as e:
                    print("recap failed:", e)
                if wkn >= 14 and not rs.get("retest14"):
                    # auto re-test after Weeks 12-14 with the same scripts
                    run_backtest(season, wkn)
                    retest_rules(season, wkn)
                    rs["retest14"] = iso(now)
                break
        try:   # Kalshi slow-price test on our own saved prices: runs weekly once 3+ weeks are saved (mid-Dec)
            from .lag_study import run_weekly as lag_weekly
            lag_weekly(rs, now)
        except Exception as e:  # research never blocks the board
            print("lag study failed:", e)
    # common-sense checks: hold calls (and every Buy/Sell/Dip push) if the data looks wrong
    from . import alarm as AL
    from . import sanity as SN
    problems = SN.apply(board, now)
    if problems:
        print("data check:", problems)
    AL.data(problems)
    # pushes
    if "top3" in jobs:
        lines = top3_message(board, now)
        if lines:
            P.send("Game day", "\n".join(lines))
        rs["top3"] = ct(now).strftime("%Y-%m-%d")
    sent = set(rs.get("alertsSent", []))
    for a in board["alerts"]:
        k = f"{a['key']}|Q{a['q']}"
        if k in sent:
            continue
        P.send(f"Dip: {a['team']} {a['price']:.0f}c", f"{a['team']} now {a['price']:.0f}c -> +{a['profit']:.0f}c if it wins · grade {a['confidence']}\n{a['why']}", priority="high")
        sent.add(k)
    rs["alertsSent"] = sorted(sent)[-300:]
    # pregame: a team turning Value now (e.g. a Wait price got hit) -> one push
    vsent = rs.setdefault("valueSent", {})
    pre_c = [c for c in board["calls"]
             if c.get("state") == "pre" and c.get("call") == "Value" and not c.get("priceStale")
             and not (c.get("lineCheck") and c["price"] > (c["lineCheck"].get("buyUnder") or 0)) and vsent.get(c["key"]) != round(c["price"] or 0)]
    live_c = [c for c in board["calls"]
              if c.get("state") == "in" and c.get("liveCall") == "Value" and not c.get("paused") and not c.get("priceStale") and not c.get("alertsOff")
              and c.get("price") is not None and vsent.get(c["key"] + ":live") != round(c["price"])]
    ok = recheck(pre_c + live_c, board)      # review 2026-11-23: confirm a minute later on fresh data before any Buy push
    for c in pre_c:
        if c["key"] in ok:
            P.send(f"{'Slow price' if c.get('lag') else 'Buy now'}: {c['team']} {c['price']:.0f}c",
                   f"{c['team']} vs {c['opp']} {c['price']:.0f}c -> win {100 - c['price']:.0f}c · grade {c['confidence']['level']}\n{c['why']}")
            vsent[c["key"]] = round(c["price"] or 0)
    # live: a Wait price getting hit mid-game -> one push (never paused, never late Q4)
    for c in live_c:
        if c["key"] in ok:
            P.send(f"Buy now (live): {c['team']} {c['price']:.0f}c",
                   f"{c['team']} vs {c['opp']} {c['price']:.0f}c -> win {100 - c['price']:.0f}c · fair {c.get('liveFair')}c", priority="high")
            vsent[c["key"] + ":live"] = round(c["price"])
    # Sell (if you own it): one push per team per price; same pause / stale / late-Q4 rules as buys
    for c in board["calls"]:
        sl = c.get("sell")
        if not sl or c.get("priceStale") or c.get("paused") or c.get("alertsOff") or c.get("state") == "post":
            continue
        k = c["key"] + ":sell"
        if vsent.get(k) == round(sl["bid"]):
            continue
        fair = c.get("liveFair") if c.get("state") == "in" else c.get("fair")
        P.send(f"Sell{' (live)' if c.get('state') == 'in' else ''}: {c['team']} {sl['bid']:.0f}c",
               f"If you own {c['team']}, selling now at {sl['bid']:.0f}c beats holding · fair {fair:.0f}c ({sl['edge']:.0f}c above after fees)",
               priority="high")
        vsent[k] = round(sl["bid"])
    news_alerts(board, rs, now)
    try:   # last call ~30 min before each kickoff (Rick 2026-11-26)
        from . import recaps as RC
        RC.note_buys(board, rs)
        if not problems:
            RC.last_call(board, rs, now, P.send)
    except Exception as e:
        print("last call failed:", e)
    from .feeds import feed_alerts
    feed_alerts(board, rs, now, P.send)
    swing_alerts(board, rs, now)
    gap_alerts(board, rs)
    if len(vsent) > 400:
        rs["valueSent"] = dict(list(vsent.items())[-400:])
    board["nextCheck"] = next_check(now, [B.parse_dt(g.get("kickoff")) for g in board["games"]])
    board["feedNotes"] = feed_notes(board, HEALTH.data)
    if problems:
        board["feedNotes"].insert(0, "Data looks off (" + "; ".join(problems)[:160] + ") — calls on hold, check Robinhood")
    try:
        AL.feeds(board, HEALTH.data, now)
        P.migrate_topic()
    except Exception as e:
        print("alarm/topic failed:", e)
    board["health"] = HEALTH.data
    board["push"] = P.public()
    od = load_json(os.path.join(C.STATE, "odds.json"), {}) or {}
    board["odds"] = {k: od.get(k) for k in ("enabled", "fetchedAt", "left", "used", "error")}
    board["banners"] = {"weekly": weekly_banner(board, L),
                        "windows": [w for w in L["windows"] if w["season"] == season and w["week"] == week]}
    board["learningShrink"] = L["shrink"]
    try:   # nflverse files the research blocks read (the loop's cache may not have them)
        _nflverse_files(season)
    except Exception as e:
        print("nflverse files failed:", e)
    try:   # form, coach style, backup-QB profiles: context only
        from . import form as FM
        fp = load_json(FM.PROF, {}) or {}
        if "pregame" in jobs or not fp.get("teams") or (now - B.parse_dt(fp.get("at"))).days >= 6:
            FM.build(season)
        FM.for_board(board, load_tables())
    except Exception as e:
        print("form failed:", e)
    try:   # head-to-head history (this season + last): context only
        from . import h2h as HH
        hp = load_json(HH.FILE, {}) or {}
        if "pregame" in jobs or hp.get("week") != week or hp.get("season") != season:
            HH.build(season, week)
        lq = {t: f["backupQB"]["backup"] for g in board["games"] for t, f in (g.get("form") or {}).items() if f.get("backupQB")}
        HH.for_board({"games": board["games"] + (board.get("nextWeek") or [])}, latest_qb=lq)
    except Exception as e:
        print("h2h failed:", e)
    try:   # expert picks: context only, never blocks the board
        from . import experts as EX
        est = EX.update(season, week, now, rs)
        EX.for_board(est, board["games"])
        EX.tag_legs(board)
        board["experts"] = EX.public(est)
    except Exception as e:
        print("experts failed:", e)
    try:   # watch tags from the combo study: tag only, tracked live
        from . import watch as WT
        wp = load_json(WT.FILE, {}) or {}
        if "pregame" in jobs or wp.get("season") != season or (now - B.parse_dt(wp.get("at"))).total_seconds() >= 86400:
            WT.build(season)
        WT.for_board(board)
        WT.for_board(board, board.get("nextWeek") or [], week=week + 1, early=True)
        WT.tag_legs(board)
        board["watch"] = WT.track(board)
    except Exception as e:
        print("watch failed:", e)
    try:   # resting-starters flag, Weeks 15-18: info only (Rick 2026-11-26)
        from . import rest as RS
        RS.attach(board)
    except Exception as e:
        print("rest flag failed:", e)
    try:   # top combos (under 10c + best value), this week and next week; logged and graded weekly
        from . import topcombos as TC
        board["topCombos"] = TC.build(board)
    except Exception as e:
        print("top combos failed:", e)
    board["schedule"] = {"pregameAt": rs.get("pregameAt"), "thursdayBaseline": rs.get("pregame") == wk}
    LR.save(L)
    cfg = C._cfg()   # real Robinhood combo quotes feed the app's markup estimate
    board["comboQuotes"] = cfg.get("comboQuotes") or []
    board["comboMarkup"] = float(cfg.get("comboMarkup") or C.COMBO_MARKUP)
    save_json(TOP_FILE, board, compact=True)
    pub = LR.public(L, backtest)
    ih = load_json(os.path.join(C.STATE, "injury_history.json"), {}) or {}
    ms = load_json(os.path.join(C.STATE, "model_study.json"))
    if ms:
        pub["modelStudy"] = ms
    ts = load_json(os.path.join(C.STATE, "timing_study.json"))
    if ts:
        pub["timingStudy"] = ts
    ss = load_json(os.path.join(C.STATE, "signals_study.json"))
    if ss:
        pub["signalsStudy"] = ss
    ps = load_json(os.path.join(C.STATE, "profiles_study.json"))
    if ps:
        pub["profilesStudy"] = ps
    fs = load_json(os.path.join(C.STATE, "form_study.json"))
    if fs:
        pub["formStudy"] = fs
    hs = load_json(os.path.join(C.STATE, "h2h_study.json"))
    if hs:
        pub["h2hStudy"] = hs
    if board.get("clv"):
        pub["clv"] = board["clv"]
    ls = load_json(os.path.join(C.STATE, "lag_study.json"))
    if ls:
        pub["lagStudy"] = {k: ls.get(k) for k in ("at", "weeks", "summary", "held", "baseline", "signals")}
    rw = load_json(os.path.join(C.STATE, "retest_log.json"))
    if rw:
        pub["retest"] = rw
    if ih:
        pub["injuryResearch"] = {k: ih.get(k) for k in ("headline", "byQuarter", "byPosition", "throughWeek", "builtAt")}
    save_json(LEARN_PUB, pub, compact=True)
    rs["light"] = iso(now)
    save_json(RUN, rs)
    HEALTH.save()
    print(f"board: {len(board['games'])} games, top3={len(board['top3'])}, alerts={len(board['alerts'])}")


if __name__ == "__main__":
    args = sys.argv[1:] or ["tick"]
    cmd = args[0]
    if cmd == "odds":            # Refresh button: pull the odds feeds now (quota.py keeps taps 30 min apart)
        os.environ["NFL_FORCE_ODDS"] = "1"
    force = {"tick": (), "pregame": ("pregame",), "inactives": ("inactives",), "top3": ("top3",),
             "window": tuple(f"window-{w}" for w in (args[1:] or ["early", "late", "snf"])),
             "weekly": ("weekly-check",), "board": ("board",), "backfill": ("backfill",), "odds": ("board",)}.get(cmd, ())
    tick(force=set(force) | ({"board"} if cmd != "tick" else set()))
