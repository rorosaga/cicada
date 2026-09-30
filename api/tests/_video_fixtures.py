"""Shared fixtures for the G162 video tests — never collected (underscore prefix).

A synthetic bank with saved videos written the way `media_ingestor` writes them (a
page with a `media:` block and a `sources/url_index.json` row), plus watch episodes
written straight into `episodes/` in the shape `watch_record` writes, so the state and
queue tests need no network and no MCP round trip. Placeholders only: example.com,
alpha-project, bob-example."""
from __future__ import annotations

from pathlib import Path

from _synthetic_bank import _bank
from api.services import bank_index, markdown_parser, media_ingestor

YOUTUBE = "https://www.youtube.com/watch?v={id}"


def add_video(memory: Path, slug: str, *, url: str | None = None, title: str | None = None,
              channel: str | None = "alpha-project", media_type: str = "youtube", status: str = "active",
              kind: str | None = None, enrichment_status: str | None = None, duration_s: int | None = None,
              alias_of: str | None = None) -> str:
    """Save one media page and its index row; returns the url-index key. ``url`` defaults to
    a YouTube link derived from ``slug`` (so each slug is a distinct video)."""
    url = url or YOUTUBE.format(id=f"vid{slug}")
    title = title or f"Video {slug}"
    eid = f"media-{slug}"
    media = {"url": url, "media_type": media_type, "site": "example.com", "channel": channel, "thumbnail": None,
             "saved_at": "2026-09-20T10:00:00+00:00", "url_hash": media_ingestor.url_hash(url)}
    if kind:
        media["kind"] = kind
    if duration_s:
        media["duration_s"] = duration_s
    fm = {"name": title, "type": "media", "status": status, "confidence": 0.7, "created": "2026-09-20",
          "last_referenced": "2026-09-20", "decay_class": "evergreen", "source_episodes": [], "tags": [],
          "related": [], "version": 1, "media": media}
    if enrichment_status:
        fm["enrichment_status"] = enrichment_status
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, f"## Summary\nSaved {media_type}.")
    idx = media_ingestor.load_url_index(memory)
    key = media_ingestor.url_hash(url)
    entry = {"media_entity_id": eid, "episode_id": "", "url": url, "title": title, "media_type": media_type,
             "thumbnail": None, "saved_at": "2026-09-20T10:00:00+00:00"}
    if alias_of:
        entry["alias_of"] = alias_of
    idx[key] = entry
    media_ingestor.save_url_index(memory, idx)
    bank_index.invalidate(memory)
    return key


def add_watch_episode(memory: Path, url: str, *, basis: str | None = None, engine: str | None = None,
                      n: int = 1, day: str = "2026-09-28", harness: str | None = "claude-code",
                      processed: bool = False, processed_by: str | None = None, source: str = "video-watch",
                      timestamp: str | None = None, entity_id: str | None = None) -> str:
    """Write one episode in `watch_record`'s frontmatter shape."""
    ep = f"ep_{day}_{n:03d}"
    fm = {"id": ep, "timestamp": timestamp or f"{day}T14:31:07+00:00", "source": source, "origin": "mcp",
          "title": "Watched: a video", "processed": processed, "content_hash": f"h{n:011d}", "url": url,
          "media_entity_id": entity_id or "media-x"}
    if harness:
        fm["harness"] = harness
    if basis:
        fm["watch_basis"] = basis
    if engine:
        fm["watch_engine"] = engine
    if processed_by:
        fm["processed_by"] = processed_by
    markdown_parser.write(memory / "episodes" / f"{ep}.md", fm, "assistant: A summary.")
    bank_index.invalidate(memory)
    return ep


def bank_with_videos(tmp_path: Path, count: int = 3) -> tuple[Path, list[str]]:
    """A bank with ``count`` saved YouTube videos; returns it and their keys."""
    memory = _bank(tmp_path)
    keys = [add_video(memory, f"{i:02d}") for i in range(count)]
    return memory, keys


def url_of(slug: str) -> str:
    return YOUTUBE.format(id=f"vid{slug}")
