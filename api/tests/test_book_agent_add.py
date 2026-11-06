"""`cicada_add_book`: an agent adds a book on the person's ask, by the ISBN it found, through the scan's writer, with
one body on every door (piece 2b). Synthetic numbers and titles only (the fixtures of ``test_books``)."""
from __future__ import annotations

import pytest

from api.remote import catalog, runtime as remote_runtime, tools as remote_tools
from api.services import books, cli_map, markdown_parser, mcp_tools, tool_door
from api.services.claims import parse_claims
from test_books import PAPERBACK, UNKNOWN, _books, client  # noqa: F401  (fixtures)


def _home_ctx(memory, harness="claude-code"):
    """The context the tool door builds: in the home, Sleep asked in-process."""
    caller = tool_door.Caller(session_id="sess-1", harness=harness, project_dir=None, client_name=None, client_version=None)
    return tool_door.context(memory_path=memory, bank_name=memory.name, caller=caller, state=tool_door.SessionState(),
                             surface="mcp", device_id=None, backend_url="http://127.0.0.1:1", headers=lambda: {})


def _remote_ctx(memory):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="r", harness="claude-ai", connector_id="abc123")


def _stdio_ctx(memory, post):
    return mcp_tools.ToolContext(memory_path=lambda: memory, session_id="s", harness="claude-code",
                                 backend_url="http://127.0.0.1:1", post=post, headers=lambda: {},
                                 sleep_probe=None)


def test_preview_shows_the_edition_and_writes_nothing(client):
    _, memory, calls = client
    before = len(list((memory / "episodes").glob("*.md")))
    text = str(mcp_tools.add_book(_home_ctx(memory), "978-0-00-000000-2", True))
    assert "The Lantern Orchard" in text and "Ada Example" in text
    assert len(list((memory / "episodes").glob("*.md"))) == before and not _books(memory)
    assert all("The Lantern" not in u for u in calls)             # the number is asked, never a title


def test_preview_of_an_unknown_number_and_the_network_off(client, monkeypatch):
    _, memory, calls = client
    assert "No edition" in str(mcp_tools.add_book(_home_ctx(memory), UNKNOWN, True))
    calls.clear()
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "off")
    assert "No edition" in str(mcp_tools.add_book(_home_ctx(memory), PAPERBACK, True)) and not calls


@pytest.mark.parametrize("make", [_home_ctx, _remote_ctx])
def test_an_add_in_the_home_makes_the_page_with_no_status(client, make):
    _, memory, _ = client
    text = str(mcp_tools.add_book(make(memory), PAPERBACK, False))
    assert text.startswith("Added:"), text
    [(eid, page)] = _books(memory).items()
    assert not [c for c in parse_claims(page.body) if c.predicate == books.STATUS_PREDICATE]
    assert [w["label"] for w in books.book_card(memory, eid)["ways"]] == [books.AGENT_WORDS]
    [ep] = [f for f in (memory / "episodes").glob("*.md")
            if (markdown_parser.parse(f).frontmatter or {}).get("origin") == "book-scan"]
    assert markdown_parser.parse(ep).frontmatter["book"]["status"] is None
    # a repeat changes nothing
    assert "Already in memory" in str(mcp_tools.add_book(make(memory), PAPERBACK, False))
    assert len(_books(memory)) == 1


def test_a_stdio_call_goes_to_the_homes_generic_door_and_falls_back_to_staging(client):
    _, memory, _ = client
    seen = []
    def post(path, payload):
        seen.append((path, payload))
        return {"text": "Added: Home answered.", "code": None, "error": None}
    assert str(mcp_tools.add_book(_stdio_ctx(memory, post), PAPERBACK, False)) == "Added: Home answered."
    assert seen[0][0] == "/tools/call" and seen[0][1]["tool"] == "cicada_add_book" and not _books(memory)

    def down(path, payload):
        raise OSError("down")
    text = str(mcp_tools.add_book(_stdio_ctx(memory, down), PAPERBACK, False))
    assert "is queued" in text and not _books(memory)       # staged only; the next apply makes the page
    assert "was already requested" in str(mcp_tools.add_book(_stdio_ctx(memory, down), PAPERBACK, False))


def test_a_bad_number_is_refused(client):
    _, memory, _ = client
    assert "not a book's ISBN" in str(mcp_tools.add_book(_home_ctx(memory), "1234567890123", False))


def test_the_tool_is_on_every_door():
    assert "cicada_add_book" in remote_tools.REMOTE_TOOLS if hasattr(remote_tools, "REMOTE_TOOLS") else True
    assert catalog.TOOL_SCOPE["cicada_add_book"] == "record" and "cicada_add_book" in catalog.WRITE_TOOLS
    assert "cicada_add_book" not in catalog.NEVER_REMOTE
    assert "cicada_add_book" in remote_runtime.SELF_ADMITTED and "cicada_add_book" in tool_door.DISPATCH
    assert cli_map.by_tool()["cicada_add_book"].mutates
