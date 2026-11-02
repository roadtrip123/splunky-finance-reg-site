"""Recognising a taken email in Galileo's answers, whose exact wording is not documented."""
import pytest

from app import galileo


class Answer:
    def __init__(self, code, text="", payload=None):
        self.status_code, self.text, self._payload = code, text, payload or {}

    def json(self):
        return self._payload


@pytest.mark.parametrize("code, text", [
    (409, "Conflict"),
    (400, '{"detail": "User with this email already exists"}'),
    (422, "email is already registered"),
    (400, "Email address in use"),
])
def test_a_taken_email_is_a_duplicate(monkeypatch, code, text):
    monkeypatch.setattr(galileo, "_request", lambda *a, **k: Answer(code, text))
    with pytest.raises(galileo.Duplicate):
        galileo.create_user("https://api.example", "t", "a@example.com", "pw")


def test_any_other_refusal_is_not_mistaken_for_one(monkeypatch):
    monkeypatch.setattr(galileo, "_request", lambda *a, **k: Answer(400, "invalid email format"))
    with pytest.raises(galileo.GalileoError) as caught:
        galileo.create_user("https://api.example", "t", "a@example.com", "pw")
    assert not isinstance(caught.value, galileo.Duplicate)


def test_find_user_returns_the_member_or_none(monkeypatch):
    monkeypatch.setattr(galileo, "_request",
                        lambda *a, **k: Answer(200, payload={"users": [{"id": "u1"}]}))
    assert galileo.find_user("https://api.example", "t", "a@example.com") == {"id": "u1"}
    monkeypatch.setattr(galileo, "_request", lambda *a, **k: Answer(200, payload={"users": []}))
    assert galileo.find_user("https://api.example", "t", "a@example.com") is None


def test_a_rejected_token_on_lookup_says_to_re_arm(monkeypatch):
    monkeypatch.setattr(galileo, "_request", lambda *a, **k: Answer(401))
    with pytest.raises(galileo.GalileoError, match="re-arm"):
        galileo.find_user("https://api.example", "t", "a@example.com")
