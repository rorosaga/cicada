"""G183(d) — a write the app made in one bank never lands in another (`bank_binding`).

The app names the bank an operation started in (`X-Cicada-Bank`); a mutating request whose bank is not the active one
is refused before its handler runs. Without the header every route behaves exactly as before."""
from __future__ import annotations

import subprocess

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_binding, markdown_parser


def _git(repo, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path, monkeypatch):
    """The legacy `default` bank (no registry), committed clean, with one page and one inbox question."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "inbox").mkdir()
    (memory / "episodes").mkdir()
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
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    yield memory
    config.get_settings.cache_clear()


def _snapshot(memory):
    files = sorted(p.relative_to(memory).as_posix() for p in memory.rglob("*") if p.is_file() and ".git" not in p.parts)
    return files, {f: (memory / f).read_bytes() for f in files}, _git(memory, "rev-parse", "HEAD")


#: A representative set of the app's bank-scoped writes: an answer, a page rewrite, a picture, a per-bank setting,
#: a local source batch, and the owner page.
WRITES = [
    ("post", "/inbox/inbox-001/resolve", {"json": {"action": "defer"}}),
    ("put", "/entities/alpha-project/decay", {"json": {"decayClass": "durable"}}),
    ("post", "/entities/alpha-project/picture", {"files": {"file": ("a.png", b"\x89PNG\r\n\x1a\n", "image/png")}}),
    ("put", "/sleep/schedule", {"json": {"enabled": True, "time": "03:00"}}),
    ("post", "/sources/folders/fld-1/sync", {"json": {"files": [], "deleted": []}}),
    ("put", "/settings/owner", {"json": {"name": "bob-example"}}),
    ("put", "/memory/decay-tuning", {"json": {"project": 1.5}}),
]


@pytest.mark.parametrize("method,path,kwargs", WRITES, ids=[w[1] for w in WRITES])
def test_a_write_named_for_another_bank_is_refused_and_writes_nothing(bank, method, path, kwargs):
    before = _snapshot(bank)
    resp = getattr(TestClient(main.app), method)(path, headers={bank_binding.HEADER: "other-bank"}, **kwargs)
    assert resp.status_code == 409, resp.text
    assert resp.json() == {"code": "bank_mismatch", "detail": bank_binding.DETAIL}
    assert _snapshot(bank) == before, "the handler never ran"


def test_a_write_named_for_the_active_bank_goes_through(bank):
    resp = TestClient(main.app).put("/entities/alpha-project/decay", json={"decayClass": "durable"},
                                    headers={bank_binding.HEADER: "default"})
    assert resp.status_code == 200, resp.text


def test_the_bank_name_is_percent_decoded(bank):
    resp = TestClient(main.app).post("/inbox/inbox-001/resolve", json={"action": "defer"},
                                     headers={bank_binding.HEADER: "defa%75lt"})
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("method,path,kwargs", WRITES[:2], ids=[w[1] for w in WRITES[:2]])
def test_without_the_header_every_route_is_unchanged(bank, method, path, kwargs):
    resp = getattr(TestClient(main.app), method)(path, **kwargs)
    assert resp.status_code == 200, resp.text


def test_reads_are_never_checked(bank):
    resp = TestClient(main.app).get("/inbox", headers={bank_binding.HEADER: "other-bank"})
    assert resp.status_code == 200


def test_the_routes_that_change_the_bank_are_exempt(bank):
    c = TestClient(main.app)
    stale = {bank_binding.HEADER: "other-bank"}
    assert c.post("/banks", json={"name": "beta"}, headers=stale).status_code == 200
    assert c.post("/banks/beta/activate", headers=stale).status_code == 200
    assert c.post("/banks/default/activate", headers=stale).status_code == 200
    # The bank moved: the app's next write names the bank it now shows.
    assert c.put("/entities/alpha-project/decay", json={"decayClass": "volatile"},
                 headers={bank_binding.HEADER: "beta"}).json()["code"] == "bank_mismatch"


def test_every_exempt_route_exists():
    """The exemptions are route templates; a renamed route must not silently fall out of them."""
    templates = {(m, r.path) for r in main.app.routes for m in getattr(r, "methods", ()) or ()}
    assert bank_binding.EXEMPT <= templates
