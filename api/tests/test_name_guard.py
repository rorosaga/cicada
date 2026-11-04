"""What may leave in a web search or an opened link (ruling 54, owner correction 2026-11-04): never a name known only from
the person's own record; reading it is fine. Synthetic banks only; nothing reaches a network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import markdown_parser, name_guard, people_directory, web_settle


def _page(memory: Path, eid: str, name: str, body: str = "## Summary\nA page.\n", **fm) -> None:
    meta = {"name": name, "type": "person", "status": "active", "confidence": 0.7, "created": "2026-10-21",
            "last_referenced": "2026-10-21", "source_episodes": [], "related": [], "version": 1}
    meta.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", meta, body)


def _episode(memory: Path, eid: str, body: str, source: str, **fm) -> None:
    meta = {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00", "processed": True, "title": "item", "source": source}
    meta.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", meta, body)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    _page(m, "dana-rivers", "Dana Rivers", owner=True)
    _episode(m, "ep_2026-10-21_001", "attachment [video]: Bea Example on agent workflows, with Omar Public", "video-watch")
    return m


def _guard(memory: Path) -> name_guard.NameGuard:
    return name_guard.build(memory, web_settle.bank_facts(memory))


def _store(memory: Path, name: str, payload: dict) -> None:
    path = people_directory.path(memory.name, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# --------------------------------------------------------------------------- a mention, against the public record


def test_a_name_also_public_is_not_blocked_because_a_chat_mentioned_it(bank):
    _episode(bank, "ep_2026-10-22_001", "user: did you see what Bea Example said?", "whatsapp")
    guard = _guard(bank)
    assert guard.clears("Bea Example") is None
    assert guard.check("Bea Example blog") is None


def test_a_name_only_a_chat_says_is_blocked_in_any_order_and_any_case(bank):
    _episode(bank, "ep_2026-10-22_001", "user: Nora Hidden is coming tonight", "whatsapp")
    guard = _guard(bank)
    assert guard.clears("Nora Hidden") == "not_public"
    for query in ("Nora Hidden", "nora hidden github", "Hidden Nora", "NÓRA HÍDDEN blog", "nora"):
        assert guard.check(query) == "private_only", query


def test_a_public_first_name_does_not_carry_a_private_full_name_past_it(bank):
    _episode(bank, "ep_2026-10-22_001", "user: Bea Smith called", "imessage")
    guard = _guard(bank)
    assert guard.check("Bea Smith") == "private_only"     # "bea" alone is public; the pair and "smith" are not


def test_the_persons_own_note_on_a_saved_link_is_not_public_content(bank):
    _episode(bank, "ep_2026-10-23_001", "user: Nora Hidden sent me this https://example.org/post\nattachment [page]: a post",
             "bookmark")
    assert _guard(bank).check("Nora Hidden") == "private_only"


@pytest.mark.parametrize("source", ["imessage", "whatsapp", "telegram-chats", "telegram", "email", "folder", "wispr-flow",
                                    "calendar-local", "apple-notes", "claude-code", "a-new-writer-nobody-knows"])
def test_every_source_that_is_not_public_content_counts_as_private(bank, source):
    _episode(bank, "ep_2026-10-22_001", "user: Nora Hidden is coming", source)
    assert _guard(bank).check("Nora Hidden") == "private_only"


def test_a_handle_said_in_a_chat_is_private_and_a_link_to_a_post_is_the_post(bank):
    _episode(bank, "ep_2026-10-22_001", "user: https://x.com/postauthor/status/123 lol", "telegram-chats")
    _episode(bank, "ep_2026-10-22_002", "user: my friend norah99 will come", "telegram-chats")
    _episode(bank, "ep_2026-10-22_003", "user: https://www.instagram.com/igfriend", "whatsapp")
    guard = _guard(bank)
    assert guard.check("postauthor") is None
    assert guard.check("norah99") == "private_only"
    assert guard.check("igfriend") == "private_only"      # a bare profile link is that handle said


# --------------------------------------------------------------------------- a tie, always


def test_public_content_never_clears_a_chat_correspondent(bank):
    _episode(bank, "ep_2026-10-22_001", "user: hola", "imessage", title="Messages with Bea Example",
             correspondent={"name": "Bea Example", "kind": "person"})
    guard = _guard(bank)
    assert guard.clears("Bea Example") == "tie" and guard.clears("Example Bea") == "tie"
    assert guard.check("Bea Example") == "tie"


@pytest.mark.parametrize("writer", ["imessage", "whatsapp", "telegram-chats"])
def test_a_group_member_and_a_speaker_label_are_ties(bank, writer):
    _episode(bank, "ep_2026-10-22_001", "speaker:Omar Public: hola", writer,
             participants=[{"key": "k1", "marker": "speaker:Ana", "name": "Ana Member", "kind": "person"}])
    guard = _guard(bank)
    assert guard.clears("Ana Member") == "tie"
    assert guard.clears("Omar Public") == "tie"           # said in a video too; still someone in a group chat


def test_a_waiting_contacts_card_is_a_tie_with_either_word_order_and_its_first_name_alone(bank):
    _store(bank, name_guard.WAITING_FILE, {"cards": [{"id": "c1", "given_name": "Bea", "family_name": "Example"}]})
    guard = _guard(bank)
    assert guard.clears("Bea Example") == "tie" and guard.clears("Example Bea") == "tie"
    assert guard.check("Bea") == "tie" and guard.check("Bea github") == "tie"


def test_a_one_part_name_in_the_contacts_book_guards_a_full_name_holding_it(bank):
    """The store open draft #602 adds, read by its layout: `contacts-book/<scope>/book.json`."""
    book = people_directory.path(bank.name, name_guard.CONTACTS_BOOK_DIR) / "here"
    book.mkdir(parents=True)
    (book / name_guard.BOOK_FILE).write_text(json.dumps({"cards": [{"key": "a" * 16, "given": "Bea", "family": ""}]}))
    assert _guard(bank).clears("Bea Example") == "tie"


def test_two_full_names_sharing_a_first_name_are_two_people(bank):
    _store(bank, name_guard.WAITING_FILE, {"cards": [{"id": "c1", "given_name": "Bea", "family_name": "Other"}]})
    guard = _guard(bank)
    assert guard.clears("Bea Example") is None
    assert guard.check("Bea Example blog", allowed=("Bea Example",)) is None   # cleared, so the card's "bea" is not asked
    assert guard.check("Bea blog", allowed=("Bea Example",)) == "tie"          # the first name alone still is


def test_a_linkedin_connection_and_its_slug_are_ties(bank):
    _store(bank, name_guard.LINKEDIN_FILE, {"connections": [{"id": "1", "first": "Bea", "last": "Example",
                                                             "url": "https://www.linkedin.com/in/bea-slug"}]})
    guard = _guard(bank)
    assert guard.clears("Bea Example") == "tie"
    assert guard.check("bea-slug") == "tie"


def test_a_page_carrying_a_card_or_an_import_is_a_tie(bank):
    _page(bank, "omar", "Omar Public", sources=[{"ref": "addressbook://card-1", "kind": "app", "predicate": "phone"}])
    assert _guard(bank).clears("Omar Public") == "tie"


def test_the_owners_own_name_never_leaves(bank):
    assert _guard(bank).check("Dana Rivers") == "tie"


def test_a_person_page_the_public_record_never_says_is_a_tie(bank):
    _page(bank, "nora", "Nora Hidden")
    assert _guard(bank).check("Nora Hidden blog") == "tie"


@pytest.mark.parametrize("query", ["N o r a H i d d e n", "norahidden", "hiddennora"])
def test_respelling_a_tie_is_still_the_tie(bank, query):
    _page(bank, "nora", "Nora Hidden")
    assert _guard(bank).check(query) == "tie"


@pytest.mark.parametrize("query, reason", [
    ("reach me at nora@example.org", "contact_detail"), ("call +1 415 555 0100", "contact_detail"),
    ("a " * 20, "shape"), ("x" * 200, "shape"), ("Tm9yYSBIaWRkZW4gaXMgYSBmcmllbmQgb2YgbWluZQ==abcdef", "shape"),
])
def test_contact_details_and_odd_shapes_never_leave(bank, query, reason):
    assert _guard(bank).check(query) == reason


# --------------------------------------------------------------------------- a link carries words too


def test_a_link_with_a_guarded_name_in_its_path_or_query_is_blocked(bank):
    _page(bank, "nora", "Nora Hidden")
    guard = _guard(bank)
    assert guard.check_url("https://example.org/people/nora-hidden") == "tie"
    assert guard.check_url("https://example.org/find?who=Nora%20Hidden") == "tie"
    assert guard.check_url("https://norahidden.example.org/") == "tie"
    assert guard.check_url("https://example.org/people/some-public-page/12345678") is None


# --------------------------------------------------------------------------- fails closed, for what leaves


@pytest.mark.parametrize("store", [name_guard.WAITING_FILE, name_guard.LINKEDIN_FILE])
def test_a_store_that_cannot_be_read_fails_closed(bank, store):
    path = people_directory.path(bank.name, store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(name_guard.GuardUnreadable):
        _guard(bank)


def test_a_contacts_book_that_cannot_be_read_fails_closed(bank):
    book = people_directory.path(bank.name, name_guard.CONTACTS_BOOK_DIR) / "here"
    book.mkdir(parents=True)
    (book / name_guard.BOOK_FILE).write_text("nope", encoding="utf-8")
    with pytest.raises(name_guard.GuardUnreadable):
        _guard(bank)


def test_an_episode_that_cannot_be_read_fails_closed(bank, monkeypatch):
    real = markdown_parser.parse

    def broken(path, *a, **kw):
        if "episodes" in str(path):
            raise OSError("no")
        return real(path, *a, **kw)
    monkeypatch.setattr(markdown_parser, "parse", broken)
    with pytest.raises(name_guard.GuardUnreadable):
        _guard(bank)


def test_a_corpus_too_large_to_hold_fails_closed(bank, monkeypatch):
    monkeypatch.setattr(name_guard, "MAX_CORPUS_CHARS", 3)
    with pytest.raises(name_guard.GuardUnreadable):
        _guard(bank)


def test_a_store_that_is_not_there_is_empty_and_the_guard_rereads_a_change(bank):
    facts = web_settle.bank_facts(bank)
    guard = name_guard.guard_for(bank, facts)
    assert name_guard.guard_for(bank, facts) is guard
    _episode(bank, "ep_2026-10-22_001", "user: Nora Hidden came", "whatsapp")
    assert name_guard.guard_for(bank, facts).check("Nora Hidden") == "private_only"
    name_guard.release()
    assert name_guard._HELD == {}
