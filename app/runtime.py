"""Settings the admin page can change while the site runs.

The repository is public and .env is written once by the installer, so anything that might need
changing on the day lives here instead: a value saved on the admin page sits in the site's own
database and wins over the installer's, which stays as the fallback. Reinstalling without
--keep-data starts a fresh database, so the installer's values come back.
"""
from . import store
from .config import settings

EDITABLE = ("passphrase", "admin_password", "llm_base_url", "llm_model", "llm_api_key",
            "galileo_password")


def get(name):
    value, _ = store.get_config(name)
    return value if value else getattr(settings, name)


def source(name):
    """("admin", when) if the admin page set it, otherwise ("install", None)."""
    value, at = store.get_config(name)
    return ("admin", at) if value else ("install", None)


def put(name, value):
    if name not in EDITABLE:
        raise KeyError(name)
    store.set_config(name, value)


def missing():
    """Settings with no value from either place, named for the admin page."""
    names = {"passphrase": "Workshop passphrase", "admin_password": "Admin password",
             "llm_api_key": "Model gateway API key", "llm_base_url": "Model gateway URL",
             "galileo_password": "Galileo account password"}
    gaps = [label for key, label in names.items() if not get(key)]
    if not settings.galileo_api_url:
        gaps.append("GALILEO_API_URL")
    return gaps
