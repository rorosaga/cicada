"""G141 PJ-3b (T6) — the person's writes from the Projects page (§5.3).

Every write is the person's (`companion_app`, `user_stated`, the resolved
owner as observer — R-PJ18), commits alone as `Cicada-Author: user` over its
own pages, refuses while Sleep runs, and stores no relative word (R-PJ6)."""
import subprocess
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from _demo_scenario import T, d, demo
from api import config, main
from api.routers import projects
from api.services import bank_index, handshake, markdown_parser, sleep_cycle, telemetry
from api.services.claims import parse_claims

SECRET = "sk-" + "Z" * 24
ONGOING = "Bob is connecting to Lab Cluster Example to run the Pick And Place Demo"
CAMERA = "Bob started calibrating the gripper camera"


@pytest.fixture
def client(tmp_path, monkeypatch):
    bank = demo(tmp_path, person=False, followups=False)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(projects, "_now", lambda: datetime(2026, 9, 23, 18, tzinfo=UTC))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    yield TestClient(main.app), bank
    config.get_settings.cache_clear()


def _claims(bank, page):
    return parse_claims(markdown_parser.parse(bank / "entities" / f"{page}.md").body)


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def _thread(bank, page, text):
    return next(c for c in _claims(bank, page)
                if c.predicate == "happened" and c.text == text and c.valid_to is None)


def test_a_new_milestone_is_the_persons_and_commits_alone(client):
    c, bank = client
    r = c.post("/projects/rover-arm-project/milestones", json={"name": "Lab showcase dry run", "target": "2026-10-20"})
    assert r.status_code == 200, r.text
    claim = r.json()["claims"][0]
    assert (claim["origin"], claim["authoredBy"], claim["dateBasis"]) == ("companion_app", "user", "person")
    assert claim["sourceTrust"] == "user_stated" and claim["target"] == "2026-10-20"
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Project update 2026-09-23") and "Cicada-Author: user" in log
    assert "trigger: user/companion_app" in log
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == ["entities/rover-arm-project.md"]


def test_a_due_is_promoted_by_its_first_move_and_renamed_in_place(client):
    c, bank = client
    due = next(x for x in _claims(bank, "rover-arm-project") if x.predicate == "due" and x.object == d(-14))
    r = c.patch(f"/projects/rover-arm-project/milestones/due-{d(-14)}", json={"target": d(8), "on": d(-13)})
    assert r.status_code == 200, r.text
    ms = r.json()["claims"][0]
    assert (ms["predicate"], ms["object"], ms["supersedes"], ms["target"]) == ("milestone", "first-grasp", due.id, d(8))
    after = next(x for x in _claims(bank, "rover-arm-project") if x.id == due.id)
    assert after.valid_to == d(-14) and after.superseded_by == ms["id"]
    r = c.patch("/projects/rover-arm-project/milestones/first-grasp", json={"name": "First grasp (arm v2)"})
    assert r.status_code == 200, r.text
    heads = [x for x in _claims(bank, "rover-arm-project")
             if x.predicate == "milestone" and x.object == "first-grasp" and x.valid_to is None]
    assert [(h.id, h.text) for h in heads] == [(ms["id"], "First grasp (arm v2)")]


def test_the_log_cuts_its_day_out_and_cites_a_companion_note(client):
    c, bank = client
    r = c.post("/projects/pick-and-place-demo/happenings",
               json={"text": "got the guide from Hana Example yesterday", "status": "done"})
    assert r.status_code == 200, r.text
    body = r.json()
    claim = body["claims"][0]
    assert (body["day"], body["dateBasis"]) == (d(-1), "stated")
    assert claim["text"] == "got the guide from Hana Example" and claim["validFrom"] == d(-1)
    assert claim["origin"] == "companion_app" and claim["status"] == "done"
    assert any(p.get("entity") == "hana-example" for p in claim["participants"])
    ep = markdown_parser.parse(bank / "episodes" / f"{body['episodeId']}.md")
    fm = ep.frontmatter
    assert (fm["origin"], fm["processed"], fm["processed_by"]) == ("companion_app", True, "user")
    assert isinstance(fm["turns"], list) and fm["turns"][0]["speaker"] == "user"
    assert "yesterday" in ep.body
    [span] = claim["evidence"]
    assert span["episode"] == body["episodeId"] and span["kind"] == "user" and span["start"] >= 0
    assert body["episodeId"] in _git(bank, "show", "--name-only", "--format=", "HEAD")


def test_the_log_scrubs_both_copies(client):
    c, bank = client
    r = c.post("/projects/pick-and-place-demo/happenings", json={"text": f"set the cluster key to {SECRET}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert SECRET not in body["claims"][0]["text"]
    assert SECRET not in (bank / "episodes" / f"{body['episodeId']}.md").read_text()
    assert SECRET not in (bank / "entities" / "pick-and-place-demo.md").read_text()


def test_two_days_are_refused_and_a_date_chip_is_the_persons(client):
    c, bank = client
    head = _git(bank, "rev-parse", "HEAD")
    eps = sorted(p.name for p in (bank / "episodes").glob("*.md"))
    r = c.post("/projects/pick-and-place-demo/happenings", json={"text": "yesterday I planned it for tomorrow"})
    assert r.status_code == 422 and r.json()["detail"] == "Say one day, or pick it with the date chip"
    assert _git(bank, "rev-parse", "HEAD") == head and sorted(p.name for p in (bank / "episodes").glob("*.md")) == eps
    r = c.post("/projects/pick-and-place-demo/happenings", json={"text": "Tidied the bench", "when": "2026-09-20"})
    assert r.status_code == 200 and (r.json()["day"], r.json()["dateBasis"]) == ("2026-09-20", "person")


def test_a_thread_is_settled_or_restated(client):
    c, bank = client
    ongoing = _thread(bank, "pick-and-place-demo", ONGOING)
    r = c.post(f"/projects/pick-and-place-demo/threads/{ongoing.id}", json={"status": "done"})
    assert r.status_code == 200, r.text
    done = r.json()["claims"][0]
    assert done["status"] == "done" and done["validTo"] == d(0) and done["id"] != ongoing.id
    closed = next(x for x in _claims(bank, "pick-and-place-demo") if x.id == ongoing.id)
    assert closed.valid_to == d(0) and closed.superseded_by == done["id"]

    camera = _thread(bank, "rover-arm-project", CAMERA)
    r = c.post(f"/projects/rover-arm-project/threads/{camera.id}", json={"status": "ongoing"})
    assert r.status_code == 200 and r.json()["action"] == "reinforced", r.text
    open_ = [x for x in _claims(bank, "rover-arm-project")
             if x.predicate == "happened" and x.text == CAMERA and x.valid_to is None]
    assert [(x.id, x.recorded_at) for x in open_] == [(camera.id, "2026-09-23")]


def test_not_right_withdraws_and_records_an_overruled_verdict(client, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    c, bank = client
    s3 = next(x for x in _claims(bank, "rover-arm-project")
              if x.predicate == "happened" and x.text == "The arm is fully assembled")
    r = c.post("/projects/rover-arm-project/withdraw", json={"claimId": s3.id})
    assert r.status_code == 200 and r.json()["action"] == "retracted", r.text
    assert next(x for x in _claims(bank, "rover-arm-project") if x.id == s3.id).superseded_by
    rows = [e for e in telemetry.read_events() if e.kind == "resolution"]
    assert len(rows) == 1
    assert rows[0].refs["kind"] == "happening" and rows[0].refs["verdict"] == "overruled"
    assert rows[0].refs["claim_id"] == s3.id
    ledger = "".join(p.read_text() for p in telemetry.telemetry_dir().glob("*.jsonl"))
    assert "fully assembled" not in ledger
    ms = c.post("/projects/rover-arm-project/milestones", json={"name": "Dry run"}).json()["claimId"]
    r = c.post("/projects/rover-arm-project/withdraw", json={"claimId": ms})
    assert r.status_code == 400 and r.json()["detail"] == "Move or drop a milestone with its own controls"


def test_every_write_waits_while_sleep_runs(client, monkeypatch):
    c, bank = client
    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: SimpleNamespace(status="running"))
    head = _git(bank, "rev-parse", "HEAD")
    before = {p.name: p.read_text() for p in (bank / "entities").glob("*.md")}
    thread = _thread(bank, "pick-and-place-demo", ONGOING).id
    calls = [("post", "/projects/rover-arm-project/milestones", {"name": "X"}),
             ("patch", f"/projects/rover-arm-project/milestones/due-{d(-14)}", {"target": d(8)}),
             ("post", "/projects/pick-and-place-demo/happenings", {"text": "Tidied the bench"}),
             ("post", f"/projects/pick-and-place-demo/threads/{thread}", {"status": "done"}),
             ("post", "/projects/rover-arm-project/withdraw", {"claimId": thread})]
    for method, url, body in calls:
        r = getattr(c, method)(url, json=body)
        assert r.status_code == 409 and r.json()["detail"] == projects.BUSY, url
    assert _git(bank, "rev-parse", "HEAD") == head
    assert {p.name: p.read_text() for p in (bank / "entities").glob("*.md")} == before


def test_unknown_projects_slots_and_claims_are_404(client):
    c, _ = client
    assert c.post("/projects/lab-cluster-example/milestones", json={"name": "X"}).status_code == 404
    assert c.post("/projects/nobody-here/happenings", json={"text": "X"}).status_code == 404
    assert c.patch("/projects/rover-arm-project/milestones/no-such-slot", json={"target": d(8)}).status_code == 404
    assert c.post("/projects/rover-arm-project/threads/clm_nope", json={"status": "done"}).status_code == 404
    assert c.post("/projects/rover-arm-project/withdraw", json={"claimId": "clm_nope"}).status_code == 404
    # A claim on a page outside the tree is never reachable through this project's URL.
    garden = c.post("/projects/garden-sensor-project/happenings", json={"text": "Watered the beds"}).json()["claimId"]
    assert c.post("/projects/rover-arm-project/withdraw", json={"claimId": garden}).status_code == 404
