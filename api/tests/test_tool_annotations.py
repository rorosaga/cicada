"""Every tool says whether it only reads, from one list (2026-10-23).

The live test found Codex asking for approval on every ``cicada_continue`` (and ``codex exec`` refusing it outright):
the stdio server annotated only the remote connector's ``READ_TOOLS``, which leaves out the stdio-only reads. The one
list is now the tool table's own ``mutates`` flag (``cli_map.read_only_tools()``); these tests hold every stdio tool,
the remote definitions and the remote catalog's two sets to it, and make sure no write is ever marked read-only.

Synthetic: no bank, no backend.
"""
from __future__ import annotations

from _stdio_server import stdio_server
from api.remote import catalog
from api.remote import tools as remote_tools
from api.services import cli_map

#: Tools that change something a person relies on — the bank, the inbox, a queue lease, their agent folders. Named
#: here by hand so a flag flipped in the table by mistake fails a test, not a person's memory.
KNOWN_WRITES = frozenset({
    "cicada_save_episode", "cicada_write_claim", "cicada_retract_claim", "cicada_note_progress", "cicada_edit_page",
    "cicada_add_source", "cicada_change_source", "cicada_save_url", "cicada_record_watch", "cicada_video_claim",
    "cicada_explore_claim", "cicada_mark_processed", "cicada_resolve_inbox", "cicada_add_backlog_item",
    "cicada_add_backlog_note", "cicada_save_design", "cicada_create_skill", "cicada_propose_skill",
})
#: Stdio-only reads the live test needed unprompted (each body checked: it writes no bank, inbox or lease).
STDIO_ONLY_READS = frozenset({"cicada_continue", "cicada_repo_context", "cicada_pending", "cicada_design_search"})


def _stdio_tools() -> dict[str, dict]:
    return {t["name"]: t for t in stdio_server().TOOLS}


def test_every_stdio_tool_is_classified_once():
    tools = _stdio_tools()
    table = cli_map.by_tool()
    assert set(tools) == set(table), "a stdio tool with no row in cli_map has no read/write classification"


def test_every_stdio_tool_annotation_matches_whether_it_writes():
    reads = cli_map.read_only_tools()
    for name, tool in _stdio_tools().items():
        hint = (tool.get("annotations") or {}).get("readOnlyHint")
        if name in reads:
            assert hint is True, f"{name} only reads but does not say so"
        else:
            assert hint is not True, f"{name} writes but is marked read-only"


def test_known_writes_are_writes_and_the_stdio_reads_are_reads():
    reads = cli_map.read_only_tools()
    assert not (KNOWN_WRITES & reads), sorted(KNOWN_WRITES & reads)
    assert STDIO_ONLY_READS <= reads, sorted(STDIO_ONLY_READS - reads)
    assert STDIO_ONLY_READS <= catalog.NEVER_REMOTE   # the reason the remote list missed them


def test_the_remote_door_agrees_with_the_one_list():
    reads = cli_map.read_only_tools()
    stdio = set(cli_map.by_tool())
    assert catalog.READ_TOOLS <= reads
    assert not (catalog.WRITE_TOOLS & reads)
    for definition in remote_tools.REMOTE_TOOLS.values():
        name = definition["name"]
        read_only = definition["annotations"]["read_only_hint"]
        if name in stdio:
            assert read_only == (name in reads), name
        else:   # a remote-only tool (relayed capture) is a write
            assert name in catalog.REMOTE_ONLY and read_only is False, name
