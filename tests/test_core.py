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


def test_combo_exhaustive_16_and_picks_cheap_side(monkeypatch):
    from engine import config as C
    monkeypatch.setattr(C, "combo_markup", C._old_markup)   # tests the search, not the markup
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
    assert C.combo_markup(1) == 1.0 and C.combo_markup(2) == C.COMBO_MARKUP == C.combo_markup(10)   # ~26% (review 2026-11-23)
    assert C.combo_markup(12) > C.COMBO_MARKUP
    legs = [L(i, f"T{i}", 80, 60) for i in range(9)]
    card = combos.card_from(legs, 80 ** 9 / 100 ** 8, 60 ** 9 / 100 ** 8)
    assert card["est"] > card["cost"] and abs(card["edge"] - (card["maxPay"] - card["est"])) <= 0.011


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


def test_search_safe_prefers_winners(monkeypatch):
    from engine import config as C
    monkeypatch.setattr(C, "combo_markup", C._old_markup)
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
    assert all(c["conf"] in ("A", "B", "C", "F") for c in T.pick(legs, "value"))


def test_backfilled_snapshots_repriced_with_current_model():
    from engine import backtest as BT, learning as LR
    snaps = {"2026-w11|1": {"backfilled": True, "spreadHome": -16.5, "home": "BUF", "away": "MIA",
                            "teams": {"BUF": {"fair": 78.8, "price": 91, "confidence": {"level": "B"}},
                                      "MIA": {"fair": 21.2, "price": 9, "confidence": {"level": "A"}}}}}
    assert BT.refresh_backfilled(snaps) == ["2026-w11|1"]
    t = snaps["2026-w11|1"]["teams"]
    assert t["BUF"]["fair"] == 92.0 and t["MIA"]["confidence"]["level"] == "F"
    assert BT.refresh_backfilled(snaps) == []          # idempotent
    L = {"graded": {"2026-w11|1": {"season": 2026, "week": 11}}, "windows": [{"season": 2026, "week": 11}, {"season": 2026, "week": 10}]}
    assert LR.regrade(L, ["2026-w11|1"]) == 1 and not L["graded"] and len(L["windows"]) == 1


def test_stale_line_turns_buy_into_check_the_line():
    from datetime import datetime, timezone, timedelta
    from engine import lag
    now = datetime(2026, 11, 29, 12, tzinfo=timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")
    g = {"book": "DraftKings", "spreadHome": -3.0}
    c = {"call": "Value", "price": 40.0, "bid": 39.0, "fee": 2.0, "buyAt": 40, "why": "x"}
    rows = [[iso(now - timedelta(hours=8)), -3.0, 60, 46], [iso(now), -3.0, 60, 40]]
    lag.line_check(g, c, "home", rows, now)
    assert c["call"] == "Wait" and c["buyAt"] == 29 and "no consensus" in c["why"] and "Kalshi fell 6" in c["why"]
    c2 = {"call": "Value", "price": 40.0, "bid": 39.0, "fee": 2.0}
    lag.line_check({"book": "Consensus of 9 books", "spreadHome": -3.0}, c2, "home", rows[-1:], now)
    assert c2["call"] == "Value" and "lineCheck" not in c2


def test_price_archive_appends_only_changes(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from engine import archive as AR
    monkeypatch.setattr(AR, "FILE", str(tmp_path / "a.json"))
    g = {"id": "1", "away": "A", "home": "H", "kickoff": "k", "state": "pre", "espnSpread": -3, "total": 44.5,
         "teams": {"away": {"price": 40, "fair": 41}, "home": {"price": 61, "fair": 59}}}
    b = {"season": 2026, "week": 12, "games": [g]}
    now = datetime(2026, 11, 24, tzinfo=timezone.utc)
    AR.record(b, now); AR.record(b, now)
    g["teams"]["away"]["price"] = 38
    AR.record(b, now)
    g.update(state="in", period=1, clock="9:00", score={"away": 7, "home": 0})
    g["teams"]["away"]["liveFair"] = 55
    A = AR.record(b, now)
    assert len(A["1"]["pre"]) == 2 and A["1"]["pre"][0][1] == 40 and A["1"]["pre"][-1][1] == 38
    assert A["1"]["live"][0][3:5] == [7, 0]


def test_markup_shrinks_for_pricey_combos():
    # Rick's real quote: JAX+CIN+DAL legs 61.2c, Robinhood 60.1c -> near-zero markup on favourite combos
    from engine import config as C
    assert C.combo_markup(3, 61.2) < 1.03 and C.combo_markup(3, 5) > 1.15


def test_sanity_holds_bad_data():
    """Review 2026-11-25: odd prices or a stuck week put calls on hold instead of guessing."""
    import copy
    import json
    from datetime import datetime, timezone, timedelta
    from engine import sanity as SN
    now = datetime(2026, 11, 25, 4, 0, tzinfo=timezone.utc)
    g = lambda i, a, h, ko, st="pre": {"id": i, "away": a, "home": h, "kickoff": ko, "state": st}  # noqa
    c = lambda i, t, p, call="Value": {"key": f"w|{i}|{t}", "gameId": i, "team": t, "price": p, "state": "pre", "call": call}  # noqa
    good = {"week": 12, "games": [g("1", "GB", "LAR", "2026-11-26T01:00Z"), g("2", "CHI", "DET", "2026-11-26T18:00Z")],
            "calls": [c("1", "GB", 45), c("1", "LAR", 56, "Wait"), c("2", "CHI", 53), c("2", "DET", 47)],
            "top3": ["w|1|GB", "w|2|CHI"], "alerts": []}
    b = copy.deepcopy(good)
    assert SN.apply(b, now) == [] and b["dataCheck"]["ok"] and b["calls"][0]["call"] == "Value"
    b = copy.deepcopy(good)
    b["calls"][2]["price"] = 150
    probs = SN.apply(b, now)
    assert probs and b["calls"][2]["call"] == "Pass" and b["calls"][2]["dataHold"]
    assert b["calls"][0]["call"] == "Value" and b["top3"] == ["w|1|GB"]      # other game untouched
    b = copy.deepcopy(good)
    b["calls"][0]["price"] = 20                                                # 20 + 56 = 76c: off
    assert SN.apply(b, now) and b["calls"][1]["call"] == "Pass"
    b = copy.deepcopy(good)                                                    # week stuck: all final 3+ days ago
    for x in b["games"]:
        x["state"] = "post"
    later = now + timedelta(days=4)
    assert any("ended" in p for p in SN.apply(b, later))
    b = copy.deepcopy(good)
    b["games"][1]["home"] = "GB"
    assert any("twice" in p for p in SN.apply(b, now)) and all(x["call"] == "Pass" for x in b["calls"])
    b = json.load(open(os.path.join(os.path.dirname(__file__), "..", "docs", "data", "board.json")))
    SN.check(b, datetime.fromisoformat(b["generatedAt"].replace("Z", "+00:00")))   # live board shape works


def test_alarm_buzzes_once(tmp_path, monkeypatch):
    from engine import alarm as AL
    sent = []
    monkeypatch.setattr(AL, "FILE", str(tmp_path / "alarm.json"))
    monkeypatch.setattr(AL.P, "send", lambda t, b, **k: sent.append(t) or True)
    for _ in range(5):
        AL.tick_result(False)
    assert sent == ["App problem: updates failing"]
    AL.tick_result(True)
    AL.tick_result(True)
    assert sent[-1] == "App is updating again" and len(sent) == 2
    AL.data(["odd price for GB"])
    AL.data(["odd price for GB"])
    AL.data([])
    assert sent[2:] == ["Data looks off — calls on hold", "Data looks right again"]


def test_thin_market_note():
    from engine.board import thin_note
    assert thin_note(56, 55, 266000) is None                       # normal NFL market: quiet
    assert "sell only 37" in thin_note(42, 37, 500000)             # wide buy/sell gap
    assert "6,200 traded" in thin_note(50, 49, 6200)               # few trades
    assert thin_note(None, None, None) is None


def test_game_day_alert_and_gap_push(monkeypatch):
    from datetime import datetime, timezone
    from engine import run as R
    g = {"id": "1", "state": "pre", "kickoff": "2026-11-29T18:00Z"}
    calls = [{"key": "k|JAX", "team": "JAX", "opp": "TEN", "gameId": "1", "state": "pre", "price": 90, "fair": 88, "call": "Pass"},
             {"key": "k|TEN", "team": "TEN", "opp": "JAX", "gameId": "1", "state": "pre", "price": 11, "fair": 12, "call": "Pass",
              "bookP": 20.0, "bookGap": 9.0}]
    board = {"games": [g], "calls": calls, "topCombos": {"thisWeek": {"cheap": [{"legs": [{"team": "JAX"}, {"team": "CIN"}], "cost": 8.2, "oneIn": 9}]}}}
    sun = datetime(2026, 11, 29, 17, 0, tzinfo=timezone.utc)          # 11 AM Central, game day
    lines = R.top3_message(board, sun)
    assert lines[0] == "1 game today" and "JAX A+ 90c" in lines[1] and "JAX+CIN" in lines[-1]
    assert R.top3_message(board, datetime(2026, 11, 27, 17, 0, tzinfo=timezone.utc)) == []   # no game that day
    jobs = R.due_jobs(sun, {}, False, "2026-w12")
    assert "top3" in jobs and "top3" not in R.due_jobs(datetime(2026, 11, 29, 16, 0, tzinfo=timezone.utc), {}, False, "2026-w12")
    sent = []
    monkeypatch.setattr(R.P, "send", lambda t, b, **k: sent.append(t))
    rs = {}
    R.gap_alerts(board, rs)
    R.gap_alerts(board, rs)                                            # once per team per price
    assert sent == ["Gap: TEN 11c vs books 20%"]


def test_swing_alerts_push_once_and_grade(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from engine import run as R
    sent = []
    monkeypatch.setattr(R.P, "send", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(R, "SWING_LOG", str(tmp_path / "s.json"))
    now = datetime.now(timezone.utc)

    def b(wp, state="in"):
        return {"games": [{"id": "1", "short": "CIN @ WSH", "state": state, "home": "WSH", "away": "CIN", "period": 4,
                           "clock": "5:00", "score": {"away": 10, "home": 17},
                           "teams": {"home": {"team": "WSH", "espnWP": wp, "price": 60},
                                     "away": {"team": "CIN", "espnWP": 100 - wp, "price": 41}}}]}
    rs = {}
    for wp in (50, 55, 75):
        R.swing_alerts(b(wp), rs, now)
    assert len(sent) == 1 and "WSH 55% -> 75%" in sent[0][0]
    R.swing_alerts(b(75, "post"), rs, now)
    log = R.load_json(R.SWING_LOG)
    assert log[0]["team"] == "WSH" and log[0]["won"] == 1


def test_drive_odds_file_shape():
    import json, os
    t = json.load(open(os.path.join(os.path.dirname(__file__), "..", "docs", "data", "drive_odds.json")))["t"]
    td, fg, n = t["5|1|goal"]
    assert 60 <= td <= 95 and n > 1000


def test_polymarket_parse_and_gap():
    """Polymarket moneyline -> per-team buy price; 3c+ gap vs Robinhood shown, smaller gaps hidden."""
    from unittest import mock
    from datetime import datetime, timezone
    from engine import feeds as FD
    rows = [{"slug": "nfl-gb-la-2026-11-26", "bestBid": 0.40, "bestAsk": 0.41, "volume24hr": 1000,
             "gameStartTime": "2026-11-26 01:00:00+00"},
            {"slug": "nfl-was-ari-2026-11-29", "bestBid": 0.05, "bestAsk": 0.95, "gameStartTime": None}]  # no real market
    with mock.patch.object(FD, "cached", lambda *a: (rows, False)):
        idx = FD.poly_index()
    assert set(idx) == {frozenset(("GB", "LAR"))}
    assert idx[frozenset(("GB", "LAR"))]["LAR"]["ask"] == 60.0
    g = {"id": "x", "away": "GB", "home": "LAR", "state": "pre",
         "teams": {"away": {"team": "GB", "price": 45.0}, "home": {"team": "LAR", "price": 61.0}}}
    with mock.patch.object(FD, "save_json", lambda *a, **k: None):
        FD.poly_attach(g, idx, datetime(2026, 11, 26, 1, tzinfo=timezone.utc), datetime(2026, 11, 25, tzinfo=timezone.utc))
    assert "4¢ dearer" in g["teams"]["away"]["polyLine"]
    assert g["teams"]["home"]["polyLine"] is None


def test_fpi_missing_stays_missing():
    from engine import feeds as FD
    g = {"state": "pre", "teams": {"away": {"team": "A", "price": 40}, "home": {"team": "B", "price": 60}}}
    FD.fpi_attach(g, {"predictor": {"homeTeam": {"gameProjection": "61.0"}}})   # away side missing
    assert g["teams"]["home"]["fpi"] is None and g["teams"]["away"]["fpi"] is None


def test_sportsbook_mode():
    """Sports Book mode: American odds -> implied %, Buy/Wait/Pass vs the book's odds, ESPN moneyline parse."""
    from engine.board import espn_ml
    assert M.american_imp(-150) == 60.0 and M.american_imp("+150") == 40.0 and M.american_imp(None) is None
    assert M.american_from_p(60) == -150 and M.american_from_p(40) == 150
    assert M.sb_classify(60, -150)["call"] == "Pass"          # fair == book: the vig makes it a Pass
    assert M.sb_classify(60, 200)["call"] == "Value"          # 60% at +200 (33%)
    w = M.sb_classify(50, 110)                                # 50% vs 47.6%... Pass; 58% vs 47.6 -> Wait
    assert w["call"] == "Pass"
    w = M.sb_classify(58, 110)
    assert w["call"] == "Wait" and w["betAt"] >= 135
    assert M.sb_classify(None, -110)["call"] == "Pass" and M.sb_classify(55, None)["imp"] is None
    odds = {"moneyline": {"home": {"close": {"odds": "-141"}}, "away": {"close": {"odds": "+119"}}}}
    assert espn_ml(odds) == {"home": -141, "away": 119}
    assert espn_ml({}) == {}


def test_consensus_best_price():
    from engine.odds import consensus_from
    ev = [{"home_team": "Denver Broncos", "away_team": "Las Vegas Raiders", "bookmakers": [
        {"key": "draftkings", "title": "DraftKings", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Denver Broncos", "price": -200}, {"name": "Las Vegas Raiders", "price": 170}]}]},
        {"key": "fanduel", "title": "FanDuel", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Denver Broncos", "price": -190}, {"name": "Las Vegas Raiders", "price": 160}]}]}]}]
    b = consensus_from(ev)["LV@DEN"]["best"]
    assert b["DEN"] == {"odds": -190, "book": "FanDuel"} and b["LV"] == {"odds": 170, "book": "DraftKings"}


def test_playoff_weeks_get_their_own_numbers():
    from engine import fetch as F
    sb = {"season": {"year": 2026, "type": 3}, "week": {"number": 1},
          "events": [{"id": "1", "season": {"year": 2026, "type": 3}, "week": {"number": 1}},
                     {"id": "pb", "season": {"year": 2026, "type": 3}, "week": {"number": 4}}]}
    tbd = {"id": "t", "season": {"year": 2026, "type": 3}, "week": {"number": 2},
           "competitions": [{"competitors": [{"team": {"abbreviation": "TBD"}}, {"team": {"abbreviation": "TBD"}}]}]}
    sb["events"].append(tbd)
    F.normalize_scoreboard(sb)
    assert sb["week"]["number"] == 19 and sb["events"][0]["week"]["number"] == 19
    assert [e["id"] for e in sb["events"]] == ["1"]                         # Pro Bowl dropped
    F.normalize_scoreboard(sb)                                              # running twice changes nothing
    assert sb["week"]["number"] == 19
    reg = {"season": {"year": 2026, "type": 2}, "week": {"number": 12}, "events": []}
    assert F.normalize_scoreboard(reg)["week"]["number"] == 12
    assert F.week_label(12) == "Week 12" and F.week_label(19) == "Wild Card" and F.week_label(22) == "Super Bowl"
    assert F.ESPN_POST[22] == 5 and F.ESPN_POST[21] == 3


def test_game_day_alert_on_every_game_day(monkeypatch):
    from datetime import datetime, timezone
    from engine import run as R
    monkeypatch.setattr(R, "load_tables", lambda: {"ok": True, "week": 12})
    wed_kick = datetime(2026, 11, 26, 1, 0, tzinfo=timezone.utc)            # Wed 7 PM Central
    fri_kick = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)           # Fri 2 PM Central
    kicks = [wed_kick, fri_kick]
    wed11 = datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc)              # Wed 11 AM Central
    assert "top3" in R.due_jobs(wed11, {}, False, "2026-w12", kickoffs=kicks)
    assert "top3" in R.due_jobs(datetime(2026, 11, 27, 17, 5, tzinfo=timezone.utc), {}, False, "2026-w12", kickoffs=kicks)
    tue11 = datetime(2026, 11, 24, 17, 0, tzinfo=timezone.utc)              # no game Tuesday
    assert "top3" not in R.due_jobs(tue11, {}, False, "2026-w12", kickoffs=kicks)
    # inactives refresh 90 min before the first kickoff of the day
    assert "inactives" in R.due_jobs(datetime(2026, 11, 27, 18, 35, tzinfo=timezone.utc), {}, False, "2026-w12", kickoffs=kicks)
    assert "inactives" not in R.due_jobs(datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc), {}, False, "2026-w12", kickoffs=kicks)
    # London game 8:30 AM Central: alert at 7 AM, not after kickoff
    lon = datetime(2026, 10, 4, 13, 30, tzinfo=timezone.utc)
    assert "top3" in R.due_jobs(datetime(2026, 10, 4, 12, 5, tzinfo=timezone.utc), {}, False, "2026-w12", kickoffs=[lon])
    assert "top3" not in R.due_jobs(datetime(2026, 10, 4, 16, 5, tzinfo=timezone.utc), {}, False, "2026-w12", kickoffs=[lon])
    assert R.next_check(datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc), kicks) == "Next check: Thu 12pm"
    assert R.next_check(datetime(2026, 11, 26, 20, 0, tzinfo=timezone.utc), kicks) == "Next check: Fri 11am"


def test_lag_study_counts_only_real_gaps():
    from engine import lag_study as L
    A, P = {}, {}
    for i in range(30):
        wk = 12 + i % 3
        # away priced 40 while books say 46 (6c gap); closes at 44; away wins 2 of 3
        A[str(i)] = {"season": 2026, "week": wk, "kickoff": "2026-12-01T18:00Z", "final": [24, 17] if i % 3 else [10, 20],
                     "pre": [["2026-11-30T10:00:00Z", 40.0, 61.0, 1.5, 44.5, 46.0, 54.0],
                             ["2026-12-01T17:50:00Z", 44.0, 57.0, 1.0, 44.5, 46.0, 54.0],
                             ["2026-12-01T19:00:00Z", 60.0, 41.0, 1.0, 44.5, 46.0, 54.0]]}   # after kickoff: ignored
    r = L.study(A, P)
    assert len(r["weeks"]) == 3
    assert r["signals"]["book5"]["n"] == 30 and r["signals"]["book8"]["n"] == 0 and r["signals"]["poly3"]["n"] == 0
    assert r["signals"]["book5"]["avgClv"] == 4.0
    assert r["signals"]["book5"]["holds"] is True and "real edge" in r["summary"]
    assert L.study({}, {})["summary"].startswith("Waiting")


def test_sync_newest_wins_and_quotes_checked():
    import json as J
    from engine import sync as S
    stores, quotes = {}, []
    sf = lambda c: stores.setdefault(c, {"bets": {}, "deleted": {}, "quotes": []})
    msg = lambda d: {"message": J.dumps({"v": 1, "code": "AB12CD34", **d})}
    msgs = [msg({"op": "put", "bet": {"id": "b1", "upd": "2026-11-25T10:00Z", "team": "JAX", "price": 90, "evil": 1}}),
            msg({"op": "put", "bet": {"id": "b1", "upd": "2026-11-25T09:00Z", "team": "JAX", "price": 80}}),   # older: ignored
            msg({"op": "put", "bet": {"id": "b2", "upd": "2026-11-25T10:00Z", "team": "CIN", "price": 150}}),  # bad price
            msg({"op": "put", "bet": {"id": "b3", "upd": "2026-11-25T10:00Z", "team": "DAL", "price": 80}}),
            msg({"op": "del", "id": "b3", "upd": "2026-11-25T11:00Z"}),
            msg({"op": "quote", "quote": {"legs": 9.0, "quote": 11.0, "n": 4, "at": "2026-11-25T12:00Z"}}),
            msg({"op": "quote", "quote": {"legs": 9.0, "quote": 60.0, "n": 4, "at": "2026-11-25T12:01Z"}}),    # typo: ignored
            {"message": J.dumps({"v": 1, "code": "bad", "op": "put", "bet": {"id": "x", "price": 5}})}]
    assert S.apply(msgs, sf, quotes) == {"AB12CD34"}
    st = stores["AB12CD34"]
    assert st["bets"]["b1"]["price"] == 90 and "evil" not in st["bets"]["b1"]
    assert "b2" not in st["bets"] and "b3" not in st["bets"] and st["deleted"]["b3"] == "2026-11-25T11:00Z"
    assert len(quotes) == 1 and quotes[0]["quote"] == 11.0 and len(st["quotes"]) == 1
    assert S.apply([msg({"op": "put", "bet": {"id": "b3", "upd": "2026-11-25T10:30Z", "price": 80}})], sf, quotes) == set()
    assert "b3" not in st["bets"]                                       # deleted later than this edit


def test_extra_books_parse_and_sharp_line():
    """PinnWire / OddsPapi / TheRundown replies (documented shapes) -> de-vigged win % per team, Pinnacle line on card."""
    from unittest import mock
    from datetime import datetime, timezone
    from engine import books as BK
    T = BK.Teams({"GB": "Packers", "LAR": "Rams"})
    pw = {"events": [{"league_name": "NFL", "away": "Green Bay Packers", "home": "Los Angeles Rams",
                      "periods": {"num_0": {"money_line": {"away": 2.35, "home": 1.65}}}}]}
    with mock.patch.object(BK, "_get", lambda *a, **k: pw):
        p = BK.pinnwire("k", T)[frozenset(("GB", "LAR"))]["Pinnacle"]
    assert 41 < p["GB"] < 42 and abs(p["GB"] + p["LAR"] - 100) < 0.2
    rd = {"events": [{"teams": [{"team_id": 1, "mascot": "Packers", "is_away": True}, {"team_id": 2, "mascot": "Rams", "is_home": True}],
                      "markets": [{"market_id": 1, "participants": [
                          {"id": 1, "lines": [{"prices": {"19": {"price": 140}}}]},
                          {"id": 2, "lines": [{"prices": {"19": {"price": -160}}}]}]}]}]}
    with mock.patch.object(BK, "_get", lambda *a, **k: rd):
        r = BK.rundown("k", T, ["2026-11-25"])[frozenset(("GB", "LAR"))]["DraftKings"]
    assert r["LAR"] > r["GB"]
    g = {"away": "GB", "home": "LAR", "state": "pre",
         "teams": {"away": {"team": "GB", "price": 46.0}, "home": {"team": "LAR", "price": 58.0}}}
    BK.attach(g, {frozenset(("GB", "LAR")): {"Pinnacle": p}})
    assert "Robinhood 5¢ dearer" in g["teams"]["away"]["sharpLine"]
    assert g["teams"]["home"]["sharpLine"] is None


def test_extra_books_off_without_keys(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from engine import books as BK
    for k in BK.KEYS.values():
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(BK, "STATE_FILE", str(tmp_path / "b.json"))
    called = []
    monkeypatch.setattr(BK, "_get", lambda *a, **k: called.append(a) or {})
    now = datetime(2026, 11, 25, tzinfo=timezone.utc)
    assert BK.refresh({"GB": "Packers"}, [datetime(2026, 11, 27, tzinfo=timezone.utc)], now) == {}
    assert not called


def test_quota_schedule(monkeypatch):
    """Rick 2026-11-25: 20 min live, 30 min in the 2 h before kickoff, 9 AM + 6 PM CT otherwise, taps 30 min apart."""
    from datetime import datetime, timedelta, timezone
    from engine import quota as Q
    monkeypatch.delenv("NFL_FORCE_ODDS", raising=False)
    U = timezone.utc
    sun = datetime(2026, 11, 29, 18, 0, tzinfo=U)            # Sunday noon CT kickoff
    games = [(sun, "pre"), (sun + timedelta(hours=7, minutes=20), "pre")]
    # quiet Wednesday: 9 AM CT slot (15:00Z), not again until 6 PM CT
    wed9 = datetime(2026, 11, 25, 15, 5, tzinfo=U)
    assert Q.due(datetime(2026, 11, 25, 1, 0, tzinfo=U), wed9, games, 20, 30)
    assert not Q.due(wed9, wed9 + timedelta(hours=3), games, 20, 30)
    assert Q.due(wed9, datetime(2026, 11, 26, 0, 1, tzinfo=U), games, 20, 30)
    # 8:00 AM CT before any slot: nothing
    assert not Q.due(datetime(2026, 11, 25, 0, 30, tzinfo=U), datetime(2026, 11, 25, 14, 0, tzinfo=U), games, 20, 30)
    # pregame window: 30 min
    t = sun - timedelta(minutes=90)
    assert Q.window(games, t) == "pre"
    assert not Q.due(t - timedelta(minutes=20), t, games, 20, 30)
    assert Q.due(t - timedelta(minutes=31), t, games, 20, 30)
    # live: 20 min
    live = [(sun, "in"), (sun + timedelta(hours=7), "pre")]
    assert Q.due(sun, sun + timedelta(minutes=21), live, 20, 30)
    assert not Q.due(sun, sun + timedelta(minutes=15), live, 20, 30)
    # all games over this week: nothing, even at a slot
    done = [(sun, "post")]
    assert not Q.due(None, datetime(2026, 11, 30, 15, 5, tzinfo=U), done, 20, 30)
    # Refresh tap: allowed after 30 min, skipped inside 30 min
    monkeypatch.setenv("NFL_FORCE_ODDS", "1")
    assert Q.due(wed9, wed9 + timedelta(minutes=31), done, 20, 30)
    assert not Q.due(wed9, wed9 + timedelta(minutes=10), done, 20, 30)


def test_live_book_line():
    from datetime import datetime, timedelta, timezone
    from engine.odds import live_attach
    k = datetime(2026, 11, 29, 18, 0, tzinfo=timezone.utc)
    now = k + timedelta(hours=1)
    g = {"state": "in", "away": "GB", "home": "DET",
         "teams": {"away": {"team": "GB", "price": 40}, "home": {"team": "DET", "price": 61}}}
    cons = {"GB@DET": {"pHome": 0.65, "books": 8, "at": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")}}
    live_attach(g, cons, k, now)
    assert g["teams"]["away"]["liveBookLine"] == "Sportsbooks now (8): GB 35% · Robinhood 5¢ dearer"
    assert g["teams"]["home"]["liveBookLine"] == "Sportsbooks now (8): DET 65% · Robinhood 4¢ cheaper"
    cons["GB@DET"]["at"] = (k - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")   # pregame pull: not live
    live_attach(g, cons, k, now)
    assert g["teams"]["away"]["liveBookLine"] is None


def test_eqwd_boost_rule():
    from engine import watch as WT
    st = {"qb": {"q1": [0.25, 50], "q2": [0.05, 50]}, "dsr": {"AAA": 0.47, "BBB": 0.40}}
    WT._EQ.clear()
    WT._EQ[(2026, 12)] = (st, {"AAA": ("q1", "Al Able"), "BBB": ("q2", "Bo Baker")})
    WT._EQ["at"] = __import__("time").time()
    assert WT.eqwd_team(2026, 12, "AAA", "BBB") == "AAA"
    # listed starter out: no boost
    assert WT.eqwd_team(2026, 12, "AAA", "BBB", [{"player": "Al Able", "status": "Out"}]) is None
    # opponent also qualifies: no boost
    st["qb"]["q2"] = [0.2, 50]
    st["dsr"]["BBB"] = 0.46
    assert WT.eqwd_team(2026, 12, "AAA", "BBB") is None
    assert WT.EQWD_BOOST == 3
    WT._EQ.clear()


def test_mid_tier_combo():
    from engine import topcombos as T
    mk = lambda gid, team, est, price, call="Pass": {"gameId": gid, "team": team, "opp": "X", "price": price, "fair": est,
                                                    "est": est, "call": call, "why": [], "dog": price < 50}
    legs = [mk("g1", "A", 88, 90), mk("g2", "B", 82, 84), mk("g3", "C", 79, 80), mk("g4", "D", 76, 78),
            mk("g5", "E", 68, 64, "Value"), mk("g6", "F", 55, 56), mk("g6", "G", 45, 46), mk("g7", "H", 72, 73)]
    c = T.mid_tier(legs, 4)
    assert [l["team"] for l in c["legs"]] == ["A", "B", "C", "E"] and c["mid"] == "E"
    assert c["allFav"]["teams"] == ["A", "B", "C", "D"]
    assert T.mid_tier(legs[:2], 4) is None


def test_last_call_once_per_game():
    from datetime import datetime, timezone
    from engine import recaps as RC
    now = datetime(2026, 11, 29, 17, 30, tzinfo=timezone.utc)
    g1 = {"id": "g1", "state": "pre", "kickoff": "2026-11-29T18:00Z", "away": "AAA", "home": "BBB"}
    g2 = {"id": "g2", "state": "pre", "kickoff": "2026-11-29T21:25Z", "away": "CCC", "home": "DDD"}
    calls = [{"gameId": "g1", "team": "AAA", "state": "pre", "price": 60.0, "fair": 70.0, "call": "Value"},
             {"gameId": "g1", "team": "BBB", "state": "pre", "price": 42.0, "fair": 30.0, "call": "Pass"},
             {"gameId": "g2", "team": "CCC", "state": "pre", "price": 50.0, "fair": 50.0, "call": "Pass"},
             {"gameId": "g2", "team": "DDD", "state": "pre", "price": 52.0, "fair": 50.0, "call": "Pass"}]
    board = {"games": [g1, g2], "calls": calls}
    rs, sent = {"buySeen": {"g1": ["BBB"]}}, []
    lines = RC.last_call(board, rs, now, lambda t, b: sent.append((t, b)))
    assert any(l.startswith("Still BUY AAA 60c") for l in lines)
    assert any("BBB no longer a Buy: now Pass at 42c" in l for l in lines)
    assert len(sent) == 1 and sent[0][0].startswith("Last call: 1 game")
    assert RC.last_call(board, rs, now, lambda t, b: sent.append((t, b))) == [] and len(sent) == 1
    # nothing worth saying -> no push, but the game is still marked done
    now2 = datetime(2026, 11, 29, 21, 0, tzinfo=timezone.utc)
    assert RC.last_call(board, rs, now2, lambda t, b: sent.append((t, b))) == [] and len(sent) == 1 and "g2" in rs["lastCall"]


def test_weekly_recap():
    from engine import recaps as RC
    mk = lambda gid, away, home, winner, calls, pf: {"key": f"2026-w13|{gid}", "season": 2026, "week": 13, "away": away, "home": home,
                                                     "winner": winner, "tie": winner is None, "pick": max(calls, key=lambda t: calls[t]["fair"]),
                                                     "pickFair": pf, "final": f"{away} 1 — {home} 2", "calls": calls}
    c = lambda call, fair, price: {"call": call, "fair": fair, "price": price}
    g = {"a": mk("g1", "AAA", "BBB", "AAA", {"AAA": c("Value", 62, 50), "BBB": c("Pass", 38, 50)}, 62),
         "b": mk("g2", "CCC", "DDD", "CCC", {"CCC": c("Pass", 20, 22), "DDD": c("Pass", 80, 78)}, 80)}
    for r in g.values():
        r["right"] = r["pick"] == r["winner"]
    L = {"graded": g}
    store = {"bets": {"x": {"kind": "single", "team": "AAA", "gameId": "g1", "price": 50, "qty": 2, "result": "open", "season": 2026, "week": 13},
                      "y": {"kind": "combo", "legs": [{"gameId": "g1", "team": "AAA"}, {"gameId": "g2", "team": "DDD"}],
                            "price": 5, "qty": 100, "result": "open", "season": 2026, "week": 13}}}
    lines = RC.recap_lines(L, 2026, 13, store)
    assert lines[0] == "Picks 1-1" and "Buys 1-0 · +50c per contract" in lines and "A picks 0-1" in lines
    assert "Best: Buy AAA at 50c won (+50c)" in lines and lines[-2].startswith("Worst: DDD (80%) lost")
    assert lines[-1] == "Your bets 1-1 · -$4.00"   # +$1.00 single, -$5.00 combo
    rs, sent = {}, []
    RC.recap(L, 2026, 13, rs, lambda t, b: sent.append(t), store={})
    RC.recap(L, 2026, 13, rs, lambda t, b: sent.append(t), store={})
    assert sent == ["Week 13 recap"]


def test_rest_flag():
    from engine import rest as R
    d = {"children": [{"standings": {"entries": [
        {"team": {"abbreviation": "DEN"}, "stats": [{"name": "clincher", "displayValue": "*"}]},
        {"team": {"abbreviation": "KC"}, "stats": [{"name": "clincher", "displayValue": "e"}]}]}}]}
    codes = R.parse(d)
    assert codes == {"DEN": "*", "KC": "e"}
    g = {"id": "g1", "state": "pre", "away": "KC", "home": "DEN"}
    calls = [{"gameId": "g1", "team": "KC"}, {"gameId": "g1", "team": "DEN"}]
    board = {"week": 18, "season": 2026, "games": [g], "calls": calls}
    assert R.attach(board, fetch=lambda s: codes) == 2
    assert calls[1]["restLine"].startswith("DEN has locked the #1 seed") and "its starters" in calls[0]["restLine"]
    board["week"] = 12
    assert R.attach(board, fetch=lambda s: codes) == 0 and "restLine" not in calls[0]
