"""Track B review — the one-shot collapse of already-written decay duplicates."""

from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import bank_migrations, inbox_migration, markdown_parser


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init(tmp_path: Path) -> Path:
    repo = tmp_path / "memory"
    (repo / "inbox").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    return repo


def _decay(repo, item_id, entity, created, priority, claim_id=None, status="pending"):
    fm = {"kind": "decay", "status": status, "entity_id": entity, "entity_name": entity,
          "priority": priority, "created_date": created}
    if claim_id:
        fm["claim_id"] = claim_id
    markdown_parser.write(repo / "inbox" / f"{item_id}.md", fm, "still tracking?")


def _seed(repo):
    _decay(repo, "inbox-001", "alpha-tool", "2026-06-01", 0.38, "clm_1")
    _decay(repo, "inbox-002", "alpha-tool", "2026-06-02", 0.33, "clm_2")
    _decay(repo, "inbox-003", "alpha-tool", "2026-06-03", 0.31)
    _decay(repo, "inbox-004", "beta-tool", "2026-06-03", 0.35)
    _decay(repo, "inbox-005", "alpha-tool", "2026-06-04", 0.30, status="resolved")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")


def test_decay_piles_collapse_into_the_oldest_and_keep_every_claim(tmp_path):
    repo = _init(tmp_path)
    _seed(repo)

    assert inbox_migration.dedup_decay_items(repo) == 2

    left = sorted(p.stem for p in (repo / "inbox").glob("inbox-*.md"))
    assert left == ["inbox-001", "inbox-004", "inbox-005"], "resolved items are never touched"
    fm = markdown_parser.parse(repo / "inbox" / "inbox-001.md").frontmatter
    assert fm["created_date"] == "2026-06-01" and fm["claim_id"] == "clm_1"
    assert fm["claim_ids"] == ["clm_2"]
    assert fm["priority"] == 0.31, "the most decayed reading is kept"
    log = _git(repo, "log", "--format=%s%n%b")
    assert "inbox/dedup" in log and "Cicada-Author: cicada" in log


def test_it_runs_after_the_general_dedup_marker_and_is_idempotent(tmp_path):
    repo = _init(tmp_path)
    _seed(repo)
    (repo / "inbox" / ".deduped").write_text("v1")     # an older bank: G60's dedup already ran
    assert inbox_migration.dedup_decay_items(repo) == 2
    assert (repo / "inbox" / ".deduped_decay").exists()
    assert inbox_migration.dedup_decay_items(repo) == 0


def test_bank_migrations_runs_it(tmp_path):
    repo = _init(tmp_path)
    _seed(repo)
    assert bank_migrations.run_bank_migrations(repo)["deduped"] == 2
    assert bank_migrations.run_bank_migrations(repo)["deduped"] == 0
