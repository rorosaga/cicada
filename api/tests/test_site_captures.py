"""G166 exploring, D1 (b) — capture records: dated and append-only in the bank, one thumbnail (≤ 640×400) per changed
look, full images and page text outside the bank, the signed-in flag, the look's hash and palette read by Cicada.
Made-up pictures (`demo_pictures.website`) and bob-example.org links only."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _explore_fixtures import DARK, LIGHT, bank_with_sites
from api.services import image_decode, markdown_parser, site_captures

T0 = datetime(2026, 10, 14, 14, 2, 0, tzinfo=timezone.utc)
needs_sips = pytest.mark.skipif(not image_decode.available(), reason="macOS's sips decodes images here")
TOKEN_A, TOKEN_B, TOKEN_C = "a" * 32, "b" * 32, "c" * 32
PAGE = {"title": "Alpha Example", "description": "A made-up tool.",
        "outline": [{"level": 1, "text": "Build alpha things"}, {"level": 2, "text": "Pricing from $12 per month"}],
        "fonts": ["Georgia"], "tokens": {"--brand": "#3b5bfd"}, "text": "Build alpha things. Pricing © 2026.",
        "components": [{"name": "nav", "box": {"x": 0, "y": 0, "width": 1440, "height": 56}}, {"name": "hero"}],
        "jsonld": [{"@type": "SoftwareApplication", "name": "Alpha Example", "offers": {"price": "12",
                                                                                     "priceCurrency": "USD"}}]}


@pytest.fixture
def bank(tmp_path):
    memory, _ = bank_with_sites(tmp_path, 1)
    return memory


def _record(bank, token, *, shots=None, now=T0, **kw):
    kw.setdefault("page", PAGE)
    return site_captures.record(bank, entity_id="media-site00", url="https://site00.bob-example.org/", lease_token=token,
                                outcome=kw.pop("outcome", "captured"), captured_at=kw.pop("captured_at", now),
                                window_start=now - timedelta(minutes=1), shots=shots, author="claude-code",
                                session="s1", now=now, **kw)


@needs_sips
def test_a_capture_is_a_dated_record_with_a_bounded_thumbnail_in_the_bank(bank, tmp_path):
    out = _record(bank, TOKEN_A, shots=[("viewport", DARK)], saved_at="2026-03-02", why_at="2026-10-01T09:00:00Z")
    assert out["action"] == "added" and out["id"] == "20261014T140200Z-aaaaaa"
    rel, thumb_rel = out["paths"]
    assert rel == "captures/media-site00/20261014T140200Z-aaaaaa.md"
    assert thumb_rel.startswith("assets/captures/") and thumb_rel.endswith(".jpg")
    thumb = (bank / thumb_rel).read_bytes()
    assert image_decode.sniff(thumb) == "jpg"
    w, h = image_decode.dimensions(thumb)
    assert (w, h) == (640, 400), "a 1440×900 viewport thumbnails to 640×400"
    cap = out["capture"]
    assert cap["captured_at"] == "2026-10-14T14:02:00Z" and cap["recorded_at"] == "2026-10-14T14:02:00Z"
    assert cap["saved_at"] == "2026-03-02" and cap["why_at"] == "2026-10-01T09:00:00Z", "every date is kept"
    assert cap["palette"] and "dark" in cap["look"], "Cicada reads the colours itself"
    assert len(cap["dhash"]) == 16 and cap["text_sha256"]
    fm = markdown_parser.parse(bank / rel).frontmatter
    assert fm["jsonld"] == [{"type": "SoftwareApplication", "name": "Alpha Example", "price": "12",
                             "priceCurrency": "USD"}]
    assert fm["outline"][0] == {"level": 1, "text": "Build alpha things"}


@needs_sips
def test_full_images_and_text_live_outside_the_bank(bank, tmp_path):
    out = _record(bank, TOKEN_A, shots=[("viewport", DARK), ("full", LIGHT)])
    outside = site_captures.outside_root(bank)
    assert not str(outside).startswith(str(bank)), "the full-resolution store is outside every bank"
    for img in out["capture"]["images"]:
        path = outside / f"{img['sha256']}.{img['ext']}"
        assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == img["sha256"]
    assert {i["kind"] for i in out["capture"]["images"]} == {"viewport", "full"}
    assert list((outside / "text").glob("*.txt")), "the page's words are kept beside the images, not in git"
    bank_files = {p.relative_to(bank).as_posix() for p in bank.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert not any(f.endswith(".png") for f in bank_files if f.startswith(("captures/", "assets/captures/")))
    assert sum(1 for f in bank_files if f.startswith("assets/captures/")) == 1


@needs_sips
def test_a_revisit_adds_a_record_and_never_replaces_one(bank):
    first = _record(bank, TOKEN_A, shots=[("viewport", DARK)])
    first_text = (bank / first["paths"][0]).read_text()
    later = T0 + timedelta(days=30)
    second = _record(bank, TOKEN_B, shots=[("viewport", DARK)], now=later)
    assert second["id"] != first["id"]
    assert (bank / first["paths"][0]).read_text() == first_text, "append-only: an earlier record is never edited"
    caps = site_captures.list_captures(bank, "media-site00")
    assert [c["id"] for c in caps] == [second["id"], first["id"]], "newest first"
    change = second["capture"]["change"]
    assert change["since"] == first["id"] and change["look"] == "same" and change["words"] == "same"
    assert second["capture"]["thumb"]["reused"] is True and second["paths"] == [second["paths"][0]], \
        "an unchanged look adds no thumbnail bytes"
    third = _record(bank, TOKEN_C, shots=[("viewport", LIGHT)], now=later + timedelta(days=1),
                    page={**PAGE, "outline": [{"level": 1, "text": "A new headline"}]})
    assert third["capture"]["change"]["look"] == "new" and third["capture"]["change"]["words"].startswith("changed")
    assert len(third["paths"]) == 2, "a new look adds its thumbnail"


def test_the_same_record_twice_writes_nothing(bank):
    out = _record(bank, TOKEN_A, outcome="gone", shots=None)
    again = _record(bank, TOKEN_A, outcome="gone", shots=None)
    assert out["action"] == "added" and again["action"] == "duplicate" and again["paths"] == []
    assert len(site_captures.list_captures(bank, "media-site00")) == 1


def test_a_dead_site_is_dated_with_no_images(bank):
    out = _record(bank, TOKEN_A, outcome="not_found", shots=[("viewport", DARK)])
    cap = out["capture"]
    assert cap["outcome"] == "not_found" and "images" not in cap and "thumb" not in cap
    assert out["paths"] == [out["paths"][0]]


def test_captured_needs_a_viewport_and_a_wall_is_never_a_capture(bank):
    assert _record(bank, TOKEN_A, shots=[])["action"] == "error"
    assert _record(bank, TOKEN_A, outcome="needs_login")["action"] == "error"
    assert not (bank / "captures").exists()


def test_the_signed_in_flag_is_recorded_both_ways(bank):
    signed = _record(bank, TOKEN_A, outcome="gone", signed_in=True)["capture"]
    private = _record(bank, TOKEN_B, outcome="gone", signed_in=False, now=T0 + timedelta(seconds=5))["capture"]
    assert signed["signed_in"] is True and signed["context"] == "signed_in"
    assert private["signed_in"] is False and private["context"] == "isolated"
    body = (bank / signed["path"]).read_text()
    assert "signed-in browser" in body


@needs_sips
def test_a_page_showing_the_persons_account_keeps_its_thumbnail_outside_the_bank(bank):
    out = _record(bank, TOKEN_A, shots=[("viewport", DARK)], account_visible=True)
    assert len(out["paths"]) == 1 and "thumb" not in out["capture"]
    assert {i["kind"] for i in out["capture"]["images"]} == {"viewport", "thumb"}
    assert not (bank / "assets" / "captures").exists()


def test_a_clock_outside_the_lease_window_is_replaced_and_flagged(bank):
    out = _record(bank, TOKEN_A, outcome="gone", captured_at="2020-01-01T00:00:00Z")
    assert out["capture"]["captured_at"] == "2026-10-14T14:02:00Z" and out["capture"]["captured_at_flagged"] is True


def test_free_text_is_scrubbed(bank):
    secret = "sk-" + "A1b2C3d4E5f6G7h8J9k0"
    out = _record(bank, TOKEN_A, outcome="gone", page={**PAGE, "title": f"Key {secret}"})
    assert secret not in (bank / out["paths"][0]).read_text()


def test_thumb_size_fits_the_box():
    assert site_captures.thumb_size(2880, 1800) == (640, 400)
    assert site_captures.thumb_size(780, 1688) == (185, 400)
    assert site_captures.thumb_size(300, 200) == (300, 200), "never enlarged"


def test_dhash_distances_name_the_change():
    assert site_captures.look_change(site_captures.hamming("0" * 16, "0" * 16)) == "same"
    assert site_captures.look_change(site_captures.hamming("0" * 16, "00000000000000ff")) == "small"
    assert site_captures.look_change(site_captures.hamming("0" * 16, "ffffffffffffffff")) == "new"
    assert site_captures.normalize_words("Copyright 2025  Alpha") == site_captures.normalize_words("copyright 2026 alpha")


@needs_sips
def test_the_wire_serves_the_thumbnail_and_says_which_full_images_are_here(bank):
    out = _record(bank, TOKEN_A, shots=[("viewport", DARK)])
    wire = site_captures.wire(bank, out["capture"])
    assert wire["thumb"]["url"] == f"/explore/captures/media-site00/{out['id']}/thumb"
    (viewport,) = wire["images"]
    assert viewport["onThisMac"] is True and viewport["url"].endswith("/image/viewport")
    path = site_captures.outside_root(bank) / f"{out['capture']['images'][0]['sha256']}.png"
    path.unlink()
    assert site_captures.wire(bank, out["capture"])["images"][0] == {**viewport, "onThisMac": False, "url": None}


def test_thumb_file_refuses_any_other_path(bank):
    assert site_captures.thumb_file(bank, "../../etc/passwd") is None
    assert site_captures.thumb_file(bank, "assets/design/x.jpg") is None
