"""G141 PJ-1 HTTP: ETags carry no today and no viewer zone (R-PJ7)."""
import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from _demo_scenario import T, d, day_one
from api import config, main
from api.services import bank_index, handshake, markdown_parser, sync_service, telemetry


def _touch(path):
    """Rewrite a page and move its mtime a clear 10 s on, so a same-tick write
    can never look unchanged to `dir_mtime` (max mtime over the .md files)."""
    parsed = markdown_parser.parse(path)
    parsed.frontmatter["touched"] = True
    markdown_parser.write(path, parsed.frontmatter, parsed.body)
    t = path.stat().st_mtime + 10
    os.utime(path, (t, t))
    bank_index.invalidate()


@pytest.fixture
def client(tmp_path, monkeypatch):
    bank = day_one(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def test_the_list_and_the_detail_answer(client):
    c, _ = client
    r = c.get("/projects")
    assert r.status_code == 200 and r.json()["tzName"] == "UTC"
    ids = [p["id"] for p in r.json()["projects"]]
    assert {"rover-arm-project", "pick-and-place-demo", "garden-sensor-project"} <= set(ids)
    t = c.get("/projects/rover-arm-project/timeline")
    assert t.status_code == 200 and t.json()["project"]["children"] == ["pick-and-place-demo"]
    for bad in ("nobody-here", "lab-cluster-example"):
        assert c.get(f"/projects/{bad}/timeline").status_code == 404


def test_since_filters_items_not_milestones(client):
    c, _ = client
    body = c.get(f"/projects/rover-arm-project/timeline?since={d(-2)}").json()
    assert all(i["day"] is None or i["day"] >= d(-2) for i in body["items"])
    assert len(body["milestones"]) == 4
    assert c.get("/projects/rover-arm-project/timeline?since=not-a-day").status_code == 400


def test_a_repeat_is_a_304_and_writes_move_both_etags(client):
    c, bank = client
    for url in ("/projects", "/projects/rover-arm-project/timeline"):
        first = c.get(url)
        assert c.get(url, headers={"If-None-Match": first.headers["ETag"]}).status_code == 304
        for touch in ("entities/garden-sensor-project.md", "inbox/inbox-001.md"):
            _touch(bank / touch)
            assert c.get(url).headers["ETag"] != first.headers["ETag"], (url, touch)
            first = c.get(url)


def test_a_new_episode_and_a_zone_change_move_the_etag(client, monkeypatch):
    c, bank = client
    before = c.get("/projects").headers["ETag"]
    markdown_parser.write(bank / "episodes" / f"ep_{d(0)}_099.md",
                          {"id": f"ep_{d(0)}_099", "timestamp": f"{d(0)}T20:00:00+00:00", "processed": False},
                          "user: a new note")
    bank_index.invalidate()
    after = c.get("/projects").headers["ETag"]
    assert after != before
    monkeypatch.setattr(handshake, "local_timezone", lambda: "America/New_York")
    assert c.get("/projects").headers["ETag"] != after


def test_the_etag_is_identical_across_a_pinned_midnight(client, monkeypatch):
    c, _ = client
    before = {u: c.get(u).headers["ETag"] for u in ("/projects", "/projects/rover-arm-project/timeline")}

    class Tomorrow(date):
        @classmethod
        def today(cls):
            return T + timedelta(days=1)

    monkeypatch.setattr(sync_service, "date", Tomorrow)
    assert {u: c.get(u).headers["ETag"] for u in before} == before   # no deferral pending on the demo


def test_opening_a_project_records_an_ids_only_read(client, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")        # conftest turns the ledger off by default
    c, _ = client
    c.get("/projects/rover-arm-project/timeline")
    reads = [e for e in telemetry.read_events() if e.kind == "read"]
    assert reads and reads[-1].refs == {"entity_id": "rover-arm-project", "surface": "project"}
    ledger = "".join(p.read_text() for p in telemetry.telemetry_dir().glob("*.jsonl"))
    assert "Hana" not in ledger and "cluster" not in ledger.lower()


@pytest.mark.parametrize("state", ["building", "stale"])
def test_a_body_built_without_a_ready_index_carries_no_etag(client, monkeypatch, state):
    """G141 final review: the ETag covers bank content, but the reverse-claims
    layer reads the FTS index. A body built while it is `building` (a capped
    raw scan, `partial`) or `stale` must never be revalidated into a 304."""
    from api.routers import projects as projects_router

    c, _ = client
    monkeypatch.setattr(projects_router, "_index_state", lambda mp: state)
    for url in ("/projects", "/projects/rover-arm-project/timeline"):
        r = c.get(url)
        assert r.status_code == 200 and "etag" not in r.headers, url


def test_a_partial_body_carries_no_etag(client, monkeypatch):
    from api.routers import projects as projects_router
    from api.services import project_timeline

    c, _ = client
    monkeypatch.setattr(projects_router, "_index_state", lambda mp: "ready")
    real = project_timeline.list_projects

    def partial(*a, **kw):
        out = real(*a, **kw)
        out.partial = True
        return out

    monkeypatch.setattr(project_timeline, "list_projects", partial)
    r = c.get("/projects")
    assert r.status_code == 200 and r.json()["partial"] is True and "etag" not in r.headers
