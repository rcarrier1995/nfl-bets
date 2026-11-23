"""Scheduler + jobs. GitHub Actions calls `python -m engine.run tick` every 10 minutes; the tick
decides (in America/Chicago time, DST-safe) which jobs are due:

  nfl-pregame-weekly   Thu 12:00 CT        full pregame refresh + nflverse tables + Thursday baseline
  nfl-sunday-inactives Sun 10:30 CT        inactives refresh, rebuild backup_map
  morning Top 3 push   Thu & Sun 8:00 CT   ntfy push of just the Top 3
  nfl-live-sunday      every 10 min while games are live (any day)
  nfl-window-early     Sun 15:35 CT        early window review (also auto when the window's last game is final)
  nfl-window-late      Sun 18:50 CT
  nfl-window-snf       Sun 23:00 CT
  nfl-learning-monday  Mon 23:45 CT        full weekly learning review after MNF
  light refresh        hourly otherwise    prices/injuries/weather for the board
"""
import os
import sys
from datetime import datetime, timedelta

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


def due_jobs(now, rs, sb_live, week_key, force=()):
    t = ct(now)
    wd, hm, date = t.weekday(), t.hour * 60 + t.minute, t.strftime("%Y-%m-%d")
    jobs = set(force)
    if (wd == 3 and hm >= 12 * 60 and rs.get("pregame") != week_key) or not load_tables().get("ok") \
            or load_tables().get("week") != int(week_key.split("-w")[1]):
        jobs.add("pregame")
    if wd == 6 and hm >= 10 * 60 + 30 and rs.get("inactives") != date:
        jobs.add("inactives")
    if wd in (3, 6) and 8 * 60 <= hm < 11 * 60 and rs.get("top3") != date:
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


def next_check(now):
    """Next scheduled check, for empty-state hints."""
    t = ct(now)
    slots = [(3, 12, 0, "Thu 12pm"), (6, 8, 0, "Sun 8am"), (6, 10, 30, "Sun 10:30am"), (6, 15, 35, "Sun 3:35pm"),
             (6, 18, 50, "Sun 6:50pm"), (6, 23, 0, "Sun 11pm"), (0, 23, 45, "Mon 11:45pm"), (3, 8, 0, "Thu 8am")]
    best = None
    for wd, h, m, label in slots:
        d = (wd - t.weekday()) % 7
        cand = (t + timedelta(days=d)).replace(hour=h, minute=m, second=0, microsecond=0)
        if cand <= t:
            cand += timedelta(days=7)
        if best is None or cand < best[0]:
            best = (cand, label)
    return f"Next check: {best[1]}"


def top3_message(board):
    by = {c["key"]: c for c in board["calls"]}
    lines = []
    for k in board["top3"]:
        c = by[k]
        if c["call"] == "Value":
            lines.append(f"{c['team']} Buy {c['price']:.0f}c -> win {100 - c['price']:.0f}c · grade {c['confidence']['level']}")
        else:
            lines.append(f"{c['team']} Wait {c['price']:.0f}c, buy at {c['buyAt']}c -> win {100 - c['buyAt']}c · grade {c['confidence']['level']}")
    return lines


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
        return {"label": f"Week {w['week']}: {w['w']}–{w['l']} · {w['acc']:.0f}%", "week": w["week"], **w}
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
    sb, _ = B.espn_scoreboard()
    if not sb:
        HEALTH.save()
        print("scoreboard unavailable; nothing to do")
        return
    season = (sb.get("season") or {}).get("year")
    week = (sb.get("week") or {}).get("number")
    wk = f"{season}-w{week}"
    live = any_live(sb, now)
    jobs = due_jobs(now, rs, live, wk, force)
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
    board = B.build(now, extra_shrink=L["shrink"].get("factor", 1.0), calib=calib, sb_override=sb)
    if board is None:
        return
    if "pregame" in jobs and (rs.get("pregame") != wk):
        B.set_thursday_baseline(board)
        rs["pregame"] = wk
        rs["pregameAt"] = iso(now)
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
                if wkn >= 14 and not rs.get("retest14"):
                    # auto re-test after Weeks 12-14 with the same scripts
                    run_backtest(season, wkn)
                    retest_rules(season, wkn)
                    rs["retest14"] = iso(now)
                break
    # pushes
    if "top3" in jobs:
        lines = top3_message(board)
        if lines:
            P.send("Top 3 today", "\n".join(lines))
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
    if len(vsent) > 400:
        rs["valueSent"] = dict(list(vsent.items())[-400:])
    board["nextCheck"] = next_check(now)
    board["feedNotes"] = feed_notes(board, HEALTH.data)
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
    try:   # top combos (under 10c + best value), this week and next week; logged and graded weekly
        from . import topcombos as TC
        board["topCombos"] = TC.build(board)
    except Exception as e:
        print("top combos failed:", e)
    board["schedule"] = {"pregameAt": rs.get("pregameAt"), "thursdayBaseline": rs.get("pregame") == wk}
    LR.save(L)
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
    force = {"tick": (), "pregame": ("pregame",), "inactives": ("inactives",), "top3": ("top3",),
             "window": tuple(f"window-{w}" for w in (args[1:] or ["early", "late", "snf"])),
             "weekly": ("weekly-check",), "board": ("board",), "backfill": ("backfill",)}.get(cmd, ())
    tick(force=set(force) | ({"board"} if cmd != "tick" else set()))
