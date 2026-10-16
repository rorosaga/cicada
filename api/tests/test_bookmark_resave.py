"""G191 v3 — bookmarks, round 3 (owner 2026-10-15).

* A bookmark removed and saved again is a new moment of saving: the sync reports it (``resave``) so the app asks; a
  move, a rename or a reorganisation never is.
* A re-save's answer is a new dated reason beside the earlier ones; the person can edit one answer.
* Remove forgets a bookmark in Cicada through the tombstone path (the page archived, never deleted), and a link saved
  again comes back.
* ``GET /sources`` carries every answer, the newest moment of saving and a capture thumbnail for the history list.

Synthetic bookmarks only; nothing reads a browser.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bookmark_forget, bookmark_seen, bookmark_sync, markdown_parser, saved_why

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
    from api.services import media_ingestor

    async def fake_enrich(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="", site=media_ingestor._site_of(url),
            media_type=media_ingestor._classify(url, from_bookmark_file=from_bookmark_file))

    monkeypatch.setattr(media_ingestor, "enrich", fake_enrich)


def _bank(tmp_path, *, git: bool = False):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    if git:
        for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
            subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True)
    return memory


def _sync(memory, data: bytes, **kw):
    return asyncio.run(bookmark_sync.sync_bookmarks(memory, chrome_data=data, **kw))


def _client(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


# --- Re-save versus move -------------------------------------------------------------------------------------------


def test_removed_then_saved_again_is_a_resave_with_its_held_episode(tmp_path):
    memory = _bank(tmp_path)
    first = _sync(memory, _chrome(A, B, C))
    episode = {f["url"]: f["episode_id"] for f in first["fresh"]}
    _sync(memory, _chrome(A, B))                                       # C removed in the browser
    again = _leaf(C["url"], "Gamma three", NOW - timedelta(seconds=5))
    r = _sync(memory, _chrome(A, B, again))
    assert r["fresh_total"] == 1 and r["new"] == 0
    (item,) = r["fresh"]
    assert item["resave"] is True
    assert item["episode_id"] == episode[C["url"]]                     # the link's own episode, not a new one
    assert item["added_at"] == (NOW - timedelta(seconds=5)).isoformat()


def test_removed_and_saved_again_between_two_syncs_is_a_resave_by_its_new_instant(tmp_path):
    """Chrome writes once 2.5 s after a change, so a quick remove + save can reach Cicada as one file in which the
    link never left — the node's own `date_added`, newer than anything the last sync saw, still tells."""
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    again = _leaf(C["url"], "Gamma three", NOW - timedelta(seconds=3))
    r = _sync(memory, _chrome(A, B, again))
    assert [f["url"] for f in r["fresh"]] == [C["url"]] and r["fresh"][0]["resave"] is True


def test_a_move_a_rename_and_a_reorganisation_are_never_a_resave(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    moved = _chrome({"type": "folder", "name": "Sorted", "children": [C, A]}, folder="Renamed bar", other=(B,))
    r = _sync(memory, moved)
    assert r["fresh_total"] == 0 and r["fresh"] == []
    renamed = dict(A, name="Alpha, renamed")
    assert _sync(memory, _chrome(renamed, B, C))["fresh_total"] == 0


def test_a_link_another_browser_holds_saved_here_for_the_first_time_asks(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))                                    # Chrome holds C
    safari_first = asyncio.run(bookmark_sync.sync_bookmarks(memory, chromium=[("brave", _chrome(A))]))
    assert safari_first["sources"][0]["first_sync"] is True            # a first sync never asks (the app's policy)
    r = asyncio.run(bookmark_sync.sync_bookmarks(memory, chromium=[("brave", _chrome(A, C))]))
    assert [(f["url"], f["resave"], f["channel"]) for f in r["fresh"]] == [(C["url"], True, "brave-bookmarks")]


def test_a_first_sync_or_a_changed_folder_scope_reports_no_resave(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B))
    seen = bookmark_seen.read_seen(memory)["chrome-bookmarks"]
    assert seen["newest_added"] == (NOW - timedelta(days=20)).isoformat()
    scoped = _sync(memory, _chrome(A, B, C), folders=["Bookmarks bar"])
    assert all(not f.get("resave") for f in scoped["fresh"])


def test_the_early_look_reports_a_resave_and_writes_nothing(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(A, B, C))
    _sync(memory, _chrome(A, B))
    before = {p: p.read_bytes() for p in memory.rglob("*") if p.is_file()}
    look = bookmark_sync.fresh_preview(memory, chrome_data=_chrome(A, B, _leaf(C["url"], "Gamma three", NOW)))
    assert [(f["url"], f["resave"]) for f in look["fresh"]] == [(C["url"], True)]
    assert {p: p.read_bytes() for p in memory.rglob("*") if p.is_file()} == before


def test_a_resave_of_a_removed_bookmark_brings_it_back(tmp_path):
    memory = _bank(tmp_path, git=True)
    first = _sync(memory, _chrome(A, C))
    c = next(f for f in first["fresh"] if f["url"] == C["url"])
    bookmark_forget.forget(memory, url=C["url"])
    assert markdown_parser.parse(memory / "entities" / f"{c['media_entity_id']}.md").frontmatter["status"] == "archived"
    _sync(memory, _chrome(A))                                          # gone from Chrome too
    r = _sync(memory, _chrome(A, _leaf(C["url"], "Gamma three", NOW)))
    assert r["fresh"][0]["resave"] is True
    page = markdown_parser.parse(memory / "entities" / f"{c['media_entity_id']}.md").frontmatter
    assert page["status"] == "active" and "removed_at" not in page
    ep = markdown_parser.parse(memory / "episodes" / f"{c['episode_id']}.md").frontmatter
    assert bookmark_forget.TOMBSTONE not in ep
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True,
                         check=True).stdout
    assert "sync/bookmark_resave" in log and "Cicada-Author: cicada" in log
    assert subprocess.run(["git", "-C", str(memory), "status", "--porcelain"], capture_output=True, text=True,
                          check=True).stdout == ""


# --- A new dated reason per moment of saving, and the person's edit ------------------------------------------------


def _saved(memory, monkeypatch):
    _sync(memory, _chrome(A))
    first = _sync(memory, _chrome(A, C))
    return first["fresh"][0], _client(memory, monkeypatch)


def _at(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).replace(microsecond=0).isoformat()


def test_a_resaves_answer_adds_a_dated_reason_and_replaces_none(tmp_path, monkeypatch):
    memory = _bank(tmp_path, git=True)
    item, client = _saved(memory, monkeypatch)
    first_at, second_at = _at(30), _at(1)
    resaved_at = (NOW - timedelta(seconds=90)).isoformat()
    assert client.post("/sources/saved-why", json={"url": C["url"], "reasons": ["design"], "at": first_at,
                                                   "addedAt": item["added_at"]}).status_code == 200
    r = client.post("/sources/saved-why", json={"url": C["url"], "reasons": ["technique"], "text": "the sync trick",
                                                "at": second_at, "addedAt": resaved_at})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["savedWhy"]["reasons"] == ["technique"] and body["savedWhy"]["addedAt"] == resaved_at
    assert [h["reasons"] for h in body["history"]] == [["design"], ["technique"]]

    parsed = markdown_parser.parse(memory / "episodes" / f"{item['episode_id']}.md")
    assert parsed.frontmatter["saved_why"]["at"] == second_at
    assert [r["at"] for r in parsed.frontmatter[saved_why.EARLIER_KEY]] == [first_at]
    assert parsed.body.count(saved_why.HEADING) == 1
    section = parsed.body[parsed.body.index(saved_why.HEADING):]
    assert section.index("The design") < section.index("A technique to reuse")   # oldest first
    assert f"about a bookmark saved {resaved_at}" in section

    items = {i["url"]: i for i in client.get("/sources").json()["items"]}
    row = items[C["url"]]
    assert [h["at"] for h in row["savedWhyHistory"]] == [first_at, second_at]
    assert row["savedWhy"]["at"] == second_at
    assert row["lastSavedAt"] == resaved_at                            # the re-save moves the bookmark up


def test_an_answer_held_and_sent_again_is_one_answer(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    item, client = _saved(memory, monkeypatch)
    said = _at(5)
    for _ in range(2):
        assert client.post("/sources/saved-why", json={"url": C["url"], "reasons": ["design"],
                                                       "at": said}).status_code == 200
    fm = markdown_parser.parse(memory / "episodes" / f"{item['episode_id']}.md").frontmatter
    assert saved_why.EARLIER_KEY not in fm


def test_the_person_edits_one_answer_and_keeps_the_others(tmp_path, monkeypatch):
    memory = _bank(tmp_path, git=True)
    item, client = _saved(memory, monkeypatch)
    first_at, second_at = _at(40), _at(2)
    client.post("/sources/saved-why", json={"url": C["url"], "reasons": ["design"], "at": first_at})
    client.post("/sources/saved-why", json={"url": C["url"], "reasons": ["product"], "at": second_at,
                                            "addedAt": NOW.isoformat()})
    r = client.put("/sources/saved-why", json={"url": C["url"], "at": first_at.replace("+00:00", "Z"),
                                               "reasons": ["design", "read_later"], "text": "their launch video"})
    assert r.status_code == 200, r.text
    hist = r.json()["history"]
    assert [h["reasons"] for h in hist] == [["design", "read_later"], ["product"]]
    assert hist[0]["at"] == first_at and hist[0]["editedAt"] and hist[0]["text"] == "their launch video"
    assert hist[1]["editedAt"] is None
    parsed = markdown_parser.parse(memory / "episodes" / f"{item['episode_id']}.md")
    assert parsed.frontmatter["processed"] is False
    assert "their launch video" in parsed.body and "- The product" in parsed.body
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True,
                         check=True).stdout
    assert "Cicada-Author: user" in log and saved_why.TRIGGER in log


@pytest.mark.parametrize("body,status", [
    ({"url": C["url"], "at": "2026-01-01T00:00:00Z", "reasons": ["design"]}, 404),   # no answer at that time
    ({"url": C["url"], "at": "whenever", "reasons": ["design"]}, 422),
    ({"url": "https://nowhere.example/x", "at": "2026-01-01T00:00:00Z", "reasons": ["design"]}, 404),
    ({"url": C["url"], "at": "2026-01-01T00:00:00Z"}, 422),                           # names nothing
])
def test_an_edit_that_names_nothing_held_is_refused_unwritten(tmp_path, monkeypatch, body, status):
    memory = _bank(tmp_path)
    item, client = _saved(memory, monkeypatch)
    client.post("/sources/saved-why", json={"url": C["url"], "reasons": ["design"]})
    path = memory / "episodes" / f"{item['episode_id']}.md"
    before = path.read_text()
    assert client.put("/sources/saved-why", json=body).status_code == status
    assert path.read_text() == before


# --- Remove ------------------------------------------------------------------------------------------------------


def test_remove_archives_the_page_tombstones_the_episode_and_commits_as_the_person(tmp_path, monkeypatch):
    memory = _bank(tmp_path, git=True)
    item, client = _saved(memory, monkeypatch)
    client.post("/sources/saved-why", json={"url": C["url"], "reasons": ["design"]})
    r = client.post("/sources/bookmarks/remove", json={"url": C["url"]})
    assert r.status_code == 200, r.text
    assert r.json() == {"episodeId": item["episode_id"], "mediaEntityId": item["media_entity_id"],
                        "status": "archived"}
    page = memory / "entities" / f"{item['media_entity_id']}.md"
    assert page.is_file()                                              # never deleted
    assert markdown_parser.parse(page).frontmatter["status"] == "archived"
    ep = markdown_parser.parse(memory / "episodes" / f"{item['episode_id']}.md")
    assert ep.frontmatter[bookmark_forget.TOMBSTONE]
    assert ep.frontmatter["saved_why"]["reasons"] == ["design"]       # what the person said stays said
    assert C["url"] not in {i["url"] for i in client.get("/sources").json()["items"]}
    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True,
                         check=True).stdout
    assert "Cicada-Author: user" in log and bookmark_forget.TRIGGER in log
    again = client.post("/sources/bookmarks/remove", json={"url": C["url"]})
    assert again.status_code == 200                                    # idempotent


def test_remove_after_the_browser_drops_it_asks_nothing(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    item, client = _saved(memory, monkeypatch)
    client.post("/sources/bookmarks/remove", json={"url": C["url"]})
    r = _sync(memory, _chrome(A))                                      # the app removed it from Chrome
    assert r["removals_proposed"] == 0                                 # an archived page is never asked about


@pytest.mark.parametrize("url,status", [("https://nowhere.example/x", 404), ("ftp://gamma.example", 422)])
def test_remove_refuses_a_link_not_held(tmp_path, monkeypatch, url, status):
    memory = _bank(tmp_path)
    _saved(memory, monkeypatch)
    assert _client(memory, monkeypatch).post("/sources/bookmarks/remove", json={"url": url}).status_code == status


def test_remove_while_sleep_holds_the_pages_is_refused(tmp_path, monkeypatch):
    from api.services import write_admission

    memory = _bank(tmp_path)
    item, client = _saved(memory, monkeypatch)
    page = memory / "entities" / f"{item['media_entity_id']}.md"
    before = page.read_text()
    monkeypatch.setattr(write_admission, "holding", lambda: True)
    assert client.post("/sources/bookmarks/remove", json={"url": C["url"]}).status_code == 409
    assert page.read_text() == before


# --- The history list's wire ---------------------------------------------------------------------------------------


def test_a_captured_page_carries_its_newest_thumbnail(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    item, client = _saved(memory, monkeypatch)
    entity = item["media_entity_id"]
    folder = memory / "captures" / entity
    folder.mkdir(parents=True)
    thumbs = memory / "assets" / "captures"
    thumbs.mkdir(parents=True)
    (thumbs / "0123456789abcdef.jpg").write_bytes(b"\xff\xd8\xff")
    rel = "assets/captures/0123456789abcdef.jpg"
    markdown_parser.write(folder / "20261014T100000Z-abcdef.md",
                          {"entity": entity, "captured_at": "2026-10-14T10:00:00+00:00",
                           "thumb": {"file": rel, "width": 640, "height": 400}}, "")
    items = {i["url"]: i for i in client.get("/sources").json()["items"]}
    assert items[C["url"]]["captureThumb"] == f"/explore/captures/{entity}/20261014T100000Z-abcdef/thumb"
    assert items[A["url"]]["captureThumb"] is None
