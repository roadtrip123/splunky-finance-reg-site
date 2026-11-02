"""Public pages: the overview, the three guide pages, registration, and a participant's own lab."""
import re

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import content, pages, store
from ..config import settings
from ..security import (
    COOKIE_MAX_AGE,
    PARTICIPANT_COOKIE,
    client_ip,
    passphrase_attempts,
    passphrase_ok,
    registrations,
    sign,
    unsign,
)
from ..templating import templates

router = APIRouter()
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def current_participant(request):
    token = unsign(request.cookies.get(PARTICIPANT_COOKIE, ""))
    return store.by_token(token) if token else None


def page(request, template, here="", status_code=200, **context):
    context.setdefault("participant", current_participant(request))
    context.update({"settings": settings, "here": here})
    return templates.TemplateResponse(request, template, context, status_code=status_code)


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    steps = []
    for section in content.steps():
        tag, blurb = pages.STEP_CARDS.get(section["step"], ("Step", ""))
        steps.append({**section, "tag": tag, "blurb": blurb,
                      "href": f"{pages.GUIDE_PAGES[section['group']]['path']}#{section['id']}"
                      if section["group"] in pages.GUIDE_PAGES else "/lab"})
    counts = store.counts()
    return page(request, "home.html", here="home", steps=steps, rules=pages.HOUSE_RULES,
                headline=pages.gradient_lines(pages.HEADLINE),
                counts=counts, closed=counts["participants"] >= settings.account_cap,
                step_count=len(steps), step_word=pages.number_word(len(steps)))


def guide_page(request, key):
    meta = dict(pages.GUIDE_PAGES[key])
    sections = content.sections(key)
    meta["title"] = meta["title"].format(count=pages.number_word(len(sections)))
    neighbour = {}
    for side in ("prev", "next"):
        target = meta.get(side)
        if target:
            neighbour[side] = {"path": pages.GUIDE_PAGES[target]["path"],
                               "name": pages.PAGE_NAMES[target]}
    return page(request, "guide_page.html", here=key, meta=meta, sections=sections,
                intro=content.intro() if key == "briefing" else "", neighbour=neighbour)


@router.get("/briefing", response_class=HTMLResponse)
def briefing(request: Request):
    return guide_page(request, "briefing")


@router.get("/lab", response_class=HTMLResponse)
def lab(request: Request):
    return guide_page(request, "lab")


@router.get("/troubleshooting", response_class=HTMLResponse)
def troubleshooting(request: Request):
    return guide_page(request, "troubleshooting")


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    if current_participant(request):
        return RedirectResponse("/my-lab", status_code=303)
    counts = store.counts()
    return page(request, "register.html", here="register", counts=counts,
                closed=counts["participants"] >= settings.account_cap)


@router.post("/register", response_class=HTMLResponse)
def register(request: Request, name: str = Form(""), email: str = Form(""),
             passphrase: str = Form("")):
    ip = client_ip(request)
    counts = store.counts()

    def again(error, status=400):
        return page(request, "register.html", here="register", status_code=status, error=error,
                    name=name, email=email, counts=counts, participant=None,
                    closed=counts["participants"] >= settings.account_cap)

    if not passphrase_attempts.allow(ip):
        return again("Too many attempts from this address. Wait a minute and try again.", 429)
    # The passphrase is checked before anything else is looked at, so an unauthorised visitor
    # cannot learn whether an address is already registered, and cannot create Galileo accounts
    # in the tenant at all.
    if not passphrase_ok(passphrase):
        return again("That passphrase is not right. Your instructor has it.", 403)
    if not (name or "").strip():
        return again("Please give a name, so your instructor can find you in the room.")
    if not EMAIL.match((email or "").strip()):
        return again("That does not look like an email address.")
    if not registrations.allow(ip):
        return again("Too many registrations from this address. Wait a minute.", 429)

    try:
        participant, _created = store.register(name, email, ip)
    except store.RegistrationClosed as error:
        return again(f"Registration is closed: {error}", 409)

    passphrase_attempts.reset(ip)
    response = RedirectResponse("/my-lab", status_code=303)
    response.set_cookie(PARTICIPANT_COOKIE, sign(participant["token"]), max_age=COOKIE_MAX_AGE,
                        httponly=True, samesite="lax")
    return response


@router.get("/my-lab", response_class=HTMLResponse)
def my_lab(request: Request):
    participant = current_participant(request)
    if not participant:
        return RedirectResponse("/register", status_code=303)
    return page(request, "my_lab.html", here="my-lab", participant=participant)


@router.post("/forget")
def forget(request: Request):
    """Clear the cookie on a shared laptop. The row stays, so the same email gets the same
    instance back rather than consuming a second one."""
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(PARTICIPANT_COOKIE)
    return response
