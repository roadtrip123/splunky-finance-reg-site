"""One Jinja environment, so every router shares the same filters and header context."""
import hashlib
import time

from fastapi.templating import Jinja2Templates

from . import pages
from .config import ROOT
from .store import clean_url

templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
BRAND_LOGO = ROOT / "app" / "static" / "brand" / "splunk-logo.svg"


def clock(value):
    """A wall-clock time. Dates are pointless here: everything on the admin page happened today."""
    if not value:
        return ""
    return time.strftime("%H:%M:%S", time.localtime(float(value)))


def ago(value):
    """How long ago, for timestamps on the admin page."""
    if not value:
        return ""
    seconds = max(0, int(time.time() - float(value)))
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    return f"{seconds // 3600} h ago"


STATIC = ROOT / "app" / "static"
_versions = {}


def asset(path):
    """/static/<path>?v=<content hash>. The static files are served without caching instructions,
    so a browser keeps an old stylesheet for as long as it likes after an update: the page arrives
    new and the styling arrives old. A URL that changes with the file makes it fetch the new one."""
    file = STATIC / path
    try:
        stamp = file.stat().st_mtime_ns
    except OSError:
        return f"/static/{path}"
    key = (path, stamp)
    if key not in _versions:
        _versions[key] = hashlib.sha256(file.read_bytes()).hexdigest()[:12]
    return f"/static/{path}?v={_versions[key]}"


def brand_logo():
    """An official logo dropped into app/static/brand/ replaces the text wordmark, checked per
    render so it shows up without a restart."""
    return "/static/brand/splunk-logo.svg" if BRAND_LOGO.exists() else ""


templates.env.filters["clock"] = clock
templates.env.filters["clean_url"] = clean_url
templates.env.filters["ago"] = ago
templates.env.globals["nav"] = pages.NAV
templates.env.globals["brand_logo"] = brand_logo
templates.env.globals["asset"] = asset
