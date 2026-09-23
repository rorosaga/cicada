"""Track I (R-IA13) — one-shot, idempotent: stamp ``origin`` on chat-export
episodes written before every import path stamped it.

``POST /conversations/upload`` — the ``+`` sheet's and the upload overlay's path
until Track I — never set ``origin`` (R7 §1.2 defect 1). Those episodes sit in the
Sources page's ``origin:unknown`` bucket ("Unattributed"), and Sleep derived
``claude-code`` for them, stamping a claude.ai export's claims as Claude Code's.
A read-time fallback would have to be taught separately to every reader that keys
on ``origin`` (the overview, ``/origins``, the conversations list, the Sleep
queue); markdown is the source of truth (ruling 3), so the file is fixed once.

Scope, exactly: an episode with NO ``origin``, NO ``session_id`` (a live
conversation is never an import), and a ``source`` only the chat importer writes.
Nothing else is touched — not ``processed``, not the body, not ``content_hash`` —
so nothing re-queues for Sleep and no evidence span moves. Marker-guarded, commit
scoped to exactly the rewritten paths, ``Cicada-Author: cicada`` — the
``decay_migration`` shape. Claims already consolidated keep the origin they were
stamped with (claim origin carries no trust weight; rewriting claims is out of
scope). Never raises.
"""
from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import git_service, markdown_parser

#: The chat importer's own ``source`` values -> the export they came from.
IMPORTER_ORIGINS = {
    "claude": "claude-export",
    "claude_memory": "claude-export",
    "claude_project": "claude-export",
    "chatgpt": "chatgpt-export",
    "gemini_export": "gemini-export",
}
_MARKER = ".export_origins_v1"
TRIGGER = "maintenance/export_origin_backfill"


def backfill_export_origins(memory_path) -> int:
    """Stamp one bank. Returns how many episodes were rewritten."""
    memory_path = Path(memory_path)
    episodes_dir = memory_path / "episodes"
    if not episodes_dir.exists():
        return 0
    marker = memory_path / _MARKER
    if marker.exists():
        return 0
    try:
        written = _rewrite(episodes_dir)
    except Exception as e:
        logger.error(f"Export-origin backfill FAILED — leaving episodes/ untouched: {e}")
        return 0
    if written:
        try:
            _commit(memory_path, written)
        except Exception as e:
            # Files are right on disk but uncommitted (or this bank is not a
            # git repo). No marker, so the next boot re-scans; it finds nothing
            # left to stamp and writes the marker, and the stamped files ride
            # the bank's next commit — the same trade `decay_migration` makes,
            # because a bank without git must still get its origins.
            logger.warning(f"Export-origin backfill commit skipped: {e}")
            return len(written)
    marker.write_text("v1", encoding="utf-8")
    return len(written)


def _rewrite(episodes_dir: Path) -> list[Path]:
    written: list[Path] = []
    for path in sorted(episodes_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        if not isinstance(fm, dict) or fm.get("origin") or fm.get("session_id"):
            continue
        origin = IMPORTER_ORIGINS.get(str(fm.get("source") or "").strip().lower())
        if not origin:
            continue
        fm["origin"] = origin
        markdown_parser.write(path, fm, parsed.body)
        written.append(path)
    return written


def _commit(memory_path: Path, written: list[Path]) -> None:
    rel = [str(p.relative_to(memory_path)) for p in written]
    subprocess.run(["git", "add", "--", *rel], cwd=str(memory_path), check=True)
    status = subprocess.run(["git", "status", "--porcelain", "--", *rel], cwd=str(memory_path),
                            check=True, capture_output=True, text=True)
    if not status.stdout.strip():
        return
    message = git_service.build_commit_message(
        f"Backfill export origins {date.today().isoformat()}",
        [f"episodes/: {len(rel)} chat-export episode(s) stamped with their origin (trigger: {TRIGGER})"],
        authors=["cicada"],
    )
    subprocess.run(["git", "commit", "-m", message, "--", *rel], cwd=str(memory_path), check=True)
