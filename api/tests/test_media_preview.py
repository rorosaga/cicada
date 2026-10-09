"""A media page's own picture: where it comes from, fetched once, stored outside the bank, served from then on.

Fake HTTP only — no test here reaches a real site (the conftest pins DNS to a public address and the logo gate off).
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from api.services import markdown_parser, media_preview, papers, pdf_page


def png(width=32, height=24) -> bytes:
    return pdf_page.encode_png(width, height, b"\x80" * (width * 3 * height), width * 3)


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def page(memory, entity_id, media, *, type_="media"):
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    markdown_parser.write(memory / "entities" / f"{entity_id}.md",
                          {"id": entity_id, "name": entity_id, "type": type_, "media": media}, "\n## Summary\n\nx\n")


class FakeWeb:
    def __init__(self, routes):
        self.routes = routes
        self.asked = []

    async def __call__(self, url):
        self.asked.append(url)
        answer = self.routes.get(url)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return media_preview.Fetched(404, b"")
        return answer


def ok(body, ctype="image/png"):
    return media_preview.Fetched(200, body, ctype)


def run(coro):
    return asyncio.run(coro)


# --- the source --------------------------------------------------------------------------------------------------


def test_the_paper_kind_is_spelled_like_papers():
    assert media_preview.PAPER_KIND == papers.KIND


@pytest.mark.parametrize("media, expected", [
    ({"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.jpg"},
     ("image", "https://cdn.example.com/a.jpg")),
    # A relative og:image finally counts: made absolute against the saved page.
    ({"url": "https://example.com/blog/a", "thumbnail": "/img/a.png"}, ("image", "https://example.com/img/a.png")),
    ({"url": "https://example.com/blog/a", "thumbnail": "//cdn.example.com/a.png"},
     ("image", "https://cdn.example.com/a.png")),
    ({"url": "http://example.com/a", "thumbnail": "http://example.com/a.png"}, ("image", "http://example.com/a.png")),
    # A YouTube video oEmbed gave nothing for: its standard still, from the validated id.
    ({"url": "https://www.youtube.com/watch?v=abcDEF12345"},
     ("image", "https://i.ytimg.com/vi/abcDEF12345/hqdefault.jpg")),
    ({"url": "https://youtu.be/abcDEF12345", "thumbnail": ""},
     ("image", "https://i.ytimg.com/vi/abcDEF12345/hqdefault.jpg")),
    # The stored one wins over the derived one.
    ({"url": "https://www.youtube.com/watch?v=abcDEF12345", "thumbnail": "https://img.example.com/t.jpg"},
     ("image", "https://img.example.com/t.jpg")),
    # A PDF the person saved as a direct link.
    ({"url": "https://example.com/guides/onboarding.PDF"}, ("pdf", "https://example.com/guides/onboarding.PDF")),
    # A saved image is its own picture.
    ({"url": "https://example.com/photos/a.JPG"}, ("image", "https://example.com/photos/a.JPG")),
])
def test_where_a_preview_comes_from(media, expected):
    source = media_preview.source_for({"type": "media", "media": media})
    assert (source.kind, source.url) == expected
    assert len(source.key) == 12


@pytest.mark.parametrize("fm", [
    {"type": "person", "media": {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.jpg"}},
    {"type": "concept", "media": {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.jpg"}},
    {"type": "media", "media": {"url": "https://example.com/a"}},
    # A paper is never fetched: no arXiv page, no arXiv PDF (G133).
    {"type": "media", "media": {"kind": "paper", "url": "https://arxiv.org/abs/2401.00001",
                                "thumbnail": "https://cdn.example.com/p.jpg"}},
    {"type": "media", "media": {"url": "https://arxiv.org/pdf/2401.00001.pdf"}},
    {"type": "media", "media": {"url": "https://doi.org/10.1000/xyz.pdf"}},
    # A login-walled host is never asked, for the page's image or its PDF.
    {"type": "media", "media": {"url": "https://www.instagram.com/p/x", "thumbnail": "https://www.instagram.com/a.jpg"}},
    {"type": "media", "media": {"url": "https://www.linkedin.com/files/a.pdf"}},
    {"type": "media", "media": {"url": "https://example.com/a", "thumbnail": "data:image/png;base64,AAAA"}},
    {"type": "media", "media": {"url": "https://example.com/a", "thumbnail": "javascript:alert(1)"}},
    {"type": "media", "media": "not a block"},
])
def test_pages_with_no_preview(fm):
    assert media_preview.source_for(fm) is None
    assert media_preview.preview_path("x", fm) is None


def test_the_wire_path_changes_with_the_source():
    a = {"type": "media", "media": {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/1.jpg"}}
    b = {"type": "media", "media": {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/2.jpg"}}
    pa, pb = media_preview.preview_path("a b", a), media_preview.preview_path("a b", b)
    assert pa.startswith("/entities/a%20b/preview?v=") and pa != pb


# --- fetched once, stored, served -----------------------------------------------------------------------------------


def test_fetched_once_and_served_from_the_stored_copy(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    web = FakeWeb({"https://cdn.example.com/a.png": ok(png())})
    first = run(media_preview.ensure_preview(memory, "a-link", fetcher=web))
    second = run(media_preview.ensure_preview(memory, "a-link", fetcher=web))
    assert first == second and first.read_bytes() == png()
    assert web.asked == ["https://cdn.example.com/a.png"]
    # Outside every bank.
    assert memory not in first.parents and first.parent.name == "bank" and first.parent.parent.name == "previews"


def test_a_dead_link_keeps_the_stored_copy(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    run(media_preview.ensure_preview(memory, "a-link", fetcher=FakeWeb({"https://cdn.example.com/a.png": ok(png())})))
    # The page's image changes and the new one is gone: the card keeps what it had.
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/b.png"})
    dead = FakeWeb({})
    kept = run(media_preview.ensure_preview(memory, "a-link", fetcher=dead))
    assert kept is not None and kept.read_bytes() == png()
    assert dead.asked == ["https://cdn.example.com/b.png"]
    # …and the miss is remembered: no second request inside the window.
    run(media_preview.ensure_preview(memory, "a-link", fetcher=dead))
    assert dead.asked == ["https://cdn.example.com/b.png"]


def test_a_miss_is_remembered_then_retried_after_its_window(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    dead = FakeWeb({})
    assert run(media_preview.ensure_preview(memory, "a-link", fetcher=dead)) is None
    assert run(media_preview.ensure_preview(memory, "a-link", fetcher=dead)) is None
    assert len(dead.asked) == 1
    later = datetime.now(timezone.utc) + media_preview.MISS_TTL + timedelta(minutes=1)
    alive = FakeWeb({"https://cdn.example.com/a.png": ok(png())})
    assert run(media_preview.ensure_preview(memory, "a-link", fetcher=alive, now=later)) is not None
    assert len(alive.asked) == 1


def test_a_transient_failure_retries_sooner(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    flaky = FakeWeb({"https://cdn.example.com/a.png": media_preview.Fetched(503, b"")})
    run(media_preview.ensure_preview(memory, "a-link", fetcher=flaky))
    meta = media_preview.read_meta("bank", "a-link")
    assert meta["miss"]["transient"] is True
    soon = datetime.now(timezone.utc) + media_preview.RETRY_TTL + timedelta(minutes=1)
    run(media_preview.ensure_preview(memory, "a-link", fetcher=flaky, now=soon))
    assert len(flaky.asked) == 2


def test_a_wall_is_a_miss_and_never_retried_with_other_headers(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    wall = FakeWeb({"https://cdn.example.com/a.png": media_preview.Fetched(403, b"")})
    assert run(media_preview.ensure_preview(memory, "a-link", fetcher=wall)) is None
    assert wall.asked == ["https://cdn.example.com/a.png"]
    assert media_preview.read_meta("bank", "a-link")["miss"]["reason"] == "blocked"


@pytest.mark.parametrize("body, ctype", [
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>", "image/png"),   # SVG behind a raster header
    (b"<html>not an image</html>", "image/png"),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * (media_preview.MAX_BYTES + 10), "image/png"),   # over the rail's bound
])
def test_only_a_raster_within_the_bound_is_kept(tmp_path, body, ctype):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    assert run(media_preview.ensure_preview(
        memory, "a-link", fetcher=FakeWeb({"https://cdn.example.com/a.png": ok(body, ctype)}))) is None


def test_a_tracking_pixel_is_not_a_preview(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    assert run(media_preview.ensure_preview(
        memory, "a-link", fetcher=FakeWeb({"https://cdn.example.com/a.png": ok(png(1, 1))}))) is None


def test_a_jpeg_is_stored_as_a_jpeg_whatever_the_header_says(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a"})
    got = run(media_preview.ensure_preview(
        memory, "a-link", fetcher=FakeWeb({"https://cdn.example.com/a": ok(JPEG, "application/octet-stream")})))
    assert got.suffix == ".jpg"


def test_every_redirect_hop_is_checked(tmp_path, monkeypatch):
    from api.services import net_guard

    monkeypatch.setattr(net_guard, "_resolve_host",
                        lambda host: ["10.0.0.5"] if host == "inside.example.com" else ["93.184.216.34"])
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    web = FakeWeb({"https://cdn.example.com/a.png": media_preview.Fetched(302, b"", location="https://inside.example.com/x.png"),
                   "https://inside.example.com/x.png": ok(png())})
    assert run(media_preview.ensure_preview(memory, "a-link", fetcher=web)) is None
    assert web.asked == ["https://cdn.example.com/a.png"]


def test_a_redirect_onto_a_login_wall_is_not_followed(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    web = FakeWeb({"https://cdn.example.com/a.png":
                   media_preview.Fetched(302, b"", location="https://www.facebook.com/login.php")})
    assert run(media_preview.ensure_preview(memory, "a-link", fetcher=web)) is None
    assert web.asked == ["https://cdn.example.com/a.png"]


# --- the gates ------------------------------------------------------------------------------------------------------


def test_the_picture_gate_off_fetches_nothing_and_records_no_miss(tmp_path, monkeypatch):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    called = []

    async def boom(url):  # the default transport must never run with the gate off
        called.append(url)
        raise AssertionError("fetched")

    monkeypatch.setattr(media_preview, "_http_get", boom)
    assert run(media_preview.ensure_preview(memory, "a-link")) is None
    assert called == [] and media_preview.read_meta("bank", "a-link") == {}


def test_an_unattended_caller_also_needs_the_connector_gate(monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "on")
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    assert media_preview.fetch_allowed() is True
    assert media_preview.fetch_allowed(unattended=True) is False
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    assert media_preview.fetch_allowed(unattended=True) is True
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    assert media_preview.fetch_allowed() is False


# --- a saved PDF -----------------------------------------------------------------------------------------------------


def test_a_saved_pdf_is_rendered_once_in_the_backend(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-guide", {"url": "https://example.com/guide.pdf"})
    web = FakeWeb({"https://example.com/guide.pdf": ok(b"%PDF-1.4 fake", "application/pdf")})
    rendered = []

    def renderer(data):
        rendered.append(data)
        return png(48, 64)

    got = run(media_preview.ensure_preview(memory, "a-guide", fetcher=web, renderer=renderer))
    assert got.suffix == ".png" and got.read_bytes() == png(48, 64)
    run(media_preview.ensure_preview(memory, "a-guide", fetcher=web, renderer=renderer))
    assert rendered == [b"%PDF-1.4 fake"] and len(web.asked) == 1


def test_a_pdf_link_that_is_not_a_pdf_is_a_miss(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-guide", {"url": "https://example.com/guide.pdf"})
    web = FakeWeb({"https://example.com/guide.pdf": ok(b"<html>login</html>", "text/html")})
    assert run(media_preview.ensure_preview(memory, "a-guide", fetcher=web,
                                            renderer=lambda d: pytest.fail("rendered"))) is None


def test_no_page_no_preview(tmp_path):
    assert run(media_preview.ensure_preview(tmp_path / "bank", "missing", fetcher=FakeWeb({}))) is None
    assert run(media_preview.ensure_preview(tmp_path / "bank", "../escape", fetcher=FakeWeb({}))) is None


def test_the_sidecar_holds_no_url(tmp_path):
    memory = tmp_path / "bank"
    page(memory, "a-link", {"url": "https://example.com/a", "thumbnail": "https://cdn.example.com/a.png"})
    run(media_preview.ensure_preview(memory, "a-link", fetcher=FakeWeb({})))
    raw = json.dumps(media_preview.read_meta("bank", "a-link"))
    assert "example.com" not in raw
