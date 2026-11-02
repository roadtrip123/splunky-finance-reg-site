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


SPLUNK_SHOW_EXPORT = ("sshPassword{d}sshUrl{d}url\n"
                      "Hunter2-Secret{d}ssh -p 2222 splunk@3.91.84.26{d}https://p01.example.show\n"
                      "Hunter2-Secret{d}ssh -p 2222 splunk@3.232.133.207{d}https://p02.example.show.\n")


def test_the_splunk_show_export_parses_in_any_separator_and_keeps_only_urls():
    """The platform's export carries an SSH password in every row. A tab-separated copy once came
    through as whole lines, password included, ready to be shown to a participant as their app."""
    for delimiter in (",", "\t", ";"):
        rows = store.parse_csv(SPLUNK_SHOW_EXPORT.format(d=delimiter))
        assert rows == [("https://p01.example.show", ""), ("https://p02.example.show", "")], delimiter
        assert "Hunter2" not in repr(rows)


def test_uploading_the_export_stores_no_password():
    store.add_boxes(store.parse_csv(SPLUNK_SHOW_EXPORT.format(d="\t")))
    stored = [box["url"] for box in store.boxes()]
    assert stored == ["https://p01.example.show", "https://p02.example.show"]


def test_clean_url_accepts_only_a_bare_url():
    assert store.clean_url(" https://p01.example.show ") == "https://p01.example.show"
    assert store.clean_url("https://p01.example.show.") == "https://p01.example.show"
    for bad in ("sshPassword\tsshUrl\turl", "Secret\tssh -p 2222 x\thttps://p01.example.show",
                "ftp://p01.example.show", "p01.example.show", "https://", "", None,
                "javascript:alert(1)"):
        assert store.clean_url(bad) == "", bad


def test_removing_an_instance_puts_its_holder_back_in_line():
    add_boxes(2)
    first, _ = store.register("First", "first@example.com")
    store.remove_box(first["box_id"])
    # They are served the remaining free instance rather than left with nothing.
    assert store.by_email("first@example.com")["box_url"] == "https://p02.example.show"
    assert store.counts()["boxes_total"] == 1


def test_moving_someone_to_the_instance_they_actually_use():
    """Mohamed was given one box and worked on another he had started himself."""
    add_boxes(2)
    person, _ = store.register("Mohamed", "mo@example.com")
    given = person["box_id"]
    moved = store.move_to_box(person["id"], "https://galileo2-own-box.example.show/")
    assert moved == "https://galileo2-own-box.example.show"
    row = store.by_email("mo@example.com")
    assert row["box_url"] == "https://galileo2-own-box.example.show"
    old = next(b for b in store.boxes() if b["id"] == given)
    assert old["state"] == "free" and old["participant_id"] is None


def test_moving_onto_a_known_instance_reuses_it_whatever_the_trailing_slash():
    add_boxes(2)
    person, _ = store.register("Mohamed", "mo@example.com")
    store.move_to_box(person["id"], "https://p02.example.show/")
    assert store.counts()["boxes_total"] == 2
    assert store.by_email("mo@example.com")["box_url"] == "https://p02.example.show"


def test_moving_onto_someone_elses_instance_is_refused():
    add_boxes(2)
    first, _ = store.register("First", "first@example.com")
    second, _ = store.register("Second", "second@example.com")
    with pytest.raises(store.MoveRefused, match="already given to First"):
        store.move_to_box(second["id"], first["box_url"])
    assert store.by_email("second@example.com")["box_id"] == second["box_id"]


def test_moving_to_something_that_is_not_a_url_is_refused():
    person, _ = store.register("Mohamed", "mo@example.com")
    with pytest.raises(store.MoveRefused):
        store.move_to_box(person["id"], "galileo2 box")


def test_a_freed_instance_goes_to_whoever_is_waiting():
    add_boxes(1)
    mover, _ = store.register("Mover", "mover@example.com")
    waiting, _ = store.register("Waiting", "waiting@example.com")
    store.move_to_box(mover["id"], "https://own-box.example.show")
    assert store.by_email("waiting@example.com")["box_url"] == "https://p01.example.show"
