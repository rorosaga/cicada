"""The memory-tool adapter (`clients/memory-tool`): Claude's memory tool answered by a Cicada agent token over `/v1`.

A client of the agent API, not a door (ruling 38, clarified 2026-10-29): every command below reaches the backend only
as `POST /v1/<op>` / `GET /v1/me` with a scoped `cic_api_` token, through the real routes in process. Synthetic bank
and placeholder names only; nothing reaches the network.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from api.services import markdown_parser
from api.tests.test_agent_api import _agent, _auth, server  # noqa: F401 — the fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clients" / "memory-tool" / "python"))
from cicada_memory_tool import CicadaMemory, MemoryCommandError  # noqa: E402


def _memory(client, token, calls=None, **kw):
    def send(method, path, body):
        if calls is not None:
            calls.append((method, path))
        answer = client.request(method, path, json=body, headers=_auth(token))
        return answer.status_code, answer.json()
    return CicadaMemory(transport=send, **kw)


def _hub(memory_path):
    markdown_parser.write(memory_path / "hubs" / "projects.md", {"type": "hub"},
                          "# Projects\n- [[alpha-project]] — Alpha.\n- [[beta-project]] — Beta.")


def _episodes(memory_path):
    return sorted(p.name for p in (memory_path / "episodes").glob("*.md"))


def _refused(memory, command):
    with pytest.raises(MemoryCommandError) as refused:
        memory.execute(command)
    return str(refused.value)


@pytest.mark.parametrize("path", [
    "/memories/../secrets.env", "/memories/pages/../../x", "/etc/passwd", "/memoriesX/a", "memories/a",
    "/memories/%2e%2e%2fsecrets", "/memories/pages\\..\\x", "/memories/.hidden", "/memories//pages",
    "/memories/pages/a\x00b", "/memories/./pages",
])
def test_every_path_outside_memories_is_refused_before_a_request_is_made(server, path):
    client, master, _ = server
    calls: list = []
    memory = _memory(client, _agent(client, master)["token"], calls)
    for command in ({"command": "view", "path": path}, {"command": "create", "path": path, "file_text": "x"},
                    {"command": "delete", "path": path},
                    {"command": "rename", "old_path": path, "new_path": "/memories/notes/a.md"}):
        assert "Error: The path" in _refused(memory, command)
    assert calls == []


def test_the_listing_shows_what_this_token_can_open(server):
    client, master, memory_path = server
    _hub(memory_path)
    full = _memory(client, _agent(client, master, scopes=("search", "read", "record", "sources"))["token"])
    listing = full.execute({"command": "view", "path": "/memories"})
    assert listing.startswith("Here're the files and directories up to 2 levels deep in /memories")
    for line in ("\t/memories/README.md", "\t/memories/recent.md", "\t/memories/hubs/projects.md",
                 "\t/memories/search", "\t/memories/pages", "\t/memories/sources", "\t/memories/notes"):
        assert line in listing
    assert "/memories/hubs/people.md" not in listing  # a hub this memory does not have is not listed

    record_only = _memory(client, _agent(client, master, name="writer", scopes=("record",))["token"])
    listing = record_only.execute({"command": "view", "path": "/memories"})
    assert "/memories/notes" in listing and "/memories/pages" not in listing and "/memories/hubs" not in listing
    assert "can open" in record_only.execute({"command": "view", "path": "/memories/README.md"})
    assert "scopes do not include it" in _refused(record_only, {"command": "view", "path": "/memories/pages"})


def test_a_page_reads_numbered_with_cicadas_fence_kept_and_a_range_reads_from_its_line(server):
    client, master, _ = server
    memory = _memory(client, _agent(client, master)["token"])
    page = memory.execute({"command": "view", "path": "/memories/pages/alpha-project.md"})
    lines = page.split("\n")
    assert lines[0] == "Here's the content of /memories/pages/alpha-project.md with line numbers:"
    assert "<<<cicada-reference" in lines and "cicada-reference>>>" in lines
    assert "     1\t---" in lines and "     2\tname: Alpha Project" in lines
    assert any(line.endswith("\tAlpha Project is a synthetic fixture.") for line in lines)

    part = memory.execute({"command": "view", "path": "/memories/pages/alpha-project.md", "view_range": [3, 4]})
    numbered = [line for line in part.split("\n") if line[:6].strip().isdigit()]
    assert numbered == ["     3\ttype: project", "     4\tstatus: active"]

    missing = _refused(memory, {"command": "view", "path": "/memories/pages/no-such-page.md"})
    assert missing.startswith("The path /memories/pages/no-such-page.md does not exist.")


def test_search_hub_and_recent_are_read_through_their_operations(server):
    client, master, memory_path = server
    _hub(memory_path)
    calls: list = []
    memory = _memory(client, _agent(client, master)["token"], calls)
    found = memory.execute({"command": "view", "path": "/memories/search/alpha-project.md"})
    assert "Alpha Project" in found and ("POST", "/v1/recall") in calls
    hub = memory.execute({"command": "view", "path": "/memories/hubs/projects.md"})
    assert "[[alpha-project]]" in hub
    assert "What changed in memory" in memory.execute({"command": "view", "path": "/memories/recent.md"})


def test_a_note_is_saved_as_the_agents_own_words_and_an_edit_saves_the_revised_note(server, tmp_path):
    client, master, memory_path = server
    state = tmp_path / "agent" / "memory-state.json"
    token = _agent(client, master)["token"]
    memory = _memory(client, token, state_path=state)
    before = _episodes(memory_path)
    made = memory.execute({"command": "create", "path": "/memories/notes/alpha-plan.md",
                           "file_text": "Plan for alpha:\n- ship the beta\n"})
    assert made.startswith("File created successfully at: /memories/notes/alpha-plan.md") and "in your words" in made
    added = sorted(set(_episodes(memory_path)) - set(before))
    assert len(added) == 1
    parsed = markdown_parser.parse(memory_path / "episodes" / added[0])
    frontmatter, body = parsed.frontmatter, parsed.body
    assert "ship the beta" in body and frontmatter.get("harness") == "agent-api"
    assert "/memories/notes/alpha-plan.md" in memory.execute({"command": "view", "path": "/memories/notes"})

    edited = memory.execute({"command": "str_replace", "path": "/memories/notes/alpha-plan.md",
                             "old_str": "ship the beta", "new_str": "ship the beta on Friday"})
    assert edited.startswith("The memory file has been edited.")
    memory.execute({"command": "insert", "path": "/memories/notes/alpha-plan.md", "insert_line": 0,
                    "insert_text": "Decided today."})
    view = memory.execute({"command": "view", "path": "/memories/notes/alpha-plan.md"})
    assert "     1\tDecided today." in view and "ship the beta on Friday" in view
    assert len(set(_episodes(memory_path)) - set(before)) == 3  # every save is a record; none is overwritten

    # The agent's own notes outlive the process on its machine, owner-only.
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    again = _memory(client, token, state_path=state)
    assert "ship the beta on Friday" in again.execute({"command": "view", "path": "/memories/notes/alpha-plan.md"})

    assert "did not appear verbatim" in _refused(memory, {"command": "str_replace", "path":
                                                          "/memories/notes/alpha-plan.md", "old_str": "absent"})
    assert "Invalid `insert_line`" in _refused(memory, {"command": "insert", "path": "/memories/notes/alpha-plan.md",
                                                        "insert_line": 99, "insert_text": "x"})
    assert "already holds this exact text" in memory.execute({"command": "create", "path": "/memories/notes/b.md",
                                                              "file_text": "Decided today.\nPlan for alpha:\n"
                                                                           "- ship the beta on Friday\n"})


def test_pages_are_never_written_and_nothing_is_deleted_or_renamed(server):
    client, master, memory_path = server
    memory = _memory(client, _agent(client, master)["token"])
    memory.execute({"command": "create", "path": "/memories/notes/mine.md", "file_text": "A note."})
    before = _episodes(memory_path)
    page_before = (memory_path / "entities" / "alpha-project.md").read_text()
    for command in ({"command": "create", "path": "/memories/pages/alpha-project.md", "file_text": "x"},
                    {"command": "str_replace", "path": "/memories/pages/alpha-project.md", "old_str": "Alpha",
                     "new_str": "Beta"},
                    {"command": "insert", "path": "/memories/hubs/projects.md", "insert_line": 0, "insert_text": "x"},
                    {"command": "create", "path": "/memories/recent.md", "file_text": "x"}):
        assert "read-only here" in _refused(memory, command) and "/memories/notes/" in _refused(memory, command)
    for command in ({"command": "delete", "path": "/memories/notes/mine.md"},
                    {"command": "delete", "path": "/memories/pages/alpha-project.md"},
                    {"command": "rename", "old_path": "/memories/notes/mine.md", "new_path": "/memories/notes/b.md"}):
        assert "Nothing was" in _refused(memory, command)
    assert "cannot be deleted" in _refused(memory, {"command": "delete", "path": "/memories"})
    assert _episodes(memory_path) == before
    assert (memory_path / "entities" / "alpha-project.md").read_text() == page_before
    assert "A note." in memory.execute({"command": "view", "path": "/memories/notes/mine.md"})


def test_cicada_decides_the_scope_and_its_sentence_reaches_the_model(server):
    client, master, memory_path = server
    read_only = _memory(client, _agent(client, master, name="reader", scopes=("search", "read"))["token"])
    before = _episodes(memory_path)
    refusal = _refused(read_only, {"command": "create", "path": "/memories/notes/x.md", "file_text": "x"})
    assert "isn't allowed" in refusal
    assert _episodes(memory_path) == before
    # The listing does not offer a folder the token cannot use.
    assert "/memories/notes" not in read_only.execute({"command": "view", "path": "/memories"})


def test_the_sdk_backend_turns_a_refusal_into_an_error_result(server):
    anthropic = pytest.importorskip("anthropic")
    from anthropic.lib.tools import ToolError
    from cicada_memory_tool import CicadaMemoryTool

    client, master, _ = server
    tool = CicadaMemoryTool(memory=_memory(client, _agent(client, master)["token"]))
    assert tool.to_dict() == {"type": "memory_20250818", "name": "memory"}
    assert "README.md" in tool.call({"command": "view", "path": "/memories"})
    with pytest.raises(ToolError):
        tool.call({"command": "delete", "path": "/memories/notes/x.md"})
    assert anthropic
