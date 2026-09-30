"""G166 (ruling 14 amended 2026-09-30) — the reading queue is a read model: the person's asks,
plus saved wall pages of sites they allowed, computed at read and never fanned out as rows."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from _reading_fixtures import enable, put_page
from _synthetic_bank import _bank
from api.services import bank_index, media_ingestor, reading_asks, reading_queue, reading_settings, reading_walls

ART = "https://articles.paperfold.io/post/{}"


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    reading_walls.reset_memo()
    bank_index.invalidate()
    m = _bank(tmp_path)
    (m / "sources").mkdir(exist_ok=True)
    return m


def _h(url):
    return media_ingestor.url_hash(url)


def _files(root):
    return {p: p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()} if root.exists() else {}


def _urls(memory, **kw):
    return [e.url for e in reading_queue.entries(memory, **kw)]


def test_allowed_site_pages_are_queued_and_a_new_wall_page_joins_with_no_write(memory, tmp_path):
    put_page(memory, "a", ART.format(1), fetch_status="blocked")
    put_page(memory, "b", ART.format(2), fetch_status="blocked")
    put_page(memory, "other", "https://blog.elsewhere.io/x", fetch_status="blocked")
    enable(sites=("paperfold.io",))
    assert _urls(memory) == [ART.format(1), ART.format(2)]
    home = tmp_path / "home"
    before = _files(home)
    put_page(memory, "c", ART.format(3), fetch_status="interstitial")  # a page saved (and walled) later
    assert _urls(memory) == [ART.format(i) for i in (1, 2, 3)]
    assert _files(home) == before, "no write anywhere: a new wall page joins the queue by being read"
    e = reading_queue.entries(memory)[0]
    assert (e.origin, e.site, e.wall, e.host) == ("site", "paperfold.io", "refused", "articles.paperfold.io")


def test_site_off_or_master_off_dequeues_instantly(memory):
    put_page(memory, "a", "https://www.linkedin.com/in/alpha")
    enable(sites=("linkedin",))
    assert len(_urls(memory)) == 1
    reading_settings.update(sites={"linkedin": False})
    assert _urls(memory) == []
    reading_settings.update(sites={"linkedin": True}, surfaced={"linkedin"})
    assert len(_urls(memory)) == 1
    reading_settings.update(agent_enabled_=False)
    assert _urls(memory) == [] and reading_queue.count_waiting(memory) == 0


def test_an_explicit_ask_is_listed_before_site_entries(memory):
    put_page(memory, "old", ART.format(1), fetch_status="blocked", saved="2020-01-01")
    put_page(memory, "asked", "https://blog.elsewhere.io/asked")
    enable(sites=("paperfold.io",))
    reading_asks.ask(memory, _h("https://blog.elsewhere.io/asked"), host="blog.elsewhere.io", host_class="public")
    e = reading_queue.entries(memory)
    assert [(x.origin, x.url) for x in e] == [("ask", "https://blog.elsewhere.io/asked"), ("site", ART.format(1))]


def test_a_live_row_keeps_a_page_out_and_expiry_offers_it_once_more(memory):
    url = ART.format(1)
    put_page(memory, "a", url, fetch_status="blocked")
    enable(sites=("paperfold.io",))
    reading_asks.ask(memory, _h(url), host="articles.paperfold.io", host_class="public")
    reading_asks.record_outcome(memory, _h(url), "blocked")
    assert _urls(memory) == [], "a recorded outcome keeps the page out for its week"
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert _urls(memory, now=later) == [url], "after the row expires the page may be offered once more"


def test_needs_login_pauses_the_whole_site_until_the_row_expires(memory):
    for i in (1, 2, 3):
        put_page(memory, f"a{i}", ART.format(i), fetch_status="blocked")
    put_page(memory, "li", "https://www.linkedin.com/in/alpha")
    enable(sites=("paperfold.io", "linkedin"))
    reading_asks.record_outcome(memory, _h(ART.format(1)), "needs_login", create=True, origin="site",
                                host="articles.paperfold.io")
    assert _urls(memory) == ["https://www.linkedin.com/in/alpha"], "the agent was not signed in: the site pauses"
    later = datetime.now(timezone.utc) + timedelta(days=8)
    assert sorted(_urls(memory, now=later)) == sorted([ART.format(i) for i in (1, 2, 3)] + ["https://www.linkedin.com/in/alpha"])


def test_switching_a_site_on_again_clears_its_needs_login_pause_per_site_and_per_bank(memory, tmp_path):
    put_page(memory, "a", ART.format(1), fetch_status="blocked")
    put_page(memory, "b", ART.format(2), fetch_status="blocked")
    put_page(memory, "li", "https://www.linkedin.com/in/alpha")
    enable(sites=("paperfold.io", "linkedin"))
    for url, host in ((ART.format(1), "articles.paperfold.io"), ("https://www.linkedin.com/in/alpha", "linkedin.com")):
        reading_asks.record_outcome(memory, _h(url), "needs_login", create=True, origin="site", host=host)
    assert _urls(memory) == []
    assert reading_queue.resume_site(memory, "paperfold.io") == 1, "only that site's pause"
    assert _urls(memory) == [ART.format(1), ART.format(2)]
    # the ask store is per bank: another bank's pause is not this one's
    other = tmp_path / "other"
    other.mkdir()
    assert reading_queue.paused_sites(reading_asks.all_rows(memory)) == {"linkedin"}
    assert reading_asks.all_rows(other) == []


def test_chat_and_agent_saved_pages_need_sources_for_a_remote_caller(memory):
    put_page(memory, "saved", ART.format(1), fetch_status="blocked", origin="x-bookmarks")
    put_page(memory, "tg", ART.format(2), fetch_status="blocked", origin="telegram")
    put_page(memory, "mcp", ART.format(3), fetch_status="blocked", origin="mcp")
    put_page(memory, "chat", ART.format(4), fetch_status="blocked", origin="claude-export")
    put_page(memory, "bm", ART.format(5), fetch_status="blocked", origin="chrome-bookmark")
    put_page(memory, "none", ART.format(6), fetch_status="blocked", origin="")
    enable(sites=("paperfold.io",))
    assert len(_urls(memory)) == 6, "a local caller sees every allowed page"
    fenced = sorted(_urls(memory, include_words_origin=False))
    assert fenced == [ART.format(1), ART.format(5)], "only saved-content channels; the person's own words need `sources`"
    assert reading_queue.count_waiting(memory, include_words_origin=False) == 2


def test_authorizes_ask_site_or_none(memory):
    url, other = ART.format(1), ART.format(2)
    put_page(memory, "a", url, fetch_status="blocked")
    put_page(memory, "b", other, fetch_status="blocked")
    put_page(memory, "plain", "https://blog.paperfold.io/plain")
    put_page(memory, "li", "https://www.linkedin.com/in/alpha")
    assert reading_queue.authorizes(memory, url) is None, "master off"
    enable(sites=("paperfold.io",))
    assert reading_queue.authorizes(memory, url) == ("site", None)
    assert reading_queue.authorizes(memory, "https://blog.paperfold.io/plain") is None, "a saved public page: no wall"
    assert reading_queue.authorizes(memory, "https://www.linkedin.com/in/alpha") is None, "site not allowed"
    assert reading_queue.authorizes(memory, "https://never-saved.example.net/") is None
    reading_asks.ask(memory, _h("https://www.linkedin.com/in/alpha"), host="linkedin.com", host_class="walled")
    kind, row = reading_queue.authorizes(memory, "https://www.linkedin.com/in/alpha")
    assert kind == "ask" and row["state"] == "waiting", "an explicit ask needs no site permission"


def test_count_waiting_cold_cache_counts_rows_only_and_warms_in_the_background(memory):
    put_page(memory, "a", ART.format(1), fetch_status="blocked")
    put_page(memory, "asked", "https://blog.elsewhere.io/asked")
    enable(sites=("paperfold.io",))
    reading_asks.ask(memory, _h("https://blog.elsewhere.io/asked"), host="blog.elsewhere.io", host_class="public")
    bank_index.invalidate(memory)
    assert reading_queue.count_waiting(memory, warm_only=True) == 1, "cold: the ask row only, no page parsed"
    for t in [t for t in __import__("threading").enumerate() if t.name == "reading-warm"]:
        t.join(5)
    assert bank_index.is_warm(memory, "entities")
    assert reading_queue.count_waiting(memory, warm_only=True) == 2, "warm: the derived part counts too"


def test_a_slow_scan_is_never_run_by_the_hook_path(memory, monkeypatch):
    put_page(memory, "a", ART.format(1), fetch_status="blocked")
    enable(sites=("paperfold.io",))
    bank_index.invalidate(memory)

    def slow(*a, **k):
        raise AssertionError("the hook path scanned a cold bank")

    monkeypatch.setattr(reading_walls, "scan", slow)
    assert reading_queue.count_waiting(memory, warm_only=True) == 0


def test_site_rows_count_only_measured_things(memory):
    put_page(memory, "a", ART.format(1), fetch_status="blocked")
    put_page(memory, "b", ART.format(2), fetch_status="blocked")
    put_page(memory, "c", "https://news.paperfold.io/x", fetch_status="interstitial")
    put_page(memory, "li", "https://www.linkedin.com/in/alpha")
    put_page(memory, "tt", "https://www.tiktok.com/@alpha")
    put_page(memory, "done", "https://www.linkedin.com/in/done",
             read={"by": "agent", "at": "2026-09-30T00:00:00Z"})
    rows = {r["site"]: r for r in reading_queue.site_rows(memory)}
    assert set(rows) == {"paperfold.io", "linkedin", "tiktok"}
    pf = rows["paperfold.io"]
    assert (pf["waiting"], pf["wall"], pf["allowed"], pf["read"], pf["needsLogin"]) == (3, "refused", False, 0, 0)
    assert rows["linkedin"]["waiting"] == 1 and rows["linkedin"]["read"] == 1 and rows["linkedin"]["wall"] == "walled"
    assert rows["tiktok"]["note"] and "video" in rows["tiktok"]["note"].lower() and rows["linkedin"]["note"] is None
    assert rows["linkedin"]["iconHost"] == "linkedin.com" and rows["paperfold.io"]["iconHost"] == "paperfold.io"
    for r in rows.values():
        assert not any("http" in str(v) for v in r.values()), "hosts and numbers only"


def test_an_allowed_site_with_no_pages_is_still_listed_and_a_pause_is_counted(memory):
    enable(sites=("linkedin",))
    reading_asks.record_outcome(memory, _h("https://www.linkedin.com/in/x"), "needs_login", create=True,
                                origin="site", host="linkedin.com")
    (row,) = reading_queue.site_rows(memory)
    assert (row["site"], row["allowed"], row["waiting"], row["needsLogin"]) == ("linkedin", True, 0, 1)
    assert row["since"], "the day it was allowed"


def test_site_rows_never_evict_an_explicit_ask(memory):
    reading_asks.ask(memory, _h("https://blog.elsewhere.io/mine"), host="blog.elsewhere.io", host_class="public")
    for i in range(reading_asks.MAX_SITE_ROWS + 60):
        reading_asks.record_outcome(memory, f"{i:012x}", "failed", create=True, origin="site", host="x.com")
    rows = reading_asks.all_rows(memory)
    assert len([r for r in rows if r.get("origin") == "site"]) == reading_asks.MAX_SITE_ROWS
    assert any(r["url_hash"] == _h("https://blog.elsewhere.io/mine") and r["state"] == "waiting" for r in rows)


def test_sites_are_ordered_allowed_with_needs_login_first_then_by_waiting(memory):
    for i in range(3):
        put_page(memory, f"a{i}", f"https://articles.paperfold.io/{i}", fetch_status="blocked")
    put_page(memory, "li", "https://www.linkedin.com/in/alpha")
    put_page(memory, "ig", "https://www.instagram.com/alpha/")
    enable(sites=("instagram",))
    reading_asks.record_outcome(memory, _h("https://www.instagram.com/alpha/"), "needs_login", create=True,
                                origin="site", host="instagram.com")
    assert [r["site"] for r in reading_queue.site_rows(memory)] == ["instagram", "paperfold.io", "linkedin"]


def test_is_warm_compares_the_directory_and_goes_cold_after_a_rewrite(memory):
    put_page(memory, "a", ART.format(1), fetch_status="blocked")
    bank_index.invalidate(memory)
    assert bank_index.is_warm(memory, "entities") is False
    bank_index.files(memory, "entities")
    assert bank_index.is_warm(memory, "entities") is True
    from api.services import markdown_parser

    path = memory / "entities" / "media-a.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body + "\nmore\n")
    assert bank_index.is_warm(memory, "entities") is False, "a Sleep rewrite makes it cold again: no inline parse in the hook"
    put_page(memory, "b", ART.format(2))
    bank_index.files(memory, "entities")
    (memory / "entities" / "media-b.md").unlink()
    assert bank_index.is_warm(memory, "entities") is False
