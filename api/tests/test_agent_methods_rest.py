"""G166 — `GET|PUT /agent-methods` and the "Add to your graph" door. The wire is pinned by
`fixtures/agent_methods.json` (the Swift test decodes the same file). A choice saves to a machine
file and always succeeds once valid; the page write beside it is best-effort."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from _synthetic_bank import _bank
from api import config, main
from api.services import agent_methods, demo_guard, markdown_parser, sleep_cycle

FIXTURE = Path(__file__).parent / "fixtures" / "agent_methods.json"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield TestClient(main.app), memory
    config.get_settings.cache_clear()


def test_get_matches_the_pinned_fixture(api):
    client, _ = api
    body = client.get("/agent-methods").json()
    if os.environ.get("CICADA_UPDATE_FIXTURES") == "1":
        FIXTURE.write_text(json.dumps(body, indent=1) + "\n")
    assert body == json.loads(FIXTURE.read_text())
    reading, watching = body["jobs"]
    assert (body["shape"], reading["job"], reading["question"], reading["chosen"]) == ("agent-methods-1", "reading", "How your agent reads", "auto")
    assert [o["id"] for o in reading["options"]] == ["auto", "own", "browser-harness", "macos-harness"]
    assert (watching["job"], watching["question"], watching["chosen"]) == ("watching", "How your agent watches", "auto")
    assert [o["id"] for o in watching["options"]] == ["auto", "own", "watch", "browser-harness", "macos-harness"]
    assert all(o.get("page") is None for j in body["jobs"] for o in j["options"] if o["kind"] == "skill")


def test_no_etag_and_no_store_domain(api):
    client, _ = api
    r = client.get("/agent-methods")
    assert "etag" not in {k.lower() for k in r.headers}


def test_put_round_trip_and_422_sentences(api):
    client, memory = api
    r = client.put("/agent-methods", json={"job": "reading", "choice": "own"})
    assert r.status_code == 200 and r.json()["chosen"] == "own" and r.json()["write"] == {"page": "none"}
    assert client.get("/agent-methods").json()["jobs"][0]["chosen"] == "own"
    assert not list((memory / "entities").glob("*harness*")), "the agent's own tools file no page"
    bad = client.put("/agent-methods", json={"job": "reading", "choice": "watch"})
    assert bad.status_code == 422 and bad.json()["detail"] == "That isn't one of the choices for how your agent reads."
    nope = client.put("/agent-methods", json={"job": "cooking", "choice": "auto"})
    assert nope.status_code == 422 and "isn't" in nope.json()["detail"]
    assert client.put("/agent-methods", json={"job": "reading", "choice": "auto"}).json()["chosen"] == "auto"


def test_selecting_an_uninstalled_skill_is_saved_and_files_its_page(api):
    client, memory = api
    r = client.put("/agent-methods", json={"job": "reading", "choice": "browser-harness"})
    body = r.json()
    assert r.status_code == 200 and body["chosen"] == "browser-harness" and body["write"] == {"page": "created"}
    option = next(o for o in body["options"] if o["id"] == "browser-harness")
    assert option["state"]["claude-code"] == "not_installed", "saved anyway: the agent's half is to say so and stop"
    assert option["page"] == {"id": "browser-harness", "state": "exists"}
    fm = markdown_parser.parse(memory / "entities" / "browser-harness.md").frontmatter
    assert fm["type"] == "skill" and "agent-skill" in fm["tags"]
    again = client.put("/agent-methods", json={"job": "reading", "choice": "browser-harness"}).json()
    assert again["write"] == {"page": "exists"}


def test_put_while_sleep_runs_saves_the_choice_and_reports_page_busy(api, monkeypatch):
    client, memory = api
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    r = client.put("/agent-methods", json={"job": "reading", "choice": "macos-harness"})
    assert r.status_code == 200 and r.json()["write"] == {"page": "busy"} and r.json()["chosen"] == "macos-harness"
    assert agent_methods.choice("reading") == "macos-harness"
    assert not (memory / "entities" / "macos-harness.md").exists()
    door = client.post("/agent-methods/skills/macos-harness/page")
    assert door.status_code == 409 and "Sleep" in door.json()["detail"]


def test_put_in_a_demo_bank_saves_and_reports_demo(api):
    client, memory = api
    demo_guard.write_manifest(memory)
    r = client.put("/agent-methods", json={"job": "reading", "choice": "browser-harness"})
    assert r.status_code == 200 and r.json()["write"] == {"page": "demo"} and agent_methods.choice("reading") == "browser-harness"
    assert not (memory / "entities" / "browser-harness.md").exists()
    door = client.post("/agent-methods/skills/browser-harness/page")
    assert door.status_code == 409 and door.json()["detail"] == demo_guard.REFUSAL


def test_page_door_404_409s_and_add_to_your_graph(api):
    client, memory = api
    assert client.post("/agent-methods/skills/pdf/page").status_code == 404, "a skill with no role"
    assert client.post("/agent-methods/skills/nonsense/page").status_code == 404
    ok = client.post("/agent-methods/skills/macos-harness/page")
    assert ok.status_code == 200 and ok.json() == {"id": "macos-harness", "state": "created"}
    assert client.post("/agent-methods/skills/macos-harness/page").json()["state"] == "exists"
    assert agent_methods.choice("reading") == "auto", "adding a page is not a choice"
