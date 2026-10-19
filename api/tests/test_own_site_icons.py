"""Owner ruling 2026-10-19 — a saved link's row shows its site's OWN icon, asked of that site only.

Never a third-party icon service (no one learns what the person saved); only for a list the person opened (the app's
row asks; nothing in Sleep or the list itself does); the registrable domain of the link's own URL; the SSRF guard and
the ToS rail (4 s, ≤ 512 KB, no cookies, never behind auth, a block never retried); behind CICADA_ALLOW_LOGO_FETCH;
cached outside every bank, misses too; a failure is a monogram (404), never an error. Hermetic: conftest turns logo
fetching off and fixes the SSRF resolver; every fetcher here is injected, so nothing touches the network."""
from __future__ import annotations

import asyncio
import json
import struct
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, channel_items, logo_service

SERVICE_HOST = urlparse(logo_service.SERVICE_URL.format(domain="x.example")).hostname


def png(w=64, h=64) -> bytes:
    ihdr = struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00" * 8 + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def ico() -> bytes:
    # ICONDIR + one 32×32 entry.
    return b"\x00\x00\x01\x00\x01\x00" + bytes([32, 32]) + b"\x00" * 14


class Recorder:
    def __init__(self, answers=None, default=(404, b"", "text/plain")):
        self.urls: list[str] = []
        self.answers = answers or {}
        self.default = default

    async def __call__(self, url):
        self.urls.append(url)
        status, body, ctype, *rest = self.answers.get(url, self.default) + ((None,) if len(self.answers.get(url, self.default)) == 3 else ())
        return logo_service.FetchResult(status=status, body=body, content_type=ctype, location=rest[0] if rest else None)

    @property
    def hosts(self):
        return {urlparse(u).hostname for u in self.urls}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


# --- the fetch ----------------------------------------------------------------------------------------------------


def test_the_icon_is_asked_of_the_site_itself_never_a_service():
    fetcher = Recorder({"https://paperfold.example/favicon.ico": (200, ico(), "image/x-icon")})
    got = run(logo_service.fetch_own_site_icon("paperfold.example", fetcher=fetcher))
    assert got is not None and got[1] == "ico"
    assert fetcher.urls == ["https://paperfold.example/apple-touch-icon.png", "https://paperfold.example/favicon.ico"]
    assert SERVICE_HOST not in fetcher.hosts and fetcher.hosts == {"paperfold.example"}


def test_the_touch_icon_wins_and_the_homepage_is_never_read():
    fetcher = Recorder({"https://paperfold.example/apple-touch-icon.png": (200, png(), "image/png")})
    assert run(logo_service.fetch_own_site_icon("paperfold.example", fetcher=fetcher))[1] == "png"
    assert fetcher.urls == ["https://paperfold.example/apple-touch-icon.png"]
    assert not any(urlparse(u).path in ("", "/") for u in fetcher.urls), "no HTML page is fetched"


def test_a_favicon_served_as_octet_stream_is_sniffed_but_an_svg_never_is():
    fetcher = Recorder({"https://a.example/favicon.ico": (200, ico(), "application/octet-stream")})
    assert run(logo_service.fetch_own_site_icon("a.example", fetcher=fetcher)) is not None
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>"
    fetcher = Recorder({"https://a.example/favicon.ico": (200, svg, "image/png")})
    assert run(logo_service.fetch_own_site_icon("a.example", fetcher=fetcher)) is None


def test_a_block_stops_at_once_and_is_never_retried():
    for status in (401, 403, 407, 451):
        fetcher = Recorder({"https://walled.example/apple-touch-icon.png": (status, b"no", "text/html")})
        assert run(logo_service.fetch_own_site_icon("walled.example", fetcher=fetcher)) is None
        assert fetcher.urls == ["https://walled.example/apple-touch-icon.png"], "no second path, no other headers"


def test_an_oversize_body_is_refused():
    big = png() + b"\x00" * (logo_service.MAX_BYTES + 1)
    fetcher = Recorder({"https://a.example/apple-touch-icon.png": (200, big, "image/png"),
                        "https://a.example/favicon.ico": (200, big, "image/x-icon")})
    assert run(logo_service.fetch_own_site_icon("a.example", fetcher=fetcher)) is None


def test_a_redirect_may_stay_on_the_site_but_never_leave_it():
    stay = Recorder({"https://a.example/apple-touch-icon.png": (301, b"", "text/html", "https://www.a.example/t.png"),
                     "https://www.a.example/t.png": (200, png(), "image/png")})
    assert run(logo_service.fetch_own_site_icon("a.example", fetcher=stay)) is not None
    leave = Recorder({"https://a.example/apple-touch-icon.png": (302, b"", "text/html", "https://cdn.other.example/i.png"),
                      "https://cdn.other.example/i.png": (200, png(), "image/png")})
    assert run(logo_service.fetch_own_site_icon("a.example", fetcher=leave)) is None
    assert "cdn.other.example" not in leave.hosts, "the other host is never asked"
    login = Recorder({"https://a.example/apple-touch-icon.png": (302, b"", "text/html", "https://www.linkedin.com/login")})
    assert run(logo_service.fetch_own_site_icon("a.example", fetcher=login)) is None
    assert "www.linkedin.com" not in login.hosts


def test_a_private_address_is_never_asked():
    fetcher = Recorder({"https://intranet.example/apple-touch-icon.png": (200, png(), "image/png")})
    got = run(logo_service.fetch_own_site_icon("intranet.example", fetcher=fetcher, resolver=lambda h: ["10.0.0.2"]))
    assert got is None and fetcher.urls == []


def test_a_dead_host_is_a_miss_never_an_error():
    async def boom(url):
        raise OSError("down")
    assert run(logo_service.fetch_own_site_icon("a.example", fetcher=boom)) is None


def test_the_gate_off_asks_nothing_and_records_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    asked = []

    async def spy(url):
        asked.append(url)
        raise AssertionError("never called")
    monkeypatch.setattr(logo_service, "_http_get", spy)
    assert run(logo_service.fetch_own_site_icon("a.example")) is None
    assert run(logo_service.ensure_own_site_icon(tmp_path / "bank", "a.example")) is None
    assert asked == []
    assert logo_service.read_meta(logo_service.own_site_bank("bank")) == {}, "an un-asked site is never a cached miss"


def test_the_domain_is_the_links_own_registrable_domain():
    assert logo_service.own_site_domain("https://www.blog.paperfold.io/post/1?x=y") == "paperfold.io"
    assert logo_service.own_site_domain("https://www.linkedin.com/posts/someone") is None, "walled: the bundled mark"
    assert logo_service.own_site_domain("http://192.168.1.4/x") is None
    assert logo_service.own_site_domain("http://printer.local/") is None
    assert logo_service.own_site_domain("") is None


# --- the cache ----------------------------------------------------------------------------------------------------


def test_a_hit_and_a_miss_are_cached_outside_the_bank(tmp_path):
    bank = tmp_path / "memory"
    bank.mkdir()
    hit = Recorder({"https://a.example/apple-touch-icon.png": (200, png(), "image/png")})
    path = run(logo_service.ensure_own_site_icon(bank, "a.example", fetcher=hit))
    assert path is not None and path.exists() and bank not in path.parents
    assert "/logos/" in str(path) and "/sites/own/" in str(path)
    again = Recorder()
    assert run(logo_service.ensure_own_site_icon(bank, "a.example", fetcher=again)) == path
    assert again.urls == [], "a fresh hit is served from the cache"
    miss = Recorder()
    assert run(logo_service.ensure_own_site_icon(bank, "b.example", fetcher=miss)) is None
    assert len(miss.urls) == 2
    later = Recorder({"https://b.example/apple-touch-icon.png": (200, png(), "image/png")})
    assert run(logo_service.ensure_own_site_icon(bank, "b.example", fetcher=later)) is None
    assert later.urls == [], "a fresh miss is cached too"
    meta = logo_service.read_meta(logo_service.own_site_bank("memory"))
    assert meta["b.example"]["miss"] is True and meta["a.example"]["ext"] == "png"
    assert logo_service.read_meta(logo_service.site_bank("memory")) == {}, "never mixed with the icon-service cache"


# --- the route: only on request, only for a saved link ---------------------------------------------------------------


def _write(path, fm):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + "".join(f"{k}: {json.dumps(v)}\n" for k, v in fm.items()) + "---\n", encoding="utf-8")


@pytest.fixture
def bank(tmp_path):
    b = tmp_path / "memory"
    _write(b / "entities" / "media-saved.md", {"id": "media-saved", "type": "media", "name": "A", "origin": "chrome-bookmark"})
    _write(b / "entities" / "media-feed.md", {"id": "media-feed", "type": "media", "name": "B", "origin": "rss"})
    _write(b / "entities" / "media-gone.md", {"id": "media-gone", "type": "media", "name": "C", "origin": "chrome-bookmark",
                                              "status": "archived"})
    _write(b / "entities" / "carol-example.md", {"id": "carol-example", "type": "person", "name": "Carol"})
    idx = {"h1": {"media_entity_id": "media-saved", "url": "https://www.paperfold.io/a/b?q=1"},
           "h2": {"media_entity_id": "media-feed", "url": "https://feed.example/post"},
           "h3": {"media_entity_id": "media-gone", "url": "https://gone.example/"}}
    (b / "sources").mkdir(parents=True)
    (b / "sources" / "url_index.json").write_text(json.dumps(idx), encoding="utf-8")
    bank_index.invalidate()
    return b


def test_only_a_live_saved_link_names_a_site(bank):
    assert channel_items.saved_link_site(bank, "media-saved") == "paperfold.io"
    assert channel_items.saved_link_site(bank, "media-feed") is None, "a feed item is captured, not saved"
    assert channel_items.saved_link_site(bank, "media-gone") is None
    assert channel_items.saved_link_site(bank, "carol-example") is None
    assert channel_items.saved_link_site(bank, "nope") is None


def test_listing_a_page_asks_no_site(bank, monkeypatch):
    async def never(*a, **k):
        raise AssertionError("a list never fetches an icon")
    monkeypatch.setattr(logo_service, "fetch_own_site_icon", never)
    monkeypatch.setattr(logo_service, "ensure_own_site_icon", never)
    channel_items.items(bank, "chrome-bookmarks")
    channel_items.items(bank, "files")


@pytest.fixture
def client(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_the_route_serves_the_sites_own_icon_on_request(client, monkeypatch):
    asked: list[str] = []
    real = logo_service.ensure_own_site_icon

    async def injected(memory_path, site, *, fetcher=None):
        asked.append(site)
        return await real(memory_path, site, fetcher=Recorder(
            {"https://paperfold.io/apple-touch-icon.png": (200, png(), "image/png")}))
    monkeypatch.setattr(logo_service, "ensure_own_site_icon", injected)
    r = client.get("/sources/saved/media-saved/site-icon")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert asked == ["paperfold.io"], "the registrable domain of the link's own URL, nothing the caller named"
    assert client.get("/sources/saved/media-saved/site-icon",
                      headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    for other in ("media-feed", "media-gone", "carol-example", "nope"):
        assert client.get(f"/sources/saved/{other}/site-icon").status_code == 404
    assert asked == ["paperfold.io"], "a refused id asks nothing"


def test_the_route_is_a_monogram_with_the_gate_off(client):
    # conftest: CICADA_ALLOW_LOGO_FETCH=off and no injected fetcher → nothing asked, 404, no miss recorded.
    assert client.get("/sources/saved/media-saved/site-icon").status_code == 404
    assert logo_service.read_meta(logo_service.own_site_bank("memory")) == {}


def test_sleep_never_reaches_the_own_site_path():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "services"
    for name in ("sleep_cycle.py", "sleep_tail.py"):
        path = root / name
        if path.exists():
            text = path.read_text(encoding="utf-8")
            assert "own_site" not in text and "saved_link_site" not in text, name


def test_a_reserved_or_private_name_is_never_asked():
    assert logo_service.own_site_domain("https://paperfold.example/") is None, "a reserved name is not a public site"


# --- the real streamed fetcher (re-review of #347) ------------------------------------------------------------------


def test_the_real_fetcher_cuts_raw_bytes_asks_identity_and_passes_a_redirect_through():
    import httpx

    seen: list[httpx.Request] = []

    class Chunks(httpx.AsyncByteStream):
        """A body that arrives in 64 KB pieces, as off a socket (a plain `content=` is read whole up front)."""

        def __init__(self, data: bytes):
            self.data = data

        async def __aiter__(self):
            for i in range(0, len(self.data), 64 * 1024):
                yield self.data[i:i + 64 * 1024]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/moved":
            return httpx.Response(302, headers={"location": "https://www.a.example/t.png"}, stream=Chunks(b""))
        # A "gzip" body the client must never inflate: the cut is on the raw bytes off the wire.
        return httpx.Response(200, stream=Chunks(b"\x1f\x8b" + b"\x00" * (2 * logo_service.MAX_BYTES)),
                              headers={"content-type": "image/png", "content-encoding": "gzip"})

    transport = httpx.MockTransport(handler)
    big = run(logo_service._http_get("https://a.example/big.png", transport=transport))
    assert big.status == 200 and len(big.body) == logo_service.MAX_BYTES + 1
    assert seen[0].headers["accept-encoding"] == "identity"
    assert "cookie" not in {k.lower() for k in seen[0].headers}
    moved = run(logo_service._http_get("https://a.example/moved", transport=transport))
    assert moved.status == 302 and moved.location == "https://www.a.example/t.png", "redirects are ours to check, hop by hop"
    assert len(seen) == 2, "the client never follows the redirect itself"


def test_the_site_check_never_resolves_on_the_event_loop(monkeypatch):
    from api.services import net_guard

    calls = []

    async def off_loop(url):
        calls.append(url)
        return True
    monkeypatch.setattr(net_guard, "is_fetchable_url_async", off_loop)
    fetcher = Recorder({"https://a.example/apple-touch-icon.png": (200, png(), "image/png")})
    assert run(logo_service.fetch_own_site_icon("a.example", fetcher=fetcher)) is not None
    assert calls == ["https://a.example/apple-touch-icon.png"]
