"""G91 (owner ruling 38, 2026-10-23): a paired phone shares a photo or a file through `POST /capture/file`, and speaks a
note it transcribed itself. The bytes live outside every bank, the bank holds one scrubbed episode with the person's
caption, the type is read from the bytes, and a resend writes nothing twice. Synthetic bytes and placeholder names, no
network, no model."""
from __future__ import annotations

import hashlib
import os
import stat

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api.remote import reach
from api.services import auth, capture_files, demo_guard, markdown_parser, request_limits, video_queue

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + bytes(range(256)) * 8
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 600
HEIC = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x01" * 600
PDF = b"%PDF-1.7\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"
GIF = b"GIF89a" + b"\x00" * 64


@pytest.fixture
def server(tmp_path, monkeypatch):
    from api import config
    from api.main import app

    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_API_AUTH", "on")
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(reach, "tailnet_backend", lambda port, **kw: reach.TailnetBackend("missing", None))
    config.get_settings.cache_clear()
    master = auth.get_token()
    with TestClient(app) as client:
        yield client, master, memory, tmp_path / "home"
    config.get_settings.cache_clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _phone(client, master, kind="capture", name="Example Phone"):
    """A device paired the way `POST /pair` pairs one (its route is rate-limited per process; `test_phone_pairing`
    covers it), returned as the wire's dict and its token."""
    from api.services import device_tokens

    store = device_tokens.store()
    _, code = store.create_pairing(kind=kind)
    device, token = store.redeem(code, name)
    return {"id": device.id, "kind": device.kind}, token


def _send(client, token, data, name="whiteboard.jpg", mime="image/jpeg", key=None, **fields):
    headers = {**_auth(token), **({"Idempotency-Key": key} if key else {})}
    return client.post("/capture/file", files={"file": (name, data, mime)}, data=fields, headers=headers)


def _episode(memory, episode_id):
    path = memory / "episodes" / f"{episode_id}.md"
    return markdown_parser.parse(path).frontmatter, path.read_text()


def _bank_files(memory):
    """Every file in the bank but git's and the derived indexes' (disposable, rebuilt on read, never tracked)."""
    return {p.relative_to(memory).as_posix() for p in memory.rglob("*")
            if p.is_file() and ".git" not in p.parts and not p.name.startswith(("search_index", "vectors"))}


def test_a_photo_lands_outside_the_bank_and_the_bank_holds_only_its_episode(server):
    client, master, memory, home = server
    device, token = _phone(client, master)
    before = _bank_files(memory)
    sent = _send(client, token, JPEG, caption="The plan for alpha-project, from the whiteboard.", key="item-1")
    assert sent.status_code == 200, sent.text
    answer = sent.json()
    sha = hashlib.sha256(JPEG).hexdigest()
    assert answer["status"] == "created" and answer["file"] == {"kind": "image", "size": len(JPEG), "sha256": sha}

    # The bytes: outside every bank, content-addressed, kept exactly as sent, 0600 in a 0700 folder.
    kept = home / "files" / video_queue.bank_slug(memory) / f"{sha}.jpg"
    assert kept.read_bytes() == JPEG
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600 and stat.S_IMODE(kept.parent.stat().st_mode) == 0o700
    # The bank: one new episode, and not a byte of the photo (no thumbnail either).
    added = _bank_files(memory) - before
    assert added == {f"episodes/{answer['episodeId']}.md"}
    assert not any(JPEG[:64] in (memory / rel).read_bytes() for rel in _bank_files(memory))

    fm, text = _episode(memory, answer["episodeId"])
    assert fm["origin"] == "phone" and fm["device"] == device["id"] and fm["processed"] is False
    assert fm["file"] == {"kind": "image", "mime": "image/jpeg", "name": "whiteboard.jpg", "size": len(JPEG),
                          "sha256": sha}
    assert "user: The plan for alpha-project, from the whiteboard.\n[image: whiteboard.jpg]" in text
    assert fm["turn_extras"][0]["attachments"] == [{"kind": "image", "name": "whiteboard.jpg", "size": len(JPEG),
                                                    "mime": "image/jpeg"}]
    assert str(home) not in text and "files/" not in str(fm["file"])          # never a path
    mine = client.get("/capture/mine", headers=_auth(token)).json()["captures"]
    assert [c["id"] for c in mine] == [answer["episodeId"]]


def test_the_capture_only_token_reaches_the_file_route_and_nothing_new_else(server):
    client, master, _, _ = server
    assert ("POST", "/capture/file") in auth.CAPTURE_ROUTES
    _, token = _phone(client, master)
    assert _send(client, token, PNG, name="shot.png", mime="image/png").status_code == 200
    assert client.get("/capture/file", headers=_auth(token)).status_code in (403, 405)
    assert client.post("/sources/upload", files={"file": ("x.json", b"{}", "application/json")},
                       headers=_auth(token)).status_code == 403
    assert client.post("/capture/file", files={"file": ("a.png", PNG, "image/png")}).status_code == 401


def test_a_resend_with_the_same_key_or_the_same_bytes_writes_nothing_twice(server):
    client, master, memory, _ = server
    _, token = _phone(client, master)
    first = _send(client, token, PDF, name="receipt.pdf", mime="application/pdf", key="item-2").json()
    episodes = set((memory / "episodes").glob("ep_*.md"))
    again = _send(client, token, PDF, name="receipt.pdf", mime="application/pdf", key="item-2").json()
    assert again == first and set((memory / "episodes").glob("ep_*.md")) == episodes
    # Without a key or an id, the bytes are the identity: the same file twice is one episode.
    a = _send(client, token, HEIC, name="IMG_0001.HEIC", mime="image/heic").json()
    b = _send(client, token, HEIC, name="IMG_0001.HEIC", mime="image/heic").json()
    assert a["status"] == "created" and b["status"] == "unchanged" and a["episodeId"] == b["episodeId"]
    # The client's own id is the identity when it sends one.
    c = _send(client, token, HEIC, name="IMG_0001.HEIC", mime="image/heic", id="queue-item-7").json()
    assert c["status"] == "created" and c["episodeId"] != a["episodeId"]


def test_heic_and_pdf_are_kept_as_sent_and_the_type_comes_from_the_bytes(server):
    client, master, memory, home = server
    _, token = _phone(client, master)
    heic = _send(client, token, HEIC, name="IMG_0002.HEIC", mime="application/octet-stream").json()
    assert heic["file"]["kind"] == "image"
    assert (capture_files.outside_root(memory) / f"{hashlib.sha256(HEIC).hexdigest()}.heic").read_bytes() == HEIC
    pdf = _send(client, token, PDF, name="  ", mime="application/octet-stream").json()   # a blank name
    fm, text = _episode(memory, pdf["episodeId"])
    assert fm["file"]["kind"] == "pdf" and fm["file"]["name"] == "document.pdf" and "[file: document.pdf]" in text


@pytest.mark.parametrize("data,name,mime", [
    (GIF, "anim.gif", "image/gif"),                       # a picture, but not one of the three photo types
    (b"MZ\x90\x00" + b"\x00" * 100, "photo.jpg", "image/jpeg"),   # the client's word is not the type
    (b"\x00\x01binary\xff\xfe", "notes.txt", "text/plain"),     # "text" that is not UTF-8 text
    (b"plain words", "notes.md", "text/markdown"),         # text, but not declared plain text
])
def test_a_type_outside_the_allowlist_is_415_and_writes_nothing(server, data, name, mime):
    client, master, memory, home = server
    _, token = _phone(client, master)
    before = _bank_files(memory)
    sent = _send(client, token, data, name=name, mime=mime)
    assert sent.status_code == 415 and "photo" in sent.json()["detail"]
    assert _bank_files(memory) == before and not (home / "files").exists()


def test_a_file_past_the_cap_is_413_before_a_byte_is_kept(server, monkeypatch):
    client, master, memory, home = server
    _, token = _phone(client, master)
    monkeypatch.setattr(capture_files, "MAX_BYTES", 1024)
    sent = _send(client, token, JPEG + b"\x00" * 2048)
    assert sent.status_code == 413 and not (home / "files").exists()
    # The request bound refuses a bigger body before the route reads it.
    monkeypatch.setitem(request_limits.BODY_LIMITS, "/capture/file", 512)
    assert _send(client, token, JPEG).status_code == 413
    assert _send(client, token, b"", name="empty.jpg").status_code in (400, 413, 422)


def test_a_text_file_s_words_are_a_scrubbed_person_turn(server):
    client, master, memory, _ = server
    _, token = _phone(client, master)
    words = "Groceries for the alpha-project offsite.\nkey: sk-abcdefghijklmnopqrstuvwx1234\n"
    sent = _send(client, token, words.encode(), name="list.txt", mime="text/plain", caption="for Friday").json()
    fm, text = _episode(memory, sent["episodeId"])
    assert fm["file"]["kind"] == "text" and sent["file"]["kind"] == "text"
    assert "user: for Friday\n[file: list.txt]\nuser: Groceries for the alpha-project offsite." in text
    assert "sk-abcdefghijklmnopqrstuvwx1234" not in text and "[redacted]" in text
    # The kept file is the bytes as sent (outside the bank); only the bank's copy is scrubbed.
    kept = capture_files.outside_root(memory) / f"{hashlib.sha256(words.encode()).hexdigest()}.txt"
    assert kept.read_bytes() == words.encode()


def test_a_name_is_a_name_never_a_path_and_cannot_close_its_marker(server):
    client, master, memory, _ = server
    _, token = _phone(client, master)
    sent = _send(client, token, PNG, name="../../etc/odd]name[.png", mime="image/png").json()
    fm, text = _episode(memory, sent["episodeId"])
    assert fm["file"]["name"] == "odd)name(.png" and "[image: odd)name(.png]" in text


def test_a_demo_bank_is_409_and_nothing_is_kept_anywhere(server):
    client, master, memory, home = server
    _, token = _phone(client, master)
    demo_guard.write_manifest(memory)
    before = _bank_files(memory)
    sent = _send(client, token, JPEG, key="item-demo")
    assert sent.status_code == 409 and sent.json()["detail"] == demo_guard.REFUSAL
    assert _bank_files(memory) == before and not (home / "files").exists()


def test_a_file_from_a_full_device_is_device_file_not_phone(server):
    client, master, memory, _ = server
    device, token = _phone(client, master, kind="full", name="laptop")
    sent = _send(client, token, PNG, name="diagram.png", mime="image/png").json()
    fm, _ = _episode(memory, sent["episodeId"])
    assert fm["origin"] == "device-file" and fm["device"] == device["id"]
    from api.services import source_overview

    assert source_overview.source_key({"origin": "device-file"}) == "device-files"


def test_a_voice_note_is_marked_and_a_typed_one_is_unchanged(server):
    client, master, memory, _ = server
    _, token = _phone(client, master)
    voice = client.post("/capture/note", json={"text": "Call about the alpha-project budget.", "kind": "voice"},
                        headers=_auth(token)).json()
    fm, text = _episode(memory, voice["episodeId"])
    assert fm["note_kind"] == "voice" and fm["title"] == "Voice note" and fm["origin"] == "phone"
    assert "user: Call about the alpha-project budget." in text
    typed = client.post("/capture/note", json={"text": "A typed one."}, headers=_auth(token)).json()
    fm, _ = _episode(memory, typed["episodeId"])
    assert "note_kind" not in fm and fm["title"] == "Note"
    assert client.post("/capture/note", json={"text": "x", "kind": "audio"}, headers=_auth(token)).status_code == 422


def test_keep_is_atomic_and_writes_the_same_bytes_once(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "bank"
    memory.mkdir()
    accepted = capture_files.accept(PNG, "image/png", "a.png")
    first = capture_files.keep(memory, PNG, accepted)
    mtime = first.stat().st_mtime_ns
    assert capture_files.keep(memory, PNG, accepted) == first and first.stat().st_mtime_ns == mtime
    assert [p.name for p in first.parent.iterdir()] == [first.name]          # no temporary file left
    assert capture_files.stored_path(memory, "../x", "png") is None
    assert capture_files.stored_path(memory, accepted.sha256, "exe") is None
    assert os.path.commonpath([first, tmp_path / "home"]) == str(tmp_path / "home")
