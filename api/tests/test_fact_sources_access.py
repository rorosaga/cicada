"""G61 phase 2 S1 — sources that can be checked: the record's new fields, their
validation, access inferred at read, and the person's upsert (spec §5.1, plan
R-AC21, R-AC27, R-AC28). Synthetic names only."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models.schemas import EntitySourceCreate
from api.routers import entities as entities_router
from api.services import fact_sources, markdown_parser

TEAM = "https://example.com/staff-directory"


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


def _bank(tmp_path: Path, *, git: bool = False) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    markdown_parser.write(memory / "entities" / "bob-example.md",
                          {"name": "Bob Example", "type": "person", "status": "active"}, "## Summary\nx\n")
    if git:
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"],
                     ["add", "."], ["commit", "-q", "-m", "seed"]):
            subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True)
    return memory


def _only(memory: Path) -> list[dict]:
    return fact_sources.list_sources(memory, "bob-example")


def test_app_and_repo_are_kinds_a_caller_names(tmp_path):
    memory = _bank(tmp_path)
    fact_sources.add_source(memory, "bob-example", "Calendar", kind="app", predicate="works-at")
    fact_sources.add_source(memory, "bob-example", "~/src/alpha-project", kind="repo", predicate="runs-on")
    assert [(s["kind"], s["ref"]) for s in _only(memory)] == [("app", "Calendar"), ("repo", "~/src/alpha-project")]
    assert "access" not in _only(memory)[0], "access is stored only when someone states it"


@pytest.mark.parametrize("source, expected", [
    ({"ref": TEAM, "kind": "url"}, "unknown"),
    ({"ref": TEAM, "kind": "url", "access": "public"}, "public"),
    ({"ref": "https://www.linkedin.com/in/bob-example", "kind": "url"}, "signed_in"),
    ({"ref": "https://accounts.google.com/signin", "kind": "url"}, "signed_in"),
    ({"ref": "https://example.com/login", "kind": "url"}, "signed_in"),
    ({"ref": "https://arxiv.org/abs/2601.00001", "kind": "url"}, "signed_in"),
    ({"ref": "~/Documents/cv.pdf", "kind": "path"}, "local"),
    ({"ref": "~/src/alpha-project", "kind": "repo"}, "local"),
    ({"ref": "Calendar", "kind": "app"}, "signed_in"),
    ({"ref": "ask me — I announce job changes", "kind": "note"}, "unknown"),
    ({"ref": TEAM, "kind": "url", "access": "not-a-value"}, "unknown"),
])
def test_access_is_the_stated_value_else_inferred_at_read(source, expected):
    assert fact_sources.effective_access(source) == expected


def test_a_stated_access_never_unrefuses_a_host():
    source = {"ref": "https://www.linkedin.com/in/bob-example", "kind": "url", "access": "public"}
    assert fact_sources.effective_access(source) == "public"
    assert fact_sources.is_refused_host(source["ref"]) is True


@pytest.mark.parametrize("kwargs, message", [
    ({"kind": "website"}, "kind must be one of"),
    ({"access": "open"}, "access must be one of"),
    ({"access": "local"}, "access 'local' is for a path or a repo"),
    ({"only_me": True}, "only_me needs a predicate"),
])
def test_values_the_record_does_not_allow_are_refused(tmp_path, kwargs, message):
    memory = _bank(tmp_path)
    with pytest.raises(fact_sources.InvalidSource, match=message):
        fact_sources.add_source(memory, "bob-example", TEAM, **kwargs)
    assert _only(memory) == []


def test_an_over_long_ref_is_refused(tmp_path):
    memory = _bank(tmp_path)
    with pytest.raises(fact_sources.InvalidSource, match="at most 2,048"):
        fact_sources.add_source(memory, "bob-example", "https://example.com/" + "a" * 2048)


def test_the_persons_repeat_applies_their_fields_and_an_agents_never_does(tmp_path):
    memory = _bank(tmp_path)
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="claude-code")
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="gpt-5.4-mini",
                            access="public")
    assert "access" not in _only(memory)[0], "an agent's repeat never mutates an entry"
    fact_sources.add_source(memory, "bob-example", TEAM, predicate="works-at", added_by="user",
                            access="signed_in", accepted=True)
    entry = _only(memory)[0]
    assert (entry["added_by"], entry["access"], entry["accepted"]) == ("claude-code", "signed_in", True)
    fact_sources.add_source(memory, "bob-example", "https://example.com/mine", predicate="works-at",
                            added_by="user", accepted=True)
    assert "accepted" not in _only(memory)[1], "the person's own source needs no acceptance"


def test_only_me_is_the_persons_note_and_never_a_hint(tmp_path):
    memory = _bank(tmp_path)
    fact_sources.add_source(memory, "bob-example", "Only I know", predicate="works-at", only_me=True)
    fact_sources.add_source(memory, "bob-example", TEAM, added_by="user")
    fact_sources.add_source(memory, "bob-example", "Only an agent", predicate="located-in",
                            added_by="claude-code", only_me=True)
    listed = _only(memory)
    assert (listed[0]["kind"], listed[0]["only_me"]) == ("note", True)
    assert "only_me" not in listed[2], "only the person silences a fact"
    # "Only I know" silences the fact outright — no fallback to another
    # predicate's URL (G61 final review, finding 3); other facts still fall back.
    assert fact_sources.hint_from(listed, "works-at") is None
    assert fact_sources.hint_from(listed, "role") == f"You said {TEAM} is where to check this"


def test_only_me_silences_the_served_hint_even_over_a_stored_one(tmp_path):
    memory = _bank(tmp_path)
    fact_sources.add_source(memory, "bob-example", "https://example.com/where-bob-lives",
                            predicate="located-in", added_by="user")
    fact_sources.add_source(memory, "bob-example", "Only I know", predicate="works-at", only_me=True)
    listed = _only(memory)
    item = {"kind": "conflict", "predicate": "works-at",
            "hint": "You said https://example.com/old is where to check this"}
    assert fact_sources.served_hint(item, listed) is None
    assert fact_sources.served_hint({**item, "predicate": "located-in"}, listed) == \
        "You said https://example.com/where-bob-lives is where to check this"
    # An agent's only_me (hand-written past the upsert's clamp) silences nothing.
    agent = [{"ref": "x", "kind": "note", "predicate": "works-at", "added_by": "claude-code", "only_me": True}]
    assert fact_sources.served_hint(item, agent) == item["hint"]


def test_the_endpoint_takes_the_new_fields_and_answers_400(tmp_path):
    memory = _bank(tmp_path, git=True)
    settings = _Settings(memory)
    out = asyncio.run(entities_router.add_entity_source(
        "bob-example", EntitySourceCreate(ref=TEAM, predicate="works-at", access="public"), settings=settings))
    assert (out.sources[0].access, out.sources[0].accepted, out.sources[0].only_me) == ("public", False, False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(entities_router.add_entity_source(
            "bob-example", EntitySourceCreate(ref=TEAM, access="open"), settings=settings))
    assert exc.value.status_code == 400
