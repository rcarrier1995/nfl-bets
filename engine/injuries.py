"""Section 9 in-game key-injury impact formula + Section 10 NextQFactor, and ESPN play parsing.

Impact = Base_pos x RelianceFactor x MatchupFactor x TimeFactor x Confirmed  (points, negative hurts)
Fair cut ~= Impact x 2.5c.  QB separate: -3.5 x TimeFactor (cap -4.0).
"""
import re

from . import config as C

INJ_RE = re.compile(r"\b([A-Z]{2,3})-([A-Z][A-Za-z'\.\- ]+?) was injured during the play")
RET_RE = re.compile(r"Injury Update: ([A-Z]{2,3})-([A-Z][A-Za-z'\.\- ]+?) has returned to the game")
OUT_RE = re.compile(r"([A-Z]{2,3})-([A-Z][A-Za-z'\.\- ]+?) (?:has been ruled out|will not return|is out for the (?:game|remainder))")
PASS_RE = re.compile(r"(?:^|\)\s*|\.\s+)([A-Z][A-Za-z'\.\-]+(?:\s[A-Z][A-Za-z'\.\-]+)?) pass (?:short|deep|incomplete|to|intended)")


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def time_factor(seconds_left):
    """Logical cap, not a measured effect: Q1 ~0.9, Q4 ~0.35."""
    return round(0.25 + 0.75 * clamp(seconds_left, 0, 3600) / 3600.0, 3)


def seconds_left(period, clock_str):
    try:
        m, s = clock_str.split(":")
        rem = int(m) * 60 + int(float(s))
    except Exception:
        rem = 0
    if period > 4:
        return 0
    return (4 - period) * 900 + rem


def reliance_factor(pos, reliance):
    med = C.RELIANCE_MEDIAN.get(pos)
    if med is None or reliance is None:
        return 1.0
    # Spec text says 0.8 + 0.4*ratio, but its worked examples (share 0.25 -> 1.0) need 0.6 + 0.4*ratio
    # (=1.0 at the median). Using the version that reproduces the worked examples.
    return round(clamp(0.6 + 0.4 * reliance / med, 0.8, 1.2), 3)


def matchup_factor(pos, opp_team):
    """CB/S: opponent pass share; DL/LB: opponent run share. Offense: 1.0."""
    if not opp_team:
        return 1.0
    if pos in ("CB", "S") and opp_team.get("passShare") is not None:
        return round(clamp(0.7 + 0.6 * opp_team["passShare"], 0.7, 1.3), 3)
    if pos in ("DL", "LB") and opp_team.get("runShare") is not None:
        return round(clamp(0.7 + 0.6 * opp_team["runShare"], 0.7, 1.3), 3)
    return 1.0


def impact(ev, tables, secs_left_at_event):
    """Compute one confirmed-out event's impact with every factor shown (real numbers)."""
    team, name = ev["team"], ev["name"]
    key = f"{team}|{name}"
    prior = tables.get("player_prior", {}).get(key, {})
    roster = tables.get("roster", {}).get(key, {})
    bmap = tables.get("backup_map", {}).get(key)
    pos = prior.get("pos") or roster.get("pos") or ev.get("pos") or "?"
    starter = bmap is not None
    tf = time_factor(secs_left_at_event)
    flags = []
    if prior.get("early") or not prior:
        flags.append("early-season — reliance unmeasured" if prior else "no prior stats")
    gate = (bmap or {}).get("gate") or {"halve": False, "note": "no backup on chart — full impact"}
    if bmap is not None and not bmap.get("backup"):
        flags.append("no backup on chart")
    out = {"team": team, "name": name, "full": prior.get("full") or roster.get("full") or name, "pos": pos,
           "starter": starter, "q": ev["q"], "clock": ev.get("clock"), "tf": tf, "gate": gate, "flags": flags,
           "top10": prior.get("top10")}
    rel = prior.get("reliance")
    out["relianceText"] = _rel_text(prior)
    if pos == "QB":
        pts = C.QB_OUT_PTS * tf
        if gate.get("halve"):
            pts /= 2
        out.update({"base": C.QB_OUT_PTS, "rf": 1.0, "mf": 1.0, "impact": round(max(pts, -4.0), 2), "isQB": True})
        return out
    if not starter:
        out.update({"base": 0.0, "rf": 1.0, "mf": 1.0, "impact": 0.0, "note": "not a starter — no downgrade"})
        return out
    base = C.BASE_POS.get(pos, 0.0)
    rf = reliance_factor(pos, rel if rel is not None else C.RELIANCE_MEDIAN.get(pos))
    opp = tables.get("teams", {}).get(ev.get("opp"))
    mf = matchup_factor(pos, opp)
    pts = base * rf * mf * tf
    if gate.get("halve"):
        pts /= 2
    out.update({"base": base, "rf": rf, "mf": mf, "impact": round(pts, 2)})
    return out


def _rel_text(p):
    if not p:
        return "reliance unmeasured"
    bits = []
    if p.get("reliance") is not None and p.get("relianceLabel") and p["relianceLabel"] != "QB":
        bits.append(f"{p['relianceLabel']} {p['reliance']:.2f}")
    if p.get("pos") in ("WR", "TE") and p.get("targets"):
        bits.append(f"{p['targets']} targets")
    if p.get("pos") == "RB" and p.get("carries"):
        bits.append(f"{p['carries']} carries")
    if p.get("pos") == "QB" and p.get("attempts"):
        bits.append(f"{p['attempts']} att")
    if p.get("snapPct") is not None:
        bits.append(f"snap {p['snapPct'] * 100:.0f}%")
    if p.get("early"):
        bits.append("early-season — reliance unmeasured")
    return " · ".join(bits) or "reliance unmeasured"


def combine(impacts):
    """Do NOT sum: worst + 0.5 x second, cap total non-QB at -3.0 pts."""
    nonqb = sorted([i["impact"] for i in impacts if not i.get("isQB") and i["impact"] < 0])
    qb = sum(i["impact"] for i in impacts if i.get("isQB"))
    tot = 0.0
    if nonqb:
        tot = nonqb[0] + (0.5 * nonqb[1] if len(nonqb) > 1 else 0)
        tot = max(tot, -3.0)
    return round(tot + max(qb, -4.0), 2)


def parse_plays(summary):
    """Flatten ESPN summary drives -> plays with period, clock, text, type, team."""
    plays = []
    d = (summary or {}).get("drives") or {}
    drives = list(d.get("previous") or [])
    if d.get("current"):
        drives.append(d["current"])
    seen = set()
    for dr in drives:
        for p in dr.get("plays", []):
            if p.get("id") in seen:
                continue
            seen.add(p.get("id"))
            plays.append({"id": p.get("id"), "q": (p.get("period") or {}).get("number", 0),
                          "clock": (p.get("clock") or {}).get("displayValue", "0:00"),
                          "text": p.get("text", ""), "type": (p.get("type") or {}).get("text", ""),
                          "team": ((dr.get("team") or {}).get("abbreviation")),
                          "scoring": p.get("scoringPlay", False),
                          "away": p.get("awayScore"), "home": p.get("homeScore")})
    return plays


def track_injuries(plays, cur_q, final, abbr_map):
    """Injury mention -> nothing. Confirmed = no return by end of next quarter, or official out.
    Q4 'did not return' is censored: watch-only unless the player missed the rest of that quarter."""
    events = {}
    for i, p in enumerate(plays):
        t = p["text"]
        for m in INJ_RE.finditer(t):
            team, name = abbr_map(m.group(1)), m.group(2).strip()
            k = (team, name)
            if k not in events or events[k]["returned"]:
                events[k] = {"team": team, "name": name, "q": p["q"], "clock": p["clock"], "idx": i,
                             "returned": False, "official": False}
        for m in RET_RE.finditer(t):
            k = (abbr_map(m.group(1)), m.group(2).strip())
            if k in events:
                events[k]["returned"] = True
        for m in OUT_RE.finditer(t):
            k = (abbr_map(m.group(1)), m.group(2).strip())
            if k in events:
                events[k]["official"] = True
    # also count a return if the player's name shows up in a later play
    for k, e in events.items():
        if e["returned"]:
            continue
        nm = e["name"]
        for p in plays[e["idx"] + 1:]:
            if nm in p["text"] and "injured" not in p["text"]:
                e["returned"] = True
                break
    out = []
    for e in events.values():
        if e["returned"]:
            e["state"] = "returned"
        elif e["official"]:
            e["state"] = "confirmed"
        elif e["q"] <= 3 and (cur_q >= e["q"] + 2 or final):
            e["state"] = "confirmed"
        elif e["q"] >= 4 and final:
            e["state"] = "confirmed-censored"
        else:
            e["state"] = "watch"
        e["confirmedQ"] = (e["q"] + 1) if e["state"] == "confirmed" and not e["official"] else e["q"]
        out.append(e)
    return out


def passers_by_quarter(plays, abbr_map):
    """{team: {q: [passer names]}, plus '_seq': [(q, name), ...] in play order} (QB-change inference, with lag)."""
    res = {}
    for p in plays:
        if not p.get("team"):
            continue
        m = PASS_RE.search(p["text"])
        if not m:
            continue
        nm = m.group(1).replace(" ", "")
        team = abbr_map(p["team"])
        t = res.setdefault(team, {})
        lst = t.setdefault(p["q"], [])
        if nm not in lst:
            lst.append(nm)
        t.setdefault("_seq", []).append((p["q"], nm))
    return res


def qb_change(passers, team, tables):
    """Starter = first QB-position passer. A QB change = another QB takes over and the starter
    has not thrown since (a one-series cameo followed by the starter's return is not a change)."""
    seq = (passers.get(team) or {}).get("_seq", [])
    roster = tables.get("roster", {})
    prior = tables.get("player_prior", {})

    def is_qb(nm):
        return (prior.get(f"{team}|{nm}") or roster.get(f"{team}|{nm}") or {}).get("pos") == "QB"

    seq = [(q, nm) for q, nm in seq if is_qb(nm)]
    if not seq:
        return None, None
    starter = seq[0][1]
    last_starter = max(i for i, (_, nm) in enumerate(seq) if nm == starter)
    after = seq[last_starter + 1:]
    if not after:
        return starter, None
    q, nm = after[0]
    return starter, {"q": q, "from": starter, "to": nm}
