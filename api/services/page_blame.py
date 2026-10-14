"""Who wrote each part of a page, when and why — read from git, never stored (G198, owner ruling 2026-10-14: "the
same as a doc in git: who changed what and at what time").

One ``git blame --porcelain`` over the page's prose lines (frontmatter and the claims fence left out — facts carry their
own provenance), one ``git log --no-walk`` over the commits it names, and each commit's trailers: ``Cicada-Author``
(the first one wrote the words; an applied edit proposal also names ``user``, who accepted it), the manifest line's
``trigger``, and an agent edit's ``Reason:`` line (``page_edits``). Lines are grouped by section (``## `` titles, and
an Article's ``### `` sections apart) with each contributor's line count and last change.

A line not committed yet is ``uncommitted`` (blame's all-zero commit), never guessed. Blame walks the page's whole
history (review: 0.6 s at 600 commits, 1.9 s at 2,000 on a 600 KB page), so the answer is kept per (bank, page, the
newest commit touching the page, the file's mtime and size) in this process, one computation runs per key, a request
waits for it at most :data:`WAIT_S` and is otherwise answered ``pending`` — the app keeps its last copy and asks again —
and every git call has a deadline (:data:`GIT_TIMEOUT_S`). Disposable, like the History window's blame.
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

from api.services import claims, git_service, page_edits

_HEADER = re.compile(r"^([0-9a-f]{40}) (\d+) (\d+)(?: (\d+))?$")
_TRIGGER = re.compile(r"\(.*?trigger: ([^)\s,]+)")
UNCOMMITTED = "uncommitted"
_ZERO = "0" * 40

_CACHE: dict[tuple, dict] = {}
_CACHE_MAX = 32


def prose_lines(text: str) -> tuple[int, int]:
    """1-based ``(first, last)`` lines of a page file's prose: after the frontmatter, before the claims fence.
    ``last < first`` when there is none."""
    lines = text.splitlines(keepends=True)
    first = 1
    if lines and lines[0].rstrip("\r\n") == "---":
        for i, line in enumerate(lines[1:], 2):
            if line.rstrip("\r\n") == "---":
                first = i + 1
                break
    start = claims.claims_block_start(text)
    last = text[:start].count("\n") if start is not None else len(lines)
    return first, last


def _sections(lines: list[str], first: int) -> list[tuple[int, str]]:
    """``(line number, section)`` for each line of the prose: the ``## `` title it sits under, ``Article › <title>``
    inside an Article's ``### `` section, ``(lead)`` before any heading."""
    out, h2, h3 = [], "(lead)", None
    fence = None
    for n, raw in enumerate(lines, first):
        line = raw.rstrip("\r\n")
        marker = page_edits._FENCE_LINE.match(line)
        if fence is None and marker:
            fence = marker.group(1)[0]
        elif fence is not None and marker and marker.group(1)[0] == fence:
            fence = None
        elif fence is None and (m := page_edits._HEADING.match(line)):
            if len(m.group(1)) == 2:
                h2, h3 = m.group(2).strip(), None
            elif h2 == "Article":
                h3 = m.group(2).strip()
        out.append((n, f"{h2} › {h3}" if h3 else h2))
    return out


def _commit(record: str, entity_file: str) -> dict | None:
    parts = record.split("\x1f", 3)
    if len(parts) < 4:
        return None
    sha, day, subject, body = parts[0].strip(), parts[1].strip(), parts[2], parts[3]
    authors = git_service._parse_authors(body)
    author = authors[0] if authors else git_service.UNKNOWN_AUTHOR
    kind, provider = git_service.author_identity(author)
    trigger = None
    for line in body.splitlines():
        if line.startswith(entity_file) and (m := _TRIGGER.search(line)):
            trigger = m.group(1)
            break
    return {"hash": sha, "date": day, "subject": subject.strip(), "author": author, "author_kind": kind,
            "author_provider": provider, "reason": page_edits.parse_reason(body), "trigger": trigger,
            "accepted_by": "user" if (author != "user" and "user" in authors) else None}


#: How long a request waits for a blame still running (G198 review B3, the History window's rule): past it the answer
#: is ``pending`` and the blame finishes in the background for the next ask.
WAIT_S = 0.5
#: No git call here runs longer than this; a blame that would is given up, never cached, and asked again later.
GIT_TIMEOUT_S = 30.0
_PENDING: dict[tuple, "asyncio.Task"] = {}


class _Unavailable(Exception):
    """git could not answer (an error, or past :data:`GIT_TIMEOUT_S`): nothing is cached."""


async def _git(memory_path: Path, *args: str, timeout: float | None = None) -> str:
    """A read-only git call with a deadline (:data:`GIT_TIMEOUT_S` unless given); the process is killed past it."""
    timeout = GIT_TIMEOUT_S if timeout is None else timeout
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(memory_path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except OSError as exc:
        raise _Unavailable(str(exc)) from exc
    try:
        out, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise _Unavailable(f"git {args[0]} took longer than {timeout:.0f} s") from None
    if proc.returncode != 0:
        raise _Unavailable(f"git {args[0]} failed")
    return out.decode(errors="replace")


def pending(entity_id: str) -> dict:
    """The answer while a blame is still running: the app keeps the last copy it holds and asks again."""
    return {"entity_id": entity_id, "commits": [], "sections": [], "uncommitted_lines": 0, "pending": True}


async def blame(memory_path: Path, entity_id: str, *, with_lines: bool = False, wait: float = WAIT_S) -> dict | None:
    """The page's blame, ``None`` when there is no page, or :func:`pending` when it is still being computed.

    G198 review B3: kept per (bank, page, the newest commit that touched the page, the file's mtime and size) — a
    commit elsewhere in the bank does not empty it — with one computation in flight per key, waited for at most
    ``wait`` seconds (shielded: a request that stops waiting never cancels it), and every git call bounded. A page git
    has never committed answers at once, every line ``uncommitted``."""
    memory_path = Path(memory_path)
    entity_file = f"entities/{entity_id}.md"
    page = memory_path / entity_file
    if not page.is_file():
        return None
    newest = ""
    if (memory_path / ".git").exists():
        try:
            newest = (await _git(memory_path, "log", "-1", "--format=%H", "--", entity_file, timeout=5.0)).strip()
        except _Unavailable:
            return pending(entity_id)
    st = page.stat()
    key = (str(memory_path.resolve()), entity_file, newest, st.st_mtime_ns, st.st_size)
    if key in _CACHE:
        return _shape(_CACHE[key], with_lines)
    loop = asyncio.get_running_loop()
    task = _PENDING.get(key)
    if task is None or task.done() or task.get_loop() is not loop:
        task = loop.create_task(_compute(memory_path, entity_id, entity_file, page, newest, key))
        # A failure nobody waited for is still retrieved (it is answered `pending` and asked again later).
        task.add_done_callback(lambda t: t.cancelled() or t.exception())
        _PENDING[key] = task
    try:
        result = await asyncio.wait_for(asyncio.shield(task), timeout=wait)
    except asyncio.TimeoutError:
        return pending(entity_id)
    except _Unavailable:
        return pending(entity_id)
    return _shape(result, with_lines)


async def _compute(memory_path: Path, entity_id: str, entity_file: str, page: Path, newest: str, key) -> dict:
    try:
        text = page.read_text(encoding="utf-8", errors="replace")
        first, last = prose_lines(text)
        lines = text.splitlines(keepends=True)[first - 1:last] if last >= first else []
        by_line: dict[int, str] = {}
        if lines and newest:
            out = await _git(memory_path, "blame", "--porcelain", "-L", f"{first},{last}", "--", entity_file)
            for raw in out.splitlines():
                if (m := _HEADER.match(raw)):
                    by_line[int(m.group(3))] = m.group(1)
        shas = [h for h in dict.fromkeys(by_line.values()) if h != _ZERO]
        commits: dict[str, dict] = {}
        if shas:
            out = await _git(memory_path, "log", "--no-walk=unsorted", "--date=short", git_service._HISTORY_FORMAT,
                             *shas, "--")
            for record in out.split("\x1e")[1:]:
                if (row := _commit(record, entity_file)) is not None:
                    commits[row["hash"]] = row
        rows = []
        for (n, section), raw in zip(_sections(lines, first), lines):
            sha = by_line.get(n)
            # A heading line is the section's frame, not its words: it is never counted to anyone.
            rows.append({"line": n, "section": section, "commit": sha if sha in commits else None,
                         "blank": not raw.strip() or bool(page_edits._HEADING.match(raw.rstrip("\r\n")))})
        result = _assemble(entity_id, rows, commits)
        while len(_CACHE) >= _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[key] = result
        return result
    finally:
        _PENDING.pop(key, None)


def _assemble(entity_id: str, rows: list[dict], commits: dict[str, dict]) -> dict:
    sections: list[dict] = []
    index: dict[str, dict] = {}
    uncommitted = 0
    for row in rows:
        sec = index.get(row["section"])
        if sec is None:
            sec = {"title": row["section"], "line_start": row["line"], "line_end": row["line"], "_by": {}}
            index[row["section"]] = sec
            sections.append(sec)
        sec["line_end"] = row["line"]
        if row["blank"]:
            continue
        commit = commits.get(row["commit"]) if row["commit"] else None
        if commit is None:
            uncommitted += 1
            who, kind, provider, day, sha = UNCOMMITTED, UNCOMMITTED, None, None, None
        else:
            who, kind, provider, day, sha = (commit["author"], commit["author_kind"], commit["author_provider"],
                                             commit["date"], commit["hash"])
        person = sec["_by"].setdefault(who, {"author": who, "author_kind": kind, "author_provider": provider,
                                             "lines": 0, "last_date": None, "commits": []})
        person["lines"] += 1
        if day and (person["last_date"] is None or day > person["last_date"]):
            person["last_date"] = day
        if sha and sha not in person["commits"]:
            person["commits"].append(sha)
    for sec in sections:
        people = sorted(sec.pop("_by").values(), key=lambda p: (-(p["lines"]), p["author"]))
        for p in people:
            p["commits"].sort(key=lambda h: commits[h]["date"], reverse=True)
        sec["contributors"] = people
    # A section of blank lines and a heading (the gap after the frontmatter, an empty section) has no author.
    sections = [sec for sec in sections if sec["contributors"]]
    used = {h for row in rows if (h := row["commit"])}
    ordered = sorted((commits[h] for h in used), key=lambda c: c["date"], reverse=True)
    return {"entity_id": entity_id, "commits": ordered, "sections": sections, "uncommitted_lines": uncommitted,
            "_lines": [{"line": r["line"], "section": r["section"], "commit": r["commit"]} for r in rows]}


def _shape(result: dict, with_lines: bool) -> dict:
    out = {k: v for k, v in result.items() if k != "_lines"}
    out.setdefault("pending", False)
    if with_lines:
        out["lines"] = list(result["_lines"])
    return out
