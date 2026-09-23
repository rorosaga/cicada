"""Track I T2b — imports that write more than 10 episodes stage in the
background behind a 202 and a job counter (design §9.2, R-IA12)."""
from __future__ import annotations

import json
import threading

from _intake_fixtures import claude_conversations
from api import config
from api.routers import conversations as conv
from api.services import bank_registry, intake_jobs, markdown_parser


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(tmp_path, git_init=False)
    intake_jobs.reset()
    return TestClient(main.app)


def _import(client, convs):
    return client.post("/intake/import", files={"file": ("conversations.json", json.dumps(convs).encode(), "application/json")})


def test_a_large_import_answers_202_and_its_job_reaches_done(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = _import(client, claude_conversations(50))
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["total"] == 50 and r.json()["episodesStaged"] == 0
    status = client.get(f"/intake/jobs/{job['id']}").json()
    assert status == {"id": job["id"], "total": 50, "staged": 50, "created": 50, "updated": 0,
                      "skipped": 0, "done": True, "error": None}
    ids = {markdown_parser.parse(p).frontmatter["id"] for p in (tmp_path / "episodes").glob("*.md")}
    assert len(ids) == 50, "batches must mint unique ids (G114 R1)"
    config.get_settings.cache_clear()


def test_a_small_import_stays_synchronous(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    r = _import(client, claude_conversations(3))
    assert r.status_code == 200 and r.json()["job"] is None and r.json()["episodesStaged"] == 3
    config.get_settings.cache_clear()


def test_a_reimport_that_changes_little_stays_synchronous(tmp_path, monkeypatch):
    """The threshold is what WOULD be written (plan), not the file's size."""
    client = _client(tmp_path, monkeypatch)
    assert _import(client, claude_conversations(50)).status_code == 202
    again = _import(client, claude_conversations(50, grown=True))
    assert again.status_code == 200 and (again.json()["episodesUpdated"], again.json()["duplicatesSkipped"]) == (1, 49)
    config.get_settings.cache_clear()


def test_a_job_carries_only_what_will_be_written(tmp_path, monkeypatch):
    """The job's total is the preview's "Import N" (new + grew), never the
    file's size, so "Bringing in 180 of 379" cannot count past the button."""
    client = _client(tmp_path, monkeypatch)
    assert _import(client, claude_conversations(20)).status_code == 202
    r = _import(client, claude_conversations(50))
    assert r.status_code == 202, r.text
    assert r.json()["job"]["total"] == 30 and r.json()["duplicatesSkipped"] == 20
    status = client.get(f"/intake/jobs/{r.json()['job']['id']}").json()
    assert (status["total"], status["staged"], status["created"], status["skipped"]) == (30, 30, 30, 20)
    config.get_settings.cache_clear()


def test_an_unknown_job_is_404(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/intake/jobs/nope").status_code == 404
    config.get_settings.cache_clear()


def test_a_failing_job_records_its_error_and_still_finishes(tmp_path):
    intake_jobs.reset()
    job = intake_jobs.start(3)

    def boom(_episodes, _dir):
        raise OSError("disk full")

    intake_jobs.run(job.id, [{}, {}, {}], tmp_path / "episodes", boom)
    done = intake_jobs.get(job.id)
    assert done.done is True and done.error == "OSError: disk full" and done.staged == 0


def test_two_jobs_into_one_bank_never_collide(tmp_path):
    """R-IA12: staging is serialised per process; without it both jobs seed ids
    from the same max suffix and `markdown_parser.write` overwrites."""
    intake_jobs.reset()
    ep_dir = tmp_path / "episodes"
    a = conv.parse_anthropic_conversations(claude_conversations(30))
    b = conv.parse_anthropic_conversations(claude_conversations(30))
    for ep in b:
        ep["source_id"] = "other-" + ep["source_id"]
    jobs = [intake_jobs.start(30), intake_jobs.start(30)]
    threads = [threading.Thread(target=intake_jobs.run, args=(j.id, eps, ep_dir, conv._stage_episodes), kwargs={"batch": 7})
               for j, eps in zip(jobs, (a, b))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(list(ep_dir.glob("*.md"))) == 60
