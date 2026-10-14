"""Shared fixtures for the G166 exploring tests — never collected (underscore prefix).

A synthetic bank with saved links written the way `media_ingestor` writes them (a media page, the link's episode with
its `origin`, and a `sources/url_index.json` row), the person's reading settings in the scratch `CICADA_HOME`, and
made-up screenshots drawn by `demo_pictures.website`. Placeholders only: bob-example.org hosts (an `example` label reads as a local name to reading_hosts), alpha-project, bob-example.
Nothing reads a real bank, `~/.cicada` or the network."""
from __future__ import annotations

import json
from pathlib import Path

from _synthetic_bank import _bank
from api.services import bank_index, demo_pictures, markdown_parser, media_ingestor, reading_settings

DARK = demo_pictures.website((20, 22, 28), (29, 32, 41), (226, 230, 240), (124, 156, 255), width=1440, height=900)
LIGHT = demo_pictures.website((255, 255, 255), (242, 244, 255), (17, 24, 39), (59, 91, 253), width=1440, height=900,
                              dense=True)


def add_site(memory: Path, slug: str, *, url: str | None = None, title: str | None = None,
             origin: str | None = "chrome-bookmark", why: dict | None = None, status: str = "active",
             n: int = 1) -> str:
    """One saved link: its media page, its episode and its index row. Returns the url-index key."""
    url = url or f"https://{slug}.bob-example.org/"
    title = title or f"Site {slug}"
    eid = f"media-{slug}"
    fm = {"name": title, "type": "media", "status": status, "confidence": 0.7, "created": "2026-09-20",
          "last_referenced": "2026-09-20", "decay_class": "evergreen", "source_episodes": [], "tags": [],
          "related": [], "version": 1,
          "media": {"url": url, "media_type": "url", "site": slug, "url_hash": media_ingestor.url_hash(url)}}
    markdown_parser.write(memory / "entities" / f"{eid}.md", fm, "## Summary\nA saved link.")
    ep = f"ep_2026-09-{20 + n % 9:02d}_{n:03d}"
    efm = {"id": ep, "timestamp": "2026-09-20T10:00:00+00:00", "source": "url", "title": title, "processed": True,
           "url": url, "media_entity_id": eid, "folder": "Bookmarks bar/Design", "saved_at": "2026-03-02"}
    if origin:
        efm["origin"] = origin
    if why:
        efm["saved_why"] = why
    markdown_parser.write(memory / "episodes" / f"{ep}.md", efm, f"Saved {url}")
    idx = media_ingestor.load_url_index(memory)
    key = media_ingestor.url_hash(url)
    idx[key] = {"media_entity_id": eid, "episode_id": ep, "url": url, "title": title, "media_type": "url",
                "thumbnail": None, "saved_at": "2026-09-20T10:00:00+00:00", "content_saved_at": "2026-03-02"}
    media_ingestor.save_url_index(memory, idx)
    bank_index.invalidate(memory)
    return key


def bank_with_sites(tmp_path: Path, count: int = 3, **kw) -> tuple[Path, list[str]]:
    memory = _bank(tmp_path)
    keys = [add_site(memory, f"site{i:02d}", n=i + 1, **kw) for i in range(count)]
    return memory, keys


def enable_reading(*, signed_in: bool = True, sites: dict | None = None, never: dict | None = None) -> None:
    """The person turned on "Let an agent read pages for you" and read the current sheet."""
    data = {"agent": True, "agent_ack": {"date": "2026-10-14", "v": reading_settings.ACK_VERSION}}
    if not signed_in:
        data["explore_signed_in"] = False
    if sites:
        data["agent_sites"] = sites
    if never:
        data["never_explore"] = never
    reading_settings.path().parent.mkdir(parents=True, exist_ok=True)
    reading_settings.path().write_text(json.dumps(data), encoding="utf-8")
