"""TDD coverage for G11 backend stream — structured ``media`` block on EntityResponse.

The media-preview frontend (EntityDetailCard) works off ``GET /entities/{id}``.
M4's ``write_media_entity`` stores a nested ``media:`` frontmatter block, but the
``get_entity`` handler previously dropped it. These tests pin the contract:

* a ``type: media`` entity → ``EntityResponse.media`` is a populated ``EntityMedia``
  block (url / mediaType / site / channel / thumbnail / description), camelCase on
  the wire;
* a normal entity → ``media`` is ``None`` (backward-compatible default);
* a media entity whose frontmatter omits optional keys still yields a block with
  ``None`` for the missing optionals (no crash, no key invented).

Hermetic: every test builds a throwaway memory workspace in a tmp dir and points
``CICADA_MEMORY_PATH`` at it. No git init is needed — ``get_entity_history``
degrades to ``[]`` on a non-repo. The live ``memory/`` is never touched.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser


def _make_client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app), memory


def _write_media_entity(memory: Path, eid: str, media: dict, body: str = "## Summary\n\nA saved thing.") -> None:
    fm = {
        "name": "Cool Video",
        "type": "media",
        "status": "active",
        "confidence": 0.7,
        "created": "2026-06-01",
        "last_referenced": "2026-06-01",
        "decay_rate": 0.03,
        "source_episodes": ["ep_2026-06-01_001"],
        "tags": ["youtube"],
        "related": [],
        "version": 1,
        "media": media,
    }
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, body)


_FULL_MEDIA = {
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "media_type": "youtube",
    "site": "YouTube",
    "channel": "Some Channel",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "saved_at": "2026-06-01T10:00:00Z",
    "url_hash": "abc123",
}


def test_media_entity_exposes_structured_media_block(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)
    _write_media_entity(memory, "media-cool-video", _FULL_MEDIA)

    resp = client.get("/entities/media-cool-video")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # camelCase on the wire.
    media = body["media"]
    assert media is not None
    assert media["url"] == _FULL_MEDIA["url"]
    assert media["mediaType"] == "youtube"
    assert media["site"] == "YouTube"
    assert media["channel"] == "Some Channel"
    assert media["thumbnail"] == _FULL_MEDIA["thumbnail"]


def test_media_block_description_comes_from_body_summary(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)
    _write_media_entity(
        memory,
        "media-cool-video",
        _FULL_MEDIA,
        body="## Summary\n\nThe greatest video ever recorded.\n\n## Notes\n\nignore me",
    )

    resp = client.get("/entities/media-cool-video")
    assert resp.status_code == 200, resp.text
    media = resp.json()["media"]
    assert media["description"] == "The greatest video ever recorded."


def test_normal_entity_has_null_media(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)
    fm = {
        "name": "FastAPI",
        "type": "tool",
        "status": "active",
        "confidence": 0.9,
        "created": "2026-06-01",
        "last_referenced": "2026-06-01",
        "decay_rate": 0.05,
        "source_episodes": [],
        "tags": [],
        "related": [],
        "version": 1,
    }
    markdown_parser.write(memory / "entities" / "fastapi.md", fm, "## Summary\n\nA web framework.")

    resp = client.get("/entities/fastapi")
    assert resp.status_code == 200, resp.text
    assert resp.json()["media"] is None


def test_media_block_tolerates_missing_optionals(tmp_path, monkeypatch):
    client, memory = _make_client(tmp_path, monkeypatch)
    # Only a url + media_type present (e.g. a bare bookmark with no OG metadata).
    _write_media_entity(
        memory,
        "media-bare-link",
        {"url": "https://example.com/post", "media_type": "url"},
        body="(no summary heading here)",
    )

    resp = client.get("/entities/media-bare-link")
    assert resp.status_code == 200, resp.text
    media = resp.json()["media"]
    assert media is not None
    assert media["url"] == "https://example.com/post"
    assert media["mediaType"] == "url"
    assert media["site"] is None
    assert media["channel"] is None
    assert media["thumbnail"] is None
    # No "## Summary" heading -> no description.
    assert media["description"] is None


def test_media_block_absent_when_type_media_but_no_block(tmp_path, monkeypatch):
    """Defensive: a ``type: media`` entity missing its ``media:`` frontmatter
    must not crash; ``media`` is simply ``None``."""
    client, memory = _make_client(tmp_path, monkeypatch)
    fm = {
        "name": "Orphan Media",
        "type": "media",
        "status": "active",
        "confidence": 0.7,
        "created": "2026-06-01",
        "last_referenced": "2026-06-01",
        "decay_rate": 0.03,
        "source_episodes": [],
        "tags": [],
        "related": [],
        "version": 1,
    }
    markdown_parser.write(memory / "entities" / "media-orphan.md", fm, "## Summary\n\nhi")

    resp = client.get("/entities/media-orphan")
    assert resp.status_code == 200, resp.text
    assert resp.json()["media"] is None
