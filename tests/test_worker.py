"""The creator: what a participant sees when Galileo answers, refuses, or is not armed at all."""
import time

import pytest

from app import galileo, store
from app.config import settings
from app.worker import MAX_ATTEMPTS, creator
from tests.conftest import add_boxes


@pytest.fixture
def armed(monkeypatch):
    monkeypatch.setattr(galileo, "exchange_api_key",
                        lambda api_url, key: ("a-token", {"email": "admin@example.com"}))
    # Nobody already has an account unless a test says otherwise.
    monkeypatch.setattr(galileo, "find_user", lambda api_url, token, email: None)
    creator.arm("an-api-key")
    assert creator.armed
    return creator


def a_participant(email="ada@example.com"):
    add_boxes(1)
    return store.register("Ada Lovelace", email)[0]


def test_a_dry_run_invents_nothing_and_calls_nothing(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    monkeypatch.setattr(galileo, "create_user", lambda *a, **k: pytest.fail("called Galileo"))
    person = a_participant()
    assert creator.tick() == "ada@example.com"
    assert store.by_email("ada@example.com")["galileo_state"] == "ready"
    assert store.by_email("ada@example.com")["galileo_email"] == person["email"]


def test_an_armed_creator_creates_the_account_for_the_address_they_registered(armed, monkeypatch):
    calls = []
    monkeypatch.setattr(galileo, "create_user",
                        lambda api_url, token, email, password, **kw: calls.append(
                            (email, password, token, kw)) or email)
    a_participant()
    assert creator.tick() == "ada@example.com"
    email, password, token, kw = calls[0]
    assert (email, password, token) == ("ada@example.com", "test-galileo-password", "a-token")
    assert kw["role"] == "user"
    assert (kw["first_name"], kw["last_name"]) == ("Ada", "Lovelace")
    assert store.by_email("ada@example.com")["galileo_state"] == "ready"


def test_a_transient_refusal_is_tried_again_rather_than_given_up_on(armed, monkeypatch):
    monkeypatch.setattr(galileo, "create_user", lambda *a, **k: (_ for _ in ()).throw(
        galileo.GalileoError("signup_link failed: HTTP 429")))
    a_participant()
    creator.tick()
    row = store.by_email("ada@example.com")
    assert row["galileo_state"] == "queued"
    assert "429" in row["galileo_error"]


def test_a_persistent_refusal_hands_out_a_fallback_account(armed, monkeypatch):
    monkeypatch.setattr(galileo, "create_user", lambda *a, **k: (_ for _ in ()).throw(
        galileo.GalileoError("signup_link failed: HTTP 500")))
    store.add_pool(["participant1@galileo.ai"])
    a_participant()
    for _ in range(MAX_ATTEMPTS + 1):
        creator.tick()
    row = store.by_email("ada@example.com")
    assert row["galileo_state"] == "pool"
    assert row["galileo_email"] == "participant1@galileo.ai"


def test_with_no_fallback_left_the_failure_is_recorded_rather_than_hidden(armed, monkeypatch):
    monkeypatch.setattr(galileo, "create_user", lambda *a, **k: (_ for _ in ()).throw(
        galileo.GalileoError("admin token rejected (401), re-arm with a fresh API key")))
    a_participant()
    for _ in range(MAX_ATTEMPTS + 1):
        creator.tick()
    row = store.by_email("ada@example.com")
    assert row["galileo_state"] == "failed"
    assert "401" in row["galileo_error"]
    assert "401" in creator.status()["last_error"]


def test_a_disarmed_creator_leaves_a_fresh_registration_alone():
    a_participant()
    assert creator.tick() is None
    assert store.by_email("ada@example.com")["galileo_state"] == "queued"


def test_nobody_waits_forever_on_a_disarmed_creator():
    """Two minutes of a spinner is the point at which a pre-made account beats an explanation."""
    store.add_pool(["participant1@galileo.ai"])
    person = a_participant()
    with store.writing() as db:
        db.execute("UPDATE participants SET created_at=? WHERE id=?",
                   (time.time() - 600, person["id"]))
    assert creator.tick() == "ada@example.com"
    assert store.by_email("ada@example.com")["galileo_state"] == "pool"


def test_the_cap_stops_creation_even_if_a_row_slips_through(armed, monkeypatch):
    """The cap closes registration, but a row already queued when the cap is lowered must not be
    created either: it is the last guard against a runaway loop making accounts in the tenant."""
    a_participant()
    monkeypatch.setattr(settings, "account_cap", 0)
    monkeypatch.setattr(galileo, "create_user", lambda *a, **k: pytest.fail("created past the cap"))
    creator.tick()
    assert store.by_email("ada@example.com")["galileo_state"] == "queued"


def test_disarming_forgets_the_token(armed):
    creator.disarm()
    assert not creator.armed
    assert creator.status()["identity"] == {}


def test_arming_with_a_refused_key_raises_rather_than_half_arming(monkeypatch):
    monkeypatch.setattr(galileo, "exchange_api_key", lambda api_url, key: (_ for _ in ()).throw(
        galileo.GalileoError("key exchange refused: HTTP 401")))
    with pytest.raises(galileo.GalileoError):
        creator.arm("bad-key")
    assert not creator.armed


def test_a_long_queue_tells_people_where_they_are(client):
    """One account at a time means a hundred-person room drains over minutes, so the page says how
    many are ahead rather than spinning with no explanation."""
    from app import store as s
    add_boxes(3)
    first, _ = s.register("First", "first@example.com")
    second, _ = s.register("Second", "second@example.com")
    third, _ = s.register("Third", "third@example.com")
    assert s.queue_position(first["id"]) == 0
    assert s.queue_position(third["id"]) == 2
    s.set_galileo(first["id"], "ready", email="first@example.com")
    assert s.queue_position(first["id"]) == 0
    assert s.queue_position(second["id"]) == 0


def test_nobody_waits_more_than_five_minutes_even_when_armed(armed, monkeypatch):
    """The backstop that matters on the day: the fiftieth person gets a pre-made account rather
    than watching the queue."""
    monkeypatch.setattr(galileo, "create_user", lambda *a, **k: "created@example.com")
    store.add_pool(["participant1@galileo.ai"])
    person = a_participant("slow@example.com")
    with store.writing() as db:
        db.execute("UPDATE participants SET created_at=? WHERE id=?",
                   (time.time() - 3600, person["id"]))
    assert creator.tick() == "slow@example.com"
    row = store.by_email("slow@example.com")
    assert row["galileo_state"] == "pool"
    assert row["galileo_email"] == "participant1@galileo.ai"


def test_a_member_of_the_organisation_keeps_their_own_account(armed, monkeypatch):
    """Nothing is created for them, so no invitation goes out and no duplicate is attempted."""
    monkeypatch.setattr(galileo, "find_user",
                        lambda api_url, token, email: {"id": "u1", "email": email, "role": "user"})
    monkeypatch.setattr(galileo, "create_user", lambda *a, **k: pytest.fail("created a duplicate"))
    a_participant("member@example.com")
    creator.tick()
    row = store.by_email("member@example.com")
    assert row["galileo_state"] == "existing" and row["galileo_email"] == "member@example.com"
    assert row["galileo_password"] == "" and row["galileo_error"] == ""


def test_a_read_only_member_is_flagged_for_the_instructor(armed, monkeypatch):
    monkeypatch.setattr(galileo, "find_user",
                        lambda api_url, token, email: {"id": "u1", "role": "read_only"})
    a_participant("viewer@example.com")
    creator.tick()
    row = store.by_email("viewer@example.com")
    assert row["galileo_state"] == "existing"
    assert "read-only" in row["galileo_error"]


def test_an_account_elsewhere_gets_a_workshop_account_at_once(armed, monkeypatch):
    def taken(*a, **k):
        raise galileo.Duplicate("signup_link: email already has a Galileo account (HTTP 409)")
    monkeypatch.setattr(galileo, "create_user", taken)
    store.add_pool(["participant1@galileo.ai"])
    a_participant("elsewhere@example.com")
    creator.tick()
    row = store.by_email("elsewhere@example.com")
    assert row["galileo_state"] == "pool" and row["attempts"] == 1
    assert row["galileo_email"] == "participant1@galileo.ai"
    assert "outside this organisation" in row["galileo_error"]
