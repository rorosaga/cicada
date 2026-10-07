"""G177/G183(a) — every route that rewrites a bank page refuses while Sleep holds the pages, and works between a
drain's batches.

`sleep_cycle.is_writing()` is the one predicate (never `status == "running"`): a person-started drain is writable
between batches. The window is simulated through `get_sleep_state`, the accessor `is_writing` reads.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import markdown_parser, sleep_cycle


def _git(repo, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "inbox").mkdir()
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "alpha-project", "type": "project", "status": "active", "confidence": 0.8},
                          "## Summary\nx\n")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "alpha-project", "title": "Still tracking alpha-project?",
                           "created_date": "2026-10-01"},
                          "context")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


ROUTES = [
    ("put", "/entities/alpha-project/decay", {"decayClass": "durable"}),
    ("patch", "/entities/alpha-project/repos", {"repos": [{"path": "~/code/alpha-project"}]}),
    ("post", "/inbox/inbox-001/resolve", {"action": "defer"}),
    ("post", "/nudges/inbox-001/resolve", {"action": "defer"}),
    ("post", "/clarifications/inbox-001", {"action": "defer"}),
]
#: What each route's own commit is: its subject's start and the one file it holds.
COMMITS = {
    "/entities/alpha-project/decay": ("Set decay class ", "entities/alpha-project.md"),
    "/entities/alpha-project/repos": ("Update repo links ", "entities/alpha-project.md"),
    "/inbox/inbox-001/resolve": ("Inbox deferral ", "inbox/inbox-001.md"),
    "/nudges/inbox-001/resolve": ("Inbox deferral ", "inbox/inbox-001.md"),
    "/clarifications/inbox-001": ("Inbox deferral ", "inbox/inbox-001.md"),
}


def _drain(monkeypatch, *, writing: bool):
    monkeypatch.setattr(sleep_cycle, "get_sleep_state",
                        lambda: SimpleNamespace(status="running", drain_run=True, writing=writing))


@pytest.mark.parametrize("method,path,body", ROUTES, ids=[r[1] for r in ROUTES])
def test_a_page_writing_route_refuses_inside_the_write_window(bank, monkeypatch, method, path, body):
    _drain(monkeypatch, writing=True)
    head = _git(bank, "rev-parse", "HEAD")
    resp = getattr(TestClient(main.app), method)(path, json=body)
    assert resp.status_code == 409, resp.text
    assert "Sleep" in resp.json()["detail"]
    assert resp.json()["code"] == "sleep_writing", "the stable code the app keys off (G177 review finding 4)"
    assert _git(bank, "status", "--porcelain") == "", "nothing written"
    assert _git(bank, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("method,path,body", ROUTES, ids=[r[1] for r in ROUTES])
def test_a_page_writing_route_works_between_drain_batches_and_commits_alone(bank, monkeypatch, method, path, body):
    _drain(monkeypatch, writing=False)
    # Someone else's dirty file must not ride this write's commit.
    (bank / "entities" / "bob-example.md").write_text("---\nname: bob-example\ntype: person\n---\n\nx\n")
    head = _git(bank, "rev-parse", "HEAD")
    resp = getattr(TestClient(main.app), method)(path, json=body)
    assert resp.status_code == 200, resp.text
    assert _git(bank, "status", "--porcelain").strip() == "?? entities/bob-example.md"
    subject, rel = COMMITS[path]
    assert _git(bank, "rev-parse", "HEAD~1") == head, "exactly one new commit"
    assert _git(bank, "log", "-1", "--format=%s").startswith(subject)
    assert "Cicada-Author: user" in _git(bank, "log", "-1", "--format=%B").splitlines()
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == [rel]


def test_a_plain_cycle_refuses_for_its_whole_run(bank, monkeypatch):
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    resp = TestClient(main.app).put("/entities/alpha-project/decay", json={"decayClass": "durable"})
    assert resp.status_code == 409


def test_reading_routes_are_never_gated(bank, monkeypatch):
    """`POST /entities/{id}/read` writes a ledger row outside the bank, never a page."""
    _drain(monkeypatch, writing=True)
    resp = TestClient(main.app).post("/entities/alpha-project/read", json={"surface": "app"})
    assert resp.status_code == 200, resp.text


# --- The decay and repo rewrites are one page-lock section, write through commit (review finding 3) ----------------

import threading
import time

from api.services import git_service, page_lock

PAGE_ROUTES = [r for r in ROUTES if r[1].startswith("/entities/")]


@pytest.mark.parametrize("method,path,body", PAGE_ROUTES, ids=[r[1] for r in PAGE_ROUTES])
def test_a_competing_page_writer_waits_until_the_route_has_committed(bank, monkeypatch, method, path, body):
    """The reproduced race: another writer of the same page between the route's write and its commit took the
    person's change into its own commit. Now that writer waits on the page lock until the person's commit exists."""
    page = bank / "entities" / "alpha-project.md"
    real = git_service.commit_touched_sync
    seen: dict = {}

    def competitor():
        with page_lock.page_lock(bank):
            seen["entered"] = True
            with open(page, "a") as fh:
                fh.write("\nagent edit\n")
            git_service.commit_paths_sync(
                bank, "Agent write\n\nentities/alpha-project.md: updated\n\nCicada-Author: claude-code",
                ["entities/alpha-project.md"])

    def commit_at_the_barrier(memory_path, message, paths, **kw):
        seen["held_at_commit"] = page_lock.held(memory_path)
        t = threading.Thread(target=competitor)
        t.start()
        seen["thread"] = t
        time.sleep(0.3)
        seen["competitor_ran_first"] = seen.get("entered", False)
        return real(memory_path, message, paths, **kw)

    monkeypatch.setattr(git_service, "commit_touched_sync", commit_at_the_barrier)
    _drain(monkeypatch, writing=False)
    resp = getattr(TestClient(main.app), method)(path, json=body)
    seen["thread"].join(10)

    assert resp.status_code == 200, resp.text
    assert seen["held_at_commit"] is True
    assert seen["competitor_ran_first"] is False
    authors = _git(bank, "log", "-2", "--format=%(trailers:key=Cicada-Author,valueonly)%x00").split("\0")
    assert [a.strip() for a in authors if a.strip()] == ["claude-code", "user"]
    user_diff = _git(bank, "show", "HEAD~1", "--format=")
    assert "agent edit" not in user_diff
    assert _git(bank, "status", "--porcelain") == ""


@pytest.mark.parametrize("method,path,body", PAGE_ROUTES, ids=[r[1] for r in PAGE_ROUTES])
def test_an_edit_already_on_the_page_is_committed_apart_not_as_the_persons(bank, monkeypatch, method, path, body):
    """The inbox's P1-3 mechanism: an uncommitted edit on the page the person changes is kept apart, unauthored."""
    page = bank / "entities" / "alpha-project.md"
    with open(page, "a") as fh:
        fh.write("\nsomeone else's uncommitted edit\n")
    resp = getattr(TestClient(main.app), method)(path, json=body)
    assert resp.status_code == 200, resp.text
    assert "someone else's uncommitted edit" not in _git(bank, "show", "HEAD", "--format=")
    assert "someone else's uncommitted edit" in _git(bank, "show", "HEAD~1", "--format=")
    assert "Cicada-Author" not in _git(bank, "log", "-1", "--format=%B", "HEAD~1")
    assert _git(bank, "status", "--porcelain") == ""


# --- Admission (G183): a writer admitted before Sleep's flip finishes first; Sleep waits it out ---------------------

from api.services import write_admission


def _admitted_soon(bank) -> None:
    """Wait (a deadline, not a fixed sleep) until the route holds the bank's admission."""
    deadline = time.monotonic() + 10
    while write_admission.holders(bank) == 0:
        assert time.monotonic() < deadline, "the route never took admission"
        time.sleep(0.01)


def _sleep_flips(bank, state, seen) -> threading.Thread:
    """Sleep's order: the flag first, then the wait; records the HEAD Sleep would read from."""
    def flip():
        state["writing"] = True
        seen["drained"] = write_admission.wait_for_writers(bank, give_up_after=10)
        seen["head_at_read"] = _git(bank, "rev-parse", "HEAD")
    t = threading.Thread(target=flip)
    t.start()
    return t


@pytest.mark.parametrize("method,path,body", PAGE_ROUTES, ids=[r[1] for r in PAGE_ROUTES])
def test_a_window_that_opens_while_an_admitted_route_waits_for_the_page_lock_waits_for_its_commit(
        bank, monkeypatch, method, path, body):
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "get_sleep_state",
                        lambda: SimpleNamespace(status="running", drain_run=True, writing=state["writing"]))
    result: dict = {}
    seen: dict = {}
    with page_lock.page_lock(bank):
        t = threading.Thread(target=lambda: result.update(
            resp=getattr(TestClient(main.app), method)(path, json=body)))
        t.start()
        _admitted_soon(bank)              # admitted, now waiting on the page lock
        flip = _sleep_flips(bank, state, seen)
        flip.join(0.3)
        assert flip.is_alive(), "Sleep must not read while an admitted route is mid-transaction"
    t.join(10)
    flip.join(10)
    assert result["resp"].status_code == 200, result["resp"].text
    assert seen["drained"] is True
    assert seen["head_at_read"] == _git(bank, "rev-parse", "HEAD"), "Sleep reads after the route's own commit"
    assert "Cicada-Author: user" in _git(bank, "log", "-1", "--format=%B")
    assert _git(bank, "status", "--porcelain") == ""
    resp = getattr(TestClient(main.app), method)(path, json=body)
    assert resp.status_code == 409, "a writer arriving after the flip is refused"


def test_an_inbox_answer_admitted_before_the_flip_finishes_before_sleep_reads(bank, monkeypatch):
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "get_sleep_state",
                        lambda: SimpleNamespace(status="running", drain_run=True, writing=state["writing"]))
    real = git_service.snapshot_dirty
    seen: dict = {}

    async def snapshot_then_window(memory_path):
        out = await real(memory_path)
        seen["flip"] = _sleep_flips(bank, state, seen)   # the window opens while the answer awaited its snapshot
        return out

    monkeypatch.setattr(git_service, "snapshot_dirty", snapshot_then_window)
    head = _git(bank, "rev-parse", "HEAD")
    resp = TestClient(main.app).post("/inbox/inbox-001/resolve", json={"action": "resolve", "optionKey": "keep"})
    seen["flip"].join(10)
    assert resp.status_code == 200, resp.text
    assert _git(bank, "rev-parse", "HEAD") != head
    assert seen["head_at_read"] == _git(bank, "rev-parse", "HEAD"), "Sleep reads after the answer's commit"
