"""Cookie signing, the passphrase check, and a small per-IP rate limiter.

There are no user accounts here. A participant's cookie carries the token their row already holds,
signed so it cannot be guessed or edited, and the admin cookie says nothing but "this browser typed
the admin password".
"""
import hashlib
import hmac
import time
from collections import defaultdict, deque

from . import store
from .config import settings

PARTICIPANT_COOKIE = "lab_participant"
ADMIN_COOKIE = "lab_admin"
COOKIE_MAX_AGE = 60 * 60 * 24 * 2


def _mac(value):
    return hmac.new(settings.session_secret.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def sign(value):
    return f"{value}.{_mac(value)}"


def unsign(signed):
    if not signed or "." not in signed:
        return None
    value, _, mac = signed.rpartition(".")
    return value if hmac.compare_digest(mac, _mac(value)) else None


MIN_PASSPHRASE = 6


def current_passphrase():
    """(passphrase, where it came from). One set on the admin page wins over the installer's, so it
    can be changed on the day without touching the box, the .env or the public repository."""
    value, updated_at = store.get_config("passphrase")
    if value:
        return value, "admin", updated_at
    return settings.passphrase, "install", None


def passphrase_ok(given):
    """Constant-time, and a passphrase that was never configured refuses everything rather than
    letting the whole room in."""
    expected, _, _ = current_passphrase()
    if not expected:
        return False
    return hmac.compare_digest((given or "").strip().encode(), expected.encode())


def admin_password_ok(given):
    if not settings.admin_password:
        return False
    return hmac.compare_digest((given or "").strip(), settings.admin_password)


class RateLimiter:
    """Sliding window per key, in memory. One process, one event, so there is nothing to share."""

    def __init__(self, limit, window):
        self.limit = limit
        self.window = window
        self.hits = defaultdict(deque)

    def allow(self, key):
        now = time.time()
        recent = self.hits[key]
        while recent and now - recent[0] > self.window:
            recent.popleft()
        if len(recent) >= self.limit:
            return False
        recent.append(now)
        return True

    def reset(self, key):
        self.hits.pop(key, None)


# Deliberately loose. A room shares the venue's wifi, so a hundred people arrive from one address:
# a tight per-address limit would have them locking each other out, which is a worse failure than
# the one it prevents. The real guards are the passphrase, which an outsider does not have, and
# ACCOUNT_CAP, which bounds how many Galileo accounts can ever be created. These limits exist to
# stop a script hammering the form, nothing finer.
passphrase_attempts = RateLimiter(limit=120, window=60)
registrations = RateLimiter(limit=120, window=60)


def client_ip(request):
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
