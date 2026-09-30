"""G166 (owner 2026-09-30: "make sure to have this link to the skill in the memory graph and label it as a
skill accordingly") — an installed agent skill is a `type: skill` page tagged `agent-skill`, written only on
the person's own action, alone in one `user` commit, never confused with a procedural memory.

Synthetic bank; the catalog is the shipped one (the two harness skills)."""
from __future__ import annotations

import asyncio
import subprocess
from datetime import date, datetime, timedelta

import pytest

from _synthetic_bank import _bank, _entity
from api.models.schemas import AGENT_PRODUCIBLE_DECAY_CLASSES
from api.services import (
    conflict_resolver, decay_policy, demo_guard, entity_resolver, markdown_parser, skill_catalog, skill_extractor,
    skill_pages, sleep_cycle, state_dictionary,
)
from api.services.claims import parse_claims

CATALOG = skill_catalog.load()
ENTRY = next(e for e in CATALOG["skills"] if e["id"] == "browser-harness")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    return _bank(tmp_path)


def _git(memory, *args):
    return subprocess.run(["git", "-C", str(memory), *args], capture_output=True, text=True, check=True).stdout


def _page(memory, eid="browser-harness"):
    return markdown_parser.parse(memory / "entities" / f"{eid}.md")


def test_created_page_shape(memory):
    r = run(skill_pages.ensure(memory, "browser-harness", today=date(2026, 9, 30)))
    assert (r.state, r.entity_id) == ("created", "browser-harness")
    parsed = _page(memory)
    fm = parsed.frontmatter
    assert (fm["name"], fm["type"], fm["status"], fm["confidence"]) == ("browser-harness", "skill", "active", 1.0)
    assert fm["tags"] == ["agent-skill"] and fm["decay_class"] == "evergreen" and fm["decay_rate"] == 0.0
    assert fm["human_edited"] is True and fm["source_episodes"] == [] and fm["aliases"] == ["browser harness"]
    assert (fm["created"], fm["last_referenced"], fm["layout_version"], fm["version"]) == ("2026-09-30", "2026-09-30", 2, 1)
    # the Stage-1 create shape, plus the two keys this writer adds
    stage1 = {"name", "type", "status", "confidence", "created", "last_referenced", "decayed_through", "decay_class",
              "decay_rate", "source_episodes", "tags", "aliases", "related", "version", "layout_version"}
    assert set(fm) - stage1 == {"human_edited", "sources"}
    (source,) = fm["sources"]
    assert source["ref"] == ENTRY["sourceUrl"] and source["kind"] == "url" and source["added_by"] == "cicada"
    assert ENTRY["pageSummary"] in parsed.body and "Upstream repository" in parsed.body
    assert parse_claims(parsed.body) == [], "a labelled pointer: no claims to decay or conflict"
    assert "installed" not in str(fm).lower() and "not_installed" not in str(fm), "nothing machine-dependent is stored"


def test_ensure_is_idempotent_no_second_write_no_second_commit(memory):
    run(skill_pages.ensure(memory, "browser-harness"))
    path = memory / "entities" / "browser-harness.md"
    before, log = path.stat().st_mtime_ns, _git(memory, "log", "--oneline")
    again = run(skill_pages.ensure(memory, "browser-harness"))
    assert again.state == "exists" and path.stat().st_mtime_ns == before and _git(memory, "log", "--oneline") == log


def test_one_commit_alone_with_the_users_trailer(memory):
    (memory / "entities" / "alpha-project.md").write_text((memory / "entities" / "alpha-project.md").read_text() + "\nedit\n")
    run(skill_pages.ensure(memory, "browser-harness", today=date(2026, 9, 30)))
    msg = _git(memory, "log", "-1", "--format=%B")
    assert msg.splitlines()[0] == "Skill page browser-harness 2026-09-30"
    assert "entities/browser-harness.md: created (trigger: user/companion_app)" in msg and "Cicada-Author: user" in msg
    assert "Cicada-Engine" not in msg
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/browser-harness.md"]
    assert " M entities/alpha-project.md" in _git(memory, "status", "--porcelain"), "an unrelated dirty file stays out"


def test_failed_commit_removes_the_page_and_leaves_index_and_tree_clean(memory, monkeypatch):
    from api.services import git_service

    async def boom(memory_path, message, paths):
        git_service.commit_paths_sync.__wrapped__ if False else None
        subprocess.run(["git", "-C", str(memory_path), "add", "--", *paths], check=True)  # staged, then the commit fails
        raise RuntimeError("commit failed")

    monkeypatch.setattr(git_service, "commit_paths", boom)
    with pytest.raises(RuntimeError):
        run(skill_pages.ensure(memory, "browser-harness"))
    assert not (memory / "entities" / "browser-harness.md").exists()
    status = _git(memory, "status", "--porcelain")
    assert "browser-harness" not in status, "neither untracked nor staged: nothing to sweep into the next writer's commit"


def test_foreign_page_is_left_byte_identical(memory):
    _entity(memory, "browser-harness", type="person", body="## Summary\nSomeone with an odd name.\n")
    path = memory / "entities" / "browser-harness.md"
    before = path.read_bytes()
    r = run(skill_pages.ensure(memory, "browser-harness"))
    assert r.state == "foreign" and path.read_bytes() == before
    found = skill_pages.lookup(memory, ENTRY)
    assert (found.state, found.entity_id) == ("foreign", "browser-harness")
    # a page the person edited is foreign too, whatever its type
    _entity(memory, "macos-harness", type="tool", human_edited=True)
    assert run(skill_pages.ensure(memory, "macos-harness")).state == "foreign"
    _entity(memory, "claude-video", type="tool", body="## Summary\nA tool.\n\n## My notes\nhand written\n")
    assert run(skill_pages.ensure(memory, "watch")).state == "foreign", "a hand-added section reads as human-edited"


def test_adopt_retypes_an_agent_made_tool_page_and_keeps_claims(memory):
    from api.services import link_enrichment

    _entity(memory, "browser-harness", type="tool", decay_class="active", source_episodes=["ep_2026-09-01_001"],
            body="## Summary\nA browser automation harness the person mentioned.\n")
    path = memory / "entities" / "browser-harness.md"
    parsed = markdown_parser.parse(path)
    link_enrichment._append_claim(path, link_enrichment._build_describes_claim(
        "browser-harness", "It drives a browser.", "ep_2026-09-01_001", "2026-09-01", "test-model"))
    before_claims = parse_claims(markdown_parser.parse(path).body)
    r = run(skill_pages.ensure(memory, "browser-harness"))
    assert r.state == "adopted"
    fm = _page(memory).frontmatter
    assert fm["type"] == "skill" and "agent-skill" in fm["tags"] and fm["human_edited"] is True
    assert fm["decay_class"] == "evergreen" and fm["source_episodes"] == ["ep_2026-09-01_001"]
    assert [c.id for c in parse_claims(_page(memory).body)] == [c.id for c in before_claims], "every claim kept"
    assert "A browser automation harness the person mentioned." in _page(memory).body, "its prose is kept"
    assert "browser-harness.md: updated (trigger: user/companion_app)" in _git(memory, "log", "-1", "--format=%B")
    assert run(skill_pages.ensure(memory, "browser-harness")).state == "exists"


def test_busy_while_sleep_runs_and_demo_writes_nothing(memory, monkeypatch):
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: True)
    assert run(skill_pages.ensure(memory, "browser-harness")).state == "busy"
    assert not (memory / "entities" / "browser-harness.md").exists()
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: False)
    assert run(skill_pages.ensure(memory, "browser-harness")).state == "created", "the guard is the shared predicate"
    demo = memory.parent / "demo"
    (demo / "entities").mkdir(parents=True)
    demo_guard.write_manifest(demo)
    assert run(skill_pages.ensure(demo, "macos-harness")).state == "demo"
    assert not (demo / "entities" / "macos-harness.md").exists()


def test_a_skill_with_no_role_or_page_name_is_none(memory):
    assert run(skill_pages.ensure(memory, "pdf")).state == "none"
    assert run(skill_pages.ensure(memory, "no-such-skill")).state == "none"
    assert skill_pages.page_id(ENTRY) == "browser-harness"


def test_page_write_uses_the_shared_sleep_predicate(memory, monkeypatch):
    calls = []
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: calls.append(1) or False)
    run(skill_pages.ensure(memory, "macos-harness"))
    assert calls, "one shared predicate (G177: a drain holds `running` for hours, `is_writing` is the write window)"


# --- the graph treats it as a skill page but never as a working agreement -------------------------------------


@pytest.mark.parametrize("mention,direct", [
    ("browser-harness", True), ("Browser Harness", True), ("browser harness", True), ("browserharness", True),
    ("browser-use harness", True), ("the browser harness", False),
])
def test_stage2_matches_later_mentions(memory, mention, direct):
    """The page name is the hyphenated upstream name, so a later mention resolves to it instead of a
    `browser-harness-2`. 'the browser harness' ratios under the threshold and reaches the type-gated judge."""
    run(skill_pages.ensure(memory, "browser-harness"))
    existing = {"browser-harness": {"id": "browser-harness", "frontmatter": {"name": "browser-harness", "type": "skill"}}}
    got = entity_resolver._find_direct_candidate_match({"name": mention, "type": "tool"}, existing, {})
    assert (got is not None and got["candidate"]["id"] == "browser-harness") is direct


def test_a_later_mention_keeps_the_pointer_and_only_adds(memory):
    run(skill_pages.ensure(memory, "browser-harness"))
    before = _page(memory)
    original_summary = ENTRY["pageSummary"]
    change = {"id": "browser-harness", "action": "update", "source_episode": "ep_2026-09-30_001",
              "entity": {"name": "browser-harness", "type": "tool", "summary": "A different sentence a model wrote.",
                         "tags": ["automation"], "links": [{"title": "Elsewhere", "url": "https://blog.example.net/x"}]},
              "synthesized_body": "## Summary\nA REWRITTEN summary from an LLM synthesis call.\n"}
    conflict_resolver.apply_changes([change], memory)
    after = _page(memory)
    assert original_summary in after.body and "A REWRITTEN summary" not in after.body, "no synthesis on a human_edited page"
    assert "Upstream repository" in after.body and ENTRY["sourceUrl"] in after.body
    fm = after.frontmatter
    assert fm["type"] == "skill" and "agent-skill" in fm["tags"] and fm["decay_class"] == "evergreen"
    assert "ep_2026-09-30_001" in fm["source_episodes"] and fm["human_edited"] is True
    assert fm["version"] == before.frontmatter["version"] + 1


def test_agent_skill_pages_are_not_how_to_work_with_me(memory):
    run(skill_pages.ensure(memory, "browser-harness"))
    assert [r["id"] for r in state_dictionary._preferences(memory, 10)] == ["concise-summaries"]
    _entity(memory, "prefers-short", type="skill", decay_class="durable", tags=["communication-style"])
    ids = [r["id"] for r in state_dictionary._preferences(memory, 10)]
    assert "browser-harness" not in ids and "prefers-short" in ids


def test_agent_skill_pages_never_decay(memory):
    from datetime import datetime
    from types import SimpleNamespace

    run(skill_pages.ensure(memory, "browser-harness", today=date(2025, 1, 1)))
    fm = _page(memory).frontmatter
    eff = decay_policy.effective(fm)
    assert eff.decay_class is decay_policy.DecayClass.evergreen and eff.rate == 0.0
    assert decay_policy.resolve(fm) == (decay_policy.DecayClass.evergreen, 0.0)
    # many simulated weeks through the real pass: no archive, no nudge, no decay change
    _entity(memory, "control-page", type="concept", decay_class="volatile", last_referenced="2025-01-01",
            decayed_through="2025-01-01", confidence=0.9)
    existing = sleep_cycle._load_existing_entities(memory)
    settings = SimpleNamespace(archive_threshold=0.2, decay_nudge_threshold=0.4)
    for weeks in (4, 40, 400):
        changes = run(conflict_resolver.resolve_and_prune(
            [], existing, settings, now=datetime(2025, 1, 1) + timedelta(weeks=weeks), tuning={}))
        mine = [c for c in changes if c.get("id") == "browser-harness"]
        assert mine == [], (weeks, mine)
        assert [c for c in changes if c.get("id") == "control-page"], "the control page does decay: the test is not vacuous"


def test_only_the_router_imports_skill_pages_and_the_anti_pollution_rail_is_untouched():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    hits = []
    for path in list((root / "api").rglob("*.py")) + list((root / "mcp").rglob("*.py")):
        if "tests" in path.parts or path.name == "skill_pages.py":
            continue
        if re.search(r"^\s*(from api\.services import .*\bskill_pages\b|from api\.services\.skill_pages|import api\.services\.skill_pages)",
                     path.read_text(encoding="utf-8"), re.MULTILINE):
            hits.append(path.relative_to(root).as_posix())
    assert hits == ["api/routers/agent_methods.py"], "the person's own action is the only door (no Sleep step, no seed)"
    assert decay_policy.DecayClass.evergreen not in AGENT_PRODUCIBLE_DECAY_CLASSES


def test_stage4_related_list_skips_agent_skill_pages():
    existing = [
        {"id": "browser-harness", "frontmatter": {"name": "browser-harness", "type": "skill", "tags": ["agent-skill"]},
         "body": "An installed tool."},
        {"id": "prefers-short", "frontmatter": {"name": "prefers short", "type": "skill", "tags": []}, "body": "Short."},
    ]
    text = skill_extractor._format_existing(existing, [])
    assert "prefers short" in text and "browser-harness" not in text


def test_a_page_that_stage_one_made_first_is_adoptable_only_when_safe(memory):
    _entity(memory, "macos-harness", type="concept", picture={"kind": "initials", "added": "2026-09-01"})
    assert run(skill_pages.ensure(memory, "macos-harness")).state == "foreign", "a picture the person chose"
