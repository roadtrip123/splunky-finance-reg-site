"""Test settings are pushed into the environment before the app is imported, because config reads
them once at import. Each test then gets an empty database."""
import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="lab-portal-tests-"))
os.environ.update({
    "LAB_DB": str(TMP / "test.db"),
    "LAB_RUNTIME_DIR": str(TMP / "run"),
    "LAB_PASSPHRASE": "test-passphrase",
    "ADMIN_PASSWORD": "test-admin",
    "LLM_BASE_URL": "https://llm.example/v1",
    "LLM_MODEL": "test-model",
    "LLM_API_KEY": "test-llm-key",
    "GALILEO_API_URL": "https://api.example",
    "GALILEO_CONSOLE_URL": "https://console.example",
    "GALILEO_AGENT_CONTROL_URL": "https://agent.example",
    "GALILEO_USER_PASSWORD": "test-galileo-password",
    "BANK_PASSWORD": "test-bank-password",
    "PRESENTER_PASSWORD": "test-presenter-password",
    "SESSION_SECRET": "test-secret",
    "ACCOUNT_CAP": "50",
    "DRY_RUN": "0",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import security, store  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.worker import creator  # noqa: E402


@pytest.fixture(autouse=True)
def fresh():
    """An empty database, no rate-limit history, and a disarmed creator per test."""
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(settings.db_path) + suffix)
        if path.exists():
            path.unlink()
    store.init_db()
    security.passphrase_attempts.hits.clear()
    security.registrations.hits.clear()
    settings.dry_run = False
    creator.disarm()  # also forgets any kept key
    creator.last_error = ""
    yield


@pytest.fixture
def client():
    """No context manager, so the lifespan does not start the background worker: the tests drive
    creator.tick() themselves and a loose thread would race them."""
    return TestClient(app)


@pytest.fixture
def registered(client):
    response = client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Ada Lovelace", "email": "ada@example.com"})
    assert response.status_code == 200  # TestClient follows the redirect to /my-lab
    return client


def add_boxes(count=3, start=1):
    rows = [(f"https://p{n:02d}.example.show", f"p{n:02d}") for n in range(start, start + count)]
    return store.add_boxes(rows)
