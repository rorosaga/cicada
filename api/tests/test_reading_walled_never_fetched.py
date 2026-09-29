"""G166 R-RW4 — the backend never requests a login-walled page: X, Facebook,
LinkedIn, Instagram, Reddit and `t.co` (and TikTok's page; its provider oEmbed
branch is unchanged). The proof is the call list of an injected client, the
house pattern (`test_video_enrichment.py`): the fake is NEVER called."""
from __future__ import annotations

import asyncio

import pytest

from api.services import link_enrichment, media_ingestor

WALLED = [
    "https://x.com/alpha/status/1",
    "https://twitter.com/alpha/status/1",
    "https://www.facebook.com/alpha/posts/1",
    "https://www.linkedin.com/in/alpha",
    "https://www.instagram.com/p/abc/",
    "https://www.reddit.com/r/alpha/comments/abc/",
    "https://t.co/abc",
    "https://lnkd.in/abc",
]


class Client:
    def __init__(self):
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        raise AssertionError(f"the backend requested a walled page: {url}")


@pytest.mark.parametrize("url", WALLED)
def test_enrich_never_touches_the_client_for_a_walled_host(url):
    client = Client()
    meta = asyncio.run(media_ingestor.enrich(url, client))
    assert client.calls == []
    assert meta.title == media_ingestor._fallback_title(url) and meta.description == ""


@pytest.mark.parametrize("url", WALLED + ["https://www.tiktok.com/@alpha"])
def test_the_backfill_and_recon_exclude_walled_hosts(url):
    assert link_enrichment._excluded_media(url, "url") is True


def test_a_public_host_is_still_read():
    """The rule closes one set; it does not stop the reader for everything else."""
    assert link_enrichment._excluded_media("https://blog.bob-example.org/post", "url") is False
    assert link_enrichment._excluded_media("https://notx.com/post", "url") is False


def test_a_deferred_save_of_a_walled_link_makes_no_request_and_no_enrich_call(tmp_path, monkeypatch):
    async def spy(*a, **k):
        raise AssertionError("enrich ran for a deferred save")

    monkeypatch.setattr(media_ingestor, "enrich", spy)
    memory = tmp_path / "memory"
    idx: dict = {}
    item = media_ingestor.RawItem(url="https://x.com/alpha/status/1", origin="saved-link", defer_enrich=True)
    result = asyncio.run(media_ingestor.ingest_one(item, memory, None, idx))
    assert result.status == "created" and result.title == "1"
    assert media_ingestor.url_hash(item.url) in idx
    assert (memory / "entities" / f"{result.media_entity_id}.md").exists()
