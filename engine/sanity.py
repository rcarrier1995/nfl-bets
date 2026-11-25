"""Common-sense checks on the board before any call or push goes out (review 2026-11-25).

If the data looks wrong, the app holds its calls (shows "Data looks off") instead of guessing:
  - whole board: no games, the same team twice, a week that is over for days (stuck week),
    or a week whose first game is more than 9 days away (wrong week)
  - one game: a price outside 1-99c, or the two sides' prices far from adding up to ~100c
Never changes a price; only turns Buy/Wait/Sell into a hold and says why.
"""
from datetime import timedelta

from .board import parse_dt

PAIR_LO, PAIR_HI = 85, 120   # Kalshi yes asks for the two teams normally add to ~100-104c


def check(board, now):
    """Returns (board_issues, {gameId: issue}). Empty means all good."""
    issues, per_game = [], {}
    games = board.get("games") or []
    if not games:
        return ["no games on the schedule"], per_game
    teams = [t for g in games for t in (g.get("home"), g.get("away"))]
    dup = sorted({t for t in teams if t and teams.count(t) > 1})
    if dup:
        issues.append(f"{', '.join(dup)} listed twice")
    kos = [parse_dt(g.get("kickoff")) for g in games]
    kos = [k for k in kos if k]
    if kos and all(g.get("state") == "post" for g in games) and now - max(kos) > timedelta(days=2):
        issues.append(f"week {board.get('week')} ended days ago — schedule didn't move on")
    pre = [parse_dt(g.get("kickoff")) for g in games if g.get("state") == "pre"]
    pre = [k for k in pre if k]
    if pre and not any(g.get("state") in ("in", "post") for g in games) and min(pre) - now > timedelta(days=9):
        issues.append(f"week {board.get('week')} is more than 9 days away")
    calls = {}
    for c in board.get("calls") or []:
        calls.setdefault(c.get("gameId"), []).append(c)
    for g in games:
        if g.get("state") == "post":
            continue
        cs = calls.get(g.get("id"), [])
        bad = [c["team"] for c in cs if c.get("price") is not None and not (0 < c["price"] < 100)]
        if bad:
            per_game[g["id"]] = f"odd price for {', '.join(bad)}"
            continue
        ps = [c["price"] for c in cs if c.get("price") is not None]
        if g.get("state") == "pre" and len(ps) == 2 and not (PAIR_LO <= sum(ps) <= PAIR_HI):
            per_game[g["id"]] = f"{g.get('away')} + {g.get('home')} prices add to {sum(ps):.0f}c"
    return issues, per_game


def apply(board, now):
    """Hold calls where the data looks off. Returns the list of plain-English problems (for a push)."""
    issues, per_game = check(board, now)
    held = set()
    for c in board.get("calls") or []:
        why = "; ".join(issues) if issues else per_game.get(c.get("gameId"))
        if not why or c.get("state") == "post":
            continue
        c["dataHold"] = why
        c["sell"] = None
        if c.get("call") in ("Value", "Wait"):
            c["call"] = "Pass"
        if c.get("liveCall") in ("Value", "Wait"):
            c["liveCall"] = "Pass"
        held.add(c.get("key"))
    if held:
        board["top3"] = [k for k in board.get("top3") or [] if k not in held]
        board["alerts"] = [a for a in board.get("alerts") or [] if a.get("key") not in held]
    probs = issues + list(per_game.values())
    board["dataCheck"] = {"ok": not probs, "issues": issues, "games": per_game}
    return probs
