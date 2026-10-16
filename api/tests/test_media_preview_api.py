"""The routes: `GET /entities/{id}/preview` serves the stored copy (fetching once), the wire carries the stored path
and never a provider URL, and `POST /entities/{id}/picture/pdf` turns the person's own PDF into the page's picture.
Fake HTTP and a fake renderer only."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bank_index, bank_registry, graph_builder, markdown_parser, media_ingestor, media_preview,
                          pdf_page)


def png(width=40, height=30) -> bytes:
    return pdf_page.encode_png(width, height, b"\x40" * (width * 3 * height), width * 3)


def _git(bank, *args) -> str:
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


LINK = {"url": "https://example.com/a", "media_type": "url", "site": "example.com",
        "thumbnail": "https://cdn.example.com/a.png", "saved_at": "2026-10-01T00:00:00+00:00", "url_hash": "aaaaaaaaaaaa"}
PAPER = {"url": "https://arxiv.org/abs/2401.00001", "media_type": "url", "kind": "paper",
         "saved_at": "2026-10-01T00:00:00+00:00", "url_hash": "bbbbbbbbbbbb"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "banks" / "work"
    bank_registry.scaffold_bank(memory)
    _git(memory, "config", "user.email", "test@example.com")
    _git(memory, "config", "user.name", "Cicada Test")
    markdown_parser.write(memory / "entities" / "a-link.md", {"name": "A link", "type": "media", "media": LINK},
                          "## Summary\nA saved page.\n")
    markdown_parser.write(memory / "entities" / "a-paper.md", {"name": "A paper", "type": "media", "media": PAPER},
                          "## Summary\nA paper.\n")
    markdown_parser.write(memory / "entities" / "alpha-project.md", {"name": "Alpha", "type": "project"},
                          "## Summary\nA project.\n")
    media_ingestor.save_url_index(memory, {
        "aaaaaaaaaaaa": {"url": LINK["url"], "media_entity_id": "a-link", "title": "A link", "media_type": "url",
                         "thumbnail": LINK["thumbnail"], "saved_at": LINK["saved_at"]},
        "bbbbbbbbbbbb": {"url": PAPER["url"], "media_entity_id": "a-paper", "title": "A paper", "media_type": "url",
                         "saved_at": PAPER["saved_at"]}})
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    graph_builder._CACHE.update({"key": None, "value": None})
    with TestClient(main.app) as c:
        yield c, memory
    config.get_settings.cache_clear()


def test_the_preview_is_fetched_once_then_served_from_the_store(client, monkeypatch):
    c, _ = client
    asked = []

    async def fake_get(url):
        asked.append(url)
        return media_preview.Fetched(200, png(), "image/png")

    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    monkeypatch.setattr(media_preview, "_http_get", fake_get)
    first = c.get("/entities/a-link/preview")
    assert first.status_code == 200 and first.headers["content-type"] == "image/png" and first.content == png()
    again = c.get("/entities/a-link/preview", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert c.get("/entities/a-link/preview").content == png()
    assert asked == ["https://cdn.example.com/a.png"]


def test_the_picture_gate_off_means_no_fetch_and_a_404(client, monkeypatch):
    c, _ = client

    async def boom(url):
        raise AssertionError("fetched with the gate off")

    monkeypatch.setattr(media_preview, "_http_get", boom)
    assert c.get("/entities/a-link/preview").status_code == 404
    assert c.get("/entities/a-paper/preview").status_code == 404
    assert c.get("/entities/nobody/preview").status_code == 404


def test_the_wire_carries_the_stored_path_never_the_provider_url(client):
    c, _ = client
    key = media_preview.Source("image", LINK["thumbnail"]).key
    path = f"/entities/a-link/preview?v={key}"
    entity = c.get("/entities/a-link").json()
    assert entity["picture"] == path and entity["pictureSource"] == "thumbnail"
    assert entity["media"]["preview"] == path
    assert entity["pictureInputs"]["thumbnail"] == key
    item = next(i for i in c.get("/sources").json()["items"] if i["mediaEntityId"] == "a-link")
    assert item["preview"] == path
    node = next(n for n in c.get("/graph").json()["nodes"] if n["id"] == "a-link")
    assert node["picture"] == path
    # A paper has no fetched preview (G133): its picture is the person's own PDF, or none.
    assert c.get("/entities/a-paper").json()["media"].get("preview") is None


def test_the_persons_pdf_becomes_the_papers_picture(client, monkeypatch):
    c, bank = client
    seen = []

    def fake_render(data, **_):
        seen.append(data)
        return png(48, 64)

    monkeypatch.setattr(pdf_page, "render_first_page", fake_render)
    got = c.post("/entities/a-paper/picture/pdf", files={"file": ("paper.pdf", b"%PDF-1.7 a paper", "application/pdf")})
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["pictureSource"] == "upload" and body["picture"].startswith("/entities/a-paper/picture?v=")
    assert seen == [b"%PDF-1.7 a paper"]
    assert (bank / "assets" / "pictures" / "a-paper.png").read_bytes() == png(48, 64)
    assert "Cicada-Author: user" in _git(bank, "log", "-1", "--format=%B")
    # The Feed row and the media block draw the person's own picture.
    item = next(i for i in c.get("/sources").json()["items"] if i["mediaEntityId"] == "a-paper")
    assert item["preview"] == body["picture"]
    assert c.get(body["picture"]).content == png(48, 64)


def test_a_pdf_upload_refuses_what_it_cannot_draw(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(pdf_page, "render_first_page", lambda data, **_: None)
    post = lambda eid, data: c.post(f"/entities/{eid}/picture/pdf", files={"file": ("x.pdf", data, "application/pdf")})
    assert post("a-paper", b"not a pdf").status_code == 400
    assert post("alpha-project", b"%PDF-1.7").status_code == 400
    assert post("a-paper", b"%PDF-1.7 broken").status_code == 422
    assert post("nobody", b"%PDF-1.7").status_code == 404


def test_a_pdf_picture_is_refused_while_sleep_writes_and_nothing_is_kept(client, monkeypatch):
    from types import SimpleNamespace

    from api.services import sleep_cycle

    c, bank = client
    monkeypatch.setattr(pdf_page, "render_first_page", lambda data, **_: png(48, 64))
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    got = c.post("/entities/a-paper/picture/pdf", files={"file": ("p.pdf", b"%PDF-1.7 x", "application/pdf")})
    assert got.status_code == 409 and "Sleep" in got.json()["detail"]
    assert not (bank / "assets" / "pictures" / "a-paper.png").exists()
