"""The pages, and the line between what a visitor can read and what a participant can."""
from app import security, store
from app.config import settings
from tests.conftest import add_boxes

SECRETS = ["test-llm-key", "test-galileo-password", "test-bank-password",
           "test-presenter-password", "test-passphrase", "test-admin"]


def test_every_page_is_public_and_carries_no_credentials(client):
    """The whole point of the details card: the guide can be handed to anyone, and nothing in the
    page source gets them into an instance or onto the gateway."""
    for path in ("/", "/briefing", "/lab", "/troubleshooting", "/register"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Splunky Finance" in response.text, path
        for secret in SECRETS:
            assert secret not in response.text, (path, secret)


def test_every_page_carries_the_menu_and_marks_where_you_are(client):
    for path, label in (("/briefing", "Briefing &amp; Setup"), ("/lab", "Workshop lab"),
                        ("/troubleshooting", "Troubleshooting")):
        page = client.get(path).text
        for _, href, _ in (("home", "/", ""), ("b", "/briefing", ""), ("l", "/lab", "")):
            assert f'href="{href}"' in page
        assert f'class="here" aria-current="page">{label}</a>' in page


def test_the_overview_offers_check_in_until_you_have(client):
    page = client.get("/").text
    assert 'id="check-in"' in page and 'name="passphrase"' in page
    client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Ada Lovelace", "email": "ada@example.com"})
    page = client.get("/").text
    assert 'name="passphrase"' not in page
    assert "Welcome back, Ada." in page


def test_the_wrong_passphrase_creates_nothing(client):
    response = client.post("/register", data={
        "passphrase": "not-it", "name": "Mallory", "email": "mallory@example.com"})
    assert response.status_code == 403
    assert "passphrase" in response.text.lower()
    assert store.by_email("mallory@example.com") is None
    assert store.counts()["participants"] == 0


def test_the_passphrase_is_checked_before_the_email(client):
    """An unauthorised visitor must not be able to tell whether an address is registered, and must
    not be able to create Galileo accounts in the tenant by submitting addresses."""
    store.register("Ada", "ada@example.com")

    def attempt(email):
        response = client.post("/register", data={
            "passphrase": "not-it", "name": "Mallory", "email": email})
        return response.status_code, response.text.replace(email, "EMAIL")

    assert attempt("ada@example.com") == attempt("nobody@example.com")
    assert attempt("ada@example.com")[0] == 403


def test_registering_lands_on_my_lab_with_a_cookie(client):
    add_boxes(1)
    response = client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Ada Lovelace", "email": "ada@example.com"})
    assert response.status_code == 200
    assert "here is your lab" in response.text.lower()
    assert "lab_participant" in client.cookies


def test_a_bad_email_is_refused_without_consuming_an_instance(client):
    add_boxes(1)
    response = client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Ada", "email": "not-an-email"})
    assert response.status_code == 400
    assert store.counts()["boxes_free"] == 1


def test_credentials_need_the_cookie(client):
    assert client.get("/api/credentials").status_code == 401


def test_a_registered_participant_gets_the_model_details(registered):
    add_boxes(1)
    body = registered.get("/api/credentials").json()
    assert body["llm"] == {
        "base_url": "https://llm.example/v1",
        "model": "test-model",
        "api_key": "test-llm-key",
        "integration_json": body["llm"]["integration_json"],
    }
    assert "Bearer test-llm-key" in body["llm"]["integration_json"]
    assert body["instance"]["password"] == "test-bank-password"


def test_the_galileo_password_is_withheld_until_the_account_exists(registered):
    body = registered.get("/api/credentials").json()
    assert body["galileo"]["ready"] is False
    assert body["galileo"]["password"] == ""
    participant = store.by_email("ada@example.com")
    store.set_galileo(participant["id"], "ready", email="ada@example.com")
    body = registered.get("/api/credentials").json()
    assert body["galileo"]["ready"] is True
    assert body["galileo"]["password"] == "test-galileo-password"


def test_a_forged_cookie_is_refused(client):
    client.cookies.set("lab_participant", "sometoken.deadbeef")
    assert client.get("/api/credentials").status_code == 401


def test_a_script_hammering_the_form_is_slowed_down(client, monkeypatch):
    monkeypatch.setattr(security.passphrase_attempts, "limit", 3)
    codes = [client.post("/register", data={
        "passphrase": "wrong", "name": "M", "email": "m@example.com"}).status_code
        for _ in range(5)]
    assert codes == [403, 403, 403, 429, 429]


def test_the_limits_are_loose_enough_for_a_room_on_one_wifi():
    """A hundred people behind the venue's NAT arrive from one address. A limit that locks them out
    of each other's registrations is a worse failure than the one it prevents."""
    assert security.passphrase_attempts.limit >= 100
    assert security.registrations.limit >= 100


def test_registration_closes_at_the_cap(client, monkeypatch):
    monkeypatch.setattr(settings, "account_cap", 1)
    store.register("First", "first@example.com")
    response = client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Second", "email": "second@example.com"})
    assert response.status_code == 409
    assert "closed" in response.text.lower()


def test_my_lab_sends_a_stranger_to_the_form(client):
    response = client.get("/my-lab", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/register"


def test_clearing_the_browser_keeps_the_instance_for_that_email(registered):
    add_boxes(1)
    before = store.by_email("ada@example.com")["box_id"]
    registered.post("/forget")
    assert store.by_email("ada@example.com")["box_id"] == before


def test_the_admin_page_asks_for_a_password(client):
    page = client.get("/admin")
    assert page.status_code == 200
    assert "Admin password" in page.text
    assert "Roster" not in page.text


def test_admin_uploads_instances_and_arms_nothing_by_accident(client):
    client.post("/admin/login", data={"password": "test-admin"})
    response = client.post("/admin/boxes", data={"pasted": "https://p01.example.show"})
    assert "Added 1 instance" in response.text
    assert store.counts()["boxes_total"] == 1
    assert client.get("/healthz").json()["armed"] is False


def test_admin_actions_refuse_a_stranger(client):
    for path in ("/admin/boxes", "/admin/pool", "/admin/arm", "/admin/disarm"):
        response = client.post(path, data={"pasted": "https://x.example", "api_key": "k"},
                               follow_redirects=False)
        assert response.status_code == 303, path
    assert store.counts()["boxes_total"] == 0
    export = client.get("/admin/export.csv", follow_redirects=False)
    assert export.status_code == 303


def test_an_instance_list_uploaded_as_the_pool_is_rejected(client):
    client.post("/admin/login", data={"password": "test-admin"})
    response = client.post("/admin/pool", data={"pasted": "https://p01.example.show"})
    assert "No email addresses" in response.text
    assert store.counts()["pool_total"] == 0


def test_the_export_is_a_csv_attachment(client):
    add_boxes(1)
    store.register("Ada Lovelace", "ada@example.com")
    client.post("/admin/login", data={"password": "test-admin"})
    response = client.get("/admin/export.csv")
    assert response.headers["content-disposition"].endswith('filename="lab-roster.csv"')
    assert "ada@example.com" in response.text


def admin(client):
    client.post("/admin/login", data={"password": "test-admin"})
    return client


def test_the_admin_page_can_change_the_passphrase(client):
    """The repository is public, so the passphrase has to be settable without touching it."""
    admin(client).post("/admin/passphrase", data={"passphrase": "  new-room-phrase  "})
    old = client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Ada", "email": "ada@example.com"})
    assert old.status_code == 403
    new = client.post("/register", data={
        "passphrase": "new-room-phrase", "name": "Ada", "email": "ada@example.com"})
    assert new.status_code == 200
    assert store.by_email("ada@example.com") is not None


def test_a_short_passphrase_is_refused_and_nothing_changes(client):
    page = admin(client).post("/admin/passphrase", data={"passphrase": "abc"}).text
    assert "at least 6 characters" in page
    assert store.get_config("passphrase") == (None, None)


def test_a_stranger_cannot_change_the_passphrase(client):
    response = client.post("/admin/passphrase", data={"passphrase": "hijacked-phrase"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert store.get_config("passphrase") == (None, None)


def test_changing_the_passphrase_logs_that_it_changed_but_not_to_what(client):
    admin(client).post("/admin/passphrase", data={"passphrase": "secret-room-phrase"})
    events = store.recent_events()
    assert any(e["kind"] == "config-changed" and e["detail"] == "passphrase" for e in events)
    assert not any("secret-room-phrase" in e["detail"] for e in events)


def test_the_tab_icon_is_the_badge(client):
    icon = client.get("/favicon.ico")
    assert icon.status_code == 200
    assert icon.headers["content-type"] == "image/x-icon"
    page = client.get("/").text
    assert 'href="/static/icon-32.png"' in page and 'href="/static/apple-touch-icon.png"' in page
    assert "favicon.svg" not in page
    assert client.get("/static/icon-192.png").status_code == 200


def test_the_headline_is_solid_letters_in_splunk_colours(client):
    """No gradient clipped to text anywhere: that is what looked grainy on a Retina screen."""
    page = client.get("/").text
    assert 'aria-label="Splunk Agent Observability"' in page
    assert '<span style="color: #EB008B">S</span>' in page
    assert '<span style="color: #F99D1C">y</span>' in page
    assert "background-clip: text" not in client.get("/static/app.css").text


def test_a_malformed_instance_row_is_never_shown_to_anyone(client):
    """Defence in depth: even a row stored before the parser was fixed stays out of sight."""
    leaked = "Hunter2-Secret\tssh -p 2222 splunk@3.91.84.26\thttps://p01.example.show"
    store.add_boxes([(leaked, "")])
    client.post("/register", data={
        "passphrase": "test-passphrase", "name": "Ada Lovelace", "email": "ada@example.com"})
    assert client.get("/api/credentials").json()["instance"]["url"] == ""
    assert client.get("/api/status").json()["box_url"] == ""
    assert "Hunter2" not in client.get("/").text
    page = admin(client).get("/admin").text
    assert "Hunter2" not in page
    assert "not a URL" in page and "Probably a whole line" in page
    assert "Hunter2" not in client.get("/admin/export.csv").text


def test_the_admin_page_lists_instances_and_can_remove_one(client):
    add_boxes(2)
    page = admin(client).get("/admin").text
    assert "https://p01.example.show" in page and "https://p02.example.show" in page
    box = store.boxes()[0]
    client.post(f"/admin/boxes/{box['id']}/remove")
    assert [b["url"] for b in store.boxes()] == ["https://p02.example.show"]


def test_a_stranger_cannot_remove_an_instance(client):
    add_boxes(1)
    response = client.post(f"/admin/boxes/{store.boxes()[0]['id']}/remove", follow_redirects=False)
    assert response.status_code == 303
    assert store.counts()["boxes_total"] == 1


def test_someone_with_their_own_account_is_not_shown_the_shared_password(registered):
    person = store.by_email("ada@example.com")
    store.set_galileo(person["id"], "existing", email="ada@example.com", password="")
    galileo = registered.get("/api/credentials").json()["galileo"]
    assert galileo["ready"] and galileo["existing"]
    assert galileo["email"] == "ada@example.com" and galileo["password"] == ""


def test_the_integration_snippet_is_ready_to_paste(registered):
    """Real gateway, model and key, and a readable alias for Galileo's model picker."""
    import json
    snippet = json.loads(registered.get("/api/credentials").json()["llm"]["integration_json"])
    assert snippet["endpoint"] == "https://llm.example/v1"
    assert snippet["default_model"] == "test-model"
    model = snippet["model_properties"][0]
    assert model["name"] == "test-model" and model["alias"] == "Test Model"
    assert snippet["api_key_value"] == "Bearer test-llm-key"


def test_my_lab_opens_the_snippet(registered):
    assert "data-open-snippet" in registered.get("/my-lab").text


def test_the_alias_reads_like_a_name():
    from app.routes.api import model_alias
    assert model_alias("my-gateway-model") == "My Gateway Model"
    assert model_alias("gpt_4o-mini") == "Gpt 4o Mini"


def test_the_lab_page_carries_the_live_snippet_slot_and_no_key(registered):
    page = registered.get("/lab").text
    assert "data-integration-snippet" in page
    assert "test-llm-key" not in page and "YOUR_TOKEN" not in page


def test_the_evaluator_steps_name_the_model_from_the_settings(client):
    from app import runtime
    page = client.get("/lab").text
    assert page.count('<span class="model-alias">Test Model</span>') == 7
    assert "data-model-alias" not in page
    runtime.put("llm_model", "another-gateway-model")
    assert '<span class="model-alias">Another Gateway Model</span>' in client.get("/lab").text


def test_the_overview_embeds_the_video_above_check_in(client):
    page = client.get("/").text
    video = page.index('src="https://www.youtube-nocookie.com/embed/QAbMEZI2NdM?rel=0"')
    assert video < page.index('id="check-in"')
    assert 'loading="lazy"' in page and "allowfullscreen" in page
    assert "youtube-nocookie" not in client.get("/register").text
