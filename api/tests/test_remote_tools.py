"""G135 R-R22 — the catalog is the stdio tool list partitioned exactly once, and
nothing a connection is told names a tool it lacks (G75 R12), for every one of
the 63 non-empty scope sets."""
from __future__ import annotations

import json
import re
from itertools import combinations
from pathlib import Path

import pytest

from _stdio_server import stdio_server
from api.remote import catalog, tools as remote_tools
from api.services import handshake

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "remote_catalog.json").read_text())
SUBSETS = [frozenset(c) for n in range(1, len(catalog.SCOPES) + 1) for c in combinations(catalog.SCOPES, n)]
TOKEN = re.compile(r"cicada_[a-z_]+")


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def test_the_catalog_matches_the_shared_fixture():
    assert [(a.id, a.harness, a.delivery) for a in catalog.APPS.values()] == [
        (a["id"], a["harness"], a["delivery"]) for a in FIXTURE["apps"]]
    assert list(catalog.SCOPES) == [s["id"] for s in FIXTURE["scopes"]]
    assert catalog.DEFAULT_SCOPES == {s["id"] for s in FIXTURE["scopes"] if s["default"]}


def test_every_stdio_tool_is_classified_exactly_once():
    stdio = {t["name"] for t in stdio_server().TOOLS}
    assert set(catalog.TOOL_SCOPE) | catalog.NEVER_REMOTE == stdio
    assert not set(catalog.TOOL_SCOPE) & catalog.NEVER_REMOTE
    assert set(remote_tools.REMOTE_TOOLS) == set(catalog.TOOL_SCOPE)


def test_an_empty_or_unknown_scope_set_reaches_nothing():
    assert catalog.tool_names_for(frozenset()) == frozenset()
    assert catalog.tool_names_for({"delete", "admin"}) == frozenset()
    assert catalog.clean_scopes(["search", "delete"]) == {"search"}


@pytest.mark.parametrize("scopes", SUBSETS, ids=lambda s: "+".join(sorted(s)))
def test_nothing_a_connection_is_told_names_a_tool_it_lacks(scopes):
    names = catalog.tool_names_for(scopes)
    defs = remote_tools.tool_defs_for(scopes)
    assert [d["name"] for d in defs] == [n for n in remote_tools.REMOTE_TOOLS if n in names]
    told: set[str] = set()
    for d in defs:
        told |= {t for s in _strings({k: v for k, v in d.items() if k != "name"}) for t in TOKEN.findall(s)}
    told |= set(TOKEN.findall(handshake.build_remote(None, tools=names, bank="memory")))
    assert told <= names, sorted(told - names)
    assert not told & catalog.NEVER_REMOTE


def test_the_schemas_hold_the_remote_rails():
    claim = remote_tools.REMOTE_TOOLS["cicada_write_claim"]["inputSchema"]["properties"]
    assert claim["observer"]["enum"] == ["agent", "external"]
    assert "answer" not in remote_tools.REMOTE_TOOLS["cicada_resolve_inbox"]["inputSchema"]["properties"]
    for name, d in remote_tools.REMOTE_TOOLS.items():
        props = d["inputSchema"]["properties"]
        assert ("conversation" in props) == (name != "cicada_handshake"), name
        assert d["annotations"]["destructive_hint"] is False
        assert d["annotations"]["read_only_hint"] == (name not in catalog.WRITE_TOOLS | {"cicada_resolve_inbox"})
