"""2026-11-03 — a chat source's page (owner: the synced chats "in the same order as the apps themselves", "right click →
pin a chat to the top", "a green dot for chats that are synced, and a last synced text", and the person's own chat
drawing the person's picture): the pin in each chat source's settings and its route, and what a chat row carries.

Every chat and page here is synthetic.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bank_index, channel_items, chat_live, messages_source, sync_service, telegram_source,
                          whatsapp_source)

CHAT_A = "a" * 32
CHAT_B = "b" * 32
SELF = "c" * 32


def _write(path, fm: dict, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", *(f"{k}: {json.dumps(v)}" for k, v in fm.items()), "---", "", body]
    path.write_text("\n".join(lines), encoding="utf-8")


def _sitting(bank, ep_id, chat, day, *, origin="whatsapp", last=None, **fm):
    _write(bank / "episodes" / f"{ep_id}.md",
           {"id": ep_id, "processed": False, "title": f"WhatsApp · {day}", "origin": origin, "conversation": chat,
            "timestamp": f"{day}T08:00:00+00:00", "sitting_last_at": last or f"{day}T09:00:00+00:00",
            "message_count": 2, **fm}, "user: words that never ride a list")


@pytest.fixture
def bank(tmp_path):
    b = tmp_path / "memory"
    b.mkdir()
    bank_index.invalidate()
    yield b
    bank_index.invalidate()


def test_the_settings_files_the_sources_component_reads_are_the_readers_own():
    assert set(sync_service.CHAT_SETTINGS_FILENAMES) == {
        messages_source.SETTINGS_FILENAME, whatsapp_source.SPEC.settings_filename,
        telegram_source.SPEC.settings_filename}


@pytest.mark.parametrize("spec", [whatsapp_source.SPEC, telegram_source.SPEC])
def test_a_pin_is_kept_with_the_chat_and_never_ticks_it(bank, spec):
    chat_live.update_settings(bank, spec, {"id": CHAT_A, "pinned": True})
    entry = chat_live.load_settings(bank, spec)["conversations"][CHAT_A]
    assert (entry["pinned"], entry["ticked"]) == (True, False)
    chat_live.update_settings(bank, spec, {"id": CHAT_A, "ticked": True})
    assert chat_live.load_settings(bank, spec)["conversations"][CHAT_A]["pinned"] is True   # a tick keeps the pin
    chat_live.update_settings(bank, spec, {"id": CHAT_A, "pinned": False})
    assert chat_live.load_settings(bank, spec)["conversations"][CHAT_A]["pinned"] is False


def test_a_messages_pin_is_kept_the_same_way(bank):
    messages_source.update_settings(bank, conversation={"id": CHAT_A, "pinned": True})
    entry = messages_source.load_settings(bank)["conversations"][CHAT_A]
    assert (entry["pinned"], entry["ticked"]) == (True, False)


def test_a_chat_row_says_tick_pin_recency_and_when_it_was_stored(bank):
    _sitting(bank, "ep_2026-10-01_001", CHAT_A, "2026-10-01", correspondent={"name": "Person A"})
    _sitting(bank, "ep_2026-10-20_001", CHAT_B, "2026-10-20", correspondent={"name": "Person B"},
             last="2026-10-20T18:30:00+00:00")
    chat_live.update_settings(bank, whatsapp_source.SPEC, {"id": CHAT_B, "ticked": True})
    bank_index.invalidate()
    rows = channel_items.items(bank, "whatsapp")["items"]
    assert [r["id"] for r in rows] == [CHAT_B, CHAT_A]         # the apps' order: most recent activity first
    b, a = rows
    assert (b["ticked"], a["ticked"]) == (True, False)
    assert "pinned" not in a and "pinned" not in b
    assert b["last_at"] == "2026-10-20T18:30:00Z"
    assert b["synced_at"].endswith("Z") and "T" in b["synced_at"]
    assert "words that never ride" not in json.dumps(rows)


def test_a_pinned_chat_lists_first_whatever_its_recency(bank):
    _sitting(bank, "ep_2026-10-01_001", CHAT_A, "2026-10-01", correspondent={"name": "Person A"})
    _sitting(bank, "ep_2026-10-20_001", CHAT_B, "2026-10-20", correspondent={"name": "Person B"})
    chat_live.update_settings(bank, whatsapp_source.SPEC, {"id": CHAT_A, "pinned": True})
    bank_index.invalidate()
    rows = channel_items.items(bank, "whatsapp")["items"]
    assert [(r["id"], r.get("pinned")) for r in rows] == [(CHAT_A, True), (CHAT_B, None)]


def test_messages_rows_carry_their_tick_and_pin_too(bank):
    _sitting(bank, "ep_2026-10-02_001", CHAT_A, "2026-10-02", origin=messages_source.ORIGIN,
             correspondent={"name": "Person A"})
    messages_source.update_settings(bank, conversation={"id": CHAT_A, "ticked": True, "pinned": True})
    bank_index.invalidate()
    (row,) = channel_items.items(bank, "imessage")["items"]
    assert (row["ticked"], row["pinned"]) == (True, True)


def _owner(bank, **picture):
    _write(bank / "entities" / "verify-person.md",
           {"id": "verify-person", "name": "Verify Person", "type": "person", "owner": True, "status": "active",
            **picture}, "")
    _write(bank / "_state.md", {"type": "state", "owner_id": "verify-person"}, "")


def test_the_persons_own_chat_draws_the_owners_picture(bank):
    """The owner's screenshot: "Notes to yourself" drew an "N" while the picker showed a photo. The self-chat stands
    for the owner's page, so its face is that page's picture by the one precedence (a Contacts photo here)."""
    _owner(bank, contacts_photo={"sha": "0123456789ab", "ext": "jpg"})
    _sitting(bank, "ep_2026-10-03_001", SELF, "2026-10-03", self_chat=True)
    bank_index.invalidate()
    (row,) = channel_items.items(bank, "whatsapp")["items"]
    assert row["title"] == channel_items.SELF_CHAT_TITLE
    assert row["chat"]["picture"] == "/entities/verify-person/picture?v=0123456789ab"


def test_a_bank_before_its_first_sleep_finds_the_owner_page_by_its_flag(bank):
    """A fresh bank has no `_state.md` yet; the `owner: true` page is still the person's own chat's page."""
    _owner(bank, contacts_photo={"sha": "0123456789ab", "ext": "jpg"})
    (bank / "_state.md").unlink()
    _sitting(bank, "ep_2026-10-03_001", SELF, "2026-10-03", self_chat=True)
    bank_index.invalidate()
    (row,) = channel_items.items(bank, "whatsapp")["items"]
    assert row["chat"]["picture"] == "/entities/verify-person/picture?v=0123456789ab"


def test_an_owner_page_with_no_picture_leaves_the_face_to_the_chat(bank):
    _owner(bank)
    _sitting(bank, "ep_2026-10-03_001", SELF, "2026-10-03", self_chat=True)
    bank_index.invalidate()
    (row,) = channel_items.items(bank, "whatsapp")["items"]
    assert "picture" not in row["chat"]


def test_a_chat_with_no_page_has_no_picture_key(bank):
    _sitting(bank, "ep_2026-10-01_001", CHAT_A, "2026-10-01", correspondent={"name": "Person A"})
    bank_index.invalidate()
    (row,) = channel_items.items(bank, "whatsapp")["items"]
    assert "picture" not in row["chat"]


def test_a_one_to_one_chat_draws_its_page_picture_with_no_stored_photo(bank):
    """"Other chat rows should show their photos, as the picker does": the picker draws a Contacts photo; the page drew
    a monogram unless the chat itself had posted one. The chat's page (its correspondent record, Stage 2's rule) draws
    by the one precedence, a Contacts photo included, whether or not a chat photo is stored."""
    _write(bank / "entities" / "person-a.md",
           {"id": "person-a", "name": "Person A", "type": "person", "status": "active",
            "contacts_photo": {"sha": "abcdefabcdef", "ext": "jpg"}}, "")
    _sitting(bank, "ep_2026-10-01_001", CHAT_A, "2026-10-01", correspondent={"name": "Person A", "kind": "person"})
    bank_index.invalidate()
    (row,) = channel_items.items(bank, "whatsapp")["items"]
    assert row["chat"]["picture"] == "/entities/person-a/picture?v=abcdefabcdef"


def test_a_ticked_chat_lists_before_its_first_message_is_stored(bank):
    """A tick reads live from now: the chat the person just ticked is on the page at once, "synced", with no recency
    and nothing to open yet — its name from its settings, never a word of it."""
    chat_live.update_settings(bank, whatsapp_source.SPEC, {"id": CHAT_A, "name": "Person A", "ticked": True})
    chat_live.update_settings(bank, whatsapp_source.SPEC, {"id": CHAT_B, "name": "Person B"})    # listed, never ticked
    bank_index.invalidate()
    (row,) = channel_items.items(bank, "whatsapp")["items"]
    assert (row["id"], row["title"], row["ticked"], row["day"], row.get("last_at")) == (
        CHAT_A, "Person A", True, None, None)
    assert channel_items.chat_sittings(bank, CHAT_A) == {"conversation": CHAT_A, "ticked": True, "sittings": []}
    assert channel_items.chat_sittings(bank, CHAT_B) is None


def test_an_unticked_chat_lists_no_sittings_to_open(bank):
    """G179's ticked-only rail on the chat page's panel: an unticked chat keeps its name, picture and recency on the
    page, never its messages. The words stay in memory (unticking deletes nothing); the page's route lists none."""
    _sitting(bank, "ep_2026-10-01_001", CHAT_A, "2026-10-01", correspondent={"name": "Person A"})
    bank_index.invalidate()
    assert channel_items.chat_sittings(bank, CHAT_A) == {"conversation": CHAT_A, "ticked": False, "sittings": []}
    chat_live.update_settings(bank, whatsapp_source.SPEC, {"id": CHAT_A, "ticked": True})
    page = channel_items.chat_sittings(bank, CHAT_A)
    assert page["ticked"] is True and [x["id"] for x in page["sittings"]] == ["ep_2026-10-01_001"]
    assert (bank / "episodes" / "ep_2026-10-01_001.md").exists()


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_HOME", str(bank.parent / "home"))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_settings_route_pins_and_the_list_follows(client, bank):
    """One `user` commit of the settings file (the tick's route, unchanged), and the list's ETag moves with it: a pin
    touches no other component."""
    _sitting(bank, "ep_2026-10-01_001", CHAT_A, "2026-10-01", correspondent={"name": "Person A"})
    _sitting(bank, "ep_2026-10-20_001", CHAT_B, "2026-10-20", correspondent={"name": "Person B"})
    bank_index.invalidate()
    first = client.get("/sources/channels/whatsapp/items")
    assert [r["id"] for r in first.json()["items"]] == [CHAT_B, CHAT_A]
    put = client.put("/sources/whatsapp/settings", json={"conversation": {"id": CHAT_A, "pinned": True}})
    assert put.status_code == 200, put.text
    assert next(c for c in put.json()["conversations"] if c["id"] == CHAT_A)["pinned"] is True
    again = client.get("/sources/channels/whatsapp/items", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 200
    assert [r["id"] for r in again.json()["items"]] == [CHAT_A, CHAT_B]


def test_the_messages_route_pins(client, bank):
    put = client.put("/sources/messages/settings", json={"conversation": {"id": CHAT_A, "pinned": True}})
    assert put.status_code == 200, put.text
    assert put.json()["conversations"][CHAT_A]["pinned"] is True


def test_the_sittings_route_follows_a_tick(client, bank):
    """The panel's route answers a tick at once: its ETag rides the chat settings (`sources`), not only `episodes`."""
    _sitting(bank, "ep_2026-10-01_001", CHAT_A, "2026-10-01", correspondent={"name": "Person A"})
    bank_index.invalidate()
    first = client.get(f"/sources/messages/chats/{CHAT_A}/sittings")
    assert first.status_code == 200 and first.json()["sittings"] == []
    assert client.put("/sources/whatsapp/settings", json={"conversation": {"id": CHAT_A, "ticked": True}}).status_code == 200
    again = client.get(f"/sources/messages/chats/{CHAT_A}/sittings", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 200 and [x["id"] for x in again.json()["sittings"]] == ["ep_2026-10-01_001"]


def test_the_telegram_route_pins_without_asking_telegram(client, bank):
    """A pin is not a tick: it needs no consent and no word from Telegram (ruling 47a's checks guard ticks only)."""
    put = client.put("/sources/telegram/settings", json={"conversation": {"id": CHAT_A, "pinned": True}})
    assert put.status_code == 200, put.text
    entry = chat_live.load_settings(bank, telegram_source.SPEC)["conversations"][CHAT_A]
    assert (entry["pinned"], entry["ticked"]) == (True, False)


def test_the_page_finder_answers_as_find_page_does():
    """The chat list resolves every chat's page through one index (`page_finder`); it must pick exactly what Stage 2's
    `find_page` picks — a name before an alias, the smallest id on a tie, the type, never the owner's page."""
    from api.services import correspondents

    pages = [
        {"id": "b-person", "frontmatter": {"name": "Person A", "type": "person"}},
        {"id": "a-person", "frontmatter": {"name": "person a", "type": "Person"}},
        {"id": "c-alias", "frontmatter": {"name": "Someone", "type": "person", "aliases": ["Person B", ""]}},
        {"id": "d-alias", "frontmatter": {"name": "Other", "type": "person", "aliases": "Person B"}},
        {"id": "e-owner", "frontmatter": {"name": "Person C", "type": "person", "owner": True}},
        {"id": "f-tool", "frontmatter": {"name": "Person A", "type": "tool"}},
        {"id": "g-named", "frontmatter": {"name": "Person D", "type": "person", "aliases": ["Person D"]}},
    ]
    find = correspondents.page_finder(pages)
    for name in ("Person A", "Person B", "Person C", "Person D", "Nobody"):
        for kind in ("person", "agent"):
            ident = correspondents.identity({"name": name, "kind": kind})
            expected = correspondents.find_page(pages, ident)
            assert find(ident) == expected, (name, kind)
