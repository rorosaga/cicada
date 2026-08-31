"""Entity logo resolution + fetch (G59).

Hermetic: every test builds its own tmp workspace and passes an explicit
fetcher. ``conftest`` sets ``CICADA_ALLOW_LOGO_FETCH=off`` for the whole suite
and defaults the SSRF resolver to a fixed public address, so nothing here can
reach the network even by accident. The SSRF-guard tests below override that
default resolver explicitly where they need to simulate a private/loopback
DNS answer.
"""

from __future__ import annotations

import asyncio
import json
import struct
from datetime import datetime, timedelta, timezone

import pytest

from api.services import logo_service


def run(coro):
    return asyncio.run(coro)


def png_bytes(width: int, height: int) -> bytes:
    """Minimal valid-enough PNG: signature + IHDR with the given dimensions."""
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82")


# --- domain_for ladder ------------------------------------------------------


def test_domain_for_prefers_explicit_logo_frontmatter():
    fm = {"type": "company", "name": "Acme",
          "logo": "https://cdn.acme-corp.example/mark.png",
          "sources": [{"ref": "https://other.example/x", "kind": "url"}]}
    assert logo_service.domain_for(fm, "## Links\n- https://third.example/y\n") == "cdn.acme-corp.example"


def test_domain_for_falls_back_to_the_first_url_kind_source():
    fm = {"type": "tool", "name": "Widget",
          "sources": [{"ref": "check my notes", "kind": "note"},
                      {"ref": "https://widget.example/docs", "kind": "url"}]}
    assert logo_service.domain_for(fm, "") == "widget.example"


def test_domain_for_falls_back_to_the_links_section():
    body = "## Summary\n\nA thing.\n\n## Links\n- [Docs](https://links.example/docs)\n- https://second.example\n"
    assert logo_service.domain_for({"type": "tool", "name": "Thing"}, body) == "links.example"


def test_domain_for_falls_back_to_media_url():
    fm = {"type": "media", "name": "A video", "media": {"url": "https://www.youtube.com/watch?v=abc"}}
    assert logo_service.domain_for(fm, "") == "youtube.com"


def test_domain_for_uses_a_website_claim_before_guessing():
    body = (
        "## Summary\n\nx\n\n```claims\n"
        '- {"id": "c1", "text": "MongoDB is at mongodb.com", "subject": "mongodb",'
        ' "predicate": "website", "object": "https://www.mongodb.com/"}\n'
        "```\n"
    )
    assert logo_service.domain_for({"type": "tool", "name": "Mongo DB"}, body) == "mongodb.com"


def test_domain_for_guesses_dot_com_only_for_a_single_token_name():
    assert logo_service.domain_for({"type": "tool", "name": "MongoDB"}, "") == "mongodb.com"
    assert logo_service.domain_for({"type": "company", "name": "Acme Holdings Ltd"}, "") is None


def test_domain_for_never_guesses_for_a_person():
    assert logo_service.domain_for({"type": "person", "name": "Rodrigo"}, "") is None
    # …but an explicit link on a person page is still honoured.
    fm = {"type": "person", "name": "Rodrigo", "sources": [{"ref": "https://rodrigo.example", "kind": "url"}]}
    assert logo_service.domain_for(fm, "") == "rodrigo.example"


def test_domain_for_returns_none_for_a_bare_concept():
    assert logo_service.domain_for({"type": "concept", "name": "Context Engineering"}, "") is None


# --- fetch ladder -----------------------------------------------------------


def make_fetcher(responses: dict, calls: list | None = None):
    """Injected fetcher: a URL -> FetchResult map. Anything unmapped 404s."""
    async def fetcher(url: str) -> logo_service.FetchResult:
        if calls is not None:
            calls.append(url)
        hit = responses.get(url)
        if hit is None:
            return logo_service.FetchResult(404, b"", "text/html")
        return hit
    return fetcher


def test_fetch_logo_takes_the_apple_touch_icon_first():
    calls: list[str] = []
    fetcher = make_fetcher({
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png", '"abc"'),
    }, calls)
    body, ext, etag = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert ext == "png" and etag == '"abc"' and body.startswith(b"\x89PNG")
    assert calls == ["https://acme.example/apple-touch-icon.png"]


def test_fetch_logo_parses_the_homepage_link_rel_icon():
    html = b'<html><head><link rel="apple-touch-icon" href="/static/icon.png"></head></html>'
    fetcher = make_fetcher({
        "https://acme.example/": logo_service.FetchResult(200, html, "text/html"),
        "https://acme.example/static/icon.png":
            logo_service.FetchResult(200, png_bytes(64, 64), "image/png"),
    })
    body, ext, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert ext == "png" and len(body) > 0


def test_fetch_logo_falls_back_to_duckduckgo():
    fetcher = make_fetcher({
        "https://icons.duckduckgo.com/ip3/acme.example.ico":
            logo_service.FetchResult(200, b"\x00\x00\x01\x00\x01\x00\x20\x20", "image/x-icon"),
    })
    body, ext, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert ext == "ico"


def test_fetch_logo_returns_none_when_every_rung_misses():
    assert run(logo_service.fetch_logo("acme.example", fetcher=make_fetcher({}))) is None


def test_fetch_logo_rejects_a_tracking_pixel():
    fetcher = make_fetcher({
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(1, 1), "image/png"),
    })
    assert run(logo_service.fetch_logo("acme.example", fetcher=fetcher)) is None


def test_fetch_logo_rejects_an_oversized_body():
    fetcher = make_fetcher({
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(200, b"x" * (logo_service.MAX_BYTES + 1), "image/png"),
    })
    assert run(logo_service.fetch_logo("acme.example", fetcher=fetcher)) is None


def test_min_dimension_reads_png_gif_and_ico_and_shrugs_at_svg():
    assert logo_service.min_dimension(png_bytes(180, 64)) == 64
    assert logo_service.min_dimension(b"GIF89a" + struct.pack("<HH", 48, 32)) == 32
    assert logo_service.min_dimension(b"\x00\x00\x01\x00\x01\x00\x20\x20") == 32
    assert logo_service.min_dimension(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None


# --- cache + TTL ------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "banks" / "claude-chats"
    (memory / "entities").mkdir(parents=True)
    return memory


def write_entity(memory, entity_id, frontmatter_lines, body=""):
    path = memory / "entities" / f"{entity_id}.md"
    path.write_text("---\n" + "\n".join(frontmatter_lines) + "\n---\n" + body, encoding="utf-8")
    return path


def test_ensure_logo_writes_the_file_and_a_hit_meta_entry(workspace):
    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    fetcher = make_fetcher({
        "https://mongodb.com/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png", '"v1"'),
    })
    path = run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    assert path is not None and path.exists() and path.suffix == ".png"
    assert path.parent == logo_service.logos_dir("claude-chats")

    meta = logo_service.read_meta("claude-chats")["mongodb"]
    assert meta["domain"] == "mongodb.com"
    assert meta["miss"] is False
    assert meta["etag"] == '"v1"'


def test_ensure_logo_second_call_is_served_from_cache(workspace):
    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    calls: list[str] = []
    fetcher = make_fetcher({
        "https://mongodb.com/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png"),
    }, calls)
    run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    before = len(calls)
    run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    assert len(calls) == before, "a fresh cache entry must not re-fetch"


def test_ensure_logo_caches_a_miss_and_does_not_retry_within_the_ttl(workspace):
    write_entity(workspace, "widget", ["name: Widget", "type: tool"])
    calls: list[str] = []
    fetcher = make_fetcher({}, calls)
    assert run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher)) is None
    first = len(calls)
    assert first > 0
    assert run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher)) is None
    assert len(calls) == first, "a cached miss must not re-fetch"
    assert logo_service.read_meta("claude-chats")["widget"]["miss"] is True


def test_an_expired_entry_is_refetched(workspace):
    write_entity(workspace, "widget", ["name: Widget", "type: tool"])
    calls: list[str] = []
    fetcher = make_fetcher({}, calls)
    run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher))
    first = len(calls)

    meta = logo_service.read_meta("claude-chats")
    stale = datetime.now(timezone.utc) - logo_service.MISS_TTL - timedelta(days=1)
    meta["widget"]["fetched_at"] = stale.isoformat()
    logo_service.write_meta("claude-chats", meta)

    run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher))
    assert len(calls) > first, "an expired miss must be retried"


def test_is_fresh_uses_different_ttls_for_hits_and_misses():
    now = datetime.now(timezone.utc)
    eight_days_ago = (now - timedelta(days=8)).isoformat()
    assert logo_service.is_fresh({"fetched_at": eight_days_ago, "miss": False}, now=now) is True
    assert logo_service.is_fresh({"fetched_at": eight_days_ago, "miss": True}, now=now) is False
    assert logo_service.is_fresh({}, now=now) is False


def test_ensure_logo_returns_none_without_a_domain_and_never_fetches(workspace):
    write_entity(workspace, "rodrigo", ["name: Rodrigo", "type: person"])
    calls: list[str] = []
    assert run(logo_service.ensure_logo(workspace, "rodrigo", fetcher=make_fetcher({}, calls))) is None
    assert calls == [], "a person page must not trigger any network call"


def test_cached_ids_reports_only_hits(workspace):
    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    write_entity(workspace, "widget", ["name: Widget", "type: tool"])
    fetcher = make_fetcher({
        "https://mongodb.com/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png"),
    })
    run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    run(logo_service.ensure_logo(workspace, "widget", fetcher=fetcher))
    assert logo_service.cached_ids("claude-chats") == {"mongodb"}


def test_fetch_is_refused_when_the_gate_is_off_and_no_fetcher_is_injected(workspace, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    assert run(logo_service.ensure_logo(workspace, "mongodb")) is None
    assert logo_service.read_meta("claude-chats") == {}, "a gated-off run must not cache a miss"


def test_warm_logos_visits_the_highest_degree_company_and_tool_pages(workspace):
    for i, (eid, etype) in enumerate([("mongodb", "tool"), ("acme", "company"),
                                      ("rodrigo", "person"), ("idea", "concept")]):
        write_entity(workspace, eid, [f"name: {eid}", f"type: {etype}",
                                      f"logo: https://{eid}.example/x.png"])
    fetcher = make_fetcher({
        f"https://{eid}.example/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(64, 64), "image/png")
        for eid in ("mongodb", "acme", "rodrigo", "idea")
    })
    warmed = run(logo_service.warm_logos(workspace, limit=50, fetcher=fetcher))
    assert warmed == 2
    assert logo_service.cached_ids("claude-chats") == {"mongodb", "acme"}


# --- SSRF guard (G59 round 1) ------------------------------------------------


def test_is_public_ip_rejects_reserved_ranges_and_accepts_a_public_address():
    refused = [
        "127.0.0.1",       # loopback
        "10.0.0.1",        # RFC1918 private
        "192.168.1.1",     # RFC1918 private
        "172.16.0.5",      # RFC1918 private
        "169.254.169.254", # link-local / cloud metadata
        "0.0.0.0",         # unspecified
        "::1",             # IPv6 loopback
        "fc00::1",         # IPv6 unique-local (ULA)
        "fe80::1",         # IPv6 link-local
    ]
    for ip in refused:
        assert logo_service._is_public_ip(ip) is False, ip
    assert logo_service._is_public_ip("93.184.216.34") is True


def test_fetch_logo_refuses_a_loopback_literal_host():
    calls: list[str] = []
    fetcher = make_fetcher({}, calls)
    assert run(logo_service.fetch_logo("127.0.0.1", fetcher=fetcher)) is None
    # The DuckDuckGo rung's own host is always icons.duckduckgo.com (fixed,
    # allowed) — only the loopback-hosted rungs are refused before the
    # fetcher is ever called for them.
    assert calls == ["https://icons.duckduckgo.com/ip3/127.0.0.1.ico"]


def test_fetch_logo_refuses_a_metadata_literal_host():
    calls: list[str] = []
    fetcher = make_fetcher({}, calls)
    assert run(logo_service.fetch_logo("169.254.169.254", fetcher=fetcher)) is None
    assert calls == ["https://icons.duckduckgo.com/ip3/169.254.169.254.ico"]


def test_fetch_logo_refuses_a_hostname_that_resolves_to_a_private_address():
    calls: list[str] = []
    fetcher = make_fetcher({}, calls)
    resolver = lambda host: ["10.1.2.3"]
    assert run(logo_service.fetch_logo("internal.corp", fetcher=fetcher, resolver=resolver)) is None
    assert calls == [], "a fetcher must never be called once the resolved host is refused"


def test_fetch_logo_refuses_when_any_resolved_address_is_private():
    calls: list[str] = []
    fetcher = make_fetcher({}, calls)
    resolver = lambda host: ["93.184.216.34", "10.1.2.3"]
    assert run(logo_service.fetch_logo("multi.example", fetcher=fetcher, resolver=resolver)) is None
    assert calls == []


def test_fetch_logo_refuses_a_redirect_to_a_private_host():
    calls: list[str] = []
    fetcher = make_fetcher({
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(302, b"", "", location="http://169.254.169.254/latest/meta-data"),
    }, calls)
    assert run(logo_service.fetch_logo("acme.example", fetcher=fetcher)) is None
    assert "http://169.254.169.254/latest/meta-data" not in calls, (
        "the redirect target must be checked before it is ever requested"
    )
    assert calls[0] == "https://acme.example/apple-touch-icon.png"


def test_fetch_logo_refuses_a_non_http_icon_href():
    html = b'<html><head><link rel="icon" href="file:///etc/passwd"></head></html>'
    calls: list[str] = []
    fetcher = make_fetcher({
        "https://acme.example/": logo_service.FetchResult(200, html, "text/html"),
    }, calls)
    assert run(logo_service.fetch_logo("acme.example", fetcher=fetcher)) is None
    assert "file:///etc/passwd" not in calls


def test_fetch_logo_still_fetches_a_public_host():
    calls: list[str] = []
    fetcher = make_fetcher({
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(64, 64), "image/png"),
    }, calls)
    resolver = lambda host: ["93.184.216.34"]
    body, ext, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher, resolver=resolver))
    assert ext == "png"
    assert calls == ["https://acme.example/apple-touch-icon.png"]


def test_ensure_logo_refuses_a_file_scheme_logo_frontmatter(workspace):
    # ``person`` so the company/tool name-guess heuristic can't mask this: a
    # file:// URL with no authority has no hostname, so domain_for must fall
    # all the way through to None and the fetcher must never be called.
    write_entity(workspace, "rodrigo", ["name: Rodrigo", "type: person", "logo: file:///etc/passwd"])
    calls: list[str] = []
    assert run(logo_service.ensure_logo(workspace, "rodrigo", fetcher=make_fetcher({}, calls))) is None
    assert calls == [], "a file:// value has no host and must never reach the fetcher"


def test_concurrent_fetches_for_two_entities_both_land_in_the_index(workspace):
    """MED-1: `ensure_logo` reads the whole index *after* an awaited fetch. Two
    in-flight fetches must not clobber each other's entry — the loser's image
    would sit on disk unreferenced and `has_logo` would flicker."""
    for eid, host in (("mongodb", "mongodb.com"), ("acme", "acme.example")):
        write_entity(workspace, eid, [f"name: {eid}", "type: tool", f"logo: https://{host}/x.png"])

    started = asyncio.Event()

    def slow_fetcher(host):
        async def fetcher(url):
            if url == f"https://{host}/apple-touch-icon.png":
                # Both fetches are in flight before either writes the index.
                started.set()
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                return logo_service.FetchResult(200, png_bytes(180, 180), "image/png")
            return logo_service.FetchResult(404, b"", "text/html")
        return fetcher

    async def both():
        return await asyncio.gather(
            logo_service.ensure_logo(workspace, "mongodb", fetcher=slow_fetcher("mongodb.com")),
            logo_service.ensure_logo(workspace, "acme", fetcher=slow_fetcher("acme.example")),
        )

    paths = asyncio.run(both())
    assert all(p is not None and p.exists() for p in paths)
    assert started.is_set()
    meta = logo_service.read_meta("claude-chats")
    assert set(meta) == {"mongodb", "acme"}, "a concurrent write dropped an entry"
    assert logo_service.cached_ids("claude-chats") == {"mongodb", "acme"}


def test_concurrent_requests_for_one_entity_run_the_ladder_once(workspace):
    """MED-3: the second caller for the same entity must wait on the first and
    then be served from the cache, not re-run the three-rung ladder."""
    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    calls: list[str] = []

    async def fetcher(url):
        calls.append(url)
        await asyncio.sleep(0)
        if url == "https://mongodb.com/apple-touch-icon.png":
            return logo_service.FetchResult(200, png_bytes(180, 180), "image/png")
        return logo_service.FetchResult(404, b"", "text/html")

    async def twice():
        return await asyncio.gather(
            logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher),
            logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher),
        )

    first, second = asyncio.run(twice())
    assert first is not None and first == second
    assert calls == ["https://mongodb.com/apple-touch-icon.png"], (
        f"the ladder ran more than once for one entity: {calls}")


def test_write_meta_never_corrupts_the_index_when_a_write_fails(workspace, monkeypatch):
    """MED-1 (the reachable half): the index is replaced by rename, so a failed
    or interrupted write — the CLI sleep cycle and the server share one cache
    file across processes — can never leave a truncated `meta.json` behind."""
    good = {"mongodb": {"fetched_at": datetime.now(timezone.utc).isoformat(),
                        "domain": "mongodb.com", "miss": False, "etag": None, "ext": "png"}}
    logo_service.write_meta("claude-chats", good)
    assert logo_service.read_meta("claude-chats") == good

    real_write_text = logo_service.Path.write_text

    def half_a_write(self, data, *args, **kwargs):
        real_write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("disk full")

    monkeypatch.setattr(logo_service.Path, "write_text", half_a_write)
    logo_service.write_meta("claude-chats", {**good, "acme": dict(good["mongodb"])})

    assert logo_service.read_meta("claude-chats") == good, "a failed write corrupted the index"
    leftovers = list(logo_service.logos_dir("claude-chats").glob("meta.json.*"))
    assert leftovers == [], f"a failed write left a temp file behind: {leftovers}"


# --- cache invalidation on a page edit --------------------------------------


def _touch_after_fetch(path):
    """Bump the page's mtime a second past its cache entry's `fetched_at`."""
    import os

    future = datetime.now(timezone.utc).timestamp() + 1
    os.utime(path, (future, future))


def test_editing_the_entity_page_invalidates_its_cached_logo(workspace):
    """The logo domain is resolved FROM the page, so a fresh 30-day entry must
    not outlive an edit to `logo:` / `sources:` / `## Links` / a website claim —
    it kept painting the old brand for up to a month."""
    page = write_entity(workspace, "mongodb",
                        ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    calls: list[str] = []
    fetcher = make_fetcher({
        "https://mongodb.com/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png"),
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png"),
    }, calls)
    run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    assert logo_service.read_meta("claude-chats")["mongodb"]["domain"] == "mongodb.com"
    calls.clear()

    write_entity(workspace, "mongodb",
                 ["name: MongoDB", "type: tool", "logo: https://acme.example/x.png"])
    _touch_after_fetch(page)

    run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    assert calls, "an edited page must be re-resolved, not served from the stale entry"
    assert logo_service.read_meta("claude-chats")["mongodb"]["domain"] == "acme.example"


def test_an_edited_page_keeps_its_cached_logo_when_fetching_is_gated_off(workspace, monkeypatch):
    """Invalidation must not become deletion: with fetching off (or the site
    down) the mark we already have is still the best answer available."""
    page = write_entity(workspace, "mongodb",
                        ["name: MongoDB", "type: tool", "logo: https://mongodb.com/x.png"])
    fetcher = make_fetcher({
        "https://mongodb.com/apple-touch-icon.png":
            logo_service.FetchResult(200, png_bytes(180, 180), "image/png"),
    })
    cached = run(logo_service.ensure_logo(workspace, "mongodb", fetcher=fetcher))
    _touch_after_fetch(page)

    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    assert run(logo_service.ensure_logo(workspace, "mongodb")) == cached

    # Same for a re-validation whose fetch simply misses.
    assert run(logo_service.ensure_logo(
        workspace, "mongodb", fetcher=make_fetcher({}))) == cached
    assert logo_service.read_meta("claude-chats")["mongodb"]["miss"] is False


# --- SVG refusal ------------------------------------------------------------


SVG_BYTES = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"


def test_an_svg_logo_is_refused_by_content_type(workspace):
    """`GET /entities/{id}/logo` serves stored bytes back with their stored
    media type, so an attacker-supplied SVG would be script on that origin."""
    assert logo_service.ext_for("image/svg+xml") is None
    result = logo_service.FetchResult(200, SVG_BYTES, "image/svg+xml")
    assert logo_service._accept(result) is None


def test_svg_bytes_are_refused_even_behind_a_raster_content_type():
    """The header is attacker-controlled; the body decides."""
    assert logo_service.looks_like_svg(SVG_BYTES)
    assert logo_service.looks_like_svg(
        b"<?xml version='1.0'?>\n<!-- c -->\n<svg xmlns='http://www.w3.org/2000/svg'/>")
    assert not logo_service.looks_like_svg(png_bytes(180, 180))
    assert logo_service._accept(
        logo_service.FetchResult(200, SVG_BYTES, "image/png")) is None


def test_fetch_logo_skips_an_svg_rung_and_keeps_laddering(workspace):
    fetcher = make_fetcher({
        "https://acme.example/apple-touch-icon.png":
            logo_service.FetchResult(200, SVG_BYTES, "image/svg+xml"),
        "https://icons.duckduckgo.com/ip3/acme.example.ico":
            logo_service.FetchResult(200, png_bytes(64, 64), "image/png"),
    })
    got = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert got is not None and got[1] == "png"


# --- cross-process meta.json safety -----------------------------------------


def test_record_meta_holds_an_exclusive_file_lock_while_it_rewrites(workspace, monkeypatch):
    """The asyncio lock is per-process; the CLI sleep cycle warms logos in a
    SECOND process beside the running server, and two read-modify-writes there
    drop each other's entries (atomic rename buys atomicity, not merge safety).
    `flock` is per open-file-description, so a second `open()` — here standing
    in for the other process — must not be able to take it."""
    import fcntl

    real_write_meta = logo_service.write_meta
    observed: list[bool] = []

    def spy(bank, meta):
        lock_path = logo_service.logos_dir(bank) / logo_service.LOCK_FILENAME
        with open(lock_path, "a+") as other:
            try:
                fcntl.flock(other.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                observed.append(False)
                fcntl.flock(other.fileno(), fcntl.LOCK_UN)
            except OSError:
                observed.append(True)
        real_write_meta(bank, meta)

    monkeypatch.setattr(logo_service, "write_meta", spy)
    run(logo_service._record_meta("claude-chats", "mongodb", {"fetched_at": "x"}))

    assert observed == [True], "meta.json was rewritten without an exclusive file lock"
    assert logo_service.read_meta("claude-chats")["mongodb"] == {"fetched_at": "x"}


def test_record_meta_merges_an_entry_written_by_another_process(workspace):
    """The re-read happens under the lock, so an entry that landed while this
    coroutine was fetching survives instead of being replaced wholesale."""
    logo_service.write_meta("claude-chats", {"acme": {"fetched_at": "elsewhere"}})
    run(logo_service._record_meta("claude-chats", "mongodb", {"fetched_at": "here"}))
    assert set(logo_service.read_meta("claude-chats")) == {"acme", "mongodb"}


# --- TTL expiry is visible to the version vector ----------------------------


def test_expiry_state_counts_aged_entries_and_reports_the_next_due(workspace):
    now = datetime.now(timezone.utc)
    logo_service.write_meta("claude-chats", {
        "aged": {"fetched_at": (now - logo_service.HIT_TTL - timedelta(days=1)).isoformat(),
                 "miss": False, "ext": "png"},
        "aged_miss": {"fetched_at": (now - logo_service.MISS_TTL - timedelta(days=1)).isoformat(),
                      "miss": True, "ext": None},
        "fresh": {"fetched_at": (now - timedelta(days=1)).isoformat(),
                  "miss": False, "ext": "png"},
        "unusable": {"fetched_at": "not-a-date", "miss": False, "ext": "png"},
    })
    expired, next_due = logo_service.expiry_state("claude-chats", now=now)
    assert expired == 3
    assert next_due == (now - timedelta(days=1) + logo_service.HIT_TTL).timestamp()
