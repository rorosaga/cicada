"""G219: Apple Reminders through EventKit — the backend half. The app posts the reminders of the lists the person
ticked (open ones plus those completed in the last 90 days); each is one episode through the G20 stager, scrubbed,
dated by its own creation or completion (never its due date), edited in place, tombstoned only for a named list,
committed once per sync as the person, refused in a demo bank. An EventKit-shaped payload with placeholders only."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import bank_index, channel_items, channel_registry, demo_guard, inbox_tend, markdown_parser
from api.services import reminders_local, source_overview

IDEAS = {"id": "list-ideas", "title": "Ideas", "account": "iCloud"}
HOME = {"id": "list-home", "title": "Home", "shared": True}
SINCE = "2026-07-25T00:00:00+00:00"


@pytest.fixture
def client(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def _reminder(rid, title="Try alpha-project on the old laptop", lst="list-ideas", **kw):
    """EventKit's `EKReminder`, as `RemindersMapper.record` posts it (camelCase on the wire)."""
    return {"id": rid, "listId": lst, "title": title, "created": "2026-09-20T09:15:00+02:00",
            "lastModified": "2026-09-20T09:15:00+02:00", "completed": False, "priority": 0, **kw}


def _post(c, reminders, lists=(IDEAS, HOME), since=SINCE):
    return c.post("/sources/reminders-local/sync",
                  json={"completedSince": since, "lists": list(lists), "reminders": reminders})


def _episodes(memory):
    out = {}
    for path in sorted((memory / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        sid = str(parsed.frontmatter.get("source_id") or "")
        if sid.startswith("reminders-local:"):
            out[sid] = (path, parsed)
    return out


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout


def test_a_first_sync_stages_one_episode_per_reminder_dated_by_creation_and_commits_once(client):
    c, memory = client
    r = _post(c, [_reminder("R1", notes="Ask bob-example which charger", due="2026-11-02", dueAllDay=True,
                            priority=1, url="https://example.com/path?token=abc")])
    assert r.status_code == 200, r.text
    assert r.json() == {"created": 1, "updated": 0, "unchanged": 0, "tombstoned": 0, "bank": memory.name}
    [(sid, (path, ep))] = _episodes(memory).items()
    assert sid == "reminders-local:R1"
    fm = ep.frontmatter
    assert (fm["origin"], fm["source"], fm["processed"], fm["evidence_kind"]) == (
        "reminders-local", "reminders-local", False, "user")
    # Dated when it was written down, never when it is due (2026-11-02) and never the sync day.
    assert fm["timestamp"].startswith("2026-09-20T07:15:00")
    assert path.name.startswith("ep_2026-09-20_")
    assert fm["reminder_due"] == "2026-11-02" and fm["reminder_completed_at"] is None
    assert ep.body.startswith("# Try alpha-project on the old laptop\n\n**List:** Ideas (iCloud)\n**Status:** Open")
    assert "**Due:** 2026-11-02 (all-day)" in ep.body and "**Priority:** High" in ep.body
    assert "**Link:** https://example.com/path" in ep.body and "token" not in ep.body
    assert "## Notes\nAsk bob-example which charger" in ep.body
    log = _git(memory, "log", "-1", "--format=%B")
    assert log.startswith("Reminders sync") and "capture/reminders" in log and "Cicada-Author: user" in log


def test_the_same_read_again_changes_nothing_and_commits_nothing(client):
    c, memory = client
    _post(c, [_reminder("R1")])
    before = _git(memory, "rev-parse", "HEAD")
    assert _post(c, [_reminder("R1")]).json()["unchanged"] == 1
    assert _git(memory, "rev-parse", "HEAD") == before


def test_completing_a_reminder_moves_its_episode_to_the_completion_in_place(client):
    c, memory = client
    _post(c, [_reminder("R1")])
    [(path, first)] = _episodes(memory).values()
    r = _post(c, [_reminder("R1", completed=True, completedAt="2026-10-20T18:00:00+02:00")])
    assert r.json()["updated"] == 1
    [(same, ep)] = _episodes(memory).values()
    assert same == path, "same file, same id (ruling 34)"
    fm = ep.frontmatter
    assert fm["timestamp"].startswith("2026-10-20T16:00:00") and fm["redated_from"] == first.frontmatter["timestamp"]
    assert fm["reminder_completed_at"].startswith("2026-10-20T16:00:00") and fm["processed"] is False
    assert "**Status:** Completed 2026-10-20T18:00:00+02:00" in ep.body
    # Reopened: the completion goes back to null, so the tombstone rule reads it as open again.
    _post(c, [_reminder("R1")])
    [(_, reopened)] = _episodes(memory).values()
    assert reopened.frontmatter["reminder_completed_at"] is None


def test_a_reminder_gone_from_a_named_list_is_tombstoned_never_deleted(client):
    c, memory = client
    _post(c, [_reminder("R1"), _reminder("R2", title="Renew the alpha-project domain")])
    r = _post(c, [_reminder("R1")])
    assert r.json()["tombstoned"] == 1
    eps = _episodes(memory)
    assert eps["reminders-local:R2"][1].frontmatter.get("source_deleted_at")
    assert eps["reminders-local:R2"][0].exists()


def test_an_unticked_list_says_nothing_about_its_reminders(client):
    c, memory = client
    _post(c, [_reminder("R1"), _reminder("H1", title="Water the plants", lst="list-home")])
    r = _post(c, [_reminder("R1")], lists=(IDEAS,))
    assert r.json()["tombstoned"] == 0
    assert not _episodes(memory)["reminders-local:H1"][1].frontmatter.get("source_deleted_at")


def test_a_completed_reminder_that_aged_out_of_the_window_is_kept(client):
    c, memory = client
    _post(c, [_reminder("R1", completed=True, completedAt="2026-07-30T10:00:00+00:00")])
    # Ninety days later the app's window starts after its completion: it left the read, not Reminders.
    r = _post(c, [], since="2026-08-15T00:00:00+00:00")
    assert r.json()["tombstoned"] == 0
    # Inside the window and not posted: deleted in Reminders.
    _post(c, [_reminder("R2", completed=True, completedAt="2026-09-01T10:00:00+00:00")])
    assert _post(c, [], since="2026-08-15T00:00:00+00:00").json()["tombstoned"] == 1


def test_a_list_others_add_to_is_never_the_persons_own_words(client):
    c, memory = client
    _post(c, [_reminder("H1", title="Buy bread", lst="list-home")])
    fm = _episodes(memory)["reminders-local:H1"][1].frontmatter
    assert fm["evidence_kind"] == "assistant" and fm["reminder_list_shared"] is True


def test_notes_and_titles_are_scrubbed(client):
    c, memory = client
    _post(c, [_reminder("R1", title="key sk-ant-api03-" + "a" * 40, notes="code sk-ant-api03-" + "b" * 40)])
    [(path, ep)] = _episodes(memory).values()
    assert "sk-ant" not in path.read_text()


def test_a_reminder_with_no_dates_is_dated_the_day_cicada_learned_of_it(client):
    c, memory = client
    item = _reminder("R1")
    item.pop("created")
    assert _post(c, [item]).status_code == 200
    [(_, ep)] = _episodes(memory).values()
    assert ep.frontmatter["timestamp"]


def test_a_reminder_from_a_list_not_named_is_never_staged(client):
    c, memory = client
    r = _post(c, [_reminder("X1", lst="list-other")])
    assert r.json()["created"] == 0 and _episodes(memory) == {}


def test_a_window_with_no_offset_is_refused_and_stages_nothing(client):
    c, memory = client
    r = _post(c, [_reminder("R1")], since="2026-07-25T00:00:00")
    assert r.status_code == 422 and _episodes(memory) == {}


def test_the_demo_bank_refuses(client, monkeypatch):
    c, memory = client
    monkeypatch.setattr(demo_guard, "is_demo", lambda path: True)
    assert _post(c, [_reminder("R1")]).status_code == 409
    assert _episodes(memory) == {}


def test_the_channel_row_is_always_listed_and_lists_what_came_in(client):
    c, memory = client
    def rows():
        return {r["id"]: r for r in c.get("/sources/channels").json()["channels"]}

    assert rows()["reminders-local"]["connected"] is False
    assert channel_registry.CHANNELS_SHAPE == "g219"
    _post(c, [_reminder("R1")])
    row = rows()["reminders-local"]
    assert row["connected"] is True and row["count"] == 1 and row["label"] == "Apple Reminders"
    assert row["actions"] == ["sync", "manage"]
    assert channel_items.known(memory, "reminders-local")
    page = c.get("/sources/channels/reminders-local/items").json()
    assert any("alpha-project" in (i.get("title") or "") for i in page["items"])


def test_a_reminder_is_a_record_and_its_own_overview_row():
    assert inbox_tend.record_origin("reminders-local") and not inbox_tend.saved_origin("reminders-local")
    spec = next(s for s in source_overview.CATALOG if s.id == "reminders-local")
    assert (spec.kind, spec.channel) == ("import", "reminders-local")
    assert reminders_local.SCRUB_WRITER in __import__("api.services.episode_scrub", fromlist=["WRITERS"]).WRITERS
