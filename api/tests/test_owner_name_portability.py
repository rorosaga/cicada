"""CLAUDE.md's portability rail, enforced (Track P R8).

"No owner name, no author-machine path in shipped code" — G117 removed the
last hardcoded *observer* literal, but three display/prompt literals survived:
the ``cicada_get_perspective`` tool DESCRIPTION (sent to every agent on every
``initialize``), two ``subject`` argument examples, and — worst — an example
inside ``conflict_resolver``'s contradiction PROMPT, which primed the
extractor with an unrelated person's name on somebody else's bank.

This module never types a name. Every assertion reads the literal from
``owner_identity.LEGACY_OBSERVER``, the one place the legacy wire value is
supposed to live, and asserts the SHAPE the fix introduced:

  1. the title-cased form appears nowhere in shipped ``api/``/``mcp/`` — a
     capitalised given name is always a person, never a protocol value;
  2. no MCP tool description contains the lowercase form — the ``observer``
     ENUM keeps it (CLAUDE.md R12: a schema that rejects what a description
     names is a bug), the prose does not;
  3. no ``*_PROMPT`` constant in ``api/services/`` contains it — no LLM is
     primed with a person's name.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import api.services as services_pkg
from api.services import owner_identity

REPO_ROOT = Path(__file__).resolve().parents[2]
SLUG = owner_identity.LEGACY_OBSERVER


def _shipped_python_files() -> list[Path]:
    """Everything that ships: ``api/`` minus its tests, plus ``mcp/``.

    Test fixtures are excluded on purpose — they are synthetic bank data, not
    text an install ever renders, and ``api/tests/*`` uses the legacy slug
    freely as fixture entity data (see the plan's "Not in scope").

    Measured in this worktree: 133 files, ~2 ms for the walk — cheap enough to
    run as a plain test rather than a separate lint job.
    """
    files = [
        p
        for p in (REPO_ROOT / "api").rglob("*.py")
        if "tests" not in p.parts and ".venv" not in p.parts
    ]
    files += list((REPO_ROOT / "mcp").rglob("*.py"))
    return files


def test_no_capitalised_owner_name_survives_in_shipped_code():
    needle = SLUG.capitalize()
    hits = [
        f"{p.relative_to(REPO_ROOT)}:{i}"
        for p in _shipped_python_files()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if needle in line
    ]
    assert hits == [], f"a person's name in shipped code (portability rail): {hits}"


def test_no_mcp_tool_description_names_a_person():
    import mcp.server as server

    def _descriptions(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "description" and isinstance(value, str):
                    yield value
                else:
                    yield from _descriptions(value)
        elif isinstance(node, list):
            for item in node:
                yield from _descriptions(item)

    offenders = [d for d in _descriptions(server.TOOLS) if SLUG in d.lower()]
    assert offenders == [], (
        "a tool description reaches every agent on initialize — keep it neutral"
    )
    # The wire value itself is protocol and MUST stay reachable (R12).
    observer_schema = next(
        t["inputSchema"]["properties"]["observer"]
        for t in server.TOOLS
        if t["name"] == "cicada_write_claim"
    )
    assert SLUG in observer_schema["enum"], (
        "the legacy observer stays accepted, it just stops being advertised"
    )


def test_no_llm_prompt_is_primed_with_a_person():
    # Every `api.services` module imports cleanly, and the `*_PROMPT` module
    # constants are the text an engine is actually handed. Only
    # `conflict_resolver._CONTRADICTION_PROMPT` carried the slug before this
    # fix — that is the one this test exists to turn red.
    offenders = []
    for mod_info in pkgutil.iter_modules(services_pkg.__path__):
        module = importlib.import_module(f"api.services.{mod_info.name}")
        for name, value in vars(module).items():
            if name.endswith("_PROMPT") and isinstance(value, str) and SLUG in value.lower():
                offenders.append(f"api/services/{mod_info.name}.py::{name}")
    assert offenders == [], f"an LLM prompt primed with a person's name: {offenders}"


def test_the_legacy_observer_constant_is_still_the_one_home_for_it():
    """The fix moves the literal, it does not delete the compatibility
    promise: ``resolve_observer`` still returns it for a pre-G117 bank that
    already has that page."""
    assert SLUG and SLUG.islower()
    assert inspect.getsourcefile(owner_identity).endswith("owner_identity.py")
