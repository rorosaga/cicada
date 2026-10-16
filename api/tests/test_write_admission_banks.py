"""G183 fix round 2, blocker 1 — an admitted transaction is admitted, written and committed in ONE bank: the request's
pinned bank (G177 `bank_binding`). A switch mid-transaction changes neither where it writes nor what Sleep waits for;
a remote call names its bank to the backend, which refuses rather than answer in another bank.
"""
from __future__ import annotations

import asyncio
import io
import subprocess
import threading
import urllib.error

import httpx
import pytest

from api import config, main
from api.remote import catalog
from api.remote.runtime import RemoteRuntime
from api.routers import entities
from api.services import bank_binding, bank_registry, markdown_parser, mcp_tools, sleep_cycle, write_admission


def _git(repo, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


@pytest.fixture
def two_banks(tmp_path, monkeypatch):
    """Synthetic `default` and `beta` banks, each with a committed `bob-example` page and a decay question on it."""
    root = tmp_path / "bank-root"
    root.mkdir()
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_registry.scaffold_bank(root)
    bank_registry.create_bank(root, "beta", seed_owner=False)
    for p in (root, bank_registry.bank_dir(root, "beta")):
        markdown_parser.write(p / "entities" / "bob-example.md",
                              {"name": "bob-example", "type": "person", "status": "active"}, "synthetic")
        (p / "inbox").mkdir(exist_ok=True)
        markdown_parser.write(p / "inbox" / "inbox-001.md",
                              {"kind": "decay", "status": "pending", "entity_id": "bob-example",
                               "entity_name": "bob-example", "title": "Still tracking bob-example?",
                               "created_date": "2026-10-01"}, "context")
        _git(p, "add", "entities/bob-example.md", "inbox/inbox-001.md")
        _git(p, "-c", "user.name=Cicada Test", "-c", "user.email=test@cicada.local", "commit", "-q", "-m", "seed")
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    yield root
    config.get_settings.cache_clear()


def _state(p):
    """A bank's own pages and questions, and its HEAD (the registry beside them changes with a switch)."""
    files = sorted(x.relative_to(p).as_posix() for d in ("entities", "inbox") for x in (p / d).rglob("*")
                   if x.is_file())
    return {f: (p / f).read_bytes() for f in files}, _git(p, "rev-parse", "HEAD")


def test_admit_in_a_switch_to_b_mid_transaction_the_write_and_its_commit_land_in_a(two_banks, monkeypatch):
    root = two_banks
    beta = bank_registry.bank_dir(root, "beta")
    beta_before = _state(beta)
    head_a = _git(root, "rev-parse", "HEAD")
    started, release = threading.Event(), threading.Event()
    real = entities._rewrite_page_and_commit
    wrote_in: list = []

    def rewrite(memory_path, *a, **k):
        wrote_in.append(memory_path)
        started.set()
        assert release.wait(10)
        return real(memory_path, *a, **k)

    monkeypatch.setattr(entities, "_rewrite_page_and_commit", rewrite)
    waits: dict = {}

    async def run():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            request = asyncio.create_task(c.put("/entities/bob-example/decay", json={"decayClass": "durable"},
                                                headers={bank_binding.HEADER: "default"}))
            assert await asyncio.to_thread(started.wait, 10), "admitted in A and writing"
            bank_registry.activate_bank(root, "beta")              # the switch, mid-transaction
            waits["b"] = await asyncio.to_thread(write_admission.wait_for_writers, beta, give_up_after=2)
            waits["a"] = await asyncio.to_thread(write_admission.wait_for_writers, root, log_after=10,
                                                 give_up_after=0.2)
            release.set()
            return await request

    response = asyncio.run(run())
    assert response.status_code == 200, response.text
    assert waits == {"b": True, "a": False}, "Sleep on B opens at once; Sleep on A waits for the live write"
    assert [str(p) for p in wrote_in] == [str(root)], "the write ran in A"
    assert markdown_parser.parse(root / "entities" / "bob-example.md").frontmatter.get("decay_class") == "durable"
    assert _git(root, "rev-parse", "HEAD") != head_a and "Cicada-Author: user" in _git(root, "log", "-1",
                                                                                         "--format=%B")
    assert "entities/" not in _git(root, "status", "--porcelain"), "the page change is in A's commit, not left dirty"
    assert _state(beta) == beta_before, "nothing at all landed in B"
    assert bank_registry.active_bank_name(root) == "beta", "the switch itself stands"


def test_admission_refuses_a_bank_other_than_the_pinned_one(two_banks):
    root = two_banks
    beta = bank_registry.bank_dir(root, "beta")
    ran = []

    async def body():
        ran.append(1)

    async def run():
        bank_registry.pin_request_bank(root)
        await write_admission.run_admitted(beta, body)

    with pytest.raises(write_admission.WrongBank):
        asyncio.run(run())
    assert ran == [] and write_admission.holders(beta) == 0


def _bridge(monkeypatch, root, *, switch_first: bool):
    """The remote runtime's loopback POST, carried to the real ASGI app with the headers it sends."""
    from fastapi.testclient import TestClient

    sent: list[dict] = []

    def post(url, payload, headers, timeout=8):
        sent.append(dict(headers))
        if switch_first:
            bank_registry.activate_bank(root, "beta")              # the switch, after the call resolved its bank
        resp = TestClient(main.app).post(url.removeprefix("http://127.0.0.1:8000"), json=payload, headers=headers)
        if resp.status_code >= 400:
            raise urllib.error.HTTPError(url, resp.status_code, "error", {}, io.BytesIO(resp.content))
        return resp.json()

    monkeypatch.setattr(mcp_tools, "_loopback_post", post)
    return sent


def _remote():
    connector = catalog.Connector(id="ab12cd34", label="Phone", app="claude", scopes=catalog.DEFAULT_SCOPES | {"answer"},
                                  created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")
    return RemoteRuntime(backend_url="http://127.0.0.1:8000"), connector


def test_a_remote_backend_post_names_its_bank(two_banks, monkeypatch):
    sent = _bridge(monkeypatch, two_banks, switch_first=False)
    runtime, connector = _remote()
    text, status = runtime.call(connector, "cicada_resolve_inbox", {"id": "inbox-001", "defer": True})
    assert status == "ok", text
    assert sent and sent[0].get(bank_binding.HEADER) == "default"
    assert "Deferred" in text


def test_a_remote_answer_never_lands_in_a_bank_switched_to_after_the_call_began(two_banks, monkeypatch):
    root = two_banks
    beta = bank_registry.bank_dir(root, "beta")
    a_before, b_before = _state(root), _state(beta)
    _bridge(monkeypatch, root, switch_first=True)
    runtime, connector = _remote()
    text, status = runtime.call(connector, "cicada_resolve_inbox", {"id": "inbox-001", "defer": True})
    assert "Nothing was written" in text or "Could not resolve" in text, text
    assert _state(beta) == b_before, "the answer did not land in the bank switched to"
    assert _state(root) == a_before, "and nothing was half-written in its own"
