"""Phone alerts via ntfy (free). Failures are surfaced in Setup via push.lastNote, never silently."""
import json
import os
import urllib.request

from . import config as C
from .fetch import load_json, save_json, iso

PUSH_STATE = os.path.join(C.STATE, "push.json")
CONFIG = os.path.join(C.ROOT, "config.json")


def config():
    return load_json(CONFIG, {}) or {}


def state():
    return load_json(PUSH_STATE, {}) or {}


def send(title, body, tags="football", priority="default"):
    # only the cloud job sends real pushes; a run on a dev machine (stale cached prices) must never buzz Rick
    if not os.environ.get("GITHUB_ACTIONS") and os.environ.get("NFL_PUSH") != "1":
        print(f"[push skipped, local run] {title}")
        return False
    cfg = config()
    st = state()
    topic = (os.environ.get("NTFY_TOPIC") or cfg.get("ntfyTopic") or "").strip()
    if not topic:
        st["lastNote"] = f"{iso()} · No ntfy topic saved — nothing sent"
        save_json(PUSH_STATE, st)
        return False
    server = cfg.get("ntfyServer") or "https://ntfy.sh"
    try:
        req = urllib.request.Request(f"{server}/{topic}", data=body.encode("utf-8"), method="POST",
                                     headers={"Title": title.encode("ascii", "ignore").decode(),
                                              "Tags": tags, "Priority": priority})
        with urllib.request.urlopen(req, timeout=20) as r:
            r.read()
        st["lastNote"] = f"{iso()} · Sent: {title}"
        st["lastSent"] = iso()
        st["ok"] = True
        save_json(PUSH_STATE, st)
        return True
    except Exception as e:
        st["lastNote"] = f"{iso()} · Send FAILED ({str(e)[:120]}) — Top 3 is still on the Pregame tab"
        st["ok"] = False
        save_json(PUSH_STATE, st)
        return False


def public():
    cfg = config()
    st = state()
    return {"hasTopic": bool(os.environ.get("NTFY_TOPIC") or cfg.get("ntfyTopic")), "server": cfg.get("ntfyServer") or "https://ntfy.sh",
            "lastNote": st.get("lastNote"), "lastSent": st.get("lastSent"), "ok": st.get("ok")}


def migrate_topic():
    """Review 2026-11-25: the old topic sat in the public config.json, so anyone could send fake alerts.
    Once the private NTFY_TOPIC secret exists, say so on both channels and drop the public topic."""
    new = (os.environ.get("NTFY_TOPIC") or "").strip()
    cfg = config()
    old = (cfg.get("ntfyTopic") or "").strip()
    if not new or not old or not os.environ.get("GITHUB_ACTIONS"):
        return
    if new != old:
        if not send("Alerts moved here", "Your NFL Bets alerts now come on this private channel."):
            return
        server = cfg.get("ntfyServer") or "https://ntfy.sh"
        try:
            req = urllib.request.Request(f"{server}/{old}", method="POST",
                                         data="This alert channel is retired. Subscribe to the new one Claude gave you.".encode(),
                                         headers={"Title": "Old alert channel retired", "Tags": "warning"})
            urllib.request.urlopen(req, timeout=20).read()
        except Exception as e:
            print("old topic notice failed:", e)
    cfg.pop("ntfyTopic", None)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, separators=(", ", ": "))
