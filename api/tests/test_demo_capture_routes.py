"""G141 capture-side track (R-CS15, R-CS16): with the demo bank open, every
HTTP capture route answers 409 and writes nothing; the intake checks the bank
it writes INTO, so importing into your own memory still works; Sleep's tail on
a demo bank takes nothing in from outside. Synthetic banks only."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from _intake_fixtures import claude_conversations
from api import config, main
from api.routers.capture import refuse_capture_into_demo
from api.services import bank_registry, demo_guard, sleep_cycle

#: Every POST/PUT under /capture/ and /sources/ that the one dependency gates,
#: with a concrete path to call (R-CS15).
GATED = {
    ("POST", "/sources/save"): "/sources/save",
    ("POST", "/sources/upload"): "/sources/upload",
    ("POST", "/sources/rss"): "/sources/rss",
    ("POST", "/sources/sync-bookmarks"): "/sources/sync-bookmarks",
    ("POST", "/sources/sync-safari-tabs"): "/sources/sync-safari-tabs",
    ("POST", "/sources/feeds"): "/sources/feeds",
    ("POST", "/sources/poll-feeds"): "/sources/poll-feeds",
    ("POST", "/sources/calendars"): "/sources/calendars",
    ("POST", "/sources/poll-calendars"): "/sources/poll-calendars",
    ("POST", "/sources/sync-notes"): "/sources/sync-notes",
    ("POST", "/sources/folders"): "/sources/folders",
    ("PUT", "/sources/folders/{folder_id}"): "/sources/folders/f1",
    ("POST", "/sources/folders/{folder_id}/sync"): "/sources/folders/f1/sync",
    ("POST", "/sources/calendar-local/sync"): "/sources/calendar-local/sync",
    ("POST", "/sources/tab-groups/sync"): "/sources/tab-groups/sync",
    # A connector id no adapter has: were the gate missing, the handler 404s
    # before any adapter could reach the network (sync_now passes allow_fetch=True).
    ("POST", "/sources/connectors/{connector_id}/sync"): "/sources/connectors/no-such-connector/sync",
    ("POST", "/capture/local-source/wispr-flow"): "/capture/local-source/wispr-flow",
    ("PUT", "/capture/local-source/wispr-flow/settings"): "/capture/local-source/wispr-flow/settings",
}
#: The rest of the prefixes, each with the reason it is not the dependency's.
HANDLED_ELSEWHERE = {
    ("POST", "/capture/transcript"): "redirects to the real bank left last (test_demo_capture.py)",
    ("POST", "/capture/telegram"): "answers 200 with a reply so Telegram never retries (test_demo_capture.py)",
    ("POST", "/capture/hook-context"):
        "reads only, from bank_registry.capture_bank — the real bank left last while the demo is open "
        "(test_hook_context_route.py)",
    ("POST", "/intake/import"): "checks its TARGET bank in intake.resolve_target",
    ("POST", "/intake/sniff"): "stages nothing; a chat export's TARGET bank is checked in intake.resolve_target",
    ("PUT", "/sources/connectors/{connector_id}/credentials"):
        "stores the secret in ~/.cicada/secrets.env; only restamps the bank's sync_state.json, no content",
    ("POST", "/sources/connectors/{connector_id}/authorize"): "returns a sign-in link, takes nothing in",
}
PREFIXES = ("/capture/", "/sources/", "/intake/")


@pytest.fixture(autouse=True)
def _no_local_reader(monkeypatch):
    """With no body, `/sources/sync-bookmarks` and `/sources/sync-notes` fall
    back to THIS machine's bookmark files and Notes.app (`sources.py:428,883`).
    A bodiless call that reaches a handler (this file's red phase, or a gate
    removed on purpose to prove the lint) must fail loudly, never read them."""
    from api.services import bookmark_sync, notes_sync

    def _refuse(*_a, **_k):
        raise AssertionError("a demo-gate test reached a local reader; the gate is missing")

    monkeypatch.setattr(bookmark_sync, "sync_from_local_files", _refuse)
    monkeypatch.setattr(notes_sync, "sync_from_local_notes", _refuse)


def _routes() -> dict[tuple[str, str], APIRoute]:
    return {(m, r.path): r for r in main.app.routes if isinstance(r, APIRoute) for m in r.methods}


def test_every_capture_route_is_gated_or_named():
    live = {k for k in _routes() if k[0] in ("POST", "PUT") and k[1].startswith(PREFIXES)}
    assert live == set(GATED) | set(HANDLED_ELSEWHERE)


def test_the_gated_routes_carry_the_one_dependency_and_the_others_do_not():
    routes = _routes()
    for key in GATED:
        assert refuse_capture_into_demo in {d.call for d in routes[key].dependant.dependencies}, key
    for key in HANDLED_ELSEWHERE:
        assert refuse_capture_into_demo not in {d.call for d in routes[key].dependant.dependencies}, key


@pytest.fixture
def demo_open(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    slug = bank_registry.create_bank(root, "demo")
    demo = bank_registry.bank_dir(root, slug)
    demo_guard.write_manifest(demo)
    bank_registry.activate_bank(root, slug)
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    yield SimpleNamespace(client=TestClient(main.app), root=root, demo=demo)
    config.get_settings.cache_clear()


def _files(path: Path) -> set[str]:
    return {p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file() and ".git" not in p.parts}


@pytest.mark.parametrize("key", sorted(GATED))
def test_a_gated_route_answers_409_and_writes_nothing(demo_open, key):
    before = _files(demo_open.demo)
    r = demo_open.client.request(key[0], GATED[key])
    assert r.status_code == 409, (key, r.text)
    assert r.json()["detail"] == demo_guard.REFUSAL
    assert _files(demo_open.demo) == before


def test_a_real_active_bank_is_not_refused(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.delenv("CICADA_MEMORY_PATH", raising=False)
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    config.get_settings.cache_clear()
    try:
        assert TestClient(main.app).post("/sources/poll-feeds").status_code == 200
    finally:
        config.get_settings.cache_clear()


def _export() -> bytes:
    return json.dumps(claude_conversations(1)).encode()


def test_importing_into_the_open_demo_is_refused_and_writes_nothing(demo_open):
    for route in ("/intake/import", "/intake/sniff", "/conversations/upload",
                  f"/banks/{demo_open.demo.name}/import"):
        r = demo_open.client.post(route, files={"file": ("conversations.json", _export(), "application/json")})
        assert r.status_code == 409 and r.json()["detail"] == demo_guard.REFUSAL, (route, r.text)
    assert list((demo_open.demo / "episodes").glob("*.md")) == []


def test_importing_into_your_own_memory_still_works_while_the_demo_is_open(demo_open):
    r = demo_open.client.post("/intake/import", params={"bank": "default"},
                              files={"file": ("conversations.json", _export(), "application/json")})
    assert r.status_code == 200, r.text
    assert r.json()["bank"] == "default" and r.json()["episodesStaged"] >= 1
    assert list((demo_open.root / "episodes").glob("ep_*.md"))
    assert list((demo_open.demo / "episodes").glob("*.md")) == []


# --- Sleep's tail (R-CS16) ---------------------------------------------------------

TAIL_STEPS = ("_refresh_state_safely", "_expire_claims_safely", "_poll_connectors_safely",
              "_poll_feeds_and_calendars_safely", "_backfill_links_safely", "_resolve_papers_safely",
              "_replay_wispr_todos_safely", "_warm_logos_safely", "_refresh_questions_safely")


def _tail_order(monkeypatch, bank: Path) -> list[str]:
    order: list[str] = []

    def fake(name):
        async def _f(*a, **k):
            order.append(name)
        return _f

    for name in TAIL_STEPS:
        monkeypatch.setattr(sleep_cycle, name, fake(name))
    asyncio.run(sleep_cycle._run_engine_independent_tail(
        bank, SimpleNamespace(), sleep_cycle._StageOutcome(committed=True)))
    return order


def test_a_demo_banks_sleep_takes_nothing_in_from_outside(tmp_path, monkeypatch):
    demo = tmp_path / "demo"
    bank_registry.scaffold_bank(demo, git_init=False)
    demo_guard.write_manifest(demo)
    assert _tail_order(monkeypatch, demo) == ["_refresh_state_safely", "_expire_claims_safely",
                                              "_warm_logos_safely", "_refresh_questions_safely"]


def test_a_real_banks_tail_is_unchanged(tmp_path, monkeypatch):
    real = tmp_path / "real"
    bank_registry.scaffold_bank(real, git_init=False)
    assert _tail_order(monkeypatch, real) == list(TAIL_STEPS)
