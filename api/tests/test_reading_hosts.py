"""G166 (R-RW4, R-RW5, spec §7.2) — the closed host sets, pinned by
`fixtures/reading_hosts.json`: dot-boundary matching, every deny class, and the
two hosts that are walled and never offered. Pure string work; no DNS, no fetch."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import reading_hosts

CASES = json.loads((Path(__file__).parent / "fixtures" / "reading_hosts.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["url"] or "empty" for c in CASES])
def test_the_pinned_table(case):
    verdict = reading_hosts.classify(case["url"])
    assert (verdict.ok, verdict.cls, verdict.host_key) == (case["ok"], case["cls"], case["hostKey"]), case
    if not verdict.ok:
        assert verdict.reason and verdict.reason.endswith("."), "a refusal is one plain sentence"


def test_reddit_and_t_co_are_walled_and_never_a_switch():
    assert set(reading_hosts.AGENT_HOST_KEYS) == {"linkedin", "x", "facebook", "instagram", "tiktok"}
    for url in ("https://www.reddit.com/r/alpha", "https://t.co/abc", "https://redd.it/abc"):
        assert reading_hosts.is_walled(url) and reading_hosts.walled_key(url) is None
        assert not reading_hosts.agent_may_read(url, enabled=True, allowed_hosts=reading_hosts.AGENT_HOST_KEYS).ok


def test_a_lookalike_host_is_not_walled_and_a_short_host_is():
    assert not reading_hosts.is_walled("https://notx.com/a")
    assert not reading_hosts.is_walled("https://xx.com/a")
    assert reading_hosts.is_walled("https://lnkd.in/abc") and reading_hosts.is_walled("https://fb.watch/abc")
    assert reading_hosts.is_walled("https://a.b.x.com/a")


def test_the_agent_gate_needs_the_switch_and_then_the_site():
    url = "https://x.com/alpha/status/1"
    off = reading_hosts.agent_may_read(url, enabled=False, allowed_hosts=("x",))
    assert (off.ok, off.cls) == (False, "off") and "Agent reading is off" in off.reason
    no_site = reading_hosts.agent_may_read(url, enabled=True, allowed_hosts=())
    assert (no_site.ok, no_site.cls, no_site.host_key) == (False, "off", "x") and "X is not turned on" in no_site.reason
    assert reading_hosts.agent_may_read(url, enabled=True, allowed_hosts=("x",)).ok
    public = reading_hosts.agent_may_read("https://blog.bob-example.org/a", enabled=True, allowed_hosts=())
    assert public.ok and not public.walled and public.host_class == "public"


def test_a_tiktok_video_is_a_video_not_a_page_and_the_sheet_says_so():
    verdict = reading_hosts.classify("https://www.tiktok.com/@alpha/video/7300000000000000000")
    assert (verdict.ok, verdict.cls) == (False, "V") and "cicada_record_watch" in verdict.reason
    assert "video" in reading_hosts.HOST_NOTES["tiktok"].lower()


def test_a_video_or_paper_that_carries_a_secret_is_refused_for_the_secret_first():
    assert reading_hosts.classify("https://vimeo.com/123456789?token=abc").cls == "S"
    assert reading_hosts.classify("https://arxiv.org/abs/2401.00001?key=abc").cls == "S"


def test_display_host_is_plain_letters_only():
    assert reading_hosts.display_host("WWW.Blog.Bob-Example.org") == "blog.bob-example.org"
    assert reading_hosts.display_host("a<b>c.example") == "abc.example"
