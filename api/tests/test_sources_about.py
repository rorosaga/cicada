"""GET /sources carries the link's description excerpt and its `about`
neighbours (G102 R12), read from the page the endpoint already parses; and the
existing ETag (`entities` = max FILE mtime) already invalidates on an in-place
media-page edit, so no widening is needed — proven here, not assumed."""
from __future__ import annotations

import json
import os
import time

from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "sources").mkdir()
    (memory / "sources" / "url_index.json").write_text(json.dumps({
        "h1": {"url": "https://example.com/rich", "title": "Rich", "media_type": "bookmark",
               "media_entity_id": "media-rich", "saved_at": "2026-01-01T00:00:00+00:00"},
        "h2": {"url": "https://example.com/bare", "title": "Bare", "media_type": "bookmark",
               "media_entity_id": "media-bare", "saved_at": "2026-01-02T00:00:00+00:00"},
    }))
    long_desc = "Word " * 100
    base = {"type": "media", "status": "active", "confidence": 0.7, "created": "2026-01-01",
            "last_referenced": "2026-01-01", "tags": ["bookmark"]}
    markdown_parser.write(memory / "entities" / "media-rich.md",
                          {**base, "name": "Rich", "related": ["ros", "knowledge-graphs"],
                           "media": {"url": "https://example.com/rich", "media_type": "bookmark"}},
                          f"## Summary\nSaved.\n\n## Description\n{long_desc.strip()}")
    markdown_parser.write(memory / "entities" / "media-bare.md",
                          {**base, "name": "Bare", "related": [],
                           "media": {"url": "https://example.com/bare", "media_type": "bookmark"}},
                          "## Summary\nSaved.")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_sources_rows_carry_description_excerpt_and_about(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    rows = {r["mediaEntityId"]: r for r in client.get("/sources").json()["items"]}
    rich, bare = rows["media-rich"], rows["media-bare"]
    assert rich["about"] == ["ros", "knowledge-graphs"] and rich["relatedCount"] == 2
    assert rich["description"].endswith("…") and len(rich["description"]) <= 281
    assert not rich["description"].endswith(" …")   # cut at a word boundary
    assert bare["description"] is None and bare["about"] == []
    config.get_settings.cache_clear()


def test_in_place_edit_of_a_media_page_changes_the_sources_etag(tmp_path, monkeypatch):
    client, memory = _client(tmp_path, monkeypatch)
    first = client.get("/sources")
    etag = first.headers["ETag"]
    assert client.get("/sources", headers={"If-None-Match": etag}).status_code == 304
    fp = memory / "entities" / "media-bare.md"
    parsed = markdown_parser.parse(fp)
    parsed.frontmatter["related"] = ["ros"]
    markdown_parser.write(fp, parsed.frontmatter, parsed.body + "\n\n## Description\nNow described.")
    later = time.time() + 2
    os.utime(fp, (later, later))
    resp = client.get("/sources", headers={"If-None-Match": etag})
    assert resp.status_code == 200 and resp.headers["ETag"] != etag
    bare = [r for r in resp.json()["items"] if r["mediaEntityId"] == "media-bare"][0]
    assert bare["description"] == "Now described." and bare["about"] == ["ros"]
    config.get_settings.cache_clear()
