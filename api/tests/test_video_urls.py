"""The URL → video classification table (Track V, R-V8 / plan R1-R5).

One fixture, two suites: this file and
``app/CicadaApp/Tests/CicadaAppTests/VideoRefTests.swift`` read the SAME
``api/tests/fixtures/video_urls.json``. Add a provider on one side only and
the other side goes red — the "ship both halves together" rule applied to a
classification table instead of an ETag.

Hermetic by construction: ``video_urls.resolve`` does no I/O and no network,
so there is nothing to stub. A shortlink whose id is only recoverable by
following a redirect stays ``external`` rather than being resolved by a fetch
(R4) — read-time classification never reaches the network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import video_urls

FIXTURE = Path(__file__).parent / "fixtures" / "video_urls.json"


def _cases() -> list[dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = data["cases"]
    assert len(cases) >= 40, "the fixture shrank — a table test that reads 0 rows passes vacuously"
    return cases


@pytest.mark.parametrize("case", _cases(), ids=lambda c: c["url"][:60] or "<empty>")
def test_resolve_matches_the_shared_fixture(case):
    ref = video_urls.resolve(case["url"])
    if case["provider"] is None:
        assert ref is None, f"{case['url']} should not classify as a video ({case['why']})"
        return
    assert ref is not None, f"{case['url']} should classify ({case['why']})"
    assert ref.provider == case["provider"]
    assert ref.kind == case["kind"]
    assert ref.video_id == case["videoId"]
    assert ref.embed_url == case["embedUrl"]
    assert ref.watch_url == case["url"]


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not a url", "http://", "https://", "file://", "javascript:alert(1)//a.mp4",
     "mailto:someone@example.com", "https://" + "a" * 10_000 + ".com/clip.mp4", "://broken"],
)
def test_resolve_is_total_and_never_raises(raw):
    # R2: a classifier that can throw would take a Feed row down with it.
    video_urls.resolve(raw)


def test_a_very_long_but_valid_direct_file_url_still_classifies():
    url = "https://example.com/" + "a" * 5_000 + "/clip.mp4"
    ref = video_urls.resolve(url)
    assert ref is not None and ref.kind == "file" and ref.provider == "direct"


def test_embed_url_is_only_ever_set_for_an_embed_kind():
    for case in _cases():
        if case["kind"] != "embed":
            assert case["embedUrl"] is None, case["url"]


def test_is_direct_file_agrees_with_resolve():
    for case in _cases():
        expected = case["kind"] == "file"
        assert video_urls.is_direct_file(case["url"]) is expected, case["url"]


def test_every_fixture_provider_is_declared_in_the_module():
    # The fixture is the contract; PROVIDERS is what the module admits it can
    # produce. A provider named in one and not the other is exactly the drift
    # R-V8 exists to prevent, and it must fail here rather than at a call site.
    named = {c["provider"] for c in _cases() if c["provider"]}
    assert named <= video_urls.PROVIDERS
    assert set(video_urls.OEMBED_PROVIDERS) <= video_urls.PROVIDERS
