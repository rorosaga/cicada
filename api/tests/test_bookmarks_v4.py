"""G191 v4 — bookmarks, round 4 (owner 2026-10-15).

* A few basic reasons: the panel offers the design, the product, to read later and useful someday, and never a
  project; an answer given before keeps its reasons (``technique``) and its project wherever answers are listed.
* ``someday`` steers exploring like ``read_later``: the minimal capture.
* A bookmark removed in the browser is kept and marked "no longer in <browser> since <day>" — on the seen-set, on
  ``GET /sources`` (``leftBrowser``) and on the channel's item list — and never asked about. Re-adding it clears the
  mark and asks again; a move, a first sync, a folder-scope change, an empty read and a wholesale swap never set it.

Synthetic bookmarks only; nothing reads a browser.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bookmark_seen, bookmark_sync, channel_items, explore_candidates, explore_plan,
                          markdown_parser, media_ingestor, saved_why)

_WEBKIT_OFFSET = 11_644_473_600
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _webkit(dt: datetime) -> str:
    return str(int((dt.timestamp() + _WEBKIT_OFFSET) * 1_000_000))


def _leaf(url: str, name: str, at: datetime | None = None) -> dict:
    node = {"type": "url", "name": name, "url": url}
    if at is not None:
        node["date_added"] = _webkit(at)
    return node


def _chrome(*leaves: dict, folder: str = "Bookmarks bar", other: tuple = ()) -> bytes:
    return json.dumps({"version": 1, "roots": {
        "bookmark_bar": {"type": "folder", "name": folder, "children": list(leaves)},
        "other": {"type": "folder", "name": "Other bookmarks", "children": list(other)},
    }}).encode()


A = _leaf("https://alpha.example/one", "Alpha one", NOW - timedelta(days=30))
B = _leaf("https://beta.example/two", "Beta two", NOW - timedelta(days=20))
C = _leaf("https://gamma.example/three", "Gamma three", NOW - timedelta(days=10))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    async def fake_enrich(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="", site=media_ingestor._site_of(url),
            media_type=media_ingestor._classify(url, from_bookmark_file=from_bookmark_file))

    monkeypatch.setattr(media_ingestor, "enrich", fake_enrich)


def _bank(tmp_path):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources", "inbox"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    return memory


def _sync(memory, data: bytes, **kw):
    return asyncio.run(bookmark_sync.sync_bookmarks(memory, chrome_data=data, **kw))


def _client(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def _left(memory, channel="chrome-bookmarks") -> dict:
    return bookmark_seen.left_of(bookmark_seen.read_seen(memory).get(channel))


def _h(leaf: dict) -> str:
    return media_ingestor.url_hash(leaf["url"])


def _items(memory, monkeypatch) -> dict:
    return {i["url"]: i for i in _client(memory, monkeypatch).get("/sources").json()["items"]}


# --- A few basic reasons -------------------------------------------------------------------------------------------


def test_the_panel_offers_four_reasons_and_no_project(tmp_path):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"type": "project", "name": "Alpha project", "status": "active"}, "")
    options = saved_why.options(memory)
    assert [r["key"] for r in options["reasons"]] == ["design", "product", "read_later", "someday"]
    assert [r["label"] for r in options["reasons"]] == ["The design", "The product", "To read later", "Useful someday"]
    assert options["projects"] == [], "the panel never offers projects"


def test_old_answers_keep_their_retired_reason_and_project_where_answers_are_listed(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    first = _sync(memory, _chrome(A))
    _sync(memory, _chrome(A))
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"type": "project", "name": "Alpha project", "status": "archived"}, "")
    episode = memory / "episodes" / f"{first['fresh'][0]['episode_id']}.md" if first["fresh"] else None
    if episode is None:   # the first sync reports nothing fresh; find the episode by its link
        _, _, episode = saved_why.find_episode(memory, A["url"])
    parsed = markdown_parser.parse(episode)
    parsed.frontmatter["saved_why"] = {"reasons": ["technique", "design"], "project": "alpha-project",
                                       "text": "the sync trick", "at": (NOW - timedelta(days=2)).isoformat()}
    markdown_parser.write(episode, parsed.frontmatter, parsed.body)

    why = _items(memory, monkeypatch)[A["url"]]["savedWhy"]
    assert why["reasons"] == ["technique", "design"]
    assert why["labels"] == ["A technique to reuse", "The design"]
    assert why["project"] == "alpha-project"

    # An edit of that answer may keep both, though neither is offered any more (the project is archived since).
    client = _client(memory, monkeypatch)
    r = client.put("/sources/saved-why", json={"url": A["url"], "at": why["at"], "reasons": ["technique", "someday"],
                                               "project": "alpha-project", "text": "the sync trick"})
    assert r.status_code == 200, r.text
    assert r.json()["savedWhy"]["labels"] == ["Useful someday", "A technique to reuse"]
    assert "- For Alpha project" in markdown_parser.parse(episode).body


def test_someday_is_an_answer_and_an_unknown_reason_is_refused(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A))
    client = _client(memory, monkeypatch)
    r = client.post("/sources/saved-why", json={"url": A["url"], "reasons": ["someday"]})
    assert r.status_code == 200, r.text
    assert r.json()["savedWhy"]["labels"] == ["Useful someday"]
    # G191 v7: "inspiration" joined the reason bank (`saved_why.MORE`); a key in no list is still refused.
    assert client.post("/sources/saved-why", json={"url": A["url"], "reasons": ["vibes"]}).status_code == 422


def test_someday_explores_the_minimal_capture_like_read_later():
    plan = explore_plan.plan_for({"reasons": ["someday"]})
    assert plan["depth"] == "capture"
    assert [p["kind"] for p in plan["pages"]] == ["saved"]
    assert plan["because"] == [{"from": "reason", "signal": "someday"}]
    assert explore_plan.plan_for({"reasons": ["read_later"]})["pages"] == plan["pages"]
    assert explore_candidates.depth_for({"reasons": ["someday"]}) == "capture"
    assert explore_candidates._why({"saved_why": {"reasons": ["someday"]}}) == {"reasons": ["someday"]}
    # With the design, the design's plan wins (the deepest asked).
    assert explore_plan.plan_for({"reasons": ["someday", "design"]})["depth"] == "look"


# --- Left the browser ----------------------------------------------------------------------------------------------


def test_a_bookmark_removed_in_the_browser_is_kept_and_marked_with_the_day(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    r = _sync(memory, _chrome(A, B))
    assert r["left_marked"] == 1 and r["removals_proposed"] == 0
    assert set(_left(memory)) == {_h(C)}

    items = _items(memory, monkeypatch)
    assert C["url"] in items, "Cicada keeps it"
    (left,) = items[C["url"]]["leftBrowser"]
    assert left["browser"] == "Chrome" and left["channel"] == "chrome-bookmarks"
    assert datetime.fromisoformat(left["since"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    assert items[A["url"]]["leftBrowser"] == []
    assert not list((memory / "inbox").glob("inbox-*.md")), "no inbox question"


def test_re_adding_it_clears_the_mark_and_asks_again(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    _sync(memory, _chrome(A, B))
    again = _leaf(C["url"], "Gamma three", NOW - timedelta(seconds=5))
    r = _sync(memory, _chrome(A, B, again))
    assert _left(memory) == {}
    assert [(f["url"], f["resave"]) for f in r["fresh"]] == [(C["url"], True)]
    assert _items(memory, monkeypatch)[C["url"]]["leftBrowser"] == []


def test_a_move_or_rename_never_marks_it(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    moved = _chrome({"type": "folder", "name": "Sorted", "children": [C, A]}, folder="Renamed bar", other=(B,))
    assert _sync(memory, moved)["left_marked"] == 0
    assert _sync(memory, _chrome(dict(A, name="Alpha, renamed"), B, C))["left_marked"] == 0
    assert _left(memory) == {}


def test_a_first_sync_marks_nothing_even_when_cicada_already_holds_the_links(tmp_path):
    """A browser read for the first time: links Cicada holds from elsewhere that this browser lacks are not gone."""
    memory = _bank(tmp_path)
    asyncio.run(bookmark_sync.sync_bookmarks(memory, chromium=[("brave", _chrome(A, B, C))]))
    r = _sync(memory, _chrome(A))
    assert r["left_marked"] == 0 and r["sources"][0]["first_sync"] is True
    assert _left(memory) == {} and _left(memory, "brave-bookmarks") == {}


def test_a_folder_scope_change_marks_nothing(tmp_path):
    memory = _bank(tmp_path)
    data = _chrome({"type": "folder", "name": "Reading", "children": [A, B]}, C)
    _sync(memory, data)
    r = _sync(memory, data, folders=["Bookmarks bar/Reading"])
    assert r["left_marked"] == 0 and "folder scope changed" in (r["removals_skipped"] or "")
    assert _left(memory) == {}


def test_an_empty_read_marks_nothing_and_keeps_the_last_set(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    before = bookmark_seen.read_seen(memory)["chrome-bookmarks"]["hashes"]
    r = _sync(memory, b"{ half written")
    assert r["left_marked"] == 0 and "held no bookmarks" in (r["removals_skipped"] or "")
    assert bookmark_seen.read_seen(memory)["chrome-bookmarks"]["hashes"] == before
    # The next real read is compared with the last good one: a removal there is still seen, nothing is "saved again".
    r = _sync(memory, _chrome(A, B))
    assert set(_left(memory)) == {_h(C)} and r["fresh_total"] == 0


def test_a_wholesale_swap_marks_nothing(tmp_path):
    memory = _bank(tmp_path)
    many = [_leaf(f"https://site{i}.example/", f"Site {i}", NOW - timedelta(days=40 + i)) for i in range(6)]
    _sync(memory, _chrome(*many))
    r = _sync(memory, _chrome(A, B))
    assert r["left_marked"] == 0 and "shares no bookmark" in (r["removals_skipped"] or "")
    assert _left(memory) == {}


def test_a_pending_removal_question_is_retired_into_the_status(tmp_path):
    """Before G191 v4 a bookmark leaving the browser was asked about; a question still open is retired on the
    channel's next sync, and the link carries the day that sync saw it gone. A paper's removal question stays."""
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    _sync(memory, _chrome(A, B))
    seen = bookmark_seen.read_seen(memory)
    seen["chrome-bookmarks"].pop("left", None)   # as an older backend left it
    bookmark_seen.seen_path(memory).write_text(json.dumps(seen))
    common = {"kind": "removal", "required_input": "choice", "status": "pending", "priority": 0.4,
              "options": [{"key": "keep", "label": "Keep"}, {"key": "remove", "label": "Remove"}]}
    markdown_parser.write(memory / "inbox" / "inbox-001.md", {
        **common, "entity_id": "media-gamma", "channel": "chrome-bookmarks", "browser": "Chrome", "url": C["url"],
        "synced_at": "2026-10-14T08:00:00+00:00", "trigger": "sync/bookmark_removal"}, "")
    markdown_parser.write(memory / "inbox" / "inbox-002.md", {
        **common, "entity_id": "media-paper", "channel": "folder:papers", "browser": "papers", "url": "",
        "synced_at": "2026-10-14T08:00:00+00:00", "trigger": "sync/folder_removal"}, "")
    _sync(memory, _chrome(A, B))
    assert not (memory / "inbox" / "inbox-001.md").exists()
    assert (memory / "inbox" / "inbox-002.md").exists(), "a paper's question is not a bookmark's"
    assert _left(memory) == {_h(C): "2026-10-14T08:00:00+00:00"}


def test_sources_lists_the_bookmark_that_left_the_browser_with_its_day(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    _sync(memory, _chrome(A, B))
    page = channel_items.items(memory, "chrome-bookmarks")
    by_title = {row["title"]: row for row in page["items"]}
    assert page["total"] == 3
    gone = [row for row in page["items"] if row.get("left")]
    assert len(gone) == 1 and gone[0]["left"] == _left(memory)[_h(C)]
    assert all("left" not in row for row in by_title.values() if row is not gone[0])


def test_the_sources_etag_moves_when_a_bookmark_leaves(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    client = _client(memory, monkeypatch)
    etag = client.get("/sources").headers["etag"]
    _sync(memory, _chrome(A, B))
    assert client.get("/sources", headers={"If-None-Match": etag}).status_code == 200
