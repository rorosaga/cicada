"""G246 Track M (ruling 81): talking about a saved post is remembered, so the post earns its page even once Sleep has read it.

The owner's rule: a post has a page when he talks about it. The posts rule (`saved_posts`) reads one mark on the post's
save, ``named: {why, at}``; this is its writer. His own located words naming a save (its link, or its whole title) mark it
whatever state it is in — waiting for tonight, in the older pile, already read, holding nothing to read — and nothing that
rewrites a save's record ever takes the mark away. The mark changes nothing about whether or when the save is read, costs
no model call, is written with the batch's commit, and is his act alone: never an agent's words, never a relayed app's,
never a retrieval hit. Everything ships dark: with ``saved_posts.HIDE_POSTS`` off nothing he sees changes.

Synthetic banks under tmp_path, placeholder handles and example.com links; nothing real is read, nothing is fetched."""
from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

import pytest

from _reading_fixtures import reading  # noqa: F401 — a fixture (a scratch ``$CICADA_HOME`` and reading settings)
from _synthetic_bank import _bank
from drain_harness import git, install, seed_bank, settings

from api.services import (authorship, bank_index, evidence, episode_ids, episode_staging, graph_builder, history_index, keep_as_page,
                          list_pages, markdown_parser, media_ingestor, mention_asks, saved_mentions, saved_order,
                          saved_posts, saved_why, save_folders, sleep_cycle)
from api.services.episode_staging import EpisodeDraft
from api.services.media_ingestor import MediaMeta, PreparedItem, RawItem

AT = "2026-11-24T10:00:00+00:00"
LATER = "2026-12-01T10:00:00+00:00"
POST = "https://x.com/alpha_user/status/{n}"
WORDS = "What the list showed of the post"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(mention_asks, "offer", lambda memory_path, found: [])   # the ask has its own tests (G245)
    bank_index.invalidate()
    graph_builder.reset_cache()
    yield
    bank_index.invalidate()
    graph_builder.reset_cache()


@pytest.fixture(autouse=True)
def _setting_pinned(monkeypatch):
    """The shipped setting is on (ruling 81, `saved_posts.HIDE_POSTS`); this file pins its own: off, unless a test asks
    for `on`. Never the default, which is not what these tests assert."""
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", False)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(saved_posts, "HIDE_POSTS", True)


def _save(memory, n, *, title=None, origin="x-bookmarks", folder="Bookmarks", bulk=False, words=WORDS, idx=None):
    """A saved post written by the production writer: its page, its url-index row and its save episode."""
    url = POST.format(n=n)
    title = title or f"A post about vector indexes number {n}"
    item = RawItem(url=url, title=title, origin=origin, folder=folder, defer_enrich=True)
    meta = MediaMeta(title=title, description=words, site="x.com", media_type="bookmark")
    held = media_ingestor.load_url_index(memory) if idx is None else idx   # ``idx={}``: a second copy of the same link
    res = media_ingestor.write_prepared(PreparedItem(item, meta), memory, held, bulk=bulk)
    if idx is None:
        media_ingestor.save_url_index(memory, held)
    bank_index.invalidate()
    return res.episode_id, res.media_entity_id, url


def _read(memory, eid, by="sleep"):
    """Sleep reads it: what the first night does."""
    path = memory / "episodes" / f"{eid}.md"
    parsed = markdown_parser.parse(path)
    parsed.frontmatter.update(processed=True, processed_by=by)
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    bank_index.invalidate()


def _fm(memory, eid):
    bank_index.invalidate()
    return markdown_parser.parse(memory / "episodes" / f"{eid}.md").frontmatter


def _said(text, eid="ep_2026-12-01_901", **extra):
    """One read conversation, as Sleep hands it to the mention reader: the person's own turn."""
    return {"id": eid, "content": f"user: {text}", "origin": "claude-code", "gaps": (), **extra}


# ------------------------------------------------------------------------------------- the mark, whatever the state


def _make(memory, state, n):
    if state == "waiting":
        return _save(memory, n)
    if state == "pile":
        return _save(memory, n, bulk=True)
    if state == "read":
        out = _save(memory, n)
        _read(memory, out[0])
        return out
    out = _save(memory, n, words="")        # a title and a link, nothing for a model to read
    assert history_index.save_state(_fm(memory, out[0])) == "no-words"
    return out


@pytest.mark.parametrize("state", ["waiting", "pile", "read", "no-words"])
def test_his_own_words_naming_a_save_mark_it_whatever_state_it_is_in(tmp_path, state):
    memory = _bank(tmp_path)
    eid, _page, url = _make(memory, state, 1)
    assert history_index.save_state(_fm(memory, eid)) == state
    before = _fm(memory, eid)
    paths = saved_mentions.wake_mentioned(memory, [_said(f"I keep coming back to {url}")], at=AT)
    assert paths == [f"episodes/{eid}.md"]
    after = _fm(memory, eid)
    assert after["named"] == {"why": saved_mentions.WHY_LINK, "at": AT}
    # The read is exactly what it was, but for the wake a waiting or pile save gets as before.
    woken = state in ("waiting", "pile")
    assert ("read_asked" in after) is woken
    assert (after["processed"], after.get("processed_by")) == ((False, None) if woken else (before["processed"], before.get("processed_by")))
    assert {k: v for k, v in after.items() if k not in ("named", "read_asked", "processed", "processed_by")} == \
        {k: v for k, v in before.items() if k not in ("processed", "processed_by")}


@pytest.mark.parametrize("state", ["waiting", "pile", "read", "no-words"])
def test_saying_the_whole_title_marks_it_too(tmp_path, state):
    memory = _bank(tmp_path)
    eid, _page, _url = _make(memory, state, 2)
    saved_mentions.wake_mentioned(memory, [_said("Remember a post about vector indexes number 2, it was good")], at=AT)
    assert _fm(memory, eid)["named"] == {"why": saved_mentions.WHY_TITLE, "at": AT}


@pytest.mark.parametrize("origin, folder", [("chrome-bookmark", None), ("saved-link", None), ("safari-bookmark", None),
                                            ("x-likes", "Likes"), ("instagram-saved", "Saved")])
def test_every_door_a_post_came_in_by_is_marked_when_it_was_already_read(tmp_path, origin, folder):
    """A bookmark or a pasted link has no list, and was never a "list save": it is only marked."""
    memory = _bank(tmp_path)
    eid, _page, url = _save(memory, 3, origin=origin, folder=folder)
    _read(memory, eid)
    saved_mentions.wake_mentioned(memory, [_said(f"look at {url}")], at=AT)
    assert _fm(memory, eid)["named"]["why"] == saved_mentions.WHY_LINK


def test_the_mark_never_changes_whether_or_when_a_save_is_read(tmp_path):
    memory = _bank(tmp_path)
    read, _p, read_url = _make(memory, "read", 4)
    empty, _p, empty_url = _make(memory, "no-words", 5)
    before = {i: (_fm(memory, i), markdown_parser.parse(memory / "episodes" / f"{i}.md").body) for i in (read, empty)}
    saved_mentions.wake_mentioned(memory, [_said(f"{read_url} and {empty_url}")], at=AT)
    for eid, (fm, body) in before.items():
        after = _fm(memory, eid)
        assert {k: v for k, v in after.items() if k != "named"} == fm and "named" in after
        assert history_index.save_state(after) == history_index.save_state(fm)
        assert history_index.waits_for_model(after) is history_index.waits_for_model(fm)
        assert saved_order.classify(after) == saved_order.classify(fm) != saved_order.TALKED
        # The body, its hash and every span are untouched.
        assert markdown_parser.parse(memory / "episodes" / f"{eid}.md").body == body


def test_a_mark_alone_does_not_move_a_save_to_the_front_but_a_wake_still_does(tmp_path):
    memory = _bank(tmp_path)
    read, _p, read_url = _make(memory, "read", 6)
    waiting, _p, waiting_url = _make(memory, "waiting", 7)
    saved_mentions.wake_mentioned(memory, [_said(f"{read_url} {waiting_url}")], at=AT)
    assert saved_order.classify(_fm(memory, waiting)) == saved_order.TALKED
    assert saved_order.classify(_fm(memory, read)) != saved_order.TALKED


def test_the_first_mark_stays_and_a_second_mention_writes_nothing(tmp_path):
    memory = _bank(tmp_path)
    eid, _p, url = _make(memory, "read", 8)
    assert saved_mentions.wake_mentioned(memory, [_said(f"{url}")], at=AT) == [f"episodes/{eid}.md"]
    stamp = (memory / "episodes" / f"{eid}.md").stat().st_mtime_ns
    assert saved_mentions.wake_mentioned(memory, [_said(f"{url} again")], at=LATER) == []
    assert _fm(memory, eid)["named"]["at"] == AT
    assert (memory / "episodes" / f"{eid}.md").stat().st_mtime_ns == stamp


def test_a_link_saved_twice_is_marked_and_the_one_that_can_still_be_woken_is_not_shadowed(tmp_path):
    memory = _bank(tmp_path)
    read, _p, url = _save(memory, 9, origin="chrome-bookmark", folder=None)
    _read(memory, read)
    pile, _p2, _ = _save(memory, 9, origin="x-bookmarks", folder="Bookmarks", bulk=True, idx={})   # the same link, another door
    assert read != pile
    paths = saved_mentions.wake_mentioned(memory, [_said(f"{url}")], at=AT)
    assert f"episodes/{pile}.md" in paths and "read_asked" in _fm(memory, pile)
    assert "named" in _fm(memory, pile)


def test_the_cap_on_wakes_still_counts_only_what_it_always_counted(tmp_path):
    """Seven links pasted at once: three bookmarks already read come first, six waiting saves after. The first five
    waiting saves are woken as before; the read ones never take a wake's place."""
    memory = _bank(tmp_path)
    read = [_save(memory, n, origin="chrome-bookmark", folder=None) for n in (10, 11, 12)]
    for eid, _p, _u in read:
        _read(memory, eid)
    waiting = [_save(memory, n) for n in range(13, 19)]
    said = _said(" ".join(u for _e, _p, u in [*read, *waiting]))
    saved_mentions.wake_mentioned(memory, [said], at=AT)
    woken = [e for e, _p, _u in waiting if "read_asked" in _fm(memory, e)]
    assert woken == [e for e, _p, _u in waiting][:saved_mentions.MAX_WAKES_PER_CONVERSATION]
    assert all("read_asked" not in _fm(memory, e) for e, _p, _u in read)
    # Every woken one is marked, and so is the head of the paste, in the order said.
    assert all("named" in _fm(memory, e) for e in woken)
    assert all("named" in _fm(memory, e) for e, _p, _u in read)


def test_the_cap_bounds_reads_never_the_free_mark(tmp_path):
    """Eight already-read posts named in one conversation are all marked (the cap bounds reads, a mark reads nothing);
    with eight waiting saves named, the first five are woken and all eight are marked."""
    memory = _bank(tmp_path)
    read = [_save(memory, n, origin="chrome-bookmark", folder=None) for n in range(30, 38)]
    for eid, _p, _u in read:
        _read(memory, eid)
    waiting = [_save(memory, n) for n in range(40, 48)]
    said = _said(" ".join(u for _e, _p, u in [*read, *waiting]))
    saved_mentions.wake_mentioned(memory, [said], at=AT)
    assert [("named" in _fm(memory, e)) for e, _p, _u in read] == [True] * 8
    assert [("named" in _fm(memory, e)) for e, _p, _u in waiting] == [True] * 8
    woken = [e for e, _p, _u in waiting if "read_asked" in _fm(memory, e)]
    assert woken == [e for e, _p, _u in waiting][:saved_mentions.MAX_WAKES_PER_CONVERSATION]
    assert all("read_asked" not in _fm(memory, e) for e, _p, _u in read)
    # The mention reader (wake and ask) is still capped.
    saves = saved_mentions._saves(memory)
    assert len(saved_mentions.mentioned(said, saves)) == saved_mentions.MAX_WAKES_PER_CONVERSATION
    assert len(saved_mentions.named(said, saves)) == 16


# ------------------------------------------------------------------------------------- never an agent's, never a hit


def test_an_agents_words_a_relayed_app_and_a_note_an_agent_saved_never_mark_a_save(tmp_path):
    memory = _bank(tmp_path)
    eid, _p, url = _make(memory, "read", 20)
    agent_turn = {"id": "ep_2026-12-01_902", "content": f"user: nothing\nassistant: you saved {url}", "origin": "claude-code",
                  "gaps": ()}
    # A conversation in a relayed app (claude.ai, ChatGPT): every turn is the app's, never the person's own words.
    relayed_fm = {"evidence_kind": "assistant", "source": "mcp-remote"}
    relayed = {"id": "ep_2026-12-01_903", "content": f"user: {url}", "origin": "claude-ai", "gaps": (),
               authorship.KEY: authorship.of(relayed_fm)}
    # A note an agent saved for him (`cicada_save_episode`): `assistant` throughout (ruling 50).
    noted_fm = {"source": "mcp", "origin": "claude-code", "session_id": "ses_one"}
    noted = {"id": "ep_2026-12-01_904", "content": f"user: {url}", "origin": "claude-code", "gaps": (),
             authorship.KEY: authorship.of(noted_fm)}
    assert authorship.of(noted_fm) == evidence.AGENT_KIND and authorship.of(relayed_fm) == "assistant"
    assert saved_mentions.wake_mentioned(memory, [agent_turn, relayed, noted], at=AT) == []
    assert "named" not in _fm(memory, eid)


def test_a_conversation_that_names_nothing_marks_nothing(tmp_path):
    memory = _bank(tmp_path)
    eid, _p, _url = _make(memory, "read", 21)
    assert saved_mentions.wake_mentioned(memory, [_said("I like cats and dogs and vector indexes")], at=AT) == []
    assert "named" not in _fm(memory, eid)


@pytest.mark.parametrize("origin, folder, url", [
    ("github-owned", None, "https://github.com/alpha-org/alpha-project"),
    ("reddit-saved", "Joined communities", "https://www.reddit.com/r/alpha_sub/"),
    ("safari-tab", "A device", "https://example.com/open-tab"),
])
def test_a_record_another_service_keeps_is_never_marked(tmp_path, origin, folder, url):
    memory = _bank(tmp_path)
    item = RawItem(url=url, title="A record about nothing in particular", origin=origin, folder=folder, defer_enrich=True)
    meta = MediaMeta(title=item.title, description=WORDS, site="example.com", media_type="bookmark")
    eid = media_ingestor.write_prepared(PreparedItem(item, meta), memory, {}).episode_id
    bank_index.invalidate()
    assert saved_mentions.wake_mentioned(memory, [_said(f"look at {url}")], at=AT) == []
    assert history_index.mark_named(memory, eid, saved_mentions.WHY_LINK, AT) is None
    assert "named" not in _fm(memory, eid)


def test_a_removed_source_and_a_non_save_are_never_marked(tmp_path):
    memory = _bank(tmp_path)
    eid, _p, url = _make(memory, "read", 22)
    path = memory / "episodes" / f"{eid}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "source_deleted_at": AT}, parsed.body)
    bank_index.invalidate()
    assert saved_mentions.wake_mentioned(memory, [_said(url)], at=AT) == []
    # An agent's report of what it read carries the link and is no save: the mark has no business there.
    report = memory / "episodes" / "ep_2026-12-01_950.md"
    markdown_parser.write(report, {"id": "ep_2026-12-01_950", "source": "page-read", "url": url, "processed": True,
                                   "processed_by": "agent", "media_entity_id": "media-x"}, "It says things.")
    assert history_index.mark_named(memory, "ep_2026-12-01_950", saved_mentions.WHY_LINK, AT) is None
    assert history_index.mark_named(memory, "ep_2026-12-01_999", saved_mentions.WHY_LINK, AT) is None   # missing file


def test_nothing_but_the_mention_reader_ever_writes_the_mark():
    """No route, tool, remote door or read path can mark a save: the one writer has the one caller (a retrieval hit is a
    read path and never calls it)."""
    callers: set[str] = set()
    root = Path(__file__).resolve().parents[2]
    for base in ("api", "mcp"):
        for path in (root / base).rglob("*.py"):
            if "tests" in path.parts or path.name == "history_index.py":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"\bmark_named\(", text):
                callers.add(str(path.relative_to(root)))
    assert callers == {"api/services/saved_mentions.py"}
    sleep = Path(saved_mentions.__file__).resolve().parent / "sleep_cycle.py"
    assert "saved_mentions.wake_mentioned" in sleep.read_text(encoding="utf-8")


def test_no_writer_drops_the_key_by_name():
    """Nothing pops or deletes ``named`` (a re-stage pops ``read_asked``, which is why this key exists)."""
    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in (root / "api").rglob("*.py"):
        if "tests" in path.parts:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if re.search(r"pop\((history_index\.|saved_posts\.)?NAMED_KEY|pop\(\"named\"|del [a-z_]+\[\"named\"\]", line):
                offenders.append(f"{path.relative_to(root)}:{n}")
    assert offenders == []


# ------------------------------------------------------------------------------------- the mark survives every writer


def _marked(tmp_path, *, state="read", n=30, origin="x-bookmarks", folder="Bookmarks"):
    memory = _bank(tmp_path)
    eid, page, url = _save(memory, n, origin=origin, folder=folder, bulk=(state == "pile"))
    if state == "read":
        _read(memory, eid)
    assert history_index.mark_named(memory, eid, saved_mentions.WHY_LINK, AT) == f"episodes/{eid}.md"
    bank_index.invalidate()
    return memory, eid, page, url


def _still(memory, eid):
    fm = _fm(memory, eid)
    assert fm.get("named") == {"why": saved_mentions.WHY_LINK, "at": AT}, "the mark was lost"
    return fm


def test_a_restage_with_new_content_keeps_it(tmp_path):
    memory, eid, _p, url = _marked(tmp_path)
    path = memory / "episodes" / f"{eid}.md"
    draft = EpisodeDraft(title="A post, edited", source_id="x:1", source_updated_at=LATER, source="url", origin="x-bookmarks",
                         body="The post says more now.", queue_for_sleep=True)
    episode_staging.update_in_place(path, draft, "The post says more now.", "hash2", [])
    assert _still(memory, eid)["processed"] is False


def test_a_restage_as_a_lean_save_pops_the_ask_but_never_the_mark(tmp_path):
    """The sync that re-stages a save as a bare one (ruling 62's old shape) pops ``read_asked`` — which is the very reason
    for this key."""
    memory, eid, _p, _url = _marked(tmp_path, state="waiting")
    path = memory / "episodes" / f"{eid}.md"
    assert history_index.wake(memory, eid, saved_mentions.WHY_LINK, AT)
    _read(memory, eid)                       # Sleep read it on his mention: the ask has been honoured
    assert "read_asked" in _fm(memory, eid)
    draft = EpisodeDraft(title="A post", source_id="x:1", source="url", origin="x-bookmarks", body="Same words.",
                         queue_for_sleep=False, processed_by=history_index.INDEXED_BY)
    episode_staging.update_in_place(path, draft, "Same words.", "hash3", [])
    fm = _still(memory, eid)
    assert "read_asked" not in fm and fm["processed_by"] == history_index.INDEXED_BY


@pytest.mark.parametrize("how", ["refresh", "reattribute", "amend", "section", "drop_other_keys"])
def test_the_staging_writers_that_edit_a_save_in_place_keep_it(tmp_path, how):
    memory, eid, _p, _url = _marked(tmp_path)
    path = memory / "episodes" / f"{eid}.md"
    if how == "refresh":
        episode_staging._refresh(path, EpisodeDraft(source="url", extra={"origin": "x-bookmarks"}, content_sha="abc"))
    elif how == "reattribute":
        episode_staging.reattribute(path, extra={"evidence_kind": "assistant"}, queue_for_sleep=False)
    elif how == "amend":
        assert episode_staging.amend_frontmatter(path, lambda fm: fm.update(title="Renamed") or True)
    elif how == "section":
        episode_staging.amend_section(path, "## Note", "An agent's note.", writer="agent")
    else:
        episode_staging.drop_keys(path, ("correspondent", "has_note"))
    _still(memory, eid)


def test_a_list_read_that_sees_the_post_again_keeps_it(tmp_path):
    memory, eid, _page, url = _marked(tmp_path)
    idx = media_ingestor.load_url_index(memory)
    again = RawItem(url=url, title="A post about vector indexes number 30", origin="x-bookmarks", folder="Bookmarks",
                    defer_enrich=True)
    saved_again = media_ingestor.write_prepared(PreparedItem(again, None), memory, idx, append_list=True)
    assert saved_again.status == "duplicate"
    other_list = RawItem(url=url, title="Again", origin="x-likes", folder="Likes", defer_enrich=True)
    media_ingestor.write_prepared(PreparedItem(other_list, None), memory, idx, append_list=True)
    bank_index.invalidate()
    _still(memory, eid)


def test_a_repeat_save_with_a_note_leaves_the_first_save_marked(tmp_path):
    memory, eid, _page, url = _marked(tmp_path)
    idx = media_ingestor.load_url_index(memory)
    first = idx[next(iter(idx))]
    existing = media_ingestor.IngestResult(status="duplicate", media_entity_id=first["media_entity_id"], episode_id=eid,
                                           title="A post", media_type="bookmark", thumbnail=None, url=url)
    item = RawItem(url=url, title="A post", origin="x-bookmarks", folder="Bookmarks", note="Worth keeping for the layout.")
    out = media_ingestor.write_note_episode(memory, item, existing)
    assert out is not None and out[0] != eid
    bank_index.invalidate()
    _still(memory, eid)


def test_a_why_answer_added_later_keeps_it(tmp_path):
    memory, eid, _p, url = _marked(tmp_path)
    saved_why.attach(memory, url=url, answer=saved_why.Answer(reasons=("design",), project=None, project_name=None,
                                                              text="the way the layout is drawn"))
    fm = _still(memory, eid)
    assert fm["saved_why"] and fm["processed"] is False
    saved_why.attach(memory, url=url, answer=saved_why.Answer(reasons=("data",), project=None, project_name=None, text=None),
                     at="2026-12-02T10:00:00Z")
    _still(memory, eid)


def test_a_folder_change_keeps_it(tmp_path):
    memory, eid, _p, _url = _marked(tmp_path, state="pile")
    save_folders.file_save(memory, eid, "x-bookmarks", add=["Journeys"])
    _still(memory, eid)
    save_folders.set_reason(memory, site="x", folder="Journeys",
                            answer=saved_why.Answer(reasons=("design",), project=None, project_name=None, text="layouts"))
    bank_index.invalidate()
    assert _still(memory, eid).get("readable_by_folder")
    save_folders.clear_reason(memory, site="x", folder="Journeys")
    bank_index.invalidate()
    _still(memory, eid)
    save_folders.file_save(memory, eid, "x-bookmarks", remove=["Journeys"])
    _still(memory, eid)


@pytest.mark.parametrize("state", ["pile", "waiting"])
def test_the_indexes_own_writers_keep_it(tmp_path, state):
    memory, eid, _p, _url = _marked(tmp_path, state=state, n=31 if state == "pile" else 32)
    if state == "pile":
        out = history_index.take_turns(memory)
        assert f"episodes/{eid}.md" in out.paths
        _still(memory, eid)
        history_index.return_to_pile(memory, [eid])
    history_index.retire(memory)
    path = memory / "episodes" / f"{eid}.md"
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter)
    history_index.mark_person_words(fm)
    markdown_parser.write(path, fm, parsed.body)
    assert history_index.wake(memory, eid, saved_mentions.WHY_LINK, LATER) in (f"episodes/{eid}.md", None)
    _still(memory, eid)
    assert saved_mentions.wake_lit(memory, at=LATER) == []
    _still(memory, eid)


def test_sleeps_own_reading_of_the_save_keeps_it(tmp_path):
    memory, eid, _p, _url = _marked(tmp_path, state="waiting")
    path = memory / "episodes" / f"{eid}.md"
    assert sleep_cycle._mark_episodes_processed([{"id": eid, "filepath": path}]) == 1
    fm = _still(memory, eid)
    assert fm["processed"] is True and fm["processed_by"] == "sleep"


def test_keeping_it_as_a_page_and_taking_that_back_keeps_it(tmp_path):
    memory, eid, _p, url = _marked(tmp_path)
    assert keep_as_page.keep(memory, url=url, kept=True, at=LATER)["status"] == "kept"
    _still(memory, eid)
    # Taking the click back is refused while his words naming it still hold the page, and nothing is lost.
    with pytest.raises(keep_as_page.KeepError) as refused:
        keep_as_page.keep(memory, url=url, kept=False)
    assert refused.value.because_of == ("named",)
    _still(memory, eid)


def test_a_failed_release_that_puts_files_back_keeps_a_committed_mark(tmp_path):
    memory, eid, _p, _url = _marked(tmp_path, state="pile", n=33)
    git(memory, "add", "-A")
    git(memory, "commit", "-q", "-m", "seed saves")
    history_index.take_turns(memory)
    history_index.restore(memory, [f"episodes/{eid}.md"])
    _still(memory, eid)


# ------------------------------------------------------------------------------------- the page, and dark


def _expected_rows(memory):
    return saved_posts.verdict(memory)


def test_a_post_read_on_the_first_night_and_named_a_week_later_is_a_page_once_the_flip_is_on(tmp_path, on):
    memory = _bank(tmp_path)
    eid, page, url = _make(memory, "read", 40)
    other, other_page, _ = _make(memory, "read", 41)
    assert page in saved_posts.hidden_ids(memory) and other_page in saved_posts.hidden_ids(memory)
    stamp_before = saved_posts.stamp(memory)
    saved_mentions.wake_mentioned(memory, [_said(f"I was thinking about {url} again")], at=AT)
    bank_index.invalidate()
    assert saved_posts.verdict(memory).signs[page] == frozenset({"named"})
    assert page not in saved_posts.hidden_ids(memory) and other_page in saved_posts.hidden_ids(memory)
    assert saved_posts.earned_ids(memory) == {page} and saved_posts.stamp(memory) != stamp_before
    g = graph_builder.build_graph(memory)
    nodes = {n.id: n for n in g.nodes}
    assert page in nodes and nodes[page].quiet is False and other_page not in nodes


def test_it_is_joined_to_its_list_not_dimmed_and_the_list_page_shows_it(tmp_path, on):
    memory = _bank(tmp_path)
    eid, page, url = _make(memory, "read", 42)
    _e2, other, _u2 = _make(memory, "read", 43)
    git(memory, "add", "-A")
    git(memory, "commit", "-q", "-m", "saves", "--allow-empty")
    assert list_pages.sync(memory)["created"] == 1
    saved_mentions.wake_mentioned(memory, [_said(f"{url}")], at=AT)
    bank_index.invalidate()
    graph_builder.reset_cache()
    g = graph_builder.build_graph(memory)
    nodes = {n.id for n in g.nodes}
    list_page = "list-x-bookmarks"
    assert list_page in nodes and page in nodes and other not in nodes
    assert (page, list_page) in {(l.source, l.target) for l in g.links}


def test_with_the_flip_off_nothing_he_sees_changes_but_the_mark_is_still_written(tmp_path):
    memory = _bank(tmp_path)
    eid, page, url = _make(memory, "read", 44)
    _e2, other, _u2 = _make(memory, "read", 45)
    assert saved_posts.HIDE_POSTS is False

    def seen():
        bank_index.invalidate()
        graph_builder.reset_cache()
        g = graph_builder.build_graph(memory)
        return (sorted((n.id, n.quiet, n.degree) for n in g.nodes), sorted((l.source, l.target) for l in g.links),
                saved_posts.hidden_ids(memory), saved_posts.earned_ids(memory), saved_posts.stamp(memory),
                saved_posts.drawn_as_page(memory, page, {"type": "media", "media": {"url": url}}))

    before = seen()
    saved_mentions.wake_mentioned(memory, [_said(f"{url}")], at=AT)
    assert "named" in _fm(memory, eid)                       # remembered now, for the day the flip comes
    assert seen() == before
    assert before[2] == before[3] == frozenset() and before[4] == ""


# ------------------------------------------------------------------------------------- a real Sleep run


def test_a_real_sleep_run_that_reads_the_conversation_marks_the_save_in_the_batchs_commit(tmp_path, monkeypatch, on):
    rig = install(monkeypatch)
    url = POST.format(n=777)

    def extra(memory):
        # A post saved on the first night and read by Sleep then; a week later a conversation names it.
        eid, page = "ep_2026-11-17_001", "media-a-post-about-indexes"
        markdown_parser.write(memory / "entities" / f"{page}.md",
                              {"name": "A post about indexes", "type": "media", "status": "active", "origin": "x-bookmarks",
                               "folder": "Bookmarks", "created": "2026-11-17", "source_episodes": [eid],
                               "media": {"url": url, "media_type": "url"}}, "## Summary\nA short post.\n")
        markdown_parser.write(memory / "episodes" / f"{eid}.md",
                              {"id": eid, "timestamp": "2026-11-17T08:00:00+00:00", "source": "url", "origin": "x-bookmarks",
                               "folder": "Bookmarks", "url": url, "media_entity_id": page, "processed": True,
                               "processed_by": "sleep", "title": "A post about indexes"}, "A short post.")
        markdown_parser.write(memory / "episodes" / "ep_2026-11-24_001.md",
                              {"id": "ep_2026-11-24_001", "timestamp": "2026-11-24T10:00:00+00:00", "processed": False,
                               "source": "claude-code", "session_id": "ses_week_later"},
                              f"user: I keep coming back to {url}\nassistant: Noted.")

    memory = seed_bank(tmp_path, [], extra=extra)
    assert saved_posts.hidden_ids(memory) == {"media-a-post-about-indexes"}
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=1), "named_stamp", user_triggered=True,
                                drain=True))
    assert [i for b in rig.extract_batches for i in b] == ["ep_2026-11-24_001"]
    fm = _fm(memory, "ep_2026-11-17_001")
    assert fm["named"]["why"] == saved_mentions.WHY_LINK and (fm["processed"], fm["processed_by"]) == (True, "sleep")
    assert git(memory, "status", "--porcelain").strip() == ""                    # committed with the batch, nothing left over
    changed = git(memory, "log", "--name-only", "--format=%s", "-n", "6")
    assert "episodes/ep_2026-11-17_001.md" in changed
    assert saved_posts.hidden_ids(memory) == frozenset()
    assert saved_posts.verdict(memory).signs["media-a-post-about-indexes"] == frozenset({"named"})
