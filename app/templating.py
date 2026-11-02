"""One Jinja environment, so every router shares the same filters and header context."""
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


def brand_logo():
    """An official logo dropped into app/static/brand/ replaces the text wordmark, checked per
    render so it shows up without a restart."""
    return "/static/brand/splunk-logo.svg" if BRAND_LOGO.exists() else ""


templates.env.filters["clock"] = clock
templates.env.filters["clean_url"] = clean_url
templates.env.filters["ago"] = ago
templates.env.globals["nav"] = pages.NAV
templates.env.globals["brand_logo"] = brand_logo
