"""Learning: grade finals, window lessons, weekly review, calibration, shrink, audit trail."""
import os
from datetime import datetime

from . import config as C
from . import model as M
from .fetch import load_json, save_json, iso

LEARN = os.path.join(C.STATE, "learning.json")
BUCKETS = [(50, 60), (60, 70), (70, 80), (80, 101)]


def load():
    d = load_json(LEARN, {}) or {}
    for k, v in (("graded", {}), ("windows", []), ("weekly", []), ("audit", []), ("comboLog", {}),
                 ("shrink", {"factor": 1.0, "note": "No shrink adjustment yet"})):
        d.setdefault(k, v)
    return d


def save(d):
    d["audit"] = d["audit"][-1500:]
    save_json(LEARN, d, compact=True)


def window_of(kickoff_iso):
    dt = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00")).astimezone(C.CT)
    wd = dt.weekday()  # Mon 0 .. Sun 6
    if wd == 6:
        if dt.hour < 14:
            return "early"
        if dt.hour < 18:
            return "late"
        return "snf"
    return {3: "tnf", 0: "mnf", 5: "sat", 4: "fri", 1: "tue", 2: "wed"}.get(wd, "other")


WINDOW_NAME = {"early": "Early window", "late": "Late window", "snf": "SNF", "tnf": "TNF", "mnf": "MNF",
               "sat": "Saturday", "fri": "Friday", "tue": "Tuesday", "wed": "Wednesday", "other": "Other"}


def category(pick_fair, margin, right):
    if pick_fair is not None and pick_fair < 55:
        return "coin-flip"
    if not right and (pick_fair or 0) >= 60:
        return "upset"
    if margin >= 17:
        return "blowout"
    if margin <= 7:
        return "close"
    return "normal"


def grade_finals(board, snaps, L):
    """Grade each just-finished game right/wrong with margin, category, Brier."""
    new = []
    for g in board["games"]:
        if g["state"] != "post" or g["key"] in L["graded"]:
            continue
        if (g.get("kickoff") or "") < C.BASELINE["through"][:16]:
            continue   # already inside the 97/151 baseline backtest — don't double count
        s = snaps.get(g["key"]) or {}
        t = s.get("teams") or {}
        fa, fh = (t.get(g["away"]) or {}).get("fair"), (t.get(g["home"]) or {}).get("fair")
        a, h = g["score"]["away"], g["score"]["home"]
        if fa is None or fh is None or a is None or h is None:
            continue   # no pregame snapshot = not graded (never invented)
        pick = g["home"] if fh >= fa else g["away"]
        pf = max(fa, fh)
        winner = g["away"] if a > h else g["home"] if h > a else None
        outcome = 0.5 if winner is None else (1.0 if winner == pick else 0.0)
        right = outcome == 1.0
        margin = abs(a - h)
        q3 = next((q for q in g.get("quarters", []) if q["q"] == 3), None)
        rec = {"key": g["key"], "season": s.get("season") or board.get("season"), "week": s.get("week") or board.get("week"),
               "kickoff": g["kickoff"], "window": window_of(g["kickoff"]), "away": g["away"], "home": g["home"],
               "final": f"{g['away']} {a} — {g['home']} {h}", "pick": pick, "pickFair": pf, "winner": winner,
               "right": right, "tie": winner is None, "margin": margin, "category": category(pf, margin, right),
               "brier": round((pf / 100 - outcome) ** 2, 4),
               "calls": {tm: {k: (t.get(tm) or {}).get(k) for k in ("call", "fair", "price", "edge", "buyAt")}
                         for tm in (g["away"], g["home"])},
               "conf": {tm: M.confidence((t.get(tm) or {}).get("fair"))["level"] for tm in (g["away"], g["home"])},
               "q3Leader": q3["leader"] if q3 else None,
               "quarters": g.get("quarters", []), "turnovers": g.get("turnovers"),
               "injuries": [f"Q{i['q']} {i['team']} {i['pos']} {i['name']} ({i['state']})" for i in g.get("injLive", [])],
               "qb": g.get("qb"), "weatherLine": g.get("weatherLine"),
               "weatherHours": (g.get("weather") or {}).get("hours"), "changes": g.get("changes", []),
               "gradedAt": iso()}
        rec["review"] = review_line(rec)
        L["graded"][g["key"]] = rec
        new.append(rec)
    return new


def regrade(L, keys):
    """Drop grades (and that week's window lessons) for games whose snapshot was re-priced; grade_finals redoes them."""
    keys = [k for k in keys if k in L["graded"]]
    weeks = {(L["graded"][k].get("season"), L["graded"][k].get("week")) for k in keys}
    for k in keys:
        del L["graded"][k]
    L["windows"] = [w for w in L["windows"] if (w.get("season"), w.get("week")) not in weeks]
    return len(keys)


def review_line(r):
    """What happened / how it went sideways, in one short line."""
    if r["tie"]:
        return "Tie — pays 50¢ both sides."
    if r["right"]:
        return f"{r['pick']} won by {r['margin']}" + (" — Q3 leader held" if r["q3Leader"] == r["pick"] else "")
    bits = [f"{r['winner']} upset {r['pick']} ({r['pickFair']:.0f}¢ fair)"]
    to = r.get("turnovers") or {}
    if to.get(r["pick"], 0) >= 2:
        bits.append(f"{r['pick']} {to[r['pick']]} turnovers")
    if r["q3Leader"] and r["q3Leader"] != r["pick"]:
        bits.append("trailed after Q3")
    return " · ".join(bits)


def window_lessons(board, L, force_windows=()):
    """Post a short lesson the moment a window's last game goes final (or at its cron time)."""
    by = {}
    for g in board["games"]:
        w = window_of(g["kickoff"])
        by.setdefault(w, []).append(g)
    posted = {(x["season"], x["week"], x["window"]): i for i, x in enumerate(L["windows"])}
    out = []
    for w, games in by.items():
        key = (board["season"], board["week"], w)
        if key not in posted and not all(g["state"] == "post" for g in games) and w not in force_windows:
            continue
        recs = [L["graded"][g["key"]] for g in games if g["key"] in L["graded"]]
        if not recs:
            continue
        if key in posted and L["windows"][posted[key]]["n"] == len(recs):
            continue
        right = sum(r["right"] for r in recs)
        lesson = lesson_for(recs)
        item = {"season": board["season"], "week": board["week"], "window": w,
                "label": f"{WINDOW_NAME[w]} — {right}/{len(recs)} right", "right": right, "n": len(recs),
                "games": [{"final": r["final"], "pick": r["pick"], "right": r["right"], "category": r["category"],
                           "review": r["review"], "changes": r["changes"][:4]} for r in recs],
                "lesson": lesson, "at": iso()}
        if key in posted:
            L["windows"][posted[key]] = item
        else:
            L["windows"].append(item)
        out.append(item)
    return out


MIN_LESSON = 3    # review 2026-11-23: no lessons from 1-2 games


def lesson_for(recs):
    """Facts about what happened, measured against what our own chances expected. Never a model change:
    only update_shrink can change the model, and only on a big, statistically clear sample."""
    recs = [r for r in recs if not r.get("tie")]
    if len(recs) < MIN_LESSON:
        return f"{len(recs)} game{'s' if len(recs) != 1 else ''}: too few to learn from — no lesson, no change."
    wrong = [r for r in recs if not r["right"]]
    exp = sum(1 - r["pickFair"] / 100 for r in recs)
    sd = sum((r["pickFair"] / 100) * (1 - r["pickFair"] / 100) for r in recs) ** 0.5
    luck = f"{len(wrong)} miss{'es' if len(wrong) != 1 else ''} vs about {exp:.1f} expected from our own chances"
    if not wrong:
        return f"All {len(recs)} picks won ({luck}) — normal good luck, no change."
    if len(wrong) > exp + 2 * sd:
        return f"More upsets than our chances expected ({luck}). One week is still small — logged, no change yet."
    big = [r for r in wrong if r["pickFair"] >= 70]
    if big:
        return f"{len(big)} favorite(s) at 70¢+ lost; {luck} — within normal luck, no change."
    q3 = [r for r in wrong if r["q3Leader"] and r["q3Leader"] != r["pick"]]
    if q3:
        return f"{len(q3)} miss(es) trailed after Q3; {luck} — no change."
    to = [r for r in wrong if (r.get("turnovers") or {}).get(r["pick"], 0) >= 2]
    if to:
        return f"Turnovers flipped games; {luck} — no change."
    return f"Close-game misses; {luck} — coin-flips, no model change."


def calibration(recs):
    rows = []
    for lo, hi in BUCKETS:
        rs = [r for r in recs if lo <= r["pickFair"] < hi]
        if rs:
            rows.append({"bucket": f"{lo}–{min(hi, 100) if hi < 101 else 100}", "lo": lo,
                         "pred": round(sum(r["pickFair"] for r in rs) / len(rs), 1),
                         "actual": round(100 * sum(r["right"] for r in rs) / len(rs), 1), "n": len(rs)})
    return rows


def calibration_conf(recs):
    rows = []
    for lvl in ("F", "C", "B", "A", "A+"):          # graded from the pick's fair, so older records count too
        rs = [r for r in recs if M.grade(r.get("pickFair")) == lvl]
        if rs:
            rows.append({"bucket": lvl, "pred": round(sum(r["pickFair"] for r in rs) / len(rs), 1),
                         "actual": round(100 * sum(r["right"] for r in rs) / len(rs), 1), "n": len(rs)})
    return rows


def by_call(recs):
    out = {}
    for r in recs:
        for tm, c in (r.get("calls") or {}).items():
            k = c.get("call") or "Pass"
            o = out.setdefault(k, {"n": 0, "won": 0})
            o["n"] += 1
            o["won"] += int(r["winner"] == tm)
    return out


SHRINK_MIN = 40


def profit_buys(recs):
    """Profit per contract (cents, after fees) if every pregame Buy had been bought at its price."""
    n, net = 0, 0.0
    for r in recs:
        for tm, c in (r.get("calls") or {}).items():
            if c.get("call") == "Value" and c.get("price") and not r.get("tie"):
                n += 1
                net += (100 if r["winner"] == tm else 0) - c["price"] - 2
    return {"n": n, "net": round(net, 1), "per": round(net / n, 1) if n else None}


def update_shrink(L):
    """If favorites prove systematically overconfident, shrink next week's fairs toward 50c.
    Only activates with >=4 reviewed games."""
    recs = [r for r in L["graded"].values() if r["pickFair"] >= 65]
    if len(recs) < SHRINK_MIN:     # review 2026-11-23: 4 games could trip it by luck
        L["shrink"] = {"factor": 1.0, "note": f"Needs {SHRINK_MIN}+ favorites at 65¢+ before any auto-adjust ({len(recs)} so far)"}
        return L["shrink"]
    pred = sum(r["pickFair"] for r in recs) / len(recs)
    act = 100 * sum(r["right"] for r in recs) / len(recs)
    gap = pred - act
    se = 100 * ((pred / 100) * (1 - pred / 100) / len(recs)) ** 0.5
    if gap > 3 and gap > 2 * se:   # only a real, statistically clear miss (n=12 noise fooled the old rule)
        f = max(0.85, round(1 - gap / 100 * 1.5, 3))
        # Rick 2026-11-27: any fair change must pass a backtest first (2021-now, this season weighted more)
        from .weekreview import backtest_shrink
        gate = backtest_shrink(f)
        if gate and gate["passed"]:
            L["shrink"] = {"factor": f, "note": f"Favorites 65¢+ hit {act:.0f}% vs {pred:.0f}% predicted — fairs shrunk ×{f} (passed backtest)",
                           "n": len(recs), "gate": gate, "at": iso()}
        else:
            L["shrink"] = {"factor": 1.0, "note": f"Favorites 65¢+ hit {act:.0f}% vs {pred:.0f}% predicted, but a ×{f} trim "
                           + ("failed the backtest" if gate else "couldn't be backtested") + " — no change",
                           "n": len(recs), "gate": gate or {"passed": False}, "at": iso()}
    else:
        L["shrink"] = {"factor": 1.0, "note": f"Favorites {act:.0f}% vs {pred:.0f}% predicted (n={len(recs)}) — within noise, no extra shrink",
                       "n": len(recs), "at": iso()}
    return L["shrink"]


def log_combos(board, L):
    """Store each week's recommended combos before kickoff so they can be graded."""
    wk = f"{board['season']}-w{board['week']}"
    log = L["comboLog"].setdefault(wk, {})
    for cat in ("standard", "combined", "safer"):
        for k, res in (board["combos"].get(cat) or {}).items():
            c = res.get("combo")
            if not c:
                continue
            if any(l["state"] != "pre" for l in c["legs"]):
                continue
            log[f"{cat}-{k}"] = {"legs": [{"gameId": l["gameId"], "team": l["team"]} for l in c["legs"]],
                                 "hit": c["hit"], "cost": c["cost"], "at": iso()}


def grade_combos(L, wk, graded_by_gid):
    out = {}
    for name, c in (L["comboLog"].get(wk) or {}).items():
        res = []
        for l in c["legs"]:
            r = graded_by_gid.get(l["gameId"])
            if r is None:
                res = None
                break
            res.append(r["winner"] == l["team"])
        if res is None:
            continue
        c["hitResult"] = all(res)
        cat = name.split("-")[0]
        o = out.setdefault(cat, {"n": 0, "hit": 0, "net": 0.0})
        o["n"] += 1
        o["hit"] += int(all(res))
        if c.get("cost"):
            o["net"] = round(o["net"] + (100 if all(res) else 0) - c["cost"], 1)
    return out


def weekly_review(board, L, season, week):
    recs = [r for r in L["graded"].values() if r["season"] == season and r["week"] == week]
    if not recs:
        return None
    if any(w["season"] == season and w["week"] == week for w in L["weekly"]):
        return None
    right = sum(r["right"] for r in recs)
    gid = {r["key"].split("|")[-1]: r for r in recs}
    combos = grade_combos(L, f"{season}-w{week}", gid)
    shrink = update_shrink(L)
    item = {"season": season, "week": week, "w": right, "l": len(recs) - right, "n": len(recs),
            "acc": round(100 * right / len(recs), 1), "brier": round(sum(r["brier"] for r in recs) / len(recs), 4),
            "calibration": calibration(recs), "calibConf": calibration_conf(recs), "byCall": by_call(recs),
            "categories": _count(r["category"] for r in recs), "combos": combos, "buys": profit_buys(recs),
            "lesson": lesson_for(recs), "shrink": shrink["note"], "at": iso()}
    L["weekly"].append(item)
    return item


def _count(it):
    d = {}
    for x in it:
        d[x] = d.get(x, 0) + 1
    return d


def totals(L):
    recs = list(L["graded"].values())
    r = sum(x["right"] for x in recs)
    return {"buys": profit_buys(recs), "right": C.BASELINE["right"] + r, "games": C.BASELINE["games"] + len(recs),
            "reviewedRight": r, "reviewed": len(recs),
            "pct": round(100 * (C.BASELINE["right"] + r) / (C.BASELINE["games"] + len(recs)), 1),
            "baseline": C.BASELINE}


def audit(board, prev, L):
    """Every call change logged (call, fair, price, buy-at, confidence, timestamp)."""
    pc = {c["key"]: c for c in (prev or {}).get("calls", [])}
    for c in board["calls"]:
        if c.get("state") != "pre":
            continue
        p = pc.get(c["key"])
        if p is None or p.get("call") != c.get("call") or p.get("buyAt") != c.get("buyAt"):
            L["audit"].append({"t": board["generatedAt"], "team": c["team"], "game": c["key"].split("|")[1],
                               "call": c.get("call"), "fair": c.get("fair"), "price": c.get("price"),
                               "buyAt": c.get("buyAt"), "conf": (c.get("confidence") or {}).get("score"),
                               "from": None if p is None else p.get("call")})


def calib_reliability(L, backtest):
    """Per fair bucket, actual/predicted ratio feeds the confidence score."""
    recs = list(L["graded"].values())
    rows = calibration(recs) if len(recs) >= 20 else (backtest or {}).get("calibration") or []
    rel = {}
    for row in rows:
        lo = str(row.get("lo") or int(str(row["bucket"]).split("–")[0]))
        if row["pred"]:
            rel[lo] = round(max(0.2, min(1.0, 1 - max(0, row["pred"] - row["actual"]) / 20)), 2)
    if "80" in rel:
        rel["90"] = rel["80"]
    return rel or None


def public(L, backtest):
    """What the app's Learning tab reads."""
    recs = sorted(L["graded"].values(), key=lambda r: r["kickoff"])
    return {"totals": totals(L), "windows": L["windows"][-40:], "weekly": L["weekly"][-20:],
            "calibration": calibration(recs), "calibConf": calibration_conf(recs), "byCall": by_call(recs),
            "shrink": L["shrink"], "audit": L["audit"][-400:], "graded": recs[-120:],
            "backtest": backtest, "teams": _teams(), "generatedAt": iso()}


def _teams():
    """Team tracker for the Learning tab (info only). None until it has been built."""
    t = load_json(os.path.join(C.STATE, "team_track.json"), None)
    if not t:
        return None
    return {"at": t.get("at"), "status": t.get("status"),
            "rows": sorted(t.get("teams", {}).values(), key=lambda r: -(r.get("vsAppWeighted") or 0))}
