"""Track I (R-IA13) — the one-shot stamp for chat-export episodes the old
`/conversations/upload` path left without an `origin` (D4)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from api.services import export_origin_migration as mig
from api.services import markdown_parser, sleep_cycle


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _bank(tmp_path: Path) -> Path:
    repo = tmp_path / "bank"
    (repo / "episodes").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@cicada.local")
    _git(repo, "config", "user.name", "Cicada Test")
    rows = {
        "ep_2026-02-01_001": {"source": "claude", "processed": True},
        "ep_2026-02-01_002": {"source": "chatgpt", "processed": False},
        "ep_2026-02-01_003": {"source": "claude", "session_id": "3f1c", "processed": True},
        "ep_2026-02-01_004": {"source": "mcp", "processed": True},
        "ep_2026-02-01_005": {"source": "claude", "origin": "claude-export", "processed": True},
    }
    for eid, fm in rows.items():
        markdown_parser.write(repo / "episodes" / f"{eid}.md", {"id": eid, **fm}, "user: alpha-project")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    return repo


def _fm(repo, eid):
    return markdown_parser.parse(repo / "episodes" / f"{eid}.md").frontmatter


def test_only_origin_less_importer_episodes_are_stamped(tmp_path):
    repo = _bank(tmp_path)
    assert mig.backfill_export_origins(repo) == 2
    assert _fm(repo, "ep_2026-02-01_001")["origin"] == "claude-export"
    assert _fm(repo, "ep_2026-02-01_002")["origin"] == "chatgpt-export"
    assert _fm(repo, "ep_2026-02-01_002")["processed"] is False, "nothing re-queues"
    assert "origin" not in _fm(repo, "ep_2026-02-01_003"), "a live conversation is never an import"
    assert "origin" not in _fm(repo, "ep_2026-02-01_004")
    assert markdown_parser.parse(repo / "episodes" / "ep_2026-02-01_001.md").body == "user: alpha-project"


def test_the_commit_is_cicada_authored_and_holds_exactly_the_rewritten_files(tmp_path):
    repo = _bank(tmp_path)
    mig.backfill_export_origins(repo)
    assert "Cicada-Author: cicada" in _git(repo, "log", "-1", "--format=%B")
    assert sorted(_git(repo, "show", "--name-only", "--format=", "HEAD").split()) == [
        "episodes/ep_2026-02-01_001.md", "episodes/ep_2026-02-01_002.md"]


def test_it_runs_once(tmp_path):
    repo = _bank(tmp_path)
    mig.backfill_export_origins(repo)
    head = _git(repo, "rev-parse", "HEAD")
    assert mig.backfill_export_origins(repo) == 0
    assert _git(repo, "rev-parse", "HEAD") == head


def test_sleep_credits_the_importer_to_its_export_not_to_claude_code():
    """D4: `_derive_origin` stamps claims; `source: claude` is only ever the importer."""
    for source, origin in mig.IMPORTER_ORIGINS.items():
        assert sleep_cycle._derive_origin(source) == origin
    assert sleep_cycle._derive_origin("mcp") == "claude-code", "unchanged for live MCP episodes"
