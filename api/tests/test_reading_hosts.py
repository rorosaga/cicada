"""G166 (R-RW4, R-RW5, ruling 14 amended 2026-09-30) — the closed host sets, pinned by
`fixtures/reading_hosts.json`: dot-boundary matching, every deny class, the one host
that is walled and never offered (`t.co`), and the site key a permission is stored
under. Pure string work; no DNS, no fetch."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.services import reading_hosts

CASES = json.loads((Path(__file__).parent / "fixtures" / "reading_hosts.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[c["url"] or "empty" for c in CASES])
def test_the_pinned_table(case):
    verdict = reading_hosts.classify(case["url"])
    assert (verdict.ok, verdict.cls, verdict.site) == (case["ok"], case["cls"], case["site"]), case
    if not verdict.ok:
        assert verdict.reason and verdict.reason.endswith("."), "a refusal is one plain sentence"


def test_only_t_co_is_never_offered_and_reddit_is_a_site_like_any_other():
    """Owner 2026-09-30: limiting the sites makes no sense. Reddit is walled (the backend never
    requests it) and surfaces like any site; `t.co` is a redirector and is never offered."""
    assert set(reading_hosts.NEVER_OFFERED_DOMAINS) == {"t.co"}
    for url in ("https://www.reddit.com/r/alpha", "https://redd.it/abc"):
        assert reading_hosts.is_walled(url) and reading_hosts.site_of(url) == "reddit"
        assert reading_hosts.agent_may_read(url, enabled=True).ok
    assert reading_hosts.is_walled("https://t.co/abc")
    assert not reading_hosts.agent_may_read("https://t.co/abc", enabled=True).ok


def test_a_lookalike_host_is_not_walled_and_a_short_host_is():
    assert not reading_hosts.is_walled("https://notx.com/a")
    assert not reading_hosts.is_walled("https://xx.com/a")
    assert reading_hosts.is_walled("https://lnkd.in/abc") and reading_hosts.is_walled("https://fb.watch/abc")
    assert reading_hosts.is_walled("https://a.b.x.com/a")


def test_agent_may_read_needs_only_the_master_switch():
    """No per-site gate on an explicit ask: 'Ask an agent' on a page is the person's own consent
    for it. The site permission is a queue rule (reading_queue), never a refusal here."""
    url = "https://x.com/alpha/status/1"
    off = reading_hosts.agent_may_read(url, enabled=False)
    assert (off.ok, off.cls) == (False, "off") and "Agent reading is off" in off.reason
    on = reading_hosts.agent_may_read(url, enabled=True)
    assert on.ok and on.walled and on.host_class == "walled" and on.site == "x"
    public = reading_hosts.agent_may_read("https://blog.bob-example.org/a", enabled=True)
    assert public.ok and not public.walled and public.host_class == "public"


def test_a_tiktok_video_is_a_video_not_a_page_and_the_row_says_so():
    verdict = reading_hosts.classify("https://www.tiktok.com/@alpha/video/7300000000000000000")
    assert (verdict.ok, verdict.cls) == (False, "V") and "cicada_record_watch" in verdict.reason
    assert "video" in reading_hosts.SITE_NOTES["tiktok"].lower()


SITE_TABLE = [
    ("https://www.linkedin.com/in/a", "linkedin"), ("https://lnkd.in/x", "linkedin"),
    ("https://mobile.twitter.com/a", "x"), ("https://fb.watch/x", "facebook"),
    ("https://old.reddit.com/r/a", "reddit"), ("https://redd.it/a", "reddit"),
    ("https://www.paperfold.io/a", "paperfold.io"), ("https://articles.paperfold.io/a", "paperfold.io"),
    ("https://news.site-a.co.uk/x", "site-a.co.uk"), ("https://site-a.co.uk", "site-a.co.uk"),
    ("https://user.github.io/p", "user.github.io"), ("https://a.b.user.github.io/p", "user.github.io"),
    ("https://writer.substack.com/p/x", "writer.substack.com"), ("https://alpha.blogspot.com/x", "alpha.blogspot.com"),
    ("https://notx.com/a", "notx.com"), ("https://xx.com/a", "xx.com"), ("https://linkedin.com.evil.test/a", "evil.test"),
    ("paperfold.io", "paperfold.io"), ("WWW.Paperfold.IO", "paperfold.io"), ("192.168.1.5", "192.168.1.5"), ("", ""),
]


@pytest.mark.parametrize("raw,site", SITE_TABLE)
def test_site_of_folds_families_and_registrable_domains(raw, site):
    assert reading_hosts.site_of(raw) == site


def test_valid_site_key_refuses_junk_and_never_offered():
    for ok in ("linkedin", "x", "paperfold.io", "user.github.io", "site-a.co.uk"):
        assert reading_hosts.valid_site_key(ok), ok
    for bad in ("", " ", "-a.com", "Paperfold.io", "a b", "a/b", "a" * 81, "t.co", "sub.t.co", "a..b/../c", "http://a.com"):
        assert not reading_hosts.valid_site_key(bad), bad


def test_icon_hosts_cover_every_walled_family_and_only_public_names_are_looked_up():
    assert set(reading_hosts.ICON_HOSTS) == set(reading_hosts.WALLED_DOMAINS)
    assert reading_hosts.ICON_HOSTS["instagram"] == "www.instagram.com"  # the bare domain answers 404
    for family in reading_hosts.WALLED_DOMAINS:
        assert reading_hosts.icon_host(family) == reading_hosts.ICON_HOSTS[family]
    assert reading_hosts.icon_host("paperfold.io") == "paperfold.io"
    # the site key, never a saved subdomain, and never a private or tailnet name
    for private in ("box.tail1234.ts.net", "wiki.corp", "printer.local", "intranet", "192.168.1.5", "site.test"):
        assert not reading_hosts.is_public_name(private), private
        assert reading_hosts.icon_host(private) is None, private


def test_a_video_or_paper_that_carries_a_secret_is_refused_for_the_secret_first():
    assert reading_hosts.classify("https://vimeo.com/123456789?token=abc").cls == "S"
    assert reading_hosts.classify("https://arxiv.org/abs/2401.00001?key=abc").cls == "S"


def test_display_host_is_plain_letters_only():
    assert reading_hosts.display_host("WWW.Blog.Bob-Example.org") == "blog.bob-example.org"
    assert reading_hosts.display_host("a<b>c.example") == "abc.example"
