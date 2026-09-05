"""Video-aware ingest: classification, enrichment and the guards (Track V).

No network anywhere — ``enrich`` takes an injected client (media_ingestor.py:213)
and every test here hands it a fake. The point of several of these tests is that
the fake is **never called**: a direct video file must not be fetched at all
(R-V2 + the ``_excluded_media`` hook that already existed), and a non-HTML body
must never reach BeautifulSoup (R13). Same shape as
``test_sources.py::test_ingest_linkedin_saved_performs_zero_http_calls``, which
proves a ToS short-circuit by watching the call list rather than by patching
``enrich`` away.
"""
from __future__ import annotations

import asyncio
import json

from api.services import link_enrichment, media_ingestor
from api.services.media_ingestor import MediaMeta, RawItem


def run(coro):
    # The house pattern (``test_sources.py:31-32``). NOT
    # ``get_event_loop().run_until_complete`` — that is deprecated on the
    # suite's Python 3.12 and leaves an unclosed loop behind for every later
    # test in the process.
    return asyncio.run(coro)


class FakeResponse:
    def __init__(self, payload=None, *, text=None, headers=None):
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})
        # `is not None`, not `or`: an explicitly-empty dict IS the "server sent
        # no content-type" case R13 is about, and `headers or {...}` would
        # silently swap the default back in and make that test unwritable.
        self.headers = headers if headers is not None else {"content-type": "application/json"}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response=None, *, raises=None):
        self.response = response
        self.raises = raises
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if self.raises:
            raise self.raises
        return self.response


# --- classification (R14) ---------------------------------------------------


def test_a_direct_video_file_classifies_as_video():
    assert media_ingestor._classify("https://example.com/media/clip.mp4") == "video"
    assert media_ingestor._classify("https://example.com/media/stream.m3u8") == "video"
    # Even from a bookmark file: the extension is the stronger signal.
    assert media_ingestor._classify("https://example.com/media/clip.mov", True) == "video"
    assert media_ingestor._classify("file:///Users/example/Movies/clip.mov") == "video"


def test_a_provider_url_keeps_its_old_media_type():
    # R-V2: one new value only. Vimeo/TikTok/Loom carry `media.provider`
    # instead, because each media_type value lands in the page's tags and in
    # the /sources wire shape.
    assert media_ingestor._classify("https://vimeo.com/123456789") == "url"
    assert media_ingestor._classify("https://vimeo.com/123456789", True) == "bookmark"
    assert media_ingestor._classify("https://www.youtube.com/watch?v=vid00000001") == "youtube"
    assert media_ingestor._classify("https://www.instagram.com/reel/Cexample01/") == "instagram"


def test_video_is_already_excluded_from_nightly_link_enrichment():
    # The hook existed with no producer (link_enrichment.py:194) — this closes
    # the loop so a saved .mp4 can never be fetched by the backfill.
    assert link_enrichment._excluded_media("https://example.com/media/clip.mp4", "video") is True


# --- enrich: the file short-circuit -----------------------------------------


def test_a_direct_file_never_touches_the_network():
    client = FakeClient(FakeResponse({}))
    meta = run(media_ingestor.enrich("https://example.com/media/clip.mp4", client))
    assert client.calls == []          # the whole point
    assert meta.media_type == "video"
    assert meta.provider == "direct"
    assert meta.duration_s is None     # R17 — absent means absent


def test_a_local_file_never_touches_the_network_either():
    client = FakeClient(FakeResponse({}))
    meta = run(media_ingestor.enrich("file:///Users/example/Movies/clip.mov", client))
    assert client.calls == []
    assert meta.media_type == "video"
    assert meta.provider == "local"


# --- enrich: oEmbed for the three new providers (R12) -----------------------


def test_vimeo_oembed_reads_fields_only():
    client = FakeClient(FakeResponse({
        "title": "A clip", "author_name": "Example Studio",
        "thumbnail_url": "https://example.com/t.jpg", "duration": 95,
        "html": "<iframe src='https://player.vimeo.com/video/123456789'></iframe>",
    }))
    meta = run(media_ingestor.enrich("https://vimeo.com/123456789", client))
    assert meta.title == "A clip"
    assert meta.channel == "Example Studio"
    assert meta.thumbnail == "https://example.com/t.jpg"
    assert meta.duration_s == 95
    assert meta.provider == "vimeo"
    assert client.calls == ["https://vimeo.com/api/oembed.json?url=https%3A%2F%2Fvimeo.com%2F123456789"]


def test_tiktok_and_loom_use_their_own_endpoints():
    for url, endpoint_host, provider in [
        ("https://www.tiktok.com/@exampleuser/video/1234567890123456789", "www.tiktok.com", "tiktok"),
        ("https://www.loom.com/share/abc123def4567890abc123def4567890", "www.loom.com", "loom"),
    ]:
        client = FakeClient(FakeResponse({"title": "T"}))
        meta = run(media_ingestor.enrich(url, client))
        assert meta.provider == provider
        assert endpoint_host in client.calls[0]


def test_an_oembed_failure_degrades_to_url_only_and_keeps_the_provider():
    client = FakeClient(None, raises=RuntimeError("offline"))
    meta = run(media_ingestor.enrich("https://vimeo.com/123456789", client))
    assert meta.title == media_ingestor._fallback_title("https://vimeo.com/123456789")
    assert meta.provider == "vimeo"        # url-derived, so free even offline
    assert meta.media_type == "url"


def test_an_oversized_oembed_body_is_refused():
    client = FakeClient(FakeResponse(text="x" * (media_ingestor._OEMBED_MAX_BYTES + 1)))
    meta = run(media_ingestor.enrich("https://vimeo.com/123456789", client))
    assert meta.title == media_ingestor._fallback_title("https://vimeo.com/123456789")


def test_a_duration_that_is_not_a_positive_int_is_dropped():
    for bad in [None, 0, -3, "95", "n/a"]:
        client = FakeClient(FakeResponse({"title": "T", "duration": bad}))
        meta = run(media_ingestor.enrich("https://vimeo.com/123456789", client))
        assert meta.duration_s is None, bad


# --- the OG content-type guard (R13) ----------------------------------------


def test_opengraph_skips_a_non_text_body():
    client = FakeClient(FakeResponse(text="<html>", headers={"content-type": "video/mp4"}))
    fallback = MediaMeta(title="f", site="example.com")
    meta = run(media_ingestor._enrich_opengraph("https://example.com/x", client, fallback))
    # Deliberately `is`, not a title comparison: the plan's looser
    # `meta is fallback or meta.title == "f"` passes TODAY, before the guard
    # exists, because a body with no og:title already falls back to the same
    # title. Identity is the only assertion that actually proves the body was
    # never parsed.
    assert meta is fallback


def test_opengraph_still_runs_when_no_content_type_header_is_present():
    # R13: a guard that fired on ABSENCE would silently regress every fetch
    # whose server omits the header.
    html = "<html><head><meta property='og:title' content='Real title'></head></html>"
    client = FakeClient(FakeResponse(text=html, headers={}))
    fallback = MediaMeta(title="f", site="example.com")
    meta = run(media_ingestor._enrich_opengraph("https://example.com/x", client, fallback))
    assert meta.title == "Real title"


def test_opengraph_carries_the_url_derived_provider_through_a_successful_fetch():
    # A recognised-but-external provider (Twitch) still reaches _enrich_opengraph.
    # `provider` is URL-derived, so it must survive the SUCCESS path too — not
    # only the failure fallback, which would make the key mean "the fetch broke".
    html = "<html><head><meta property='og:title' content='A stream'></head></html>"
    client = FakeClient(FakeResponse(text=html, headers={"content-type": "text/html"}))
    meta = run(media_ingestor.enrich("https://www.twitch.tv/videos/1234567890", client))
    assert meta.provider == "twitch"
    assert meta.title == "A stream"
    assert meta.duration_s is None      # R17 — an OG page never states one


# --- the TikTok export path (brief item 5) ----------------------------------


def test_a_tiktok_export_item_enriches_through_oembed_not_opengraph():
    # parse_upload routes a TikTok export with from_bookmark_file=False
    # (media_ingestor.py:1074-1090), so every item used to fall to
    # _enrich_opengraph and land on TikTok's consent wall. Dispatching on the
    # URL's provider fixes it for the export path and the paste path alike.
    client = FakeClient(FakeResponse({"title": "A tiktok", "author_name": "@exampleuser"}))
    meta = run(media_ingestor.enrich(
        "https://www.tiktok.com/@exampleuser/video/1234567890123456789", client,
        from_bookmark_file=False))
    assert meta.title == "A tiktok"
    assert "tiktok.com/oembed" in client.calls[0]


# --- write + wire (R15) -----------------------------------------------------


def test_write_media_entity_omits_the_keys_when_absent(tmp_path):
    from api.services import markdown_parser
    media_ingestor.write_media_entity(
        tmp_path, "media-a", RawItem(url="https://example.com/a"),
        MediaMeta(title="A", site="example.com"), "ep_2026-09-05_001")
    fm = markdown_parser.parse(tmp_path / "media-a.md").frontmatter
    assert "provider" not in fm["media"]
    assert "duration_s" not in fm["media"]


def test_write_media_entity_writes_the_keys_when_present(tmp_path):
    from api.services import markdown_parser
    media_ingestor.write_media_entity(
        tmp_path, "media-b", RawItem(url="https://vimeo.com/123456789"),
        MediaMeta(title="B", site="vimeo.com", provider="vimeo", duration_s=95),
        "ep_2026-09-05_002")
    fm = markdown_parser.parse(tmp_path / "media-b.md").frontmatter
    assert fm["media"]["provider"] == "vimeo"
    assert fm["media"]["duration_s"] == 95


# --- the wire shapes (R15/R16) ----------------------------------------------


def test_entity_media_block_carries_the_two_keys_and_drops_a_bad_duration():
    from api.routers.entities import _build_media_block

    block = _build_media_block(
        {"media": {"url": "https://vimeo.com/123456789", "media_type": "url",
                   "provider": "vimeo", "duration_s": 95}}, "")
    assert block.provider == "vimeo"
    assert block.duration_s == 95
    # A hand-edited page could carry anything; a non-int is not a duration
    # (R17 — absent means absent, never a coerced guess).
    bad = _build_media_block(
        {"media": {"url": "https://vimeo.com/123456789", "media_type": "url",
                   "duration_s": "95"}}, "")
    assert bad.duration_s is None
    assert bad.provider is None


def test_the_two_new_wire_fields_are_additive_and_optional():
    # R16 mirrored on the producing side: an older page carries neither key,
    # and both models must still build.
    from api.models.schemas import EntityMedia, MediaSourceItem

    assert EntityMedia(url="https://example.com/a", media_type="url").provider is None
    item = MediaSourceItem(
        media_entity_id="media-a", url="https://example.com/a", title="A",
        media_type="url", saved_at="2026-09-05T00:00:00+00:00")
    assert item.provider is None and item.duration_s is None
    assert "durationS" in MediaSourceItem(
        media_entity_id="media-b", url="https://vimeo.com/1", title="B",
        media_type="url", saved_at="2026-09-05T00:00:00+00:00",
        provider="vimeo", duration_s=95).model_dump(by_alias=True)
