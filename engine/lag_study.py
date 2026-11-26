"""Kalshi 'slow price' test on our own saved prices (Rick approved 2026-11-25; first real run mid-December).

Question: when Robinhood/Kalshi sells a team cheaper than the sportsbooks (our fair, from the DraftKings
moneyline) or cheaper than Polymarket, is that a real edge or just noise?

Data (only real saved prices, nothing invented):
  state/price_archive.json  pregame rows [t, awayAsk, homeAsk, spread, total, awayFair, homeFair] + final score
  state/poly_history.json   rows [t, awayKalshi, awayPoly, homeKalshi, homePoly] (kept 60 days)

For each signal and gap size, take the FIRST moment per team per game the gap opens, "buy" at that ask, then
measure two things:
  CLV    = closing ask (last pregame row) - entry ask. Positive = the price came up to meet us. Low noise.
  profit = 100 if the team won (50 on a tie) - entry ask - 2c fee. Real result, noisy with few games.
A signal "holds" only with 25+ bets, average CLV >= +2c (t >= 2) AND profit per bet > 0.
Info only: this never changes a pick by itself. Rick decides after seeing the result.
"""
import math
import os

from . import config as C
from .fetch import load_json, save_json, iso

ARCH = os.path.join(C.STATE, "price_archive.json")
POLY = os.path.join(C.STATE, "poly_history.json")
OUT = os.path.join(C.STATE, "lag_study.json")
FEE = 2.0
GAPS = (3, 5, 8)
MIN_WEEKS = 3          # graded weeks with saved pregame prices before the first real run
MIN_N = 25


def _won(final, side):
    a, h = final
    if a == h:
        return 0.5
    return 1.0 if (a > h) == (side == "away") else 0.0


def _pre_rows(rows, kickoff):
    return [r for r in rows or [] if not kickoff or r[0] < kickoff]


def ready_weeks(A=None):
    A = A if A is not None else (load_json(ARCH, {}) or {})
    return sorted({(v.get("season"), v.get("week")) for v in A.values() if v.get("final") and len(v.get("pre") or []) >= 2})


def _summ(bets):
    n = len(bets)
    if not n:
        return {"n": 0}
    clv = [b["clv"] for b in bets]
    pr = [b["profit"] for b in bets]
    m = sum(clv) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in clv) / (n - 1)) if n > 1 else 0.0
    t = m / (sd / math.sqrt(n)) if sd > 0 else (99.0 if m > 0 else 0.0)
    out = {"n": n, "avgClv": round(m, 2), "clvT": round(t, 2), "profitPerBet": round(sum(pr) / n, 2),
           "won": round(sum(b["won"] for b in bets), 1), "avgPrice": round(sum(b["entry"] for b in bets) / n, 1)}
    out["holds"] = n >= MIN_N and m >= 2 and t >= 2 and out["profitPerBet"] > 0
    return out


def study(A=None, P=None):
    A = A if A is not None else (load_json(ARCH, {}) or {})
    P = P if P is not None else (load_json(POLY, {}) or {})
    res = {"at": iso(), "weeks": [f"{s}-w{w}" for s, w in ready_weeks(A)], "signals": {}}
    base = []
    sig = {f"book{g}": [] for g in GAPS}
    sig.update({f"poly{g}": [] for g in GAPS})
    for gid, v in A.items():
        if not v.get("final"):
            continue
        pre = _pre_rows(v.get("pre"), v.get("kickoff"))
        if len(pre) < 2:
            continue
        for side, ai, fi in (("away", 1, 5), ("home", 2, 6)):
            asks = [r for r in pre if r[ai] is not None]
            if not asks:
                continue
            close = asks[-1][ai]
            won = _won(v["final"], side)
            bet = lambda entry: {"game": gid, "side": side, "entry": entry, "clv": round(close - entry, 2),
                                 "profit": round(100 * won - entry - FEE, 2), "won": won}
            base.append(bet(asks[0][ai]))
            for g in GAPS:   # sportsbooks (our fair) above the Kalshi ask by g+
                hit = next((r for r in asks if r[fi] is not None and r[fi] - r[ai] >= g), None)
                if hit:
                    sig[f"book{g}"].append(bet(hit[ai]))
            prow = [r for r in _pre_rows(P.get(gid), v.get("kickoff"))]
            ki, pi = (1, 2) if side == "away" else (3, 4)
            for g in GAPS:   # Polymarket above the Kalshi ask by g+
                hit = next((r for r in prow if r[ki] is not None and r[pi] is not None and r[pi] - r[ki] >= g), None)
                if hit:
                    sig[f"poly{g}"].append(bet(hit[ki]))
    res["baseline"] = _summ(base)
    res["signals"] = {k: _summ(b) for k, b in sig.items()}
    held = [k for k, s in res["signals"].items() if s.get("holds")]
    res["held"] = held
    name = lambda k: ("sportsbooks" if k.startswith("book") else "Polymarket") + f" {k[4:]}c+ above Robinhood"
    if len(res["weeks"]) < MIN_WEEKS:
        res["summary"] = f"Waiting for data: {len(res['weeks'])} of {MIN_WEEKS} weeks of saved prices so far."
    elif held:
        res["summary"] = ("Kalshi slow-price test: real edge found when " + "; ".join(
            f"{name(k)} ({res['signals'][k]['n']} bets, price rose {res['signals'][k]['avgClv']}c on average, "
            f"{res['signals'][k]['profitPerBet']:+}c a bet)" for k in held) + ". Ask Claude to turn it into Buy calls.")
    else:
        best = max(res["signals"].items(), key=lambda kv: kv[1].get("avgClv", -99) if kv[1].get("n", 0) >= 10 else -99)
        b = best[1]
        res["summary"] = (f"Kalshi slow-price test ({len(res['weeks'])} weeks): no real edge yet. "
                          + (f"Best: {name(best[0])}, {b['n']} bets, price moved {b['avgClv']:+}c, {b['profitPerBet']:+}c a bet."
                             if b.get("n", 0) >= 10 else "Too few price gaps to judge.") + " Picks unchanged.")
    return res


def run_weekly(rs, now, push=True):
    """Called from the weekly check. Runs once per week once 3+ weeks of prices are saved; pushes the result."""
    A = load_json(ARCH, {}) or {}
    weeks = ready_weeks(A)
    if len(weeks) < MIN_WEEKS:
        return None
    tag = f"{weeks[-1][0]}-w{weeks[-1][1]}"
    if rs.get("lagStudy") == tag:
        return None
    res = study(A)
    prev = load_json(OUT, {}) or {}
    res["history"] = (prev.get("history") or [])[-11:] + [{"at": res["at"], "summary": res["summary"]}]
    save_json(OUT, res)
    rs["lagStudy"] = tag
    first = not prev.get("summary") or prev.get("summary", "").startswith("Waiting")
    if push and (first or set(res["held"]) != set(prev.get("held") or [])):
        from . import push as P
        P.send("Kalshi price test", res["summary"])
    return res
