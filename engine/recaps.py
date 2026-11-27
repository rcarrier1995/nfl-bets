"""Two short phone alerts Rick asked for (2026-11-26):

- Last call (idea 5): about 30 minutes before kickoff, once per kickoff time. Says which Buys are still a Buy
  after inactives, which teams were a Buy earlier today and no longer are, the A picks and the Wait targets.
  Nothing to say = no alert.
- Monday night recap (idea 8): once the week's last game is final. How the picks did, the Buy calls' result
  per contract, A picks, the best and worst call, and Rick's own bets when they are saved online.

Both read only what the app already shows (board calls, graded finals); nothing is invented.
"""
import glob
import json
import os
from datetime import timedelta

from . import config as C

LAST_CALL_MIN = 40      # minutes before kickoff when the last-call window opens (loop runs every 6-10 min)
SYNC_DIR = os.path.join(C.ROOT, "docs", "data", "sync")


def _grade(p):
    return next((g for lo, g in ((85, "A+"), (75, "A"), (60, "B"), (45, "C")) if p is not None and p >= lo), "F")


def _lbl(call):
    return {"Value": "Buy"}.get(call, call or "Pass")


def _dt(s):
    from .board import parse_dt
    return parse_dt(s)


def note_buys(board, rs):
    """Remember every team that showed Buy before its game (for 'no longer a Buy' at last call)."""
    seen = rs.setdefault("buySeen", {})
    live_ids = {g["id"] for g in board["games"] if g.get("state") != "post"}
    for c in board["calls"]:
        if c.get("state") == "pre" and c.get("call") == "Value" and not c.get("priceStale") and not c.get("dataHold"):
            ts = seen.setdefault(c["gameId"], [])
            if c["team"] not in ts:
                ts.append(c["team"])
    for gid in list(seen):
        if gid not in live_ids:
            seen.pop(gid)


def last_call_lines(board, games, seen):
    by = {(c["gameId"], c["team"]): c for c in board["calls"]}
    lines = []
    for g in games:
        for t in (g["away"], g["home"]):
            c = by.get((g["id"], t)) or {}
            if c.get("price") is None or c.get("priceStale") or c.get("dataHold"):
                continue
            p, call, fair = c["price"], c.get("call"), c.get("fair")
            stale_line = c.get("lineCheck") and p > (c["lineCheck"].get("buyUnder") or 0)
            if call == "Value" and not stale_line:
                lines.append(f"Still BUY {t} {p:.0f}c -> win {100 - p:.0f}c · {_grade(fair)}")
            elif t in (seen.get(g["id"]) or []):
                lines.append(f"{t} no longer a Buy: now {_lbl(call)} at {p:.0f}c")
            elif call == "Wait" and c.get("buyAt"):
                lines.append(f"Wait {t}: buy at {c['buyAt']}c (now {p:.0f}c)")
            if fair is not None and fair >= 75 and call != "Value":
                lines.append(f"A pick {t} {_grade(fair)} {p:.0f}c ({_lbl(call)})")
    return lines


def last_call(board, rs, now, send):
    """One push per kickoff time, ~30 min before. Returns the lines sent (for tests)."""
    done = rs.setdefault("lastCall", {})
    due = []
    for g in board["games"]:
        k = _dt(g.get("kickoff"))
        if g.get("state") != "pre" or not k or g["id"] in done:
            continue
        if timedelta(0) < k - now <= timedelta(minutes=LAST_CALL_MIN):
            due.append(g)
    if not due:
        return []
    for g in due:
        done[g["id"]] = g["kickoff"]
    if len(done) > 60:
        rs["lastCall"] = dict(list(done.items())[-60:])
    lines = last_call_lines(board, due, rs.get("buySeen") or {})
    if not lines:
        return []
    k = min(_dt(g["kickoff"]) for g in due).astimezone(C.CT)
    when = k.strftime("%I:%M%p").lstrip("0").lower()
    title = f"Last call: {len(due)} game{'s' if len(due) > 1 else ''} at {when}"
    send(title, "\n".join(lines[:10]))
    return lines


# ---------- Monday night recap ----------
def _bets_store():
    """Rick's bets saved online. Used only when there is exactly one saved code (the app link is public,
    so with several codes we can't tell whose is whose: the recap then leaves bets out)."""
    files = glob.glob(os.path.join(SYNC_DIR, "*.json"))
    if len(files) != 1:
        return None
    try:
        with open(files[0]) as f:
            return json.load(f)
    except Exception:
        return None


def _bet_result(b, winners):
    if b.get("result") in ("win", "loss", "tie"):
        return b["result"]
    legs = b.get("legs") if b.get("kind") == "combo" else [{"gameId": b.get("gameId"), "team": b.get("team")}]
    rs = []
    for l in legs or []:
        if l.get("gameId") not in winners:
            return None
        w = winners[l["gameId"]]
        rs.append("tie" if w is None else "win" if w == l.get("team") else "loss")
    if not rs:
        return None
    return "loss" if "loss" in rs else "win" if all(r == "win" for r in rs) else None if b.get("kind") == "combo" else rs[0]


def recap_lines(L, season, week, store=None):
    recs = [r for r in (L.get("graded") or {}).values() if r.get("season") == season and r.get("week") == week]
    if not recs:
        return []
    ties = sum(1 for r in recs if r.get("tie"))
    right = sum(1 for r in recs if r.get("right"))
    lines = [f"Picks {right}-{len(recs) - right - ties}{f'-{ties}' if ties else ''}"]
    buys, apk = [], []
    for r in recs:
        for t, c in (r.get("calls") or {}).items():
            p = c.get("price")
            if p is None:
                continue
            won = None if r.get("tie") else r.get("winner") == t
            prof = 50 - p if won is None else (100 - p if won else -p)
            if c.get("call") == "Value":
                buys.append((t, p, won, prof))
            if (c.get("fair") or 0) >= 75:
                apk.append((t, c["fair"], won, r))
    if buys:
        w = sum(1 for b in buys if b[2])
        tot = sum(b[3] for b in buys)
        lines.append(f"Buys {w}-{sum(1 for b in buys if b[2] is False)} · {'+' if tot >= 0 else ''}{tot:.0f}c per contract")
    else:
        lines.append("No Buy calls this week")
    if apk:
        lines.append(f"A picks {sum(1 for a in apk if a[2])}-{sum(1 for a in apk if a[2] is False)}")
    won_buys = [b for b in buys if b[2]]
    if won_buys:
        b = max(won_buys, key=lambda b: b[3])
        lines.append(f"Best: Buy {b[0]} at {b[1]:.0f}c won (+{b[3]:.0f}c)")
    else:
        hits = [r for r in recs if r.get("right")]
        if hits:
            r = min(hits, key=lambda r: r.get("pickFair") or 100)
            lines.append(f"Best: {r['pick']} ({r['pickFair']:.0f}%) won · {r['final']}")
    miss = [r for r in recs if not r.get("right") and not r.get("tie")]
    if miss:
        r = max(miss, key=lambda r: r.get("pickFair") or 0)
        lines.append(f"Worst: {r['pick']} ({r['pickFair']:.0f}%) lost · {r['final']}")
    if store:
        winners = {r["key"].split("|")[-1]: r.get("winner") for r in recs}
        n = w = l = 0
        cents = 0.0
        for b in (store.get("bets") or {}).values():
            if b.get("season") != season or b.get("week") != week:
                continue
            res = _bet_result(b, winners)
            if res is None:
                continue
            q, p = float(b.get("qty") or 1), float(b["price"])
            n += 1
            w += res == "win"
            l += res == "loss"
            cents += q * ((100 - p) if res == "win" else (50 - p) if res == "tie" else -p)
        if n:
            lines.append(f"Your bets {w}-{l} · {'+' if cents >= 0 else '-'}${abs(cents) / 100:.2f}")
    wk = next((x for x in (L.get("weekly") or []) if x.get("season") == season and x.get("week") == week), None)
    learned = ((wk or {}).get("review") or {}).get("learned")
    if learned:
        lines.append(learned)
    note = ((wk or {}).get("review") or {}).get("teamNote")
    if note:
        lines.append(note)
    return lines


def recap(L, season, week, rs, send, store=None):
    key = f"{season}-w{week}"
    if rs.get("recap") == key:
        return []
    lines = recap_lines(L, season, week, store if store is not None else _bets_store())
    rs["recap"] = key
    if lines:
        from .fetch import week_label
        send(f"{week_label(week)} recap", "\n".join(lines))
    return lines
