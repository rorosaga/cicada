"""G166 (ruling 14 amended 2026-09-30) — an agent may record an outcome for a saved wall page of a
site the person allowed, with no per-page ask; the anti-plant rule survives everywhere else.

`needs_login` and the other non-read outcomes touch only the machine-wide ask store (a row with
`origin: site`); a `read` writes the page, an episode and a commit as before, and leaves no ask row."""
from __future__ import annotations

from _reading_fixtures import SUMMARY, enable, git_log, ids, page, porcelain, put_page, reading, record  # noqa: F401
from api.services import media_ingestor, reading_asks

ART = "https://articles.paperfold.io/post/1"


def _h(url):
    return media_ingestor.url_hash(url)


def test_agent_can_record_needs_login_for_a_site_permitted_page_without_an_ask(reading):
    server, memory = reading
    put_page(memory, "a", ART, fetch_status="blocked")
    enable(sites=("paperfold.io",))
    tree = (git_log(memory, 3), porcelain(memory))
    out = record(server, url=ART, outcome="needs_login")
    assert out.startswith("Recorded: the person needs to sign in to articles.paperfold.io")
    row = reading_asks.get(memory, _h(ART))
    assert row["state"] == "needs_login" and row["origin"] == "site" and row["host"] == "articles.paperfold.io"
    assert (git_log(memory, 3), porcelain(memory)) == tree, "ask store only: no bank write, no commit"


def test_it_succeeds_while_sleep_runs(reading, monkeypatch):
    from api.services import mcp_tools

    server, memory = reading
    put_page(memory, "a", ART, fetch_status="blocked")
    enable(sites=("paperfold.io",))
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda *a, **k: True)
    assert record(server, url=ART, outcome="failed").startswith("Recorded:")


def test_read_on_a_site_page_writes_page_episode_claim_and_no_ask_row(reading):
    server, memory = reading
    eid = put_page(memory, "a", ART, fetch_status="blocked")
    enable(sites=("paperfold.io",))
    out = record(server, url=ART)
    got_eid, ep, cid = ids(out)
    assert got_eid == eid and (memory / "episodes" / f"{ep}.md").exists()
    assert page(memory, eid).frontmatter["read"]["by"] == "agent"
    assert reading_asks.get(memory, _h(ART)) is None, "the page's own read: stamp keeps it out of the queue"
    assert "Recorded your read" in out and "entities/" not in porcelain(memory), "the read is committed"
    assert "Cicada-Author: claude-code" in git_log(memory, 1)
    # ...and the page is no longer waiting
    from api.services import reading_queue

    assert reading_queue.entries(memory) == []
    assert record(server, url=ART).startswith("Not recorded"), "a second read of a page that holds words needs an ask"


def test_a_read_after_a_site_origin_outcome_drops_that_row(reading):
    server, memory = reading
    put_page(memory, "a", ART, fetch_status="blocked")
    enable(sites=("paperfold.io",))
    record(server, url=ART, outcome="failed")
    assert reading_asks.get(memory, _h(ART))["origin"] == "site"
    assert record(server, url=ART).startswith("Recorded your read")
    assert reading_asks.get(memory, _h(ART)) is None


def test_a_page_on_a_site_that_is_not_allowed_is_still_refused(reading):
    server, memory = reading
    put_page(memory, "a", ART, fetch_status="blocked")
    enable(sites=())
    for outcome in ("needs_login", "read"):
        out = record(server, url=ART, outcome=outcome)
        assert out.startswith("Not recorded:") and "asked about, or a page from a site they allowed" in out
    assert reading_asks.get(memory, _h(ART)) is None


def test_a_saved_public_page_with_no_wall_is_still_refused(reading):
    """The anti-plant rule: a site permission is for pages Cicada's reader could not read."""
    server, memory = reading
    put_page(memory, "a", "https://articles.paperfold.io/fine", fetch_status="ok")
    put_page(memory, "b", "https://articles.paperfold.io/plain")
    enable(sites=("paperfold.io",))
    for url in ("https://articles.paperfold.io/fine", "https://articles.paperfold.io/plain"):
        for outcome in ("needs_login", "blocked", "read"):
            assert record(server, url=url, outcome=outcome).startswith("Not recorded:")
        assert reading_asks.get(memory, _h(url)) is None
    assert not list((memory / "episodes").glob("*page-read*"))


def test_a_denied_class_on_an_allowed_site_is_refused(reading):
    server, memory = reading
    put_page(memory, "v", "https://www.tiktok.com/@alpha/video/7300000000000000000", fetch_status="blocked")
    put_page(memory, "s", "https://articles.paperfold.io/a?token=abc", fetch_status="blocked")
    enable(sites=("tiktok", "paperfold.io"))
    assert record(server, url="https://www.tiktok.com/@alpha/video/7300000000000000000", outcome="failed"
                  ).startswith("Not recorded:")
    assert "secret" in record(server, url="https://articles.paperfold.io/a?token=abc", outcome="failed")


def test_a_page_with_words_is_not_recordable_without_an_ask(reading):
    server, memory = reading
    text = ("A saved post whose text the connector already brought in, a couple of sentences long. It says things "
            "about the notes index and where the vectors live, and it says them at some length.")
    put_page(memory, "a", "https://x.com/alpha/status/9", origin="x-bookmarks", body=f"## Description\n\n{text}\n")
    enable(sites=("x",))
    assert record(server, url="https://x.com/alpha/status/9", outcome="needs_login").startswith("Not recorded:")
