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
