"""ROR-122 (ruling 69): a rename at the source renames the thing in Cicada, for every source that gives a page or a row
its name. The shared rules (`source_names`), then each source that owns one: books (two doors), repositories, files
and Voice Memos, feeds, episodes. Synthetic names only."""
from __future__ import annotations

import asyncio
import hashlib

import pytest
from _synthetic_bank import _bank
from test_github_repos import FakeGitHub, _connect, _pages, _sync
from test_github_repos import bank as github_bank  # noqa: F401  (a fixture)

from api.services import (books, episode_staging, feed_registry, markdown_parser, media_files, media_pages,
                          project_ownership, source_names)

DAY = "2026-11-05"


def _fm(**kw) -> dict:
    return {"name": "Old Title", "type": "media", **kw}


# --------------------------------------------------------------------------- the rules


def test_the_newest_name_wins_and_the_old_one_stays_findable():
    fm = _fm()
    assert source_names.apply(fm, "door-a", "Old Title", day=DAY, door_was="Old Title") == source_names.SAME
    assert source_names.apply(fm, "door-a", "New Title", day=DAY, door_was="Old Title") == source_names.RENAME
    assert fm["name"] == "New Title" and fm["aliases"] == ["Old Title"]
    assert fm["name_source"]["door"] == "door-a" and fm["names_seen"] == {"door-a": "New Title"}


def test_a_name_the_person_set_stands_and_the_sources_new_one_is_only_an_alias():
    marked = _fm(name_by={"by": "user", "day": DAY}, names_seen={"door-a": "Old Title"})
    assert source_names.apply(marked, "door-a", "New Title", day=DAY) == source_names.KEPT
    assert marked["name"] == "Old Title" and marked["aliases"] == ["New Title"]
    # a hand edit of the page (its name is no longer the one a source wrote) is the person's too
    edited = _fm(name="Mine", name_source={"door": "door-a", "name": "Old Title", "day": DAY},
                 names_seen={"door-a": "Old Title"})
    assert source_names.apply(edited, "door-a", "New Title", day=DAY) == source_names.KEPT
    assert edited["name"] == "Mine"
    # the app's rename (project header) leaves the mark
    page = {"name": "Alpha", "type": "project"}
    project_ownership.apply_header(page, name="Beta", by="user", day=DAY)
    assert page["name_by"] == {"by": "user", "day": DAY} and page["aliases"] == ["Alpha"]


def test_an_alias_the_person_removed_stays_removed():
    fm = _fm(names_seen={"door-a": "Old Title"},
             aliases_removed=[{"alias": "Old Title", "by": "user", "on": DAY}])
    assert source_names.apply(fm, "door-a", "New Title", day=DAY) == source_names.RENAME
    assert fm["name"] == "New Title" and not fm.get("aliases")
    kept = _fm(name_by={"by": "user"}, names_seen={"door-a": "Old Title"},
               aliases_removed=[{"alias": "New Title", "by": "user", "on": DAY}])
    source_names.apply(kept, "door-a", "New Title", day=DAY)
    assert not kept.get("aliases")


def test_the_door_that_last_changed_its_name_wins_and_a_door_repeating_itself_never_flips_the_page():
    fm = _fm(names_seen={"door-a": "Old Title"})
    assert source_names.apply(fm, "door-b", "Spelled B", day=DAY) == source_names.BASELINE   # first sight: no rename
    assert fm["name"] == "Old Title"
    assert source_names.apply(fm, "door-b", "Spelled B again", day=DAY) == source_names.RENAME
    assert fm["name"] == "Spelled B again"
    assert source_names.apply(fm, "door-a", "Old Title", day=DAY) == source_names.SAME       # a did not change
    assert fm["name"] == "Spelled B again"
    assert source_names.apply(fm, "door-a", "A moved", day=DAY) == source_names.RENAME
    assert fm["name"] == "A moved" and {"Old Title", "Spelled B again"} <= set(fm["aliases"])


def test_a_rename_is_not_a_mention():
    fm = _fm(last_referenced="2026-01-01", confidence=0.8, source_episodes=["ep_1"], names_seen={"d": "Old Title"})
    before = {k: v for k, v in fm.items() if k not in ("name", "aliases", "name_source", "names_seen")}
    source_names.apply(fm, "d", "New Title", day=DAY)
    assert {k: v for k, v in fm.items() if k not in ("name", "aliases", "name_source", "names_seen")} == before


# --------------------------------------------------------------------------- books


def _page(memory, eid):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md")


def _book(memory, door, title, *, apple=None, goodreads=None, today=DAY):
    index = books.BookIndex(memory)
    facts = books.BookFacts(title=title, authors=["Ada Example"], isbns=["9780306406157"], apple_id=apple,
                            goodreads_id=goodreads, title_from=door, door=door)
    eid, created, _ = books.ensure_page(memory, index, facts, "ep_1", today)
    return eid, index


def test_a_book_renamed_in_its_door_follows_it_and_keeps_the_old_title_as_a_name(tmp_path):
    memory = _bank(tmp_path)
    eid, _ = _book(memory, books.APPLE_ORIGIN, "The Lantern Orchard", apple="A1")
    assert _page(memory, eid).frontmatter["names_seen"] == {"apple-books": "The Lantern Orchard"}
    eid2, index = _book(memory, books.APPLE_ORIGIN, "The Lantern Orchard: Revised", apple="A1")
    assert eid2 == eid and [r[:3] for r in index.renames] == [(eid, "apple-books", "The Lantern Orchard: Revised")]
    assert _page(memory, eid).frontmatter["name"] == "The Lantern Orchard"      # not inside the person's write
    assert books.apply_renames(memory, index.renames, today=DAY) == [f"entities/{eid}.md"]
    fm = _page(memory, eid).frontmatter
    assert fm["name"] == "The Lantern Orchard: Revised" and fm["book"]["title"] == "The Lantern Orchard: Revised"
    assert "The Lantern Orchard" in fm["aliases"] and fm["last_referenced"] == DAY
    assert books.apply_renames(memory, index.renames, today=DAY) == []            # idempotent
    # the page is still found by either title and by its id of the source
    assert books.BookIndex(memory).find(books.BookFacts(apple_id="A1")) == eid


def test_a_book_the_person_renamed_keeps_their_name_across_a_source_rename(tmp_path):
    memory = _bank(tmp_path)
    eid, _ = _book(memory, books.APPLE_ORIGIN, "The Lantern Orchard", apple="A1")
    path = memory / "entities" / f"{eid}.md"
    parsed = markdown_parser.parse(path)
    fm = dict(parsed.frontmatter, name="My Orchard Book")
    markdown_parser.write(path, fm, parsed.body)
    _, index = _book(memory, books.APPLE_ORIGIN, "The Lantern Orchard 2", apple="A1")
    books.apply_renames(memory, index.renames, today=DAY)
    fm = _page(memory, eid).frontmatter
    assert fm["name"] == "My Orchard Book" and "The Lantern Orchard 2" in fm["aliases"]


def test_two_book_doors_the_one_that_last_changed_wins(tmp_path):
    memory = _bank(tmp_path)
    eid, _ = _book(memory, books.APPLE_ORIGIN, "The Lantern Orchard", apple="A1")
    _, index = _book(memory, books.GOODREADS_ORIGIN, "The Lantern Orchard (Orchard, #1)", goodreads="G1")
    assert not index.renames                                                  # a second door's first word: a baseline
    assert _page(memory, eid).frontmatter["name"] == "The Lantern Orchard"
    _, index = _book(memory, books.GOODREADS_ORIGIN, "The Lantern Orchard (Orchard Series, #1)", goodreads="G1")
    books.apply_renames(memory, index.renames, today=DAY)
    assert _page(memory, eid).frontmatter["name"] == "The Lantern Orchard (Orchard Series, #1)"
    _, index = _book(memory, books.APPLE_ORIGIN, "The Lantern Orchard", apple="A1")      # Apple repeats itself
    assert not index.renames


def test_a_book_made_before_the_rule_follows_its_only_door(tmp_path):
    memory = _bank(tmp_path)
    eid, _ = _book(memory, books.APPLE_ORIGIN, "The Lantern Orchard", apple="A1")
    path = memory / "entities" / f"{eid}.md"
    parsed = markdown_parser.parse(path)
    fm = {k: v for k, v in parsed.frontmatter.items() if k not in ("names_seen", "name_source")}
    fm["book"] = dict(fm["book"], doors=["apple-books"])
    markdown_parser.write(path, fm, parsed.body)
    _, index = _book(memory, books.APPLE_ORIGIN, "A New Orchard Title", apple="A1")
    books.apply_renames(memory, index.renames, today=DAY)
    assert _page(memory, eid).frontmatter["name"] == "A New Orchard Title"


# --------------------------------------------------------------------------- repositories


def test_a_renamed_repository_renames_its_page_by_githubs_id(github_bank):
    bank = github_bank
    _connect()
    _sync(bank, FakeGitHub())
    before = _pages(bank)["bob-example/alpha-project"]
    later = FakeGitHub()
    later.fix["owned"][0].update(full_name="bob-example/alpha-renamed", name="alpha-renamed",
                                 html_url="https://github.com/bob-example/alpha-renamed")
    _sync(bank, later)
    page = _pages(bank)["bob-example/alpha-renamed"]
    assert page["id"] == before["id"]                                         # the id never changes
    assert page["fm"]["name"] == "bob-example/alpha-renamed" and "bob-example/alpha-project" in page["fm"]["aliases"]
    # a name the person set stands over a later rename on GitHub
    path = bank / "entities" / f"{page['id']}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, dict(parsed.frontmatter, name="My Kit", name_by={"by": "user", "day": DAY}), parsed.body)
    again = FakeGitHub()
    again.fix["owned"][0].update(full_name="bob-example/alpha-third", name="alpha-third",
                                 html_url="https://github.com/bob-example/alpha-third")
    _sync(bank, again)
    kept = markdown_parser.parse(path).frontmatter
    assert kept["name"] == "My Kit" and "bob-example/alpha-third" in kept["aliases"]


# --------------------------------------------------------------------------- files and Voice Memos


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    return _bank(tmp_path)


def _memo(bank, name, *, sha="a" * 64, words="We settled the budget."):
    segs = [{"start": 0, "end": 4, "text": words}] if words else []
    return media_files.record_media(bank, name=name, kind="audio", sha256=sha, size=10, duration_s=65, language="en",
                                    segments=segs, transcribed_by="Speech model A" if segs else None,
                                    source="voice_memos", source_key="KEY-1")


def test_a_voice_memo_renamed_in_its_store_renames_its_page_and_keeps_its_words(bank):
    fid = _memo(bank, "Standup 1.m4a")["id"]
    media_pages.sync(bank)
    page = media_pages.page_for(bank, fid)
    assert markdown_parser.parse(bank / "entities" / f"{page}.md").frontmatter["name"] == "Standup 1"
    out = _memo(bank, "Budget review.m4a", words="")                       # the name alone, the same bytes
    assert out["action"] == "updated"
    assert media_files.transcript(bank, fid)                               # the words stayed
    assert media_pages.sync(bank)["updated"] == 1
    fm = markdown_parser.parse(bank / "entities" / f"{page}.md").frontmatter
    assert fm["name"] == "Budget review" and "Standup 1" in fm["aliases"] and "Standup 1.m4a" in fm["aliases"]
    assert media_pages.page_for(bank, fid) == page                         # the same page
    assert media_pages.sync(bank)["updated"] == 0                          # a second sync writes nothing


def test_a_file_page_the_person_renamed_keeps_their_name(bank):
    fid = _memo(bank, "Standup 1.m4a")["id"]
    media_pages.sync(bank)
    path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, dict(parsed.frontmatter, name="Weekly sync"), parsed.body)
    _memo(bank, "Budget review.m4a", words="")
    media_pages.sync(bank)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["name"] == "Weekly sync" and "Budget review" in fm["aliases"]


def _pre_ship(path, **fm_changes):
    """The page as it was before this rule: no name_source, no names_seen."""
    parsed = markdown_parser.parse(path)
    fm = {k: v for k, v in parsed.frontmatter.items() if k not in ("name_source", "names_seen", "name_by")}
    markdown_parser.write(path, {**fm, **fm_changes}, parsed.body)


def test_a_pre_ship_page_the_person_renamed_keeps_their_name_across_syncs(bank):
    fid = _memo(bank, "Standup 1.m4a")["id"]
    media_pages.sync(bank)
    path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    _pre_ship(path, name="Weekly sync")
    for _ in range(2):                                             # the store unchanged: the title never comes back
        media_pages.sync(bank)
        assert markdown_parser.parse(path).frontmatter["name"] == "Weekly sync"
    _memo(bank, "Budget review.m4a", words="")                     # and a later rename at the source does not take it
    media_pages.sync(bank)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["name"] == "Weekly sync" and "Standup 1" not in (fm.get("aliases") or [])


def test_a_pre_ship_page_named_as_the_store_names_it_follows_a_later_rename(bank):
    fid = _memo(bank, "Standup 1.m4a")["id"]
    media_pages.sync(bank)
    path = bank / "entities" / f"{media_pages.page_for(bank, fid)}.md"
    _pre_ship(path)
    assert media_pages.sync(bank)["updated"] == 1                  # the baseline, once
    assert media_pages.sync(bank)["updated"] == 0
    _memo(bank, "Budget review.m4a", words="")
    media_pages.sync(bank)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["name"] == "Budget review" and "Standup 1" in fm["aliases"]


# --------------------------------------------------------------------------- feeds and episodes


def test_a_feed_renamed_by_its_publisher_follows_it(tmp_path):
    feed = {"url": "https://example.com/feed.xml"}
    assert feed_registry.note_feed_title(feed, "Orchard Notes")
    assert feed["title"] == "Orchard Notes" and "aka" not in feed
    assert not feed_registry.note_feed_title(feed, "Orchard Notes")           # same: nothing to write
    assert feed_registry.note_feed_title(feed, "Orchard Letters")
    assert feed["title"] == "Orchard Letters" and feed["aka"] == ["Orchard Notes"]
    legacy = {"url": "https://example.com/a.xml", "title": "From a list"}
    feed_registry.note_feed_title(legacy, "Channel name")                     # the first report is a baseline
    assert legacy["title"] == "From a list"


def test_an_episode_whose_title_moved_and_no_word_did_shows_the_new_title_and_is_not_requeued(tmp_path):
    episodes = tmp_path / "episodes"
    episodes.mkdir()
    ts = "2026-09-01T10:00:00+00:00"

    def draft(title):
        return episode_staging.EpisodeDraft(
            title=title, source_id="note-1", source_updated_at=ts, timestamp=ts, original_date=ts[:10],
            source="folder", origin="folder", body="We talked about orchards.", writer="folder")

    assert episode_staging.stage([draft("Orchard plans")], episodes).as_tuple() == (1, 0, 0)
    (path,) = sorted(episodes.glob("ep_*.md"))
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, dict(parsed.frontmatter, processed=True, processed_by="sleep"), parsed.body)
    result = episode_staging.stage([draft("Orchard plans, renamed")], episodes)
    fm = markdown_parser.parse(path).frontmatter
    assert fm["title"] == "Orchard plans, renamed" and fm["processed"] is True and "revised" not in fm
    assert result.created == 0 and result.paths
    assert not episode_staging.stage([draft("Orchard plans, renamed")], episodes).paths
