"""Hermetic tests for the keyless browser-bookmark sync connector.

Covers:
- ``read_chrome_bookmarks`` — Chrome's ``Bookmarks`` JSON tree (nested
  folders, 2 leaf urls, folders skipped);
- ``sync_bookmarks`` — the diff/dedup summary shape, with an injected
  ``ingest_fn`` so no real enrichment/network/filesystem write happens;
- ``read_chrome_bookmarks`` degrading to ``[]`` on malformed bytes;
- a Safari plist fixture flowing through ``sync_bookmarks`` via the existing
  ``parse_safari_bookmarks``;
- the ``POST /sources/sync-bookmarks`` endpoint via ``TestClient`` with
  inline base64 data (no real bookmark files touched).

No live network, no live filesystem (the real
``~/Library/.../Bookmarks``/``Bookmarks.plist`` are never read — every test
either calls ``read_chrome_bookmarks``/``sync_bookmarks`` directly with
in-memory bytes, or hits the endpoint with inline base64).
"""

from __future__ import annotations

import base64
import json
import plistlib

from api.services import bookmark_sync
from api.services.media_ingestor import RawItem

# --- Fixtures ----------------------------------------------------------------

CHROME_BOOKMARKS_JSON = {
    "version": 1,
    "roots": {
        "bookmark_bar": {
            "type": "folder",
            "name": "Bookmarks bar",
            "children": [
                {
                    "type": "folder",
                    "name": "Reading",
                    "children": [
                        {
                            "type": "url",
                            "name": "Example One",
                            "url": "https://example.com/one",
                            "date_added": "13300000000000000",
                        },
                    ],
                },
                {
                    "type": "url",
                    "name": "Example Two",
                    "url": "https://example.com/two",
                },
            ],
        },
        "other": {
            "type": "folder",
            "name": "Other bookmarks",
            "children": [],
        },
    },
}

SAFARI_PLIST_TREE = {
    "Title": "",
    "WebBookmarkType": "WebBookmarkTypeList",
    "Children": [
        {
            "WebBookmarkType": "WebBookmarkTypeList",
            "Title": "Reading List",
            "Children": [
                {
                    "WebBookmarkType": "WebBookmarkTypeLeaf",
                    "URLString": "https://example.org/a",
                    "URIDictionary": {"title": "Page A"},
                },
                {
                    "WebBookmarkType": "WebBookmarkTypeLeaf",
                    "URLString": "https://example.org/b",
                    "URIDictionary": {"title": "Page B"},
                },
            ],
        },
    ],
}


def run(coro):
    import asyncio

    return asyncio.run(coro)


# --- read_chrome_bookmarks ---------------------------------------------------


def test_read_chrome_bookmarks_extracts_urls_skips_folders():
    data = json.dumps(CHROME_BOOKMARKS_JSON).encode("utf-8")
    items = bookmark_sync.read_chrome_bookmarks(data)

    assert len(items) == 2
    assert all(isinstance(i, RawItem) for i in items)
    urls = {i.url for i in items}
    assert urls == {"https://example.com/one", "https://example.com/two"}
    titles = {i.title for i in items}
    assert titles == {"Example One", "Example Two"}
    # Folder names ("Reading", "Bookmarks bar", "Other bookmarks") never
    # surface as items.
    assert "Reading" not in urls


def test_read_chrome_bookmarks_malformed_bytes_returns_empty():
    assert bookmark_sync.read_chrome_bookmarks(b"not json at all") == []
    assert bookmark_sync.read_chrome_bookmarks(b"") == []
    assert bookmark_sync.read_chrome_bookmarks(b"[1, 2, 3]") == []  # valid JSON, wrong shape


# --- sync_bookmarks: diff/dedup summary --------------------------------------


def test_sync_bookmarks_reports_new_and_skipped_via_injected_ingest_fn(tmp_path):
    data = json.dumps(CHROME_BOOKMARKS_JSON).encode("utf-8")

    calls = []

    async def fake_ingest_fn(items, memory_path, from_bookmark_file=False, **kwargs):
        calls.append((list(items), memory_path, from_bookmark_file))
        # Simulate: 2 items in, 1 already in the url_index -> 1 new, 1 dup.
        return 1, 1

    result = run(
        bookmark_sync.sync_bookmarks(
            tmp_path / "memory", chrome_data=data, ingest_fn=fake_ingest_fn
        )
    )

    assert result == {
        "new": 1,
        "skipped": 1,
        "sources": [
            {"origin": "chrome-bookmark", "found": 2, "new": 1, "skipped": 1},
        ],
    }
    # The injected fn was actually invoked with the parsed items, tagged with
    # their origin, and from_bookmark_file=True (bookmark, not raw url paste).
    assert len(calls) == 1
    items, memory_path, from_bookmark_file = calls[0]
    assert len(items) == 2
    assert from_bookmark_file is True
    assert all("chrome-bookmark" in i.tags for i in items)


def test_sync_bookmarks_no_data_provided_ingests_nothing(tmp_path):
    async def unreachable(*args, **kwargs):
        raise AssertionError("ingest_fn must not be called when no data is supplied")

    result = run(bookmark_sync.sync_bookmarks(tmp_path / "memory", ingest_fn=unreachable))
    assert result == {"new": 0, "skipped": 0, "sources": []}


def test_sync_bookmarks_safari_fixture_flows_through(tmp_path):
    data = plistlib.dumps(SAFARI_PLIST_TREE)

    async def fake_ingest_fn(items, memory_path, from_bookmark_file=False, **kwargs):
        return len(items), 0

    result = run(
        bookmark_sync.sync_bookmarks(
            tmp_path / "memory", safari_data=data, ingest_fn=fake_ingest_fn
        )
    )

    assert result["new"] == 2
    assert result["skipped"] == 0
    assert result["sources"] == [
        {"origin": "safari-bookmark", "found": 2, "new": 2, "skipped": 0},
    ]


def test_sync_bookmarks_both_sources_aggregate(tmp_path):
    chrome_data = json.dumps(CHROME_BOOKMARKS_JSON).encode("utf-8")
    safari_data = plistlib.dumps(SAFARI_PLIST_TREE)

    async def fake_ingest_fn(items, memory_path, from_bookmark_file=False, **kwargs):
        return len(items), 0

    result = run(
        bookmark_sync.sync_bookmarks(
            tmp_path / "memory",
            chrome_data=chrome_data,
            safari_data=safari_data,
            ingest_fn=fake_ingest_fn,
        )
    )

    assert result["new"] == 4  # 2 chrome + 2 safari
    assert result["skipped"] == 0
    origins = {s["origin"] for s in result["sources"]}
    assert origins == {"chrome-bookmark", "safari-bookmark"}


# --- sync_from_local_files: never touches real files in tests ---------------


def test_sync_from_local_files_missing_files_returns_zero(tmp_path, monkeypatch):
    # Point both "standard locations" at nonexistent paths so this stays
    # hermetic even if it somehow ran on a machine with real bookmark files.
    monkeypatch.setattr(
        bookmark_sync, "chrome_bookmarks_path", lambda: tmp_path / "no-chrome-bookmarks"
    )
    monkeypatch.setattr(
        bookmark_sync, "safari_bookmarks_path", lambda: tmp_path / "no-safari-bookmarks.plist"
    )

    result = run(bookmark_sync.sync_from_local_files(tmp_path / "memory"))
    assert result == {"new": 0, "skipped": 0, "sources": []}


def test_sync_from_local_files_reads_present_fixture_files(tmp_path, monkeypatch):
    chrome_path = tmp_path / "Bookmarks"
    chrome_path.write_bytes(json.dumps(CHROME_BOOKMARKS_JSON).encode("utf-8"))
    safari_path = tmp_path / "Bookmarks.plist"
    safari_path.write_bytes(b"\x00\x01 not a real plist")  # degrades to [] safely

    monkeypatch.setattr(bookmark_sync, "chrome_bookmarks_path", lambda: chrome_path)
    monkeypatch.setattr(bookmark_sync, "safari_bookmarks_path", lambda: safari_path)

    async def fake_ingest_batch(items, memory_path, from_bookmark_file=False, **kwargs):
        return len(items), 0

    monkeypatch.setattr(bookmark_sync.media_ingestor, "ingest_batch", fake_ingest_batch)

    result = run(bookmark_sync.sync_from_local_files(tmp_path / "memory"))
    assert result["new"] == 2  # 2 chrome urls; safari plist is malformed -> [] items, 0 found
    assert any(s["origin"] == "chrome-bookmark" for s in result["sources"])


# --- POST /sources/sync-bookmarks endpoint -----------------------------------


def _make_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main

    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def _offline_enrich(monkeypatch):
    """Force enrichment offline (URL-only fallback) so no network happens."""
    from api.services import media_ingestor

    async def fake_enrich(url, client, from_bookmark_file=False):
        from api.services.media_ingestor import MediaMeta, _classify, _fallback_title, _site_of

        return MediaMeta(
            title=_fallback_title(url),
            description="",
            site=_site_of(url),
            media_type=_classify(url, from_bookmark_file=from_bookmark_file),
        )

    monkeypatch.setattr(media_ingestor, "enrich", fake_enrich)


def test_sync_bookmarks_endpoint_inline_chrome_data(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    client, memory = _make_client(tmp_path, monkeypatch)

    chrome_b64 = base64.b64encode(json.dumps(CHROME_BOOKMARKS_JSON).encode("utf-8")).decode()
    resp = client.post("/sources/sync-bookmarks", json={"chromeDataB64": chrome_b64})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new"] == 2
    assert body["skipped"] == 0
    assert body["sources"][0]["origin"] == "chrome-bookmark"

    # Second sync with identical data -> everything already in url_index.
    resp2 = client.post("/sources/sync-bookmarks", json={"chromeDataB64": chrome_b64})
    body2 = resp2.json()
    assert body2["new"] == 0
    assert body2["skipped"] == 2


def test_sync_bookmarks_endpoint_inline_safari_data(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    client, memory = _make_client(tmp_path, monkeypatch)

    safari_b64 = base64.b64encode(plistlib.dumps(SAFARI_PLIST_TREE)).decode()
    resp = client.post("/sources/sync-bookmarks", json={"safariDataB64": safari_b64})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new"] == 2
    assert body["sources"][0]["origin"] == "safari-bookmark"


def test_sync_bookmarks_endpoint_no_body_reads_local_files_best_effort(tmp_path, monkeypatch):
    """No body -> falls back to sync_from_local_files, which must never touch
    the real filesystem or raise in this hermetic environment (missing files
    on the test machine simply yield an empty sync)."""
    _offline_enrich(monkeypatch)
    client, memory = _make_client(tmp_path, monkeypatch)

    from api.services import bookmark_sync as bs

    monkeypatch.setattr(bs, "chrome_bookmarks_path", lambda: tmp_path / "absent-chrome")
    monkeypatch.setattr(bs, "safari_bookmarks_path", lambda: tmp_path / "absent-safari.plist")

    resp = client.post("/sources/sync-bookmarks")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"new": 0, "skipped": 0, "sources": []}


def test_sync_bookmarks_endpoint_invalid_base64_rejected(tmp_path, monkeypatch):
    _offline_enrich(monkeypatch)
    client, memory = _make_client(tmp_path, monkeypatch)

    resp = client.post("/sources/sync-bookmarks", json={"chromeDataB64": "!!! not base64 !!!"})
    assert resp.status_code == 422
