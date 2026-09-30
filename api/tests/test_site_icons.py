"""G166 (owner 2026-09-30: "render the favicon like the one they have in the chrome tab itself") — the
icon of a site Cicada's reader could not read, fetched from the icon service ONLY.

R-RW4 and the ToS rail: a site that just turned Cicada away is never contacted for its icon either. The
proof is a recording fetcher: every URL it is asked for is on the icon service. Hermetic (conftest turns
logo fetching off and fixes the SSRF resolver); every fetcher here is injected."""
from __future__ import annotations

import asyncio
import json
import struct
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest

from api.services import logo_service

SERVICE_HOST = "icons.duckduckgo.com"


def png(w=32, h=32) -> bytes:
    ihdr = struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\x00" * 8 + b"\x00\x00\x00\x00IEND\xaeB`\x82")


class Recorder:
    """A fetcher that answers by URL and remembers every URL it was asked for."""

    def __init__(self, answers: dict[str, tuple[int, bytes, str]] | None = None, default=(404, b"", "text/plain")):
        self.urls: list[str] = []
        self.answers = answers or {}
        self.default = default

    async def __call__(self, url: str):
        self.urls.append(url)
        status, body, ctype = self.answers.get(url, self.default)
        return logo_service.FetchResult(status=status, body=body, content_type=ctype)

    @property
    def hosts(self):
        return {urlparse(u).hostname for u in self.urls}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))


def svc(domain):
    return logo_service.SERVICE_URL.format(domain=domain)


def test_service_rung_is_shared_with_fetch_logo():
    """One URL builder: the third rung of the entity ladder and the site icons both use it."""
    fetcher = Recorder({svc("widget.example"): (200, png(), "image/png")})
    got = run(logo_service.fetch_logo("widget.example", fetcher=fetcher))
    assert got is not None and fetcher.urls[-1] == svc("widget.example")
    assert run(logo_service.fetch_via_icon_service("widget.example", fetcher=Recorder(
        {svc("widget.example"): (200, png(), "image/png")}))) is not None


def test_a_site_icon_only_ever_requests_the_icon_service(tmp_path):
    for site, domain in (("linkedin", "linkedin.com"), ("paperfold.io", "paperfold.io"), ("instagram", "www.instagram.com")):
        fetcher = Recorder({svc(domain): (200, png(), "image/png")})
        path = run(logo_service.ensure_site_icon(tmp_path / "bank", site, domain, fetcher=fetcher))
        assert path is not None and path.exists()
        assert fetcher.hosts == {SERVICE_HOST}, "never the site, never apple-touch-icon, never a homepage"
        assert not any("apple-touch-icon" in u or u.endswith(f"//{domain}/") for u in fetcher.urls)


def test_a_walled_host_is_never_contacted_by_the_entity_ladder_either():
    """A company page whose logo domain is a walled family: rungs 1 and 2 (the site itself) are skipped."""
    fetcher = Recorder({svc("linkedin.com"): (200, png(), "image/png")})
    got = run(logo_service.fetch_logo("linkedin.com", fetcher=fetcher))
    assert got is not None and fetcher.hosts == {SERVICE_HOST}
    ordinary = Recorder({svc("widget.example"): (200, png(), "image/png")})
    run(logo_service.fetch_logo("widget.example", fetcher=ordinary))
    assert "widget.example" in ordinary.hosts, "an ordinary site keeps its three rungs"


def test_a_404_retries_once_with_www_and_only_against_the_icon_service(tmp_path):
    fetcher = Recorder({svc("www.instagram.com"): (200, png(), "image/png")})
    path = run(logo_service.ensure_site_icon(tmp_path / "bank", "instagram", "instagram.com", fetcher=fetcher))
    assert path is not None
    assert fetcher.urls == [svc("instagram.com"), svc("www.instagram.com")]
    assert fetcher.hosts == {SERVICE_HOST}
    # a domain that already has www. is not retried again
    again = Recorder()
    run(logo_service.ensure_site_icon(tmp_path / "bank", "other", "www.other.example", fetcher=again))
    assert again.urls == [svc("www.other.example")]


def test_the_service_404_placeholder_is_a_miss_and_both_misses_cache_a_miss_for_seven_days(tmp_path):
    placeholder = (404, png(), "image/png")  # the service answers a known-unknown host with a generic PNG and 404
    fetcher = Recorder(default=placeholder)
    assert run(logo_service.ensure_site_icon(tmp_path / "bank", "paperfold.io", "paperfold.io", fetcher=fetcher)) is None
    assert fetcher.urls == [svc("paperfold.io"), svc("www.paperfold.io")]
    bank = logo_service.site_bank("bank")
    entry = logo_service.read_meta(bank)["paperfold.io"]
    assert entry["miss"] is True and logo_service.is_fresh(entry)
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert not logo_service.is_fresh(entry, now=later)
    # inside the week: no second lookup
    again = Recorder()
    run(logo_service.ensure_site_icon(tmp_path / "bank", "paperfold.io", "paperfold.io", fetcher=again))
    assert again.urls == []


def test_svg_and_oversize_are_refused_like_any_logo(tmp_path):
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    for body, ctype in ((svg, "image/svg+xml"), (svg, "image/png"), (b"0" * (logo_service.MAX_BYTES + 1), "image/png"),
                        (png(4, 4), "image/png")):
        fetcher = Recorder(default=(200, body, ctype))
        assert run(logo_service.ensure_site_icon(tmp_path / f"b{len(body)}{ctype[-3:]}", "s.example", "s.example",
                                                 fetcher=fetcher)) is None


def test_ico_and_png_are_kept_with_their_type(tmp_path):
    ico = b"\x00\x00\x01\x00\x01\x00" + b"\x20\x20" + b"0" * 60
    fetcher = Recorder({svc("a.example"): (200, ico, "image/x-icon")})
    path = run(logo_service.ensure_site_icon(tmp_path / "bank", "a.example", "a.example", fetcher=fetcher))
    assert path is not None and path.suffix == ".ico"
    fetcher = Recorder({svc("b.example"): (200, png(), "image/png")})
    assert run(logo_service.ensure_site_icon(tmp_path / "bank", "b.example", "b.example", fetcher=fetcher)).suffix == ".png"


def test_hit_ttl_and_the_sites_namespace(tmp_path):
    fetcher = Recorder({svc("linkedin.com"): (200, png(), "image/png")})
    path = run(logo_service.ensure_site_icon(tmp_path / "bank", "linkedin", "linkedin.com", fetcher=fetcher))
    assert path.parent == logo_service.logos_dir("bank") / "sites" and path.name == "linkedin.png"
    # the entity cache never sees a site, and an entity named like a site is untouched
    assert logo_service.cached_ids("bank") == set()
    assert "linkedin" not in logo_service.read_meta("bank")
    assert logo_service.cached_path(logo_service.site_bank("bank"), "linkedin") == path
    entry = logo_service.read_meta(logo_service.site_bank("bank"))["linkedin"]
    assert not entry["miss"] and logo_service.is_fresh(entry)
    assert not logo_service.is_fresh(entry, now=datetime.now(timezone.utc) + timedelta(days=31))
    # a fresh hit is served with no second lookup
    again = Recorder()
    assert run(logo_service.ensure_site_icon(tmp_path / "bank", "linkedin", "linkedin.com", fetcher=again)) == path
    assert again.urls == []


def test_no_fetch_when_logo_fetch_is_off_and_no_miss_is_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    assert run(logo_service.ensure_site_icon(tmp_path / "bank", "linkedin", "linkedin.com")) is None
    assert logo_service.read_meta(logo_service.site_bank("bank")) == {}, "never asked is not a miss"
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    fetcher = Recorder({svc("linkedin.com"): (200, png(), "image/png")})
    assert run(logo_service.ensure_site_icon(tmp_path / "bank", "linkedin", "linkedin.com", fetcher=fetcher)) is not None


def test_the_icon_service_url_is_ssrf_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(logo_service, "_resolve_host", lambda host: ["10.0.0.5"])
    fetcher = Recorder({svc("linkedin.com"): (200, png(), "image/png")})
    assert run(logo_service.ensure_site_icon(tmp_path / "bank", "linkedin", "linkedin.com", fetcher=fetcher)) is None
    assert fetcher.urls == [], "a private answer stops the request before it is made"


def test_a_walled_full_flow_makes_zero_requests_to_any_walled_or_refused_host(tmp_path, monkeypatch):
    """Scan -> sites list -> icon: every request the whole path makes is to the icon service."""
    from _reading_fixtures import put_page
    from _synthetic_bank import _bank
    from api.services import reading_queue, reading_walls

    memory = _bank(tmp_path)
    put_page(memory, "a", "https://articles.paperfold.io/1", fetch_status="blocked")
    put_page(memory, "b", "https://www.linkedin.com/in/alpha")
    put_page(memory, "c", "https://x.com/alpha/status/1")
    reading_walls.reset_memo()
    fetcher = Recorder({svc(d): (200, png(), "image/png") for d in ("paperfold.io", "linkedin.com", "x.com")})
    for row in reading_queue.site_rows(memory):
        assert run(logo_service.ensure_site_icon(memory, row["site"], row["iconHost"], fetcher=fetcher)) is not None
    assert fetcher.hosts == {SERVICE_HOST}
    assert not any(h in u for u in fetcher.urls for h in ("paperfold.io/1", "/in/alpha", "/status/"))
