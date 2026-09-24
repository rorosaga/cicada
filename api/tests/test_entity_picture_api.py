"""C11's writes (plan R-PE1, R-PE2, R-PE4, R-PE8): the person's picture lives in the bank, commits alone as `user`,
refuses while Sleep runs, never stores what it cannot read, and is served only from its own folder."""
from __future__ import annotations

import asyncio
import struct
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bank_index, bank_registry, entity_picture, git_service, graph_builder, logo_service,
                          markdown_parser, sleep_cycle)


def png_bytes(width: int, height: int) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82")


def jpeg_bytes(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, height, width) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def _git(bank, *args) -> str:
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "banks" / "work"
    bank_registry.scaffold_bank(memory)
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Cicada Test")
    markdown_parser.write(memory / "entities" / "bob-example.md", {"name": "Bob Example", "type": "person"},
                          "## Summary\nRuns the lab.\n")
    markdown_parser.write(memory / "entities" / "acme.md", {"name": "Acme", "type": "company"}, "## Summary\nA client.\n")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(logo_service, "cached_ids", lambda bank: {"acme"})
    monkeypatch.setattr(logo_service, "missed_ids", lambda bank: {})
    config.get_settings.cache_clear()
    bank_index.invalidate()
    graph_builder._CACHE.update({"key": None, "value": None})
    with TestClient(main.app) as c:
        yield c, memory
    config.get_settings.cache_clear()


def _post(c, entity_id, data, name="picture.png", mime="image/png"):
    return c.post(f"/entities/{entity_id}/picture", files={"file": (name, data, mime)})


def _last(bank, path) -> str:
    return _git(bank, "log", "-1", "--format=%H", "--", path).strip()


def test_an_upload_is_stored_in_the_bank_and_commits_alone_as_the_person(client):
    c, bank = client
    acme = bank / "entities" / "acme.md"
    acme.write_text(acme.read_text(encoding="utf-8") + "\nAn unrelated edit.\n", encoding="utf-8")
    data = png_bytes(64, 64)
    r = _post(c, "bob-example", data)
    assert r.status_code == 200, r.text
    sha = entity_picture.sha12(data)
    assert r.json() == {"entityId": "bob-example", "picture": f"/entities/bob-example/picture?v={sha}",
                        "pictureSource": "upload",
                        "pictureInputs": {"type": "person", "choice": "upload", "uploadSha": sha,
                                          "contactsSha": None, "logo": False, "thumbnail": None}}
    assert (bank / "assets" / "pictures" / "bob-example.png").read_bytes() == data
    picture = markdown_parser.parse(bank / "entities" / "bob-example.md").frontmatter["picture"]
    assert (picture["kind"], picture["sha"], picture["ext"]) == ("upload", sha, "png")
    head = _last(bank, "assets/pictures/bob-example.png")
    message = _git(bank, "show", "-s", "--format=%B", head)
    assert message.startswith("Set picture ") and "Cicada-Author: user" in message
    assert "trigger: user/companion_app" in message
    assert sorted(_git(bank, "show", "--name-only", "--format=", head).split()) == \
        ["assets/pictures/bob-example.png", "entities/bob-example.md"]
    assert "entities/acme.md" in _git(bank, "status", "--porcelain"), "an unrelated dirty page is never swept in"
    node = next(n for n in c.get("/graph").json()["nodes"] if n["id"] == "bob-example")
    assert node["picture"] == f"/entities/bob-example/picture?v={sha}"


def test_a_new_format_replaces_the_old_file_and_the_removal_is_committed(client):
    c, bank = client
    assert _post(c, "bob-example", png_bytes(64, 64)).status_code == 200
    r = _post(c, "bob-example", jpeg_bytes(400, 300), name="p.jpg", mime="image/jpeg")
    assert r.status_code == 200, r.text
    assert sorted(p.name for p in (bank / "assets" / "pictures").iterdir()) == ["bob-example.jpg"]
    head = _last(bank, "assets/pictures/bob-example.jpg")
    assert sorted(_git(bank, "show", "--name-only", "--format=", head).split()) == \
        ["assets/pictures/bob-example.jpg", "assets/pictures/bob-example.png", "entities/bob-example.md"]
    assert "assets/pictures/bob-example.png" not in _git(bank, "ls-files")


# Explicit ids: a 513 KB value as the test id rides into PYTEST_CURRENT_TEST, and git's environment overflows (E2BIG).
@pytest.mark.parametrize("data,status", [
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>", 400),
    (b"GIF89a" + b"\x00" * 20, 400),
    (png_bytes(8, 8), 400),
    (png_bytes(2000, 1000), 400),
    (png_bytes(64, 64) + b"\x00" * (512 * 1024), 413),
    (b"", 400),
], ids=["svg", "gif", "too-small", "too-large-side", "over-512k", "empty"])
def test_what_the_server_cannot_keep_is_refused_in_words_and_nothing_is_written(client, data, status):
    c, bank = client
    r = _post(c, "bob-example", data)
    assert r.status_code == status
    assert r.json()["detail"].endswith("."), "a sentence the app shows as written (R-PE2)"
    assert not (bank / "assets" / "pictures").exists()
    assert "picture" not in markdown_parser.parse(bank / "entities" / "bob-example.md").frontmatter


def test_unknown_pages_and_a_running_sleep_are_refused(client, monkeypatch):
    c, _ = client
    assert _post(c, "nobody", png_bytes(64, 64)).status_code == 404
    assert c.delete("/entities/nobody/picture").status_code == 404
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    for r in (_post(c, "bob-example", png_bytes(64, 64)), c.post("/entities/bob-example/picture/initials"),
              c.delete("/entities/bob-example/picture")):
        assert r.status_code == 409 and "Sleep" in r.json()["detail"]


def test_the_picture_is_served_with_an_etag_and_only_from_its_own_folder(client):
    c, bank = client
    data = png_bytes(64, 64)
    assert _post(c, "bob-example", data).status_code == 200
    r = c.get("/entities/bob-example/picture?v=anything")
    assert r.status_code == 200 and r.content == data and r.headers["content-type"] == "image/png"
    assert c.get("/entities/bob-example/picture", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert c.get("/entities/acme/picture").status_code == 404, "a logo is served by /logo, never here"
    page = bank / "entities" / "acme.md"
    fm = markdown_parser.parse(page).frontmatter
    fm["picture"] = {"kind": "upload", "sha": "3f9a1c0b2d4e", "ext": "png"}
    markdown_parser.write(page, fm, "## Summary\nA client.\n")
    assert c.get("/entities/acme/picture").status_code == 404, "a page that claims an upload with no file serves nothing"
    (bank / "assets" / "pictures" / "acme.png").write_bytes(b"<svg/>")
    assert c.get("/entities/acme/picture").status_code == 404, "bytes that are not a PNG or JPEG are never served"


def test_initials_are_a_choice_and_delete_returns_to_what_was_detected(client):
    c, bank = client
    assert _post(c, "acme", png_bytes(64, 64)).status_code == 200
    r = c.post("/entities/acme/picture/initials")
    assert r.status_code == 200 and (r.json()["pictureSource"], r.json()["picture"]) == ("initials", None)
    assert not (bank / "assets" / "pictures" / "acme.png").exists()
    assert markdown_parser.parse(bank / "entities" / "acme.md").frontmatter["picture"]["kind"] == "initials"
    assert _git(bank, "log", "-1", "--format=%s", "--", "entities/acme.md").startswith("Use initials ")
    assert "assets/pictures/acme.png" not in _git(bank, "ls-files")
    r = c.delete("/entities/acme/picture")
    assert r.status_code == 200
    assert (r.json()["pictureSource"], r.json()["picture"]) == ("logo", "/entities/acme/logo")
    assert "picture" not in markdown_parser.parse(bank / "entities" / "acme.md").frontmatter
    assert _git(bank, "log", "-1", "--format=%s", "--", "entities/acme.md").startswith("Remove picture ")
    before = _git(bank, "rev-parse", "HEAD")
    assert c.delete("/entities/acme/picture").status_code == 200
    assert _git(bank, "rev-parse", "HEAD") == before, "nothing chosen, nothing to commit"


def test_the_contacts_seam_is_read_and_served_but_never_written(client, tmp_path):
    c, bank = client
    photo = jpeg_bytes(120, 120)
    page = bank / "entities" / "bob-example.md"
    fm = markdown_parser.parse(page).frontmatter
    fm["contacts_photo"] = {"sha": entity_picture.sha12(photo)}
    markdown_parser.write(page, fm, "## Summary\nRuns the lab.\n")
    folder = tmp_path / "home" / "pictures" / "work" / "contacts"
    folder.mkdir(parents=True)
    (folder / "bob-example.jpg").write_bytes(photo)
    body = c.get("/entities/bob-example").json()
    assert body["pictureSource"] == "contacts"
    served = c.get(body["picture"])
    assert served.status_code == 200 and served.content == photo and served.headers["content-type"] == "image/jpeg"
    up = _post(c, "bob-example", png_bytes(64, 64)).json()
    assert up["pictureSource"] == "upload", "the person's own picture outranks Contacts"
    assert c.get(up["picture"]).content == png_bytes(64, 64)
    assert (folder / "bob-example.jpg").read_bytes() == photo, "the Contacts file is T-Sources' — never touched"


def test_a_contacts_png_is_found_where_t_sources_writes_it(client, tmp_path):
    """Final review, finding 1 — written the way T-Sources' R-SR9 writes it: `contacts_photo: {sha, ext}` on the page,
    the bytes at `$CICADA_HOME/pictures/<bank>/contacts/<id>.png`. A mismatch here is a card saying 'Photo from your
    Contacts' over a monogram."""
    c, bank = client
    photo = png_bytes(96, 96)
    page = bank / "entities" / "bob-example.md"
    fm = markdown_parser.parse(page).frontmatter
    fm["contacts_photo"] = {"sha": entity_picture.sha12(photo), "ext": "png"}
    markdown_parser.write(page, fm, "## Summary\nRuns the lab.\n")
    folder = tmp_path / "home" / "pictures" / "work" / "contacts"
    folder.mkdir(parents=True)
    (folder / "bob-example.png").write_bytes(photo)
    body = c.get("/entities/bob-example").json()
    assert body["pictureSource"] == "contacts"
    served = c.get(body["picture"])
    assert served.status_code == 200 and served.content == photo and served.headers["content-type"] == "image/png"
    fm["contacts_photo"] = {"sha": entity_picture.sha12(photo), "ext": "gif"}
    markdown_parser.write(page, fm, "## Summary\nRuns the lab.\n")
    assert c.get("/entities/bob-example").json()["pictureSource"] != "contacts", "an ext the seam can't serve never claims the rung"


def test_a_scalar_sources_value_never_breaks_the_graph_or_the_card(client):
    """Final review, finding 2 — `sources: 5` on one page 500'd all of `GET /graph` through the logo domain walk."""
    c, bank = client
    # Not in the cached logo set, so the resolver walks the page for a domain — where the scalar used to raise.
    markdown_parser.write(bank / "entities" / "globex.md", {"name": "Globex", "type": "company", "sources": 5},
                          "## Summary\nA company.\n")
    assert c.get("/graph").status_code == 200
    assert c.get("/entities/globex").status_code == 200


def test_a_new_bank_has_a_home_for_pictures_and_git_says_what_it_tracks(tmp_path):
    bank = tmp_path / "fresh"
    bank_registry.scaffold_bank(bank)
    assert (bank / "assets").is_dir()
    _git(bank, "config", "user.email", "test@example.com")
    _git(bank, "config", "user.name", "Cicada Test")
    (bank / "entities" / "x.md").write_text("x\n", encoding="utf-8")
    _git(bank, "add", "entities/x.md")
    _git(bank, "commit", "-q", "-m", "seed")
    assert asyncio.run(git_service.is_tracked(bank, "entities/x.md"))
    assert not asyncio.run(git_service.is_tracked(bank, "entities/missing.md"))
