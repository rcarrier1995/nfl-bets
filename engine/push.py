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
    return {"topic": cfg.get("ntfyTopic"), "server": cfg.get("ntfyServer") or "https://ntfy.sh",
            "lastNote": st.get("lastNote"), "lastSent": st.get("lastSent"), "ok": st.get("ok")}
