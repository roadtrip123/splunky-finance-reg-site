"""The progress tracker: what an instance's status means for each step, how the tracker reads it,
and what the admin board and the participant's buttons show. Payloads follow the shapes the
Splunky Finance instance returns from /ready and /api/demo-admin/status."""
import requests

from app import store
from app.tracker import SELF_STEPS, evaluate, tracker
from tests.conftest import add_boxes

FRESH_READY = {"status": "ready", "data": "valid", "model": "unconfigured", "galileo": "unconfigured"}


def status(galileo=None, provider="unconfigured", agent=None, stages=None):
    # "unconfigured" is what a live instance with no model set reports.
    base = {"state": "unconfigured", "connection": "not_checked", "project_id": None,
            "log_stream_id": None, "export": "not_attempted"}
    return {"galileo": {**base, **(galileo or {})}, "provider_status": {"state": provider},
            "agent": agent or {}, "protection_stages": stages or {}, "protection_status": "unverified"}


CONNECTED = {"state": "connected", "connection": "connected", "project_id": "p1",
             "log_stream_id": "s1"}


def test_a_fresh_instance_shows_nothing_done():
    assert evaluate(FRESH_READY, status()) == (set(), set(), "")


def test_connected_to_galileo_with_a_model_set_is_steps_one_and_two_with_three_under_way():
    done, partial, _ = evaluate({**FRESH_READY, "model": "configured"}, status(CONNECTED))
    assert done == {1, 2} and partial == {3}


def test_a_model_answering_and_a_trace_exported_is_step_three():
    done, _, _ = evaluate(FRESH_READY, status({**CONNECTED, "export": "exported"}, "connected"))
    assert {1, 2, 3} <= done


def test_a_guardrail_that_decided_is_steps_seven_and_eight():
    done, _, _ = evaluate(FRESH_READY, status(CONNECTED, agent={"state": "registered"},
                                              stages={"pre": {"status": "verified"}}))
    assert {7, 8} <= done


def test_a_guardrail_registered_but_not_deciding_is_step_seven_under_way():
    done, partial, note = evaluate(FRESH_READY, status(
        CONNECTED, agent={"state": "registered"}, stages={"pre": {"status": "failed"}}))
    assert 7 not in done and 7 in partial
    assert "guardrail failing" in note


def test_failures_are_named_rather_than_left_blank():
    _, partial, note = evaluate(FRESH_READY, status({"state": "failed", "connection": "failed"}))
    assert 2 in partial and "Galileo connection failing" in note


def test_the_ticked_steps_are_the_ones_no_instance_can_show():
    assert SELF_STEPS == (1, 4, 5, 6)


class FakeResponse:
    def __init__(self, code, payload=None):
        self.status_code = code
        self.ok = 200 <= code < 300
        self.headers = {"content-type": "application/json"}
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    """An instance that wants a presenter login before it shows status."""

    def __init__(self, status_payload, login_code=200):
        self.logged_in = False
        self.status_payload = status_payload
        self.login_code = login_code
        self.posts = []

    def get(self, url, timeout=None):
        if url.endswith("/ready"):
            return FakeResponse(200, {**FRESH_READY, "model": "configured", "galileo": "connected"})
        return FakeResponse(200, self.status_payload) if self.logged_in else FakeResponse(401)

    def post(self, url, timeout=None, json=None, headers=None):
        self.posts.append((url, json, headers))
        self.logged_in = self.login_code == 200
        return FakeResponse(self.login_code)


def a_participant_on_an_instance():
    add_boxes(1)
    person, _ = store.register("Ada Lovelace", "ada@example.com")
    return person, store.assigned_boxes()[0]


def test_the_tracker_logs_in_as_presenter_reads_status_and_records_steps(monkeypatch):
    person, box = a_participant_on_an_instance()
    fake = FakeSession(status({**CONNECTED, "export": "exported"}, "connected"))
    monkeypatch.setattr(tracker, "_session", lambda box_id: fake)
    done, _, _ = tracker.probe(box)
    assert {1, 2, 3} <= done
    url, body, headers = fake.posts[0]
    assert url == "https://p01.example.show/api/demo-admin/login"
    assert body == {"password": "test-presenter-password"}
    assert headers == {"Origin": "https://p01.example.show"}
    marked = {s["step"] for s in store.steps_for(person["id"], "auto")}
    assert marked == {1, 2, 3}


def test_a_refused_presenter_login_is_reported(monkeypatch):
    _, box = a_participant_on_an_instance()
    monkeypatch.setattr(tracker, "_session", lambda box_id: FakeSession(status(), login_code=401))
    _, _, note = tracker.probe(box)
    assert "presenter login refused" in note


def test_an_unreachable_instance_is_reported(monkeypatch):
    _, box = a_participant_on_an_instance()

    class Down:
        def get(self, *a, **k):
            raise requests.ConnectionError("down")

    monkeypatch.setattr(tracker, "_session", lambda box_id: Down())
    tracker.probe(box)
    row = store.progress_board()[0]
    assert row["reachable"] == 0 and "unreachable" in row["note"]


def test_the_board_finds_the_current_step_and_who_is_stuck():
    person, _ = a_participant_on_an_instance()
    start = person["created_at"]
    for step in (1, 2):
        store.mark_step(person["id"], step, "auto")
    with store.writing() as db:
        db.execute("UPDATE progress SET at=? WHERE participant_id=?", (start + 60, person["id"]))
    row = store.progress_board(stuck_after=600, now=start + 60 + 700)[0]
    assert row["current"] == 3 and row["minutes"] == 11 and row["stuck"]
    assert [c["state"] for c in row["cells"]][:3] == ["auto", "auto", "none"]
    fresh = store.progress_board(stuck_after=600, now=start + 120)[0]
    assert not fresh["stuck"]


def test_a_participant_ticks_and_unticks_a_console_step(registered):
    response = registered.post("/api/progress", json={"step": 4, "done": True})
    assert response.status_code == 200
    person = store.by_email("ada@example.com")
    assert [s["step"] for s in store.steps_for(person["id"], "self")] == [4]
    registered.post("/api/progress", json={"step": 4, "done": False})
    assert store.steps_for(person["id"], "self") == []


def test_a_step_the_instance_shows_cannot_be_ticked(registered):
    assert registered.post("/api/progress", json={"step": 7, "done": True}).status_code == 400


def test_ticking_needs_a_participant(client):
    assert client.post("/api/progress", json={"step": 4, "done": True}).status_code == 401


def test_the_guide_offers_done_buttons_on_the_ticked_steps_only_when_checked_in(client):
    assert "data-step-toggle" not in client.get("/briefing").text
    client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Ada Lovelace", "email": "ada@example.com"})
    briefing, lab = client.get("/briefing").text, client.get("/lab").text
    assert 'data-step="1"' in briefing and 'data-step="2"' not in briefing
    assert 'data-step="4"' in lab and 'data-step="5"' in lab and 'data-step="6"' in lab
    assert 'data-step="7"' not in lab


def test_the_admin_board_shows_people_and_needs_the_admin(client):
    add_boxes(1)
    store.register("Ada Lovelace", "ada@example.com")
    assert client.get("/admin/progress").status_code == 401
    client.post("/admin/login", data={"password": "test-admin"})
    fragment = client.get("/admin/progress").text
    assert "Ada Lovelace" in fragment and "Step 1" in fragment
    assert "data-progress" in client.get("/admin").text


def test_a_real_unconfigured_instance_shows_nothing():
    """The shape a deployed instance returned: /ready is the front end's 404, so no ready data."""
    real = {"galileo": {"state": "unconfigured", "connection": "unconfigured",
                        "export": "not_attempted", "project_id": None, "log_stream_id": None,
                        "last_error": "Galileo credentials missing"},
            "provider_status": {"state": "unconfigured"}, "agent": {"state": "not_attempted"},
            "protection_status": "unverified", "protection_stages": {}}
    assert evaluate(None, real) == (set(), set(), "")


def test_a_configured_model_shows_step_three_under_way_without_ready():
    done, partial, _ = evaluate(None, status(CONNECTED, provider="unverified"))
    assert done == {1, 2} and 3 in partial
