"""G124 — the GitHub-style calendar per Cicada-Author and the most-written
entities. Hermetic: throwaway git repos with hand-crafted trailers; the real
memory/ is never touched."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import consumption_stats, git_service


def run(coro):
    return asyncio.run(coro)


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    import os
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True,
                          text=True, env={**os.environ, **(env or {})}).stdout


def _commit(repo: Path, rel: str, text: str, *, author: str | None, when: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", "--", rel)
    message = git_service.build_commit_message(
        f"write {rel}", [f"{rel}: updated (source: ep_1, trigger: sleep/extraction)"],
        authors=[author] if author else None)
    _git(repo, "commit", "-q", "-m", message,
         env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "memory"
    (r / "entities").mkdir(parents=True)
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "test@cicada.local")
    _git(r, "config", "user.name", "Cicada Test")
    _commit(r, "entities/alpha-project.md", "v1", author="gpt-5.4-mini", when="2026-08-01T10:00:00+00:00")
    _commit(r, "entities/alpha-project.md", "v2", author="gpt-5.4-mini", when="2026-08-01T23:30:00-07:00")  # = 08-02 UTC
    _commit(r, "entities/bob-example.md", "v1", author="user", when="2026-08-03T10:00:00+00:00")
    _commit(r, "entities/alpha-project.md", "v3", author="user", when="2026-08-03T11:00:00+00:00")
    _commit(r, "entities/gamma-tool.md", "v1", author=None, when="2026-08-04T10:00:00+00:00")  # untrailered
    return r


def test_memory_write_days_by_author_buckets_by_utc_day(repo):
    days = run(consumption_stats.memory_write_days_by_author(repo, "gpt-5.4-mini"))
    assert days == {"2026-08-01": 1, "2026-08-02": 1}, "the -07:00 commit is the next UTC day"
    assert run(consumption_stats.memory_write_days_by_author(repo, "user")) == {"2026-08-03": 2}
    assert run(consumption_stats.memory_write_days_by_author(repo, "unknown")) == {"2026-08-04": 1}
    assert run(consumption_stats.memory_write_days_by_author(repo, "nobody")) == {}


def test_memory_write_days_total_is_unchanged_by_the_refactor(repo):
    total = run(consumption_stats.memory_write_days(repo))
    assert total == {"2026-08-01": 1, "2026-08-02": 1, "2026-08-03": 2}, "untrailered commits are not memory writes"


def test_contributor_calendar_levels_come_from_writes_alone(repo):
    days = run(consumption_stats.contributor_calendar(
        repo, author="user", weeks=1, today=date(2026, 8, 5)))
    assert [d["date"] for d in days] == [f"2026-07-{n}" for n in (30, 31)] + [f"2026-08-0{n}" for n in range(1, 6)]
    by_date = {d["date"]: d for d in days}
    assert by_date["2026-08-03"]["memory_writes"] == 2 and by_date["2026-08-03"]["level"] == 4
    assert by_date["2026-08-01"]["memory_writes"] == 0 and by_date["2026-08-01"]["level"] == 0
    assert all(d["tokens"] == 0 and d["cost_usd"] == 0.0 for d in days), "R14: writes only"


def test_top_written_entities_counts_commits_per_page(repo):
    rows, scanned = run(git_service.top_written_entities(repo, limit=10))
    assert scanned == 5
    assert rows[0] == {"entity_id": "alpha-project", "commits": 3, "last_written": "2026-08-03"}
    # ties on commit count (bob 08-03, gamma 08-04) show the newer page first
    assert [r["entity_id"] for r in rows] == ["alpha-project", "gamma-tool", "bob-example"]
    assert run(git_service.top_written_entities(repo, limit=1))[0] == rows[:1]


def test_top_written_entities_on_a_non_git_dir_is_empty(tmp_path):
    assert run(git_service.top_written_entities(tmp_path, limit=5)) == ([], 0)


@pytest.fixture
def client(repo, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(repo))
    monkeypatch.setenv("CICADA_HOME", str(repo.parent / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    config.get_settings.cache_clear()
    yield TestClient(main.app)
    config.get_settings.cache_clear()


def test_calendar_route_is_per_author_and_etagged(client):
    r = client.get("/contributors/calendar?author=user&weeks=2")
    assert r.status_code == 200
    body = r.json()
    assert body["author"] == "user" and body["weeks"] == 2 and len(body["days"]) == 14
    assert {"date", "memoryWrites", "level"} <= set(body["days"][0])
    etag = r.headers["etag"]
    assert client.get("/contributors/calendar?author=user&weeks=2", headers={"If-None-Match": etag}).status_code == 304
    assert client.get("/contributors/calendar?author=gpt-5.4-mini&weeks=2").headers["etag"] != etag
    assert client.get("/contributors/calendar?weeks=2").status_code == 422, "author is required"


def test_top_entities_route_merges_git_and_ledger(client):
    from api.services import telemetry as tm
    tm.record_read("bob-example", surface="app", bank="memory")
    tm.record_read("bob-example", surface="mcp", bank="memory")
    tm.record_read("alpha-project", surface="mcp-recall", bank="memory")
    body = client.get("/contributors/top-entities?limit=5&range=all").json()
    assert body["written"][0]["entityId"] == "alpha-project" and body["written"][0]["commits"] == 3
    assert body["commitsScanned"] == 5 and body["range"] == "all"
    assert [(r["entityId"], r["reads"]) for r in body["read"]] == [("bob-example", 2), ("alpha-project", 1)]
    assert body["read"][0]["lastRead"]
