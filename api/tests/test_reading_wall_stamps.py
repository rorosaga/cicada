"""G166 (ruling 14 amended 2026-09-30, critic H1) — Cicada's own reader records the wall it hit,
wherever it hit it: at save time, in the Sleep cycle's in-cycle pass, and in the tail backfill.

So a site surfaces when its page is walled, not when the capped backfill happens to reach that
page weeks later (or never, with connector fetches off). No new request and no header change:
the one existing request's answer is written down, in the backfill's own vocabulary."""
from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from _reading_fixtures import put_page
from _synthetic_bank import _bank
from api.services import link_enrichment, markdown_parser, media_ingestor, reading_walls

URL = "https://articles.paperfold.io/post/1"


class _Resp:
    def __init__(self, status=200, headers=None, text="", exc=None):
        self.status_code = status
        self.headers = headers if headers is not None else {"content-type": "text/html"}
        self.text = text
        self._exc = exc

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[str] = []
        self.headers_seen: list[dict] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        self.headers_seen.append(dict(kwargs.get("headers") or {}))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    reading_walls.reset_memo()


def _enrich(client, url=URL):
    return asyncio.run(media_ingestor.enrich(url, client))


def test_save_time_wall_stamps_fetch_status():
    for status in (401, 403, 407, 451):
        assert _enrich(_Client(_Resp(status))).fetch_status == "blocked", status
    # a redirect that lands on a login host
    redirect = _Client(_Resp(302, {"location": "https://accounts.google.com/signin"}), _Resp(200, text="<html></html>"))
    assert _enrich(redirect).fetch_status == "blocked"
    # a consent page
    consent = "<html><head><title>Before you continue to the site</title></head><body>cookies</body></html>"
    assert _enrich(_Client(_Resp(200, text=consent))).fetch_status == "interstitial"


def test_a_failure_is_not_a_wall_and_is_not_stamped_at_save_time():
    """A 500 or a timeout is the backfill's to retry sooner than a wall; stamping it would delay that 30 days."""
    for client in (_Client(_Resp(500)), _Client(TimeoutError("slow")), _Client(_Resp(404))):
        assert _enrich(client).fetch_status is None
    ok = "<html><head><title>Fine</title><meta property='og:title' content='Fine'></head><body>hello</body></html>"
    meta = _enrich(_Client(_Resp(200, text=ok)))
    assert meta.fetch_status is None and meta.title == "Fine"


def test_a_saved_sign_in_url_is_not_stamped_blocked_by_the_redirect_rule():
    """Only a redirect ONTO a wall counts here; the saved URL being a login page is wall_kind's business."""
    meta = _enrich(_Client(_Resp(200, text="<html><head><title>Hi</title></head></html>")),
                   url="https://accounts.paperfold.io/login")
    assert meta.fetch_status is None


def test_no_new_request_and_no_header_change():
    client = _Client(_Resp(403))
    _enrich(client)
    assert client.calls == [URL], "the one request already made is all that is read: no retry, no second try"
    assert client.headers_seen[0] == {"User-Agent": media_ingestor.USER_AGENT}


def test_a_wall_stamped_at_save_time_is_a_wall_page_immediately(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    item = media_ingestor.RawItem(url=URL, origin="chrome-bookmark")
    result = asyncio.run(media_ingestor.ingest_one(item, memory, _Client(_Resp(403)), idx))
    media_ingestor.save_url_index(memory, idx)
    fm = markdown_parser.parse(memory / "entities" / f"{result.media_entity_id}.md").frontmatter
    assert fm["fetch_status"] == "blocked" and fm["fetch_attempted_at"] == date.today().isoformat()
    page = reading_walls.scan_one(memory, URL)
    assert page is not None and page.wall == "refused" and page.site == "paperfold.io" and page.waiting
    # an ordinary save leaves no stamp at all (frontmatter byte-identical to before)
    ok = "<html><head><title>Fine</title></head><body>hello</body></html>"
    other = asyncio.run(media_ingestor.ingest_one(
        media_ingestor.RawItem(url="https://blog.paperfold.io/fine"), memory, _Client(_Resp(200, text=ok)), idx))
    fm2 = markdown_parser.parse(memory / "entities" / f"{other.media_entity_id}.md").frontmatter
    assert "fetch_status" not in fm2 and "fetch_attempted_at" not in fm2


def _settings(memory):
    return SimpleNamespace(memory_path=memory, litellm_model="m", llm_mode="byok", link_enrich_enabled=True,
                           link_enrich_max_per_cycle=20, link_enrich_min_desc_len=120,
                           link_enrich_excerpt_chars=2000, link_enrich_backfill_per_cycle=20,
                           link_enrich_fetch_retry_days=30, link_enrich_fetch_min_per_cycle=None)


def test_in_cycle_blocked_fetch_is_stamped(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    put_page(memory, "a", URL)
    put_page(memory, "b", "https://articles.paperfold.io/post/2")

    async def fetch(url, settings):
        return link_enrichment.FetchResult("blocked" if url.endswith("/1") else "failed:http_500")

    monkeypatch.setattr(link_enrichment, "default_fetch", fetch)
    asyncio.run(link_enrichment.enrich_media_links(
        memory, [], _settings(memory), summarize_fn=link_enrichment.default_summarize))
    a = markdown_parser.parse(memory / "entities" / "media-a.md").frontmatter
    b = markdown_parser.parse(memory / "entities" / "media-b.md").frontmatter
    assert a["fetch_status"] == "blocked" and a["fetch_attempted_at"] == date.today().isoformat()
    assert "fetch_status" not in b, "a failure is left for the backfill to retry"
    assert reading_walls.scan_one(memory, URL).wall == "refused"


def test_in_cycle_consent_page_is_stamped_interstitial(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    put_page(memory, "a", URL)

    async def fetch(url, settings):
        return link_enrichment.FetchResult("interstitial")

    monkeypatch.setattr(link_enrichment, "default_fetch", fetch)
    asyncio.run(link_enrichment.enrich_media_links(
        memory, [], _settings(memory), summarize_fn=link_enrichment.default_summarize))
    assert reading_walls.scan_one(memory, URL).wall == "consent"


def test_backfill_does_not_refetch_a_save_time_blocked_page_inside_30_days(tmp_path):
    memory = _bank(tmp_path)
    put_page(memory, "a", URL, fetch_status="blocked", fetch_attempted_at=date.today().isoformat())
    put_page(memory, "b", "https://articles.paperfold.io/post/2")
    scan = link_enrichment.scan_backfill(memory, _settings(memory))
    assert [c.media_id for c in scan.fetch] == ["media-b"] and scan.backoff == 1
