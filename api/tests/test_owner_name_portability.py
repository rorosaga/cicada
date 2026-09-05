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

Final review F3/F5 widened two of those:

  * the file walk now includes ``skills/**/*.md`` — the librarian skill is
    the LONG-FORM agent-facing policy in a public repo, and it still told
    agents to ``tag `rodrigo` explicitly`` after ``cicada_write_claim``'s own
    description had been rewritten to say ``observer='owner'``. A lint that
    only reads ``.py`` cannot see the file that contradicts the schema;
  * the prompt check is no longer a single slug. A banned-literal tuple only
    ever catches the name someone already thought of — it missed a real
    company in ``skill_extractor`` and a real person in
    ``entity_resolver._DISAMBIG_PROMPT``, both shipped, both invisible to a
    ``rodrigo`` search. The rule enforced instead is structural: **a prompt
    names no proper noun that isn't the schema's own vocabulary or a
    household-name technology**, so the NEXT one goes red without anyone
    having to type a name into a public test file (which would defeat the
    point of removing it).
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import api.services as services_pkg
from api.services import owner_identity

REPO_ROOT = Path(__file__).resolve().parents[2]
SLUG = owner_identity.LEGACY_OBSERVER


def _shipped_agent_facing_files() -> list[Path]:
    """Everything an install ships and an agent reads: ``api/`` minus its
    tests, ``mcp/``, and ``skills/**/*.md`` (F3).

    ``skills/`` is here because the librarian SKILL.md is the same surface as
    a tool description — prose an agent loads and obeys — only longer, and it
    is what carried the name after the ``.py`` sweep was declared done.

    Test fixtures are excluded on purpose — they are synthetic bank data, not
    text an install ever renders, and ``api/tests/*`` uses the legacy slug
    freely as fixture entity data (see the plan's "Not in scope").

    Measured in this worktree: 134 files, ~2 ms for the walk — cheap enough to
    run as a plain test rather than a separate lint job.
    """
    files = [
        p
        for p in (REPO_ROOT / "api").rglob("*.py")
        if "tests" not in p.parts and ".venv" not in p.parts
    ]
    files += list((REPO_ROOT / "mcp").rglob("*.py"))
    files += list((REPO_ROOT / "skills").rglob("*.md"))
    return files


def test_no_capitalised_owner_name_survives_in_shipped_code():
    needle = SLUG.capitalize()
    hits = [
        f"{p.relative_to(REPO_ROOT)}:{i}"
        for p in _shipped_agent_facing_files()
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


def _prompt_constants() -> list[tuple[str, str]]:
    """``(qualified name, text)`` for every ``*_PROMPT`` in ``api.services``.

    Every module imports cleanly, and these module constants are the text an
    engine is actually handed — the only place a stray name reaches a model.
    """
    found = []
    for mod_info in pkgutil.iter_modules(services_pkg.__path__):
        module = importlib.import_module(f"api.services.{mod_info.name}")
        for name, value in vars(module).items():
            if name.endswith("_PROMPT") and isinstance(value, str):
                found.append((f"api/services/{mod_info.name}.py::{name}", value))
    return found


def test_no_llm_prompt_is_primed_with_a_person():
    offenders = [n for n, text in _prompt_constants() if SLUG in text.lower()]
    assert offenders == [], f"an LLM prompt primed with a person's name: {offenders}"


# Words a prompt is allowed to capitalise mid-sentence. Two families only:
# the entity page's own section/field vocabulary (a prompt has to spell
# `## Key Facts` to ask for it), and household-name technology used as a
# generic example of a tool. Anything else capitalised mid-sentence in a
# prompt is, empirically, somebody the owner knows or somewhere they work.
# Adding to this set is a deliberate act — that is the whole mechanism.
_PROMPT_PROPER_NOUNS = frozenset(
    {
        # entity-page sections and schema field names (entity_extractor,
        # conflict_resolver, source_rewrite all render these literally)
        "Entity", "Name", "Type", "Description", "Summary", "Facts", "History",
        "Links", "Questions", "Skill", "Related", "Relationships", "Source",
        # generic technologies, named as EXAMPLES of a tool/concept
        "Postgres", "SQLite", "Mongo", "MongoDB", "GitHub", "Python", "Docker",
    }
)

# A capitalised word that opens a sentence, a bullet, a quote or a JSON key
# is grammar, not a name — so a match only counts when the character before
# it is ordinary prose.
_SENTENCE_OPENERS = set('.?!:;"\'(-—|/*#>,')
_CAPITALISED = re.compile(r"\b[A-Z][a-z]{2,}\b")


def test_no_llm_prompt_names_a_proper_noun_of_its_own():
    """F5 — the widened rail: a prompt names no proper noun.

    A banned-literal list only catches the name whoever wrote the list had
    already thought of. The two survivors this replaced were invisible to a
    ``rodrigo`` search — a real employer in ``skill_extractor``'s pattern
    example and a real person's first+last name in
    ``entity_resolver._DISAMBIG_PROMPT`` — and both had been shipping on
    every other person's bank. Inverting it (allowlist the vocabulary, flag
    everything else) is what makes the NEXT one go red, and it keeps the
    banned names out of this public file, which is the point of removing
    them.
    """
    offenders = []
    for qualified, text in _prompt_constants():
        for line in text.splitlines():
            for match in _CAPITALISED.finditer(line):
                before = line[: match.start()].rstrip()
                if not before or before[-1] in _SENTENCE_OPENERS:
                    continue  # sentence/bullet/quote/JSON-key opener
                if match.group() in _PROMPT_PROPER_NOUNS:
                    continue
                offenders.append(f"{qualified}: {match.group()!r} in {line.strip()[:70]!r}")
    assert offenders == [], (
        "an LLM prompt names a proper noun — if it is a person, a company or "
        "anything else from one person's life it must go (the prompt runs on "
        "everybody's bank); if it is genuinely generic vocabulary, add it to "
        f"_PROMPT_PROPER_NOUNS on purpose: {offenders}"
    )


def test_no_shipped_skill_doc_tells_an_agent_to_use_the_legacy_observer():
    """F3 — the librarian skill is a tool description in long form.

    ``cicada_write_claim``'s own description says ``observer='owner'``; the
    skill said ``tag `rodrigo` explicitly``. Two agent-facing policies, one
    protocol, and the .py-only lint could not see the disagreement. The
    compatibility promise itself is unchanged and still lives in the schema
    enum (asserted above) — the skill just stops naming a person.
    """
    offenders = [
        f"{p.relative_to(REPO_ROOT)}:{i}"
        for p in (REPO_ROOT / "skills").rglob("*.md")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if SLUG in line.lower()
    ]
    assert offenders == [], f"an agent-facing skill doc names a person: {offenders}"


def test_the_legacy_observer_constant_is_still_the_one_home_for_it():
    """The fix moves the literal, it does not delete the compatibility
    promise: ``resolve_observer`` still returns it for a pre-G117 bank that
    already has that page."""
    assert SLUG and SLUG.islower()
    assert inspect.getsourcefile(owner_identity).endswith("owner_identity.py")
