"""This repository is public. Nothing from a deployment's .env may appear in a tracked file.

The values are read from the local .env at test time and never written down here, so the test that
guards the secrets does not itself publish them. Failures name the setting and the file, never the
value.
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SENSITIVE = ("LAB_PASSPHRASE", "ADMIN_PASSWORD", "LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY",
             "GALILEO_USER_PASSWORD", "SESSION_SECRET")
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2"}


def local_values():
    """{setting: value} from this checkout's .env, for the settings that must stay private.
    Very short values are left out, since they would match by accident."""
    env = ROOT / ".env"
    if not env.exists():
        return {}
    values = {}
    for line in env.read_text().splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key in SENSITIVE and len(value) >= 6:
            values[key] = value
    return values


def tracked_files():
    result = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True)
    if result.returncode != 0:
        pytest.skip("not a git checkout")
    return [ROOT / name for name in result.stdout.splitlines()]


def test_no_value_from_the_local_env_is_in_a_tracked_file():
    values = local_values()
    if not values:
        pytest.skip("no .env in this checkout")
    leaks = []
    for path in tracked_files():
        if path.suffix.lower() in BINARY or not path.is_file():
            continue
        text = path.read_text(errors="ignore")
        leaks.extend(f"{key} in {path.relative_to(ROOT)}"
                     for key, value in values.items() if value in text)
    assert not leaks, leaks


def test_the_example_env_ships_every_private_setting_blank():
    example = (ROOT / ".env.example").read_text()
    for key in SENSITIVE:
        line = next((row for row in example.splitlines() if row.startswith(f"{key}=")), None)
        assert line is not None, f"{key} missing from .env.example"
        assert line == f"{key}=", f"{key} has a value in .env.example"


def test_the_installer_offers_no_default_for_a_private_setting():
    """A default in a public script is a published value."""
    install = (ROOT / "scripts" / "install.sh").read_text()
    assert "Nothing here has a default" in install
    assert "[%s]" not in install
