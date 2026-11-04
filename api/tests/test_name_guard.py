"""What may leave in a web search or an opened link (ruling 54, owner correction 2026-11-04): never a name known only from
the person's own record; reading it is fine. Synthetic banks only; nothing reaches a network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import bank_index, markdown_parser, media_ingestor, name_guard, people_directory, web_settle


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
    _episode(m, "ep_2026-10-21_001", "assistant: A talk.\nvideo [0:10]: Bea Example on agent workflows, with Omar Public",
             "video-watch")
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


def _saved(title="A post", url="https://example.org/post", description="", **kw) -> str:
    meta = media_ingestor.MediaMeta(title=title, description=description, media_type="url")
    return media_ingestor._episode_body(meta, url, "2026-10-21", kw.pop("note", None), **kw)


@pytest.mark.parametrize("kw", [
    {"note": "Nora Hidden sent me this"},                    # ## User note
    {"note": "Nora Hidden sent me this", "note_by_agent": True},   # ## Note
    {"reason": "Nora Hidden told me to read it"},            # ## Saved because
    {"folder": "Nora Hidden"},                               # **Folder:**
])
def test_the_persons_own_words_on_a_real_save_are_not_public_content(bank, kw):
    _episode(bank, "ep_2026-10-23_001", _saved(description="A post about agents.", **kw), "url")
    guard = _guard(bank)
    assert guard.clears("Nora Hidden") == "not_public"
    assert guard.check("Nora Hidden") == "private_only"


def test_a_note_cannot_pose_as_a_description(bank):
    body = _saved(description="A post about agents.", note="## Description\nNora Hidden is great")
    _episode(bank, "ep_2026-10-23_001", body, "url")
    assert _guard(bank).clears("Nora Hidden") == "not_public"


def test_a_note_episode_has_no_public_words(bank):
    body = "# Note on A post\n\n**URL:** https://example.org/post\n\n## Note\nNora Hidden sent me this"
    _episode(bank, "ep_2026-10-23_001", body, "url", title="Note on A post")
    assert name_guard.public_part({"source": "url", "title": "Note on A post"}, body)[0].strip() == ""
    assert _guard(bank).check("Nora Hidden") == "private_only"


def test_a_saved_item_says_its_description_its_channel_and_a_posts_handle(bank):
    body = _saved(title="Cal Public on agents", url="https://x.com/calpub/status/1", description="Dee Public wrote this.")
    said, _own = name_guard.public_part({"source": "url"}, body)
    for words in ("Cal Public", "Dee Public", "calpub"):
        assert words in said, words


def test_a_title_the_page_never_confirmed_stays_private(bank):
    said, own = name_guard.public_part({"source": "bookmark"}, _saved(title="Nora Hidden resume"))
    assert said.strip() == "" and "Nora Hidden" in own


def test_a_saved_bare_profile_says_nothing_about_who_it_is(bank):
    said, _own = name_guard.public_part({"source": "url"}, _saved(title="x", url="https://www.linkedin.com/in/nora-hidden"))
    assert "nora" not in said.lower()


def test_each_writer_with_public_words_says_only_those(bank):
    """Real shapes: an agent's page read and watch keep the quotes, not its summary; a day of rows keeps its rows."""
    read = "assistant: Nora Hidden liked it.\n\nattachment [example.org]: as claude-code read it\n> Cal Public wrote it"
    said, own = name_guard.public_part({"source": "page-read"}, read)
    assert "Cal Public" in said and "Nora" not in said and "Nora Hidden" in own
    walled = read.replace("[example.org]", "[www.linkedin.com]")
    assert name_guard.public_part({"source": "page-read"}, walled)[0] == ""
    watch = "assistant: Nora Hidden liked it.\nvideo [0:10]: Cal Public on agents"
    said, own = name_guard.public_part({"source": "video-watch"}, watch)
    assert "Cal Public" in said and "Nora" not in said and "Nora Hidden" in own
    day = "# Watched on YouTube\n\n- 10:00 · A talk — Cal Public · https://www.youtube.com/watch?v=nora"
    for source in ("watch-history", "watch-history-month", "listening-history"):
        said, own = name_guard.public_part({"source": source}, day)
        assert "Cal Public" in said and "nora" not in said and own == ""
    assert "Cal Public" in name_guard.public_part({"source": "reading-history", "origin": "substack-history"}, day)[0]
    assert name_guard.public_part({"source": "reading-history", "origin": "traces"}, day)[0] == ""


@pytest.mark.parametrize("source, fm", [
    ("github", {"origin": "github-owned"}), ("github", {"origin": "github-starred"}),
    ("repository", {"origin": "github-owned"}), ("repository", {"origin": "github-starred"}),
    ("tab-group", {}), ("linkedin", {}), ("instagram", {}), ("a-new-writer", {}), ("", {}),
])
def test_everything_not_named_as_public_is_private(source, fm):
    body = "# t\n\nCal Public\n\n**Visibility:** private"
    assert name_guard.public_part({"source": source, **fm}, body)[0].strip() == ""


def test_a_starred_public_repository_is_public_and_a_private_one_is_not():
    body = "# cal/tool\n\n**URL:** https://github.com/cal/tool\n\n## Description\nBy Cal Public."
    fm = {"source": "repository", "origin": "github-starred", "media_entity_id": "tool"}
    assert "Cal Public" in name_guard.public_part(fm, body, {"tool": {"github": {"private": False}}})[0]
    assert name_guard.public_part(fm, body, {"tool": {"github": {"private": True}}})[0] == ""
    assert name_guard.public_part(fm, body, {"tool": {}})[0] == ""


def test_every_writer_the_guard_names_is_a_source_a_writer_really_stamps():
    from api.services import history_index, page_read, watch_history, watch_record

    assert {"url", "bookmark", "youtube", "video"} <= {media_ingestor._classify("https://example.org/"),
                                                       media_ingestor._classify("https://example.org/", True),
                                                       media_ingestor._classify("https://youtu.be/x"),
                                                       media_ingestor._classify("https://example.org/a.mp4")}
    assert {page_read.SOURCE, watch_record.SOURCE, watch_history.SOURCE, history_index.MONTH_SOURCE,
            history_index.LISTENING_SOURCE, history_index.READING_SOURCE} <= set(name_guard.WRITERS)


# --------------------------------------------------------------------------- spellings of a mention and a tie


@pytest.mark.parametrize("query", ["Maria Garcia", "Garcia Maria", "Garcia, Maria", "Maria J. Garcia", "mariagarcia",
                                   "garciamaria", "maria_garcia", "maria-garcia", "M. Garcia", "MARÍA GARCÍA"])
def test_a_mention_only_a_chat_says_is_blocked_however_it_is_written(bank, query):
    _episode(bank, "ep_2026-10-22_001", "user: Maria Garcia is coming tonight", "whatsapp")
    _episode(bank, "ep_2026-10-22_002", "video [0:01]: Maria spoke, and later Garcia did", "video-watch")
    assert _guard(bank).check(query) is not None, query


def test_each_word_public_alone_is_no_clearance_for_the_pair_but_each_alone_still_passes(bank):
    _episode(bank, "ep_2026-10-22_001", "user: Maria Garcia is coming tonight", "whatsapp")
    _episode(bank, "ep_2026-10-22_002", "video [0:01]: Maria spoke, and later Garcia did", "video-watch")
    guard = _guard(bank)
    assert guard.check("Maria") is None and guard.check("Garcia") is None


@pytest.mark.parametrize("query", ["Søren Bjørk", "Soren Bjork", "Bjork", "SOREN", "Bjørk Søren", "sorenbjork", "bjorksoren",
                                   "S o r e n B j o r k"])
def test_a_card_is_a_tie_through_full_transliteration(bank, query):
    _store(bank, name_guard.WAITING_FILE, {"cards": [{"id": "c1", "given_name": "Søren", "family_name": "Bjørk"}]})
    assert _guard(bank).check(query) == "tie", query


@pytest.mark.parametrize("a, b", [("Łukasz", "Lukasz"), ("Straße", "Strasse"), ("Æsa", "Aesa"), ("Đorđe", "Dorde"),
                                  ("Þór", "Thor"), ("José", "Jose"), ("ﬁona", "fiona")])
def test_letters_that_do_not_decompose_fold_too(a, b):
    assert name_guard.words(a) == name_guard.words(b)


def test_a_look_alike_letter_is_a_respelling():
    guard = name_guard.NameGuard()
    assert guard.check("N\u043era Hidden") == "shape"      # a Cyrillic "o"


def test_a_year_in_a_chats_title_blocks_nothing_and_a_title_is_no_tie(bank):
    _episode(bank, "ep_2026-10-22_001", "user: hi", "whatsapp", title="Python devs 2026",
             correspondent={"name": "Cal 2026", "kind": "person"})
    guard = _guard(bank)
    assert "2026" not in guard.tie_words and "python" not in guard.tie_words
    assert guard.check("bex42 talk 2026") is None


def test_an_owners_project_blocks_as_a_phrase_and_its_words_do_not(bank):
    _page(bank, "alpha-project", "Agent Memory Lab", type="project")
    guard = _guard(bank)
    assert guard.check("Agent Memory Lab") == "tie" and guard.check("lab") is None


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
    bank_index.invalidate(bank)
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


def test_an_episode_that_cannot_be_read_fails_closed(bank):
    (bank / "episodes" / "ep_2026-10-23_009.md").write_bytes(b"---\nid: [unclosed\n---\nbody \xff\xfe")
    bank_index.invalidate(bank)
    with pytest.raises(name_guard.GuardUnreadable):
        _guard(bank)


@pytest.mark.parametrize("store", [name_guard.WAITING_FILE, name_guard.LINKEDIN_FILE])
def test_a_store_not_in_utf8_fails_closed_and_never_ends_the_step(bank, store):
    path = people_directory.path(bank.name, store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe{}")
    with pytest.raises(name_guard.GuardUnreadable):
        _guard(bank)


@pytest.mark.parametrize("store, body", [
    (name_guard.WAITING_FILE, {"cards": "nope"}), (name_guard.WAITING_FILE, {}),
    (name_guard.WAITING_FILE, {"cards": ["a string"]}), (name_guard.LINKEDIN_FILE, {"connections": {"a": 1}}),
    (name_guard.LINKEDIN_FILE, {"rows": []}),
])
def test_a_store_with_an_unexpected_shape_fails_closed(bank, store, body):
    _store(bank, store, body)
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
