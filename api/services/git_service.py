import asyncio
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from loguru import logger

from api.models.schemas import (
    Contributor,
    ContributorCommit,
    DiffLine,
    EntityDiff,
    EntityHistoryEntry,
    SleepCycleDetail,
    SleepCycleEntity,
    SleepHistoryEntry,
)


class GitError(Exception):
    pass


def _replica_refusal():
    """G132 phase 1 (ruling 51e2): on a replica a git write is refused unless the follower's apply makes it. A
    ``GitError`` (every caller already handles one) that is also ``replica_guard.ReplicaReadOnly``."""
    from api.services import replica_guard

    class ReplicaGitRefused(GitError, replica_guard.ReplicaReadOnly):
        def __init__(self):
            replica_guard.ReplicaReadOnly.__init__(self, "git")

    return ReplicaGitRefused()


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
# "claude-cli" | "codex-cli" | "ollama" | "litellm" — mirroring `/sleep/status`'s
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

# How far back `top_written_entities` walks (G124 R13). Same reason as the
# contributor window above: `git log --name-only` materialises every commit's
# file list before Python can stop, so an unbounded walk grows with every
# Sleep cycle. The response says how many commits were scanned so the UI can
# say "over the last N commits" instead of implying all-time.
TOP_ENTITIES_LOG_WINDOW = 2000


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


_ENTITY_LINE_TRIGGER_RE = re.compile(r"\(.*?\btrigger:\s*([^,)]+)")

#: Vision item 5 (2026-10-28): the door a change came through, read from its manifest line's trigger, so a history row
#: shows Sleep as a tag and the contributor (the model, or the person) as its picture. Derived on read, never stored.
HISTORY_VIAS = ("sleep", "app", "agent", "remote", "inbox", "sync", "cicada", "unknown")
_SYNC_TRIGGERS = frozenset({"user/calendar_poll", "user/feed_poll", "user/notes_sync"})


def _parse_entity_trigger(body: str, entity_id: str) -> str:
    """This entity's own ``trigger:`` from its manifest line in a commit body; ``""`` when it has none (a hand-made or
    pre-manifest commit). Its own line only, like :func:`_parse_entity_sessions`: a batched commit names many."""
    prefix = f"entities/{entity_id}.md:"
    for line in body.splitlines():
        line = line.strip()
        if line.startswith(prefix) and (m := _ENTITY_LINE_TRIGGER_RE.search(line)):
            return m.group(1).strip()
    return ""


def history_via(trigger: str | None) -> str:
    """Which of :data:`HISTORY_VIAS` a change came through, from its trigger alone. ``sleep/…`` and an inbox question
    Sleep settled (``inbox/<kind>/settled…``) are Sleep; ``user/…`` the person in the app, except a reader that polls
    on its own (``sync``, like ``sync/…``); ``mcp/…`` a local agent; ``remote/…`` a connected app; any other
    ``inbox/…`` the person answering a question; anything else (``migration/…``, housekeeping) Cicada's own."""
    t = (trigger or "").strip().lower()
    if not t:
        return "unknown"
    head = t.split("/", 1)[0]
    if head == "sleep" or (head == "inbox" and "/settled" in t):
        return "sleep"
    if head == "sync" or t in _SYNC_TRIGGERS:
        return "sync"
    return {"user": "app", "mcp": "agent", "remote": "remote", "inbox": "inbox"}.get(head, "cicada")


# --- G15: contributor visual identity (kind / provider / avatar) ------------

# The literal "user" author (manual/companion-app/media-save writes).
USER_AUTHOR = "user"

# The literal "cicada" author: system maintenance with no model and no user in
# the loop. Written by ``sleep_cycle`` (the G85 decay split and the inbox
# question refresh), ``state_dictionary`` (the ``State snapshot`` commit),
# ``bookmark_sync``, ``link_enrichment`` and the one-shot migrations. It is a
# CONSTANT here rather than a literal at each site so the UI's bucket
# (``_classify_author_kind`` -> "system", R-L6) can never drift from what the
# writers actually stamp.
CICADA_AUTHOR = "cicada"

# G135: a write that arrived through MCP is authored by its harness label, and
# `agent` when the harness never said which it was (`agent_commits.author_for`).
AGENT_AUTHOR = "agent"
# The placeholder every stdio MCP claim carried before G135 R-R11 — the
# reconcile shim's "model" name. History is never rewritten (F2-back R-B10):
# every reader shows it as `agent` through `canonical_author`.
LEGACY_AGENT_AUTHOR = "mcp-agentic-write"
# R-B9: the bucket the app already names (`OriginIconography.label`) and marks
# (`OriginMark`) — a harness label is neither a model nor a person.
HARNESS_KIND = "harness"
# R-B10: folded into the ETag `extra` of every read whose body carries an
# author kind (`/contributors`, `/entities/{id}/provenance`,
# `/episodes/{id}/citations`) and, since round 4 (R4B-9), a turn's model
# (`/episodes/{id}/text`, `/projects`, `/projects/{id}/timeline`). Those bodies
# change for the same commits and claims, so an ETag over the inputs alone would
# 304 the old shape — the `graph.NODE_SHAPE` rule. Bump it when the author
# buckets or the joined model fields move.
# harness-2 (round 4 C3/C4): authorModel/authorEffort, span models, contributor models.
AUTHOR_SHAPE = "harness-2"


def canonical_author(author: str | None) -> str:
    """The author a reader shows (R-B10): the pre-G135 placeholder is `agent`,
    an empty author is the legacy `unknown` bucket, anything else is itself."""
    name = (author or "").strip() or UNKNOWN_AUTHOR
    return AGENT_AUTHOR if name == LEGACY_AGENT_AUTHOR else name


@lru_cache(maxsize=1)
def _harness_authors() -> frozenset[str]:
    """Every label a harness writes as `Cicada-Author` (R-B9): the Sources page's
    one harness table — stdio harnesses and every remote app (G135 R-R26) —
    minus its `unknown` bucket, plus `agent`. One table, so a new remote app is a
    harness here the day it is a card there. Imported lazily: `source_overview`
    reaches `folder_source`, and this module must stay importable on its own."""
    from api.services.source_overview import HARNESS_LABELS

    return frozenset(k for k in HARNESS_LABELS if k != UNKNOWN_AUTHOR) | {AGENT_AUTHOR}

# Routers that PROXY other vendors' models. Matched on the segment before the
# first "/" and checked BEFORE the substring pass (R9 of Track L): the router
# is who billed, so "openrouter/anthropic/claude-opus-4" is openrouter, not
# anthropic — attributing it to Anthropic is a lie about who was paid.
_ROUTER_PREFIXES = ("openrouter", "ollama")

# Model-id -> provider classification. We key on stable id substrings/prefixes
# (provider level, not per-model). LiteLLM-style "provider/model" ids are
# handled because the substring still appears (e.g. "anthropic/claude-...").
#
# These markers are distinctive enough to be safe as bare substring matches.
# The open-weight families (meta/mistral/deepseek/qwen) were added by R-L6:
# they are what a local or routed engine actually serves, and without them
# every one of them answered "other" and shared a single anonymous badge.
_PROVIDER_SUBSTRINGS = (
    ("openai", ("gpt", "text-embedding")),
    ("anthropic", ("claude",)),
    ("google", ("gemini", "gemma")),
    ("meta", ("llama",)),
    ("mistral", ("mistral", "mixtral")),
    ("deepseek", ("deepseek",)),
    ("qwen", ("qwen",)),
)

# OpenAI o-series markers are too short to match as bare substrings (they would
# false-positive on ids like "macro1"/"retro3"). They must match only as an
# anchored token: the whole id, a prefix ("o1-..."), or a hyphen-/slash-delimited
# token ("openai/o1-pro").
_OPENAI_O_SERIES = ("o1", "o3")


def _classify_author_kind(author: str) -> str:
    """Bucket an author into "user" | "system" | "harness" | "model" | "unknown".

    "system" is the literal ``cicada`` (R-L6): maintenance with no model and no
    user in the loop. It used to fall through to "model", where
    ``_provider_for_model`` answered "other" and the app drew a grey "?" — so
    the state snapshot, the split-out decay commit and the migrations all
    rendered as an anonymous unknown model in Cicada's own contributors list.

    "harness" (F2-back R-B9) is an agent write's label — `claude-code`,
    `claude-web`, `agent` — and the pre-G135 placeholder. They answered "model",
    so `claude-code` wore Anthropic's mark by substring and the placeholder
    showed as a raw contributor name.
    """
    if author == USER_AUTHOR:
        return "user"
    if author == CICADA_AUTHOR:
        return "system"
    if author == UNKNOWN_AUTHOR:
        return "unknown"
    if author == LEGACY_AGENT_AUTHOR or author in _harness_authors() or author.startswith("api:"):
        # G213: `api:<name>` is an agent on the HTTP agent API, named by the token the person made for it.
        return HARNESS_KIND
    return "model"


def _provider_for_model(author: str) -> str | None:
    """Derive the provider for a model id; None for user/system/unknown.

    Matches by lower-cased substring/prefix against the known provider markers;
    any unmatched model id is "other".

    The router check runs on the lower-cased id and BEFORE the substring loop
    (R9): "openrouter/anthropic/claude-opus-4" would otherwise hit ``claude``
    first and answer "anthropic", crediting the vendor whose model was proxied
    rather than the service that billed for it.
    """
    if _classify_author_kind(author) != "model":
        return None
    a = author.lower()
    head = a.split("/", 1)[0]
    if head in _ROUTER_PREFIXES:
        return head
    for provider, markers in _PROVIDER_SUBSTRINGS:
        if any(marker in a for marker in markers):
            return provider
    # o-series: anchored token match only (whole id / prefix / delimited token),
    # so "macro1"/"retro3" do not misclassify as OpenAI.
    if any(re.search(rf"(?:^|[/-]){re.escape(m)}(?:$|[/-])", a) for m in _OPENAI_O_SERIES):
        return "openai"
    return "other"


def author_identity(author: str | None) -> tuple[str, str | None]:
    """``(kind, provider)`` for an author id — the ONE rule the contributors
    strip, the claim chip, the history row and the provenance section read
    (G15 / R-L6; G118 slice 2 R-PB6). Public so no caller re-derives it; an
    empty author is the legacy ``unknown`` bucket."""
    name = canonical_author(author)
    return _classify_author_kind(name), _provider_for_model(name)


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


# --- One git writer per bank (F2-back R-B1 … R-B4) ---------------------------
#
# Found in the owner's review (2026-09-23): a background paper-details commit
# failed with git's own "Unable to create '.git/index.lock': File exists"
# because a folder-sync commit was running at the same moment, and the pages it
# wrote stayed dirty for the next `git add -A` writer to sweep under its own
# author — the G85-class smear. Eight concurrent `commit_paths` on one test bank
# reproduced it in five trials out of five. So every mutating git command runs
# under ONE re-entrant lock per bank, keyed by the resolved path, and held by a
# worker thread for the whole add → status → commit sequence: a thread lock, so
# loop tasks, the threadpool, `asyncio.run` bridges on other threads and sync
# startup migrations all queue on the same object (R-B4); the whole sequence, so
# a `status` check and its commit never straddle another writer. The backend is
# one process (R-B1); across processes git's own index.lock is the guard, and
# only its "File exists" refusal is retried (R-B2).

#: Subcommands that write the index, the working tree or a ref. `_run_git`
#: routes these through the lock; `test_git_write_lock.py`'s lint refuses a
#: literal of any of them spawned anywhere else in `api/` or `mcp/`.
WRITE_SUBCOMMANDS = frozenset({
    "add", "apply", "checkout", "cherry-pick", "clean", "commit", "merge", "mv",
    "reset", "restore", "revert", "rm", "stash", "update-index", "update-ref", "read-tree",
    # Git's own derived index of the history (`write_commit_graph_sync`): never a content commit, but a writer of
    # `.git/objects/info`, so it waits for the bank's lock like every other.
    "commit-graph",
    # G132 phase 1: the replica's follower fetches the home's bundle into `refs/cicada/home` (its one write).
    "fetch",
})
#: What the replica backstop refuses beside the write subcommands: commands that write `.git` itself.
_REPLICA_GUARDED = WRITE_SUBCOMMANDS | {"config", "init", "gc", "prune", "repack", "notes", "hash-object",
                                        "commit-tree", "write-tree", "remote", "tag", "branch", "worktree"}
#: Waits between tries while ANOTHER process holds the index (R-B2): five tries
#: in about two seconds. A terminal's `git add` takes milliseconds; an editor left
#: open by `git commit` does not, and that case is R-B5's to keep.
INDEX_LOCK_BACKOFF_S: tuple[float, ...] = (0.1, 0.25, 0.5, 1.0)
#: The retry's clock — a seam, so the suite never sleeps.
_sleep = time.sleep

_WRITE_LOCKS: dict[str, threading.RLock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def write_lock(memory_path) -> threading.RLock:
    """The one lock every git writer of this bank holds (R-B1). Keyed by the
    resolved path, so `bank`, `bank/` and a symlink to it are one bank.
    Re-entrant: a caller already holding it may call `commit_paths_sync`."""
    key = os.path.realpath(os.fspath(memory_path))
    with _WRITE_LOCKS_GUARD:
        return _WRITE_LOCKS.setdefault(key, threading.RLock())


def _index_lock_busy(stderr: str) -> bool:
    """Git's refusal while another process holds `.git/index.lock` — the one
    failure a writer retries (R-B2)."""
    return "index.lock" in stderr and "File exists" in stderr


def _spawn(memory_path: Path, args: tuple[str, ...]) -> subprocess.CompletedProcess:
    """The one place a mutating git command starts (a test seam)."""
    return subprocess.run(["git", *args], cwd=str(memory_path), capture_output=True)


def _git_sync(memory_path: Path, *args: str) -> str:
    """One git command, called with the bank's write lock held. Retries only git's
    index-lock refusal and never deletes the lock (R-B2): another process owns
    it, and removing it under a live commit corrupts the index."""
    if args and args[0] in _REPLICA_GUARDED:
        from api.services import replica_guard

        if replica_guard.blocks():
            raise _replica_refusal()
    for delay in (*INDEX_LOCK_BACKOFF_S, None):
        try:
            proc = _spawn(memory_path, args)
        except OSError as exc:
            raise GitError(f"git {' '.join(args)} failed: {exc}") from exc
        if proc.returncode == 0:
            return proc.stdout.decode(errors="replace")
        stderr = proc.stderr.decode(errors="replace")
        if delay is None or not _index_lock_busy(stderr):
            raise GitError(f"git {' '.join(args)} failed: {stderr}")
        logger.info(f"git {args[0]}: another git process holds this bank's index — retrying in {delay}s")
        _sleep(delay)
    raise GitError(f"git {' '.join(args)} failed")  # unreachable: the last try has no delay


def run_git_write_sync(memory_path, *args: str) -> str:
    """One mutating git command under the bank's write lock (R-B1) — for a sync
    caller (the expiry restore) and for `_run_git`'s write branch. A ``checkout``
    that puts pages back puts back each page's claims ledger with it, when git
    has one (``claims_ledger``)."""
    memory_path = Path(memory_path)
    with write_lock(memory_path):
        if args and args[0] == "checkout" and "--" in args:
            cut = args.index("--") + 1
            rev = [a for a in args[1:cut - 1] if not a.startswith("-")]
            args = (*args[:cut], *_with_tracked_ledgers(memory_path, list(args[cut:]), rev[0] if rev else None))
        try:
            return _git_sync(memory_path, *args)
        finally:
            if args and args[0] in _TREE_WRITERS:
                # Git rewrote working-tree files behind the parser's back: an open Sleep batch's page cache of this
                # bank starts over (`markdown_parser.page_cache`), stamps or no stamps.
                from api.services import markdown_parser

                markdown_parser.invalidate_pages(memory_path)


#: Write subcommands that can change a working-tree file (``add``, ``commit``, ``update-index`` and ``update-ref`` never
#: touch one).
_TREE_WRITERS = WRITE_SUBCOMMANDS - {"add", "commit", "update-index", "update-ref", "commit-graph"}


def write_commit_graph_sync(memory_path) -> bool:
    """Keep git's commit-graph current, with changed-path Bloom filters (owner via the coordinator, 2026-10-29).

    Every per-page history read — the History tab (``page_history``), ``entity_history``, the provenance strip's
    ``entity_commit_authors`` — is a path-limited ``git log`` that walks the whole history; the filters let git skip
    commits that never touched the path. Measured on an owner-scale bank copy in PR ``perf/commit-graph``. The file
    is git-internal and derived (``.git/objects/info/commit-graph``): never tracked, never a commit, rebuilt from the
    history at any time, and git ignores it when it is missing or stale. One full rewrite, under the bank's write lock
    (R-B1): git reuses the filters it already has, so a night's rewrite costs the new commits. ``False`` for a bank
    with no git."""
    mp = Path(memory_path)
    if not (mp / ".git").exists():
        return False
    run_git_write_sync(mp, "commit-graph", "write", "--reachable", "--changed-paths")
    return True


#: The commit identity a bank falls back to when none is configured (G181, G203): placeholder values, never the
#: person's. Who wrote a change is the ``Cicada-Author`` trailer's job, not git's author field; no reader of a bank's
#: history reads the author field (G203's Hyrum line in storage.md).
FALLBACK_IDENTITY = ("Cicada", "cicada@localhost")


def _missing_identity_keys(memory_path: Path) -> list[str]:
    """The halves of the commit identity nobody chose: ``user.name``, ``user.email``, both or neither. A half counts
    as chosen when git finds it in the environment or in the repo, global or system config (``EMAIL`` too, which git
    honours for the email); ``useConfigOnly`` stops git guessing, since with no ``user.name`` it would take the
    account's full name and ``user@hostname`` and a bank handed to someone else would carry both (G203). Each half is
    probed with the other one stood in, so a configured name is never mistaken for a missing one."""
    probes = {"user.name": "user.email=probe@cicada.invalid", "user.email": "user.name=probe"}
    missing = []
    for key, stand_in in probes.items():
        if key == "user.email" and os.environ.get("EMAIL"):
            continue
        for var in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
            try:
                proc = subprocess.run(["git", "-c", "user.useConfigOnly=true", "-c", stand_in, "var", var],
                                      cwd=str(memory_path), capture_output=True)
            except OSError:
                return []  # no git at all: nothing to fix here, and every write already degrades
            if proc.returncode != 0:
                missing.append(key)
                break
    return missing


def ensure_commit_identity_sync(memory_path) -> bool:
    """Fill, in the bank's own config, only the half of the commit identity nobody configured, with the neutral
    :data:`FALLBACK_IDENTITY` value: git would otherwise guess it from the account (or, with ``useConfigOnly``, refuse
    every commit). A configured half is the person's choice and stays, so a global ``user.name`` with no email keeps
    the name and gets the neutral email. Never touches ``~/.gitconfig``, never rewrites a commit already made. Runs
    for every bank that becomes active (``scaffold_bank``, ``run_bank_migrations``). Returns True when it set one."""
    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists():
        return False
    missing = _missing_identity_keys(memory_path)
    values = dict(zip(("user.name", "user.email"), FALLBACK_IDENTITY))
    for key in missing:
        run_git_write_sync(memory_path, "config", key, values[key])
    if missing:
        logger.info(f"git: no {' or '.join(missing)} is configured; the bank uses Cicada's neutral value")
    return bool(missing)


def _ledger_rels(paths) -> list[str]:
    from api.services import claims_ledger

    return [companion for p in paths if (companion := claims_ledger.rel_for(str(p)))]


def _with_tracked_ledgers(memory_path: Path, paths: list[str], rev: str | None) -> list[str]:
    """``paths`` plus the ledger of each page among them that git holds (in ``rev``, else the index) — a pathspec git
    does not know would fail the whole checkout. Called with the write lock held."""
    wanted = _ledger_rels(paths)
    if not wanted:
        return paths
    try:
        listing = (_git_sync(memory_path, "ls-tree", "-r", "-z", "--name-only", rev, "--", *wanted) if rev
                   else _git_sync(memory_path, "ls-files", "-z", "--", *wanted))
    except GitError:
        return paths
    known = {r for r in listing.split("\0") if r}
    return list(dict.fromkeys([*paths, *(w for w in wanted if w in known)]))


def _with_ledgers(memory_path: Path, paths: list[str]) -> list[str]:
    """``paths`` plus the claims ledger of each page among them that exists or that git knows (a page and its ledger
    are committed as one unit: a page write moves claims between them, ``claims_ledger``). Write lock held."""
    wanted = [w for w in _ledger_rels(paths) if w not in paths]
    if not wanted:
        return paths
    present = [w for w in wanted if (memory_path / w).exists()]
    # A ledger is removed only with its page (a merge, a rename): git is asked only about a gone page's ledger, so an
    # ordinary commit spawns nothing more than before.
    absent = [w for w in wanted if w not in present and not (memory_path / (w[:-len(".claims.jsonl")] + ".md")).exists()]
    known: set[str] = set()
    if absent:
        try:
            known = {r for r in _git_sync(memory_path, "ls-files", "-z", "--", *absent).split("\0") if r}
            known |= {r for r in _git_sync(memory_path, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--",
                                           *absent).split("\0") if r}
        except GitError:
            pass
    return list(dict.fromkeys([*paths, *present, *(w for w in absent if w in known)]))


def commit_paths_sync(memory_path, message: str, paths) -> None:
    """Stage and commit ONLY ``paths`` (memory-relative), never ``git add -A``,
    under the bank's write lock (R-B1, R-B4).

    A targeted write (adding a fact source, deferring one inbox item, a
    migration) must not sweep unrelated dirty files into its commit — that
    would attribute someone else's change to this action's trigger and author.
    """
    paths = [str(p) for p in paths or ()]
    if not paths:
        return
    memory_path = Path(memory_path)
    with write_lock(memory_path):
        paths = _with_ledgers(memory_path, paths)
        _git_sync(memory_path, "add", "--", *paths)
        if not _git_sync(memory_path, "status", "--porcelain", "--", *paths).strip():
            return  # Nothing to commit
        _git_sync(memory_path, "commit", "-m", message, "--", *paths)


def commit_changes_sync(memory_path, message: str) -> str | None:
    """Stage all changes and commit under the bank's write lock. The new commit
    hash, or ``None`` when there was nothing to commit."""
    memory_path = Path(memory_path)
    with write_lock(memory_path):
        _git_sync(memory_path, "add", "-A")
        if not _git_sync(memory_path, "status", "--porcelain").strip():
            return None  # Nothing to commit
        _git_sync(memory_path, "commit", "-m", message)
        return _git_sync(memory_path, "rev-parse", "HEAD").strip()


def _git_env_sync(memory_path: Path, env: dict, *args: str) -> str:
    """One git command against a PRIVATE index (``GIT_INDEX_FILE``), called with
    the bank's write lock held. Nothing else contends for that index, so there
    is no lock to retry."""
    from api.services import replica_guard

    if replica_guard.blocks():
        raise _replica_refusal()
    try:
        proc = subprocess.run(["git", *args], cwd=str(memory_path), capture_output=True, env=env)
    except OSError as exc:
        raise GitError(f"git {' '.join(args)} failed: {exc}") from exc
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace')}")
    return proc.stdout.decode(errors="replace")


def _commit_kept_apart_sync(memory_path: Path, contents: dict[str, bytes | None], message: str) -> bool:
    """Commit ``contents`` — what these paths held BEFORE a writer touched them —
    as their own commit, without touching the working tree (audit 2026-10-05
    P1-3). Built in a private index from HEAD, so nothing else staged rides in;
    then the real index's entries for these paths are reset to the new HEAD.
    ``None`` is "the file was deleted". Called with the write lock held.
    Returns whether a commit was made."""
    git_dir = Path(_git_sync(memory_path, "rev-parse", "--absolute-git-dir").strip())
    try:
        head = _git_sync(memory_path, "rev-parse", "--verify", "-q", "HEAD^{commit}").strip()
    except GitError:
        head = ""   # an unborn branch: the kept-apart commit is the first one
    index = git_dir / "cicada-kept-apart.index"
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    try:
        index.unlink(missing_ok=True)
        if head:
            _git_env_sync(memory_path, env, "read-tree", head)
        for rel, data in contents.items():
            if data is None:
                _git_env_sync(memory_path, env, "update-index", "--force-remove", "--", rel)
                continue
            fd, tmp = tempfile.mkstemp(prefix="cicada-kept-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                blob = _git_env_sync(memory_path, env, "hash-object", "-w", f"--path={rel}", tmp).strip()
            finally:
                os.unlink(tmp)
            mode = "100644"
            if head:
                listed = _git_sync(memory_path, "ls-tree", head, "--", rel).split()
                mode = listed[0] if listed and listed[0] in ("100644", "100755") else mode
            _git_env_sync(memory_path, env, "update-index", "--add", "--cacheinfo", f"{mode},{blob},{rel}")
        tree = _git_env_sync(memory_path, env, "write-tree").strip()
        if head and tree == _git_sync(memory_path, "rev-parse", f"{head}^{{tree}}").strip():
            return False
        commit = _git_env_sync(memory_path, env, "commit-tree", tree, *(["-p", head] if head else []),
                               "-m", message).strip()
        _git_sync(memory_path, "update-ref", "HEAD", commit, *([head] if head else []))
        # The real index still holds the old HEAD's entries for these paths: bring them to the new HEAD, or
        # the next status would read the kept edit as staged in reverse. The working tree is never touched.
        _git_sync(memory_path, "reset", "-q", "HEAD", "--", *contents)
        return True
    finally:
        index.unlink(missing_ok=True)


def commit_contents_sync(memory_path, contents: dict[str, bytes], message: str) -> bool:
    """Commit exactly ``contents`` — these bytes at these paths, never what the working tree holds by then, never
    another path, never the index's other entries — under the bank's write lock (G132 phase 1's capture commit,
    ``capture_commit``). Built in a private index like the kept-apart commit; the working tree is never touched.
    Returns whether a commit was made (``False`` when HEAD already holds them)."""
    memory_path = Path(memory_path)
    if not contents:
        return False
    with write_lock(memory_path):
        return _commit_kept_apart_sync(memory_path, dict(contents), message)


class NotFastForward(GitError):
    """The home's head is not a descendant of the copy's: the copy never applies it (it is copied again on the
    person's word)."""


class DirtyCopy(GitError):
    """A tracked file of the copy differs from its HEAD: something wrote it outside the apply; never overwritten."""


#: The ref the home's bundle is fetched into on a replica (never a branch anything else moves).
HOME_REF = "refs/cicada/home"


def _blobs_at(memory_path: Path, rev: str, paths: list[str]) -> dict[str, bytes]:
    """``{path: bytes}`` of ``paths`` at ``rev``, through one ``git cat-file --batch`` (a read)."""
    if not paths:
        return {}
    proc = subprocess.run(["git", "cat-file", "--batch"], cwd=str(memory_path), capture_output=True,
                          input="".join(f"{rev}:{p}\n" for p in paths).encode("utf-8"))
    if proc.returncode != 0:
        raise GitError("git cat-file --batch failed")
    out, pos, got = proc.stdout, 0, {}
    for p in paths:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        pos = nl + 1
        if len(header) < 3 or header[1] != b"blob":
            raise GitError(f"not a file at {rev}: {p}")
        size = int(header[2])
        got[p] = out[pos:pos + size]
        pos += size + 1
    return got


def _write_atomically(path: Path, data: bytes) -> None:
    """The page rule: a temp file beside it, then ``os.replace`` — a reader sees the old file or the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.cicada-apply")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def fast_forward_sync(memory_path, bundle: Path, *, expect: str | None = None, rewrite: bool = False) -> dict:
    """The replica's apply (G132 phase 1, ruling 51a): bring this copy to the home's head in ``bundle``.

    Under the bank's write lock: fetch the bundle into :data:`HOME_REF`; require the copy's HEAD to be an ancestor of
    it (ancestry checked here, never a seq trusted alone) and every tracked file clean; write each changed file
    atomically (``os.replace``, so no reader parses a torn page) and remove each removed one; then move HEAD
    (compare-and-swap) and bring the index to it. ``rewrite`` is only the person's "copy again" after the home's
    history was rewritten: the whole tree is written over and HEAD is moved without the ancestry test.
    Returns ``{"head", "old", "changed", "removed"}``. Called inside ``replica_guard.applying()``."""
    memory_path = Path(memory_path)
    with write_lock(memory_path):
        _git_sync(memory_path, "fetch", "-q", "--no-tags", "--no-write-fetch-head", str(bundle),
                  f"+HEAD:{HOME_REF}")
        new = _git_sync(memory_path, "rev-parse", "--verify", "-q", f"{HOME_REF}^{{commit}}").strip()
        if expect and new != expect:
            raise GitError("the bundle's head is not the one the home named")
        try:
            old = _git_sync(memory_path, "rev-parse", "--verify", "-q", "HEAD^{commit}").strip()
        except GitError:
            old = ""
        if old == new:
            return {"head": new, "old": old, "changed": [], "removed": []}
        if old and not rewrite:
            ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", old, new], cwd=str(memory_path),
                                      capture_output=True)
            if ancestor.returncode != 0:
                raise NotFastForward("the home's head does not descend from this copy's")
            if _git_sync(memory_path, "status", "--porcelain", "-z", "--untracked-files=no").strip("\0").strip():
                raise DirtyCopy("a tracked file of this copy was changed outside the apply")
            listing = _git_sync(memory_path, "diff", "--name-status", "-z", "--no-renames", old, new)
            fields = [f for f in listing.split("\0") if f]
            changed, removed = [], []
            for status, path in zip(fields[0::2], fields[1::2]):
                (removed if status.startswith("D") else changed).append(path)
        else:
            changed = [p for p in _git_sync(memory_path, "ls-tree", "-r", "-z", "--name-only", new).split("\0") if p]
            have = set()
            if old:
                have = {p for p in _git_sync(memory_path, "ls-tree", "-r", "-z", "--name-only", old).split("\0") if p}
            removed = sorted(have - set(changed))
        blobs = _blobs_at(memory_path, new, changed)
        for rel in changed:
            _write_atomically(memory_path / rel, blobs[rel])
        for rel in removed:
            (memory_path / rel).unlink(missing_ok=True)
        if old and not rewrite:
            _git_sync(memory_path, "update-ref", "HEAD", new, old)
        else:
            _git_sync(memory_path, "update-ref", "HEAD", new)
        _git_sync(memory_path, "reset", "-q")
    from api.services import bank_index, markdown_parser

    markdown_parser.invalidate_pages(memory_path)
    bank_index.invalidate(memory_path)
    return {"head": new, "old": old, "changed": changed, "removed": removed}


def bootstrap_from_bundle_sync(target: Path, bundle: Path) -> str:
    """A replica's first copy: a new git repository at ``target`` (which must not exist) holding the bundle's history,
    its tree checked out on ``main``. Returns the head. Called inside ``replica_guard.applying()``."""
    target = Path(target)
    if target.exists():
        raise GitError("the copy's folder already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    _git_sync(target.parent, "init", "-q", "-b", "main", target.name)
    try:
        with write_lock(target):
            _git_sync(target, "fetch", "-q", "--no-tags", "--no-write-fetch-head", str(bundle), f"+HEAD:{HOME_REF}")
            head = _git_sync(target, "rev-parse", "--verify", "-q", f"{HOME_REF}^{{commit}}").strip()
            _git_sync(target, "reset", "-q", "--hard", head)
    except BaseException:
        import shutil

        shutil.rmtree(target, ignore_errors=True)
        raise
    return head


def head_blob_sync(memory_path, rel: str) -> bytes | None:
    """What HEAD holds at ``rel`` (memory-relative), or ``None`` when it holds nothing there. A read."""
    try:
        proc = subprocess.run(["git", "cat-file", "blob", f"HEAD:{rel}"], cwd=str(memory_path), capture_output=True,
                              timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise GitError("git cat-file failed") from None
    return proc.stdout if proc.returncode == 0 else None


def commit_touched_sync(memory_path, message: str, paths, *, before: dict[str, bytes | None] | None = None,
                        kept_subject: str | None = None, kept_trigger: str = "kept-apart") -> None:
    """Commit exactly ``paths`` (memory-relative) — never ``git add -A`` — under the
    bank's write lock (audit 2026-10-05 P1-3). A path that is gone is committed
    as a removal when git knows it and skipped when it never existed.

    ``before`` is what the dirty paths held before the writer ran
    (:func:`snapshot_dirty`): an edit already on a path this commit takes is
    committed FIRST, alone, as ``kept_subject`` (one manifest line per file it
    really holds) with no author trailer — it was
    not this writer's, and Cicada does not guess whose it was — so the writer's
    commit carries only its own change. A path the writer did not change keeps
    its uncommitted edit uncommitted."""
    memory_path = Path(memory_path)
    paths = list(dict.fromkeys(str(p) for p in paths or () if p))
    if not paths:
        return
    with write_lock(memory_path):
        paths = _with_ledgers(memory_path, paths)
        missing = [p for p in paths if not (memory_path / p).exists()]
        known = set()
        if missing:
            # Known to git if the index OR HEAD has it: a `git mv` (the inbox's
            # keep-the-cleaner-name rename) has already taken the old path out of
            # the index, and its removal must still be committed here.
            known = {r for r in _git_sync(memory_path, "ls-files", "-z", "--", *missing).split("\0") if r}
            try:
                known |= {r for r in _git_sync(memory_path, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--",
                                               *missing).split("\0") if r}
            except GitError:
                pass   # an unborn branch: nothing in HEAD
        stage = [p for p in paths if p not in missing or p in known]
        if not stage:
            return
        kept = {}
        for rel in stage:
            if before is None or rel not in before:
                continue
            now = (memory_path / rel).read_bytes() if (memory_path / rel).is_file() else None
            if now != before[rel]:
                kept[rel] = before[rel]
            else:
                stage = [p for p in stage if p != rel]   # untouched by this writer: not its to commit
        if kept:
            kept_message = build_commit_message(
                kept_subject or f"Uncommitted edit kept apart {date.today().isoformat()}",
                [f"{p}: updated (trigger: {kept_trigger})" for p in sorted(kept)],
            )
            _commit_kept_apart_sync(memory_path, kept, kept_message)
        if not stage:
            return
        # `git add` refuses a path that is in neither the tree nor the index (a
        # renamed-away page); `git commit -- <path>` still records its removal.
        indexed = {r for r in _git_sync(memory_path, "ls-files", "-z", "--", *stage).split("\0") if r}
        addable = [p for p in stage if (memory_path / p).exists() or p in indexed]
        if addable:
            _git_sync(memory_path, "add", "-A", "--", *addable)
        if not _git_sync(memory_path, "status", "--porcelain", "--", *stage).strip():
            return
        _git_sync(memory_path, "commit", "-m", message, "--", *stage)


#: What a resolution can rewrite: pages, its own item, and the bank's root files (`_merge_rejected.yaml`, the
#: predicate map, `graph_edges.yaml`). `snapshot_dirty` reads only these — never a dirty episode's text.
_TOUCHABLE_DIRS = ("entities/", "inbox/", "nudges/", "clarifications/")


async def dirty_paths(memory_path: Path) -> frozenset[str]:
    """Every path `git status` reports as changed or untracked, relative to the
    bank root. `-z` so a name is never C-quoted; `--untracked-files=all` so a
    new page is listed by name, not folded into its directory; a rename's
    second record (its source) is kept too. Raises `GitError` rather than
    `porcelain_status`'s empty string, so an unreadable tree never reads as a
    clean one."""
    out = await _run_git(memory_path, "status", "--porcelain", "-z", "--untracked-files=all")
    return _parse_status_z(out)


def dirty_paths_sync(memory_path, *pathspec: str) -> frozenset[str]:
    """:func:`dirty_paths` for a sync writer, under the bank's write lock (a
    writer that already holds it re-enters), optionally narrowed to
    ``pathspec``. Staged, modified and untracked paths all count."""
    memory_path = Path(memory_path)
    with write_lock(memory_path):
        out = _git_sync(memory_path, "status", "--porcelain", "-z", "--untracked-files=all",
                        *(("--", *pathspec) if pathspec else ()))
    return _parse_status_z(out)


def _parse_status_z(out: str) -> frozenset[str]:
    records = out.split("\0")
    dirty: set[str] = set()
    i = 0
    while i < len(records):
        rec = records[i]
        i += 1
        if len(rec) < 4:
            continue
        dirty.add(rec[3:])
        if rec[0] in "RC" or rec[1] in "RC":
            if i < len(records) and records[i]:
                dirty.add(records[i])
            i += 1
    return frozenset(dirty)


async def snapshot_dirty(memory_path: Path) -> dict[str, bytes | None] | None:
    """What every uncommitted page, inbox item and root file holds right now —
    taken before a resolution writes, so :func:`commit_touched_sync` can keep an
    edit that was already there apart from the person's answer. ``None`` when
    the tree cannot be read (no repo: nothing to commit anyway)."""
    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists():
        return None
    try:
        dirty = await dirty_paths(memory_path)
    except GitError:
        return None
    out: dict[str, bytes | None] = {}
    for rel in dirty:
        if "/" in rel and not rel.startswith(_TOUCHABLE_DIRS):
            continue
        path = memory_path / rel
        try:
            out[rel] = path.read_bytes() if path.is_file() else None
        except OSError:
            out[rel] = None
    return out


def snapshot_dirty_sync(memory_path) -> dict[str, bytes | None] | None:
    """:func:`snapshot_dirty` for a sync caller (an agent's tool call, before its write): the same paths, the same
    ``None`` when the tree cannot be read."""
    memory_path = Path(memory_path)
    if not (memory_path / ".git").exists():
        return None
    try:
        dirty = dirty_paths_sync(memory_path)
    except GitError:
        return None
    out: dict[str, bytes | None] = {}
    for rel in dirty:
        if "/" in rel and not rel.startswith(_TOUCHABLE_DIRS):
            continue
        path = memory_path / rel
        try:
            out[rel] = path.read_bytes() if path.is_file() else None
        except OSError:
            out[rel] = None
    return out


async def _run_git(memory_path: Path, *args: str) -> str:
    if args and args[0] in WRITE_SUBCOMMANDS:
        # R-B1: a write through the async helper (`inbox_service`'s `git mv` /
        # `git rm`) queues on the same lock as every commit.
        return await asyncio.to_thread(run_git_write_sync, memory_path, *args)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(memory_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # R-B3: `git status` otherwise takes the index lock to refresh its
            # stat cache — the very lock a Cicada writer then finds held.
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
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
    skip: int = 0,
) -> list[EntityHistoryEntry]:
    """:func:`entity_history`'s rows, for a caller that serves the plain list."""
    rows, _ = await entity_history(entity_id, memory_path, include_diff=include_diff, skip=skip)
    return rows


_HISTORY_FORMAT = "--format=%x1e%H%x1f%ad%x1f%s%x1f%b"
_BLAME_HEADER = re.compile(r"^([0-9a-f]{40}) \d+ \d+ \d+$", re.MULTILINE)


async def entity_history(
    entity_id: str,
    memory_path: Path,
    *,
    include_diff: bool = False,
    skip: int = 0,
) -> tuple[list[EntityHistoryEntry], bool]:
    """``(rows, truncated)``: every commit that touched ``entities/<entity_id>.md``, newest first, with field-level
    provenance, and whether older touching commits were left out.

    ONE ``git log`` over the path, at most :data:`MAX_PROVENANCE_COMMITS` rows after ``skip`` — the rule
    ``entity_commit_authors`` serves the provenance strip, so the History tab and "N changes by" count the same
    commits. It replaced ``git blame`` plus one ``git log -1`` per surviving commit: 1.0 s on a 3,500-claim page, 1.7 s
    at 6,000, against ~30 ms (benchmarks/scale). Past the cap (review round 1) nothing the page still shows is lost:
    every commit whose lines survive — the creation row and its conversation, say — is added after the window from
    ``git blame --incremental`` and one batched ``git log``, and ``truncated`` says older touches were left out; they
    are reachable with ``skip``. Each entry carries the authoring agent (from the commit's ``Cicada-Author:`` trailer;
    "unknown" when absent) and the commit hash; ``include_diff`` adds the per-commit diff for this file (opt-in so the
    default response stays small — backlog A1).
    """
    entity_file = f"entities/{entity_id}.md"
    entity_path = memory_path / entity_file

    if not entity_path.exists():
        return [], False

    limit = MAX_PROVENANCE_COMMITS
    try:
        log_output = await _run_git(
            memory_path, "log", f"-n{limit + 1}", f"--skip={max(0, int(skip))}",
            _HISTORY_FORMAT, "--date=short", "--", entity_file,
        )
    except GitError:
        return [], False
    records = log_output.split("\x1e")[1:]
    truncated = len(records) > limit
    records = records[:limit]
    if truncated and not skip:
        records += await _older_survivors(memory_path, entity_file, entity_path, records)

    entries: list[EntityHistoryEntry] = []
    for record in records:
        parts = record.split("\x1f", 3)
        if len(parts) < 4:
            continue
        commit_hash, date, subject, body = parts[0].strip(), parts[1].strip(), parts[2], parts[3].rstrip("\n")
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

        author_kind, author_provider = author_identity(author)
        entries.append(EntityHistoryEntry(
            date=date,
            change_type=change_type,
            description=description,
            author=author,
            author_kind=author_kind,
            author_provider=author_provider,
            commit_hash=commit_hash,
            diff=diff,
            sessions=sessions,
            trigger=(trigger := _parse_entity_trigger(body, entity_id)),
            via=history_via(trigger),
        ))

    return entries, truncated


#: Owner page, 2026-10-14: ``git blame`` over a page rewritten by hundreds of Sleep commits diffs every multi-MB
#: revision it walks back through — 2.3 s on a synthetic owner page with 520 commits, paid on every card open (the
#: card and its History tab both ask). What it finds depends only on the page as it stands and its history, so it is
#: kept per (bank, page, newest touching commit, the file's mtime and size) for this process, and a card does not wait
#: for it longer than :data:`_SURVIVORS_WAIT_S`: past that the window is served (``truncated`` already says older
#: touches are left out) while the blame finishes in the background for the next open. Process-local, disposable.
_SURVIVORS: dict[tuple, list[str]] = {}
_SURVIVORS_MAX = 64
_SURVIVORS_WAIT_S = 0.5
_SURVIVORS_PENDING: dict[tuple, "asyncio.Task"] = {}


async def _blame_survivors(memory_path: Path, entity_file: str, shown: set[str], key) -> list[str]:
    try:
        blame = await _run_git(memory_path, "blame", "--incremental", "--", entity_file)
        survivors = [h for h in dict.fromkeys(_BLAME_HEADER.findall(blame))
                     if h not in shown and not h.startswith("0000000")]
        older: list[str] = []
        if survivors:
            out = await _run_git(memory_path, "log", "--no-walk=sorted", _HISTORY_FORMAT, "--date=short",
                                 *survivors, "--")
            older = out.split("\x1e")[1:]
    except GitError:
        return []
    finally:
        _SURVIVORS_PENDING.pop(key, None)
    if key is not None:
        while len(_SURVIVORS) >= _SURVIVORS_MAX:
            _SURVIVORS.pop(next(iter(_SURVIVORS)))
        _SURVIVORS[key] = older
    return older


async def _older_survivors(memory_path: Path, entity_file: str, entity_path: Path, records: list[str]) -> list[str]:
    """The history rows of commits older than the window whose lines the page still shows (``git blame``), or ``[]``
    when git cannot say or has not said within :data:`_SURVIVORS_WAIT_S` — the window still stands, and
    ``truncated`` already says it is partial."""
    shown = {r.split("\x1f", 1)[0].strip() for r in records}
    try:
        st = entity_path.stat()
        key = (str(memory_path), entity_file, records[0].split("\x1f", 1)[0].strip(), st.st_mtime_ns, st.st_size)
    except (OSError, IndexError):
        return await _blame_survivors(memory_path, entity_file, shown, None)
    if key in _SURVIVORS:
        return list(_SURVIVORS[key])
    loop = asyncio.get_running_loop()
    task = _SURVIVORS_PENDING.get(key)
    if task is None or task.done() or task.get_loop() is not loop:
        task = loop.create_task(_blame_survivors(memory_path, entity_file, shown, key))
        _SURVIVORS_PENDING[key] = task
    try:
        return list(await asyncio.wait_for(asyncio.shield(task), timeout=_SURVIVORS_WAIT_S))
    except asyncio.TimeoutError:
        return []


# G118 slice 2 (R-PB6): enough history for "N changes by <author>" on the
# entity card. A page touched by more commits than this says so
# (`commitsTruncated`) instead of walking the whole history per card open.
MAX_PROVENANCE_COMMITS = 500


async def entity_commit_authors(
    memory_path: Path, entity_id: str, *, limit: int | None = None,
) -> tuple[dict[str, int], bool]:
    """Commits that touched ``entities/<entity_id>.md``, counted per
    ``Cicada-Author`` (an untrailered commit is ``unknown``), and whether the
    walk was cut at ``limit``.

    ONE ``git log`` over the path with git's own trailer directive: every
    commit that ever changed the page (not only blame survivors — a decay pass
    that was later overwritten still contributed), and never ``%b``, because a
    Sleep commit's body is a manifest of every entity it touched (the M1
    lesson). ``entity_id`` is a resolved page stem; ``--`` keeps it a path.
    ``({}, False)`` on a non-git bank or a git failure — provenance never
    blocks on history.
    """
    limit = MAX_PROVENANCE_COMMITS if limit is None else max(1, int(limit))
    if not (Path(memory_path) / ".git").exists():
        return {}, False
    try:
        out = await _run_git(
            memory_path, "log", f"-n{limit + 1}",
            f"--format=%x1e%(trailers:key={AUTHOR_TRAILER},valueonly,separator=%x1f)",
            "--", f"entities/{entity_id}.md",
        )
    except GitError:
        return {}, False
    records = out.split("\x1e")[1:]
    counts: dict[str, int] = {}
    for record in records[:limit]:
        authors = [a.strip() for a in record.strip("\n").split("\x1f") if a.strip()] or [UNKNOWN_AUTHOR]
        for author in dict.fromkeys(authors):
            counts[author] = counts.get(author, 0) + 1
    return counts, len(records) > limit


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
    """Build a human-readable description from commit message. An agent's page edit (G198) adds its reason."""
    reason = next((line[len("Reason: "):].strip() for line in body.splitlines() if line.startswith("Reason: ")), "")
    # Look for entity-specific line in body
    for line in body.splitlines():
        if entity_id in line.lower():
            return f"{line.strip()} — {reason}" if reason else line.strip()
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
    # field separator: <RS> hash <US> date <US> body <US>, then the commit's
    # changed paths (``--name-only``). One git process for the whole history
    # (2026-10-16 perf): a ``git diff-tree`` per commit cost ~18 s on a
    # 1,043-commit synthetic bank, paid again on every commit since the ETag is
    # HEAD. ``--root`` lists the first commit's files and ``--no-renames``
    # lists a rename's two paths, as ``diff-tree -r --root`` did; a merge
    # lists no files under either.
    sep = "\x1f"
    rec = "\x1e"
    try:
        out = await _run_git(
            memory_path,
            "log",
            f"--format={rec}%H{sep}%ad{sep}%b{sep}",
            "--date=short",
            "--name-only",
            "--root",
            "--no-renames",
            # A `log.showSignature` config prints each signed commit's check
            # before its record, which would land in the previous commit's
            # file list.
            "--no-show-signature",
        )
    except GitError:
        return []

    # author -> aggregation state
    agg: dict[str, dict] = {}

    for record in out.split(rec):
        if not record.strip():
            continue
        fields = record.split(sep, 3)
        if len(fields) < 4:
            continue
        commit_hash, date, body, tail = fields[0].strip(), fields[1].strip(), fields[2], fields[3]
        if not commit_hash:
            continue

        authors = _parse_authors(body) or [UNKNOWN_AUTHOR]
        files = [f for f in tail.strip().splitlines() if f]

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


async def top_written_entities(memory_path: Path, *, limit: int = 10) -> tuple[list[dict], int]:
    """Entity pages ranked by how many commits touched them (G124 R13).

    Engine-free: one ``git log --name-only`` over the last
    ``TOP_ENTITIES_LOG_WINDOW`` commits; every ``entities/*.md`` path counts
    once per commit. Returns ``(rows, commits_scanned)``; rows are
    ``{entity_id, commits, last_written}`` sorted by commits desc, then
    newest, then id. ``([], 0)`` for a non-git directory.
    """
    if not (memory_path / ".git").exists():
        return [], 0
    rec = "\x1e"
    try:
        out = await _run_git(
            memory_path, "log", f"--max-count={TOP_ENTITIES_LOG_WINDOW}",
            f"--format={rec}%ad", "--date=short", "--name-only",
        )
    except GitError:
        return [], 0
    counts: dict[str, int] = {}
    last: dict[str, str] = {}
    scanned = 0
    for record in out.split(rec):
        if not record.strip():
            continue
        scanned += 1
        date_str, _, tail = record.partition("\n")
        date_str = date_str.strip()
        for line in tail.splitlines():
            f = line.strip()
            if f.startswith("entities/") and f.endswith(".md"):
                entity_id = f[len("entities/"):-len(".md")].rsplit("/", 1)[-1]
                counts[entity_id] = counts.get(entity_id, 0) + 1
                if date_str > last.get(entity_id, ""):
                    last[entity_id] = date_str
    rows = [{"entity_id": eid, "commits": n, "last_written": last[eid]} for eid, n in counts.items()]
    # Two stable sorts: newest first, then commits desc — so ties on commit
    # count show the page that was written most recently first, then by id.
    rows.sort(key=lambda r: (r["last_written"], r["entity_id"]), reverse=True)
    rows.sort(key=lambda r: -r["commits"])
    return rows[: max(1, int(limit or 10))], scanned


_MANIFEST_LINE_RE = re.compile(r"^(?P<path>[^:\s][^:]*?):\s+(?P<action>\w+)\s*\((?P<rest>.*)\)\s*$")
_ENTITY_PATH_RE = re.compile(r"^entities/(?P<id>.+)\.md$")
MAX_DETAIL_ENTITIES = 200


@dataclass
class CycleManifest:
    entities: list[dict]
    files: list[str]
    episodes: list[str]
    inbox_changes: int
    authors: list[str]
    sessions: list[str]
    engine: str | None


def parse_cycle_body(subject: str, body: str) -> CycleManifest:
    """Read a Sleep-cycle commit body back into counts (G125 R4).

    The body is what ``sleep_cycle._finalize`` wrote: one ``<path>: <action>
    (source: <ep|n/a>, trigger: <t>[, sessions: …])`` line per file, then the
    trailer block. ``n/a`` is not an episode. Unknown lines are ignored so a
    legacy or hand-written commit degrades to zeros rather than an error.
    """
    entities: list[dict] = []
    files: list[str] = []
    episodes: list[str] = []
    seen_eps: set[str] = set()
    inbox_changes = 0
    engine: str | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith(f"{ENGINE_TRAILER}:"):
            engine = line.split(":", 1)[1].strip() or None
            continue
        m = _MANIFEST_LINE_RE.match(line)
        if not m:
            continue
        path = m.group("path").strip()
        files.append(path)
        fields = {}
        for part in m.group("rest").split(","):
            if ":" in part:
                k, v = part.split(":", 1)
                fields[k.strip()] = v.strip()
        source = fields.get("source")
        source = None if not source or source == "n/a" else source
        if path.startswith("inbox/"):
            inbox_changes += 1
        em = _ENTITY_PATH_RE.match(path)
        if em:
            entities.append({"id": em.group("id"), "action": m.group("action"),
                             "source_episode": source, "trigger": fields.get("trigger", "")})
            if source and source not in seen_eps:
                seen_eps.add(source)
                episodes.append(source)
    return CycleManifest(entities=entities, files=files, episodes=episodes, inbox_changes=inbox_changes,
                         authors=_parse_authors(body), sessions=_parse_sessions(body), engine=engine)


def _cycle_kind(subject: str) -> str | None:
    s = subject.lower()
    if s.startswith("sleep cycle"):
        return "decay" if s.rstrip().endswith("(decay)") else "sleep"
    if s.startswith("inbox resolution"):
        return "inbox"
    return None


#: The action words a manifest line uses for a page that commit made: ``create`` is what Sleep writes (the change's own
#: action, ``sleep_cycle._finalize``); ``created`` what other writers and older commits wrote.
CREATED_ACTIONS = frozenset({"create", "created"})


def _entry_from(commit_hash: str, date: str, subject: str, body: str) -> SleepHistoryEntry:
    m = parse_cycle_body(subject, body)
    return SleepHistoryEntry(
        commit_hash=commit_hash, date=date, message=subject, files_changed=m.files, engine=m.engine,
        kind=_cycle_kind(subject) or "sleep",
        entities_created=sum(1 for e in m.entities if e["action"] in CREATED_ACTIONS),
        entities_updated=sum(1 for e in m.entities if e["action"] not in CREATED_ACTIONS),
        episodes=len(m.episodes), sessions=len(m.sessions), authors=m.authors,
    )


_history_cache: dict[tuple[str, str, int], list[SleepHistoryEntry]] = {}


async def get_sleep_history(memory_path: Path, limit: int = 15) -> list[SleepHistoryEntry]:
    """The last ``limit`` consolidations, newest first (G125 R4).

    One ``git log -n <limit>`` filtered by git's own ``--grep`` (the two
    subjects a consolidation can carry), with bodies parsed HERE — the body
    never leaves the process (the M1 lesson in the 2026-09-01 review: ``%b``
    over the wire grew this endpoint to 378 KB for eight commits). The
    filter lives in git, not in a Python pass over a ``limit * k`` window:
    measured on the live bank 2026-09-05, the top of history was a run of
    State-snapshot / inbox / docs commits longer than ``limit * 3``, so
    ``?limit=2`` answered ``[]`` while ``?limit=15`` found cycles — a bounded
    window that is not a *matching* window is a wrong answer, not a cheap
    one. ``-n`` now counts only matching commits, so the window is exact.
    Cached per ``(memory_path, HEAD, limit)`` so a Sleep page poll costs no
    subprocess until HEAD moves. Durations are joined from the ledger (R5).

    ``--date=iso-strict`` (R-A11): the row needs a time of day. git renders it
    in the COMMIT's own zone, so the client parses the offset rather than
    assuming UTC; the telemetry bound below slices to ``[:10]`` because
    ``date.fromisoformat`` rejects a datetime string (measured, CPython
    3.12.11 — unsliced, this endpoint and ``get_sleep_cycle_detail`` both 500
    the moment the format changes).
    """
    from api.services import cycle_usage, sleep_history, sync_service, telemetry

    limit = max(1, int(limit))
    key = (str(memory_path), sync_service.git_head(memory_path), limit)
    cached = _history_cache.get(key)
    if cached is None:
        sep, rec = "\x1f", "\x1e"
        try:
            output = await _run_git(
                memory_path, "log", f"-n{limit}",
                "--regexp-ignore-case", "--grep=^Sleep cycle", "--grep=^Inbox resolution",
                f"--format=%H{sep}%ad{sep}%s{sep}%b{rec}", "--date=iso-strict",
            )
        except GitError:
            return []
        entries: list[SleepHistoryEntry] = []
        for record in output.split(rec):
            if not record.strip():
                continue
            fields = record.strip("\n").split(sep, 3)
            if len(fields) < 4 or _cycle_kind(fields[2].strip()) is None:
                continue
            entries.append(_entry_from(fields[0].strip(), fields[1].strip(), fields[2].strip(), fields[3]))
            if len(entries) >= limit:
                break
        # No `.clear()`: this is a multi-key cache — the SAME shape as
        # `status._last_sleep_cache` — keyed on `(memory_path, head, limit)`
        # (R4). Wiping the dict on every miss would make two different
        # `limit`s at the SAME head evict each other forever, contradicting
        # "cached per (memory_path, git_head, limit)" above. Unbounded
        # growth is accepted the same way `_last_sleep_cache` accepts it:
        # trivially small at personal scale (one entry per unique head this
        # process has ever seen `/sleep/history` called against).
        _history_cache[key] = entries
        cached = entries
    out = [e.model_copy() for e in cached]
    # Bound the telemetry join the same way the git side is bounded: only
    # scan months that could possibly contain one of THESE entries' commits,
    # never the whole machine-global ledger (the exact class of cost this
    # function's own docstring above warns against for `%b` — a call site
    # that grows with the SIZE of everything that ever happened, not with
    # what this request actually needs). Nothing to join → skip the read.
    if out:
        # A day early: a cycle that ran across midnight UTC has calls on the
        # day before its commit. One ledger read serves both joins.
        oldest = min(date.fromisoformat(e.date[:10]) for e in out) - timedelta(days=1)
        events = telemetry.read_events(start=oldest)
        sleep_history.attach_durations(out, events)
        cycle_usage.attach_usage(out, events, memory_path=memory_path)
    return out


async def get_sleep_cycle_detail(memory_path: Path, commit: str) -> SleepCycleDetail | None:
    """``GET /sleep/history/{commit}`` (G125). ``None`` when the hash is not
    a Sleep/inbox commit — never a diff, never the raw body.

    ``--date=iso-strict`` and the ``[:10]`` slice on the telemetry bound are
    the same pair as in ``get_sleep_history`` above, and for the same reason —
    they must move together or this endpoint raises ``ValueError``."""
    from api.services import cycle_usage, sleep_history, telemetry

    if not re.fullmatch(r"[0-9a-f]{7,40}", commit or ""):
        return None
    try:
        output = await _run_git(memory_path, "show", "-s", "--format=%H%x1f%ad%x1f%s%x1f%b", "--date=iso-strict", commit)
    except GitError:
        return None
    fields = output.strip("\n").split("\x1f", 3)
    if len(fields) < 4 or _cycle_kind(fields[2].strip()) is None:
        return None
    base = _entry_from(fields[0].strip(), fields[1].strip(), fields[2].strip(), fields[3])
    manifest = parse_cycle_body(fields[2].strip(), fields[3])
    detail = SleepCycleDetail(
        **base.model_dump(),
        entities=[SleepCycleEntity(**e) for e in manifest.entities[:MAX_DETAIL_ENTITIES]],
        truncated=len(manifest.entities) > MAX_DETAIL_ENTITIES,
        episodes_by_origin=sleep_history.episodes_by_origin(memory_path, manifest.episodes),
        inbox_changes=manifest.inbox_changes,
    )
    events = telemetry.read_events(start=date.fromisoformat(detail.date[:10]) - timedelta(days=1))
    sleep_history.attach_durations([detail], events)
    cycle_usage.attach_usage([detail], events, detail=True, memory_path=memory_path)
    return detail


async def commit_changes(memory_path: Path, message: str) -> str | None:
    """Stage all changes and commit. Returns the new commit hash, or ``None``
    when there was nothing to commit. Runs in a worker thread under the bank's
    one write lock (R-B4)."""
    return await asyncio.to_thread(commit_changes_sync, memory_path, message)


async def commit_paths(memory_path: Path, message: str, paths: list[str]) -> None:
    """Stage and commit ONLY ``paths`` (memory-relative), never ``git add -A`` —
    :func:`commit_paths_sync` in a worker thread (R-B4)."""
    if not paths:
        return
    await asyncio.to_thread(commit_paths_sync, memory_path, message, list(paths))


async def is_tracked(memory_path: Path, rel: str) -> bool:
    """Is `rel` in the bank's index? A read (R-B3). The picture writer stages a removal only for a file git knows:
    `git add -- <path>` refuses a pathspec that matches nothing (G146 plan R-PE8)."""
    try:
        return bool((await _run_git(Path(memory_path), "ls-files", "--", rel)).strip())
    except GitError:
        return False


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
    *,
    change: str = "updated",
    paths: list[str] | None = None,
    before: dict[str, bytes | None] | None = None,
    relayed_by: str | None = None,
    sessions: list[str] | None = None,
) -> None:
    """Commit after an inbox (nudge/clarification/conflict) resolution.

    Emits a structured "Inbox resolution <date>" subject so the resolution
    surfaces in ``get_sleep_history`` (the Sleep dashboard) — the old
    single-line subject was never matched by the history filter. ``extra_lines``
    appends further per-file manifest lines (G60: one per closed claim's page).

    ``change`` is the manifest verb for the entity's own line (default
    ``updated``). G113 R2: a decay archive/keep passes ``status archived`` /
    ``status active`` so ``_infer_change_type``'s existing ``"status"`` branch
    classifies the commit as ``statusChange`` — an enum the app already decodes
    — instead of inventing a new change type.

    Audit 2026-10-05 P1-3: it commits ONLY the files the answer wrote — the
    entity's page, every manifest line's file and ``paths`` (the item file) —
    never ``git add -A``: an unrelated dirty episode or page is not the
    person's answer. An edit already on one of those files before the answer
    (``before``, from :func:`snapshot_dirty`) is committed first on its own,
    with no author claimed (:func:`commit_touched_sync`).
    """
    await asyncio.to_thread(commit_resolution_sync, memory_path, entity_id, trigger, extra_lines,
                            change=change, paths=paths, before=before, relayed_by=relayed_by, sessions=sessions)


def commit_resolution_sync(
    memory_path: Path,
    entity_id: str,
    trigger: str,
    extra_lines: list[str] | None = None,
    *,
    change: str = "updated",
    paths: list[str] | None = None,
    before: dict[str, bytes | None] | None = None,
    relayed_by: str | None = None,
    sessions: list[str] | None = None,
) -> None:
    """:func:`commit_resolution` for a resolver that already holds the bank's
    page lock in a worker thread and commits inside it (G98/G115: a
    normalization answer's pages, map and item are one critical section)."""
    date_str = date.today().isoformat()
    from api.services import inbox_actor

    # Ruling 29: Sleep settles through the same resolvers; the commit then names Sleep, never the person.
    actor = inbox_actor.current()
    trigger = inbox_actor.trigger(trigger)
    # trigger is "inbox/<kind>/resolved[:<label>]" — tag the kind into the
    # subject so the dashboard can distinguish a conflict adjudication from a
    # decay archive. G113 R1: the ``:<label>`` suffix names the action the user
    # took; nothing parses it (this split reads only the kind segment), so it is
    # inert to every existing reader and `git log` alone can answer "did the
    # user agree?".
    kind = ""
    parts = trigger.split("/")
    if len(parts) >= 2 and parts[0] == "inbox":
        kind = parts[1]
    what = "Inbox settled by Sleep" if actor is not None else "Inbox resolution"
    subject = f"{what} ({kind}) {date_str}" if kind else f"{what} {date_str}"
    body_lines = [f"entities/{entity_id}.md: {change} (trigger: {trigger})"]
    # The manifest is a SET of file lines: a caller that closes N claims on one
    # page must not repeat that page's line N times.
    for line in [*(extra_lines or []), *(actor.extra_lines if actor is not None else [])]:
        line = inbox_actor.trigger(line) if actor is not None else line
        if line not in body_lines:
            body_lines.append(line)
    # An inbox resolution is a user/companion-app action -> attribute to "user". An answer an agent relayed from a
    # conversation (owner, 2026-10-14) also names that agent and the conversation, so git says who carried it.
    # Sleep's settle (ruling 29) is Sleep's: the model that judged it, or `cicada` for an engine-free rule.
    authors = list(actor.authors) if actor is not None else ["user", *([relayed_by] if relayed_by else [])]
    message = build_commit_message(subject, body_lines, authors=authors, sessions=sessions,
                                   engine=actor.engine if actor is not None else None)
    touched = [line.split(": ", 1)[0].strip() for line in body_lines if ": " in line]
    touched += list(paths or [])
    if actor is not None:
        touched += list(actor.extra_paths)
        inbox_actor.write_record(actor)
    commit_touched_sync(memory_path, message, touched, before=before,
                        kept_subject=f"Uncommitted edit kept apart {date_str}", kept_trigger="inbox/kept-apart")
    if actor is not None:
        actor.committed = True


# G147 — the manifest line `commit_resolution` writes for a decay answer. Its
# parser lives HERE, beside its producer, so the two cannot drift.
_DECAY_VERDICT_RE = re.compile(
    r"^entities/(?P<id>[^\s/]+)\.md: [^\n]*"
    r"\(trigger: inbox/decay/resolved:(?P<label>archive|keep_active)\)\s*$",
    re.MULTILINE,
)
_decay_verdict_cache: dict[tuple[str, str, str], dict[str, str]] = {}


async def decay_verdicts(memory_path: Path, *, since: date) -> dict[str, str]:
    """``{entity_id: label}`` — each page's LATEST decay answer committed since
    ``since`` (G147, plan R-FD6). ``archive`` / ``keep_active`` only: a
    ``remind_later`` is a deferral (``inbox/deferred``), never a verdict.

    Git's own ``--grep`` filters, as in :func:`get_sleep_history` — a bounded
    window that is not a matching window is a wrong answer, not a cheap one —
    and the body never leaves this function. Newest first, so the first line
    seen per page wins. ``--since`` ends the walk at the first commit older
    than the cutoff, so a clock-skewed old commit near HEAD would hide answers
    behind it — the same answer ``git log --since`` gives anywhere, accepted
    rather than walking all history. Cached per (bank, HEAD, since); the cache
    grows one entry per HEAD per day at most, the `_history_cache` trade-off.
    """
    from api.services import sync_service

    head = sync_service.git_head(memory_path)
    key = (str(memory_path), head, since.isoformat())
    # An empty HEAD (no commit yet, or a worktree/submodule bank whose `.git`
    # is a file `git_head` does not follow) cannot key a cache: it would
    # never move, and an answer given later today would stay invisible.
    cached = _decay_verdict_cache.get(key) if head else None
    if cached is not None:
        return dict(cached)
    try:
        output = await _run_git(
            memory_path, "log", f"--since={since.isoformat()}T00:00:00",
            "--fixed-strings", "--grep=inbox/decay/resolved:", "--format=%x1e%B",
        )
    except GitError:
        return {}
    latest: dict[str, str] = {}
    for record in output.split("\x1e"):
        for match in _DECAY_VERDICT_RE.finditer(record):
            latest.setdefault(match.group("id"), match.group("label"))
    if head:
        _decay_verdict_cache[key] = latest
    return dict(latest)
