"""G154 (round 4 decision 12; R-SR8, R-SR9): macOS Contacts ENRICHES the people Cicada already knows. The app reads
the address book after one prompt and posts names plus which facts each card holds (never an email or a phone
number); a contact matching exactly one person page adds where to look those facts up as `sources:` and caches its
photo outside the bank; nothing else is stored and no page is ever created. Synthetic people only."""
from __future__ import annotations

import base64
import subprocess

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank, _entity
from api import config, main
from api.services import bank_index, contacts_local, demo_guard, fact_sources, markdown_parser, sleep_cycle

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 60
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)   # has `bob-example` (person, "Bob Example")
    _entity(memory, "carol-example", type="person", name="Carolina Example", aliases=["Carol Example"])
    _entity(memory, "dana-one", type="person", name="Dana Twin")
    _entity(memory, "dana-two", type="person", name="Dana Twin")
    subprocess.run(["git", "-C", str(memory), "add", "entities"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(memory), "commit", "-qm", "fixtures"], check=True, capture_output=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _contact(cid, given, family, *, org=False, title=False, email=False, phone=False, birthday=False, photo=None):
    body = {"id": cid, "givenName": given, "familyName": family, "hasOrganization": org, "hasJobTitle": title,
            "hasEmail": email, "hasPhone": phone, "hasBirthday": birthday}
    if photo is not None:
        body["photoB64"] = base64.b64encode(photo).decode()
    return body


def _post(c, contacts):
    return c.post("/sources/contacts-local/sync", json={"contacts": contacts})


def _page(memory, eid):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md")


def _people(memory):
    return sorted(p.stem for p in (memory / "entities").glob("*.md"))


def test_a_matched_contact_adds_where_to_look_its_facts_up_and_commits_once_as_the_person(client):
    c, memory = client
    before = _people(memory)
    r = _post(c, [_contact("C1:ABPerson", "Bob", "Example", org=True, email=True, birthday=True),
                  _contact("C2:ABPerson", "Nobody", "Known", org=True)])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["contacts"], body["matched"], body["people"], body["unmatched"], body["sourcesAdded"]) == (2, 1, 1, 1, 3)
    assert _people(memory) == before, "never a page per contact"
    sources = fact_sources.list_sources(memory, "bob-example")
    assert [(s["ref"], s["kind"], s["predicate"], s["added_by"]) for s in sources] == [
        ("addressbook://C1:ABPerson", "app", "works-at", "cicada"),
        ("addressbook://C1:ABPerson", "app", "email", "cicada"),
        ("addressbook://C1:ABPerson", "app", "birthday", "cicada"),
    ]
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True,
                         check=True).stdout
    assert log.startswith("Contacts sync") and "capture/contacts" in log and "Cicada-Author: user" in log
    assert "Nobody" not in (memory / "entities" / "bob-example.md").read_text(encoding="utf-8")


def test_matching_is_the_full_name_or_an_alias_folded_and_never_one_name_part(client):
    c, memory = client
    body = _post(c, [_contact("C3", "Carol", "Example", phone=True),        # an alias
                     _contact("C4", "Example", "Bob", email=True),          # family-first order
                     _contact("C5", "Bob", "", email=True)]).json()          # one name part: never
    assert (body["matched"], body["unmatched"]) == (2, 1)
    assert [s["predicate"] for s in fact_sources.list_sources(memory, "carol-example")] == ["phone"]
    assert [s["ref"] for s in fact_sources.list_sources(memory, "bob-example")] == ["addressbook://C4"]


def test_an_ambiguous_match_is_counted_and_skipped(client):
    c, memory = client
    body = _post(c, [_contact("C6", "Dana", "Twin", email=True),                 # two pages share the name
                     _contact("C7", "Bob", "Example", email=True),
                     _contact("C8", "Bob", "Example", phone=True)]).json()      # two contacts, one page
    assert (body["matched"], body["ambiguous"]) == (0, 3)
    assert fact_sources.list_sources(memory, "dana-one") == []
    assert fact_sources.list_sources(memory, "bob-example") == []


def test_the_same_address_book_again_changes_nothing_and_commits_nothing(client):
    c, memory = client
    _post(c, [_contact("C1", "Bob", "Example", org=True)])
    head = subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    body = _post(c, [_contact("C1", "Bob", "Example", org=True)]).json()
    assert (body["sourcesAdded"], body["sourcesRemoved"]) == (0, 0)
    assert subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True, text=True).stdout == head


def test_a_removed_fact_or_contact_removes_only_cicadas_own_entries(client):
    c, memory = client
    fact_sources.add_source(memory, "bob-example", "https://example.com/bob", predicate="works-at")   # the person's
    _post(c, [_contact("C1", "Bob", "Example", org=True, email=True)])
    assert _post(c, [_contact("C1", "Bob", "Example", org=True)]).json()["sourcesRemoved"] == 1
    assert _post(c, [_contact("C9", "Someone", "Else")]).json()["sourcesRemoved"] == 1
    assert [(s["ref"], s.get("added_by")) for s in fact_sources.list_sources(memory, "bob-example")] == [
        ("https://example.com/bob", "user")]


def _photos_on_disk(memory):
    """Every cached thumbnail of `bob-example`, whichever ext — asked through the one path function (R-SR9)."""
    paths = [contacts_local.photo_path(memory.name, "bob-example", ext) for ext in contacts_local.PHOTO_EXTS]
    return [p for p in paths if p is not None and p.exists()]


def test_a_photo_is_cached_outside_the_bank_at_the_path_t_people_reads(client, tmp_path):
    c, memory = client
    assert _post(c, [_contact("C1", "Bob", "Example", photo=JPEG)]).json()["photos"] == 1
    mark = _page(memory, "bob-example").frontmatter["contacts_photo"]
    assert set(mark) == {"sha", "ext"} and mark["ext"] == "jpg" and len(mark["sha"]) == 12
    path = contacts_local.photo_path(memory.name, "bob-example", mark["ext"])
    assert path == (tmp_path / "home" / "pictures" / memory.name / "contacts" / "bob-example.jpg").resolve(), (
        "exactly R-SR9's path — the one T-People's picture ladder reads with the page's ext")
    assert path.read_bytes() == JPEG
    assert not list(memory.rglob("*.jpg")), "never inside a bank (R-SR9)"
    _post(c, [_contact("C1", "Bob", "Example", photo=PNG)])
    assert _page(memory, "bob-example").frontmatter["contacts_photo"]["ext"] == "png"
    assert _photos_on_disk(memory) == [contacts_local.photo_path(memory.name, "bob-example", "png")], "the jpg went"
    _post(c, [_contact("C1", "Bob", "Example")])
    assert _photos_on_disk(memory) == []
    assert "contacts_photo" not in _page(memory, "bob-example").frontmatter


@pytest.mark.parametrize("photo", [b"GIF89a" + b"\x00" * 60, JPEG + b"\x00" * (70 * 1024)])
def test_a_photo_that_is_not_a_small_jpeg_or_png_is_ignored(client, photo):
    c, memory = client
    assert _post(c, [_contact("C1", "Bob", "Example", photo=photo)]).json()["photos"] == 0
    assert _photos_on_disk(memory) == []
    assert "contacts_photo" not in _page(memory, "bob-example").frontmatter


def test_the_photo_path_is_exactly_the_one_t_people_reads(tmp_path, monkeypatch):
    """R-SR9 as amended (the phase-A contract): `$CICADA_HOME/pictures/<bank>/contacts/<id>.<ext>`, jpg or png, None
    read as jpg, anything else or an id that would leave the folder None — the answers T-People's
    `entity_picture.contacts_path` gives — and a read never creates a folder."""
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    base = (tmp_path / "home" / "pictures" / "alpha" / "contacts").resolve()
    assert contacts_local.photo_path("alpha", "bob-example", "jpg") == base / "bob-example.jpg"
    assert contacts_local.photo_path("alpha", "bob-example", "png") == base / "bob-example.png"
    assert contacts_local.photo_path("alpha", "bob-example", None) == base / "bob-example.jpg"
    assert contacts_local.photo_path("alpha", "bob-example", "gif") is None
    assert contacts_local.photo_path("alpha", "../bob-example", "jpg") is None
    assert not (tmp_path / "home" / "pictures").exists()


def test_contacts_waits_while_sleep_is_tidying(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: type("S", (), {"status": "running"})())
    r = _post(c, [_contact("C1", "Bob", "Example", org=True)])
    assert r.status_code == 409 and r.json()["detail"] == contacts_local.SLEEP_REFUSAL
    assert fact_sources.list_sources(memory, "bob-example") == []


def test_a_demo_bank_is_refused_and_too_many_contacts_is_too_many(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(contacts_local, "MAX_CONTACTS", 1)
    assert _post(c, [_contact("C1", "Bob", "Example"), _contact("C2", "Carol", "Example")]).status_code == 413
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert _post(c, [_contact("C1", "Bob", "Example", org=True)]).status_code == 409
    assert fact_sources.list_sources(memory, "bob-example") == []


def test_the_channel_is_offered_before_the_first_sync_and_counts_after(client):
    c, _ = client

    def row():
        return next(ch for ch in c.get("/sources/channels").json()["channels"] if ch["id"] == "contacts-local")

    assert (row()["label"], row()["connected"], row()["actions"]) == ("Contacts", False, ["sync", "manage"])
    _post(c, [_contact("C1", "Bob", "Example", org=True), _contact("C2", "Nobody", "Known")])
    assert (row()["connected"], row()["count"], row()["countNoun"], row()["parts"]) == (
        True, 2, "contact", [{"key": "people", "count": 1}])


def test_the_hint_says_a_contacts_card_in_words_and_keeps_the_ref():
    hint = fact_sources.voiced_hint({"ref": "addressbook://C1:ABPerson", "kind": "app", "added_by": "cicada"})
    assert hint == "Their card in your Contacts (addressbook://C1:ABPerson) is where to check this"


def test_the_always_listed_contacts_row_moves_the_channels_etag_shape():
    """R-SR19: PR #109 shipped `"r4-sources"`; the Contacts row joins the body with no bank file changing, so a client
    still holding PR #109's list must not 304 past it."""
    from api.services import channel_registry

    assert channel_registry.CHANNELS_SHAPE not in ("g142", "r4-sources")


def test_a_sync_keeps_the_persons_choices_and_every_sources_place(client):
    """Final review, finding 1: Cicada's entries are updated in place — the person's `accepted`/`access`/`only_me`
    survive, a source the person added later stays after them, and a second sync commits nothing."""
    c, memory = client
    _post(c, [_contact("C1", "Bob", "Example", org=True, email=True)])
    fact_sources.add_source(memory, "bob-example", "addressbook://C1", predicate="works-at", added_by="user",
                            accepted=True, access="signed_in")
    fact_sources.add_source(memory, "bob-example", "https://example.com/bob", predicate="role")
    before = fact_sources.list_sources(memory, "bob-example")
    subprocess.run(["git", "-C", str(memory), "commit", "-qam", "person"], check=True, capture_output=True)
    head = subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    body = _post(c, [_contact("C1", "Bob", "Example", org=True, email=True)]).json()
    assert (body["sourcesAdded"], body["sourcesRemoved"]) == (0, 0)
    after = fact_sources.list_sources(memory, "bob-example")
    assert after == before
    assert after[0].get("accepted") is True and after[0].get("access") == "signed_in"
    assert subprocess.run(["git", "-C", str(memory), "rev-parse", "HEAD"], capture_output=True, text=True).stdout == head
    # A dropped fact leaves the person's source at the same index it had.
    _post(c, [_contact("C1", "Bob", "Example", email=True)])
    assert [s["ref"] for s in fact_sources.list_sources(memory, "bob-example")] == [
        "addressbook://C1", "https://example.com/bob"]


def test_an_entry_the_person_removes_is_never_put_back(client):
    """Final review, finding 1: removing a Contacts entry on the card is remembered in `_contacts_rejected.yaml`,
    committed with the removal, and the next sync skips exactly that (page, ref, predicate)."""
    c, memory = client
    _post(c, [_contact("C1", "Bob", "Example", org=True, email=True)])
    r = c.delete("/entities/bob-example/sources/0")
    assert r.status_code == 200, r.text
    assert (memory / contacts_local.REFUSED_FILE).exists()
    status = subprocess.run(["git", "-C", str(memory), "status", "--porcelain"], capture_output=True, text=True).stdout
    assert contacts_local.REFUSED_FILE not in status, "committed with the removal"
    body = _post(c, [_contact("C1", "Bob", "Example", org=True, email=True)]).json()
    assert body["sourcesAdded"] == 0
    assert [s["predicate"] for s in fact_sources.list_sources(memory, "bob-example")] == ["email"]
    # A person's own source is theirs to remove and is never recorded.
    fact_sources.add_source(memory, "bob-example", "https://example.com/bob", predicate="role")
    assert contacts_local.remember_removal(memory, "bob-example", {"ref": "https://example.com/bob"}) is None
