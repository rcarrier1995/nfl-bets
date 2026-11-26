"""Free cloud save for Rick's bet log and Robinhood combo quotes (Rick approved 2026-11-25).

No accounts, no sign-in, nothing touches a betting account. The app posts small change messages to an ntfy
mailbox topic (free, already used for alerts); each loop run (every 6-10 min) reads new messages and saves
them to docs/data/sync/<code>.json, which every device with the same sync code reads back from the website.

Messages (JSON in the ntfy message body, each well under ntfy's 4 KB limit):
  {"v": 1, "code": "AB12CD34", "op": "put",   "bet": {... "id": "...", "upd": "<iso>"}}
  {"v": 1, "code": "AB12CD34", "op": "del",   "id": "...", "upd": "<iso>"}
  {"v": 1, "code": "AB12CD34", "op": "quote", "quote": {"legs": 61.2, "quote": 60.1, "n": 3, "at": "<iso>", "teams": [...]}}
  {"v": 1, "op": "idea", "idea": {"id": "...", "name": "Sam", "text": "..."}}   (no code: app suggestions box)
Newest "upd" wins per bet. ntfy keeps messages ~12 h, the loop reads them every few minutes, and the app
re-sends anything the saved file is missing, so a missed message heals itself.
Real combo quotes also go into config.json comboQuotes (that is what tunes the combo price estimate).
The repo is public, so the saved file is readable by anyone who knows the code (Rick: no sensitive data here).
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timezone

from . import config as C
from .fetch import load_json, save_json, iso

SYNC_DIR = os.path.join(C.ROOT, "docs", "data", "sync")
DEFAULT_TOPIC = "nflbets-sync-7k2q9w4m"
CODE = re.compile(r"^[A-Z0-9]{8}$")
BET_KEYS = {"id", "upd", "kind", "team", "game", "gameId", "legs", "grade", "call", "price", "qty", "date", "result",
            "week", "season", "auto"}
MAX_BETS = 2000
IDEAS_FILE = os.path.join(C.ROOT, "docs", "data", "suggestions.json")
MAX_IDEAS = 300


def topic(cfg=None):
    cfg = cfg if cfg is not None else C._cfg()
    return (cfg.get("syncTopic") or DEFAULT_TOPIC).strip()


def _poll(server, tp, since):
    url = f"{server}/{tp}/json?poll=1&since={since or '12h'}"
    req = urllib.request.Request(url, headers={"User-Agent": "nfl-bets-sync"})
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode("utf-8", "ignore")
    out = []
    for line in body.splitlines():
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("event") == "message":
            out.append(m)
    return out


def _clean_bet(b):
    if not isinstance(b, dict) or not isinstance(b.get("id"), str) or not b["id"] or len(b["id"]) > 40:
        return None
    b = {k: v for k, v in b.items() if k in BET_KEYS}
    try:
        p = float(b.get("price"))
    except Exception:
        return None
    if not 0 < p < 100:
        return None
    if b.get("legs") is not None and not isinstance(b["legs"], list):
        b.pop("legs")
    return b


def _clean_quote(q):
    try:
        legs, quote = float(q["legs"]), float(q["quote"])
    except Exception:
        return None
    if not (0 < legs < 100 and 0 < quote < 100 and 0.5 <= quote / legs <= 2.0):
        return None   # junk or a typo: never let it move the combo estimate
    return {"at": str(q.get("at") or iso())[:20], "teams": [str(t)[:4] for t in (q.get("teams") or [])][:12],
            "legs": round(legs, 2), "quote": round(quote, 2), "n": int(q.get("n") or 0), "note": "Rick, Robinhood (app)"}


def _clean_idea(x, at):
    """Suggestion from someone using the shared app. Saved for Rick to review; never applied by itself."""
    if not isinstance(x, dict):
        return None
    iid = str(x.get("id") or "")[:40]
    text = " ".join(str(x.get("text") or "").split())[:600]
    if not iid or len(text) < 3:
        return None
    name = " ".join(str(x.get("name") or "").split())[:30] or "Someone"
    return {"id": iid, "name": name, "text": text, "at": at}


def apply(msgs, store_for, quotes, ideas=None):
    """Fold messages into per-code stores. store_for(code) -> dict. Returns the codes changed.
    App suggestions ("idea") are appended to the ideas list when one is passed."""
    changed = set()
    for m in msgs:
        try:
            d = json.loads(m.get("message") or "")
        except Exception:
            continue
        if isinstance(d, dict) and d.get("v") == 1 and d.get("op") == "idea":
            if ideas is not None:
                t = m.get("time")
                at = iso(datetime.fromtimestamp(t, timezone.utc)) if isinstance(t, (int, float)) else iso()
                x = _clean_idea(d.get("idea"), at)
                if x and not any(i.get("id") == x["id"] for i in ideas):
                    ideas.append(x)
            continue
        code = str(d.get("code") or "")
        if d.get("v") != 1 or not CODE.match(code):
            continue
        st = store_for(code)
        op = d.get("op")
        if op == "put":
            b = _clean_bet(d.get("bet"))
            if not b:
                continue
            old = st["bets"].get(b["id"])
            gone = st["deleted"].get(b["id"])
            upd = str(b.get("upd") or "")
            if (old and str(old.get("upd") or "") > upd) or (gone and gone >= upd):
                continue
            if len(st["bets"]) >= MAX_BETS and not old:
                continue
            st["bets"][b["id"]] = b
        elif op == "del":
            bid, upd = str(d.get("id") or "")[:40], str(d.get("upd") or "")
            if not bid:
                continue
            old = st["bets"].get(bid)
            if old and str(old.get("upd") or "") > upd:
                continue
            st["bets"].pop(bid, None)
            st["deleted"][bid] = upd
        elif op == "quote":
            q = _clean_quote(d.get("quote") or {})
            if not q:
                continue
            if not any(x.get("at") == q["at"] and x.get("quote") == q["quote"] for x in quotes):
                quotes.append(q)
            if not any(x.get("at") == q["at"] for x in st["quotes"]):
                st["quotes"].append(q)
        else:
            continue
        changed.add(code)
    return changed


def run(rs, now):
    """Read new mailbox messages and save them. Never raises into the loop."""
    cfg = C._cfg()
    server = cfg.get("ntfyServer") or "https://ntfy.sh"
    try:
        msgs = _poll(server, topic(cfg), rs.get("syncSince"))
    except Exception as e:
        print("sync poll failed:", e)
        return 0
    if not msgs:
        return 0
    stores = {}

    def store_for(code):
        if code not in stores:
            s = load_json(os.path.join(SYNC_DIR, f"{code}.json"), {}) or {}
            stores[code] = {"bets": s.get("bets") or {}, "deleted": s.get("deleted") or {}, "quotes": s.get("quotes") or []}
        return stores[code]

    quotes = list(cfg.get("comboQuotes") or [])
    n_q = len(quotes)
    ideas = list((load_json(IDEAS_FILE, {}) or {}).get("ideas") or [])
    n_i = len(ideas)
    changed = apply(msgs, store_for, quotes, ideas)
    if len(ideas) != n_i:
        new = ideas[n_i:]
        save_json(IDEAS_FILE, {"at": iso(now), "ideas": ideas[-MAX_IDEAS:]}, compact=True)
        try:   # tell Rick; he decides what (if anything) changes for everyone
            from .push import send
            x = new[-1]
            send("New app suggestion" + (f"s ({len(new)})" if len(new) > 1 else ""),
                 f"{x['name']}: {x['text'][:200]}\nOpen Setup > Suggestions to see it.", tags="bulb")
        except Exception as e:
            print("suggestion push failed:", e)
    os.makedirs(SYNC_DIR, exist_ok=True)
    for code in changed:
        s = stores[code]
        s["at"] = iso(now)
        save_json(os.path.join(SYNC_DIR, f"{code}.json"), s, compact=True)
    if len(quotes) != n_q:
        cfg["comboQuotes"] = quotes
        with open(os.path.join(C.ROOT, "config.json"), "w") as f:
            json.dump(cfg, f, separators=(", ", ": "))
    rs["syncSince"] = msgs[-1].get("id") or rs.get("syncSince")
    return len(changed)
