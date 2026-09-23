"""G61 phase 2 S1 — the agent surfaces (spec §5.3, §10.4; plan R-AC30, R-AC31):
`cicada_add_source` on stdio and remote, and `cicada_write_claim(sources=)`
taking `{ref, access}`. Synthetic bank; git is real; nothing reaches a network."""
from __future__ import annotations

import subprocess

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank
from api import config
from api.remote import catalog
from api.remote import tools as remote_tools
from api.remote.runtime import BUSY_TEXT, RemoteRuntime
from api.services import fact_sources

TEAM = "https://example.com/staff-directory"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def _sources(memory, eid="bob-example"):
    return fact_sources.list_sources(memory, eid)


@pytest.fixture
def server(tmp_path, monkeypatch):
    srv = stdio_server()
    memory = _bank(tmp_path)
    monkeypatch.setattr(srv, "get_memory_path", lambda: memory)
    monkeypatch.setattr(srv, "SESSION", srv.SessionIdentity("ses_2026-09-23_c0ffee00", "claude-code", None))
    return srv, memory


def _connector(scopes=catalog.DEFAULT_SCOPES):
    return catalog.Connector(id="ab12cd34", label="Phone", app="claude", scopes=frozenset(scopes),
                             created_at="2026-09-01T00:00:00+00:00", last_client="claude-ai")


@pytest.fixture
def remote(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    config.get_settings.cache_clear()
    yield RemoteRuntime(post=lambda p, d: {}, sleep_running=lambda: False), memory
    config.get_settings.cache_clear()


# ---------- stdio ----------


def test_a_stdio_source_is_the_harnesss_and_commits_alone(server):
    srv, memory = server
    (memory / "notes.md").write_text("an unrelated dirty file\n")
    out = srv.handle_add_source("bob-example", TEAM, "works-at")
    assert out.startswith("Added ") and TEAM in out
    assert _sources(memory) == [{"ref": TEAM, "kind": "url", "predicate": "works-at",
                                 "added_by": "claude-code", "added_at": _sources(memory)[0]["added_at"]}]
    body = _git(memory, "log", "-1", "--format=%B")
    assert body.startswith("Agent write ")
    assert "entities/bob-example.md: updated (trigger: mcp/claude-code)" in body
    assert "Cicada-Author: claude-code" in body and "Cicada-Engine" not in body
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/bob-example.md"]
    assert "notes.md" in _git(memory, "status", "--porcelain"), "never git add -A"


def test_a_repeat_is_already_listed_and_commits_nothing(server):
    srv, memory = server
    srv.handle_add_source("bob-example", TEAM, "works-at")
    head = _git(memory, "rev-parse", "HEAD")
    assert srv.handle_add_source("bob-example", TEAM, "works-at").startswith("Already listed")
    assert _git(memory, "rev-parse", "HEAD") == head and len(_sources(memory)) == 1


def test_no_page_means_nothing_written(server):
    srv, memory = server
    head = _git(memory, "rev-parse", "HEAD")
    out = srv.handle_add_source("nobody-example", TEAM, "works-at")
    assert out.startswith("No page named") and "cicada_" not in out
    assert _git(memory, "rev-parse", "HEAD") == head
    assert not (memory / "entities" / "nobody-example.md").exists()


def test_stdio_may_name_an_app_a_repo_and_their_access(server):
    srv, memory = server
    srv.handle_add_source("alpha-project", "~/src/alpha-project", "runs-on", "local", "repo")
    srv.handle_add_source("bob-example", "Calendar", "works-at", None, "app")
    assert [(s["kind"], s.get("access")) for s in _sources(memory, "alpha-project")] == [("repo", "local")]
    assert [s["kind"] for s in _sources(memory)] == ["app"]


def test_a_value_the_record_refuses_writes_nothing(server):
    srv, memory = server
    out = srv.handle_add_source("bob-example", TEAM, "works-at", "open")
    assert out.startswith("Nothing added") and "access must be one of" in out
    assert _sources(memory) == []


# ---------- remote ----------


def test_a_remote_source_is_the_apps_with_its_own_commit(remote):
    runtime, memory = remote
    text, status = runtime.call(_connector(), "cicada_add_source",
                                {"subject": "bob-example", "ref": TEAM, "predicate": "works-at"})
    assert status == "ok" and text.startswith("Added ")
    assert _sources(memory)[0]["added_by"] == "claude-web"
    body = _git(memory, "log", "-1", "--format=%B")
    assert body.startswith("Remote write ") and "trigger: remote/claude-web" in body
    assert "Cicada-Author: claude-web" in body


@pytest.mark.parametrize("args", [
    {"ref": "~/Documents/cv.pdf"},
    {"ref": "/tmp/alpha-project/notes.md"},
    {"ref": "alpha-project checkout", "kind": "repo"},
    {"ref": "alpha-project checkout", "kind": "path"},
    {"ref": TEAM, "access": "local"},
])
def test_a_remote_app_can_never_name_a_file_on_this_mac(remote, args):
    runtime, memory = remote
    page = memory / "entities" / "bob-example.md"
    before, head = page.read_text(), _git(memory, "rev-parse", "HEAD")
    text, status = runtime.call(_connector(), "cicada_add_source", {"subject": "bob-example", **args})
    assert status == "ok" and "can't name a file or folder" in text
    assert page.read_text() == before and _git(memory, "rev-parse", "HEAD") == head


def test_the_tool_is_a_record_scoped_write_and_waits_for_sleep(remote):
    # The `remote` fixture pins CICADA_MEMORY_PATH: the runtime's ledger row
    # resolves the bank even for a refused call, and a test must never let
    # that fall through to a default bank path.
    _, memory = remote
    assert catalog.TOOL_SCOPE["cicada_add_source"] == "record"
    assert "cicada_add_source" in catalog.WRITE_TOOLS
    assert "cicada_add_source" in catalog.tool_names_for({"record"})
    busy = RemoteRuntime(post=lambda p, d: {}, sleep_running=lambda: True)
    assert busy.call(_connector(), "cicada_add_source", {"subject": "bob-example", "ref": TEAM}) == (BUSY_TEXT, "busy")
    assert _sources(memory) == []


def test_the_remote_schema_offers_no_local_choice_and_names_no_other_tool():
    d = remote_tools.REMOTE_TOOLS["cicada_add_source"]
    props = d["inputSchema"]["properties"]
    assert "local" not in props["access"]["enum"]
    assert not {"path", "repo"} & set(props["kind"]["enum"])
    assert "cicada_" not in d["description"]
    assert d["annotations"]["read_only_hint"] is False and d["annotations"]["open_world_hint"] is False
    stdio = {t["name"]: t for t in stdio_server().TOOLS}["cicada_add_source"]
    assert "cicada_sources" in stdio["description"], "locally it says it is not the conversations tool"


# ---------- cicada_write_claim(sources=) ----------


def test_write_claim_takes_a_string_or_ref_and_access_and_drops_the_rest(server):
    srv, memory = server
    out = srv.handle_write_claim("alpha-project", "uses", "sqlite-vec", None, None, None, None, False, [
        {"ref": TEAM, "access": "public"}, "ask me, I announce changes", {"access": "public"},
        {"ref": "https://example.com/x", "access": "open"}, {"ref": "https://example.com/y", "access": "local"},
        42,
    ])
    assert out.startswith("Recorded")
    got = [(s["ref"], s.get("access"), s["added_by"]) for s in _sources(memory, "alpha-project")]
    assert got == [(TEAM, "public", "claude-code"), ("ask me, I announce changes", None, "claude-code"),
                   ("https://example.com/x", None, "claude-code"), ("https://example.com/y", None, "claude-code")]


def test_a_remote_write_claim_drops_a_path_source(remote):
    runtime, memory = remote
    text, status = runtime.call(_connector(), "cicada_write_claim", {
        "subject": "alpha-project", "predicate": "uses", "object": "sqlite-vec",
        "sources": ["~/Documents/notes.md", TEAM]})
    assert status == "ok"
    assert [s["ref"] for s in _sources(memory, "alpha-project")] == [TEAM]


def test_both_schemas_take_a_string_or_a_ref_object():
    stdio = {t["name"]: t for t in stdio_server().TOOLS}["cicada_write_claim"]
    for tool in (stdio, remote_tools.REMOTE_TOOLS["cicada_write_claim"]):
        items = tool["inputSchema"]["properties"]["sources"]["items"]["anyOf"]
        assert items[0] == {"type": "string"}
        assert items[1]["type"] == "object" and items[1]["required"] == ["ref"]
