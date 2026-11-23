"""Stamp docs/index.html with a content hash on style.css and app.js (?v=...), so phones and
browsers can never mix an old page with new styles. Run after editing the app:
python -m engine.stamp   (tests fail if the stamp is out of date)."""
import hashlib
import os
import re

from . import config as C

DOCS = os.path.join(C.ROOT, "docs")


def version():
    h = hashlib.sha1()
    for f in ("style.css", "app.js"):
        with open(os.path.join(DOCS, f), "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:10]


def stamp():
    p = os.path.join(DOCS, "index.html")
    s = open(p).read()
    v = version()
    s = re.sub(r'href="style\.css(\?v=[0-9a-f]+)?"', f'href="style.css?v={v}"', s)
    s = re.sub(r'src="app\.js(\?v=[0-9a-f]+)?"', f'src="app.js?v={v}"', s)
    open(p, "w").write(s)
    return v


if __name__ == "__main__":
    print(stamp())
