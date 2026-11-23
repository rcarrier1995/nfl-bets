"""Core checks for Section 16. Run: python -m pytest -q tests  (or python tests/test_core.py)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import combos, injuries as I, model as M  # noqa


def L(g, t, f, p, call="Pass"):
    leg = {"gameId": g, "team": t, "opp": "", "fair": f, "price": p, "call": call, "state": "pre"}
    leg["tags"] = combos.leg_label(leg)
    return leg


def test_wait_example():
    c = M.classify(70, 60)
    assert c["call"] == "Wait" and c["edge"] == 8.0 and c["buyAt"] == 53


def test_value_and_pass():
    assert M.classify(80, 60)["call"] == "Value"
    assert M.classify(62, 65)["call"] == "Pass"


def test_fee_is_two_cents_inside_range():
    assert all(M.fee_cents(p) == 2.0 for p in (1, 40, 50, 70, 85, 99))


def test_spread_to_fair():
    fa, fb, _ = M.fair_pair(6.0)       # 6-pt favourite -> ~69-70c with the fitted k=1.15
    assert 68 <= fa <= 71 and abs(fa + fb - 100) < 0.01


def test_injury_not_double_counted():
    qb = [{"team": "X", "player": "Q B", "short": "Q.B", "pos": "QB", "status": "Out", "starter": True}]
    assert M.injury_pts(qb, baseline_inj=[], line_move=0.5)[0] == -3.5      # fresh news, line hasn't moved
    assert M.injury_pts(qb, baseline_inj=[], line_move=3.0)[0] == 0.0       # line already moved
    assert M.injury_pts(qb, baseline_inj=qb, line_move=0.0)[0] == 0.0       # already out Thursday


def test_combo_exhaustive_16_and_picks_cheap_side():
    games = [(L("LVDEN", "DEN", 93, 90), L("LVDEN", "LV", 7, 11)),
             (L("JAXNYG", "NYG", 80, 78), L("JAXNYG", "JAX", 20, 23)),
             (L("MINSF", "SF", 81, 81), L("MINSF", "MIN", 19, 20)),
             (L("CINWSH", "WSH", 36, 28), L("CINWSH", "CIN", 64, 73))]
    r = combos.search(games, (4,))["4"]
    assert r["checked"] == 16
    teams = [l["team"] for l in r["combo"]["legs"]]
    assert teams == ["DEN", "NYG", "SF", "WSH"]
    assert abs(r["combo"]["hit"] - 21.7) < 0.1 and abs(r["combo"]["cost"] - 15.9) < 0.1
    assert r["combo"]["cost"] <= r["combo"]["maxPay"]


def test_shoe_in_only_at_70():
    for f in (40, 33, 22, 69.9):
        assert "Shoe-in" not in combos.sanitize({"fair": f, "tags": ["Shoe-in"]})["tags"]
    assert "Shoe-in" in combos.sanitize({"fair": 70, "tags": []})["tags"]


def test_pass_leg_allowed_and_tagged():
    assert "Pass single" in L("x", "A", 60, 50)["tags"]


def test_injury_worked_examples():
    q2 = I.time_factor(I.seconds_left(2, "7:30"))
    q1 = I.time_factor(I.seconds_left(1, "7:30"))
    wr = -2.0 * I.reliance_factor("WR", 0.25)
    assert -1.6 < wr * q2 < -1.3          # ~ -1.4 -> watch only
    assert -2.0 < wr * q1 < -1.8          # ~ -1.9 -> cut ~5c
    assert abs(I.matchup_factor("CB", {"passShare": 0.65}) - 1.09) < 1e-6
    assert -2.6 < -3.5 * q2 < -2.4        # QB out Q2 ~ -2.5


def test_combine_not_summed():
    imps = [{"impact": -2.0}, {"impact": -1.5}, {"impact": -1.0}]
    assert I.combine(imps) == -2.75
    assert I.combine([{"impact": -3.0}, {"impact": -3.0}]) == -3.0


def test_injury_confirmation_gate():
    plays = [{"q": 1, "clock": "10:00", "text": "X run. NYG-A.Bee was injured during the play.", "type": "Rush", "team": "NYG"},
             {"q": 2, "clock": "9:00", "text": "pass to C.Dee", "type": "Pass", "team": "NYG"}]
    ev = I.track_injuries(plays, 2, False, lambda a: a)
    assert ev[0]["state"] == "watch"                 # never fire on first mention
    ev = I.track_injuries(plays, 3, False, lambda a: a)
    assert ev[0]["state"] == "confirmed"             # no return by end of next quarter


def test_replay_live_plus_upcoming_combo():
    from tests.replay import replay
    b = replay()
    r = b["combos"]["standard"]["4"]
    assert b["combos"]["poolGames"] == 4               # 2 live + 2 scheduled, no finals
    assert r["checked"] == 16
    best = r.get("combo") or r.get("closest")
    assert best and len(best["legs"]) == 4
    assert {l["state"] for l in best["legs"]} == {"in", "pre"}   # live + upcoming mixed
    if r.get("combo"):
        assert r["combo"]["edge"] > 0
    else:
        assert r["none"] is True                         # never forced
    assert all(l["state"] != "post" for l in b["combos"]["pool"])


def test_slow_price_detects_kalshi_lag():
    from datetime import datetime, timezone, timedelta
    from engine.lag import detect
    now = datetime(2026, 11, 22, 17, 0, tzinfo=timezone.utc)
    t = lambda m: (now - timedelta(minutes=m)).isoformat()
    rows = [[t(50), -3.0, 40, 62], [t(5), -6.0, 40, 63]]       # home moved 3 pts, Kalshi +1c
    lag = detect(rows, now)
    assert lag and lag["side"] == "home"
    rows = [[t(50), -3.0, 40, 62], [t(5), -6.0, 33, 69]]       # Kalshi kept up
    assert detect(rows, now) is None


def test_combos_any_size_from_two():
    from engine import combos as CB
    pool = [({"gameId": str(i), "team": f"A{i}", "fair": 60, "price": 55},
             {"gameId": str(i), "team": f"B{i}", "fair": 40, "price": 45}) for i in range(5)]
    r = CB.search(pool)
    assert sorted(map(int, r)) == [2, 3, 4, 5]
    assert r["2"]["checked"] == 10 * 4


def test_best_time_lines():
    from engine.timing import best_time, threshold
    assert threshold(70) == 53                     # 70 - 53 - 2 = 15
    assert best_time({"state": "pre", "price": 50, "call": "Value", "edge": 18, "fair": 70}).startswith("Now")
    assert best_time({"state": "pre", "price": 60, "call": "Wait", "edge": 9, "fair": 71, "buyAt": 54}) == "When it drops to 54¢ before kickoff — phone alert"
    assert best_time({"state": "pre", "price": 60, "call": "Pass", "edge": 0, "fair": 62}) == "Only at 45¢ or less"
    assert best_time({"state": "pre", "price": 5, "call": "Pass", "edge": 0, "fair": 10}) == "No price works"
    assert best_time({"state": "in", "price": 40, "alertsOff": "late Q4"}).startswith("Too late")
    assert best_time({"state": "post"}) is None


def test_news_alerts_once_and_seeded():
    from datetime import datetime, timezone
    from engine import run as R
    sent = []
    R.P.send = lambda t, b, **k: sent.append(t)
    now = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
    c = lambda t, side: {"gameId": "1", "team": t, "state": "pre", "price": 60, "fair": 62, "key": t, "liveLines": []}
    g = {"id": "1", "short": "A @ B", "away": "A", "home": "B", "state": "pre", "kickoff": "2026-11-23T18:00Z",
         "injuries": [], "teams": {"away": c("A", "away"), "home": c("B", "home")}}
    board = {"games": [g], "calls": [g["teams"]["away"], g["teams"]["home"]]}
    rs = {}
    g["injuries"] = [{"team": "A", "pos": "WR", "player": "Old News", "status": "Out", "starter": True}]
    R.news_alerts(board, rs, now)
    assert sent == []                                   # first run only records
    g["injuries"].append({"team": "A", "pos": "QB", "player": "Joe Q", "status": "Out", "starter": True})
    R.news_alerts(board, rs, now)
    R.news_alerts(board, rs, now)
    assert len(sent) == 1 and "Joe Q" in sent[0]


def test_odds_consensus_and_spread():
    from engine.odds import consensus_from, spread_from_p
    from engine.model import fair_pair
    ev = [{"home_team": "Denver Broncos", "away_team": "Las Vegas Raiders", "commence_time": "x",
           "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
               {"name": "Denver Broncos", "price": -300}, {"name": "Las Vegas Raiders", "price": 250}]}]},
                          {"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
               {"name": "Denver Broncos", "price": -320}, {"name": "Las Vegas Raiders", "price": 260}]}]}]}]
    c = consensus_from(ev)["LV@DEN"]
    assert c["books"] == 2 and c["pinnacle"] and 0.72 < c["pHome"] < 0.76
    sp = spread_from_p(c["pHome"])
    assert sp < 0                                   # home favoured
    h, a, _ = fair_pair(-sp)                        # home margin = -spread; round-trips
    assert abs(h - c["pHome"] * 100) < 0.6


def test_index_stamp_current():
    from engine.stamp import version
    import os
    html = open(os.path.join(os.path.dirname(__file__), "..", "docs", "index.html")).read()
    assert f"style.css?v={version()}" in html and f"app.js?v={version()}" in html, "run: python -m engine.stamp"


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f()
            print("ok", k)


def test_combo_markup_estimate():
    from engine import config as C
    assert C.combo_markup(2) == 1.0 and abs(C.combo_markup(8) - 1.07) < 1e-9 and abs(C.combo_markup(10) - 1.22) < 1e-9
    legs = [L(i, f"T{i}", 80, 60) for i in range(9)]
    card = combos.card_from(legs, 80 ** 9 / 100 ** 8, 60 ** 9 / 100 ** 8)
    assert card["est"] > card["cost"] and card["edge"] == round(card["maxPay"] - card["est"], 2)


def test_our_live_wp_sane():
    from engine import profiles as PF
    if not PF._wp_cache():
        return
    up = PF.live_wp(0.5, 14, 300, True, 40, 0)
    down = PF.live_wp(0.5, -14, 300, True, 40, 0)
    even = PF.live_wp(0.7, 0, 3500, None, 75, 0)
    assert up > 0.95 and down < 0.05 and 0.6 < even < 0.8


def test_no_pushes_from_local_runs(monkeypatch):
    import importlib
    from engine import push as P
    importlib.reload(P)          # another test swaps P.send for a recorder
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("NFL_PUSH", raising=False)
    assert P.send("t", "b") is False


def test_matchup_lines_use_real_ranks():
    from engine import profiles as PF
    PF._prof = {"AAA": {"rank": {"passOff": 2, "passDef": 10, "rushOff": 16, "rushDef": 16, "sackRate": 16, "sackAllowed": 16,
                                 "stuffRate": 16, "stuffAllowed": 16, "q4For": 16, "q4Against": 16, "q1For": 16,
                                 "q1Against": 16, "h2h1": 2}, "fumLuck": 0, "h2h1": 0.1},
                "BBB": {"rank": {"passOff": 20, "passDef": 30, "rushOff": 16, "rushDef": 16, "sackRate": 16, "sackAllowed": 16,
                                 "stuffRate": 16, "stuffAllowed": 16, "q4For": 16, "q4Against": 16, "q1For": 16,
                                 "q1Against": 16, "h2h1": 16}, "fumLuck": 0, "h2h1": 0}}
    PF._stud = {"rows": []}
    out = PF.matchup_lines("AAA", "BBB")
    assert any("AAA pass attack (2nd) vs BBB pass D (30th)" in x for x in out)
    assert PF.adjust_pts("AAA", "BBB") == (0.0, [])
    PF._prof = PF._stud = None


def test_sell_check():
    from engine import model as M
    assert M.sell_check(60, 80)["edge"] == 18.0      # 80 - 60 - 2c fee
    assert M.sell_check(60, 75) is None               # 13c, under the 15c bar
    assert M.sell_check(None, 80) is None and M.sell_check(60, None) is None


def test_search_safe_prefers_winners():
    from engine import combos as CB
    mk = lambda gid, t, f, p: {"gameId": gid, "team": t, "opp": "X", "fair": f, "price": p, "state": "pre"}
    pool = [(mk(1, "A", 80, 78), mk(1, "a", 20, 22)),
            (mk(2, "B", 62, 50), mk(2, "b", 38, 50)),   # big value but less likely
            (mk(3, "C", 75, 74), mk(3, "c", 25, 26)),
            (mk(4, "D", 45, 30), mk(4, "d", 55, 70))]   # nothing at 60%+
    r = CB.search_safe(pool)
    c = r["2"]["combo"]
    assert {l["team"] for l in c["legs"]} == {"A", "C"}      # highest hit that still fits max pay
    assert all(l["fair"] >= 60 for l in c["legs"])
    assert c["est"] <= c["maxPay"]


def test_expert_stats_profit_at_price():
    from engine import experts as E
    st = {"weeks": {"2026-w1": {"cbs": {"su": {"experts": ["A", "B"], "games": [
        {"away": "X", "home": "Y", "picks": {"A": {"team": "X", "line": "+200"}, "B": {"team": "Y", "line": "-250"}}}]}}}},
          "results": {"2026-w1": {"X@Y": "X"}}}
    s = E.stats(st)["experts"]
    assert s["A"]["w"] == 1 and abs(s["A"]["profit"] - 2.0) < 0.01     # +200 underdog paid 2 units
    assert s["B"]["w"] == 0 and s["B"]["profit"] == -1.0
    assert s["A"]["dog"][:2] == [1, 1] and s["B"]["fav"][:2] == [1, 0]


def test_watch_track_fade_bets_other_side(tmp_path, monkeypatch):
    from engine import watch as W
    monkeypatch.setattr(W, "LOG", str(tmp_path / "log.json"))
    g = {"id": "1", "short": "A @ B", "state": "pre", "teams": {"away": {"team": "A", "price": 30}, "home": {"team": "B", "price": 72}},
         "watch": [{"team": "B", "tag": W.TAGS["hot"], "kind": "fade", "why": "x"}, {"team": "B", "tag": W.TAGS["qbwr"], "kind": "good", "why": "y"}]}
    b = {"season": 2026, "week": 12, "games": [g]}
    W.track(b)
    g["state"], g["result"] = "post", {"winner": "A", "tie": False}
    out = W.track(b)["live"]
    assert out[W.TAGS["hot"]]["w"] == 1 and out[W.TAGS["hot"]]["price"] == 30      # bet on A at A's price
    assert out[W.TAGS["qbwr"]]["w"] == 0 and out[W.TAGS["qbwr"]]["n"] == 1
    assert W._pct_rank({"x": 1, "y": 2, "z": 3})["z"] > W._pct_rank({"x": 1, "y": 2, "z": 3})["x"]


def test_top_combos_under_10c_and_spread_out():
    from engine import topcombos as T
    legs = []
    for i in range(12):
        p = 60 + i * 2
        legs.append({"gameId": str(i), "team": f"F{i}", "opp": f"D{i}", "price": p, "fair": p + 1, "est": p + 1, "dog": False, "why": []})
        legs.append({"gameId": str(i), "team": f"D{i}", "opp": f"F{i}", "price": 100 - p, "fair": 99 - p, "est": 99 - p, "dog": True, "why": []})
    cheap = T.pick(legs, "cheap")
    assert len(cheap) == 3 and all(c["cost"] <= 10 for c in cheap)
    assert all(len({l["gameId"] for l in c["legs"]}) == c["size"] for c in cheap)        # one leg per game
    assert not any(l["dog"] for c in cheap for l in c["legs"])                           # no longshots
    assert cheap[1]["reused"] < cheap[1]["size"]
    assert all(c["conf"] in ("High", "Med", "Low") for c in T.pick(legs, "value"))


def test_backfilled_snapshots_repriced_with_current_model():
    from engine import backtest as BT, learning as LR
    snaps = {"2026-w11|1": {"backfilled": True, "spreadHome": -16.5, "home": "BUF", "away": "MIA",
                            "teams": {"BUF": {"fair": 78.8, "price": 91, "confidence": {"level": "Med"}},
                                      "MIA": {"fair": 21.2, "price": 9, "confidence": {"level": "High"}}}}}
    assert BT.refresh_backfilled(snaps) == ["2026-w11|1"]
    t = snaps["2026-w11|1"]["teams"]
    assert t["BUF"]["fair"] == 92.0 and t["MIA"]["confidence"]["level"] == "Low"
    assert BT.refresh_backfilled(snaps) == []          # idempotent
    L = {"graded": {"2026-w11|1": {"season": 2026, "week": 11}}, "windows": [{"season": 2026, "week": 11}, {"season": 2026, "week": 10}]}
    assert LR.regrade(L, ["2026-w11|1"]) == 1 and not L["graded"] and len(L["windows"]) == 1
