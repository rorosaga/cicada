"""G150 — agents file, note and read a project's backlog over MCP, locally and remotely (R-B6, R-B8, R-B12,
R-B13, R-B16, R-B17). Synthetic only."""
import subprocess

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank, _ok_repo, _settings
from api.remote import catalog
from api.remote import tools as remote_tools
from api.services import backlog, bank_index, handshake, mcp_tools, state_dictionary


@pytest.fixture
def bank(tmp_path, monkeypatch):
    memory = _bank(tmp_path)                                      # a git bank: every write commits
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))    # the state file's reads never reach ~/.cicada
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    bank_index.invalidate()
    return memory


def _ctx(bank, scopes=None):
    if scopes is None:
        return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_test", harness="claude-code")
    return mcp_tools.ToolContext(memory_path=lambda: bank, session_id="rc_abcd1234_x", harness="claude-web",
                                 connector_id="abcd1234", available=catalog.tool_names_for(scopes),
                                 raw_excerpts="sources" in scopes, read_surface="remote")


def _git(bank, *args):
    return subprocess.run(["git", *args], cwd=bank, capture_output=True, text=True, check=True).stdout


def test_an_agent_files_an_item_notes_it_and_reads_it_back(bank):
    ctx = _ctx(bank)
    reply = mcp_tools.add_backlog_item(ctx, "alpha-project", "Cache the timeline", "Opening a big project is slow.",
                                       "apply")
    assert reply.startswith("Added AP1 to alpha-project's backlog: Cache the timeline (open).")
    assert 'cicada_add_backlog_note(item="alpha-project/AP1", note)' in reply
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Agent write ") and "Cicada-Author: claude-code" in log and "Cicada-Session: ses_test" in log
    assert "backlog/alpha-project/AP1.md: created (source: n/a, trigger: mcp/claude-code)" in log
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == ["backlog/alpha-project/AP1.md"]
    assert mcp_tools.add_backlog_note(ctx, "AP1", "Found the slow path.", "doing") == \
        "Noted on AP1 (Cache the timeline) — now doing."
    listed = mcp_tools.backlog(ctx, "Alpha Project")
    assert listed.splitlines()[0] == "Alpha Project backlog — 0 open · 1 doing · 0 done · 0 dropped"
    assert "- AP1 · Cache the timeline — doing · apply · last note" in listed and "by Claude Code" in listed
    full = mcp_tools.backlog(ctx, "alpha-project", item="AP1")
    assert "Description:\nOpening a big project is slow." in full
    assert "· Claude Code: Found the slow path.\n\nMoved from open to doing." in full


def test_one_row_per_idea_the_second_filing_points_at_the_first(bank):
    ctx = _ctx(bank)
    mcp_tools.add_backlog_item(ctx, "alpha-project", "Cache the timeline", "Slow.")
    head = _git(bank, "rev-parse", "HEAD")
    reply = mcp_tools.add_backlog_item(ctx, "alpha-project", "cache the  timeline", "Still slow.")
    assert reply.startswith("NOT added — AP1 already holds this idea") and "cicada_add_backlog_note" in reply
    assert _git(bank, "rev-parse", "HEAD") == head


def test_refusals_are_one_line_and_write_nothing(bank, monkeypatch):
    ctx = _ctx(bank)
    assert "Nothing was added" in mcp_tools.add_backlog_item(ctx, "alpha-project", "X", "   ")
    assert mcp_tools.add_backlog_item(ctx, "bob-example", "X", "Why.").startswith(
        "Not added: bob-example is a person")
    assert mcp_tools.add_backlog_note(ctx, "ZZ9", "x").startswith("Not noted: no backlog item ZZ9")
    assert mcp_tools.backlog(ctx, "alpha-project", status="someday").startswith("'someday' isn't a status")
    monkeypatch.setattr(mcp_tools, "_backend_sleep_running", lambda url, headers: True)
    assert mcp_tools.add_backlog_item(ctx, "alpha-project", "X", "Why.") == mcp_tools.BACKLOG_SLEEPING
    assert not (bank / "backlog").exists()


def test_a_remote_app_writes_as_itself_and_without_sources_never_reads_the_persons_words(bank):
    backlog.add_item(bank, project="alpha-project", title="Mine", description="My own reasoning.", author="user")
    backlog.add_note(bank, project="alpha-project", item="AP1", note="My own note.", author="user")
    remote = _ctx(bank, {"search", "read", "record"})
    assert mcp_tools.add_backlog_item(remote, "alpha-project", "Theirs", "An agent's reasoning.").startswith("Added AP2")
    log = _git(bank, "log", "-1", "--format=%B")
    assert log.startswith("Remote write ") and "Cicada-Author: claude-web" in log
    assert "trigger: remote/claude-web" in log and "Cicada-Session: rc_abcd1234_x" in log
    shown = mcp_tools.backlog(remote, "alpha-project", item="AP1")
    assert "My own reasoning." not in shown and "My own note." not in shown and mcp_tools.PERSONS_WORDS in shown
    assert "An agent's reasoning." in mcp_tools.backlog(remote, "alpha-project", item="AP2")
    assert "My own note." in mcp_tools.backlog(_ctx(bank, {"read", "sources"}), "alpha-project", item="AP1")
    assert "cicada_add_backlog_note" not in mcp_tools.backlog(_ctx(bank, {"read"}), "alpha-project")


def test_the_tools_are_classified_once_and_their_schemas_carry_the_contracts_arguments():
    assert catalog.TOOL_SCOPE["cicada_backlog"] == "read" and "cicada_backlog" in catalog.READ_TOOLS
    for tool in ("cicada_add_backlog_item", "cicada_add_backlog_note"):
        assert catalog.TOOL_SCOPE[tool] == "record" and tool in catalog.WRITE_TOOLS
    stdio = {t["name"]: t for t in stdio_server().TOOLS}
    assert stdio["cicada_add_backlog_item"]["inputSchema"]["required"] == ["project", "title", "description"]
    assert stdio["cicada_add_backlog_note"]["inputSchema"]["required"] == ["item", "note"]
    assert set(remote_tools.REMOTE_TOOLS["cicada_backlog"]["inputSchema"]["properties"]) == {
        "project", "status", "item", "conversation"}


def test_the_stdio_server_dispatches_the_three_tools(bank, monkeypatch):
    server = stdio_server()
    monkeypatch.setattr(server, "get_memory_path", lambda: bank)
    assert server.handle_tool("cicada_add_backlog_item", {"project": "alpha-project", "title": "X",
                                                          "description": "Why."}).startswith("Added AP1")
    assert server.handle_tool("cicada_add_backlog_note", {"item": "AP1", "note": "Found."}).startswith("Noted on AP1")
    assert server.handle_tool("cicada_backlog", {"project": "alpha-project"}).startswith("Alpha Project backlog")


def test_the_primer_says_what_to_do_and_counts_open_items(bank):
    assert (handshake.CONTRACT_VERSION, handshake.REMOTE_CONTRACT_VERSION) == (8, 5)  # 8: merged past G149's 7 (R-H13)
    backlog.add_item(bank, project="alpha-project", title="One", author="user")
    backlog.add_item(bank, project="alpha-project", title="Two", author="user")
    state_dictionary.refresh(bank, _settings(bank), force=True, repo_resolver=_ok_repo)
    st = state_dictionary.read_state(bank)
    assert st["schema_version"] == 4
    rows = {p["id"]: p for p in st["projects"]}
    assert rows["alpha-project"]["backlog_open"] == 2
    assert all("backlog_open" not in p for pid, p in rows.items() if pid != "alpha-project")
    text = handshake.build(st, variant="claude-code", bank="memory", tz="UTC")
    assert "`cicada_add_backlog_item(project, title, description)`" in text and "never a second item" in text
    assert "`backlog/`" in text and " · backlog: 2 open" in text
    assert len(text) // 4 <= handshake.MAX_TOKENS
    record_only = handshake.build_remote(st, tools=catalog.tool_names_for({"record"}), bank="memory")
    assert "cicada_add_backlog_item(" in record_only and " · backlog: " not in record_only   # G140's gate


def test_a_backlog_write_moves_the_state_files_inputs(bank):
    before = state_dictionary.inputs_version(bank)
    backlog.add_item(bank, project="alpha-project", title="One", author="user")
    assert state_dictionary.inputs_version(bank) != before


def test_cicada_project_lists_the_open_items_and_names_the_tool_only_when_held(tmp_path, monkeypatch):
    from _demo_scenario import T, demo

    b = demo(tmp_path)
    monkeypatch.setattr(handshake, "local_timezone", lambda: "UTC")
    monkeypatch.setattr(mcp_tools, "_today_in", lambda tz: T)
    local = mcp_tools.ToolContext(memory_path=lambda: b, session_id="ses_test", harness="claude-code")
    assert ("Backlog: 3 open — RAP5 Pick a wrist servo [decide] (doing); RAP3 Swap the gripper camera for a "
            "global-shutter one [research]; RAP4 Add a soft stop when the arm leaves the tray [apply] — "
            "cicada_backlog(project) lists them all") in mcp_tools.project(local, "rover-arm-project")
    narrow = mcp_tools.ToolContext(memory_path=lambda: b, session_id="rc_x", harness="claude-web",
                                   connector_id="abcd1234", available=frozenset({"cicada_project"}),
                                   raw_excerpts=False, read_surface="remote")
    out = mcp_tools.project(narrow, "rover-arm-project")
    assert "Backlog: 3 open" in out and "cicada_backlog(" not in out
