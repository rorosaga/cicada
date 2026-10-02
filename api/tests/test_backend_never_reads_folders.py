"""The backend never touches a folder the person declared (the ``~/Library`` rail).

Under launchd the backend's interpreter is what macOS names, so any ``stat``,
listing or ``git -C`` in a declared folder made the Mac ask whether
"python3.12" may read it. The app does those reads (``LocationLister``,
``GitRunner``) and the backend only parses what it is sent.

Every route and path that once reached such a folder runs here with the
process rigged: ``os.stat``/``os.lstat`` (under ``Path.exists``, ``is_dir``,
``resolve`` and ``os.path.*``), ``os.scandir``, ``os.listdir`` and
``subprocess.Popen`` (under ``subprocess.run``) record any call that names a
declared folder — as an absolute path or ``~``-rooted — and the test fails if
one did. The declared folders are real git checkouts, so a probe would
succeed silently without the rig. Plus: nothing under ``api/`` but
``repo_context`` itself names the git-running function; the MCP tool is its
only caller.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.routers import conversations as conv
from api.services import bank_index, markdown_parser, sleep_cycle

UUID_A = "0f8f1c2a-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _checkout(path: Path) -> None:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "README.md").write_text("x\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "seed")


class _Rig:
    """Records every filesystem or process call that names a forbidden folder."""

    def __init__(self, forbidden: list[str]):
        self.forbidden = forbidden
        self.hits: list[str] = []

    def check(self, what: str, *values) -> None:
        for value in values:
            if isinstance(value, (list, tuple)):
                self.check(what, *value)
                continue
            try:
                text = os.fsdecode(value) if isinstance(value, (str, bytes, os.PathLike)) else None
            except TypeError:
                text = None
            if text and ("~/src/alpha-project" in text or any(text.startswith(f) for f in self.forbidden)):
                self.hits.append(f"{what}: {text}")


@pytest.fixture
def rigged(tmp_path, monkeypatch):
    fake_home = tmp_path / "fakehome"
    declared_abs = tmp_path / "declared" / "beta-project"
    _checkout(fake_home / "src" / "alpha-project")
    _checkout(declared_abs)
    monkeypatch.setenv("HOME", str(fake_home))

    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    markdown_parser.write(memory / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.9,
                           "last_referenced": "2026-09-20",
                           "repos": [{"path": "~/src/alpha-project"}, {"path": str(declared_abs)}]},
                          "## Summary\nAlpha.\n")
    markdown_parser.write(memory / "entities" / "alpha-folder.md",
                          {"name": "Alpha Folder", "type": "directory", "status": "active", "confidence": 0.9,
                           "path": "~/src/alpha-project"}, "## Summary\nA folder.\n")
    markdown_parser.write(memory / "entities" / "beta-place.md",
                          {"name": "Beta Place", "type": "location", "status": "active", "confidence": 0.9,
                           "path": str(declared_abs)}, "## Summary\nA place.\n")
    (memory / "episodes" / "ep_2026-09-20_001.md").write_text(
        "\n".join(["---", "id: ep_2026-09-20_001", "timestamp: '2026-09-20T10:00:00Z'", "title: A chat",
                   "processed: true", f"session_id: {UUID_A}", "harness: claude-code",
                   f"project_dir: {declared_abs}", "---", "", "body"]), encoding="utf-8")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "t@example.com")
    _git(memory, "config", "user.name", "t")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")

    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setattr(conv, "transcript_exists", lambda pd, sid, root=None: True)
    config.get_settings.cache_clear()
    bank_index.invalidate()

    rig = _Rig([str(fake_home / "src"), str(declared_abs), str(declared_abs.resolve())])
    real_stat, real_lstat, real_scandir, real_listdir = os.stat, os.lstat, os.scandir, os.listdir
    real_popen_init = subprocess.Popen.__init__

    def stat(path, *a, **k):
        rig.check("stat", path)
        return real_stat(path, *a, **k)

    def lstat(path, *a, **k):
        rig.check("lstat", path)
        return real_lstat(path, *a, **k)

    def scandir(path=".", *a, **k):
        rig.check("scandir", path)
        return real_scandir(path, *a, **k)

    def listdir(path=".", *a, **k):
        rig.check("listdir", path)
        return real_listdir(path, *a, **k)

    def popen_init(self, args, *a, **k):
        rig.check("spawn", args, k.get("cwd"))
        return real_popen_init(self, args, *a, **k)

    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os, "lstat", lstat)
    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "listdir", listdir)
    monkeypatch.setattr(subprocess.Popen, "__init__", popen_init)
    yield SimpleNamespace(memory=memory, rig=rig, declared_abs=declared_abs)
    config.get_settings.cache_clear()
    bank_index.invalidate()


def test_the_rig_catches_a_probe(rigged):
    """Without this the other tests could pass vacuously."""
    Path("~/src/alpha-project").expanduser().is_dir()
    subprocess.run(["git", "-C", str(rigged.declared_abs), "status"], capture_output=True)
    assert len(rigged.rig.hits) >= 2


def test_repos_location_resume_and_state_never_touch_a_declared_folder(rigged):
    observed = {"repos": [
        {"path": "~/src/alpha-project", "outputs": {"inside": {"rc": 0, "stdout": "true\n"},
                                                    "branch": {"rc": 0, "stdout": "main\n"}}},
        {"path": str(rigged.declared_abs), "outputs": {"inside": {
            "rc": 128, "stdout": "", "stderr": "fatal: cannot change to 'x': Operation not permitted\n"}}},
    ]}
    with TestClient(main.app) as client:
        got = client.get("/entities/alpha-project/repos")
        assert got.status_code == 200 and [r["path"] for r in got.json()["repos"]] == [
            "~/src/alpha-project", str(rigged.declared_abs)]
        posted = client.post("/entities/alpha-project/repos/observed", json=observed)
        assert posted.status_code == 200, posted.text
        assert [r["status"] for r in posted.json()["repos"]] == ["ok", "denied"]
        assert client.patch("/entities/alpha-project/repos",
                             json={"repos": [{"path": "~/src/alpha-project"}]}).status_code == 200
        assert client.get("/entities/alpha-folder/location").json()["path"] == "~/src/alpha-project"
        assert client.get("/entities/beta-place/location").json()["path"] == str(rigged.declared_abs)
        resume = client.post(f"/conversations/{UUID_A}/resume")
        assert resume.status_code == 200 and resume.json()["cwd"] == str(rigged.declared_abs)
        state = client.get("/state", params={"refresh": "true"})
        assert state.status_code == 200
        assert state.json()["projects"][0]["repos"][0]["branch"] == "main"
    assert rigged.rig.hits == []


def test_sleeps_state_refresh_never_touches_a_declared_folder(rigged):
    settings = SimpleNamespace(memory_path=rigged.memory, litellm_model="gpt-5.4-mini")
    asyncio.run(sleep_cycle._refresh_state_safely(rigged.memory, settings))
    assert (rigged.memory / "_state.md").exists()
    assert rigged.rig.hits == []


def test_only_the_mcp_tool_calls_the_git_runner():
    """`resolve_repo_context` / `run_repo_commands` run git in a declared folder.
    The MCP tool may (it runs in the agent harness's process); nothing the
    backend serves may."""
    pattern = re.compile(r"\b(resolve_repo_context|run_repo_commands|git_repo_snapshot)\b")
    offenders = []
    for root in ("api", "mcp"):
        for path in (REPO_ROOT / root).rglob("*.py"):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel.startswith(("api/tests/", "api/.venv/")) or "/.venv/" in rel:
                continue
            if rel in {"api/services/repo_context.py", "mcp/server.py"}:
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                offenders.append(rel)
    assert offenders == []
    assert pattern.search((REPO_ROOT / "mcp" / "server.py").read_text(encoding="utf-8"))
