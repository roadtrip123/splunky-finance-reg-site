"""Settings changed on the admin page: the gateway, the Galileo password, the admin password."""
import pytest
import requests

from app import gateway, runtime, store
from app.worker import creator
from tests.conftest import add_boxes


def admin(client):
    client.post("/admin/login", data={"password": "test-admin"})
    return client


@pytest.fixture
def check_passes(monkeypatch):
    calls = []
    monkeypatch.setattr(gateway, "check", lambda url, key, model: calls.append((url, key, model))
                        or (True, f"gateway answers, key accepted, {model} available"))
    return calls


def test_the_gateway_can_be_changed_and_participants_see_it(client, check_passes):
    admin(client)
    page = client.post("/admin/settings/gateway", data={
        "base_url": "https://new-gateway.example/v1/", "model": "new-model",
        "api_key": "new-key-1234567890"}).text
    assert "Model gateway saved" in page and "new-model available" in page
    assert check_passes[-1] == ("https://new-gateway.example/v1", "new-key-1234567890", "new-model")
    client.cookies.clear()
    client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Ada Lovelace", "email": "ada@example.com"})
    llm = client.get("/api/credentials").json()["llm"]
    assert (llm["base_url"], llm["model"], llm["api_key"]) == (
        "https://new-gateway.example/v1", "new-model", "new-key-1234567890")


def test_a_blank_key_keeps_the_current_one(client, check_passes):
    admin(client).post("/admin/settings/gateway", data={
        "base_url": "https://llm.example/v1", "model": "test-model", "api_key": ""})
    assert runtime.get("llm_api_key") == "test-llm-key"


def test_the_admin_page_never_shows_the_gateway_key(client):
    runtime.put("llm_api_key", "sk-very-secret-gateway-key-9876")
    page = admin(client).get("/admin").text
    assert "sk-very-secret-gateway-key" not in page
    assert "ends 9876" in page


def test_a_gateway_url_that_is_not_a_url_is_refused(client, check_passes):
    page = admin(client).post("/admin/settings/gateway", data={
        "base_url": "litellm dot something", "model": "m", "api_key": ""}).text
    assert "must be a full https://" in page
    assert check_passes == []


def test_a_failed_check_is_shown_but_the_value_is_kept(client, monkeypatch):
    monkeypatch.setattr(gateway, "check", lambda *a: (False, "no model list at that URL"))
    page = admin(client).post("/admin/settings/gateway", data={
        "base_url": "https://llm.example", "model": "test-model", "api_key": ""}).text
    assert "the check failed: no model list at that URL" in page
    assert runtime.get("llm_base_url") == "https://llm.example"


class Answer:
    def __init__(self, code, payload=None):
        self.status_code, self.ok, self._payload = code, 200 <= code < 300, payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


@pytest.mark.parametrize("answer, url, ok, words", [
    (Answer(200, {"data": [{"id": "m1"}, {"id": "test-model"}]}), "https://g/v1", True,
     "test-model available"),
    (Answer(200, {"data": [{"id": "m1"}]}), "https://g/v1", False, "not among the 1 models"),
    (Answer(401), "https://g", False, "should end in /v1"),
    (Answer(403), "https://g/v1", False, "refused the request (HTTP 403)"),
    (Answer(404), "https://g", False, "should end in /v1"),
])
def test_the_gateway_check_says_what_is_wrong(monkeypatch, answer, url, ok, words):
    monkeypatch.setattr(requests, "get", lambda *a, **k: answer)
    result_ok, message = gateway.check(url, "secret-key-value", "test-model")
    assert result_ok is ok and words in message
    assert "secret-key-value" not in message


def test_an_unreachable_gateway_is_reported(monkeypatch):
    def down(*a, **k):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", down)
    assert gateway.check("https://g/v1", "k", "m") == (False, "gateway unreachable (ConnectionError)")


def test_changing_the_galileo_password_spares_existing_accounts(client, monkeypatch):
    from app import galileo
    monkeypatch.setattr(galileo, "exchange_api_key", lambda url, key: ("token", {}))
    monkeypatch.setattr(galileo, "find_user", lambda url, token, email: None)
    used = []
    monkeypatch.setattr(galileo, "create_user",
                        lambda url, token, email, password, **kw: used.append(password) or email)
    creator.arm("key")
    add_boxes(2)
    first, _ = store.register("First Person", "first@example.com")
    creator.tick()
    admin(client).post("/admin/settings/galileo-password", data={"password": "brand-new-pass"})
    second, _ = store.register("Second Person", "second@example.com")
    creator.tick()
    assert used == ["test-galileo-password", "brand-new-pass"]
    assert store.by_email("first@example.com")["galileo_password"] == "test-galileo-password"
    assert store.by_email("second@example.com")["galileo_password"] == "brand-new-pass"


def test_fallback_accounts_keep_the_installer_password(client):
    runtime.put("galileo_password", "changed-on-the-day")
    store.add_pool(["participant1@galileo.ai"])
    person, _ = store.register("Ada", "ada@example.com")
    store.issue_pool_account(person["id"])
    assert store.by_email("ada@example.com")["galileo_password"] == "test-galileo-password"


def test_a_short_galileo_password_is_refused(client):
    page = admin(client).post("/admin/settings/galileo-password", data={"password": "short"}).text
    assert "at least 8 characters" in page
    assert runtime.source("galileo_password")[0] == "install"


def test_the_admin_password_can_be_changed(client):
    admin(client).post("/admin/settings/admin-password", data={
        "current": "test-admin", "new": "a-new-admin-pass", "confirm": "a-new-admin-pass"})
    client.cookies.clear()
    assert "Wrong password" in client.post("/admin/login", data={"password": "test-admin"}).text
    client.post("/admin/login", data={"password": "a-new-admin-pass"})
    assert "Instructor console" in client.get("/admin").text


@pytest.mark.parametrize("form, words", [
    ({"current": "wrong", "new": "a-new-admin-pass", "confirm": "a-new-admin-pass"}, "not right"),
    ({"current": "test-admin", "new": "short", "confirm": "short"}, "at least 8"),
    ({"current": "test-admin", "new": "a-new-admin-pass", "confirm": "different-pass"}, "do not match"),
])
def test_a_bad_admin_password_change_is_refused(client, form, words):
    page = admin(client).post("/admin/settings/admin-password", data=form).text
    assert words in page
    assert runtime.source("admin_password")[0] == "install"


def test_settings_refuse_a_stranger(client):
    for path, form in (("/admin/settings/gateway", {"base_url": "https://x.example/v1", "model": "m"}),
                       ("/admin/settings/galileo-password", {"password": "hijacked-pass"}),
                       ("/admin/settings/admin-password", {"current": "x", "new": "y" * 9,
                                                           "confirm": "y" * 9})):
        assert client.post(path, data=form, follow_redirects=False).status_code == 303
    assert all(runtime.source(n)[0] == "install" for n in runtime.EDITABLE)


def test_the_galileo_organisation_can_be_set_and_participants_are_sent_there(client):
    page = admin(client).post("/admin/settings/galileo-console", data={
        "console_url": "https://console.multitenant.galileocloud.io/cisco-live-apjc/"}).text
    assert "Participants are now sent to https://console.multitenant.galileocloud.io/cisco-live-apjc." in page
    assert runtime.get("galileo_console_url") == "https://console.multitenant.galileocloud.io/cisco-live-apjc"
    client.cookies.clear()
    client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Ada Lovelace", "email": "ada@example.com"})
    galileo = client.get("/api/credentials").json()["galileo"]
    assert galileo["console_url"] == "https://console.multitenant.galileocloud.io/cisco-live-apjc"


def test_a_console_url_that_is_not_https_is_refused(client):
    page = admin(client).post("/admin/settings/galileo-console",
                              data={"console_url": "console.multitenant.galileocloud.io/x"}).text
    assert "must be a full https:// address" in page
    assert runtime.source("galileo_console_url")[0] == "install"


def test_the_admin_page_shows_where_participants_are_sent(client):
    page = admin(client).get("/admin").text
    assert "Galileo organisation" in page
    assert "Participants are sent to" in page and "https://console.example" in page
