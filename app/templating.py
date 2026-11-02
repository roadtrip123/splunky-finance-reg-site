"""One Jinja environment, so every router shares the same filters and header context."""
import time

from fastapi.templating import Jinja2Templates

from . import pages
from .config import ROOT

templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
BRAND_LOGO = ROOT / "app" / "static" / "brand" / "splunk-logo.svg"


def clock(value):
    """A wall-clock time. Dates are pointless here: everything on the admin page happened today."""
    if not value:
        return ""
    return time.strftime("%H:%M:%S", time.localtime(float(value)))


def brand_logo():
    """An official logo dropped into app/static/brand/ replaces the text wordmark, checked per
    render so it shows up without a restart."""
    return "/static/brand/splunk-logo.svg" if BRAND_LOGO.exists() else ""


templates.env.filters["clock"] = clock
templates.env.globals["nav"] = pages.NAV
templates.env.globals["brand_logo"] = brand_logo
