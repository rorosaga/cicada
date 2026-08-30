"""G60 — one-shot startup collapse of already-written duplicate open items."""

from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import inbox_migration, markdown_parser


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init_memory(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    (repo / "inbox").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    return repo


def _conflict(repo: Path, item_id: str, created: str, labels: list[str]) -> None:
    markdown_parser.write(
        repo / "inbox" / f"{item_id}.md",
        {
            "kind": "conflict",
            "required_input": "choice",
            "status": "pending",
            "priority": 0.8,
            "entity_id": "rodrigo-sagastegui",
            "entity_name": "Rodrigo Sagastegui",
            "title": "Conflicting beliefs about Rodrigo Sagastegui",
            "created_date": created,
            "predicate": "works-at",
            "options": [
                {"key": chr(ord("a") + i), "label": label, "observed_at": "2026-02-18",
                 "last_referenced": "2026-02-18"}
                for i, label in enumerate(labels)
            ],
        },
        "Conflicting beliefs.",
    )


def test_dedup_collapses_duplicates_into_the_oldest_and_commits(tmp_path):
    repo = _init_memory(tmp_path)
    _conflict(repo, "inbox-011", "2026-06-18", ["mongodb", "supahost"])
    _conflict(repo, "inbox-042", "2026-07-02", ["mongodb", "acme"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    removed = inbox_migration.dedup_open_items(repo)

    assert removed == 1
    remaining = sorted(p.stem for p in (repo / "inbox").glob("inbox-*.md"))
    assert remaining == ["inbox-011"], "the OLDEST item survives"

    fm = markdown_parser.parse(repo / "inbox" / "inbox-011.md").frontmatter
    assert [o["label"] for o in fm["options"]] == ["mongodb", "supahost", "acme"]
    assert fm["created_date"] == "2026-06-18"

    log = _git(repo, "log", "--format=%s%n%b")
    assert "inbox/dedup" in log
    assert "Cicada-Author: cicada" in log


def test_dedup_is_idempotent_and_marker_short_circuits(tmp_path):
    repo = _init_memory(tmp_path)
    _conflict(repo, "inbox-011", "2026-06-18", ["mongodb"])
    _conflict(repo, "inbox-042", "2026-07-02", ["supahost"])
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    assert inbox_migration.dedup_open_items(repo) == 1
    assert (repo / "inbox" / ".deduped").exists()
    assert inbox_migration.dedup_open_items(repo) == 0


def test_dedup_leaves_distinct_keys_and_resolved_items_alone(tmp_path):
    repo = _init_memory(tmp_path)
    _conflict(repo, "inbox-001", "2026-06-18", ["mongodb"])
    markdown_parser.write(
        repo / "inbox" / "inbox-002.md",
        {"kind": "conflict", "status": "pending", "entity_id": "rodrigo-sagastegui",
         "predicate": "uses", "created_date": "2026-06-19", "options": []},
        "other predicate",
    )
    markdown_parser.write(
        repo / "inbox" / "inbox-003.md",
        {"kind": "conflict", "status": "resolved", "entity_id": "rodrigo-sagastegui",
         "predicate": "works-at", "created_date": "2026-06-20", "options": []},
        "already resolved",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    assert inbox_migration.dedup_open_items(repo) == 0
    assert len(list((repo / "inbox").glob("inbox-*.md"))) == 3


def test_dedup_never_raises_on_a_non_repo(tmp_path):
    plain = tmp_path / "no-git"
    (plain / "inbox").mkdir(parents=True)
    _conflict(plain, "inbox-001", "2026-06-18", ["mongodb"])
    _conflict(plain, "inbox-002", "2026-06-19", ["supahost"])
    # Files still collapse on disk; only the commit is skipped.
    assert inbox_migration.dedup_open_items(plain) == 1
