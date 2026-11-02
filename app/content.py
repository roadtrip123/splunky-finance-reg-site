"""The rendered lab guide, produced by guide/build_guide.py and read from disk at request time.

Kept out of the template loader on purpose: the guide is markdown written for GitHub, so it is full
of braces that Jinja would try to interpret. It arrives as finished HTML, one entry per section,
and each page takes the sections that belong to it.
"""
import json

from .config import ROOT

GENERATED = ROOT / "app" / "generated"
GUIDE = GENERATED / "guide.json"

MISSING = {
    "source": "",
    "intro": "",
    "sections": [{
        "id": "not-built", "title": "The guide has not been built yet", "short": "", "step": None,
        "group": "briefing",
        "html": '<h2 id="not-built">The guide has not been built yet</h2><p>Run '
                "<code>python3 guide/build_guide.py</code>, then reload.</p>",
    }],
}

_cache = {}


def _guide():
    """Re-read when the file changes, so a rebuild shows up without restarting the service."""
    try:
        stamp = GUIDE.stat().st_mtime
    except OSError:
        return MISSING
    if _cache.get("stamp") != stamp:
        _cache["stamp"] = stamp
        _cache["data"] = json.loads(GUIDE.read_text())
    return _cache["data"]


def intro():
    return _guide()["intro"]


def sections(group):
    return [s for s in _guide()["sections"] if s["group"] == group]


def steps():
    return [s for s in _guide()["sections"] if s["step"]]


def guide_built():
    return GUIDE.exists()
