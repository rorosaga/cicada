"""G191 — ask why at the moment of saving.

The sync reports which bookmarks it newly saved (with the browser's own instant), never after a first sync or a
reorganisation; the person's answer lands on that bookmark's episode through the one staging path (scrubbed, queued
for Sleep, committed alone as the person), is refused in a demo bank, and rides the source record on the wire.
Synthetic bookmarks only.
"""
from __future__ import annotations

import asyncio
import base64
import json
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import (bank_registry, bookmark_sync, demo_guard, episode_staging, markdown_parser, saved_at,
                          saved_why)

_WEBKIT_OFFSET = 11_644_473_600


def _webkit(dt: datetime) -> str:
    return str(int((dt.timestamp() + _WEBKIT_OFFSET) * 1_000_000))


def _chrome(*leaves: dict, folder: str = "Bookmarks bar") -> bytes:
    return json.dumps({"version": 1, "roots": {
        "bookmark_bar": {"type": "folder", "name": folder, "children": list(leaves)},
        "other": {"type": "folder", "name": "Other bookmarks", "children": []},
    }}).encode()


def _leaf(url: str, name: str, at: datetime | None = None) -> dict:
    node = {"type": "url", "name": name, "url": url}
    if at is not None:
        node["date_added"] = _webkit(at)
    return node


NOW = datetime.now(timezone.utc).replace(microsecond=0)
OLD_A = _leaf("https://alpha.example/one", "Alpha one", NOW - timedelta(days=30))
OLD_B = _leaf("https://beta.example/two", "Beta two", NOW - timedelta(days=20))
NEW_C = _leaf("https://gamma.example/three", "Gamma three", NOW - timedelta(seconds=40))


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    from api.services import media_ingestor

    async def fake_enrich(url, client, from_bookmark_file=False):
        return media_ingestor.MediaMeta(
            title=media_ingestor._fallback_title(url), description="", site=media_ingestor._site_of(url),
            media_type=media_ingestor._classify(url, from_bookmark_file=from_bookmark_file))

    monkeypatch.setattr(media_ingestor, "enrich", fake_enrich)


def run(coro):
    return asyncio.run(coro)


def _bank(tmp_path, *, git: bool = False):
    memory = tmp_path / "memory"
    for sub in ("episodes", "entities", "sources"):
        (memory / sub).mkdir(parents=True, exist_ok=True)
    if git:
        for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
            subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True)
    return memory


def _client(memory, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    return TestClient(main.app)


def _sync(memory, data: bytes):
    return run(bookmark_sync.sync_bookmarks(memory, chrome_data=data))


# --- The instant -------------------------------------------------------------------------------------------------


def test_the_browser_instant_is_kept_beside_the_day():
    at = datetime(2026, 10, 14, 9, 30, 15, tzinfo=timezone.utc)
    assert saved_at.instant_from_webkit_micros(_webkit(at)) == "2026-10-14T09:30:15+00:00"
    assert saved_at.instant_from_webkit_micros("0") is None            # 1601: a unit bug, never a date
    assert saved_at.instant_from_webkit_micros("not a number") is None
    assert saved_at.instant_from_plist_date(datetime(2026, 10, 14, 9, 30, 15)) == "2026-10-14T09:30:15+00:00"
    assert saved_at.validate_instant("2026-10-14") is None              # a bare day is not an instant
    assert saved_at.validate_instant("2026-10-14T09:30:15Z") == "2026-10-14T09:30:15+00:00"
    assert saved_at.validate_instant("2026-10-14T09:30:15") is None     # naive: never guessed to be UTC


# --- The trigger's facts: what a sync newly saved ------------------------------------------------------------------


def test_a_first_sync_saves_everything_but_says_it_was_a_first_sync(tmp_path):
    memory = _bank(tmp_path)
    r = _sync(memory, _chrome(OLD_A, OLD_B))
    assert r["fresh_total"] == 2
    assert r["sources"][0]["first_sync"] is True


def test_one_new_bookmark_is_reported_with_its_episode_and_instant(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(OLD_A, OLD_B))
    r = _sync(memory, _chrome(OLD_A, OLD_B, NEW_C))
    assert r["sources"][0]["first_sync"] is False
    assert r["fresh_total"] == 1
    (item,) = r["fresh"]
    assert item["url"] == NEW_C["url"]
    assert item["channel"] == "chrome-bookmarks"
    assert item["added_at"] == (NOW - timedelta(seconds=40)).isoformat()
    fm = markdown_parser.parse(memory / "episodes" / f"{item['episode_id']}.md").frontmatter
    assert fm["added_at"] == item["added_at"]                          # the record keeps WHEN it was saved
    assert fm["saved_at"] == (NOW - timedelta(seconds=40)).strftime("%Y-%m-%d")


def test_a_reorganisation_saves_nothing_new(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(OLD_A, OLD_B))
    moved = _chrome({"type": "folder", "name": "Sorted", "children": [OLD_B, OLD_A]}, folder="Renamed bar")
    r = _sync(memory, moved)
    assert r["fresh_total"] == 0 and r["fresh"] == []


def test_a_bulk_import_is_reported_as_many_and_capped(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome(OLD_A))
    many = [_leaf(f"https://bulk.example/{i}", f"Bulk {i}", NOW) for i in range(6)]
    r = _sync(memory, _chrome(OLD_A, *many))
    assert r["fresh_total"] == 6
    assert len(r["fresh"]) == bookmark_sync.FRESH_CAP


def test_the_sync_route_carries_the_fresh_list_on_the_wire(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    client = _client(memory, monkeypatch)
    b64 = lambda d: base64.b64encode(d).decode()  # noqa: E731
    client.post("/sources/sync-bookmarks", json={"chromeDataB64": b64(_chrome(OLD_A))})
    body = client.post("/sources/sync-bookmarks", json={"chromeDataB64": b64(_chrome(OLD_A, NEW_C))}).json()
    assert body["freshTotal"] == 1
    assert body["fresh"][0]["url"] == NEW_C["url"] and body["fresh"][0]["addedAt"]
    assert body["sources"][0]["firstSync"] is False


# --- The answer on the episode -----------------------------------------------------------------------------------


def _saved_c(memory):
    _sync(memory, _chrome(OLD_A))
    r = _sync(memory, _chrome(OLD_A, NEW_C))
    return r["fresh"][0]["episode_id"]


def test_the_answer_lands_on_the_bookmark_episode_scrubbed_and_queued(tmp_path, monkeypatch):
    memory = _bank(tmp_path, git=True)
    episode_id = _saved_c(memory)
    path = memory / "episodes" / f"{episode_id}.md"
    # Sleep already read it: the person's answer must queue it again.
    fm = markdown_parser.parse(path).frontmatter
    fm.update(processed=True, processed_by="sleep")
    markdown_parser.write(path, fm, markdown_parser.parse(path).body)

    client = _client(memory, monkeypatch)
    secret = "sk-" + "a1" * 12
    r = client.post("/sources/saved-why", json={
        "url": NEW_C["url"], "reasons": ["product", "design"], "text": f"their onboarding, key {secret}"})
    assert r.status_code == 200, r.text
    body = r.json()["savedWhy"]
    assert body["reasons"] == ["design", "product"]                 # the panel's order, not the tap order
    assert body["labels"] == ["The design, the look", "The product itself"]
    assert secret not in (body["text"] or "") and "their onboarding" in body["text"]
    assert body["addedAt"] == (NOW - timedelta(seconds=40)).isoformat()
    assert body["at"]

    parsed = markdown_parser.parse(path)
    assert parsed.frontmatter["processed"] is False
    assert "processed_by" not in parsed.frontmatter
    assert parsed.frontmatter["saved_why"]["reasons"] == ["design", "product"]
    assert secret not in parsed.body
    assert parsed.body.count(saved_why.HEADING) == 1
    assert "- The design, the look" in parsed.body and "- The product itself" in parsed.body
    assert f"about a bookmark saved {body['addedAt']}" in parsed.body

    log = subprocess.run(["git", "-C", str(memory), "log", "-1", "--format=%B"], capture_output=True, text=True,
                         check=True).stdout
    assert "Cicada-Author: user" in log and saved_why.TRIGGER in log
    assert f"episodes/{episode_id}.md" in log


def test_the_same_answer_again_replaces_itself_and_never_twins_the_section(tmp_path, monkeypatch):
    """The app's retry of a held answer (the same `at`) or the same moment of saving answered again (the same
    `addedAt`) replaces its own answer; G191 v3 keeps every other moment's answer (test_bookmark_resave.py)."""
    memory = _bank(tmp_path)
    episode_id = _saved_c(memory)
    client = _client(memory, monkeypatch)
    said = (datetime.now(timezone.utc) - timedelta(minutes=2)).replace(microsecond=0).isoformat()
    added = (NOW - timedelta(seconds=40)).isoformat()
    assert client.post("/sources/saved-why", json={"url": NEW_C["url"], "reasons": ["design"], "at": said,
                                                   "addedAt": added}).status_code == 200
    assert client.post("/sources/saved-why", json={"url": NEW_C["url"], "reasons": ["read_later"],
                                                   "addedAt": added}).status_code == 200
    parsed = markdown_parser.parse(memory / "episodes" / f"{episode_id}.md")
    assert parsed.body.count(saved_why.HEADING) == 1
    assert "To read later" in parsed.body and "The design, the look" not in parsed.body
    assert saved_why.EARLIER_KEY not in parsed.frontmatter


def test_the_section_sits_above_an_agents_note_so_it_is_read_as_the_persons(tmp_path):
    path = tmp_path / "episodes" / "ep_2026-10-14_001.md"
    path.parent.mkdir(parents=True)
    markdown_parser.write(path, {"id": "ep_2026-10-14_001", "processed": True},
                          "# A page\n\n**URL:** https://alpha.example\n\n## Note\nassistant: an agent's words\n")
    assert episode_staging.amend_section(path, saved_why.HEADING, "- To read later", writer="saved-why",
                                         before=("## Note",))
    from api.services import evidence

    text = markdown_parser.parse(path).body
    at = text.index("- To read later")
    assert at < text.index("## Note")
    assert evidence.speaker_kind(text, at) == "user"


def test_a_project_answer_is_named_and_must_be_a_live_project(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    episode_id = _saved_c(memory)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"type": "project", "name": "Alpha project", "status": "active"}, "# Alpha project\n")
    markdown_parser.write(memory / "entities" / "old-project.md",
                          {"type": "project", "name": "Old project", "status": "archived"}, "# Old project\n")
    client = _client(memory, monkeypatch)
    assert client.post("/sources/saved-why", json={"url": NEW_C["url"], "project": "old-project"}).status_code == 422
    r = client.post("/sources/saved-why", json={"url": NEW_C["url"], "project": "alpha-project"})
    assert r.status_code == 200, r.text
    assert r.json()["savedWhy"]["project"] == "alpha-project"
    assert "- For Alpha project" in markdown_parser.parse(memory / "episodes" / f"{episode_id}.md").body


@pytest.mark.parametrize("body,status", [
    ({"url": "https://nowhere.example/x", "reasons": ["design"]}, 404),
    ({"url": NEW_C["url"]}, 422),
    ({"url": NEW_C["url"], "reasons": ["vibes"]}, 422),
    ({"url": NEW_C["url"], "text": "x" * (saved_why.MAX_TEXT + 1)}, 422),
    ({"url": "ftp://gamma.example", "reasons": ["design"]}, 422),
])
def test_an_answer_that_names_nothing_or_nothing_saved_is_refused_unwritten(tmp_path, monkeypatch, body, status):
    memory = _bank(tmp_path)
    episode_id = _saved_c(memory)
    before = (memory / "episodes" / f"{episode_id}.md").read_text()
    assert _client(memory, monkeypatch).post("/sources/saved-why", json=body).status_code == status
    assert (memory / "episodes" / f"{episode_id}.md").read_text() == before


def test_a_demo_bank_refuses_the_answer_and_writes_nothing(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    slug = bank_registry.create_bank(root, "demo")
    demo = bank_registry.bank_dir(root, slug)
    demo_guard.write_manifest(demo)
    bank_registry.activate_bank(root, slug)
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    try:
        before = sorted(p.as_posix() for p in demo.rglob("*") if p.is_file() and ".git" not in p.parts)
        r = TestClient(main.app).post("/sources/saved-why", json={"url": NEW_C["url"], "reasons": ["design"]})
        assert r.status_code == 409
        assert r.json()["detail"] == demo_guard.REFUSAL
        assert sorted(p.as_posix() for p in demo.rglob("*") if p.is_file() and ".git" not in p.parts) == before
    finally:
        config.get_settings.cache_clear()


def test_sleep_holding_the_pages_refuses_the_answer(tmp_path, monkeypatch):
    from api.services import write_admission

    memory = _bank(tmp_path)
    episode_id = _saved_c(memory)
    before = (memory / "episodes" / f"{episode_id}.md").read_text()
    monkeypatch.setattr(write_admission, "holding", lambda: True)
    r = _client(memory, monkeypatch).post("/sources/saved-why", json={"url": NEW_C["url"], "reasons": ["design"]})
    assert r.status_code == 409
    assert (memory / "episodes" / f"{episode_id}.md").read_text() == before


# --- The wire: the source record ---------------------------------------------------------------------------------


def test_the_source_record_carries_the_intent_for_a_later_reader(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _saved_c(memory)
    client = _client(memory, monkeypatch)
    items = {i["url"]: i for i in client.get("/sources").json()["items"]}
    assert items[NEW_C["url"]]["savedWhy"] is None                     # nobody asked yet: no record, never a guess
    client.post("/sources/saved-why", json={"url": NEW_C["url"], "reasons": ["technique"], "text": "the sync trick"})
    items = {i["url"]: i for i in client.get("/sources").json()["items"]}
    why = items[NEW_C["url"]]["savedWhy"]
    assert why["reasons"] == ["technique"] and why["labels"] == ["A technique to reuse"]
    assert why["text"] == "the sync trick"
    assert why["addedAt"] == (NOW - timedelta(seconds=40)).isoformat() and why["at"]
    assert items[OLD_A["url"]]["savedWhy"] is None


def test_the_options_are_the_fixed_reasons_plus_live_projects_backlog_first(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    for stem, name, last in (("alpha-project", "Alpha", "2026-10-01"), ("beta-project", "Beta", "2026-10-10"),
                             ("gamma-project", "Gamma", "2026-09-01"), ("delta-project", "Delta", "2026-10-12")):
        markdown_parser.write(memory / "entities" / f"{stem}.md",
                              {"type": "project", "name": name, "status": "active", "last_referenced": last}, "")
    markdown_parser.write(memory / "entities" / "gone-project.md",
                          {"type": "project", "name": "Gone", "status": "dropped", "last_referenced": "2026-10-13"},
                          "")
    from api.services import backlog

    backlog.add_item(memory, project="gamma-project", title="An open item", author="user")
    body = _client(memory, monkeypatch).get("/sources/saved-why/options").json()
    assert [r["key"] for r in body["reasons"]] == list(saved_why.REASONS)
    assert [p["id"] for p in body["projects"]] == ["gamma-project", "delta-project", "beta-project"]
    assert body["maxText"] == saved_why.MAX_TEXT


def test_a_renamed_folder_saves_nothing_new(tmp_path):
    memory = _bank(tmp_path)
    _sync(memory, _chrome({"type": "folder", "name": "Reading", "children": [OLD_A, OLD_B]}))
    r = _sync(memory, _chrome({"type": "folder", "name": "Reading (old)", "children": [OLD_A, OLD_B]}))
    assert r["fresh_total"] == 0 and r["sources"][0]["first_sync"] is False


def test_a_bookmark_deleted_and_added_again_is_a_new_moment_of_saving(tmp_path):
    """G191 v3 (owner 2026-10-15) — was "is not new": removing and bookmarking again now asks, as a re-save."""
    memory = _bank(tmp_path)
    _sync(memory, _chrome(OLD_A, NEW_C))
    _sync(memory, _chrome(OLD_A))                                      # deleted in the browser
    readded = _leaf(NEW_C["url"], "Gamma three", NOW)                  # re-added a moment ago
    r = _sync(memory, _chrome(OLD_A, readded))
    assert r["fresh_total"] == 1
    (item,) = r["fresh"]
    assert item["url"] == NEW_C["url"] and item["resave"] is True and item["episode_id"]
    assert r["new"] == 0                                               # nothing re-ingested: the link is held


def test_a_held_answer_keeps_the_time_the_person_gave_it(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    episode_id = _saved_c(memory)
    client = _client(memory, monkeypatch)
    said = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(microsecond=0)
    r = client.post("/sources/saved-why", json={"url": NEW_C["url"], "reasons": ["design"],
                                                "at": said.isoformat().replace("+00:00", "Z")})
    assert r.status_code == 200, r.text
    assert r.json()["savedWhy"]["at"] == said.isoformat()
    fm = markdown_parser.parse(memory / "episodes" / f"{episode_id}.md").frontmatter
    assert fm["saved_why"]["at"] == said.isoformat()


@pytest.mark.parametrize("at", [
    "2026-10-14T09:30:00",          # naive: never assumed UTC
    timedelta(minutes=10),          # the future (an offset from now, computed when the test runs)
    -timedelta(hours=25),           # over a day old
    "yesterday",
])
def test_a_client_time_is_bounded(tmp_path, monkeypatch, at):
    if isinstance(at, timedelta):
        at = (datetime.now(timezone.utc) + at).isoformat()
    memory = _bank(tmp_path)
    episode_id = _saved_c(memory)
    before = (memory / "episodes" / f"{episode_id}.md").read_text()
    r = _client(memory, monkeypatch).post("/sources/saved-why",
                                          json={"url": NEW_C["url"], "reasons": ["design"], "at": at})
    assert r.status_code == 422
    assert (memory / "episodes" / f"{episode_id}.md").read_text() == before
