"""G245 (arrival join): when a Contacts card first showed, kept outside every bank so "newly appeared" can be read for a card.

A card keeps no creation day (the app asks for none), and the waiting file is rewritten whole by every sync. So the sync keeps
a `seen` set — every card id the book has ever shown, by its hash — with the day each was first seen WAITING, and two guards
against a bulk arrival: the previous sync at most three days before, and no more than five new cards in this one (a phone
restore, an iCloud merge or a vCard import adds hundreds at once). The first sync marks everything seen with no day; a card that
ever carried a page is never stamped, so one that returns to waiting after a split or an undo is not "new". Synthetic people."""
from __future__ import annotations

from datetime import date

import pytest

from _synthetic_bank import _bank, _entity
from api.services import contacts_local, people_directory


class FakeDate(date):
    _today = date(2026, 11, 10)

    @classmethod
    def today(cls):
        return cls._today


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(contacts_local, "date", FakeDate)
    mem = _bank(tmp_path)

    class Book:
        memory = mem

        def on(self, day: str):
            FakeDate._today = date.fromisoformat(day)

        def sync(self, *names, day=None):
            if day:
                self.on(day)
            cards = [{"id": f"id-{given}-{family}", "given_name": given, "family_name": family} for given, family in names]
            return contacts_local.sync(mem, {"contacts": cards})

        def seen(self):
            return contacts_local.first_seen(mem.name)

        def stamp(self, given, family):
            return self.seen()[0][contacts_local.card_hash(f"id-{given}-{family}")]

    return Book()


def test_the_first_sync_marks_every_card_seen_with_no_day(book):
    book.sync(("Ann", "Berg"), ("Cy", "Dale"), day="2026-11-01")
    seen, synced = book.seen()
    assert synced == "2026-11-01" and len(seen) == 2 and set(seen.values()) == {None}


def test_a_new_card_in_a_later_sync_is_stamped_with_the_day_it_first_waited(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    book.sync(("Ann", "Berg"), ("Eve", "Fox"), day="2026-11-03")
    assert book.stamp("Eve", "Fox") == "2026-11-03" and book.stamp("Ann", "Berg") is None


def test_a_stamp_never_moves_once_kept(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    book.sync(("Ann", "Berg"), ("Eve", "Fox"), day="2026-11-03")
    book.sync(("Ann", "Berg"), ("Eve", "Fox"), day="2026-11-09")
    assert book.stamp("Eve", "Fox") == "2026-11-03"


def test_a_sync_more_than_three_days_after_the_last_stamps_nothing_new(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    book.sync(("Ann", "Berg"), ("Eve", "Fox"), day="2026-11-05")      # four days: a card could have come any day since
    assert book.stamp("Eve", "Fox") is None
    assert book.stamp("Ann", "Berg") is None


def test_exactly_three_days_is_trusted(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    book.sync(("Ann", "Berg"), ("Eve", "Fox"), day="2026-11-04")
    assert book.stamp("Eve", "Fox") == "2026-11-04"


def test_a_bulk_arrival_stamps_none_of_that_syncs_new_cards(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    new = [("Pat", f"Restore{n}") for n in range(300)]          # a phone restore adds hundreds at once
    book.sync(("Ann", "Berg"), *new, day="2026-11-02")
    seen, _ = book.seen()
    assert len(seen) == 301 and set(seen.values()) == {None}
    assert people_directory.load_json(book.memory.name, contacts_local.SEEN_FILE)["bulk"] == 300


def test_five_new_cards_is_a_week_s_acquaintances_and_six_is_a_bulk_arrival(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    five = [("New", f"Card{n}") for n in range(5)]
    book.sync(("Ann", "Berg"), *five, day="2026-11-02")
    assert {book.stamp(*c) for c in five} == {"2026-11-02"}
    six = [("Next", f"Card{n}") for n in range(6)]
    book.sync(("Ann", "Berg"), *five, *six, day="2026-11-03")
    assert {book.stamp(*c) for c in six} == {None}


def test_a_card_that_matched_a_page_is_never_stamped_even_if_it_returns_to_waiting(book):
    _entity(book.memory, "gus-hale", type="person", name="Gus Hale")
    book.sync(("Ann", "Berg"), day="2026-11-01")
    book.sync(("Ann", "Berg"), ("Gus", "Hale"), day="2026-11-02")           # new, but it matched a page: it carried one
    assert book.stamp("Gus", "Hale") is None
    (book.memory / "entities" / "gus-hale.md").unlink()                      # the page goes (a split, an archive, an undo)
    from api.services import bank_index

    bank_index.invalidate(book.memory)
    book.sync(("Ann", "Berg"), ("Gus", "Hale"), day="2026-11-03")
    assert book.stamp("Gus", "Hale") is None
    assert [c["given_name"] for c in contacts_local.load_waiting(book.memory.name)] == ["Ann", "Gus"]


def test_a_stamped_card_that_later_matches_a_page_is_unstamped_for_good(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    book.sync(("Ann", "Berg"), ("Eve", "Fox"), day="2026-11-02")
    assert book.stamp("Eve", "Fox") == "2026-11-02"
    _entity(book.memory, "eve-fox", type="person", name="Eve Fox")
    book.sync(("Ann", "Berg"), ("Eve", "Fox"), day="2026-11-03")
    assert book.stamp("Eve", "Fox") is None


def test_the_own_card_is_never_recorded(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    contacts_local.sync(book.memory, {"contacts": [{"id": "me", "given_name": "Zed", "family_name": "Self", "is_me": True}]})
    assert contacts_local.card_hash("me") not in book.seen()[0]


def test_nothing_in_the_file_is_a_name_or_a_card_id(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    book.sync(("Ann", "Berg"), ("Eve", "Fox"), day="2026-11-02")
    text = people_directory.path(book.memory.name, contacts_local.SEEN_FILE).read_text()
    for secret in ("Ann", "Berg", "Eve", "Fox", "id-Eve"):
        assert secret not in text


def test_stopping_contacts_wipes_when_each_card_showed_with_the_cards(book):
    book.sync(("Ann", "Berg"), day="2026-11-01")
    book.sync(("Ann", "Berg"), ("Eve", "Fox"), day="2026-11-02")
    contacts_local.forget_waiting()
    assert not people_directory.path(book.memory.name, contacts_local.SEEN_FILE).exists()
    assert book.seen() == ({}, None)
