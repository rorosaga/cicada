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


def page(*links: str, base: str = "") -> bytes:
    head = (f'<base href="{base}">' if base else "") + "".join(links)
    return f"<!doctype html><html><head><title>t</title>{head}</head><body>hi</body></html>".encode()


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
    assert fetcher.urls == ["https://paperfold.example/", "https://paperfold.example/apple-touch-icon.png",
                            "https://paperfold.example/favicon.ico"], "the homepage, then the two fixed paths"
    assert SERVICE_HOST not in fetcher.hosts and fetcher.hosts == {"paperfold.example"}


def test_with_nothing_declared_the_touch_icon_wins_after_the_homepage():
    fetcher = Recorder({"https://paperfold.example/": (200, page(), "text/html"),
                        "https://paperfold.example/apple-touch-icon.png": (200, png(), "image/png")})
    assert run(logo_service.fetch_own_site_icon("paperfold.example", fetcher=fetcher))[1] == "png"
    assert fetcher.urls == ["https://paperfold.example/", "https://paperfold.example/apple-touch-icon.png"]


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
        assert fetcher.urls == ["https://walled.example/", "https://walled.example/apple-touch-icon.png"], \
            "no second path, no other headers"
        home = Recorder({"https://walled.example/": (status, b"no", "text/html")})
        assert run(logo_service.fetch_own_site_icon("walled.example", fetcher=home)) is None
        assert home.urls == ["https://walled.example/"], "a block on the homepage stops the whole discovery"


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


# --- discovery like a browser (owner amendment 2026-10-20) -------------------------------------------------------


def jpeg(w=64, h=64) -> bytes:
    return b"\xff\xd8\xff\xc0\x00\x11\x08" + struct.pack(">HH", h, w) + b"\x00" * 12


def test_an_icon_declared_at_another_path_behind_a_same_site_redirect():
    fetcher = Recorder({
        "https://site-a.example/": (301, b"", "text/html", "https://www.site-a.example/"),
        "https://www.site-a.example/": (200, page('<link rel="icon" type="image/png" sizes="192x192" '
                                                  'href="/assets/fav-search.png">'), "text/html; charset=utf-8"),
        "https://www.site-a.example/assets/fav-search.png": (200, png(192, 192), "image/png"),
    })
    got = run(logo_service.fetch_own_site_icon("site-a.example", fetcher=fetcher))
    assert got is not None and got[1] == "png"
    assert fetcher.urls == ["https://site-a.example/", "https://www.site-a.example/",
                            "https://www.site-a.example/assets/fav-search.png"], "resolved against the page's final URL"


def test_a_relative_href_and_a_base_href_resolve_like_a_browser():
    fetcher = Recorder({"https://site-b.example/": (200, page('<link rel=icon href="assets/icon.png">'), "text/html"),
                        "https://site-b.example/assets/icon.png": (200, png(), "image/png")})
    assert run(logo_service.fetch_own_site_icon("site-b.example", fetcher=fetcher)) is not None
    based = Recorder({"https://site-b.example/": (200, page('<link rel=icon href="i.png">', base="/static/"), "text/html"),
                      "https://site-b.example/static/i.png": (200, png(), "image/png")})
    assert run(logo_service.fetch_own_site_icon("site-b.example", fetcher=based)) is not None
    assert based.urls[-1] == "https://site-b.example/static/i.png"


def test_shortcut_icon_and_apple_touch_the_larger_raster_first():
    links = ('<link rel="shortcut icon" href="/_assets/g-32.jpg">'
             '<link rel="apple-touch-icon" href="/_assets/g-256.jpg">')
    fetcher = Recorder({"https://site-c.example/": (200, page(links), "text/html"),
                        "https://site-c.example/_assets/g-256.jpg": (200, jpeg(256, 256), "image/jpeg"),
                        "https://site-c.example/_assets/g-32.jpg": (200, jpeg(32, 32), "image/jpeg")})
    got = run(logo_service.fetch_own_site_icon("site-c.example", fetcher=fetcher))
    assert got is not None and got[1] == "jpg" and logo_service.min_dimension(got[0]) == 256
    assert fetcher.urls[-1] == "https://site-c.example/_assets/g-256.jpg"
    # The shortcut icon alone is found too, and when the big one fails the next is asked.
    fetcher.answers.pop("https://site-c.example/_assets/g-256.jpg")
    fetcher.urls.clear()
    got = run(logo_service.fetch_own_site_icon("site-c.example", fetcher=fetcher))
    assert got is not None and logo_service.min_dimension(got[0]) == 32


def test_an_svg_only_site_is_a_miss_and_an_spa_html_favicon_is_never_an_icon():
    svg_links = ('<link rel="icon" type="image/svg+xml" href="/favicon.svg?v=3">'
                 '<link rel="icon" href="assets/favicon.svg">'
                 '<link rel="mask-icon" href="/mask.png" color="#000">')
    spa = b"<!doctype html><html><head></head><body><div id=root></div></body></html>"
    fetcher = Recorder({"https://site-d.example/": (200, page(svg_links), "text/html"),
                        "https://site-d.example/favicon.ico": (200, spa, "text/html"),
                        "https://site-d.example/apple-touch-icon.png": (200, spa, "image/png")})
    assert run(logo_service.fetch_own_site_icon("site-d.example", fetcher=fetcher)) is None
    assert not any(".svg" in u or "mask" in u for u in fetcher.urls), "an SVG or mask icon is never even asked"
    assert fetcher.urls == ["https://site-d.example/", "https://site-d.example/apple-touch-icon.png",
                            "https://site-d.example/favicon.ico"]


def test_a_data_icon_decodes_only_as_a_capped_raster():
    import base64

    raster = base64.b64encode(png(48, 48)).decode()
    fetcher = Recorder({"https://site-e.example/": (200, page(f'<link rel="icon" href="data:image/png;base64,{raster}">'),
                                                     "text/html")})
    got = run(logo_service.fetch_own_site_icon("site-e.example", fetcher=fetcher))
    assert got is not None and got[1] == "png" and fetcher.urls == ["https://site-e.example/"], "nothing else asked"
    svg = base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'><script>x()</script></svg>").decode()
    for uri in (f"data:image/svg+xml;base64,{svg}", "data:image/svg+xml,%3Csvg%3E%3C/svg%3E",
                f"data:image/png;base64,{svg}"):  # SVG bytes behind a raster type
        assert logo_service._decode_data_icon(uri) is None
        fetcher = Recorder({"https://site-e.example/": (200, page(f'<link rel="icon" href="{uri}">'), "text/html")})
        assert run(logo_service.fetch_own_site_icon("site-e.example", fetcher=fetcher)) is None
    huge = base64.b64encode(png() + b"\x00" * (logo_service.MAX_BYTES + 10)).decode()
    assert logo_service._decode_data_icon(f"data:image/png;base64,{huge}") is None, "capped before decoding"


def test_a_bare_domain_with_no_address_asks_its_www_host_once():
    resolver = lambda host: [] if host == "site-l.example" else ["93.184.216.34"]
    fetcher = Recorder({"https://www.site-l.example/": (200, page(), "text/html"),
                        "https://www.site-l.example/favicon.ico": (200, ico(), "image/x-icon")})
    assert run(logo_service.fetch_own_site_icon("site-l.example", fetcher=fetcher, resolver=resolver)) is not None
    assert fetcher.urls == ["https://www.site-l.example/", "https://www.site-l.example/apple-touch-icon.png",
                            "https://www.site-l.example/favicon.ico"], "the bare host is never asked; its www. is"
    answered = Recorder()  # the bare host answered (a 404): www. is not asked on top
    assert run(logo_service.fetch_own_site_icon("site-l.example", fetcher=answered)) is None
    assert "www.site-l.example" not in answered.hosts


def test_a_cross_site_homepage_redirect_is_never_followed():
    fetcher = Recorder({"https://site-f.example/": (308, b"", "text/html", "https://elsewhere.example/"),
                        "https://elsewhere.example/": (200, page('<link rel=icon href="/x.png">'), "text/html"),
                        "https://site-f.example/favicon.ico": (200, ico(), "image/x-icon")})
    assert run(logo_service.fetch_own_site_icon("site-f.example", fetcher=fetcher)) is not None
    assert "elsewhere.example" not in fetcher.hosts, "the other site is never asked; the fixed paths still are"


def test_a_cdn_icon_the_page_declares_light_before_dark():
    links = ('<link rel="icon" href="https://cdn.example/img/dark.png" media="(prefers-color-scheme: dark)">'
             '<link rel="icon" href="https://cdn.example/img/light.png" media="(prefers-color-scheme: light)">')
    fetcher = Recorder({"https://site-g.example/": (308, b"", "text/html", "https://www.site-g.example/"),
                        "https://www.site-g.example/": (200, page(links), "text/html"),
                        "https://cdn.example/img/light.png": (200, png(), "image/png"),
                        "https://cdn.example/img/dark.png": (200, png(), "image/png")})
    assert run(logo_service.fetch_own_site_icon("site-g.example", fetcher=fetcher)) is not None
    assert fetcher.urls[-1] == "https://cdn.example/img/light.png"
    assert "https://cdn.example/img/dark.png" not in fetcher.urls


def test_a_cdn_icon_must_say_image_sniff_as_one_and_stay_public_and_https():
    links = '<link rel="icon" href="https://cdn.example/i.png">'
    home = {"https://site-h.example/": (200, page(links), "text/html")}
    plain = Recorder({**home, "https://cdn.example/i.png": (200, png(), "application/octet-stream")})
    assert run(logo_service.fetch_own_site_icon("site-h.example", fetcher=plain)) is None, "another host must say image"
    html = Recorder({**home, "https://cdn.example/i.png": (200, b"<html>login</html>", "image/png")})
    assert run(logo_service.fetch_own_site_icon("site-h.example", fetcher=html)) is None, "bytes must be a raster"
    private = Recorder({**home, "https://cdn.example/i.png": (200, png(), "image/png")})
    resolver = lambda host: ["10.0.0.9"] if host == "cdn.example" else ["93.184.216.34"]
    assert run(logo_service.fetch_own_site_icon("site-h.example", fetcher=private, resolver=resolver)) is None
    assert "cdn.example" not in private.hosts, "the SSRF guard refuses before any byte is asked"
    http = Recorder({"https://site-h.example/": (200, page('<link rel="icon" href="http://cdn.example/i.png">'),
                                                 "text/html")})
    assert run(logo_service.fetch_own_site_icon("site-h.example", fetcher=http)) is None
    assert "cdn.example" not in http.hosts, "https only"
    bounce = Recorder({**home, "https://cdn.example/i.png": (302, b"", "text/html", "https://third.example/i.png"),
                       "https://third.example/i.png": (200, png(), "image/png")})
    assert run(logo_service.fetch_own_site_icon("site-h.example", fetcher=bounce)) is None
    assert "third.example" not in bounce.hosts, "a declared icon's redirect never wanders to a third site"


def test_an_oversize_declared_icon_falls_through_to_the_next():
    links = '<link rel="icon" sizes="512x512" href="/big.png"><link rel="icon" sizes="32x32" href="/small.png">'
    fetcher = Recorder({"https://site-i.example/": (200, page(links), "text/html"),
                        "https://site-i.example/big.png": (200, png(512, 512) + b"\x00" * logo_service.MAX_BYTES,
                                                            "image/png"),
                        "https://site-i.example/small.png": (200, png(32, 32), "image/png")})
    got = run(logo_service.fetch_own_site_icon("site-i.example", fetcher=fetcher))
    assert got is not None and logo_service.min_dimension(got[0]) == 32


def test_at_most_three_declared_icons_are_asked():
    links = "".join(f'<link rel="icon" sizes="{n}x{n}" href="/i{n}.png">' for n in (16, 32, 64, 128, 256))
    fetcher = Recorder({"https://site-j.example/": (200, page(links), "text/html")})
    assert run(logo_service.fetch_own_site_icon("site-j.example", fetcher=fetcher)) is None
    asked = [u for u in fetcher.urls if "/i" in u]
    assert asked == ["https://site-j.example/i256.png", "https://site-j.example/i128.png",
                     "https://site-j.example/i64.png"], "the largest first, three at most"


HOSTILE_PAGES = {
    "lt_a": b"<a" * (logo_service.MAX_BYTES // 2),
    "nested_quotes": b"<link a='" * (logo_service.MAX_BYTES // 9),
    "pi": b"<?" * (logo_service.MAX_BYTES // 2),
    "lt_slash": b"</" * (logo_service.MAX_BYTES // 2),
    "link_lt": b"<link" * (logo_service.MAX_BYTES // 5),
    "one_huge_tag": b"<link " + b"a=b " * (logo_service.MAX_BYTES // 4) + b">",
    "many_links": b'<link rel="icon" href="/f.png" sizes="32x32">' * (logo_service.MAX_BYTES // 46),
}


@pytest.mark.parametrize("name", sorted(HOSTILE_PAGES))
def test_a_hostile_page_finishes_in_budget_and_never_holds_the_event_loop(name):
    """Security review of #371: the stdlib HTML tokenizer is quadratic on such markup and ran on the event loop, so
    `wait_for` could not stop it and the whole backend froze. Now only `<link>`/`<base>` tags are scanned, linearly,
    off the loop: the discovery ends inside its budget while a 0.1 s ticker keeps ticking."""
    import time

    body = HOSTILE_PAGES[name][: logo_service.MAX_BYTES]

    async def fetcher(url):
        await asyncio.sleep(0)
        if url.endswith("/"):
            return logo_service.FetchResult(status=200, body=body, content_type="text/html")
        return logo_service.FetchResult(status=404, body=b"", content_type="text/plain")

    async def main():
        ticks = [time.perf_counter()]
        stop = asyncio.Event()

        async def ticker():
            while not stop.is_set():
                await asyncio.sleep(0.1)
                ticks.append(time.perf_counter())
        task = asyncio.create_task(ticker())
        await asyncio.sleep(0.15)
        started = time.perf_counter()
        await logo_service.fetch_own_site_icon("hostile.example", fetcher=fetcher)
        wall = time.perf_counter() - started
        await asyncio.sleep(0.15)
        stop.set()
        await task
        return wall, max(b - a for a, b in zip(ticks, ticks[1:]))
    wall, stall = run(main())
    assert wall < logo_service.OWN_SITE_BUDGET_SECONDS
    assert stall < 0.5, f"the event loop stalled {stall:.2f}s"


def test_the_budget_stops_slow_answers_and_cpu_work_alike(tmp_path, monkeypatch):
    import time

    monkeypatch.setattr(logo_service, "OWN_SITE_BUDGET_SECONDS", 0.05)

    async def slow(url):
        await asyncio.sleep(2)
        return logo_service.FetchResult(status=200, body=png(), content_type="image/png")
    started = time.monotonic()
    assert run(logo_service.fetch_own_site_icon("site-k.example", fetcher=slow)) is None
    assert time.monotonic() - started < 1
    assert run(logo_service.ensure_own_site_icon(tmp_path / "bank", "site-k.example", fetcher=slow)) is None
    assert logo_service.read_meta(logo_service.own_site_bank("bank"))["site-k.example"]["miss"] is True
    # CPU work counts against the same clock: the page's scan runs off the loop, so the budget still fires on time
    # even when the scan itself is slow.
    real = logo_service.declared_icons

    def slow_scan(html, url):
        time.sleep(0.5)
        return real(html, url)
    monkeypatch.setattr(logo_service, "declared_icons", slow_scan)

    async def page_then_icon(url):
        if url.endswith("/"):
            return logo_service.FetchResult(status=200, body=page('<link rel=icon href="/i.png">'), content_type="text/html")
        return logo_service.FetchResult(status=200, body=png(), content_type="image/png")
    async def timed():
        started = time.monotonic()
        got = await logo_service.fetch_own_site_icon("site-k.example", fetcher=page_then_icon)
        return got, time.monotonic() - started
    got, wall = run(timed())
    assert got is None and wall < 0.3, "the budget fired while the scan was still running"


def test_every_hop_is_plain_https_and_a_declared_url_has_no_port_or_userinfo():
    downgrade = Recorder({"https://site-m.example/": (301, b"", "text/html", "http://www.site-m.example/"),
                          "http://www.site-m.example/": (200, page('<link rel=icon href="/i.png">'), "text/html")})
    run(logo_service.fetch_own_site_icon("site-m.example", fetcher=downgrade))
    assert not any(u.startswith("http:") for u in downgrade.urls), "a same-site redirect to http is never followed"
    ported = Recorder({"https://site-m.example/": (301, b"", "text/html", "https://www.site-m.example:8443/")})
    run(logo_service.fetch_own_site_icon("site-m.example", fetcher=ported))
    assert not any(":8443" in u for u in ported.urls), "nor one to another port"
    links = ('<link rel="icon" sizes="64x64" href="https://cdn.example:8443/i.png">'
             '<link rel="icon" sizes="48x48" href="https://user:pw@cdn.example/i.png">'
             '<link rel="icon" sizes="32x32" href="https://cdn.example:443/i.png">')
    declared = Recorder({"https://site-m.example/": (200, page(links), "text/html")})
    assert run(logo_service.fetch_own_site_icon("site-m.example", fetcher=declared)) is None
    assert "cdn.example" not in declared.hosts, "an explicit port or userinfo is never asked"
    assert logo_service.declared_icons(page(links), "https://site-m.example/") == []


def test_declared_icons_ranks_and_skips():
    links = ('<link rel="mask-icon" href="/m.png">'
             '<link rel="icon" sizes="16x16" href="/16.png">'
             '<link rel="icon" sizes="any" href="/any.png">'
             '<LINK REL="Shortcut Icon" HREF="/s.ico">'
             '<link rel="apple-touch-icon" href="/touch.png">'
             '<link rel="icon" sizes="64x64" href="/64-dark.png" media="(prefers-color-scheme:dark)">'
             '<link rel="stylesheet" href="/s.css">')
    got = [urlparse(link.url).path for link in logo_service.declared_icons(page(links), "https://x.example/")]
    assert got == ["/touch.png", "/any.png", "/s.ico", "/16.png", "/64-dark.png"]
    assert logo_service.declared_icons(b"<html><link rel=icon", "https://x.example/") == []


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
    assert len(miss.urls) == 3
    later = Recorder({"https://b.example/apple-touch-icon.png": (200, png(), "image/png")})
    assert run(logo_service.ensure_own_site_icon(bank, "b.example", fetcher=later)) is None
    assert later.urls == [], "a fresh miss is cached too"
    meta = logo_service.read_meta(logo_service.own_site_bank("memory"))
    assert meta["b.example"]["miss"] is True and meta["a.example"]["ext"] == "png"
    assert logo_service.read_meta(logo_service.site_bank("memory")) == {}, "never mixed with the icon-service cache"


def test_a_miss_from_the_older_discovery_is_asked_once_more_and_hits_stay(tmp_path):
    from datetime import datetime, timezone

    bank = tmp_path / "memory"
    bank.mkdir()
    own = logo_service.own_site_bank("memory")
    now = datetime.now(timezone.utc).isoformat()
    run(logo_service._record_meta(own, "old-miss.example", {"fetched_at": now, "miss": True, "etag": None, "ext": None}))
    run(logo_service._record_meta(own, "old-hit.example", {"fetched_at": now, "miss": False, "etag": None, "ext": "png"}))
    (logo_service.logos_dir(own) / "old-hit.example.png").write_bytes(png())
    fetcher = Recorder({"https://old-miss.example/": (200, page('<link rel=icon href="/i.png">'), "text/html"),
                        "https://old-miss.example/i.png": (200, png(), "image/png")})
    assert run(logo_service.ensure_own_site_icon(bank, "old-miss.example", fetcher=fetcher)) is not None
    assert run(logo_service.ensure_own_site_icon(bank, "old-hit.example", fetcher=fetcher)) is not None
    assert "old-hit.example" not in fetcher.hosts, "a hit from the older discovery is kept"
    assert logo_service.read_meta(own)["old-miss.example"]["v"] == logo_service.OWN_SITE_DISCOVERY
    again = Recorder()
    assert run(logo_service.ensure_own_site_icon(bank, "new-miss.example", fetcher=again)) is None
    assert run(logo_service.ensure_own_site_icon(bank, "new-miss.example", fetcher=again)) is None
    assert len(again.urls) == 3, "a miss under this discovery is retried only when it expires"


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


# --- owner 2026-10-20: a Waiting row of a saved link, before Sleep made its page -------------------------------------


@pytest.fixture
def episodes(bank):
    ep = bank / "episodes"
    base = {"timestamp": "2026-10-01T10:00:00+00:00", "processed": False}
    _write(ep / "ep_2026-10-01_1.md", {**base, "id": "ep_2026-10-01_1", "origin": "chrome-bookmark",
                                       "url": "https://www.paperfold.io/a?q=1", "title": "A"})
    _write(ep / "ep_2026-10-01_2.md", {**base, "id": "ep_2026-10-01_2", "origin": "claude-code", "session_id": "s-1",
                                       "harness": "claude-code", "url": "https://paperfold.io/"})
    _write(ep / "ep_2026-10-01_3.md", {**base, "id": "ep_2026-10-01_3", "origin": "rss",
                                       "url": "https://feedsite.io/post"})
    _write(ep / "ep_2026-10-01_4.md", {**base, "id": "ep_2026-10-01_4", "origin": "chrome-bookmark",
                                       "url": "https://gone-site.io/", "source_deleted_at": "2026-10-02T00:00:00+00:00"})
    _write(ep / "ep_2026-10-01_5.md", {**base, "id": "ep_2026-10-01_5", "origin": "chrome-bookmark",
                                       "url": "https://www.linkedin.com/posts/x"})
    bank_index.invalidate()
    return bank


def test_only_a_live_saved_episode_names_a_site(episodes):
    assert channel_items.saved_episode_site(episodes, "ep_2026-10-01_1") == "paperfold.io"
    assert channel_items.saved_episode_site(episodes, "ep_2026-10-01_2") is None, "a conversation is never a saved link"
    assert channel_items.saved_episode_site(episodes, "ep_2026-10-01_3") is None, "a feed item is captured, not saved"
    assert channel_items.saved_episode_site(episodes, "ep_2026-10-01_4") is None, "a deleted source is not live"
    assert channel_items.saved_episode_site(episodes, "ep_2026-10-01_5") is None, "a walled family is never asked"
    for bad in ("nope", "../entities/media-saved", "ep_2026-10-01_9", "ep_2026-10-01_1\n", "ep_2026-10-01_1.md"):
        assert channel_items.saved_episode_site(episodes, bad) is None


def test_the_episode_route_asks_the_same_site_and_cache(episodes, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(episodes))
    config.get_settings.cache_clear()
    client = TestClient(main.app)
    asked: list[str] = []
    real = logo_service.ensure_own_site_icon

    async def injected(memory_path, site, *, fetcher=None):
        asked.append(site)
        return await real(memory_path, site, fetcher=Recorder(
            {"https://paperfold.io/apple-touch-icon.png": (200, png(), "image/png")}))
    monkeypatch.setattr(logo_service, "ensure_own_site_icon", injected)
    try:
        r = client.get("/sources/saved/episodes/ep_2026-10-01_1/site-icon")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"
        assert asked == ["paperfold.io"]
        # The media route for the same site is served from the one cache: nothing asked again.
        assert client.get("/sources/saved/media-saved/site-icon").status_code == 200
        assert asked == ["paperfold.io"], "one site, one ask"
        for other in ("ep_2026-10-01_2", "ep_2026-10-01_3", "ep_2026-10-01_4", "ep_2026-10-01_5", "nope"):
            assert client.get(f"/sources/saved/episodes/{other}/site-icon").status_code == 404
        assert asked == ["paperfold.io"], "a refused id asks nothing"
    finally:
        config.get_settings.cache_clear()


def test_rows_carry_the_site_key_their_mark_is_drawn_under(episodes, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(episodes))
    config.get_settings.cache_clear()
    try:
        rows = {r["id"]: r for r in TestClient(main.app).get("/sleep/episodes?processed=false").json()}
        assert rows["ep_2026-10-01_1"]["site"] == "paperfold.io"
        assert rows["ep_2026-10-01_5"]["site"] == "linkedin", "a walled family keys its bundled mark"
        assert rows["ep_2026-10-01_2"]["site"] is None, "a conversation's row keeps its harness mark"
        assert rows["ep_2026-10-01_3"]["site"] is None, "a captured feed item keeps its source's mark"
        assert rows["ep_2026-10-01_4"]["site"] is None, "a deleted bookmark is not a live saved link"
    finally:
        config.get_settings.cache_clear()


def test_mark_key_is_site_of_when_valid():
    from api.services import reading_hosts
    assert reading_hosts.mark_key("https://blog.paperfold.io/x") == "paperfold.io"
    assert reading_hosts.mark_key("https://user.github.io/p") == "user.github.io"
    assert reading_hosts.mark_key("https://lnkd.in/abc") == "linkedin"
    assert reading_hosts.mark_key("") is None and reading_hosts.mark_key("not a url") is None


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
    assert calls == ["https://a.example/", "https://a.example/apple-touch-icon.png"]


def test_a_saved_item_on_the_list_carries_its_site_key(bank, client):
    # Review of #372: a key only where the media icon route answers — a feed page's key would ask by an id the route
    # refuses, and that miss must never stand for the site.
    idx = json.loads((bank / "sources" / "url_index.json").read_text(encoding="utf-8"))
    idx["h2"]["url"] = "https://paperfold.io/feed-post"
    (bank / "sources" / "url_index.json").write_text(json.dumps(idx), encoding="utf-8")
    bank_index.invalidate()
    items = {i["mediaEntityId"]: i for i in client.get("/sources").json()["items"]}
    assert items["media-saved"]["siteKey"] == "paperfold.io", "the one key every surface draws its mark under"
    assert items["media-feed"].get("siteKey") is None, "a captured feed page names no site: its row keeps its mark"
    assert channel_items.saved_link_site(bank, "media-feed") is None


def test_the_readers_document_names_a_saved_links_site(episodes):
    from api.services import provenance
    assert provenance.episode_document(episodes, "ep_2026-10-01_1").site == "paperfold.io"
    assert provenance.episode_document(episodes, "ep_2026-10-01_2").site is None, "a conversation keeps its harness"
    assert provenance.episode_document(episodes, "ep_2026-10-01_3").site is None
