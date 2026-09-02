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
from api.services.claims import Claim, write_claims


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "sources").mkdir()
    (memory / "sources" / "url_index.json").write_text(json.dumps({
        "h1": {"url": "https://example.com/rich", "title": "Rich", "media_type": "bookmark",
               "media_entity_id": "media-rich", "saved_at": "2026-01-01T00:00:00+00:00"},
        "h2": {"url": "https://example.com/bare", "title": "Bare", "media_type": "bookmark",
               "media_entity_id": "media-bare", "saved_at": "2026-01-02T00:00:00+00:00"},
        "h3": {"url": "https://example.com/claimed", "title": "Claimed", "media_type": "bookmark",
               "media_entity_id": "media-claimed", "saved_at": "2026-01-03T00:00:00+00:00"},
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
    # The shape every backfilled / `/save <url> <reason>` / recon-touched page
    # has: `## Description` is the last H2 and the ```claims fence follows it.
    blurb = "A short blurb about example topics."
    claimed_body = write_claims(f"## Summary\nSaved.\n\n## Description\n{blurb}", [
        Claim(id="clm_describes_1", text=blurb, subject="media-claimed", predicate="describes",
              object=blurb, object_kind="literal", observer="agent", authored_by="cicada",
              origin="sleep/link_enrichment"),
    ])
    markdown_parser.write(memory / "entities" / "media-claimed.md",
                          {**base, "name": "Claimed", "related": [],
                           "media": {"url": "https://example.com/claimed", "media_type": "bookmark"}},
                          claimed_body)
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


def test_description_excerpt_never_carries_the_claims_block(tmp_path, monkeypatch):
    """Final review H1: `parse_sections` ends a section at the next H2 or EOF
    and knows nothing about the ```claims fence, so a bare read leaked the
    serialized claim YAML into the Feed row (and the preview sheet)."""
    client, _ = _client(tmp_path, monkeypatch)
    rows = {r["mediaEntityId"]: r for r in client.get("/sources").json()["items"]}
    desc = rows["media-claimed"]["description"]
    assert desc == "A short blurb about example topics."
    assert "clm_" not in desc and "observer" not in desc and "```" not in desc
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
