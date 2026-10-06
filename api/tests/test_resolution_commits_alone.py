"""Audit 2026-10-05 P1-3: an inbox resolution commits only what it touched.

`commit_resolution` ran `git add -A`, so answering one question committed
every unrelated dirty file in the bank — an episode a stdio agent saved, a
hand edit on another page — under `Cicada-Author: user`. And an uncommitted
edit already on the page the answer rewrites was folded into the person's
commit. CLAUDE.md's rail: a write that commits commits alone, under its true
author. Synthetic banks only (`alpha-project`, `bob-example`).
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from api.models.schemas import InboxResolveRequest
from api.services import inbox_service, markdown_parser
from api.services.claims import Claim, write_claims


class _Settings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.litellm_disambiguation_model = ""
        self.consolidation_model = ""
        self.llm_mode = "byok"

    @property
    def effective_consolidation_model(self) -> str:
        return self.litellm_model


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _bank(tmp_path: Path) -> Path:
    repo = tmp_path / "bank"
    for sub in ("entities", "inbox", "episodes"):
        (repo / sub).mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    for eid in ("alpha-project", "beta-project"):
        markdown_parser.write(repo / "entities" / f"{eid}.md",
                              {"name": eid, "type": "project", "status": "decaying", "confidence": 0.3},
                              f"## Summary\n{eid} is a project.\n")
    markdown_parser.write(repo / "inbox" / "inbox-001.md", {
        "kind": "decay", "required_input": "choice", "status": "pending", "entity_id": "alpha-project",
        "entity_name": "alpha-project", "created_date": "2026-09-01"}, "Still working on alpha-project?")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _resolve(repo: Path, item: str, **req) -> dict:
    return asyncio.run(inbox_service.resolve(item, InboxResolveRequest(**req), _Settings(repo)))


def _answer(repo: Path) -> str:
    """The resolution's own commit (`_state.md`'s refresh commits after it, alone)."""
    return _git(repo, "log", "-1", "--format=%H", "--grep=^Inbox resolution").strip()


def _files(repo: Path, rev: str | None = None) -> list[str]:
    return sorted(_git(repo, "show", "--name-only", "--format=", rev or _answer(repo)).split())


def test_an_answer_never_commits_an_unrelated_dirty_file(tmp_path):
    repo = _bank(tmp_path)
    (repo / "episodes" / "ep_2026-10-05_001.md").write_text("---\nid: ep_2026-10-05_001\n---\nuser: hi\n")
    beta = repo / "entities" / "beta-project.md"
    beta.write_text(beta.read_text() + "\nA hand edit.\n")

    assert _resolve(repo, "inbox-001", action="archive")["status"] == "resolved"

    assert _files(repo) == ["entities/alpha-project.md", "inbox/inbox-001.md"]
    assert "Cicada-Author: user" in _git(repo, "log", "-1", "--format=%B", _answer(repo))
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    assert "episodes/ep_2026-10-05_001.md" in status and "entities/beta-project.md" in status
    assert "alpha-project" not in status and "inbox-001" not in status


def test_an_edit_already_on_the_page_is_kept_apart_not_attributed_to_the_person(tmp_path):
    repo = _bank(tmp_path)
    page = repo / "entities" / "alpha-project.md"
    page.write_text(page.read_text() + "\nSomeone's uncommitted note.\n")

    _resolve(repo, "inbox-001", action="archive")

    # The person's commit holds only the answer…
    rev = _answer(repo)
    answer = _git(repo, "show", rev, "--", "entities/alpha-project.md")
    assert "status: archived" in answer and "uncommitted note" not in answer
    assert "Cicada-Author: user" in _git(repo, "log", "-1", "--format=%B", rev)
    # …and the edit that was already there is its own commit, with no author claimed for it.
    kept = _git(repo, "log", "-1", "--format=%B", f"{rev}~1")
    assert "Cicada-Author" not in kept
    assert "uncommitted note" in _git(repo, "show", f"{rev}~1", "--", "entities/alpha-project.md")
    assert _files(repo, f"{rev}~1") == ["entities/alpha-project.md"]
    assert not _git(repo, "status", "--porcelain")
    assert "uncommitted note" in page.read_text() and "status: archived" in page.read_text()


def test_a_merge_answer_commits_every_page_it_rewrote_and_nothing_else(tmp_path):
    repo = _bank(tmp_path)
    ents = repo / "entities"
    markdown_parser.write(ents / "alpha-tool-build.md", {"name": "alpha tool build", "type": "tool"},
                          write_claims("## Summary\nThe build.\n",
                                       [Claim(id="c1", text="uses x", subject="alpha-tool-build",
                                              predicate="uses", object="x")]))
    markdown_parser.write(ents / "alpha-tool.md", {"name": "alpha tool", "type": "tool"}, "## Summary\nThe tool.\n")
    markdown_parser.write(ents / "gamma.md", {"name": "gamma", "type": "project", "related": ["alpha-tool-build"]},
                          "Uses [[alpha-tool-build]].\n")
    markdown_parser.write(repo / "inbox" / "inbox-002.md", {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "entity_name": "alpha tool",
        "entity_id": "alpha-tool", "merge_target_hint": "alpha-tool-build", "created_date": "2026-09-01"}, "Dup?")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed 2")
    (repo / "episodes" / "ep_2026-10-05_002.md").write_text("---\nid: ep_2026-10-05_002\n---\nuser: hi\n")

    _resolve(repo, "inbox-002", action="merge", merge_target="alpha-tool-build", merge_survivor="alpha tool")

    assert _files(repo) == ["entities/alpha-tool-build.md", "entities/alpha-tool.md", "entities/gamma.md",
                            "inbox/inbox-002.md"]
    assert _git(repo, "status", "--porcelain", "--untracked-files=all").split() == [
        "??", "episodes/ep_2026-10-05_002.md"]


def test_a_conflict_answer_commits_its_page_and_item(tmp_path):
    repo = _bank(tmp_path)
    markdown_parser.write(repo / "entities" / "bob-example.md", {"name": "Bob", "type": "person"},
                          write_claims("Bob.\n", [
                              Claim(id="c_a", text="Bob works at A", subject="bob-example", predicate="works-at",
                                    object="a-co", valid_from="2026-02-18"),
                              Claim(id="c_b", text="Bob works at B", subject="bob-example", predicate="works-at",
                                    object="b-co", valid_from="2026-02-18")]))
    markdown_parser.write(repo / "inbox" / "inbox-003.md", {
        "kind": "conflict", "required_input": "choice", "status": "pending", "entity_id": "bob-example",
        "entity_name": "Bob", "predicate": "works-at", "created_date": "2026-09-01",
        "options": [{"key": "a", "label": "a-co", "claim_id": "c_a"},
                    {"key": "b", "label": "b-co", "claim_id": "c_b"}]}, "Where?")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed 3")
    (repo / "notes.md").write_text("unrelated\n")

    _resolve(repo, "inbox-003", action="resolve", option_key="a")

    assert _files(repo) == ["entities/bob-example.md", "inbox/inbox-003.md"]
    assert _git(repo, "status", "--porcelain", "--untracked-files=all").split() == ["??", "notes.md"]


def _rename_bank(tmp_path: Path) -> Path:
    repo = _bank(tmp_path)
    ents = repo / "entities"
    markdown_parser.write(ents / "alpha-tool-build.md", {"name": "alpha tool build", "type": "tool"},
                          "## Summary\nThe build.\n")
    markdown_parser.write(ents / "gamma.md", {"name": "gamma", "type": "project", "related": ["alpha-tool-build"]},
                          "Uses [[alpha-tool-build]].\n")
    markdown_parser.write(repo / "inbox" / "inbox-004.md", {
        "kind": "merge_suggestion", "required_input": "merge", "status": "pending", "entity_name": "alpha tool",
        "entity_id": "alpha-tool", "merge_target_hint": "alpha-tool-build", "created_date": "2026-09-01"}, "Dup?")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed rename")
    return repo


def test_a_rename_answer_commits_the_old_page_gone(tmp_path):
    repo = _rename_bank(tmp_path)
    _resolve(repo, "inbox-004", action="merge", merge_target="alpha-tool-build", merge_survivor="alpha tool")
    assert "entities/alpha-tool-build.md" in _files(repo)
    assert not _git(repo, "status", "--porcelain", "--untracked-files=all")
    tree = _git(repo, "ls-tree", "-r", "--name-only", "HEAD").split()
    assert "entities/alpha-tool.md" in tree and "entities/alpha-tool-build.md" not in tree


def test_a_rename_answer_keeps_an_edit_on_the_old_page_apart(tmp_path):
    repo = _rename_bank(tmp_path)
    old = repo / "entities" / "alpha-tool-build.md"
    old.write_text(old.read_text() + "\nA hand note.\n")
    _resolve(repo, "inbox-004", action="merge", merge_target="alpha-tool-build", merge_survivor="alpha tool")
    rev = _answer(repo)
    assert "Cicada-Author" not in _git(repo, "log", "-1", "--format=%B", f"{rev}~1")
    assert "A hand note." in _git(repo, "show", f"{rev}~1", "--", "entities/alpha-tool-build.md")
    assert "A hand note." in (repo / "entities" / "alpha-tool.md").read_text()
    assert not _git(repo, "status", "--porcelain", "--untracked-files=all")
