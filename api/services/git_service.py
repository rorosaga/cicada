import asyncio
import re
from pathlib import Path

from api.models.schemas import EntityHistoryEntry, SleepHistoryEntry


class GitError(Exception):
    pass


async def _run_git(memory_path: Path, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(memory_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {stderr.decode()}")
    return stdout.decode()


async def get_entity_history(entity_id: str, memory_path: Path) -> list[EntityHistoryEntry]:
    """Build entity history from git blame — field-level provenance grouped by commit."""
    entity_file = f"entities/{entity_id}.md"
    entity_path = memory_path / entity_file

    if not entity_path.exists():
        return []

    # git blame with porcelain format for structured parsing
    try:
        blame_output = await _run_git(
            memory_path, "blame", "--porcelain", entity_file
        )
    except GitError:
        return []

    # Extract unique commit hashes from blame output
    commit_hashes: list[str] = []
    seen: set[str] = set()
    for line in blame_output.splitlines():
        match = re.match(r"^([0-9a-f]{40})\s", line)
        if match:
            h = match.group(1)
            if h not in seen and not h.startswith("0000000"):
                seen.add(h)
                commit_hashes.append(h)

    # For each unique commit, get date + structured message
    entries: list[EntityHistoryEntry] = []
    for commit_hash in commit_hashes:
        try:
            log_output = await _run_git(
                memory_path,
                "log", "-1", f"--format=%ad|%s|%b", "--date=short", commit_hash,
            )
        except GitError:
            continue

        line = log_output.strip()
        if not line:
            continue

        parts = line.split("|", 2)
        date = parts[0] if len(parts) > 0 else ""
        subject = parts[1] if len(parts) > 1 else ""
        body = parts[2] if len(parts) > 2 else ""

        change_type = _infer_change_type(subject, body, entity_id)
        description = _build_description(subject, body, entity_id)

        entries.append(EntityHistoryEntry(
            date=date,
            change_type=change_type,
            description=description,
        ))

    return entries


def _infer_change_type(subject: str, body: str, entity_id: str) -> str:
    """Infer change type from structured commit message."""
    combined = f"{subject} {body}".lower()

    # Check for entity-specific lines in commit body
    entity_line = ""
    for line in body.splitlines():
        if entity_id in line.lower():
            entity_line = line.lower()
            break

    if "created" in entity_line or "created" in combined and "initial" in combined.lower():
        return "created"
    if "status" in entity_line:
        return "statusChange"
    if "confidence" in entity_line:
        return "confidenceChange"
    if "relation" in entity_line or "related" in entity_line:
        return "relationAdded"
    return "updated"


def _build_description(subject: str, body: str, entity_id: str) -> str:
    """Build a human-readable description from commit message."""
    # Look for entity-specific line in body
    for line in body.splitlines():
        if entity_id in line.lower():
            return line.strip()
    return subject


async def get_sleep_history(memory_path: Path) -> list[SleepHistoryEntry]:
    """Get chronological Sleep cycle history from git log."""
    try:
        output = await _run_git(
            memory_path,
            "log", "--format=%H|%ad|%s", "--date=short",
        )
    except GitError:
        return []

    entries: list[SleepHistoryEntry] = []
    for line in output.strip().splitlines():
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        commit_hash, date, subject = parts
        if subject.lower().startswith("sleep cycle"):
            # Get changed files for this commit
            try:
                diff_output = await _run_git(
                    memory_path,
                    "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash,
                )
                files = [f for f in diff_output.strip().splitlines() if f]
            except GitError:
                files = []

            entries.append(SleepHistoryEntry(
                commit_hash=commit_hash,
                date=date,
                message=subject,
                files_changed=files,
            ))

    return entries


async def commit_changes(memory_path: Path, message: str) -> None:
    """Stage all changes and commit."""
    await _run_git(memory_path, "add", "-A")
    # Check if there's anything to commit first
    status = await _run_git(memory_path, "status", "--porcelain")
    if not status.strip():
        return  # Nothing to commit
    await _run_git(memory_path, "commit", "-m", message)


async def porcelain_status(memory_path: Path) -> str:
    """Return ``git status --porcelain`` output (or empty on error)."""
    try:
        return await _run_git(memory_path, "status", "--porcelain")
    except GitError:
        return ""


async def commit_resolution(memory_path: Path, entity_id: str, trigger: str) -> None:
    """Commit after a nudge/clarification resolution."""
    await commit_changes(
        memory_path,
        f"entities/{entity_id}.md: updated (trigger: {trigger})",
    )
