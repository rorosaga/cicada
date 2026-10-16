"""The photo a ticked Messages chat shares, as its correspondent page's picture everywhere (2026-10-16).

Synthetic throughout: a synthetic ``chat.db`` (`_imessage_fixtures`), placeholder handles and names, and header-only
PNGs. Covers: the rung on the graph and the card, the bytes outside every bank, the link following the correspondent
record (a mark, a page that appears later), the person's own picture winning, the Contacts photo winning, a changed
photo replacing, a removal, unticking, the refusals, and the sync stamp moving."""
from __future__ import annotations

import base64
import struct

import pytest
from fastapi.testclient import TestClient

from _imessage_fixtures import ChatDB, conversation_id, payload, read_rows, utc
from api import config, main
from api.models.schemas import MessagesSyncRequest
from api.services import (bank_index, entity_picture, graph_builder, markdown_parser, messages_photos, messages_source,
                          sync_service)

AGENT = "+15550000001"     # placeholder handles — never real numbers
OTHER = "+15550000003"


def png(width: int = 128, height: int = 128, tag: bytes = b"\x00") -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + tag * 4
            + b"\x00\x00\x00\x00IEND\xaeB`\x82")


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.fixture
def home(tmp_path, monkeypatch):
    path = tmp_path / "cicada-home"
    monkeypatch.setenv("CICADA_HOME", str(path))
    messages_photos._MEMO.clear()
    return path


@pytest.fixture
def bank(tmp_path, home):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True)
    bank_index.invalidate()
    return memory


@pytest.fixture
def chat(tmp_path):
    db = ChatDB(tmp_path / "chat.db")
    db.agent = db.chat(AGENT)
    db.other = db.chat(OTHER)
    db.message(db.agent, utc(2026, 9, 3, 10, 0), from_me=True, text="Can you help me plan the alpha-project launch?")
    db.message(db.agent, utc(2026, 9, 3, 10, 1), from_me=False, text="Sure, here is a first step.")
    db.message(db.other, utc(2026, 9, 3, 11, 0), from_me=False, text="Lunch on Friday?")
    db.db.commit()
    yield db
    db.close()


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    graph_builder._CACHE.update({"key": None, "value": None})
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def _tick(bank, guid, name, **extra):
    messages_source.update_settings(bank, conversation={"id": conversation_id(guid), "name": name, "ticked": True,
                                                        **extra})


def _sync(bank, db, chat_id, name, **kw):
    rows = read_rows(db.path, chat_id)
    body = MessagesSyncRequest.model_validate(payload(db.chat_guid(chat_id), rows, name=name, **kw))
    messages_source.ingest(bank, body.model_dump(by_alias=False), bank=bank.name)
    bank_index.invalidate()


def _page(bank, page_id, name, type_, **extra):
    markdown_parser.write(bank / "entities" / f"{page_id}.md", {"id": page_id, "name": name, "type": type_, **extra},
                          f"# {name}\n")
    bank_index.invalidate()


def _node(client, page_id):
    # No cache reset here: the graph's own cache and its ETag must move with the photo and the link.
    nodes = {n["id"]: n for n in client.get("/graph").json()["nodes"]}
    return nodes[page_id]


def _bank_files(bank) -> dict:
    return {p.relative_to(bank).as_posix(): p.read_bytes() for p in bank.rglob("*") if p.is_file()}


def test_a_texted_agents_page_draws_the_photo_its_chat_shares_everywhere(client, bank, chat, home):
    _tick(bank, chat.chat_guid(chat.agent), "Instinct")
    _sync(bank, chat, chat.agent, "Instinct", from_me=10, from_them=40)            # identified: an agent
    _page(bank, "instinct-agent", "Instinct", "tool")
    _page(bank, "instinct", "Instinct", "concept")                                 # same letters, another type
    cid = conversation_id(chat.chat_guid(chat.agent))
    before = _bank_files(bank)
    photo = png()
    r = client.put("/sources/messages/photos", json={"photos": [{"conversation": cid, "photoB64": b64(photo)}]})
    assert r.status_code == 200, r.text
    assert r.json() == {"stored": 1, "removed": 0, "unchanged": 0, "pages": {cid: "instinct-agent"}}
    # The bytes live outside the bank; nothing in the bank moved.
    assert _bank_files(bank) == before
    assert (home / "pictures" / bank.name / "messages" / f"{cid}.png").read_bytes() == photo
    sha = entity_picture.sha12(photo)
    node = _node(client, "instinct-agent")
    assert (node["pictureSource"], node["picture"]) == ("messages", f"/entities/instinct-agent/picture?v={sha}")
    assert "pictureSource" not in _node(client, "instinct")                       # never the same-name concept
    card = client.get("/entities/instinct-agent").json()
    assert card["pictureSource"] == "messages" and card["pictureInputs"]["messagesSha"] == sha
    served = client.get("/entities/instinct-agent/picture")
    assert served.status_code == 200 and served.content == photo and served.headers["content-type"] == "image/png"
    # The same post again changes nothing.
    again = client.put("/sources/messages/photos", json={"photos": [{"conversation": cid, "photoB64": b64(photo)}]})
    assert again.json()["unchanged"] == 1


def test_the_link_follows_the_record_a_mark_and_a_page_that_appears_later(client, bank, chat):
    _tick(bank, chat.chat_guid(chat.other), "Bob Example")
    _sync(bank, chat, chat.other, "Bob Example", from_me=0, from_them=1)           # undecided: no page
    cid = conversation_id(chat.chat_guid(chat.other))
    _page(bank, "bob-example", "Bob Example", "person")
    r = client.put("/sources/messages/photos", json={"photos": [{"conversation": cid, "photoB64": b64(png())}]})
    assert r.json()["pages"] == {cid: None} and messages_photos.links(bank) == {}
    assert "pictureSource" not in _node(client, "bob-example")
    stamp = sync_service.components(bank)["photos"]
    # The person marks the chat a person: the record moves (no new words), so does the link — no second post.
    client.put("/sources/messages/settings", json={"conversation": {"id": cid, "actor": {"kind": "person"}}})
    bank_index.invalidate()
    assert messages_photos.links(bank)["bob-example"]["conversation"] == cid
    assert _node(client, "bob-example")["pictureSource"] == "messages"
    assert sync_service.components(bank)["photos"] != stamp                        # the graph's ETag moves
    # A page created later (here: the person page is replaced by Sleep's own) is found the same way.
    (bank / "entities" / "bob-example.md").unlink()
    _page(bank, "bob-example-person", "Bob Example", "person")
    assert list(messages_photos.links(bank)) == ["bob-example-person"]


def test_the_persons_choice_and_the_contacts_photo_win(client, bank, chat):
    _tick(bank, chat.chat_guid(chat.other), "Bob Example", actor={"kind": "person"})
    _sync(bank, chat, chat.other, "Bob Example", from_me=0, from_them=1)
    cid = conversation_id(chat.chat_guid(chat.other))
    _page(bank, "bob-example", "Bob Example", "person", contacts_photo={"sha": "0a1b2c3d4e5f", "ext": "jpg"})
    client.put("/sources/messages/photos", json={"photos": [{"conversation": cid, "photoB64": b64(png())}]})
    assert _node(client, "bob-example")["pictureSource"] == "contacts"
    _page(bank, "bob-example", "Bob Example", "person", picture={"kind": "initials", "added": "2026-10-16"})
    assert _node(client, "bob-example")["pictureSource"] == "initials"
    _page(bank, "bob-example", "Bob Example", "person")
    assert _node(client, "bob-example")["pictureSource"] == "messages"


def test_a_changed_photo_replaces_it_none_removes_it_and_unticking_forgets_it(client, bank, chat, home):
    _tick(bank, chat.chat_guid(chat.agent), "Instinct", actor={"kind": "agent"})
    _sync(bank, chat, chat.agent, "Instinct")
    _page(bank, "instinct-agent", "Instinct", "tool")
    cid = conversation_id(chat.chat_guid(chat.agent))
    first, second = png(tag=b"\x01"), png(tag=b"\x02")
    client.put("/sources/messages/photos", json={"photos": [{"conversation": cid, "photoB64": b64(first)}]})
    r = client.put("/sources/messages/photos", json={"photos": [{"conversation": cid, "photoB64": b64(second)}]})
    assert r.json()["stored"] == 1
    assert _node(client, "instinct-agent")["picture"].endswith(entity_picture.sha12(second))
    assert client.get("/entities/instinct-agent/picture").content == second
    r = client.put("/sources/messages/photos", json={"photos": [{"conversation": cid}]})
    assert r.json()["removed"] == 1 and "pictureSource" not in _node(client, "instinct-agent")
    client.put("/sources/messages/photos", json={"photos": [{"conversation": cid, "photoB64": b64(first)}]})
    assert _node(client, "instinct-agent")["pictureSource"] == "messages"
    client.put("/sources/messages/settings", json={"conversation": {"id": cid, "ticked": False}})
    assert not (home / "pictures" / bank.name / "messages" / f"{cid}.png").exists()
    assert cid not in messages_photos.read_meta(bank.name)
    assert "pictureSource" not in _node(client, "instinct-agent")
    assert client.get("/entities/instinct-agent/picture").status_code == 404


def test_refusals(client, bank, chat):
    cid = conversation_id(chat.chat_guid(chat.agent))
    r = client.put("/sources/messages/photos", json={"photos": [{"conversation": cid, "photoB64": b64(png())}]})
    assert r.status_code == 409                                                     # not ticked
    _tick(bank, chat.chat_guid(chat.agent), "Instinct")
    for bad in (b"GIF89a....", png(4, 4), png(4096, 4096), b"\x89PNG" + b"\x00" * (300 * 1024)):
        r = client.put("/sources/messages/photos", json={"photos": [{"conversation": cid, "photoB64": b64(bad)}]})
        assert r.status_code == 422, bad[:8]
    assert client.put("/sources/messages/photos", json={"photos": [{"conversation": "not-a-hash"}]}).status_code == 422
    assert messages_photos.read_meta(bank.name) == {}


def test_paths_never_leave_the_cache():
    assert messages_photos.photo_path("work", "../../etc") is None
    assert messages_photos.photo_path("work", "a" * 24, "gif") is None
    assert messages_photos.photo_path("work", "a" * 24).name == f"{'a' * 24}.png"


def test_a_chat_unticked_while_its_photo_was_being_posted_keeps_no_photo(bank, chat, home, monkeypatch):
    """Hunt 2026-10-16: the tick was checked before the store's lock, so an untick (and its `forget`) landing between
    the check and the write left the photo of an unticked chat on disk — "gone on untick" broken by a race."""
    _tick(bank, chat.chat_guid(chat.agent), "Instinct", actor={"kind": "agent"})
    cid = conversation_id(chat.chat_guid(chat.agent))
    real_decode = messages_photos._decode

    def decode_then_untick(raw):
        out = real_decode(raw)
        messages_source.update_settings(bank, conversation={"id": cid, "ticked": False})
        messages_photos.forget(bank, cid)          # what the settings route does on untick
        return out

    monkeypatch.setattr(messages_photos, "_decode", decode_then_untick)
    out = messages_photos.store(bank, [{"conversation": cid, "photo_b64": b64(png())}])
    assert out["stored"] == 0
    assert not (home / "pictures" / bank.name / "messages" / f"{cid}.png").exists()
    assert cid not in messages_photos.read_meta(bank.name)
