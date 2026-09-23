"""G75 R12, enforced for ARGUMENTS (G140 Q-R14): every `cicada_x(args)` a
primer names must be a tool the reader holds, and every argument it names
must be a property of that tool's schema — for the three local variants and
for all 63 remote scope sets. It found `cicada_recall_detail(id)` (the
property is `entity_id`)."""
from __future__ import annotations

import re
from itertools import combinations

import pytest

from _stdio_server import stdio_server
from _synthetic_bank import _bank, _ok_repo, _settings
from api.remote import catalog
from api.remote import tools as remote_tools
from api.services import handshake, state_dictionary

CALL = re.compile(r"`(cicada_[a-z_]+)\(([^`]*)\)`")
SUBSETS = [frozenset(c) for n in range(1, len(catalog.SCOPES) + 1) for c in combinations(catalog.SCOPES, n)]


def _args(arglist: str) -> list[str]:
    """Top-level argument names: `a, b=[{x, y}], c|d` → a, b, c, d. A quoted
    literal or `<placeholder>` names nothing."""
    parts, depth, current = [], 0, ""
    for ch in arglist:
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    names = []
    for part in parts:
        for alt in part.split("|"):
            m = re.match(r"\s*([a-z_]+)\s*(=|$)", alt)
            if m:
                names.append(m.group(1))
    return names


def _check(text: str, schemas: dict[str, set[str]]):
    for tool, arglist in CALL.findall(text):
        assert tool in schemas, tool
        for arg in _args(arglist):
            assert arg in schemas[tool], (tool, arg)


def test_every_argument_the_local_primer_names_is_in_the_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = _bank(tmp_path)
    state_dictionary.refresh(memory, _settings(memory), force=True, repo_resolver=_ok_repo)
    schemas = {t["name"]: set(t["inputSchema"].get("properties", {})) for t in stdio_server().TOOLS}
    for variant in handshake.VARIANTS:
        _check(handshake.build(state_dictionary.read_state(memory), variant=variant, bank="memory",
                               tz="Europe/Madrid"), schemas)


@pytest.mark.parametrize("scopes", SUBSETS, ids=lambda s: "+".join(sorted(s)))
def test_every_argument_a_remote_primer_names_is_in_its_schema(scopes):
    schemas = {n: set(d["inputSchema"]["properties"]) for n, d in remote_tools.REMOTE_TOOLS.items()}
    _check(handshake.build_remote(None, tools=catalog.tool_names_for(scopes), bank="memory"), schemas)


def test_the_parser_reads_nested_and_alternative_arguments():
    assert _args("subject, evidence=[{episode, quote}], sources=[url]") == ["subject", "evidence", "sources"]
    assert _args("entity_id|path") == ["entity_id", "path"] and _args("'projects'") == []
    assert _args("entity_ids=<recall ids>") == ["entity_ids"]
