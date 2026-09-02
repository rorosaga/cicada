"""GET /entities/{id}/logo + has_logo on graph nodes (G59).

The graph path must never touch the network: `has_logo` is read from the cache
index only. The endpoint is the only place a fetch can start, and it is bounded
by an in-process semaphore so opening a busy graph can't fan out.
"""

from __future__ import annotations

import asyncio
import os
import struct
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, logo_service


def png_bytes(width: int, height: int) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = tmp_path / "banks" / "work"
    (memory / "entities").mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def write_entity(memory, entity_id, lines, body=""):
    (memory / "entities" / f"{entity_id}.md").write_text(
        "---\n" + "\n".join(lines) + "\n---\n" + body, encoding="utf-8")


def seed_cached_logo(memory, entity_id, domain="acme.example"):
    """Put a real cached hit on disk without any fetch."""
    async def fetcher(url):
        if url.endswith("/apple-touch-icon.png"):
            return logo_service.FetchResult(200, png_bytes(180, 180), "image/png", '"v1"')
        return logo_service.FetchResult(404, b"", "text/html")

    return asyncio.run(logo_service.ensure_logo(memory, entity_id, fetcher=fetcher))


def _touch_after_fetch(path):
    """Bump the page's mtime a second past its cache entry's `fetched_at`."""
    future = datetime.now(timezone.utc).timestamp() + 1
    os.utime(path, (future, future))


def test_logo_404_for_an_unknown_entity(client):
    c, _ = client
    assert c.get("/entities/nope/logo").status_code == 404


def test_logo_404_for_a_person_page(client):
    c, memory = client
    write_entity(memory, "rodrigo", ["name: Rodrigo", "type: person"])
    bank_index.invalidate()
    assert c.get("/entities/rodrigo/logo").status_code == 404


def test_logo_200_then_304_from_the_cache(client):
    c, memory = client
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://acme.example/x.png"])
    assert seed_cached_logo(memory, "acme") is not None
    bank_index.invalidate()

    first = c.get("/entities/acme/logo")
    assert first.status_code == 200, first.text
    assert first.headers["content-type"].startswith("image/png")
    assert first.headers["cache-control"] == "max-age=86400"
    etag = first.headers["etag"]
    assert first.content.startswith(b"\x89PNG")

    again = c.get("/entities/acme/logo", headers={"If-None-Match": etag})
    assert again.status_code == 304


def test_logo_endpoint_re_resolves_an_edited_page_instead_of_shortcutting(client, monkeypatch):
    """D1: the endpoint used to return `cached_path` before `ensure_logo` ever
    ran, so `page_edited_since_fetch` never executed on the real GET path — a
    page edit was invisible to it for up to 30 days. Editing the page to a
    NEW domain must be picked up here too, not just when calling
    `ensure_logo` directly."""
    c, memory = client
    page = memory / "entities" / "acme.md"
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://acme.example/x.png"])
    assert seed_cached_logo(memory, "acme", domain="acme.example") is not None
    bank_index.invalidate()

    first = c.get("/entities/acme/logo")
    assert first.status_code == 200, first.text
    old_bytes = first.content

    # Point the page at a DIFFERENT domain, past the cache entry's mtime, and
    # turn fetching on with a fake HTTP layer so the router's own call can
    # actually revalidate (conftest gates real fetching off for the suite).
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://rebrand.example/x.png"])
    _touch_after_fetch(page)
    bank_index.invalidate()
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")

    async def fake_http_get(url):
        if url == "https://rebrand.example/apple-touch-icon.png":
            return logo_service.FetchResult(200, png_bytes(64, 64), "image/png", '"v2"')
        return logo_service.FetchResult(404, b"", "text/html")

    monkeypatch.setattr(logo_service, "_http_get", fake_http_get)

    second = c.get("/entities/acme/logo")
    assert second.status_code == 200, second.text
    assert second.content != old_bytes, (
        "an edited page's new domain must be re-fetched by the endpoint, not shortcut past"
    )
    assert logo_service.read_meta("work")["acme"]["domain"] == "rebrand.example"


def test_logo_endpoint_keeps_a_stale_revalidation_failure(client, monkeypatch):
    """The M1/M2 fallback behaviour (keep-old-logo-on-failed-revalidation)
    must survive going through the router, not just direct `ensure_logo`
    calls: a page edit whose re-fetch comes up empty must not turn a live
    cache entry into a 404."""
    c, memory = client
    page = memory / "entities" / "acme.md"
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://acme.example/x.png"])
    assert seed_cached_logo(memory, "acme", domain="acme.example") is not None
    bank_index.invalidate()
    old_bytes = c.get("/entities/acme/logo").content

    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://dead.example/x.png"])
    _touch_after_fetch(page)
    bank_index.invalidate()
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")

    async def all_miss(url):
        return logo_service.FetchResult(404, b"", "text/html")

    monkeypatch.setattr(logo_service, "_http_get", all_miss)

    resp = c.get("/entities/acme/logo")
    assert resp.status_code == 200, "a failed revalidation must keep serving the old mark, not 404"
    assert resp.content == old_bytes


def test_graph_nodes_report_has_logo_from_the_cache_only(client):
    c, memory = client
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://acme.example/x.png"])
    write_entity(memory, "widget", ["name: Widget", "type: tool"])
    bank_index.invalidate()

    before = {n["id"]: n for n in c.get("/graph").json()["nodes"]}
    assert before["acme"]["hasLogo"] is False
    assert before["widget"]["hasLogo"] is False

    assert seed_cached_logo(memory, "acme") is not None
    bank_index.invalidate()
    from api.services import graph_builder
    graph_builder._CACHE["key"] = None  # the graph cache keys on mtimes, not the logo cache

    after = {n["id"]: n for n in c.get("/graph").json()["nodes"]}
    assert after["acme"]["hasLogo"] is True
    assert after["widget"]["hasLogo"] is False
    assert after["acme"]["contentHash"] != before["acme"]["contentHash"], (
        "has_logo must move the node's content_hash or the app's delta never repaints it")


def test_graph_never_fetches(client, monkeypatch):
    c, memory = client
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://acme.example/x.png"])
    bank_index.invalidate()

    async def explode(_url):
        raise AssertionError("GET /graph must never fetch a logo")

    monkeypatch.setattr(logo_service, "_http_get", explode)
    assert c.get("/graph").status_code == 200


def test_warming_a_logo_moves_the_graph_etag_and_the_version_vector(client):
    """HIGH-1: the logo cache lives outside the bank, so nothing in `memory/`
    moves when a logo is warmed. Without a `logos` component the app's
    conditional GET 304s forever and the node keeps painting a monogram."""
    c, memory = client
    write_entity(memory, "acme", ["name: Acme", "type: company", "logo: https://acme.example/x.png"])
    bank_index.invalidate()

    first = c.get("/graph")
    etag = first.headers["ETag"]
    assert first.json()["nodes"][0]["hasLogo"] is False
    version = c.get("/sync/version").json()["version"]
    assert c.get("/graph", headers={"If-None-Match": etag}).status_code == 304

    assert seed_cached_logo(memory, "acme") is not None
    # Deliberately no bank_index/graph cache busting: the fix has to work with
    # every cache in place, exactly as it does in the running app.

    after = c.get("/graph", headers={"If-None-Match": etag})
    assert after.status_code == 200, "the warmed logo must invalidate /graph's ETag"
    assert after.headers["ETag"] != etag
    assert after.json()["nodes"][0]["hasLogo"] is True
    assert c.get("/sync/version").json()["version"] != version
    assert "logos" in c.get("/sync/version").json()["components"]
