"""Combo search (Section 8). Exhaustive over every game set and every side combination.

Hit % = product of fair probs. Fair price = hit% x 100. Max pay = fair price - 2c buffer.
Cost = product of market prices. Edge = max pay - cost. One leg per game (same-game legs are
correlated and never multiplied as if independent).
"""
import itertools
import math

import numpy as np

from . import config as C


def leg_label(leg):
    tags = []
    if leg.get("fair") is not None and leg["fair"] >= C.SHOE_IN:
        tags.append("Shoe-in")
    if leg.get("lopsided"):
        tags.append("Lopsided")
    if leg.get("tdDip"):
        tags.append("TD dip")
    if leg.get("call") == "Pass":
        tags.append("Pass single")
    return tags


def sanitize(leg):
    """Shoe-in label ONLY for genuine favourites with fair >= 70c (also used on stored legs)."""
    tags = [t for t in leg.get("tags", []) if t != "Shoe-in"]
    if leg.get("fair") is not None and leg["fair"] >= C.SHOE_IN:
        tags.insert(0, "Shoe-in")
    leg["tags"] = tags
    return leg


def _best_for_size(games, k, top_n=1):
    """games: list of (legA, legB) with fair/price in cents. Returns best combos + counts."""
    n = len(games)
    if n < k:
        return [], 0, n
    fa = np.array([[g[0]["fair"], g[1]["fair"]] for g in games], dtype=float) / 100.0
    pa = np.array([[g[0]["price"], g[1]["price"]] for g in games], dtype=float) / 100.0
    bits = ((np.arange(2 ** k)[:, None] >> np.arange(k)[None, :]) & 1)  # (2^k, k)
    best = []  # (edge, subset, sides)
    checked = 0
    subsets = list(itertools.combinations(range(n), k))
    chunk = max(1, 2_000_000 // (2 ** k * k))
    for s0 in range(0, len(subsets), chunk):
        sub = np.array(subsets[s0:s0 + chunk])            # (m, k)
        f = fa[sub[:, None, :], bits[None, :, :]]          # (m, 2^k, k)
        p = pa[sub[:, None, :], bits[None, :, :]]
        hit = f.prod(axis=2) * 100.0
        cost = p.prod(axis=2) * 100.0
        edge = (hit - C.FEE_BUFFER_COMBO) - cost
        checked += edge.size
        flat = edge.ravel()
        take = min(top_n, flat.size)
        idx = np.argpartition(-flat, take - 1)[:take]
        for j in idx:
            si, bi = divmod(int(j), 2 ** k)
            best.append((float(flat[j]), tuple(sub[si]), tuple(bits[bi])))
        best.sort(key=lambda x: -x[0])
        best = best[:top_n]
    return best, checked, n


def build_card(games, subset, sides, k):
    legs = []
    for gi, side in zip(subset, sides):
        leg = dict(games[gi][side])
        legs.append(sanitize(leg))
    hit = math.prod(l["fair"] / 100 for l in legs) * 100
    cost = math.prod(l["price"] / 100 for l in legs) * 100
    maxpay = hit - C.FEE_BUFFER_COMBO
    return {"size": k, "legs": legs, "hit": round(hit, 2), "fair": round(hit, 2),
            "maxPay": round(maxpay, 2), "cost": round(cost, 2), "edge": round(maxpay - cost, 2),
            "profit": round(100 - cost, 2), "tier": tier(cost)}


def tier(cost):
    if cost < C.LOOK_DONT_BUY:
        return "look"       # highlighted, but 1c tick + fees make it nearly unplayable
    if cost <= C.GOOD_COMBO:
        return "good"
    if cost <= C.PREF_COMBO:
        return "pref"
    return "above"


def sizes_for(n):
    """Every combo size from 2 legs up to one leg per available game."""
    return list(range(C.COMBO_MIN, min(n, C.COMBO_MAX) + 1))


def search(pool_games, sizes=None):
    """pool_games: list of (legA, legB) with numeric fair & price. Returns {k: result}."""
    games = [g for g in pool_games if all(l.get("fair") is not None and l.get("price") for l in g)]
    out = {}
    for k in (sizes or sizes_for(len(games))):
        best, checked, n = _best_for_size(games, k)
        res = {"size": k, "checked": checked, "games": n}
        if not best:
            res["none"] = True
            res["note"] = f"{n} games left — need {k}"
        else:
            e, sub, sides = best[0]
            card = build_card(games, sub, sides, k)
            if card["cost"] <= card["maxPay"]:
                res["combo"] = card
            else:
                res["none"] = True
                res["closest"] = card
        out[str(k)] = res
    return out


def search_legs(legs, sizes=None):
    """Combined combos: a fixed leg pool (one side each). Exhaustive over leg subsets with
    one leg per game."""
    legs = [l for l in legs if l.get("fair") is not None and l.get("price")]
    out = {}
    for k in (sizes or sizes_for(len({l["gameId"] for l in legs}))):
        best, checked = None, 0
        for sub in itertools.combinations(range(len(legs)), k):
            if len({legs[i]["gameId"] for i in sub}) < k:
                continue
            hit = math.prod(legs[i]["fair"] / 100 for i in sub) * 100
            cost = math.prod(legs[i]["price"] / 100 for i in sub) * 100
            e = hit - C.FEE_BUFFER_COMBO - cost
            checked += 1
            if best is None or e > best[0]:
                best = (e, sub)
            if checked > 3_000_000:
                break
        res = {"size": k, "checked": checked, "games": len({l["gameId"] for l in legs})}
        if best is None:
            res["none"] = True
            res["note"] = f"{res['games']} qualifying legs — need {k}"
        else:
            sel = [sanitize(dict(legs[i])) for i in best[1]]
            hit = math.prod(l["fair"] / 100 for l in sel) * 100
            cost = math.prod(l["price"] / 100 for l in sel) * 100
            card = {"size": k, "legs": sel, "hit": round(hit, 2), "fair": round(hit, 2),
                    "maxPay": round(hit - 2, 2), "cost": round(cost, 2),
                    "edge": round(hit - 2 - cost, 2), "profit": round(100 - cost, 2), "tier": tier(cost)}
            if card["cost"] <= card["maxPay"]:
                res["combo"] = card
            else:
                res["none"] = True
                res["closest"] = card
        out[str(k)] = res
    return out
