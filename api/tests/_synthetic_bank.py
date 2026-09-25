"""Shared synthetic bank for the G53/G75 tests — never collected by pytest
(underscore prefix), imported by sibling test files as `from _synthetic_bank
import …` (`api/tests` has no `__init__.py`, so pytest's rootdir-prepend
import mode puts this directory on `sys.path`). Every name here is a
placeholder (alpha-project, bob-example, example.com); nothing reads a real
bank, `~/.cicada`, or the network."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from api.services import markdown_parser, predicates


def _entity(memory: Path, eid: str, **fm):
    body = fm.pop("body", f"## Summary\n{eid.replace('-', ' ').title()} is a synthetic fixture.\n")
    base = {"name": eid.replace("-", " ").title(), "type": "concept", "status": "active",
            "confidence": 0.5, "created": "2026-01-01", "last_referenced": "2026-09-01",
            "decay_rate": 0.05, "source_episodes": [], "tags": [], "related": [], "version": 1}
    base.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", base, body)


def _bank(tmp_path: Path, *, git: bool = True) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox", "hubs"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    _entity(memory, "alpha-project", type="project", confidence=0.9, last_referenced="2026-09-02",
            repos=[{"path": "~/src/alpha-project", "default_branch": "main"}])
    _entity(memory, "beta-project", type="project", confidence=0.4, last_referenced="2026-03-01")
    _entity(memory, "gamma-project", type="project", status="archived", confidence=0.9)
    _entity(memory, "bob-example", type="person", confidence=0.8, last_referenced="2026-09-01")
    _entity(memory, "concise-summaries", type="skill", confidence=0.7, decay_class="durable",
            body="## Summary\nPrefers concise summaries over long reports.\n")
    markdown_parser.write(memory / "episodes" / "ep_2026-09-01_001.md",
                          {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T09:00:00+00:00",
                           "processed": False, "session_id": "ses_2026-09-01_abcd1234",
                           "harness": "codex", "title": "Planning alpha"}, "user: plan alpha")
    markdown_parser.write(memory / "episodes" / "ep_2026-09-02_001.md",
                          {"id": "ep_2026-09-02_001", "timestamp": "2026-09-02T09:00:00+00:00",
                           "processed": True, "session_id": "11111111-2222-4333-8444-555555555555",
                           "harness": "claude-code", "project_dir": "/tmp/alpha",
                           "title": "Shipping alpha"}, "user: ship alpha")
    markdown_parser.write(memory / "inbox" / "inbox-001.md",
                          {"kind": "decay", "status": "pending", "entity_id": "beta-project",
                           "entity_name": "Beta Project", "title": "Still tracking Beta?",
                           "created_date": "2026-08-01"}, "ctx")
    markdown_parser.write(memory / "inbox" / "inbox-002.md",
                          {"kind": "conflict", "status": "pending", "entity_id": "alpha-project",
                           "entity_name": "Alpha Project", "title": "Which db?", "remind_after": "2099-01-01",
                           "created_date": "2026-08-01"}, "ctx")
    if git:
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "t"], ["add", "."],
                     ["commit", "-q", "-m", "Sleep cycle 2026-09-02\n\nentities/alpha-project.md: updated (source: n/a, trigger: sleep/extraction)\n\nCicada-Author: cicada"]):
            subprocess.run(["git", "-C", str(memory), *args], check=True, capture_output=True)
    return memory


def _settings(memory: Path, **over):
    base = dict(memory_path=memory, llm_mode="byok", litellm_model="gpt-5.4-mini",
                consolidation_model="", agent_model="sonnet", ollama_model="llama3.1",
                state_projects=7, state_people=7, state_preferences=5, state_conversations=5)
    base.update(over)
    ns = SimpleNamespace(**base)
    ns.effective_consolidation_model = (ns.consolidation_model or "").strip() or ns.litellm_model
    return ns


def _ok_repo(decl, *, timeout_s=2.0):
    return {"path": decl["path"], "status": "ok", "current_branch": "feat/x", "dirty_files": 2,
            "ahead": 1, "behind": 0, "worktrees": [], "last_commit": None}
