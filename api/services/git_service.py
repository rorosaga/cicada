import asyncio
import re
from datetime import date
from pathlib import Path

from api.models.schemas import (
    Contributor,
    ContributorCommit,
    EntityDiff,
    EntityHistoryEntry,
    SleepHistoryEntry,
)


class GitError(Exception):
    pass


# Commit-author trailer (backlog A2). Every Cicada write records which agent
# authored it as one or more ``Cicada-Author:`` lines in the commit body — a
# model id (e.g. "gpt-5.4-mini") for sleep-cycle/agent writes, or "user" for
# manual/companion-app writes. The trailer is machine-parseable and inert to
# the existing entity-line parsing (it carries no entity id), so it does not
# break ``_infer_change_type`` / ``_build_description``.
AUTHOR_TRAILER = "Cicada-Author"
_AUTHOR_RE = re.compile(rf"^{AUTHOR_TRAILER}:\s*(.+?)\s*$")
UNKNOWN_AUTHOR = "unknown"

# A git object name is 7-40 hex chars. We validate any *caller-supplied* commit
# hash against this before handing it to git so a flag-like value (e.g.
# "--output=/tmp/x") can never be parsed by git as an option (arg injection ->
# arbitrary file write). Matches the blame-hash regex used internally below.
_COMMIT_HASH_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

# Hard cap on diff lines returned per side so one giant rewrite can't produce an
# unbounded response (the per-commit diff is also inlined once per commit when
# history is fetched with include_diff=True). A truncation marker is appended
# and ``EntityDiff.truncated`` is set when the cap is hit.
DIFF_MAX_LINES = 400
_DIFF_TRUNCATION_MARKER = "... [diff truncated]"

# Hard cap on a contributor-commit listing, so a caller-supplied `limit` can't
# ask for the entire history of a bank with thousands of Sleep cycles.
MAX_CONTRIBUTOR_COMMITS = 200


def build_commit_message(
    subject: str,
    body_lines: list[str],
    authors: list[str] | None = None,
) -> str:
    """Assemble a structured commit message with optional author trailers.

    ``subject`` is line 1, ``body_lines`` are the per-file manifest, and each
    distinct, non-empty ``authors`` entry becomes one ``Cicada-Author:`` trailer
    appended after a blank line (git-trailer convention). Author order is
    preserved and duplicates are dropped.
    """
    parts = [subject]
    if body_lines:
        parts.append("\n".join(body_lines))

    seen: set[str] = set()
    trailers: list[str] = []
    for a in authors or []:
        name = (a or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        trailers.append(f"{AUTHOR_TRAILER}: {name}")
    if trailers:
        parts.append("\n".join(trailers))

    return "\n\n".join(parts)


def _parse_authors(body: str) -> list[str]:
    """Extract author names from ``Cicada-Author:`` trailer lines in a commit body."""
    out: list[str] = []
    seen: set[str] = set()
    for line in body.splitlines():
        m = _AUTHOR_RE.match(line.strip())
        if m:
            name = m.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


# --- G15: contributor visual identity (kind / provider / avatar) ------------

# The literal "user" author (manual/companion-app/media-save writes).
USER_AUTHOR = "user"

# Model-id -> provider classification. We key on stable id substrings/prefixes
# (provider level, not per-model). LiteLLM-style "provider/model" ids are
# handled because the substring still appears (e.g. "anthropic/claude-...").
#
# These markers are distinctive enough to be safe as bare substring matches.
_PROVIDER_SUBSTRINGS = (
    ("openai", ("gpt", "text-embedding")),
    ("anthropic", ("claude",)),
    ("google", ("gemini", "gemma")),
)

# OpenAI o-series markers are too short to match as bare substrings (they would
# false-positive on ids like "macro1"/"retro3"). They must match only as an
# anchored token: the whole id, a prefix ("o1-..."), or a hyphen-/slash-delimited
# token ("openai/o1-pro").
_OPENAI_O_SERIES = ("o1", "o3")


def _classify_author_kind(author: str) -> str:
    """Bucket an author into "user" | "model" | "unknown" for the UI."""
    if author == USER_AUTHOR:
        return "user"
    if author == UNKNOWN_AUTHOR:
        return "unknown"
    return "model"


def _provider_for_model(author: str) -> str | None:
    """Derive the provider for a model id; None for user/unknown (not models).

    Matches by lower-cased substring/prefix against the known provider markers;
    any unmatched model id is "other".
    """
    if _classify_author_kind(author) != "model":
        return None
    a = author.lower()
    for provider, markers in _PROVIDER_SUBSTRINGS:
        if any(marker in a for marker in markers):
            return provider
    # o-series: anchored token match only (whole id / prefix / delimited token),
    # so "macro1"/"retro3" do not misclassify as OpenAI.
    if any(re.search(rf"(?:^|[/-]){re.escape(m)}(?:$|[/-])", a) for m in _OPENAI_O_SERIES):
        return "openai"
    return "other"


def _github_handle_from_remote_url(url: str | None) -> str | None:
    """Extract the GitHub owner handle from an origin remote URL, else None.

    Handles both ``https://github.com/<owner>/<repo>(.git)`` and
    ``git@github.com:<owner>/<repo>(.git)``. Returns None for non-GitHub or
    unparseable URLs — never raises.
    """
    if not url:
        return None
    text = url.strip()
    m = re.search(r"github\.com[:/]+([^/]+)/", text)
    if not m:
        return None
    handle = m.group(1).strip()
    return handle or None


async def _origin_github_handle(memory_path: Path) -> str | None:
    """Best-effort GitHub owner handle from the repo's ``origin`` remote.

    Never raises: a missing remote / non-git dir / non-GitHub origin all yield
    None so avatar derivation degrades cleanly to "no avatar".
    """
    try:
        url = await _run_git(memory_path, "remote", "get-url", "origin")
    except GitError:
        return None
    return _github_handle_from_remote_url(url.strip())


def _user_avatar_url(handle: str | None) -> str | None:
    """GitHub profile-picture URL for a handle (the user-contributor avatar)."""
    handle = (handle or "").strip().lstrip("@")
    if not handle:
        return None
    return f"https://github.com/{handle}.png"


async def _run_git(memory_path: Path, *args: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(memory_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        # cwd missing (e.g. a bank/memory dir not yet scaffolded) -> treat like
        # "no git history" rather than crashing the caller.
        raise GitError(f"git {' '.join(args)} failed: {exc}") from exc
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {stderr.decode(errors='replace')}")
    # ``errors="replace"`` so a non-UTF-8 entity file (porcelain blame embeds the
    # raw file bytes) degrades gracefully instead of raising a 500.
    return stdout.decode(errors="replace")


async def get_entity_history(
    entity_id: str,
    memory_path: Path,
    *,
    include_diff: bool = False,
) -> list[EntityHistoryEntry]:
    """Build entity history from git blame — field-level provenance grouped by commit.

    Each entry carries the authoring agent (from the commit's ``Cicada-Author:``
    trailer; "unknown" when absent) and the commit hash. When ``include_diff`` is
    set, each entry also carries the per-commit add/remove diff for this entity
    file (opt-in so the default response stays small — backlog A1).
    """
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
        authors = _parse_authors(body)
        author = authors[0] if authors else UNKNOWN_AUTHOR

        diff = None
        if include_diff:
            diff = await get_entity_commit_diff(entity_id, commit_hash, memory_path)

        entries.append(EntityHistoryEntry(
            date=date,
            change_type=change_type,
            description=description,
            author=author,
            commit_hash=commit_hash,
            diff=diff,
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


async def get_entity_commit_diff(
    entity_id: str, commit_hash: str, memory_path: Path
) -> EntityDiff:
    """Per-commit add/remove diff for one entity file (backlog A1).

    Returns an empty diff (not an error) when the commit is missing or the file
    didn't change in it — callers render "no diff" rather than failing.

    ``commit_hash`` is validated against ``_COMMIT_HASH_RE`` before reaching git:
    a non-hex / flag-like value (e.g. ``--output=/tmp/x``) is rejected here, so it
    can never be parsed by ``git show`` as an option (arg-injection guard). The
    ``--end-of-options`` token is also passed so a future hex-only edge can't be
    treated as a flag. Output is bounded by ``DIFF_MAX_LINES`` per side.
    """
    if not _COMMIT_HASH_RE.match(commit_hash):
        return EntityDiff(added="", removed="", truncated=False)

    entity_file = f"entities/{entity_id}.md"
    try:
        out = await _run_git(
            memory_path,
            "show",
            "--format=",
            "--no-color",
            "--unified=0",
            "--end-of-options",
            commit_hash,
            "--",
            entity_file,
        )
    except GitError:
        return EntityDiff(added="", removed="", truncated=False)

    added: list[str] = []
    removed: list[str] = []
    truncated = False
    for line in out.splitlines():
        # Skip diff headers (+++/---) and hunk markers (@@).
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            if len(added) >= DIFF_MAX_LINES:
                truncated = True
                continue
            added.append(line[1:])
        elif line.startswith("-"):
            if len(removed) >= DIFF_MAX_LINES:
                truncated = True
                continue
            removed.append(line[1:])

    if truncated:
        if added:
            added.append(_DIFF_TRUNCATION_MARKER)
        if removed:
            removed.append(_DIFF_TRUNCATION_MARKER)

    return EntityDiff(
        added="\n".join(added),
        removed="\n".join(removed),
        truncated=truncated,
    )


async def get_contributors(
    memory_path: Path, *, github_user: str | None = None
) -> list[Contributor]:
    """Repo-wide attribution summary parsed from ``Cicada-Author:`` trailers.

    For each author (model id, "user", or "unknown" for legacy untrailered
    commits) aggregate: commit count, distinct files + entities touched, and the
    most recent commit date. Each contributor also carries a visual identity
    (G15): ``kind`` (user/model/unknown), ``provider`` (model company, or None),
    and ``avatar_url`` (the user's GitHub profile picture, or None). The user
    avatar handle is ``github_user`` if given, else derived from the repo's
    ``origin`` remote. Returns ``[]`` on a non-git / missing directory.
    """
    if not (memory_path / ".git").exists():
        return []

    # NUL-record-delimited log so multi-line bodies never collide with the
    # field separator: hash <US> date <US> body <RS-record>.
    sep = "\x1f"
    rec = "\x1e"
    try:
        out = await _run_git(
            memory_path,
            "log",
            f"--format=%H{sep}%ad{sep}%b{rec}",
            "--date=short",
        )
    except GitError:
        return []

    # author -> aggregation state
    agg: dict[str, dict] = {}

    for record in out.split(rec):
        record = record.strip("\n")
        if not record.strip():
            continue
        fields = record.split(sep, 2)
        if len(fields) < 3:
            continue
        commit_hash, date, body = fields[0].strip(), fields[1].strip(), fields[2]

        authors = _parse_authors(body) or [UNKNOWN_AUTHOR]

        # Files changed in this commit (best-effort).
        try:
            names_out = await _run_git(
                memory_path,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "--root",  # so the initial (parentless) commit lists its added files
                commit_hash,
            )
            files = [f for f in names_out.strip().splitlines() if f]
        except GitError:
            files = []

        for author in authors:
            state = agg.setdefault(
                author,
                {"commits": 0, "files": set(), "entities": set(), "last": ""},
            )
            state["commits"] += 1
            for f in files:
                state["files"].add(f)
                if f.startswith("entities/") and f.endswith(".md"):
                    state["entities"].add(f)
            if date > state["last"]:
                state["last"] = date

    # Resolve the user-avatar handle once (explicit setting wins; else origin
    # remote), and only pay the git remote lookup if there's actually a `user`
    # contributor to show an avatar for.
    user_handle = (github_user or "").strip() or None
    if user_handle is None and USER_AUTHOR in agg:
        user_handle = await _origin_github_handle(memory_path)
    user_avatar = _user_avatar_url(user_handle)

    contributors = []
    for author, s in agg.items():
        kind = _classify_author_kind(author)
        contributors.append(
            Contributor(
                author=author,
                commit_count=s["commits"],
                file_count=len(s["files"]),
                entity_count=len(s["entities"]),
                files=sorted(s["files"]),
                last_active=s["last"],
                kind=kind,
                provider=_provider_for_model(author),
                avatar_url=user_avatar if kind == "user" else None,
            )
        )
    # Most active first; stable tie-break by author name.
    contributors.sort(key=lambda c: (-c.commit_count, c.author))
    return contributors


async def get_contributor_commits(
    memory_path: Path, author: str, *, limit: int = 50
) -> list[ContributorCommit]:
    """The commits one author wrote, newest first (G67 §2.2).

    Reuses the NUL-record ``git log`` + ``_parse_authors`` plumbing from
    :func:`get_contributors`, with ``--name-only`` folded into the SAME call so
    the listing costs one git invocation rather than one per commit. Records are
    ``hash <US> date <US> subject <US> body <US>`` followed by a blank line and
    the changed paths; ``git log --name-only`` lists the root (parentless)
    commit's files too, so no ``--root`` dance is needed.

    An author of ``"unknown"`` matches legacy untrailered commits. Returns ``[]``
    for a non-git dir, a blank author, or an author with no commits — the app
    renders an empty state, never an error.
    """
    author = (author or "").strip()
    if not author or not (memory_path / ".git").exists():
        return []

    limit = max(1, min(int(limit or 50), MAX_CONTRIBUTOR_COMMITS))
    sep = "\x1f"
    rec = "\x1e"
    try:
        out = await _run_git(
            memory_path,
            "log",
            f"--format={rec}%H{sep}%ad{sep}%s{sep}%b{sep}",
            "--date=short",
            "--name-only",
        )
    except GitError:
        return []

    commits: list[ContributorCommit] = []
    for record in out.split(rec):
        if not record.strip():
            continue
        fields = record.split(sep, 4)
        if len(fields) < 5:
            continue
        commit_hash, date_str, subject, body, tail = fields

        if author not in (_parse_authors(body) or [UNKNOWN_AUTHOR]):
            continue

        files = [line.strip() for line in tail.splitlines() if line.strip()]
        entities = sorted(
            {
                f[len("entities/"):-len(".md")].rsplit("/", 1)[-1]
                for f in files
                if f.startswith("entities/") and f.endswith(".md")
            }
        )
        commits.append(
            ContributorCommit(
                commit_hash=commit_hash.strip(),
                date=date_str.strip(),
                subject=subject.strip(),
                entities=entities,
                files_changed=len(files),
            )
        )
        if len(commits) >= limit:
            break

    return commits


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
        subj = subject.lower()
        if subj.startswith("sleep cycle") or subj.startswith("inbox resolution"):
            # Get changed files for this commit
            try:
                diff_output = await _run_git(
                    memory_path,
                    "diff-tree", "--no-commit-id", "--name-only", "-r",
                    "--root",  # so the initial (parentless) commit lists its files
                    commit_hash,
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


async def commit_changes(memory_path: Path, message: str) -> str | None:
    """Stage all changes and commit. Returns the new commit hash, or ``None``
    when there was nothing to commit."""
    await _run_git(memory_path, "add", "-A")
    # Check if there's anything to commit first
    status = await _run_git(memory_path, "status", "--porcelain")
    if not status.strip():
        return None  # Nothing to commit
    await _run_git(memory_path, "commit", "-m", message)
    return (await _run_git(memory_path, "rev-parse", "HEAD")).strip()


async def commit_paths(memory_path: Path, message: str, paths: list[str]) -> None:
    """Stage and commit ONLY ``paths`` (memory-relative), never ``git add -A``.

    A targeted write (adding a fact source, deferring one inbox item) must not
    sweep unrelated dirty files in ``memory/`` into its commit — that would
    attribute someone else's change to this action's trigger and author.
    """
    if not paths:
        return
    await _run_git(memory_path, "add", "--", *paths)
    status = await _run_git(memory_path, "status", "--porcelain", "--", *paths)
    if not status.strip():
        return  # Nothing to commit
    await _run_git(memory_path, "commit", "-m", message, "--", *paths)


async def porcelain_status(memory_path: Path) -> str:
    """Return ``git status --porcelain`` output (or empty on error)."""
    try:
        return await _run_git(memory_path, "status", "--porcelain")
    except GitError:
        return ""


async def commit_resolution(
    memory_path: Path,
    entity_id: str,
    trigger: str,
    extra_lines: list[str] | None = None,
) -> None:
    """Commit after an inbox (nudge/clarification/conflict) resolution.

    Emits a structured "Inbox resolution <date>" subject so the resolution
    surfaces in ``get_sleep_history`` (the Sleep dashboard) — the old
    single-line subject was never matched by the history filter. ``extra_lines``
    appends further per-file manifest lines (G60: one per closed claim's page).
    """
    date_str = date.today().isoformat()
    # trigger is "inbox/<kind>/resolved" — tag the kind into the subject so the
    # dashboard can distinguish a conflict adjudication from a decay archive.
    kind = ""
    parts = trigger.split("/")
    if len(parts) >= 2 and parts[0] == "inbox":
        kind = parts[1]
    subject = (
        f"Inbox resolution ({kind}) {date_str}" if kind
        else f"Inbox resolution {date_str}"
    )
    body_lines = [f"entities/{entity_id}.md: updated (trigger: {trigger})"]
    # The manifest is a SET of file lines: a caller that closes N claims on one
    # page must not repeat that page's line N times.
    for line in extra_lines or []:
        if line not in body_lines:
            body_lines.append(line)
    # An inbox resolution is a user/companion-app action -> attribute to "user".
    message = build_commit_message(subject, body_lines, authors=["user"])
    await commit_changes(memory_path, message)
