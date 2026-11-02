"""A quick check that the model gateway answers, takes the key and serves the model. The same
check that found a missing /v1 by hand during setup. Messages never contain the key."""
import requests


def check(base_url, api_key, model, timeout=10):
    """(ok, message)."""
    url = f"{(base_url or '').rstrip('/')}/models"
    try:
        response = requests.get(url, headers={"Authorization": f"Bearer {api_key}"},
                                timeout=timeout)
    except requests.RequestException as error:
        return False, f"gateway unreachable ({type(error).__name__})"
    if response.status_code in (401, 403):
        hint = "" if base_url.rstrip("/").endswith("/v1") else "; the URL should end in /v1"
        return False, f"gateway refused the request (HTTP {response.status_code}){hint}"
    if response.status_code == 404:
        return False, "no model list at that URL; it should end in /v1"
    if not response.ok:
        return False, f"gateway answered HTTP {response.status_code}"
    try:
        ids = [m.get("id") for m in response.json().get("data", [])]
    except (ValueError, AttributeError):
        return False, "gateway answered, but not with a model list"
    if model not in ids:
        return False, f"key accepted, but {model} is not among the {len(ids)} models it serves"
    return True, f"gateway answers, key accepted, {model} available"
