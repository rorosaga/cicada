"""G150 — a project's backlog over HTTP (R-B7, R-B8, R-B9, R-B18).

Every write is the person's (`Cicada-Author: user`, `user/companion_app`), commits alone over the item's own
file, refuses while Sleep runs, and scrubs. Synthetic only (`_synthetic_bank`)."""
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.routers import backlog as backlog_router
from api.services import bank_index, handshake, sleep_cycle

SECRET = "sk-" + "Z" * 24


@pytest.fixture
def client(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(backlog_router, "_now", lambda: datetime(2026, 9, 24, 18, tzinfo=UTC))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def _add(c, title="Cache the timeline", **body):
    return c.post("/projects/alpha-project/backlog", json={"title": title, **body})


def test_the_person_adds_an_item_and_it_commits_alone_as_theirs(client):
    c, bank = client
    r = _add(c, description=f"The key was {SECRET}", triage="apply")
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["id"], body["status"], body["triage"]) == ("AP1", "open", "apply")
    assert (body["addedBy"], body["addedByKind"], body["addedByLabel"]) == ("user", "user", "You")
    assert SECRET not in body["description"] and body["path"] == "backlog/alpha-project/AP1.md"
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Backlog update 2026-09-24") and "Cicada-Author: user" in log
    assert "backlog/alpha-project/AP1.md: created (source: n/a, trigger: user/companion_app)" in log
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == ["backlog/alpha-project/AP1.md"]


def test_the_list_is_etagged_counts_every_state_and_filters(client):
    c, _bank_dir = client
    _add(c, "One")
    _add(c, "Two")
    c.post("/backlog/alpha-project/AP1/notes", json={"note": "Started.", "status": "doing"})
    r = c.get("/projects/alpha-project/backlog")
    assert r.status_code == 200 and r.headers["etag"]
    body = r.json()
    assert (body["project"], body["projectName"], body["prefix"], body["tzName"]) == (
        "alpha-project", "Alpha Project", "AP", "UTC")
    assert body["counts"] == {"open": 1, "doing": 1, "done": 0, "dropped": 0}
    assert [i["id"] for i in body["items"]] == ["AP1", "AP2"]          # same day: the one with a note is newer
    assert body["items"][0]["lastNoteDay"] == "2026-09-24" and body["items"][0]["noteCount"] == 1
    again = c.get("/projects/alpha-project/backlog", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    assert [i["id"] for i in c.get("/projects/alpha-project/backlog?status=doing").json()["items"]] == ["AP1"]
    assert c.get("/projects/alpha-project/backlog?status=someday").status_code == 400
    _add(c, "Three")
    assert c.get("/projects/alpha-project/backlog", headers={"If-None-Match": r.headers["etag"]}).status_code == 200


def test_an_item_reads_in_full_with_its_signed_notes(client):
    c, _ = client
    _add(c, description="Why it matters.")
    c.post("/backlog/alpha-project/ap1/notes", json={"note": "Found the slow path.", "status": "doing"})
    r = c.get("/backlog/alpha-project/AP1")
    assert r.status_code == 200 and r.headers["etag"]
    item = r.json()
    assert item["description"] == "Why it matters." and item["status"] == "doing"
    note = item["notes"][0]
    assert (note["day"], note["by"], note["byKind"], note["byLabel"]) == ("2026-09-24", "user", "user", "You")
    assert note["text"] == "Found the slow path.\n\nMoved from open to doing." and note["at"] == "2026-09-24T18:00:00Z"
    assert note["authorModel"] is None and note["authorEffort"] is None           # R-B6: C3 lands these
    assert c.get("/backlog/alpha-project/AP9").status_code == 404
    assert c.get("/backlog/bob-example/AP1").status_code == 404                     # not a project


def test_edits_and_refusals_speak_in_status_codes(client):
    c, _ = client
    _add(c)
    r = c.patch("/backlog/alpha-project/AP1", json={"title": "Cache it", "status": "done", "triage": "research"})
    assert r.status_code == 200 and (r.json()["title"], r.json()["status"], r.json()["triage"]) == (
        "Cache it", "done", "research")
    assert r.json()["notes"][-1]["text"] == "Moved from open to done."
    assert c.patch("/backlog/alpha-project/AP1", json={}).status_code == 400
    assert c.post("/backlog/alpha-project/AP1/notes", json={"note": "  "}).status_code == 400
    assert c.post("/projects/no-such-project/backlog", json={"title": "x"}).status_code == 404
    _add(c, "Second idea")
    dup = _add(c, "second IDEA")
    assert dup.status_code == 409 and dup.json()["detail"].startswith("AP2 already holds this")


def test_every_write_waits_while_sleep_runs(client, monkeypatch):
    c, bank = client
    _add(c)
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    head = _git(bank, "rev-parse", "HEAD")
    calls = [("post", "/projects/alpha-project/backlog", {"title": "X"}),
             ("post", "/backlog/alpha-project/AP1/notes", {"note": "Y"}),
             ("patch", "/backlog/alpha-project/AP1", {"status": "done"}),
             ("post", "/projects/alpha-project/backlog/import", {"markdown": "| G1 | **X** | y | 🔲 |"})]
    for method, url, body in calls:
        r = getattr(c, method)(url, json=body)
        assert r.status_code == 409 and r.json()["detail"] == backlog_router.BUSY, url
    assert _git(bank, "rev-parse", "HEAD") == head


def test_the_import_route_files_rows_once(client):
    c, bank = client
    text = ("| ID | Item | Notes | Status |\n|----|------|-------|--------|\n"
            "| G1 | **Cache it** | why | ✅ done |\n| G2 | **Index it** | why | 🔲 |\n")
    first = c.post("/projects/alpha-project/backlog/import", json={"markdown": text})
    assert first.status_code == 200 and first.json() == {"created": ["G1", "G2"], "skipped": [], "failed": []}
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Backlog import 2026-09-24") and "trigger: user/backlog_import" in log
    head = _git(bank, "rev-parse", "HEAD")
    second = c.post("/projects/alpha-project/backlog/import", json={"markdown": text})
    assert second.json() == {"created": [], "skipped": ["G1", "G2"], "failed": []}
    assert _git(bank, "rev-parse", "HEAD") == head
    assert c.post("/projects/alpha-project/backlog/import", json={"markdown": text, "prefix": "g1"}).status_code == 400
