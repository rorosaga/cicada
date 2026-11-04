"""The lean pass (ruling 62, owner 2026-11-04): a save with no reason is indexed, found when it comes up, and read once
when the person talks about it. Measured: 25 bookmarks cost 58 model calls and 272k input tokens to learn little beyond
each title. Synthetic banks, placeholder titles and example.com links only."""
from __future__ import annotations

import asyncio
import time

import pytest

from _synthetic_bank import _bank, _entity
from drain_harness import git, install, seed_bank, settings

from api.services import (bank_index, history_index, link_enrichment, link_recon, markdown_parser, media_ingestor,
                          saved_lookup, saved_mentions, search_index, sleep_cycle, sleep_drain, sleep_progress,
                          source_overview, tab_groups)
from api.services.media_ingestor import MediaMeta, PreparedItem, RawItem

AT = "2026-11-04T10:00:00+00:00"


@pytest.fixture(autouse=True)
def _fresh():
    bank_index.invalidate()
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def _save(memory, url, title, *, origin="chrome-bookmark", idx=None, description="", **kw):
    item = RawItem(url=url, title=title, origin=origin, **kw)
    meta = MediaMeta(title=title, description=description, site="example.com", media_type="bookmark")
    res = media_ingestor.write_prepared(PreparedItem(item, meta), memory, idx if idx is not None else {})
    bank_index.invalidate()
    return res.episode_id, res.media_entity_id


def _fm(memory, episode_id):
    return markdown_parser.parse(memory / "episodes" / f"{episode_id}.md").frontmatter


def _conversation(memory, eid, body, **fm):
    base = {"id": eid, "timestamp": AT, "processed": False, "source": "claude-code", "harness": "claude-code",
            "session_id": f"ses_{eid}", "title": "A conversation"}
    base.update(fm)
    path = memory / "episodes" / f"{eid}.md"
    markdown_parser.write(path, base, body)
    bank_index.invalidate()
    return {"id": eid, "content": body, "origin": "claude-code", "filepath": path, "words_of": None, "gaps": ()}


# --- what is lean ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("fm", "kind"), [
    ({"origin": "chrome-bookmark", "url": "u", "media_entity_id": "m", "processed": False}, "saved"),
    ({"origin": "safari-bookmark", "processed": False}, "saved"),
    ({"origin": "saved-link", "url": "u", "media_entity_id": "m", "processed": False}, "saved"),
    ({"origin": "rss", "url": "u", "media_entity_id": "m", "processed": False}, "saved"),
    ({"origin": "reddit-saved", "folder": "r/example", "url": "u", "media_entity_id": "m", "processed": False}, "saved"),
    ({"source": "tab-group", "origin": "chrome-tab-group", "processed": False}, "saved"),
    ({"source": "bookmark", "url": "u", "media_entity_id": "m", "processed": True, "processed_by": "index"}, "saved"),
    # A reason, a note, an answer: read like any conversation.
    ({"origin": "chrome-bookmark", "url": "u", "media_entity_id": "m", "processed": False, "has_note": True}, None),
    ({"origin": "chrome-bookmark", "url": "u", "media_entity_id": "m", "processed": False,
      "saved_why": {"text": "the layout"}}, None),
    # Read before this ruling: it keeps what it made and stays as it was.
    ({"origin": "chrome-bookmark", "url": "u", "media_entity_id": "m", "processed": True, "processed_by": "sleep"}, None),
    ({"origin": "chrome-bookmark", "url": "u", "media_entity_id": "m", "processed": True}, None),
    # Woken: the read happens once and is a normal one.
    ({"origin": "chrome-bookmark", "url": "u", "media_entity_id": "m", "processed": False,
      "read_asked": {"why": "said-the-link", "at": AT}}, None),
    # Not a save, though each carries the page's link.
    ({"source": "page-read", "origin": "mcp", "url": "u", "media_entity_id": "m", "processed": True,
      "processed_by": "agent"}, None),
    ({"source": "video-watch", "origin": "mcp", "url": "u", "media_entity_id": "m", "processed": False}, None),
    ({"origin": "goodreads", "book": {"isbn": "1"}, "url": "u", "media_entity_id": "m", "processed": False}, None),
    # A conversation stays a conversation.
    ({"source": "claude-code", "harness": "claude-code", "session_id": "ses", "processed": False}, None),
    ({"origin": "telegram", "source": "telegram", "processed": False}, None),
])
def test_what_is_lean(fm, kind):
    assert history_index.kind(fm) == kind
    assert history_index.waits_for_model(fm) is (kind is None and not fm.get("processed", False))


def test_a_bare_save_lands_read_and_a_save_with_a_reason_or_note_waits(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    bare, page = _save(memory, "https://example.com/a", "Bare bookmark title", idx=idx)
    assert (_fm(memory, bare)["processed"], _fm(memory, bare)["processed_by"]) == (True, "index")
    assert (memory / "entities" / f"{page}.md").exists()   # still a saved page in Saved, with its link views
    why, _ = _save(memory, "https://example.com/b", "Saved with a reason", idx=idx, reason="for the layout")
    note, _ = _save(memory, "https://example.com/c", "Saved with a note", idx=idx, note="check this later")
    for eid in (why, note):
        assert _fm(memory, eid)["processed"] is False and _fm(memory, eid)["has_note"] is True
        assert history_index.waits_for_model(_fm(memory, eid))


def test_a_note_on_a_link_already_saved_is_read_and_the_save_stays_indexed(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    bare, page = _save(memory, "https://example.com/a", "Bare bookmark title", idx=idx)
    existing = media_ingestor.IngestResult(status="duplicate", media_entity_id=page, episode_id=bare,
                                           title="Bare bookmark title", media_type="bookmark")
    noted = media_ingestor.write_note_episode(
        memory, RawItem(url="https://example.com/a", note="worth reading for the intro", origin="saved-link"), existing)
    assert noted is not None
    assert history_index.waits_for_model(_fm(memory, noted[0])) is True
    assert history_index.kind(_fm(memory, bare)) == "saved"


def test_a_tab_group_is_indexed_when_captured_and_when_it_changes(tmp_path):
    memory = _bank(tmp_path)

    def sync(tabs):
        return tab_groups.sync(memory, {"browser": "chrome", "profile": "Default", "groups": [
            {"title": "Alpha research", "color": "blue", "saved_guid": "guid-1",
             "tabs": [{"title": t, "url": f"https://example.com/{t}"} for t in tabs]}]})

    assert sync(["one"])["created"] == 1
    path = next(p for p in (memory / "episodes").glob("*.md")
                if markdown_parser.parse(p).frontmatter.get("source") == "tab-group")
    assert markdown_parser.parse(path).frontmatter["processed_by"] == "index"
    bank_index.invalidate()
    assert sync(["one", "two"])["updated"] == 1
    fm = markdown_parser.parse(path).frontmatter
    assert (fm["processed"], fm["processed_by"]) == (True, "index")
    assert history_index.waits_for_model(fm) is False


# --- what is already in a bank ---------------------------------------------------------------------------------------


def _queued(memory, eid, body="# A title\n\n**URL:** https://example.com/a", **fm):
    base = {"id": eid, "timestamp": AT, "processed": False, "source": "bookmark", "origin": "chrome-bookmark",
            "url": f"https://example.com/{eid}", "media_entity_id": f"media-{eid}", "title": "A saved title"}
    base.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", base, body)


def test_retire_takes_what_waits_and_leaves_what_a_model_read_as_it_was(tmp_path):
    memory = _bank(tmp_path)
    _entity(memory, "media-ep_2026-08-01_001", type="media", media={"url": "u"}, source_episodes=["ep_2026-08-01_001"])
    _queued(memory, "ep_2026-08-01_001")
    _queued(memory, "ep_2026-08-01_002", processed=True, processed_by="sleep")
    read_before = (memory / "episodes" / "ep_2026-08-01_002.md").read_bytes()
    _queued(memory, "ep_2026-08-01_003", body="# A title\n\n## Note\nassistant: the intro is what matters")
    _queued(memory, "ep_2026-08-01_004", body="# A title\n\n## Saved because\nfor the layout")
    out = history_index.retire(memory)
    assert out.by_kind == {"saved": 1} and out.returned == 2
    assert (memory / "episodes" / "ep_2026-08-01_002.md").read_bytes() == read_before
    assert _fm(memory, "ep_2026-08-01_001")["processed_by"] == "index"
    bank_index.invalidate()
    waiting = {e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)}
    assert {"ep_2026-08-01_003", "ep_2026-08-01_004"} <= waiting and "ep_2026-08-01_001" not in waiting


def test_a_queued_save_whose_page_a_conversation_already_lit_gets_its_read(tmp_path):
    memory = _bank(tmp_path)
    eid = "ep_2026-08-01_001"
    _conversation(memory, "ep_2026-08-02_001", "user: that article on tides")
    _entity(memory, f"media-{eid}", type="media", media={"url": "u"},
            source_episodes=[eid, "ep_2026-08-02_001"])
    _queued(memory, eid)
    bank_index.invalidate()
    out = history_index.retire(memory)
    assert out.returned == 1 and not out.by_kind
    fm = _fm(memory, eid)
    assert fm["read_asked"]["why"] == saved_mentions.WHY_LIT and history_index.waits_for_model(fm)


def test_a_first_run_commits_alone_with_no_engine_and_no_model_ever_sees_a_save(tmp_path, monkeypatch):
    """The 371 waiting bookmarks: one `cicada` commit, nothing asked of an engine, no question, no page, no claim."""
    rig = install(monkeypatch)
    pages_before = {}

    def extra(memory):
        for i in range(1, 6):
            eid = f"ep_2026-08-01_{i:03d}"
            _queued(memory, eid)
            markdown_parser.write(memory / "entities" / f"media-{eid}.md",
                                  {"name": f"Saved item {i}", "type": "media", "status": "active", "confidence": 0.7,
                                   "created": "2026-08-01", "last_referenced": "2026-08-01",
                                   "media": {"url": f"https://example.com/{eid}"}, "source_episodes": [eid]},
                                  "## Summary\nSaved bookmark.\n")
        pages_before.update({p.name: p.read_bytes() for p in (memory / "entities").glob("*.md")})

    memory = seed_bank(tmp_path, [], extra=extra)
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=25), "sleep_lean",
                                user_triggered=True, drain=True))
    assert rig.extract_batches == []
    log = git(memory, "log", "--format=%s%n%b%x00")
    entry = next(c for c in log.split("\x00") if c.strip().startswith("Indexed without a model"))
    assert "Cicada-Author: cicada" in entry and "Cicada-Engine" not in entry
    assert git(memory, "status", "--porcelain").strip() == ""
    assert {p.name: p.read_bytes() for p in (memory / "entities").glob("*.md")} == pages_before
    assert not list((memory / "inbox").glob("*")) if (memory / "inbox").exists() else True
    assert sleep_progress.unprocessed_ids(memory) == {}


# --- the way back: read once, when the person talks about it ---------------------------------------------------------


def _bank_with_saves(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    a, _ = _save(memory, "https://example.com/crdts", "CRDTs for local-first apps", idx=idx)
    b, _ = _save(memory, "https://example.com/tides", "How tide tables are computed", idx=idx)
    c, _ = _save(memory, "https://example.com/two", "Reading list", idx=idx)
    return memory, a, b, c


def test_their_own_words_naming_the_link_or_the_whole_title_wake_it_once(tmp_path):
    memory, a, b, c = _bank_with_saves(tmp_path)
    by_link = _conversation(memory, "ep_2026-12-01_001", "user: have a look at https://example.com/crdts, it is good")
    by_title = _conversation(memory, "ep_2026-12-01_002", "user: I read how tide tables are computed last night")
    paths = saved_mentions.wake_mentioned(memory, [by_link, by_title], at=AT)
    assert sorted(paths) == sorted([f"episodes/{a}.md", f"episodes/{b}.md"])
    assert _fm(memory, a)["read_asked"] == {"why": saved_mentions.WHY_LINK, "at": AT}
    assert _fm(memory, b)["read_asked"]["why"] == saved_mentions.WHY_TITLE
    for eid in (a, b):
        assert history_index.waits_for_model(_fm(memory, eid))
        assert "processed_by" not in _fm(memory, eid)
    # Read once: after Sleep's read it is a read episode, and a second mention does nothing.
    bank_index.invalidate()
    ep = next(e for e in sleep_cycle._get_unprocessed_episodes(memory) if e["id"] == a)
    assert sleep_cycle._mark_episodes_processed([ep]) == 1
    assert _fm(memory, a)["processed_by"] == "sleep" and history_index.kind(_fm(memory, a)) is None
    bank_index.invalidate()
    assert saved_mentions.wake_mentioned(memory, [by_link], at=AT) == []
    # A title of two words is no name.
    other = _conversation(memory, "ep_2026-12-01_003", "user: my reading list is long")
    assert saved_mentions.wake_mentioned(memory, [other], at=AT) == []
    assert history_index.kind(_fm(memory, c)) == "saved"


@pytest.mark.parametrize("body", [
    "user: thanks\nassistant: you could read https://example.com/crdts or how tide tables are computed",
    "user: what do tide tables look like",
    "user: something about crdts for apps",
])
def test_an_agent_saying_it_or_a_shared_word_wakes_nothing(tmp_path, body):
    memory, a, b, _c = _bank_with_saves(tmp_path)
    conv = _conversation(memory, "ep_2026-12-01_001", body)
    assert saved_mentions.wake_mentioned(memory, [conv], at=AT) == []
    assert history_index.kind(_fm(memory, a)) == history_index.kind(_fm(memory, b)) == "saved"


def test_a_paste_of_many_links_wakes_only_the_first_few(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    urls = [f"https://example.com/p{i}" for i in range(9)]
    for i, url in enumerate(urls):
        _save(memory, url, f"Item {i}", idx=idx)
    conv = _conversation(memory, "ep_2026-12-01_001", "user: " + " ".join(urls))
    assert len(saved_mentions.wake_mentioned(memory, [conv], at=AT)) == saved_mentions.MAX_WAKES_PER_CONVERSATION


def test_a_lit_page_wakes_its_indexed_save_and_an_untouched_one_costs_nothing(tmp_path):
    memory, a, b, _c = _bank_with_saves(tmp_path)
    _conversation(memory, "ep_2026-12-01_001", "user: that piece on local-first", processed=True, processed_by="sleep")
    page = _fm(memory, a)["media_entity_id"]
    parsed = markdown_parser.parse(memory / "entities" / f"{page}.md")
    parsed.frontmatter["source_episodes"] = [a, "ep_2026-12-01_001"]
    time.sleep(0.01)
    markdown_parser.write(memory / "entities" / f"{page}.md", parsed.frontmatter, parsed.body)
    bank_index.invalidate()
    assert saved_mentions.wake_lit(memory, at=AT) == [f"episodes/{a}.md"]
    assert _fm(memory, a)["read_asked"]["why"] == saved_mentions.WHY_LIT
    assert history_index.kind(_fm(memory, b)) == "saved"


def test_a_removed_save_never_wakes(tmp_path):
    memory, a, _b, _c = _bank_with_saves(tmp_path)
    parsed = markdown_parser.parse(memory / "episodes" / f"{a}.md")
    parsed.frontmatter["source_deleted_at"] = AT
    markdown_parser.write(memory / "episodes" / f"{a}.md", parsed.frontmatter, parsed.body)
    assert history_index.wake(memory, a, saved_mentions.WHY_LINK, AT) is None


def test_a_woken_save_is_read_as_the_page_never_as_the_person(tmp_path):
    from api.services import authorship, evidence

    memory, a, _b, _c = _bank_with_saves(tmp_path)
    assert history_index.wake(memory, a, saved_mentions.WHY_LINK, AT)
    bank_index.invalidate()
    ep = next(e for e in sleep_cycle._get_unprocessed_episodes(memory) if e["id"] == a)
    assert authorship.of_episode(ep) == evidence.SAVE_KIND
    assert all(t.role != "user" for t in evidence.turns(ep["content"], override=evidence.SAVE_KIND))


def test_a_batch_wakes_what_its_conversation_named_and_the_next_run_reads_it(tmp_path, monkeypatch):
    rig = install(monkeypatch)

    def extra(memory):
        _queued(memory, "ep_2026-08-01_001", title="CRDTs for local-first apps", url="https://example.com/crdts")
        markdown_parser.write(memory / "episodes" / "ep_2026-09-01_100.md",
                              {"id": "ep_2026-09-01_100", "processed": False, "source": "claude-code",
                               "timestamp": "2026-09-01T11:00:00", "session_id": "ses_2026-09-01_abcdef01"},
                              "user: I keep coming back to https://example.com/crdts for this")

    memory = seed_bank(tmp_path, [], extra=extra)
    run = settings(memory, sleep_max_episodes_per_cycle=25)
    asyncio.run(sleep_cycle.run(run, "sleep_a", user_triggered=True, drain=True))
    assert [i for b in rig.extract_batches for i in b] == ["ep_2026-09-01_100"]
    fm = _fm(memory, "ep_2026-08-01_001")
    assert fm["read_asked"]["why"] == saved_mentions.WHY_LINK and history_index.waits_for_model(fm)
    assert git(memory, "status", "--porcelain").strip() == ""
    asyncio.run(sleep_cycle.run(run, "sleep_b", user_triggered=True, drain=True))
    assert rig.extract_batches[-1] == ["ep_2026-08-01_001"]
    assert _fm(memory, "ep_2026-08-01_001")["processed_by"] == "sleep"
    bank_index.invalidate()
    assert sleep_progress.unprocessed_ids(memory) == {}


# --- no model describes it, relates it or asks about it --------------------------------------------------------------


def test_link_enrichment_and_recon_pass_over_a_bare_saves_page(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    long = "A long description the page gave of itself. It says what the page is about, at length, in two sentences."
    bare, bare_page = _save(memory, "https://example.com/a", "Bare bookmark", idx=idx, description=long * 2)
    why, why_page = _save(memory, "https://example.com/b", "With a reason", idx=idx, description=long * 2,
                          reason="for the layout")
    run = settings(memory, link_enrich_min_desc_len=120)
    assert link_enrichment.lean_page(memory, markdown_parser.parse(memory / "entities" / f"{bare_page}.md").frontmatter)
    assert {p.stem for p in link_enrichment._candidates(memory, 20)} == {why_page}
    scan = link_enrichment.scan_backfill(memory, run)
    assert {c.media_id for c in (*scan.reuse, *scan.fetch, *scan.reason)} == {why_page}
    assert {c.media_id for c in link_recon.scan_recon(memory, run)} == {why_page}
    # A page it got its read on is an ordinary page again.
    assert history_index.wake(memory, bare, saved_mentions.WHY_LINK, AT)
    bank_index.invalidate()
    assert not link_enrichment.lean_page(
        memory, markdown_parser.parse(memory / "entities" / f"{bare_page}.md").frontmatter)


# --- findable: recall, Ask and the hook ------------------------------------------------------------------------------


@pytest.fixture
def found(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    for slug, title in (("crdts", "CRDTs for local-first apps"), ("tides", "How tide tables are computed"),
                        ("rust", "Rust ownership explained with diagrams"),
                        ("guide-a", "A field guide to sourdough hydration"),
                        ("guide-b", "A field guide to bird migration"), ("guide-c", "A field guide to cast iron"),
                        ("guide-d", "A field guide to scree"), ("guide-e", "A field guide to tide pools"),
                        ("guide-f", "A field guide to pottery"), ("guide-g", "A field guide to weaving")):
        _save(memory, f"https://example.com/{slug}", title, idx=idx)
    tab_groups.sync(memory, {"browser": "chrome", "profile": "Default", "groups": [
        {"title": "Espresso research", "color": "blue", "saved_guid": "g1",
         "tabs": [{"title": "Grind size notes", "url": "https://example.com/espresso/grind"}]}]})
    bank_index.invalidate()
    search_index.refresh(memory)
    return memory


def _ids(hits):
    return [h.url for h in hits]


def test_a_message_about_the_topic_finds_the_save_with_what_an_agent_needs(found):
    hits = saved_lookup.find(found, "I'm building a local-first sync engine with CRDTs")
    assert _ids(hits) == ["https://example.com/crdts"]
    line = saved_lookup.line(hits[0])
    assert "CRDTs for local-first apps" in line and "https://example.com/crdts" in line and "example.com" in line
    assert hits[0].read is False


def test_a_word_many_saves_share_finds_nothing_and_neither_does_an_unrelated_message(found):
    assert saved_lookup.find(found, "I want a field guide") == []
    assert saved_lookup.find(found, "what time is my dentist appointment") == []
    assert saved_lookup.find(found, "refactor the login form validation") == []


def test_a_lookup_takes_one_rare_word_and_the_unasked_note_two(found):
    assert saved_lookup.find(found, "crdts") == []
    assert _ids(saved_lookup.find(found, "crdts", min_shared=1)) == ["https://example.com/crdts"]


def test_a_tab_group_is_found_by_its_words_and_only_for_a_caller_with_the_source_scope(found):
    hits = saved_lookup.find(found, "espresso grind size")
    assert [h.title for h in hits] == ["Tab group: Espresso research"] and hits[0].page is None
    assert hits[0].episode and saved_lookup.line(hits[0]).endswith(f"`{hits[0].episode}`")
    assert saved_lookup.find(found, "espresso grind size", episodes=False) == []


def test_an_archived_or_shown_page_is_left_out(found):
    hit = saved_lookup.find(found, "rust ownership")[0]
    assert saved_lookup.find(found, "rust ownership", exclude=frozenset({hit.page})) == []
    path = found / "entities" / f"{hit.page}.md"
    parsed = markdown_parser.parse(path)
    parsed.frontmatter["status"] = "archived"
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    bank_index.invalidate()
    search_index.refresh(found)
    assert saved_lookup.find(found, "rust ownership") == []


def test_the_hook_note_carries_a_save_and_reads_nothing_back_into_the_bank(found):
    from api.services import hook_recall, recall_text

    before = {p: p.read_bytes() for p in (found / "episodes").glob("*.md")}
    note = hook_recall.prompt_context(found, "should I use CRDTs for my local-first sync?")
    assert note.reason == "saved" and "https://example.com/crdts" in note.text
    assert note.text.startswith(recall_text.INJECTION_PREFIX) and recall_text.is_injection(note.text)
    assert note.tokens <= hook_recall.MAX_TOKENS
    # The session's window keeps it from repeating turn after turn.
    again = hook_recall.prompt_context(found, "should I use CRDTs for my local-first sync?",
                                       recent=frozenset(note.injected))
    assert not (again.text and "https://example.com/crdts" in again.text)
    assert hook_recall.prompt_context(found, "what time is my dentist appointment").text is None
    assert {p: p.read_bytes() for p in (found / "episodes").glob("*.md")} == before


def test_recall_lists_a_save_once_says_what_it_is_and_wakes_nothing(found, monkeypatch):
    from api.services import mcp_tools, vector_index

    class _NoIndex:
        def __init__(self, *a, **k):
            raise RuntimeError("no vector index in this bank")

    monkeypatch.setattr(vector_index, "SqliteVecIndexer", _NoIndex)
    monkeypatch.setattr(mcp_tools, "_relevant_inbox", lambda memory_path, query, **_: [])
    from _stdio_server import stdio_server

    mcp = stdio_server()
    monkeypatch.setattr(mcp, "get_memory_path", lambda: found)
    monkeypatch.setattr(mcp, "_STATE_HINT_SENT", False)
    before = {p: p.read_bytes() for p in (found / "episodes").glob("*.md")}
    text = str(mcp.handle_recall("crdts for local-first"))
    # Whether a leg ranks its page or the saved list finds it, an agent gets the link, and a save is no conversation.
    assert "https://example.com/crdts" in text and "**Source:** bookmark" not in text
    words_only = str(mcp.handle_recall("tide tables computed"))
    assert "https://example.com/tides" in words_only
    assert {p: p.read_bytes() for p in (found / "episodes").glob("*.md")} == before


def test_reading_a_save_by_id_says_what_it_is_and_where_it_goes(found, monkeypatch):
    from _stdio_server import stdio_server

    mcp = stdio_server()
    monkeypatch.setattr(mcp, "get_memory_path", lambda: found)
    ep = next(p.stem for p in (found / "episodes").glob("*.md")
              if markdown_parser.parse(p).frontmatter.get("url") == "https://example.com/crdts")
    text = str(mcp.handle_sources(ep))
    assert "nobody has read" in text and "https://example.com/crdts" in text


def test_ask_sees_a_save_no_claim_could_reach_and_no_engine_is_called_for_a_miss(found, monkeypatch):
    from api.services import ask_service

    prompts: list[str] = []

    def llm(prompt):
        prompts.append(prompt)
        return '{"answer": "A saved link covers it.", "confidence": 0.5, "used_entities": []}'

    out = ask_service.answer_query(found, "what have I saved about crdts", retrieve_fn=lambda q, k: [], llm_fn=llm,
                                 search_fn=lambda *a, **k: None)
    assert "SAVED LINKS" in prompts[0] and "https://example.com/crdts" in prompts[0]
    assert "nobody has read them" in prompts[0]
    assert out["answer"] == "A saved link covers it."
    prompts.clear()
    miss = ask_service.answer_query(found, "what time is my dentist appointment", retrieve_fn=lambda q, k: [], llm_fn=llm,
                                  search_fn=lambda *a, **k: None)
    assert prompts == [] and miss["gaps"]


# --- what the pages say ----------------------------------------------------------------------------------------------


def test_the_overview_counts_what_is_kept_apart_from_what_waits(tmp_path):
    memory = _bank(tmp_path)
    idx: dict = {}
    _save(memory, "https://example.com/a", "Bare one", idx=idx)
    _save(memory, "https://example.com/b", "Bare two", idx=idx)
    _save(memory, "https://example.com/c", "With a note", idx=idx, note="the person's note")
    row = next(r for r in source_overview.build_overview(memory, channels=[]) if "chrome-bookmark" in r["origins"])
    assert (row["kept"], row["waiting"]) == (2, 1)


def test_the_queue_route_lists_what_waits_and_counts_what_is_kept(tmp_path):
    from fastapi.testclient import TestClient

    from api import main
    from api.config import get_settings

    memory = _bank(tmp_path)
    idx: dict = {}
    _save(memory, "https://example.com/a", "Bare one", idx=idx)
    noted, _ = _save(memory, "https://example.com/c", "With a note", idx=idx, note="the person's note")
    main.app.dependency_overrides[get_settings] = lambda: settings(memory)
    try:
        body = TestClient(main.app).get("/sleep/queue").json()
    finally:
        main.app.dependency_overrides.clear()
    assert body["kept"] == 1 and noted in {i["id"] for i in body["items"]}
    assert not any(i["title"] == "Bare one" for i in body["items"])


# --- a batch is bounded by what it holds -----------------------------------------------------------------------------


def test_a_long_session_reads_alone_and_short_ones_keep_the_count():
    ids = ["big", "a", "b", "c", "huge", "d"]
    sizes = {"big": 102_000, "a": 2_000, "b": 2_000, "c": 2_000, "huge": 68_000, "d": 2_000}
    waiting = set(ids)
    batch, more = sleep_drain.next_batch_retrying(ids, waiting, set(), 25, {}, sizes=sizes)
    assert (batch, more) == (["big"], 5)                         # a stop after it keeps it
    batch, more = sleep_drain.next_batch_retrying(ids, waiting, {"big"}, 25, {}, sizes=sizes)
    assert (batch, more) == (["a", "b", "c"], 2)
    assert sleep_drain.batches_left(ids, 25, sizes) == 4
    # Twenty-five short chats are still one batch of the person's count; without sizes, count alone.
    small = [f"s{i}" for i in range(30)]
    two_k = {i: 2_000 for i in small}
    assert len(sleep_drain.next_batch_retrying(small, set(small), set(), 25, {}, sizes=two_k)[0]) == 25
    assert sleep_drain.next_batch_retrying(ids, waiting, set(), 25, {})[0] == ids


def test_a_retry_still_goes_first_and_a_batch_is_never_empty():
    ids = ["big", "a"]
    sizes = {"big": 500_000, "a": 2_000}
    assert sleep_drain.next_batch_retrying(ids, set(ids), set(), 25, {"a": 1}, sizes=sizes)[0] == ["a"]
    assert sleep_drain.next_batch_retrying(["big"], {"big"}, set(), 25, {}, sizes=sizes)[0] == ["big"]


def test_a_drain_commits_a_long_session_on_its_own_before_a_stop_can_cost_it(tmp_path, monkeypatch):
    """The owner's run: 22 items, one batch, a plan limit, nothing kept. Bounded, the sessions before the stop stay."""
    rig = install(monkeypatch)

    def extra(memory):
        for name, chars in (("ep_2026-09-01_100", 70_000), ("ep_2026-09-01_101", 2_000), ("ep_2026-09-01_102", 2_000)):
            markdown_parser.write(memory / "episodes" / f"{name}.md",
                                  {"id": name, "processed": False, "source": "claude-code",
                                   "timestamp": f"2026-09-01T11:0{name[-1]}:00",
                                   "session_id": f"ses_2026-09-01_abcdef{name[-2:]}"},
                                  "user: " + "alpha project words " * (chars // 20))

    memory = seed_bank(tmp_path, [], extra=extra)
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=25), "sleep_big",
                                user_triggered=True, drain=True))
    assert rig.extract_batches == [["ep_2026-09-01_100"], ["ep_2026-09-01_101", "ep_2026-09-01_102"]]
    assert sleep_cycle.get_sleep_state().drain.committed_batches == 2
