"""The database layer, where the only subtle thing is handing out one instance per person."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import store
from app.config import settings
from tests.conftest import add_boxes


def test_a_registration_takes_one_free_instance():
    add_boxes(2)
    participant, created = store.register("Ada", "ada@example.com")
    assert created
    assert participant["box_url"] == "https://p01.example.show"
    assert store.counts()["boxes_free"] == 1


def test_registering_twice_returns_the_same_instance():
    """Someone who reloads the form, or opens it on their phone as well, must not consume two."""
    add_boxes(3)
    first, created_first = store.register("Ada", "Ada@Example.com ")
    second, created_second = store.register("Ada again", "ada@example.com")
    assert created_first and not created_second
    assert first["id"] == second["id"]
    assert first["box_url"] == second["box_url"]
    assert store.counts()["boxes_free"] == 2


def test_simultaneous_registrations_never_share_an_instance():
    add_boxes(10)
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda n: store.register(f"P{n}", f"p{n}@example.com"), range(10)))
    urls = [participant["box_url"] for participant, _ in results]
    assert len(set(urls)) == 10
    assert store.counts()["boxes_free"] == 0


def test_registering_with_no_instances_left_puts_you_in_line():
    participant, _ = store.register("Ada", "ada@example.com")
    assert participant["box_id"] is None
    assert store.counts()["waiting"] == 1


def test_uploading_instances_serves_whoever_was_waiting_first():
    store.register("First", "first@example.com")
    store.register("Second", "second@example.com")
    add_boxes(1)
    assert store.by_email("first@example.com")["box_url"] == "https://p01.example.show"
    assert store.by_email("second@example.com")["box_id"] is None
    assert store.counts()["waiting"] == 1


def test_the_cap_closes_registration(monkeypatch):
    monkeypatch.setattr(settings, "account_cap", 3)
    for n in range(settings.account_cap):
        store.register(f"P{n}", f"p{n}@example.com")
    with pytest.raises(store.RegistrationClosed):
        store.register("One too many", "extra@example.com")


def test_releasing_an_instance_offers_it_to_the_next_person():
    add_boxes(1)
    leaving, _ = store.register("Leaving", "leaving@example.com")
    waiting, _ = store.register("Waiting", "waiting@example.com")
    store.release(leaving["id"])
    assert store.by_email("waiting@example.com")["box_url"] == "https://p01.example.show"
    assert store.by_email("leaving@example.com")["box_id"] is None
    assert store.by_email("leaving@example.com")["state"] == "released"
    assert store.counts()["waiting"] == 0


def test_someone_who_left_and_comes_back_is_served_again():
    add_boxes(2)
    person, _ = store.register("Returning", "returning@example.com")
    store.release(person["id"])
    again, created = store.register("Returning", "returning@example.com")
    assert not created
    assert again["box_url"] and again["state"] == "active"


def test_uploading_the_same_list_twice_adds_nothing():
    assert add_boxes(3) == (3, 0)
    assert add_boxes(3) == (0, 3)
    assert store.counts()["boxes_total"] == 3


def test_a_csv_with_a_url_column_and_a_bare_list_both_parse():
    csv_rows = store.parse_csv("url,label\nhttps://a.example,A\nhttps://b.example,B\n")
    assert csv_rows == [("https://a.example", "A"), ("https://b.example", "B")]
    bare = store.parse_csv("https://a.example\nhttps://b.example\n\n")
    assert bare == [("https://a.example", ""), ("https://b.example", "")]


def test_a_csv_exported_with_a_byte_order_mark_still_parses():
    rows = store.parse_csv("﻿url,label\nhttps://a.example,A\n")
    assert rows == [("https://a.example", "A")]


def test_the_fallback_pool_is_issued_once_per_account():
    store.add_pool(["participant1@galileo.ai", "participant2@galileo.ai"])
    first, _ = store.register("First", "first@example.com")
    second, _ = store.register("Second", "second@example.com")
    assert store.issue_pool_account(first["id"]) == "participant1@galileo.ai"
    assert store.issue_pool_account(second["id"]) == "participant2@galileo.ai"
    assert store.issue_pool_account(second["id"]) is None
    assert store.by_email("first@example.com")["galileo_state"] == "pool"


def test_the_export_carries_what_the_instructor_needs():
    add_boxes(1)
    participant, _ = store.register("Ada Lovelace", "ada@example.com")
    store.set_galileo(participant["id"], "ready", email="ada@example.com")
    text = store.export_csv()
    assert text.splitlines()[0] == "name,email,box_url,galileo_email,galileo_state,registered_at"
    assert "Ada Lovelace,ada@example.com,https://p01.example.show,ada@example.com,ready," in text
