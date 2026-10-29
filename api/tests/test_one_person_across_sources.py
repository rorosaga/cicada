"""One person, one page across every source (owner 2026-10-28; `contact_identity`). Synthetic people only.

A chat participant reaches their page through the ONE address-book card the app found for their handle — the card's
Contacts id, never a handle; a name-only mention elsewhere joins only through the name rules, and a one-word name is
asked about across sources, never joined on the first name alone."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from _imessage_fixtures import apple_ns, utc
from api.models.schemas import MessagesSyncRequest
from api.services import (bank_index, contact_identity, contacts_local, entity_resolver as er, inbox_wording,
                          markdown_parser, messages_source, sleep_cycle)

ONE = "1" * 24
GROUP = "2" * 24
A, B = "a1" * 8, "b2" * 8


def _settings(bank):
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model", litellm_disambiguation_model="",
                           sleep_promotion_threshold=2, sleep_resolve_concurrency=1)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "bank"
    for name in ("entities", "episodes", "inbox"):
        (memory / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)

    async def different(*_a, **_k):
        return "different"

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return ["different" for _ in entries]

    monkeypatch.setattr(er, "_llm_judge_same_entity", different)
    monkeypatch.setattr(er, "_llm_judge_batch", batch)
    bank_index.invalidate()
    yield memory
    bank_index.invalidate()


def _row(n, minute, text, *, me=False, sender=None):
    row = {"rowid": n, "guid": f"G-{n:04d}", "date": apple_ns(utc(2026, 9, 5, 10, minute)), "isFromMe": me,
           "text": text, "associatedMessageType": 0}
    if sender and not me:
        row["sender"] = sender
    return row


def _sync(memory, cid, rows, **conversation):
    body = MessagesSyncRequest.model_validate({"conversation": {"id": cid, "service": "iMessage", **conversation},
                                               "messages": rows})
    out = messages_source.ingest(memory, body.model_dump(by_alias=False))
    bank_index.invalidate()
    return out


def _episodes(memory):
    return [markdown_parser.parse(p) for p in sorted((memory / "episodes").glob("*.md"))]


def _page(memory, pid, name, *, card=None, owner=False, episodes=()):
    fm = {"name": name, "type": "person", "status": "active", "confidence": 0.8,
          "source_episodes": list(episodes)}
    if card:
        fm["sources"] = [{"ref": contact_identity.ref(card), "kind": "app", "predicate": "phone", "added_by": "cicada"}]
    if owner:
        fm["owner"] = True
    markdown_parser.write(memory / "entities" / f"{pid}.md", fm, f"## Summary\n{name}.\n")
    bank_index.invalidate()
    return {"id": pid, "frontmatter": fm}


def _mention(name, *, episode="ep_2026-09-05_001", card=None, named=False, origin="imessage", **extra):
    entity = {"name": name, "type": "person", "confidence": 0.6, "description": f"{name} came up.",
              "source_episode": episode, "source_episode_timestamp": "2026-09-05T10:00:00Z", "origin": origin,
              "named_by_person": named, **extra}
    if card:
        entity[contact_identity.MARK] = card
    return [{"episode_id": episode, "relationships": [], "entities": [entity]}]


def _resolve(memory, extracted, pages=()):
    return asyncio.run(er.resolve(extracted, list(pages), _settings(memory)))


# --- the card id is kept on the sitting's own records, never a handle -------------------------------------------------


def test_a_texted_persons_card_rides_on_the_correspondent_record_and_stays(bank):
    messages_source.update_settings(bank, conversation={"id": ONE, "name": "Robert Example", "ticked": True,
                                                        "actor": {"kind": "person"}})
    _sync(bank, ONE, [_row(1, 0, "lunch tomorrow?")], name="Robert Example", contact="ABCD-1234:ABPerson")
    (ep,) = _episodes(bank)
    assert ep.frontmatter["correspondent"]["contact"] == "ABCD-1234:ABPerson"
    # A later pass that names no card keeps the one recorded.
    _sync(bank, ONE, [_row(2, 5, "sure")], name="Robert Example")
    (ep,) = _episodes(bank)
    assert ep.frontmatter["correspondent"]["contact"] == "ABCD-1234:ABPerson"


def test_the_chats_shared_photo_lands_on_the_cards_page(bank):
    from test_messages_photos import b64, png

    from api.services import messages_photos

    messages_source.update_settings(bank, conversation={"id": ONE, "name": "Rob", "ticked": True,
                                                        "actor": {"kind": "person"}})
    _sync(bank, ONE, [_row(1, 0, "lunch?")], name="Rob", contact="CARD-R")
    _page(bank, "rob", "Rob")                                     # a same-name page of someone else
    _page(bank, "robert-example", "Robert Example", card="CARD-R")
    messages_photos.store(bank, [{"conversation": ONE, "photo_b64": b64(png())}])
    assert set(messages_photos.links(bank)) == {"robert-example"}


@pytest.mark.parametrize("raw",["+1 555 000 0001", "bob@example.com", "x" * 201, "a b"])
def test_a_handle_is_never_kept_as_a_card(raw):
    assert contact_identity.clean_card_id(raw) is None


def test_each_group_member_keeps_their_own_card_and_an_agent_none(bank):
    direct = "e" * 24
    messages_source.update_settings(bank, conversation={"id": direct, "ticked": True, "actor": {"kind": "agent"}})
    messages_source.update_settings(bank, conversation={"id": GROUP, "ticked": True})
    members = [{"key": A, "name": "Alice Example", "contact": "CARD-A"},
               {"key": B, "name": "Helper Bot", "direct": direct, "contact": "CARD-B"}]
    _sync(bank, GROUP, [_row(1, 0, "hi", sender=A), _row(2, 1, "hello", sender=B)], group=True, members=members)
    (ep,) = _episodes(bank)
    by_key = {p["key"]: p for p in ep.frontmatter["participants"]}
    assert by_key[A]["contact"] == "CARD-A"
    assert "contact" not in by_key[B] and by_key[B]["marker"] == "assistant"


# --- Stage 1 marks the participant ----------------------------------------------------------------------------------


def test_stage_one_marks_only_a_person_naming_exactly_one_participant_with_a_card():
    episode = {"group": True, "participants": [
        {"marker": "speaker:alice-example", "name": "Alice Example", "kind": "person", "contact": "CARD-A"},
        {"marker": "speaker:bob-example", "name": "Bob Example", "kind": "person"},
        {"marker": "assistant", "name": "Helper Bot", "kind": "agent", "contact": "CARD-X"}]}
    result = {"entities": [
        {"name": "Alice", "aliases": ["Alice Example"], "type": "person"},
        {"name": "Bob Example", "type": "person"},                       # no card
        {"name": "Helper Bot", "type": "person"},                        # an agent: never a card
        {"name": "Alice Example", "type": "project"},                    # not a person
        {"name": "Zed", "type": "person", contact_identity.MARK: "MODEL-SET"}]}   # the model may never set it
    assert contact_identity.mark(result, episode) == 1
    alice, bob, bot, project, zed = result["entities"]
    assert alice[contact_identity.MARK] == "CARD-A"
    assert all(contact_identity.MARK not in e for e in (bob, bot, project, zed))


# --- Stage 2 reads the card before any name -------------------------------------------------------------------------


def test_a_participant_spelled_differently_lands_on_their_cards_page(bank):
    robert = _page(bank, "robert-example", "Robert Example", card="CARD-R")
    bobby = _page(bank, "bobby", "Bobby")                     # someone else, by name
    out = _resolve(bank, _mention("Bobby", card="CARD-R"), [robert, bobby])
    assert out["name_to_id"]["bobby"] == "robert-example"
    assert [c["id"] for c in out["changes"] if c["action"] == "update"] == ["robert-example"]


def test_a_texted_correspondent_lands_on_their_cards_page_not_a_new_one(bank):
    from api.services import correspondents

    robert = _page(bank, "robert-example", "Robert Example", card="CARD-R")
    extracted = _mention("Rob", card="CARD-R", **{correspondents.MARK: {"name": "Rob", "kind": "person"}})
    extracted[0][correspondents.MARK] = {"name": "Rob", "kind": "person"}
    out = _resolve(bank, extracted, [robert])
    assert out["name_to_id"].get("rob") == "robert-example"
    assert not [c for c in out["changes"] if c["action"] == "create"]


def test_the_owners_card_never_takes_a_participant(bank):
    owner = _page(bank, "pat-owner", "Pat Owner", card="CARD-ME", owner=True)
    out = _resolve(bank, _mention("Pat", card="CARD-ME"), [owner])
    assert out["name_to_id"].get("pat") != "pat-owner"


def test_a_waiting_card_is_used_only_once_the_usual_rules_promote(bank):
    contacts_local.save_waiting(bank.name, [{"id": "CARD-R", "given_name": "Robert", "family_name": "Example"}])
    # One sitting, nobody's own words: below the bar — the card is never a page by itself (owner 2026-10-20).
    out = _resolve(bank, _mention("Bobby", card="CARD-R"))
    assert not [c for c in out["changes"] if c["action"] == "create"]
    # Two sittings: the rule passes, and the page is born under the card's name, the chat's name kept as an alias.
    two = _mention("Bobby", card="CARD-R") + _mention("Bobby", card="CARD-R", episode="ep_2026-09-06_001")
    out = _resolve(bank, two)
    (create,) = [c for c in out["changes"] if c["action"] == "create"]
    assert create["entity"]["name"] == "Robert Example" and "Bobby" in create["entity"]["aliases"]
    assert create["contacts_card"]["id"] == "CARD-R"


# --- a name-only mention elsewhere is asked about, never joined -----------------------------------------------------


def _chat_and_session(bank):
    markdown_parser.write(bank / "episodes" / "ep_2026-09-05_001.md",
                          {"id": "ep_2026-09-05_001", "origin": "imessage", "source": "imessage", "group": True},
                          "speaker:alice-example: hi")
    markdown_parser.write(bank / "episodes" / "ep_2026-09-07_001.md",
                          {"id": "ep_2026-09-07_001", "origin": "claude-code", "harness": "claude-code"},
                          "user: ask Alice about the alpha-project review")
    bank_index.invalidate()


def test_a_first_name_heard_in_a_session_is_asked_about_in_human_words(bank):
    _chat_and_session(bank)
    alice = _page(bank, "alice-example", "Alice Example", episodes=["ep_2026-09-05_001"])
    out = _resolve(bank, _mention("Alice", episode="ep_2026-09-07_001", origin="claude-code"), [alice])
    assert out["name_to_id"].get("alice") != "alice-example"          # never joined on the first name
    items = [markdown_parser.parse(p).frontmatter for p in (bank / "inbox").glob("*.md")]
    (item,) = [i for i in items if i.get("kind") == "merge_suggestion"]
    assert item["heard_in"] == {"mention": "you talked to Claude about", "page": "in your group chat"}
    spoken = inbox_wording.spoken(item, "2026-09-08", page_fm=None, other_fm=alice["frontmatter"])
    assert spoken.question == "Is the Alice in your group chat the same Alice you talked to Claude about?"


@pytest.mark.parametrize("verdict", ["same", "unsure"])
def test_a_judge_that_would_join_on_the_first_name_asks_instead(bank, monkeypatch, verdict):
    _chat_and_session(bank)

    async def same(*_a, **_k):
        return verdict

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return [verdict for _ in entries]

    monkeypatch.setattr(er, "_llm_judge_same_entity", same)
    monkeypatch.setattr(er, "_llm_judge_batch", batch)
    alice = _page(bank, "alice-example", "Alice Example", episodes=["ep_2026-09-05_001"])
    out = _resolve(bank, _mention("Alice", episode="ep_2026-09-07_001", origin="claude-code"), [alice])
    assert out["name_to_id"].get("alice") != "alice-example"
    assert not [c for c in out["changes"] if c["action"] == "update" and c["id"] == "alice-example"]
    items = [markdown_parser.parse(p).frontmatter for p in (bank / "inbox").glob("*.md")]
    (item,) = [i for i in items if i.get("kind") == "merge_suggestion"]
    assert item["heard_in"]["page"] == "in your group chat"
    if verdict == "unsure":
        return
    # In a chat itself the judge's word stands: the guard is only across sources.
    _page(bank, "bea-example", "Bea Example", episodes=["ep_2026-09-05_001"])
    out = _resolve(bank, _mention("Bea", episode="ep_2026-09-05_001", origin="imessage"),
                   [_page(bank, "bea-example", "Bea Example", episodes=["ep_2026-09-05_001"])])
    assert out["name_to_id"].get("bea") == "bea-example"


def test_a_model_note_on_the_name_and_a_page_born_this_batch_still_ask(bank):
    """Seen on haiku (2026-10-29): the session's mention came back as "Alice (unnamed surname)", and the chat's page
    was being born in the same Sleep."""
    _chat_and_session(bank)
    extracted = (_mention("Alice Example", episode="ep_2026-09-05_001", named=True, confidence=0.9)
                 + _mention("Alice Example", episode="ep_2026-09-06_001", named=True, confidence=0.9)
                 + _mention("Alice (unnamed surname)", episode="ep_2026-09-07_001", origin="claude-code"))
    markdown_parser.write(bank / "episodes" / "ep_2026-09-06_001.md",
                          {"id": "ep_2026-09-06_001", "origin": "imessage", "source": "imessage", "group": True},
                          "speaker:alice-example: hi again")
    bank_index.invalidate()
    out = _resolve(bank, extracted)
    assert any(c["action"] == "create" and c["id"] == "alice-example" for c in out["changes"])
    items = [markdown_parser.parse(p).frontmatter for p in (bank / "inbox").glob("*.md")]
    (item,) = [i for i in items if i.get("kind") == "merge_suggestion"]
    spoken = inbox_wording.spoken(item, "2026-09-08", other_fm={"name": "Alice Example", "type": "person"})
    assert spoken.question == "Is the Alice in your group chat the same Alice you talked to Claude about?"


def test_a_first_name_in_the_same_kind_of_place_asks_nothing_new(bank):
    _chat_and_session(bank)
    # The page's person was never in a chat: no cross-source question.
    alice = _page(bank, "alice-example", "Alice Example", episodes=["ep_2026-09-07_001"])
    _resolve(bank, _mention("Alice", episode="ep_2026-09-07_001", origin="claude-code"), [alice])
    items = [markdown_parser.parse(p).frontmatter for p in (bank / "inbox").glob("*.md")]
    assert not [i for i in items if i.get("heard_in")]
    # Two full-name pages share the first name: nobody is asked about.
    _page(bank, "alice-other", "Alice Other", episodes=["ep_2026-09-05_001"])
    assert er._full_name_pages([alice, {"id": "alice-other", "frontmatter": {"type": "person", "name": "Alice Other"}}],
                               {}, None) == {}


def test_sleeps_episode_dict_carries_the_participants_cards(bank):
    messages_source.update_settings(bank, conversation={"id": GROUP, "ticked": True})
    _sync(bank, GROUP, [_row(1, 0, "hi", sender=A)], group=True,
          members=[{"key": A, "name": "Alice Example", "contact": "CARD-A"}])
    (episode,) = sleep_cycle._get_unprocessed_episodes(bank)
    assert contact_identity.participants(episode) == {"alice example": "CARD-A"}
