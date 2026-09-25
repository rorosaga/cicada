"""GET /sources hides what the person removed and what enrichment retired
(Track P, recent-work #4 and #14a; test gap 6).

G129 slice 2's `remove` ARCHIVES the media entity — `inbox_service.py:962`
sets `status: "archived"`, it never deletes — but `list_sources` passed
`status` straight through into `MediaSourceItem` and no client filtered it, so
the row was still there on the next render and the answer read as ignored.
`link_enrichment` likewise stamps `enrichment_status: "junk"` on consent and
login interstitials (`link_enrichment.py:886`) and the only readers were the
enrichment scan itself and `link_recon` — no read path filtered it, so a
retired interstitial kept a Feed row.

Hermetic: a synthetic bank, no network, no LLM.
"""
from __future__ import annotations

import json
import os
import time

from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser

BASE = {"type": "media", "confidence": 0.7, "created": "2026-09-01",
        "last_referenced": "2026-09-01", "tags": ["bookmark"]}


def _client(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "sources").mkdir()
    rows = {
        "h1": ("media-kept", "https://example.com/kept", "Kept"),
        "h2": ("media-removed", "https://example.com/removed", "Removed"),
        "h3": ("media-dropped", "https://example.com/dropped", "Dropped"),
        "h4": ("media-consent", "https://example.com/consent", "Before you continue"),
        "h5": ("media-orphan", "https://example.com/orphan", "No page at all"),
    }
    (memory / "sources" / "url_index.json").write_text(json.dumps({
        h: {"url": url, "title": title, "media_type": "bookmark",
            "media_entity_id": eid, "saved_at": f"2026-09-0{i + 1}T00:00:00+00:00"}
        for i, (h, (eid, url, title)) in enumerate(rows.items())
    }))
    for eid, status, extra in [
        ("media-kept", "active", {}),
        ("media-removed", "archived", {}),
        ("media-dropped", "dropped", {}),
        ("media-consent", "active", {"enrichment_status": "junk"}),
    ]:
        markdown_parser.write(
            memory / "entities" / f"{eid}.md",
            {**BASE, "name": eid, "status": status, **extra,
             "media": {"url": f"https://example.com/{eid}", "media_type": "bookmark"}},
            "## Summary\nSaved.",
        )
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def test_archived_dropped_and_junk_never_reach_the_feed(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    body = client.get("/sources").json()
    ids = [r["mediaEntityId"] for r in body["items"]]
    assert "media-kept" in ids
    assert "media-removed" not in ids, "a bookmark resolved as `remove` is archived — it must stop rendering"
    assert "media-dropped" not in ids
    assert "media-consent" not in ids, "a consent interstitial is retired, not content"
    # An index entry with no page at all is NOT a removal — nothing said to
    # hide it, and hiding it would silently drop every pre-enrichment save.
    assert "media-orphan" in ids
    assert body["total"] == len(body["items"]) == 2
    config.get_settings.cache_clear()


def test_the_existing_etag_already_covers_a_status_flip(tmp_path, monkeypatch):
    """ETag ship-together: `etag_for(..., "sources", "episodes", "entities")`
    already moves when a media page is edited in place, so hiding a row needs
    no widening — proven here rather than assumed."""
    client, memory = _client(tmp_path, monkeypatch)
    first = client.get("/sources")
    etag = first.headers["ETag"]
    assert client.get("/sources", headers={"If-None-Match": etag}).status_code == 304
    page = memory / "entities" / "media-kept.md"
    parsed = markdown_parser.parse(page)
    parsed.frontmatter["status"] = "archived"
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    # `entities` is a max-FILE-mtime component: a rewrite inside the same
    # coarse tick yields an identical ETag. Same bump `test_sources_about.py`
    # uses for the same reason — not a sleep.
    later = time.time() + 2
    os.utime(page, (later, later))
    after = client.get("/sources", headers={"If-None-Match": etag})
    assert after.status_code == 200
    assert [r["mediaEntityId"] for r in after.json()["items"]] == ["media-orphan"]
    config.get_settings.cache_clear()
