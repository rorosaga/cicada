import asyncio
import re
from datetime import date
from pathlib import Path

from api.models.schemas import (
    Contributor,
    ContributorCommit,
    DiffLine,
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

# Conversation trailer (G48). A twin of ``Cicada-Author:`` recording WHICH
# CONVERSATION a write came from — a Claude Code session uuid, or G20's
# per-thread export id for an imported chat. Inert to the entity-line parsing
# by the same contract as the author trailer: it carries no entity id, so
# ``_infer_change_type`` / ``_build_description`` never see it.
SESSION_TRAILER = "Cicada-Session"
_SESSION_RE = re.compile(rf"^{SESSION_TRAILER}:\s*(.+?)\s*$")

# Engine trailer (G74(a) Task 6). Records WHICH ENGINE drove a Sleep commit —
# "claude-cli" | "ollama" | "litellm" — mirroring `/sleep/status`'s
# `lastEngine` field into the git history so `/sleep/history` can stop being
# the one place in the app "reflects what actually ran" (Ruling 4) never
# reached. Singular (one trailer, not a list like authors/sessions): a commit
# is driven by exactly one engine. Omitted entirely for a commit where no LLM
# engine ran at all (the `cicada`-authored decay-only commit, G85) — the
# honest absence, never a guessed value. Inert to the entity-line parsing by
# the same contract as the other two trailers: it carries no entity id.
#
# No Python-side `_parse_ENGINE_RE`/regex parser for this one (unlike
# authors/sessions): M1 review fix round 1 — `get_sleep_history` reads it
# straight out of `git log` via `%(trailers:key=Cicada-Engine,valueonly,…)`,
# so there is nothing left in this module that needs to scan a raw body for
# it. Verified against git 2.50.1: empty string (not an error) when the
# trailer is absent, one bare value with no key/prefix when present.
ENGINE_TRAILER = "Cicada-Engine"

# Cap on session trailers in ONE commit. `build_commit_message` does not cap —
# the call site does (sleep_cycle._collect_session_ids), so a caller that
# genuinely wants every id can have it. 50 distinct conversations consolidated
# in a single Sleep is effectively unreachable; when it happens, the trailer
# degrades (the click-through affordance loses the overflow) while
# `GET /conversations/recent` stays complete — it reads episodes, not commits.
MAX_SESSION_TRAILERS = 50

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

# How much unchanged context git is asked to include around each change (G69).
# "Generous" on purpose: an entity page is a few dozen lines of frontmatter +
# prose, so 4 lines either side is usually the whole neighbourhood a reader
# needs to see WHY a line changed, and hunks that come within 8 lines of each
# other coalesce into one.
DIFF_CONTEXT_LINES = 4

# Hard cap on the ORDERED ``lines`` list. Higher than DIFF_MAX_LINES because
# this list carries context and hunk headers too, not just the changed lines —
# a 400/400 change with 4 lines of context around every hunk is still well
# under this. When hit, the list is cut and ``lines_truncated`` is set.
DIFF_MAX_CONTEXT_LINES = 2000

# ``@@ -<old_start>[,<old_count>] +<new_start>[,<new_count>] @@[ heading]``.
# Matching this is also how the parser knows it has entered a hunk: everything
# before the first header (``diff --git``, ``index``, mode/``---``/``+++``
# lines) is skipped BY POSITION rather than by prefix, so a file line that
# legitimately begins with ``---`` or ``+++`` — YAML frontmatter fences! — is
# still treated as content.
_HUNK_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

# Hard cap on a contributor-commit listing, so a caller-supplied `limit` can't
# ask for the entire history of a bank with thousands of Sleep cycles.
MAX_CONTRIBUTOR_COMMITS = 200

# Cap on the entity ids carried by ONE ContributorCommit. A real Sleep cycle
# rewrites hundreds of pages (measured on the live bank: 895 entity files in
# one commit), and the app renders a tappable chip per id, so an uncapped list
# is both a fat payload and a multi-thousand-view layout pass. The full count
# still travels as `entities_total`, so the app can say "+N more".
MAX_COMMIT_ENTITIES = 12

# How far back `get_contributor_commits` is willing to walk.
#
# The listing filters on a `Cicada-Author:` trailer, and a rare author (e.g.
# the reserved `cicada` system author, one commit deep in history) can sit at
# ANY depth, so there is no depth at which the walk is provably complete. But
# `git log --name-only` materialises every commit's full file list before the
# Python loop can `break`, so an unbounded walk grows without limit with every
# Sleep cycle. This window is the bound: `min(window, ...)` commits are read,
# newest first, and an author whose commits are all older than it simply shows
# as having none in the drill-down (`GET /contributors` aggregates are computed
# separately and stay complete). Sized so a `limit=50` listing is still filled
# for an author holding as little as 5% of the recent history.
CONTRIBUTOR_LOG_WINDOW_MULTIPLIER = 20
CONTRIBUTOR_LOG_WINDOW_MIN = 500


def build_commit_message(
    subject: str,
    body_lines: list[str],
    authors: list[str] | None = None,
    sessions: list[str] | None = None,
    engine: str | None = None,
) -> str:
    """Assemble a structured commit message with optional trailers.

    ``subject`` is line 1, ``body_lines`` are the per-file manifest. Each
    distinct, non-empty ``authors`` entry becomes one ``Cicada-Author:`` line
    and each distinct, non-empty ``sessions`` entry one ``Cicada-Session:``
    line; a non-empty ``engine`` becomes exactly one ``Cicada-Engine:`` line
    (singular — a commit is driven by one engine, unlike the author/session
    lists). Order in the trailer block: authors, then engine, then sessions,
    in ONE block after a blank line (git-trailer convention). Caller order is
    preserved and duplicates are dropped, per list independently — an author
    id equal to a session id emits both. ``engine`` defaults to ``None``
    (no trailer at all) so every pre-existing call site stays byte-identical.
    """
    parts = [subject]
    if body_lines:
        parts.append("\n".join(body_lines))

    trailers: list[str] = []

    seen_authors: set[str] = set()
    for a in authors or []:
        name = (a or "").strip()
        if not name or name in seen_authors:
            continue
        seen_authors.add(name)
        trailers.append(f"{AUTHOR_TRAILER}: {name}")

    eng = (engine or "").strip()
    if eng:
        trailers.append(f"{ENGINE_TRAILER}: {eng}")

    seen_sessions: set[str] = set()
    for s in sessions or []:
        sid = (s or "").strip()
        if not sid or sid in seen_sessions:
            continue
        seen_sessions.add(sid)
        trailers.append(f"{SESSION_TRAILER}: {sid}")

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


def _parse_sessions(body: str) -> list[str]:
    """Extract conversation ids from ``Cicada-Session:`` trailer lines.

    Commit-LEVEL: every conversation the whole commit touched (a Sleep cycle
    that batched N conversations lists all N here). Correct as commit
    provenance (used by :func:`get_contributor_commits`); too broad to
    attribute to any ONE entity — see :func:`_parse_entity_sessions` for the
    precise per-entity answer, which ``get_entity_history`` uses instead of
    this function (PR #20 round-2 review fix: no fallback to this commit-wide
    set at the entity level).
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in body.splitlines():
        m = _SESSION_RE.match(line.strip())
        if m:
            sid = m.group(1).strip()
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sid)
    return out


# Matches the optional `, sessions: <id>[,<id>...]` clause `sleep_cycle._finalize`
# appends to an entity's OWN manifest line (never the whole-commit trailer).
_ENTITY_LINE_SESSIONS_RE = re.compile(r"sessions:\s*([^)]+)\)")


def _parse_entity_sessions(body: str, entity_id: str) -> list[str]:
    """This ONE entity's own session ids from its manifest line(s) in a commit
    body (PR #20 review fix).

    A batched Sleep cycle's commit-level ``Cicada-Session:`` trailers list
    EVERY conversation the cycle touched (see ``_parse_sessions``); crediting
    all of them to every changed entity overclaims provenance ("entity
    history reports unrelated conversations"). This instead reads the precise
    per-entity ``sessions: ...`` clause ``sleep_cycle._finalize`` stamps onto
    THAT entity's own ``entities/<id>.md: ...`` manifest line, derived from
    only the episode(s) that actually touched it.

    Returns ``[]`` when no such clause is present (a decay/archive change
    with no episode, or a pre-fix commit) — the caller (``get_entity_history``)
    uses that empty list as-is and does NOT fall back to the commit-level
    trailer (PR #20 round-2 review fix: falling back there overclaimed every
    conversation in a batched Sleep cycle as this one entity's own). "No known
    sessions" is the honest answer when no precise per-entity data exists.
    """
    prefix = f"entities/{entity_id}.md:"
    out: list[str] = []
    seen: set[str] = set()
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        m = _ENTITY_LINE_SESSIONS_RE.search(line)
        if not m:
            continue
        for sid in m.group(1).split(","):
            sid = sid.strip()
            if sid and sid not in seen:
                seen.add(sid)
                out.append(sid)
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

        # PR #20 round-2 review fix: use ONLY this entity's own precise
        # sessions (from its manifest line's `sessions: ...` clause) — never
        # the commit-wide `Cicada-Session:` trailer set as a fallback. A
        # decay/archive change carries no episode, so it never gets a
        # `sessions:` clause; falling back to the commit-wide trailers would
        # then credit it with EVERY conversation in that Sleep batch, even
        # ones that never touched it. When no precise per-entity data exists
        # (a decay/archive change, or a pre-fix commit), the honest answer is
        # "no known sessions" — an empty list, not a guess.
        sessions = _parse_entity_sessions(body, entity_id)

        entries.append(EntityHistoryEntry(
            date=date,
            change_type=change_type,
            description=description,
            author=author,
            commit_hash=commit_hash,
            diff=diff,
            sessions=sessions,
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


def _parse_unified_diff(
    out: str,
) -> tuple[list[DiffLine], list[str], list[str], bool, bool]:
    """Parse ``git show --unified=N`` output into ordered rows + legacy blocks.

    Returns ``(lines, added, removed, truncated, lines_truncated)``.

    ``lines`` is the ordered unified diff: one row per hunk header, context
    line, addition and removal, each carrying git's own 1-based old/new line
    numbers. ``added`` / ``removed`` are the pre-G69 flat blocks, still built
    here so the response stays back-compatible with an older app build.

    Everything before the first ``@@`` hunk header (``diff --git``, ``index``,
    mode lines, ``---`` / ``+++`` file headers) is skipped. The gate is "have we
    seen a hunk header yet", NOT a prefix match, so a file line that genuinely
    begins with ``---`` or ``+++`` inside a hunk is treated as content.
    """
    lines: list[DiffLine] = []
    added: list[str] = []
    removed: list[str] = []
    # Tracked per-sink, not as one flag: the ordered list can hit its (much
    # larger) cap while a side is complete, and vice versa. Only a side that was
    # itself clipped gets the marker appended, so the legacy blocks never claim
    # to be truncated when they are whole.
    added_clipped = False
    removed_clipped = False
    lines_clipped = False
    old_no = 0
    new_no = 0
    in_hunk = False

    def _emit(kind: str, old: int | None, new: int | None, text: str) -> None:
        nonlocal lines_clipped
        if len(lines) < DIFF_MAX_CONTEXT_LINES:
            lines.append(DiffLine(kind=kind, old_line=old, new_line=new, text=text))
        else:
            lines_clipped = True

    for raw in out.splitlines():
        header = _HUNK_HEADER_RE.match(raw)
        if header:
            in_hunk = True
            old_no = int(header.group(1))
            new_no = int(header.group(2))
            _emit("hunk", None, None, raw)
            continue
        if not in_hunk:
            continue
        # "\ No newline at end of file" annotates the previous row; it is not a
        # line of the file and consumes no line number.
        if raw.startswith("\\"):
            continue

        if raw.startswith("+"):
            text = raw[1:]
            _emit("add", None, new_no, text)
            new_no += 1
            if len(added) < DIFF_MAX_LINES:
                added.append(text)
            else:
                added_clipped = True
        elif raw.startswith("-"):
            text = raw[1:]
            _emit("remove", old_no, None, text)
            old_no += 1
            if len(removed) < DIFF_MAX_LINES:
                removed.append(text)
            else:
                removed_clipped = True
        else:
            # A context line is prefixed with a single space; a bare "" is an
            # empty context line whose single space was stripped in transit.
            _emit("context", old_no, new_no, raw[1:] if raw else "")
            old_no += 1
            new_no += 1

    if added_clipped:
        added.append(_DIFF_TRUNCATION_MARKER)
    if removed_clipped:
        removed.append(_DIFF_TRUNCATION_MARKER)

    return (
        lines,
        added,
        removed,
        added_clipped or removed_clipped or lines_clipped,
        lines_clipped,
    )


async def get_entity_commit_diff(
    entity_id: str, commit_hash: str, memory_path: Path
) -> EntityDiff:
    """Per-commit diff for one entity file (backlog A1, context lines in G69).

    Returns a real unified diff — additions, removals AND the unchanged context
    around them (``DIFF_CONTEXT_LINES`` either side), ordered, each row carrying
    its old/new line number — as ``lines``, alongside the pre-G69 flat
    ``added`` / ``removed`` blocks kept for back-compat.

    Returns an empty diff (not an error) when the commit is missing or the file
    didn't change in it — callers render "no diff" rather than failing.

    ``git show`` (rather than ``git diff <commit>^ <commit>``) is deliberate: it
    already diffs a ROOT commit against the empty tree, so the first commit of a
    file — which has no ``^`` parent — comes back as all-additions instead of
    erroring on an unknown revision.

    ``--first-parent`` is what makes a MERGE commit renderable. Left to itself
    ``git show`` emits a *combined* (``--cc``) diff for a merge, whose ``@@@ …
    @@@`` headers ``_HUNK_HEADER_RE`` cannot match — the parser would see no
    hunk at all and hand back an empty diff, i.e. the app would claim "no line
    changes" for a commit that plainly changed the file. With it, the merge is
    diffed two-sidedly against its first parent, exactly like an ordinary
    commit. It is inert for single-parent and root commits (verified), and on a
    git too old to imply ``--diff-merges=first-parent`` (< 2.31) it is simply
    ignored rather than erroring — degrading to today's behaviour for merges
    only, instead of breaking every diff the way ``--diff-merges=…`` would.

    ``commit_hash`` is validated against ``_COMMIT_HASH_RE`` before reaching git:
    a non-hex / flag-like value (e.g. ``--output=/tmp/x``) is rejected here, so it
    can never be parsed by ``git show`` as an option (arg-injection guard). The
    ``--end-of-options`` token is also passed so a future hex-only edge can't be
    treated as a flag. Output is bounded by ``DIFF_MAX_LINES`` per side and by
    ``DIFF_MAX_CONTEXT_LINES`` for the ordered list.
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
            f"--unified={DIFF_CONTEXT_LINES}",
            "--first-parent",
            "--end-of-options",
            commit_hash,
            "--",
            entity_file,
        )
    except GitError:
        return EntityDiff(added="", removed="", truncated=False)

    lines, added, removed, truncated, lines_truncated = _parse_unified_diff(out)

    return EntityDiff(
        added="\n".join(added),
        removed="\n".join(removed),
        truncated=truncated,
        lines=lines,
        lines_truncated=lines_truncated,
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

    The walk is bounded by ``--max-count`` (see ``CONTRIBUTOR_LOG_WINDOW_*``)
    and each commit's ``entities`` list by ``MAX_COMMIT_ENTITIES``.
    """
    author = (author or "").strip()
    if not author or not (memory_path / ".git").exists():
        return []

    limit = max(1, min(int(limit or 50), MAX_CONTRIBUTOR_COMMITS))
    window = max(limit * CONTRIBUTOR_LOG_WINDOW_MULTIPLIER, CONTRIBUTOR_LOG_WINDOW_MIN)
    sep = "\x1f"
    rec = "\x1e"
    try:
        out = await _run_git(
            memory_path,
            "log",
            f"--max-count={window}",
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
                # Capped for the wire; the honest count rides alongside it.
                entities=entities[:MAX_COMMIT_ENTITIES],
                entities_total=len(entities),
                files_changed=len(files),
                sessions=_parse_sessions(body),
            )
        )
        if len(commits) >= limit:
            break

    return commits


async def get_sleep_history(memory_path: Path) -> list[SleepHistoryEntry]:
    """Get chronological Sleep cycle history from git log.

    Each entry's ``engine`` (G74(a) Task 6, Ruling 4 extended) comes straight
    from the commit's optional ``Cicada-Engine:`` trailer — the same one line
    ``sleep_cycle._finalize`` now stamps on its main commit — via git's own
    ``%(trailers:key=...,valueonly,separator=)`` pretty-format directive,
    NOT ``%b``. M1 review fix round 1: pulling the full body (``%b``) for
    every commit to extract one trailer line made this endpoint's payload
    grow with the SIZE of every commit message ever written (measured on the
    live bank: 787 B -> 378 KB for 8 commits; a year of nightly cycles would
    be tens of MB parsed and NUL-split per request). The trailers directive
    gets git itself to do the extraction — it returns the bare value with no
    key/prefix, and an empty string (never an error) when the trailer is
    absent — so the per-record payload is back to what it was before this
    field existed. Verified against git 2.50.1.
    """
    sep = "\x1f"
    rec = "\x1e"
    engine_directive = "%(trailers:key=Cicada-Engine,valueonly,separator=)"
    try:
        output = await _run_git(
            memory_path,
            "log", f"--format=%H{sep}%ad{sep}%s{sep}{engine_directive}{rec}", "--date=short",
        )
    except GitError:
        return []

    entries: list[SleepHistoryEntry] = []
    for record in output.split(rec):
        record = record.strip("\n")
        if not record.strip():
            continue
        fields = record.split(sep, 3)
        if len(fields) < 4:
            continue
        commit_hash, date, subject, engine_field = (
            fields[0].strip(), fields[1].strip(), fields[2].strip(), fields[3].strip()
        )
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
                engine=engine_field or None,
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
