"""Vision item 2 (2026-10-28) — a brand's mark is the largest its own homepage offers, not the first tag it finds.

Hermetic: an injected fetcher, ``CICADA_HOME`` in tmp. The domain is always the page's trusted site (G61 S3-b): these
tests only change which of that site's own icons is kept.
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
from datetime import datetime, timedelta, timezone

import pytest

from api.services import logo_service


def run(coro):
    return asyncio.run(coro)


def png(width: int, height: int | None = None) -> bytes:
    ihdr = struct.pack(">II", width, height or width) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82")


def fetcher_for(responses: dict, calls: list | None = None):
    async def fetcher(url: str) -> logo_service.FetchResult:
        if calls is not None:
            calls.append(url)
        return responses.get(url) or logo_service.FetchResult(404, b"", "text/html")
    return fetcher


def html(*tags: str) -> logo_service.FetchResult:
    return logo_service.FetchResult(200, ("<html><head>" + "".join(tags) + "</head></html>").encode(), "text/html")


HOME = "https://acme.example/"


def test_the_largest_declared_icon_wins_over_the_first_tag():
    calls: list[str] = []
    fetcher = fetcher_for({
        HOME: html('<link rel="icon" href="/favicon-16.png" sizes="16x16">',
                   '<link rel="icon" href="/icon-192.png" sizes="192x192">'),
        "https://acme.example/favicon-16.png": logo_service.FetchResult(200, png(16), "image/png"),
        "https://acme.example/icon-192.png": logo_service.FetchResult(200, png(192), "image/png"),
    }, calls)
    body, ext, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert logo_service.min_dimension(body) == 192 and ext == "png"
    assert "https://acme.example/favicon-16.png" not in calls, "a good mark stops the ladder before the small one"


def test_a_small_apple_touch_icon_keeps_looking_and_the_larger_one_is_kept():
    fetcher = fetcher_for({
        "https://acme.example/apple-touch-icon.png": logo_service.FetchResult(200, png(32), "image/png"),
        HOME: html('<link rel="icon" href="/i.png" sizes="128x128">'),
        "https://acme.example/i.png": logo_service.FetchResult(200, png(128), "image/png"),
    })
    body, _, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert logo_service.min_dimension(body) == 128


def test_a_square_og_image_is_a_candidate_only_when_nothing_declared_is_good():
    fetcher = fetcher_for({
        HOME: html('<link rel="icon" href="/f.png" sizes="32x32">',
                   '<meta property="og:image" content="https://cdn.acme.example/mark.png">'),
        "https://acme.example/f.png": logo_service.FetchResult(200, png(32), "image/png"),
        "https://cdn.acme.example/mark.png": logo_service.FetchResult(200, png(400), "image/png"),
    })
    body, _, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert logo_service.min_dimension(body) == 400


def test_a_banner_og_image_is_never_a_logo():
    calls: list[str] = []
    fetcher = fetcher_for({
        HOME: html('<link rel="icon" href="/f.png" sizes="32x32">',
                   '<meta property="og:image" content="/share.png">'),
        "https://acme.example/f.png": logo_service.FetchResult(200, png(32), "image/png"),
        "https://acme.example/share.png": logo_service.FetchResult(200, png(1200, 630), "image/png"),
    }, calls)
    body, _, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert logo_service.min_dimension(body) == 32, "the 32 px icon stays: a share banner is not a mark"
    assert "https://acme.example/share.png" in calls


def test_og_image_is_https_only_and_never_a_data_uri():
    page = (b'<meta property="og:image" content="http://acme.example/a.png">'
            b'<meta property="og:image" content="data:image/png;base64,AAAA">')
    assert logo_service.og_image(page, HOME) is None
    assert logo_service.og_image(b'<meta name="og:image" content="/m.png">', HOME) == "https://acme.example/m.png"


def test_the_icon_service_is_asked_when_the_site_offers_only_a_tiny_icon_and_the_larger_wins():
    fetcher = fetcher_for({
        "https://acme.example/apple-touch-icon.png": logo_service.FetchResult(200, png(16), "image/png"),
        "https://icons.duckduckgo.com/ip3/acme.example.ico": logo_service.FetchResult(200, png(48), "image/png"),
    })
    body, _, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert logo_service.min_dimension(body) == 48


def test_relative_icons_resolve_against_the_homepage_the_redirect_landed_on():
    fetcher = fetcher_for({
        HOME: logo_service.FetchResult(301, b"", "text/html", location="https://www.acme.example/"),
        "https://www.acme.example/": html('<link rel="icon" href="icon.png" sizes="96x96">'),
        "https://www.acme.example/icon.png": logo_service.FetchResult(200, png(96), "image/png"),
    })
    body, _, _ = run(logo_service.fetch_logo("acme.example", fetcher=fetcher))
    assert logo_service.min_dimension(body) == 96


# --- a small mark cached by the older ladder is asked once more ------------------------------------------------------


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "banks" / "b"
    (memory / "entities").mkdir(parents=True)
    page = memory / "entities" / "acme.md"
    page.write_text("---\nname: Acme\ntype: company\nlogo: https://acme.example/\n---\n", encoding="utf-8")
    old = datetime.now(timezone.utc) - timedelta(days=1)
    os.utime(page, (old.timestamp() - 60, old.timestamp() - 60))
    return memory, old


def _cache(entity_id: str, data: bytes, ext: str, fetched_at: datetime, **extra) -> None:
    directory = logo_service.logos_dir("b")
    (directory / f"{entity_id}.{ext}").write_bytes(data)
    meta = logo_service.read_meta("b")
    meta[entity_id] = {"fetched_at": fetched_at.isoformat(), "domain": "acme.example", "miss": False, "etag": None,
                       "ext": ext, **extra}
    logo_service.write_meta("b", meta)


def test_a_small_cached_mark_from_the_older_ladder_is_replaced_by_a_larger_one(bank):
    memory, old = bank
    _cache("acme", b"\x00\x00\x01\x00\x01\x00\x10\x10" + b"\x00" * 16, "ico", old)
    fetcher = fetcher_for({"https://acme.example/apple-touch-icon.png":
                           logo_service.FetchResult(200, png(180), "image/png")})
    path = run(logo_service.ensure_logo(memory, "acme", fetcher=fetcher))
    assert path is not None and path.suffix == ".png" and logo_service.min_dimension(path.read_bytes()) == 180
    assert not (logo_service.logos_dir("b") / "acme.ico").exists(), "the replaced format leaves no orphan"
    assert logo_service.read_meta("b")["acme"]["ladder"] == logo_service.LOGO_LADDER


def test_a_small_cached_mark_stays_when_nothing_larger_exists_and_is_not_asked_again(bank):
    memory, old = bank
    _cache("acme", png(32), "png", old)
    calls: list[str] = []
    fetcher = fetcher_for({}, calls)
    path = run(logo_service.ensure_logo(memory, "acme", fetcher=fetcher))
    assert path is not None and logo_service.min_dimension(path.read_bytes()) == 32
    assert calls, "asked once under the new ladder"
    entry = logo_service.read_meta("b")["acme"]
    assert entry["ladder"] == logo_service.LOGO_LADDER and not entry["miss"]
    calls.clear()
    run(logo_service.ensure_logo(memory, "acme", fetcher=fetcher))
    assert calls == [], "stamped: never asked again for the same ladder"


def test_a_good_cached_mark_or_one_from_this_ladder_is_never_re_asked(bank):
    memory, old = bank
    calls: list[str] = []
    _cache("acme", png(128), "png", old)
    run(logo_service.ensure_logo(memory, "acme", fetcher=fetcher_for({}, calls)))
    _cache("acme", png(16 + 16), "png", old, ladder=logo_service.LOGO_LADDER)
    run(logo_service.ensure_logo(memory, "acme", fetcher=fetcher_for({}, calls)))
    assert calls == []


def test_the_gate_off_never_re_asks_a_small_mark(bank, monkeypatch):
    memory, old = bank
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    _cache("acme", png(32), "png", old)
    path = run(logo_service.ensure_logo(memory, "acme"))
    assert path is not None and "ladder" not in json.loads(logo_service.meta_path("b").read_text())["acme"]
