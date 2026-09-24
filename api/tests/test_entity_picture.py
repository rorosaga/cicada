"""G146 / G159 slice 1 — the picture precedence (plan R-PE3, R-PE9) and its inputs, pure.

`resolve` and the app's `EntityPictureResolver` run ONE table, `fixtures/entity_picture.json`: add a rung on one side
only and the other goes red (the `timeline_state.json` precedent)."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from api.services import entity_picture, papers
from api.services.entity_picture import PictureInputs, Resolved

CASES = json.loads((Path(__file__).parent / "fixtures" / "entity_picture.json").read_text(encoding="utf-8"))


def png_bytes(width: int, height: int) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00IEND\xaeB`\x82")


def jpeg_bytes(width: int, height: int) -> bytes:
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">HBHH", 17, 8, height, width) + b"\x03" + b"\x00" * 9
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_the_precedence_matches_the_shared_fixture(case):
    inputs = PictureInputs.from_wire(case["input"])
    assert entity_picture.resolve(case["id"], inputs) == Resolved(**case["expected"])
    assert entity_picture.detected(case["id"], inputs) == Resolved(**case["detected"])


def test_the_fixture_covers_every_rung_and_is_not_vacuous():
    assert len(CASES) >= 12
    assert set(entity_picture.SOURCES) | {None} <= {c["expected"]["source"] for c in CASES}


def test_inputs_read_the_persons_choice_and_nothing_a_hand_edit_invented():
    upload = {"type": "person", "picture": {"kind": "upload", "sha": "3f9a1c0b2d4e", "ext": "jpg", "added": "2026-09-24"}}
    assert entity_picture.inputs_for(upload) == PictureInputs(type="person", choice="upload", upload_sha="3f9a1c0b2d4e")
    assert entity_picture.inputs_for({"type": "company", "picture": {"kind": "initials"}}).choice == "initials"
    for junk in ("assets/pictures/bob-example.jpg", {"kind": "upload", "sha": "3f9a1c0b2d4e", "ext": "gif"},
                 {"kind": "upload", "sha": "../../x", "ext": "jpg"}, {"kind": "logo"}, ["upload"]):
        assert entity_picture.inputs_for({"type": "person", "picture": junk}).choice is None, junk
    contacts = {"type": "person", "contacts_photo": {"sha": "0a1b2c3d4e5f"}}
    assert entity_picture.inputs_for(contacts).contacts_sha == "0a1b2c3d4e5f"
    assert entity_picture.inputs_for({"type": "person", "contacts_photo": {"sha": "nope"}}).contacts_sha is None
    assert entity_picture.inputs_for({"name": "No Type"}).type == "concept"


def test_a_thumbnail_is_a_media_pages_own_and_never_a_papers():
    media = {"url": "https://video.example.com/v/1", "thumbnail": "https://img.example.com/1.jpg"}
    assert entity_picture.inputs_for({"type": "media", "media": media}).thumbnail == "https://img.example.com/1.jpg"
    paper = {"type": "media", "media": {"kind": entity_picture.PAPER_KIND, "thumbnail": "https://img.example.com/p.jpg"}}
    assert entity_picture.inputs_for(paper).thumbnail is None
    assert entity_picture.inputs_for({"type": "media", "media": {"thumbnail": "http://img.example.com/1.jpg"}}).thumbnail is None
    assert entity_picture.inputs_for({"type": "concept", "media": media}).thumbnail is None
    assert entity_picture.PAPER_KIND == papers.KIND


def test_the_logo_rung_is_for_brands_and_pages_that_name_one():
    assert entity_picture.logo_eligible({"type": "company"}) and entity_picture.logo_eligible({"type": "tool"})
    assert entity_picture.logo_eligible({"type": "concept", "logo": "https://acme.example"})
    assert not entity_picture.logo_eligible({"type": "concept"})
    assert not entity_picture.logo_eligible({"type": "person", "logo": "https://acme.example"}), "a surname is not a domain"
    assert not entity_picture.logo_eligible({"type": "media", "logo": "https://acme.example"})
    assert entity_picture.inputs_for({"type": "concept"}, logo_available=True).logo is False, \
        "eligibility is decided here, never by the caller"


def test_a_logo_is_available_when_cached_or_not_yet_known_to_miss():
    fm = {"type": "company", "name": "Acme"}   # a single-token company: `acme.com` is guessable (G59)
    kw = {"page_mtime": 1000.0}
    assert entity_picture.logo_available("acme", fm, "", cached={"acme"}, missed={}, **kw)
    assert entity_picture.logo_available("acme", fm, "", cached=set(), missed={}, **kw), "never asked: the card may ask"
    assert not entity_picture.logo_available("acme", fm, "", cached=set(), missed={"acme": 2000.0}, **kw)
    assert entity_picture.logo_available("acme", fm, "", cached=set(), missed={"acme": 500.0}, **kw), \
        "a page edited after its miss is re-resolved (page_edited_since_fetch's rule)"
    two_words = {"type": "company", "name": "Acme Example"}
    assert not entity_picture.logo_available("acme-example", two_words, "", cached=set(), missed={}, **kw), \
        "nothing to fetch"
    person = {"type": "person", "name": "Bob"}
    assert not entity_picture.logo_available("bob", person, "", cached={"bob"}, missed={}, **kw)


def test_headers_are_read_never_decoded():
    assert entity_picture.sniff(png_bytes(40, 30)) == "png"
    assert entity_picture.dimensions(png_bytes(40, 30)) == (40, 30)
    assert entity_picture.sniff(jpeg_bytes(640, 480)) == "jpg"
    assert entity_picture.dimensions(jpeg_bytes(640, 480)) == (640, 480)
    assert entity_picture.sniff(b"GIF89a\x01\x00\x01\x00") is None
    assert entity_picture.sniff(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None
    assert entity_picture.dimensions(b"\xff\xd8\xff") is None
    assert entity_picture.sha12(b"abc") == "ba7816bf8f01", "the app's PreparedPicture.sha hashes the same bytes the same way"
    assert entity_picture.day("2026-09-20") == "2026-09-20" and entity_picture.day("soon") is None


def test_paths_are_derived_from_the_id_and_never_leave_their_folder(tmp_path, monkeypatch):
    assert entity_picture.upload_rel("bob-example", "jpg") == "assets/pictures/bob-example.jpg"
    expected = (tmp_path / "assets" / "pictures" / "bob-example.png").resolve()
    assert entity_picture.upload_path(tmp_path, "bob-example", "png") == expected
    assert entity_picture.upload_path(tmp_path, "bob-example", "gif") is None
    assert entity_picture.upload_path(tmp_path, "../escape", "png") is None
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    seam = (tmp_path / "home" / "contacts" / "work" / "bob-example.jpg").resolve()
    assert entity_picture.contacts_path("work", "bob-example") == seam
    assert not (tmp_path / "home").exists(), "reading the seam never creates anything"
