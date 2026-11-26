"""Top combos each week (this week + next week's early prices), for Rick:
  * "cheap": the 3 combos costing under 10c with the best chance to hit, overlapping as little as possible
    (a reused game costs a small penalty, so strong legs can still repeat when nothing else works);
  * "value": the 3 best blends of win chance and price at any cost (chance minus cost, leaning to chance).
Win chance per leg = our fair value (watch tags are shown, never added: review 2026-11-23). Combo-study finding:
cheap combos work best as stacked favourites (60-85c legs); a longshot leg hurts, so it only gets in when
our numbers say it's worth its price. Every suggestion is logged and graded (learn weekly).
Info only: never changes a Buy/Wait/Pass call. The real Robinhood quote can run well above legs multiplied.
"""
import math

from . import config as C
from . import model as M
from . import watch as W
from .fetch import load_json, save_json, iso

LOG = f"{C.STATE}/combo_log.json"
CHEAP = 10.0        # cents
MAX_LEGS = 10
STEP = 0.01         # log-price bucket
REUSE = 0.06        # log-hit penalty per game already used in an earlier pick of the same list


def legs_for(games_list):
    """One entry per team in pregame games with a price: est = our fair + watch-tag adjustments."""
    ed = W.edges()
    by_tag = {v: k for k, v in W.TAGS.items()}
    out = []
    for g in games_list or []:
        if g.get("state") != "pre":
            continue
        teams = [g["teams"]["away"], g["teams"]["home"]]
        adj, why = {c["team"]: 0.0 for c in teams}, {c["team"]: [] for c in teams}
        good = {c["team"]: 0.0 for c in teams}
        for x in g.get("watch") or []:
            k = by_tag.get(x["tag"])
            if k in W.EDGE:
                good[x["team"]] = max(good[x["team"]], ed[k])
                why[x["team"]].append(x["tag"])
            elif k in W.FADE:
                o = next(c["team"] for c in teams if c["team"] != x["team"])
                adj[x["team"]] -= ed[k]
                adj[o] += ed[k]
                why[o].append(f"Fade {x['team']}: {x['tag'].lower()}")
        for c in teams:
            if not c.get("price") or c.get("fair") is None or not (3 <= c["price"] <= 97):
                continue
            # review 2026-11-23: tags are info only -- no padding; the win chance is our fair
            est = max(1.0, min(97.0, c["fair"]))
            out.append({"gameId": g["id"], "team": c["team"], "opp": c["opp"], "label": g.get("short"), "price": c["price"],
                        "fair": c["fair"], "est": round(est, 1), "call": c.get("call"), "why": why[c["team"]],
                        "dog": c["price"] < 50, "kickoff": g.get("kickoff")})
    return out


def _frontier(legs, used):
    """DP over games: best (penalised) log-hit for every (size, log-cost bucket)."""
    games = {}
    for l in legs:
        games.setdefault(l["gameId"], []).append(l)
    st = {(0, 0): (0.0, ())}
    for gid, opts in games.items():
        nxt = dict(st)
        for (k, b), (lh, sel) in st.items():
            if k >= MAX_LEGS:
                continue
            for l in opts:
                nb = b + round(-math.log(l["price"] / 100) / STEP)
                if nb * STEP > -math.log(0.002):   # never below 0.2c
                    continue
                v = lh + math.log(l["est"] / 100) - (REUSE if gid in used else 0)
                key = (k + 1, nb)
                if key not in nxt or v > nxt[key][0]:
                    nxt[key] = (v, sel + (l,))
        st = nxt
    return st


def _card(sel):
    k = len(sel)
    hit = math.prod(l["est"] / 100 for l in sel) * 100
    legs_cost = math.prod(l["price"] / 100 for l in sel) * 100
    cost = legs_cost * C.combo_markup(k, legs_cost)
    fair = math.prod(l["fair"] / 100 for l in sel) * 100
    return {"size": k, "legs": [dict(l) for l in sel], "hit": round(hit, 1), "cost": round(cost, 1), "legsCost": round(legs_cost, 1),
            "fair": round(fair, 1), "edge": round(hit - C.FEE_BUFFER_COMBO - cost, 1), "dogs": sum(1 for l in sel if l["dog"]),
            "oneIn": round(100 / hit) if hit > 0 else None, "conf": combo_conf(hit, cost, sel)}


def combo_conf(hit, cost=None, sel=None):
    """Combo grade from its real hit chance (Rick 2026-11-23): A = 33%+ (1 in 3), B = 15%+ (1 in 7),
    C = 7%+ (1 in 14), F = rarer. Price value is shown separately."""
    return M.grade(hit, M.COMBO_CUTS)


def pick(legs, kind, n=3):
    if kind == "cheap":   # combo study: longshot legs sink cheap combos; an underdog only if we expect it to win
        legs = [l for l in legs if l["price"] >= 50 or l["est"] >= 50]
    out, used = [], set()
    for _ in range(n):
        st = _frontier(legs, used)
        best = None
        for (k, b), (lh, sel) in st.items():
            if k < 2:
                continue
            c = _card(sel)
            if kind == "cheap":
                if c["cost"] > CHEAP:
                    continue
                score = lh
            else:
                if k > 6:
                    continue
                pen = sum(REUSE for l in sel if l["gameId"] in used) * 100
                score = (c["hit"] - c["cost"]) + 0.15 * c["hit"] - pen
            if best is None or score > best[0]:
                best = (score, c)
        if not best:
            break
        c = best[1]
        c["reused"] = sum(1 for l in c["legs"] if l["gameId"] in used)
        if any(set(x["gameId"] for x in c["legs"]) == set(l["gameId"] for l in prev["legs"]) for prev in out for x in [c["legs"][0]]):
            # identical games again: stop rather than show a near-copy
            if any({l["gameId"] + l["team"] for l in prev["legs"]} == {l["gameId"] + l["team"] for l in c["legs"]} for prev in out):
                break
        out.append(c)
        used |= {l["gameId"] for l in c["legs"]}
    return out


MID_LO, MID_HI = 50.0, 70.0   # "mid-tier" leg: a 50-70% team (Rick 2026-11-26)
CALL_BONUS = {"Value": 2.0, "Wait": 1.0, "Pass": 0.0, "Sell": -5.0}


def mid_score(l):
    """Strongest mid-tier leg: win chance first (backtest: the strongest one hit 36% in 4-leg combos vs 26% for
    the weakest), then a small nudge for value vs its price and for its Buy/Wait call."""
    return l["est"] + 0.5 * (l["est"] - l["price"]) + CALL_BONUS.get(l.get("call"), 0.0)


def mid_tier(legs, k):
    """k-leg combo = the k-1 most likely winners (one per game) + the best 50-70% team from another game.
    Also returns the all-favourites k-leg combo for comparison. Never invents: needs real prices on every leg."""
    favs, seen = [], set()
    for l in sorted(legs, key=lambda l: (-l["est"], l["price"])):
        if l["gameId"] not in seen and l["est"] >= 50:
            favs.append(l)
            seen.add(l["gameId"])
    if len(favs) < k - 1:
        return None
    top = favs[:k - 1]
    used = {l["gameId"] for l in top}
    cands = [l for l in legs if l["gameId"] not in used and MID_LO <= l["est"] <= MID_HI]
    if not cands:
        return None
    mid = max(cands, key=mid_score)
    c = _card(top + [mid])
    c["mid"] = mid["team"]
    if len(favs) >= k and {l["team"] for l in favs[:k]} != {l["team"] for l in c["legs"]}:
        a = _card(favs[:k])
        c["allFav"] = {"hit": a["hit"], "cost": a["cost"], "teams": [l["team"] for l in a["legs"]]}
    return c


def build(board):
    """-> {"thisWeek": {"cheap": [...], "value": [...]}, "nextWeek": {...}, "record": {...}}"""
    res = {}
    for key, gl in (("thisWeek", board.get("games")), ("nextWeek", board.get("nextWeek"))):
        legs = legs_for(gl)
        res[key] = {"cheap": pick(legs, "cheap"), "value": pick(legs, "value"), "legs": len(legs),
                    "midTier": [c for c in (mid_tier(legs, k) for k in (4, 5)) if c]}
    res["record"] = track(board, res["thisWeek"])
    res["cheapMax"] = CHEAP
    return res


def track(board, this_week):
    """Log this week's suggestions (latest version before the first leg kicks off), grade when every leg is final."""
    lg = load_json(LOG, {}) or {}
    rows = lg.setdefault("rows", {})
    games = {g["id"]: g for g in board.get("games", [])}
    wk = f"{board.get('season')}-w{board.get('week')}"
    for kind in ("cheap", "value", "midTier"):
        for i, c in enumerate(this_week.get(kind) or []):
            k = f"{wk}|{kind}|{i + 1}"
            r = rows.get(k)
            started = r and any((games.get(l["gameId"]) or {}).get("state") != "pre" for l in r["legs"])
            if not started:
                rows[k] = {"kind": kind, "hit": c["hit"], "cost": c["cost"], "legs": [{"gameId": l["gameId"], "team": l["team"]} for l in c["legs"]],
                           "at": iso()}
    for k, r in rows.items():
        if r.get("won") is not None or not k.startswith(wk):
            continue
        gs = [games.get(l["gameId"]) for l in r["legs"]]
        if all(g and g.get("state") == "post" and g.get("result") for g in gs):
            r["won"] = all(g["result"].get("winner") == l["team"] for g, l in zip(gs, r["legs"]))
    lg["at"] = iso()
    save_json(LOG, lg, compact=True)
    out = {}
    for kind in ("cheap", "value", "midTier"):
        xs = [r for r in rows.values() if r["kind"] == kind and r.get("won") is not None]
        out[kind] = {"n": len(xs), "won": sum(1 for r in xs if r["won"]),
                     "expected": round(sum(r["hit"] for r in xs) / 100, 1),
                     "net": round(sum((100 - r["cost"]) if r["won"] else -r["cost"] for r in xs), 1)}
    return out
