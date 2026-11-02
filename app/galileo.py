"""The Galileo account-creation chain.

Galileo has no admin "create user" call. The sequence below is the one proved out by
galileo-workshop-setup/batch_create_users.py for this tenant, in the same order and with the same
pacing, because /signup_link and /system_users sit behind a rate limiter:

  POST /signup_link   (admin)        -> a signup_url carrying a one-time token
  POST /system_users  (token-gated)  -> completes signup, setting the shared password
  POST /users/all     (admin)        -> the new user's org-scoped id
  PUT  /users/{id}    (admin)        -> the role, when it differs from the tenant default

/signup_link always sends a real invitation email. Nobody needs to open it, since the password is
already set by the time they read their details, but it does arrive.
"""
import re
import time
from urllib.parse import parse_qs, urlparse

import requests

REQUEST_DELAY = 0.3
MAX_RETRIES = 3
BACKOFF = 2
TIMEOUT = 30


class GalileoError(Exception):
    """A failure worth showing on the admin page. The message never carries the key or token."""


class Unauthorized(GalileoError):
    """The admin token was refused, usually because the session behind it expired."""


class Duplicate(GalileoError):
    """Galileo already has an account for this email. Retrying can never succeed."""


# Galileo's exact wording for a taken email is not documented, so this matches loosely.
TAKEN = re.compile(r"already|exist|duplicate|taken|in use|registered", re.I)


def _refused(step, response):
    text = response.text[:160]
    if response.status_code == 409 or (response.status_code in (400, 422) and TAKEN.search(text)):
        return Duplicate(f"{step}: email already has a Galileo account (HTTP {response.status_code})")
    return GalileoError(f"{step} failed: HTTP {response.status_code} {text}")


def _request(method, url, **kwargs):
    last = None
    response = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.request(method, url, timeout=TIMEOUT, **kwargs)
        except requests.exceptions.RequestException as error:
            last = error
        else:
            if response.status_code < 500:
                return response
            last = None
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF * attempt)
    if last:
        raise GalileoError(f"{type(last).__name__} talking to Galileo")
    return response


def exchange_api_key(api_url, api_key):
    """An API key for a bearer token. /login wants a password, which an SSO admin does not have,
    so this is the path that works for a Google or Okta account."""
    response = _request("POST", f"{api_url}/login/api_key", json={"api_key": api_key})
    if response.status_code != 200:
        raise GalileoError(f"key exchange refused: HTTP {response.status_code}")
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise GalileoError("key exchange returned no access_token")
    return token, {field: payload.get(field, "") for field in ("email", "user_id", "role")}


def whoami(api_url, token):
    """A cheap call to prove a token is still good, so the admin page can say so before the room
    fills up. Any 2xx is enough; the shape of the body does not matter here."""
    response = _request("GET", f"{api_url}/current_user",
                        headers={"Authorization": f"Bearer {token}"})
    return response is not None and response.status_code < 300


def find_user(api_url, token, email):
    """The user in this organisation with this email, as Galileo describes them, or None."""
    response = _request("POST", f"{api_url}/users/all", params={"limit": 1, "starting_token": 0},
                        headers={"Authorization": f"Bearer {token}"},
                        json={"filters": [{"name": "email", "value": email, "operator": "eq"}]})
    if response.status_code == 401:
        raise Unauthorized("admin token rejected (401), re-arm with a fresh API key")
    if response.status_code != 200:
        raise GalileoError(f"user lookup failed: HTTP {response.status_code}")
    users = response.json().get("users", [])
    return users[0] if users else None


def create_user(api_url, token, email, password, role="user", first_name="", last_name=""):
    """Create one user with the shared password. Raises Duplicate when the email is taken and
    GalileoError for anything else, each with a short reason."""
    headers = {"Authorization": f"Bearer {token}"}

    response = _request("POST", f"{api_url}/signup_link", params={"user_email": email},
                        headers=headers)
    if response.status_code == 401:
        raise Unauthorized("admin token rejected (401), re-arm with a fresh API key")
    if response.status_code != 200:
        raise _refused("signup_link", response)
    signup_url = response.json().get("signup_url")
    if not signup_url:
        raise GalileoError("no signup_url returned; the invitation-link feature flag may be off")
    tokens = parse_qs(urlparse(signup_url).query).get("token")
    if not tokens:
        raise GalileoError("signup_url carried no token")
    time.sleep(REQUEST_DELAY)

    response = _request("POST", f"{api_url}/system_users", params={"signup_token": tokens[0]},
                        json={"email": email, "password": password, "first_name": first_name,
                              "last_name": last_name, "auth_method": "email"})
    if response.status_code != 200:
        raise _refused("system_users", response)
    time.sleep(REQUEST_DELAY)

    if role and role != "read_only":
        try:
            user = find_user(api_url, token, email)
        except GalileoError as error:
            raise GalileoError(f"created, but {error}") from None
        if not user:
            raise GalileoError("created, but the user could not be found afterwards")
        response = _request("PUT", f"{api_url}/users/{user['id']}", headers=headers,
                            json={"role": role})
        if response.status_code != 200:
            raise GalileoError(f"created, but the role stayed default: HTTP {response.status_code}")
    return email
