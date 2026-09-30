"""G166 — the two reading tools' scopes over all 63 scope sets: `read` gates the
queue, `record` gates recording; the remote schemas never name the other tool
(different scopes); and, with agent reading on, the remote primer names each
tool only where the connection holds it."""
from __future__ import annotations

import re
from itertools import combinations

import pytest

from api.remote import catalog, tools as remote_tools
from api.services import handshake

SUBSETS = [frozenset(c) for n in range(1, len(catalog.SCOPES) + 1) for c in combinations(catalog.SCOPES, n)]
TOKEN = re.compile(r"cicada_[a-z_]+")


def test_the_scopes_and_kinds():
    assert catalog.TOOL_SCOPE["cicada_reading_queue"] == "read"
    assert catalog.TOOL_SCOPE["cicada_record_read"] == "record"
    assert "cicada_reading_queue" in catalog.READ_TOOLS and "cicada_reading_queue" not in catalog.WRITE_TOOLS
    assert "cicada_record_read" in catalog.WRITE_TOOLS and "cicada_record_read" not in catalog.READ_TOOLS


@pytest.mark.parametrize("scopes", SUBSETS, ids=lambda s: "+".join(sorted(s)))
def test_read_gates_the_queue_and_record_gates_recording(scopes):
    names = catalog.tool_names_for(scopes)
    assert ("cicada_reading_queue" in names) == ("read" in scopes)
    assert ("cicada_record_read" in names) == ("record" in scopes)


def test_neither_remote_description_names_the_other_tool():
    queue = remote_tools.REMOTE_TOOLS["cicada_reading_queue"]
    record = remote_tools.REMOTE_TOOLS["cicada_record_read"]
    assert "cicada_record_read" not in str(queue) and "cicada_reading_queue" not in str(record)
    assert queue["annotations"]["read_only_hint"] is True
    assert record["annotations"]["read_only_hint"] is False and record["annotations"]["open_world_hint"] is True
    assert record["inputSchema"]["required"] == ["url", "outcome"]
    assert record["inputSchema"]["properties"]["outcome"]["enum"] == [
        "read", "needs_login", "blocked", "not_found", "failed"]


@pytest.mark.parametrize("scopes", SUBSETS, ids=lambda s: "+".join(sorted(s)))
def test_the_reading_primer_names_a_tool_only_where_it_is_held(scopes):
    names = catalog.tool_names_for(scopes)
    on = handshake.build_remote(None, tools=names, bank="memory", reading=True)
    off = handshake.build_remote(None, tools=names, bank="memory", reading=False)
    assert "Reading pages for the person" not in off
    held = {t for t in TOKEN.findall(on) if t.startswith(("cicada_reading", "cicada_record_read"))}
    assert held <= {t for t in ("cicada_reading_queue", "cicada_record_read") if t in names}
    both = {"cicada_reading_queue", "cicada_record_read"} & names
    assert ("Reading pages for the person" in on) == bool(both)
    assert all(t in on for t in both)
