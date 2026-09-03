"""``<bank>/_state.md`` — the live state dictionary (G53).

MHS's state-dictionary idea, ported: one small, documented, *live* object a
fresh agent reads at session start. Cicada's version is a **cursor into the
graph** — ids, names, one-liners already on entity pages, counts and enums —
never a copy of it (G53: "not a cache of entity pages"). Everything here is
derived from frontmatter the bank already holds, so regeneration is zero-LLM
and cheap enough to run on every Sleep tail and lazily on every read.

Three rails, each from a review that cost something:

* **Deterministic and debounced (R1).** ``inputs_version`` digests the
  ``sync_service`` components the file is built from; ``refresh`` skips a
  rebuild when nothing changed, and a forced rebuild writes only when the
  rendering differs with ``generated_at`` masked. An idle night therefore
  makes no commit, and two runs on a still bank are byte-identical.
* **Bounded probes.** Repo state is live (``repo_context``) but under one
  total budget (``REPO_BUDGET_S``); a repo past the budget is recorded as
  ``state: unavailable`` and never probed. ``sleep.last_at`` is one
  ``git log`` with a timeout, ``check=False``, never raising.
* **Never persisted: ``resumable`` (G48) or anything not already on a page.**
  Conversations carry id/harness/title/last_seen/episode_count; the API adds
  ``resumable`` per request. No transcript content, no claim text, no secret
  (engine *model names* and connection *ids* only).

The file is a projection, never a source of truth: a reader that finds it
stale (``generated_at``) must still work, and every field has a live twin
(``/status``, ``/inbox``, ``/conversations/recent``, ``cicada_repo_context``).

This module is the ONLY writer of ``_state.md`` (R1: two schedulers of
regeneration — Sleep's tail and the lazy read path — one writer), and
``refresh_and_commit`` is the ONLY committer: every regeneration that
touched the file lands in its own ``State snapshot`` commit authored
``cicada`` before it returns. Final review (2026-09-03) reproduced why a
write left dirty is not harmless: ``git_service.commit_changes`` is
``git add -A`` and is what an inbox resolution, ``POST /capture/telegram``,
the notes sync, ``PATCH /entities/{id}/repos`` and ``POST /sources/poll-feeds``
all commit through, so a projection dirtied by ``GET /state`` was swept into
the NEXT user write — an ``Inbox resolution`` commit under
``Cicada-Author: user`` carrying 13 lines of ``_state.md`` — far more often
than Sleep's tail ever got to claim it. That is the G85-class smear R2/R3
exist to prevent, on the read path. The MCP server only ever reads the file
(R4), so an agent connecting never dirties the bank with a projection.

``sleep.next_at`` is deliberately NOT in the file: with a schedule enabled it
advances every day, so a forced tail rebuild on an otherwise idle bank would
write and commit a ``State snapshot`` every night — the exact R1 promise
("an idle night makes no commit") broken under the live configuration. It is
added per request by ``GET /state`` (local clock, like ``/status``), the
same way ``resumable`` is (R5).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import subprocess
import time
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from api.services import bank_index, inbox_service, markdown_parser, session_stats, sync_service
from api.services.claims import strip_claims_block
from api.services.hub_builder import _one_line_summary

STATE_FILENAME = "_state.md"
SCHEMA_VERSION = 1
# R10: the handshake primer that embeds this file is budgeted at ~1,800
# tokens; 6 KiB of cursor leaves room for the contract text around it.
MAX_BYTES = 6 * 1024
TITLE_LIMIT = 60
ONE_LINER_LIMIT = 120
REPO_BUDGET_S = 2.0
GIT_TIMEOUT_S = 2.0
# The sync components the file is a function of. `bank` is included so a
# bank switch can never serve another bank's cursor from a stale digest.
# `git_head` is deliberately NOT: this file's own `State snapshot` commit
# moves HEAD, so a digest over it would invalidate itself every cycle and
# commit forever (R1). `sleep.last_at` only changes with a `Sleep cycle`
# commit, which never lands without an entity/episode/inbox change.
INPUT_COMPONENTS = ("entities", "inbox", "episodes", "bank")
# G121 in one sentence — the handshake carries this verbatim (single source).
WORLD_FACTS_NOTE = (
    "Personal facts (what the person said, did or decided) are authoritative; "
    "world facts on a page are a dated cache — verify before acting on them."
)
_ARCHIVED = {"archived", "dropped"}
_DEFAULTS = {"state_projects": 7, "state_people": 7, "state_preferences": 5, "state_conversations": 5}

RepoResolver = Callable[..., dict]


def state_path(memory_path: Path) -> Path:
    return Path(memory_path) / STATE_FILENAME


def inputs_version(memory_path: Path) -> str:
    comps = sync_service.components(Path(memory_path))
    parts = {k: comps.get(k, "") for k in INPUT_COMPONENTS}
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def read_state(memory_path: Path) -> dict | None:
    """Parsed frontmatter plus ``body``; ``None`` when absent or unparseable."""
    path = state_path(memory_path)
    if not path.exists():
        return None
    try:
        parsed = markdown_parser.parse(path)
    except Exception as exc:
        logger.warning(f"_state.md unreadable: {type(exc).__name__}: {exc}")
        return None
    if parsed.frontmatter.get("type") != "state":
        return None
    out = dict(parsed.frontmatter)
    out["body"] = parsed.body
    return out


# --- ranking ----------------------------------------------------------------


def _days_since(value: Any, today: date) -> float:
    try:
        d = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return 365.0
    return max(0.0, float((today - d).days))


def _score(fm: dict, today: date) -> float:
    """R6: ``confidence × 1/(1 + days_since_last_referenced/30)`` — a stale
    high-confidence page ranks below a fresh middling one; ties break on id
    in ``_ranked`` so two runs on a still bank order identically."""
    try:
        confidence = float(fm.get("confidence", 0.5) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence / (1.0 + _days_since(fm.get("last_referenced"), today) / 30.0)


def _ranked(memory_path: Path, etype: str, today: date, n: int) -> list[bank_index.IndexedFile]:
    """Top-``n`` live pages of one type from the frontmatter cache — bodies
    are parsed only for the rows that survive (never the whole bank)."""
    rows = []
    for f in bank_index.files(memory_path, "entities"):
        fm = f.frontmatter
        if str(fm.get("type", "") or "") != etype:
            continue
        if str(fm.get("status", "active") or "active").lower() in _ARCHIVED:
            continue
        rows.append((-_score(fm, today), f.stem, f))
    rows.sort(key=lambda r: (r[0], r[1]))
    return [r[2] for r in rows[: max(0, n)]]


def _name(f: bank_index.IndexedFile) -> str:
    return str(f.frontmatter.get("name") or f.stem.replace("-", " ").title())


def _one_liner(f: bank_index.IndexedFile) -> str:
    """First sentence of ``## Summary`` with the claims fence stripped FIRST
    (``claims.strip_claims_block``): ``parse_sections`` runs a section to EOF,
    so on a page whose fence follows the summary the fence sits inside it —
    the "never claim text" rail must not rest on a first-sentence split."""
    try:
        return _one_line_summary(strip_claims_block(f.body()), limit=ONE_LINER_LIMIT)
    except Exception:
        return ""


# --- blocks -----------------------------------------------------------------


def _unavailable(path: str, state: str = "unavailable") -> dict:
    return {"path": path, "branch": None, "dirty": None, "ahead_behind": None, "state": state}


def _repo_blocks(
    declared: list, *, resolver: RepoResolver | None, budget: list[float], previous: dict[str, dict] | None,
) -> list[dict]:
    """One block per declared repo, live-probed under the shared budget.

    ``budget`` is a one-element list (remaining seconds) shared across every
    project so the WHOLE file costs at most ``REPO_BUDGET_S`` of git. A repo
    that would start past the budget is recorded ``unavailable`` — the
    honest answer, and cheaper than a timeout. With ``resolver=None`` the
    previous file's block for that path is carried over (R4: a read-side
    refresh never pays for git).
    """
    out: list[dict] = []
    for decl in declared or []:
        if not isinstance(decl, dict) or not decl.get("path"):
            continue
        path = str(decl["path"])
        if resolver is None:
            prev = (previous or {}).get(path)
            out.append(prev or _unavailable(path))
            continue
        remaining = budget[0]
        if remaining <= 0.05:
            out.append(_unavailable(path))
            continue
        started = time.monotonic()
        try:
            ctx = resolver(decl, timeout_s=min(remaining, 2.0))
        except Exception as exc:  # a probe must degrade one block, never the file
            logger.warning(f"repo probe failed for a declared repo: {type(exc).__name__}")
            ctx = {"path": path, "status": "git_unavailable"}
        budget[0] -= time.monotonic() - started
        status = str(ctx.get("status") or "unavailable")
        if status == "ok":
            ahead, behind = ctx.get("ahead"), ctx.get("behind")
            out.append({
                "path": path,
                "branch": ctx.get("current_branch"),
                "dirty": ctx.get("dirty_files"),
                "ahead_behind": None if ahead is None and behind is None else f"{ahead or 0}/{behind or 0}",
                "state": "ok",
            })
        else:
            out.append(_unavailable(path, status))
    return out


def _engine_block(settings, connected_ids: list[str] | None) -> dict:
    """Configuration, never a probe (R7) — the registry's cached ids are the
    only 'live' part, and they are cache-only. Every read is ``getattr`` with
    a default so the hermetic ``SimpleNamespace`` settings the Sleep tests
    pass keep working."""
    from api.services import engine_select

    mode = str(getattr(settings, "llm_mode", None) or "byok").strip().lower()
    engine = engine_select.engine_label(settings) if settings is not None else "litellm"
    if mode == "agent":
        model = getattr(settings, "agent_model", None)
    elif mode == "local":
        model = f"ollama/{getattr(settings, 'ollama_model', 'llama3.1')}"
    else:
        model = getattr(settings, "effective_consolidation_model", None) or getattr(settings, "litellm_model", None)
    return {"mode": mode, "engine": engine, "model": model or None, "connected": list(connected_ids or [])}


def _default_git_runner(memory_path: Path, args: list[str]) -> str | None:
    """One bounded, sync ``git`` call (R8): ``check=False``, a timeout, and
    ``None`` for every failure — a bank without git still gets a file."""
    try:
        proc = subprocess.run(["git", *args], cwd=str(memory_path), capture_output=True, text=True,
                              timeout=GIT_TIMEOUT_S, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def _sleep_block(memory_path: Path, git_runner) -> dict:
    """``last_at`` + ``queue_depth`` only. ``next_at`` is a clock, not a
    belief: it moves every day on a bank with a schedule, which would make
    an idle night's forced rebuild differ under ``_masked`` and commit (R1,
    final review). ``GET /state`` adds it per request from
    ``sleep_scheduler.next_run_at`` — on the LOCAL clock the schedule's
    hours are expressed in, where the old in-file value fed a UTC wall time
    and could name a time already past."""
    out = git_runner(memory_path, ["log", "-1", "--grep=^Sleep cycle", "--format=%aI"])
    last_at = (out or "").strip() or None
    queue = sum(1 for f in bank_index.files(memory_path, "episodes") if not f.frontmatter.get("processed", False))
    return {"last_at": last_at, "queue_depth": queue}


def _inbox_block(memory_path: Path) -> dict:
    """Exactly what ``GET /inbox`` would show. ``inbox_service.load_inbox``
    hides deferred items AND (G98) items whose subject is archived/dropped/
    gone, so the cursor never advertises a question the app would not.
    ``load_inbox`` reads the wall clock for deferral; the ``inbox`` sync
    component folds today's date in whenever a deferral is pending
    (sync_service.py:145), so the digest and this count move together."""
    by_kind: Counter = Counter()
    for item in inbox_service.load_inbox(memory_path):
        if item.status != "pending":
            continue
        by_kind[str(getattr(item.kind, "value", item.kind) or "decay")] += 1
    return {"pending": sum(by_kind.values()), "by_kind": dict(sorted(by_kind.items()))}


def cached_connected_ids(settings) -> list[str]:
    """Connection ids from the registry's status cache — cache-only, never a
    vendor-CLI shell-out (R7). ``[]`` when the cache is cold or when
    ``settings`` is a hermetic stand-in the registry cannot take. Shared by
    Sleep's tail and ``GET /state`` so the two writers agree on content."""
    try:
        from api.services.connections.registry import get_registry

        return sorted(c.id for c in get_registry(settings).cached_statuses() if c.connected)
    except Exception:
        return []


def _conversations(memory_path: Path, n: int) -> list[dict]:
    """R5: ``resumable`` is computed per request by the API and never lands
    here — the injected ``transcript_exists`` is a constant so the aggregator
    never even stats a transcript path on the builder's behalf."""
    rows = session_stats.aggregate_conversations(memory_path, limit=max(1, n), transcript_exists=lambda *_: False)
    return [{"id": r["conversation_id"], "harness": r["harness"], "title": r["title"][:TITLE_LIMIT],
             "last_seen": r["last_seen"], "episode_count": r["episode_count"]} for r in rows]


# --- build / render -----------------------------------------------------------


def _now() -> datetime:
    """The one clock ``build`` defaults to (aware UTC). A seam, so a test can
    run "the next night" against a still bank and assert nothing is written —
    the idle-night rail (R1) is only real if it holds across a date change."""
    return datetime.now(timezone.utc)


def _limit(settings, key: str) -> int:
    try:
        return int(getattr(settings, key, _DEFAULTS[key]) or _DEFAULTS[key])
    except (TypeError, ValueError):
        return _DEFAULTS[key]


def build(
    memory_path: Path,
    settings=None,
    *,
    today: date | None = None,
    now: datetime | None = None,
    probe_repos: bool = True,
    previous: dict | None = None,
    repo_resolver: RepoResolver | None = None,
    git_runner=None,
    connected_ids: list[str] | None = None,
    repo_budget_s: float | None = None,
) -> tuple[dict, str]:
    """Render the state dictionary. Pure given its seams; never calls an LLM."""
    memory_path = Path(memory_path)
    now = now or _now()
    # The local calendar date of `now` — `date.today()` in production, and
    # the injected clock's date under test, so the two never disagree.
    today = today or now.astimezone().date()
    git_runner = git_runner or _default_git_runner
    if probe_repos and repo_resolver is None:
        from api.services.repo_context import resolve_repo_context
        repo_resolver = resolve_repo_context
    resolver = repo_resolver if probe_repos else None
    prev_repos: dict[str, dict] = {}
    for p in (previous or {}).get("projects", []) or []:
        for r in p.get("repos", []) or []:
            if r.get("path"):
                prev_repos[str(r["path"])] = dict(r)
    # Read the module constant at call time (not as a default-arg binding) so
    # a test can monkeypatch `REPO_BUDGET_S` to 0.0 and probe nothing.
    budget = [float(REPO_BUDGET_S if repo_budget_s is None else repo_budget_s)]

    projects = []
    for f in _ranked(memory_path, "project", today, _limit(settings, "state_projects")):
        projects.append({
            "id": f.stem, "name": _name(f), "one_liner": _one_liner(f),
            "confidence": round(float(f.frontmatter.get("confidence", 0.5) or 0.0), 2),
            "last_referenced": str(f.frontmatter.get("last_referenced") or "")[:10] or None,
            "repos": _repo_blocks(f.frontmatter.get("repos") or [], resolver=resolver, budget=budget, previous=prev_repos),
        })
    people = [{"id": f.stem, "name": _name(f), "one_liner": _one_liner(f),
               "last_referenced": str(f.frontmatter.get("last_referenced") or "")[:10] or None}
              for f in _ranked(memory_path, "person", today, _limit(settings, "state_people"))]
    preferences = [{"id": f.stem, "name": _name(f), "one_liner": _one_liner(f)}
                   for f in _ranked(memory_path, "skill", today, _limit(settings, "state_preferences"))]

    fm: dict = {
        "type": "state",
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(),
        "inputs_version": inputs_version(memory_path),
        "bank": memory_path.name,
    }
    # Portability rail: the owner is an entity id from config, never a name
    # in code, and only when that page actually exists in this bank.
    owner = str(getattr(settings, "observer_owner", "") or "").strip()
    if owner and (memory_path / "entities" / f"{owner}.md").exists():
        fm["owner_id"] = owner
    fm.update({
        "engine": _engine_block(settings, connected_ids),
        "sleep": _sleep_block(memory_path, git_runner),
        "inbox": _inbox_block(memory_path),
        "projects": projects,
        "people": people,
        "conversations": _conversations(memory_path, _limit(settings, "state_conversations")),
        "preferences": preferences,
        "repos_probed_at": now.isoformat() if resolver is not None else (previous or {}).get("repos_probed_at"),
        "world_facts_note": WORLD_FACTS_NOTE,
    })
    _fit(fm)
    return fm, render_body(fm)


def render_body(fm: dict) -> str:
    """The human-readable half: a cursor (wikilinks + ids), never entity bodies."""
    lines = ["# Cicada — now", "",
             f"Bank `{fm['bank']}` · engine {fm['engine']['engine']} ({fm['engine']['model'] or 'unset'}) · "
             f"inbox {fm['inbox']['pending']} pending · queue {fm['sleep']['queue_depth']} · "
             f"last Sleep {fm['sleep']['last_at'] or 'never'} · as of {fm['generated_at']}",
             "", "## Projects"]
    for p in fm["projects"]:
        repo_bits = ", ".join(
            f"{r['path']}@{r['branch']}" + (f" (dirty {r['dirty']})" if r.get("dirty") else "")
            if r.get("state") == "ok" else f"{r['path']} ({r.get('state')})" for r in p.get("repos", [])
        )
        tail = f" — {p['one_liner']}" if p.get("one_liner") else ""
        lines.append(f"- [[{p['name']}]] (`{p['id']}`){tail}" + (f" — repo: {repo_bits}" if repo_bits else ""))
    if not fm["projects"]:
        lines.append("- (no active projects yet)")
    lines += ["", "## People"]
    lines += [f"- [[{p['name']}]] (`{p['id']}`)" + (f" — {p['one_liner']}" if p.get("one_liner") else "") for p in fm["people"]] or ["- (none yet)"]
    lines += ["", "## Recent conversations"]
    lines += [f"- `{c['id']}` · {c['harness'] or 'unknown'} · {c['title']} · {c['last_seen'][:10]}" for c in fm["conversations"]] or ["- (none recorded)"]
    lines += ["", "## Preferences"]
    lines += [f"- [[{p['name']}]] (`{p['id']}`)" + (f" — {p['one_liner']}" if p.get("one_liner") else "") for p in fm["preferences"]] or ["- (none extracted yet)"]
    lines += ["", "## Rules for agents",
              f"- {fm['world_facts_note']}",
              "- This file is a cursor: open `entities/<id>.md` (or `cicada_recall_detail`) for the page; `_index.md` is the map.",
              "- Never edit entity files directly — write through `cicada_write_claim` / `cicada_save_episode`."]
    return "\n".join(lines)


def render(fm: dict, body: str) -> str:
    import yaml

    fm_str = yaml.dump(fm, default_flow_style=False, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm_str}\n---\n\n{body}\n"


def _fit(fm: dict) -> None:
    """Trim until the rendering fits MAX_BYTES, in a fixed order (R10)."""
    def size() -> int:
        return len(render(fm, render_body(fm)).encode("utf-8"))

    for c in fm["conversations"]:
        c["title"] = c["title"][:TITLE_LIMIT]
    if size() <= MAX_BYTES:
        return
    # Whole rows go people → preferences → conversations → projects: the
    # projects list is what a cursor exists for, so it is given up last (R10).
    for key in ("people", "preferences", "conversations", "projects"):
        while fm[key] and size() > MAX_BYTES:
            fm[key].pop()


_VOLATILE_KEYS = ("generated_at:", "repos_probed_at:", "inputs_version:")


def _masked(text: str) -> str:
    """The document with its clock and digest lines removed — what "content
    unchanged" means (R1). The body's `as of` line is the same clock."""
    return "\n".join(
        l for l in text.splitlines()
        if not l.startswith(_VOLATILE_KEYS) and " · as of " not in l
    )


def refresh(
    memory_path: Path,
    settings=None,
    *,
    force: bool = False,
    probe_repos: bool | None = None,
    today: date | None = None,
    now: datetime | None = None,
    repo_resolver: RepoResolver | None = None,
    connected_ids: list[str] | None = None,
) -> dict:
    """Regenerate ``_state.md`` when its inputs changed (or ``force``).

    ``probe_repos`` defaults to ``force``: Sleep pays for git nightly, a
    read-side refresh carries the previous blocks over. ``connected_ids``
    defaults to the registry's cache (``cached_connected_ids``). Returns
    ``{"written", "reason", "path"}``; never raises on a normal bank.
    """
    memory_path = Path(memory_path)
    path = state_path(memory_path)
    previous = read_state(memory_path)
    if probe_repos is None:
        probe_repos = force
    if not force and previous is not None and previous.get("inputs_version") == inputs_version(memory_path):
        return {"written": False, "reason": "inputs unchanged", "path": str(path)}
    if connected_ids is None:
        connected_ids = cached_connected_ids(settings)
    fm, body = build(memory_path, settings, today=today, now=now, probe_repos=probe_repos, previous=previous,
                     repo_resolver=repo_resolver, connected_ids=connected_ids)
    text = render(fm, body)
    if path.exists() and _masked(path.read_text(encoding="utf-8")) == _masked(text):
        if force and (previous or {}).get("inputs_version") != fm["inputs_version"]:
            # Same content, newer inputs: re-stamp the digest so the read
            # path's debounce is cheap again. Sleep commits the one-line diff.
            path.write_text(text, encoding="utf-8")
            return {"written": True, "reason": "version stamped", "path": str(path)}
        return {"written": False, "reason": "content unchanged", "path": str(path)}
    path.write_text(text, encoding="utf-8")
    return {"written": True, "reason": "rebuilt", "path": str(path)}


def commit_message(today: date | None = None) -> str:
    """The one ``State snapshot`` commit message, shared by every committer
    (the tail, the read path, ``_finalize``'s R3 split) so `git log` shows one
    shape: subject ``State snapshot <date>``, one manifest line under the
    ``sleep/state`` trigger (``_infer_trigger_for_path`` names the projection,
    not who asked for it), ``Cicada-Author: cicada`` — system maintenance
    with no model and no user in the loop — and no engine trailer, because no
    LLM ran (the same contract as the G85 decay commit)."""
    from api.services import git_service

    return git_service.build_commit_message(
        f"State snapshot {(today or date.today()).isoformat()}",
        [f"{STATE_FILENAME}: updated (trigger: sleep/state)"],
        authors=["cicada"],
    )


async def refresh_and_commit(
    memory_path: Path, settings=None, *, lock: asyncio.Lock | None = None, **refresh_kw,
) -> dict:
    """``refresh`` in a thread, then — only when it wrote — commit ``_state.md``
    ALONE as ``cicada``. The single entry point for every regeneration that
    can land on disk: Sleep's tail, ``GET /state``, an inbox resolution.

    Why the read path commits too (final review, 2026-09-03): leaving the
    file dirty "until Sleep's tail commits it" was reproduced to be wrong in
    practice — the next ``git add -A`` writer (an inbox resolution, a
    Telegram capture, a feed poll) swept it into ITS commit under the wrong
    author and trigger. ``commit_paths``, never ``git add -A``, so a dirty
    entity page beside it is never touched. Best-effort throughout: a commit
    failure logs and returns ``committed: False`` with the file written —
    ``_finalize``'s R3 split picks it up next cycle. A bank without git
    (R8: a plain folder still gets a file) is written and never committed.
    ``lock`` is the caller's asyncio lock when it serialises git itself
    (Sleep's ``_lock``); the other callers share git's own index lock.
    """
    memory_path = Path(memory_path)
    result = await asyncio.to_thread(refresh, memory_path, settings, **refresh_kw)
    result["committed"] = False
    if not result.get("written"):
        return result
    if not (memory_path / ".git").exists():
        result["reason"] = f"{result.get('reason', 'written')} (no git — not committed)"
        return result
    from api.services import git_service

    try:
        async with (lock if lock is not None else contextlib.nullcontext()):
            await git_service.commit_paths(memory_path, commit_message(), [STATE_FILENAME])
        result["committed"] = True
    except Exception as exc:
        logger.warning(
            f"State snapshot commit failed (file written, will be split out next cycle): "
            f"{type(exc).__name__}: {exc}"
        )
    return result


def _sleep_for_tests(seconds: float) -> None:  # pragma: no cover - a test seam
    time.sleep(seconds)
