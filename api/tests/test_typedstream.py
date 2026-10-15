"""G179 — a Messages ``attributedBody`` blob decodes to its words, on blobs built the way macOS builds them.

The real blobs come from ``NSArchiver`` on macOS 26.6.2 (``fixtures/imessage_attributed_bodies.swift``): plain text,
no attributes, emoji and accents, attachment placeholders, a link attribute, the one/two/four-byte length forms (127,
128, 129, 300, 40,000 and 70,000 characters) and a multi-line message. Synthetic words only."""
from __future__ import annotations

import pytest

from _imessage_fixtures import attributed_body, blob_cases
from api.services import typedstream

CASES = blob_cases()


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_every_real_blob_decodes_to_its_words(case):
    assert typedstream.decode(case["blob"]) == case["text"]


@pytest.mark.parametrize("case", [c for c in CASES if c["name"] != "with_link"], ids=lambda c: c["name"])
def test_the_test_builder_is_byte_for_byte_what_nsarchiver_writes(case):
    # So a synthetic chat.db's blobs are the real format, not a lookalike the decoder happens to read.
    assert attributed_body(case["text"], attributes=case["name"] != "no_attributes") == case["blob"]


def test_the_length_forms_are_the_ones_measured():
    by = {c["name"]: c["blob"] for c in CASES}
    tag = b"\x84\x01+"
    assert by["len_127"][by["len_127"].find(tag) + 3] == 0x7F
    assert by["len_128"][by["len_128"].find(tag) + 3] == 0x81
    assert by["len_40000"][by["len_40000"].find(tag) + 3] == 0x82


def test_attachment_placeholders_stay_in_the_words_and_leave_the_visible_text():
    by = {c["name"]: c for c in CASES}
    assert typedstream.decode(by["attachment_only"]["blob"]) == "￼"
    assert typedstream.visible_text(typedstream.decode(by["attachment_only"]["blob"])) == ""
    assert typedstream.visible_text(typedstream.decode(by["attachment_and_text"]["blob"])) == (
        "Here is the plan for alpha-project.")


@pytest.mark.parametrize("bad", [
    b"", b"not a typedstream", b"\x04\x0bstreamtyped\x81\xe8\x03", None,
    # A header and a class chain but the bytes cut short.
    attributed_body("a long enough message to cut")[:60],
])
def test_anything_else_is_none_never_an_exception(bad):
    assert typedstream.decode(bad) is None


def test_a_length_past_the_end_is_none():
    blob = bytearray(attributed_body("short"))
    at = blob.find(b"\x84\x01+") + 3
    blob[at] = 0x7F  # claims 127 bytes…
    blob = bytes(blob[: at + 10])  # …and only 9 follow
    assert typedstream.decode(blob) is None


def test_invalid_utf8_is_replaced_not_raised():
    blob = attributed_body("abc")
    at = blob.find(b"abc")
    broken = blob[:at] + b"\xff\xfe\xfd" + blob[at + 3:]
    assert typedstream.decode(broken) == "���"
