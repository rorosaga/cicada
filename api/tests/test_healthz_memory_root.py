"""`/healthz` exposes the raw *configured* memory root alongside the resolved
active-bank path (G88 follow-up).

Why this matters: `CICADA_MEMORY_PATH` names the memory ROOT (container of
`banks.yaml` + `banks/<name>/`), never a bank directly — see
`api/config.py::Settings.memory_root`. The companion app's Connect page used
to build its copy-pasteable MCP registration commands from a *local* Swift
heuristic (`BackendProcess.installRoot()`) instead of asking the actually-
running backend what root it was configured with. Those two computations can
disagree (e.g. a default `install.sh` run outside `~/cicada` bakes the
launchd backend's `CICADA_MEMORY_PATH` to `~/cicada/memory` while the app's
own heuristic resolves the real checkout instead) — a copy-pasted command
then registers an agent against a different bank than the one the app
itself talks to, silently. This is the same *class* of bug as the MCP
bank-resolution split-brain fixed 2026-07-03 (`mcp/server.py`
`get_memory_path()`), just on the app side instead of the MCP-server side.

The fix: `/healthz` (auth-exempt, so no token dance is needed) now reports
`memoryRoot` — the raw configured root — so the app can read the backend's
own answer instead of re-deriving one that can drift. These tests pin the
contract that fix depends on: `memoryRoot` is always the raw root, and it is
distinct from `memoryPath` (the resolved active bank) once a non-default
bank is active.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_registry


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path / "memory"))
    monkeypatch.delenv("CICADA_API_TOKEN", raising=False)
    monkeypatch.setenv("CICADA_API_AUTH", "off")
    config.get_settings.cache_clear()
    yield tmp_path / "memory"
    config.get_settings.cache_clear()


def test_healthz_reports_the_configured_root(home):
    with TestClient(main.app) as client:
        body = client.get("/healthz").json()
    assert body["memoryRoot"] == str(home)
    # Legacy contract: with no banks.yaml yet, the resolved path IS the root.
    assert body["memoryPath"] == str(home)


def test_healthz_root_differs_from_resolved_bank_path_once_a_bank_is_active(home):
    bank_registry.create_bank(home, "work")
    bank_registry.activate_bank(home, "work")
    config.get_settings.cache_clear()

    with TestClient(main.app) as client:
        body = client.get("/healthz").json()

    assert body["memoryRoot"] == str(home)
    assert body["memoryPath"] == str(home / "banks" / "work")
    assert body["memoryRoot"] != body["memoryPath"]


def test_healthz_root_is_stable_across_a_bank_switch(home):
    """The root a client should register an MCP agent against never changes
    when the active bank changes — only `resolve_active_bank_path` (applied
    fresh, by both the API and the MCP server, on every request) does. This
    is exactly why the root, not the resolved path, is the value the
    Connect page's copy-pasted commands must use.
    """
    bank_registry.create_bank(home, "work")
    bank_registry.create_bank(home, "personal")

    bank_registry.activate_bank(home, "work")
    config.get_settings.cache_clear()
    with TestClient(main.app) as client:
        first = client.get("/healthz").json()

    bank_registry.activate_bank(home, "personal")
    config.get_settings.cache_clear()
    with TestClient(main.app) as client:
        second = client.get("/healthz").json()

    assert first["memoryRoot"] == second["memoryRoot"] == str(home)
    assert first["memoryPath"] != second["memoryPath"]
