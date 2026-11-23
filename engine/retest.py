"""Weekly re-test (runs Tuesday early morning, after Monday night's play-by-play is posted).

Downloads fresh free nflverse data, then re-runs every study with the newest games:
team & matchup grades, our live win model, game-total variance, timing, situations.
A grade moves prices only while it keeps beating the line in both the fit years and the
current season; this is where it can start or stop counting. Writes state/retest_log.json.
"""
import json
import os
from datetime import datetime, timezone

from . import config as C
from .fetch import nflverse_csv, iso, load_json, save_json

LOG = os.path.join(C.STATE, "retest_log.json")


def download(season):
    for y in range(2021, season + 1):
        nflverse_csv("pbp", f"play_by_play_{y}.csv.gz")
    nflverse_csv("schedules", "games.csv")


def main():
    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 8 else now.year - 1
    download(season)
    prev = load_json(LOG, {}) or {}
    out = {"at": iso(), "season": season, "studies": {}}
    from . import profiles, timing, signals, form, h2h
    for name, fn in (("grades", profiles.study), ("timing", timing.study), ("signals", signals.study), ("form", form.study), ("h2h", h2h.study)):
        try:
            r = fn()
            held = r.get("held") if name == "grades" else (
                [e["spot"] for e in r.get("edges", [])] if name == "timing" else r.get("held", []) if name in ("form", "h2h") else [x["signal"] for x in r["rows"] if x["holds"]])
            out["studies"][name] = {"ok": True, "held": held}
        except Exception as e:  # one broken study never blocks the others
            out["studies"][name] = {"ok": False, "error": str(e)[:200]}
    g = out["studies"].get("grades", {})
    before = set(((prev.get("studies") or {}).get("grades") or {}).get("held") or [])
    now_held = set(g.get("held") or [])
    added, dropped = sorted(now_held - before), sorted(before - now_held)
    n_ok = sum(1 for v in out["studies"].values() if v.get("ok"))
    if added or dropped:
        out["summary"] = (f"Re-tested {n_ok} studies with the newest games. "
                          + (f"Now used: {', '.join(added)}. " if added else "")
                          + (f"No longer used: {', '.join(dropped)}." if dropped else ""))
    else:
        out["summary"] = (f"Re-tested {n_ok} studies with the newest games: no change"
                          + (f" — still using {', '.join(sorted(now_held))}." if now_held else
                             " — nothing beats the line yet, prices unchanged."))
    out["added"], out["dropped"] = added, dropped
    hist = prev.get("history", [])
    hist.append({"at": out["at"], "summary": out["summary"]})
    out["history"] = hist[-20:]
    save_json(LOG, out)
    print(out["summary"])
    if added or dropped:
        from . import push as P
        P.send("Weekly re-test", out["summary"])


if __name__ == "__main__":
    main()
