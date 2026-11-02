"""The instructor's page: upload instances, arm account creation, watch the roster, export it."""
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from .. import galileo, store
from ..config import settings
from ..security import (
    ADMIN_COOKIE,
    COOKIE_MAX_AGE,
    MIN_PASSPHRASE,
    admin_password_ok,
    client_ip,
    current_passphrase,
    passphrase_attempts,
    sign,
    unsign,
)
from ..templating import templates
from ..worker import creator

router = APIRouter(prefix="/admin")
MAX_UPLOAD = 1_000_000


def signed_in(request):
    return unsign(request.cookies.get(ADMIN_COOKIE, "")) == "admin"


def dashboard(request, message="", error=""):
    passphrase, source, changed_at = current_passphrase()
    missing = [name for name in settings.missing()
               if not (name == "LAB_PASSPHRASE" and passphrase)]
    return templates.TemplateResponse(request, "admin.html", {
        "passphrase": passphrase,
        "passphrase_source": source,
        "passphrase_changed_at": changed_at,
        "min_passphrase": MIN_PASSPHRASE,
        "counts": store.counts(),
        "roster": store.roster(),
        "boxes": store.boxes(),
        "malformed": store.malformed_boxes(),
        "events": store.recent_events(30),
        "status": creator.status(),
        "settings": settings,
        "missing": missing,
        "message": message,
        "error": error,
    })


def login_page(request, error="", status=200):
    return templates.TemplateResponse(request, "admin_login.html",
                                      {"error": error, "settings": settings}, status_code=status)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    if not signed_in(request):
        return login_page(request)
    return dashboard(request)


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, password: str = Form("")):
    ip = client_ip(request)
    if not passphrase_attempts.allow(ip):
        return login_page(request, "Too many attempts. Wait a minute.", 429)
    if not admin_password_ok(password):
        if not settings.admin_password:
            return login_page(request, "No admin password is configured on this box.", 503)
        return login_page(request, "Wrong password.", 403)
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie(ADMIN_COOKIE, sign("admin"), max_age=COOKIE_MAX_AGE, httponly=True,
                        samesite="lax")
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/admin", status_code=303)
    response.delete_cookie(ADMIN_COOKIE)
    return response


def guard(request):
    return None if signed_in(request) else RedirectResponse("/admin", status_code=303)


async def _uploaded_text(file, pasted):
    if file is not None and file.filename:
        raw = await file.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            return None, "That file is larger than 1 MB, which is not a list of instances."
        return raw.decode("utf-8-sig", errors="replace"), ""
    return pasted or "", ""


@router.post("/boxes", response_class=HTMLResponse)
async def upload_boxes(request: Request, file: UploadFile = File(None), pasted: str = Form("")):
    denied = guard(request)
    if denied:
        return denied
    text, error = await _uploaded_text(file, pasted)
    if error:
        return dashboard(request, error=error)
    rows = store.parse_csv(text)
    if not rows:
        return dashboard(request, error="Nothing in that upload looked like an instance URL.")
    added, duplicates = store.add_boxes(rows)
    note = f"Added {added} instance{'' if added == 1 else 's'}"
    if duplicates:
        note += f", skipped {duplicates} already known"
    return dashboard(request, message=note + ".")


@router.post("/boxes/{box_id}/remove", response_class=HTMLResponse)
def remove_box(request: Request, box_id: int):
    denied = guard(request)
    if denied:
        return denied
    store.remove_box(box_id)
    return dashboard(request, message="Instance removed.")


@router.post("/pool", response_class=HTMLResponse)
async def upload_pool(request: Request, file: UploadFile = File(None), pasted: str = Form("")):
    denied = guard(request)
    if denied:
        return denied
    text, error = await _uploaded_text(file, pasted)
    if error:
        return dashboard(request, error=error)
    emails = [row[0] for row in store.parse_csv(text) if "@" in row[0]]
    if not emails:
        # A pool CSV exported from the account script leads with an email column, so a file with
        # no @ in it is the instance list uploaded into the wrong box.
        return dashboard(request, error="No email addresses in that upload.")
    added, duplicates = store.add_pool(emails)
    return dashboard(request, message=f"Added {added} fallback accounts, skipped {duplicates}.")


@router.post("/passphrase", response_class=HTMLResponse)
def set_passphrase(request: Request, passphrase: str = Form("")):
    denied = guard(request)
    if denied:
        return denied
    value = passphrase.strip()
    if len(value) < MIN_PASSPHRASE:
        return dashboard(request, error=f"The passphrase needs at least {MIN_PASSPHRASE} "
                                        "characters, so it cannot be guessed in a few tries.")
    store.set_config("passphrase", value)
    return dashboard(request, message="Passphrase changed. The old one stops working now; anyone "
                                      "already checked in keeps their lab.")


@router.post("/arm", response_class=HTMLResponse)
def arm(request: Request, api_key: str = Form("")):
    denied = guard(request)
    if denied:
        return denied
    if not api_key.strip():
        return dashboard(request, error="No key given.")
    try:
        identity = creator.arm(api_key.strip())
    except galileo.GalileoError as error:
        return dashboard(request, error=f"Could not arm: {error}")
    who = identity.get("email") or "the key's owner"
    return dashboard(request, message=f"Account creation is armed as {who}.")


@router.post("/disarm", response_class=HTMLResponse)
def disarm(request: Request):
    denied = guard(request)
    if denied:
        return denied
    creator.disarm()
    return dashboard(request, message="Disarmed. Nothing further will be created.")


@router.post("/release/{participant_id}", response_class=HTMLResponse)
def release(request: Request, participant_id: int):
    denied = guard(request)
    if denied:
        return denied
    store.release(participant_id)
    return dashboard(request, message="Instance released and offered to anyone waiting.")


@router.post("/retry/{participant_id}", response_class=HTMLResponse)
def retry(request: Request, participant_id: int):
    denied = guard(request)
    if denied:
        return denied
    store.retry(participant_id)
    return dashboard(request, message="Queued for another attempt.")


@router.get("/export.csv", response_class=PlainTextResponse)
def export(request: Request):
    if not signed_in(request):
        return RedirectResponse("/admin", status_code=303)
    return PlainTextResponse(store.export_csv(), media_type="text/csv", headers={
        "Content-Disposition": 'attachment; filename="lab-roster.csv"'})
