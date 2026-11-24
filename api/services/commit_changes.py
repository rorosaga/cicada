"""What one commit did to the bank's pages, classified once and remembered (owner 2026-11-24, the Sleep page's Past
sleeps: a count is a count of real changes, and it stays fast).

``classify_commit(memory, sha)`` answers, for an entity commit: its subject, its file list, a verdict for every page it
modified (``page_change``: bookkeeping / fade / substance, plus a ``status:`` move) and the manifest trigger of each
page line (what the commit's own body says changed it). Four git calls at most — the subject + file list, one ``-U0``
patch of the modified entity files, one ``cat-file --batch`` for where the header ends in the few pages with a stamp-like
line, and one for the few pages whose patch the fast path cannot read (prose, lists) or whose ledger file appeared or went. Nothing is parsed for the other 1,900.

A commit never changes, so the answer is **derived and disposable**: one JSON file per commit under
``$CICADA_HOME/sleep/<bank>/changes/<sha>.json`` — outside every bank and git — read back when present and current
(``VERSION``), rebuilt when missing, corrupt or stale, never an error (a write that fails is a log line, the answer is
still returned). No page text, claim or conversation is in it: ids, enums and statuses only.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from loguru import logger

from api.services import git_service, page_change, sleep_local

#: Bump when the classification rules change: every cached answer is then read as missing.
VERSION = 2

_HASH = re.compile(r"[0-9a-f]{7,40}")
_MANIFEST_LINE = git_service._MANIFEST_LINE_RE


def _dir(memory_path: Path, *, create: bool) -> Path:
    return sleep_local.bank_dir(memory_path, create=create) / "changes"


def cache_get(memory_path: Path, key: str) -> dict | None:
    """The remembered answer for ``key`` (a commit, or a window's key), ``None`` when absent, stale or unreadable."""
    try:
        path = _dir(memory_path, create=False) / f"{key}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("v") == VERSION else None


def cache_put(memory_path: Path, key: str, data: dict) -> None:
    """Remember ``data`` atomically; a failure is a log line, never an error."""
    try:
        folder = _dir(memory_path, create=True)
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = folder / f".{key}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps({**data, "v": VERSION}, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, folder / f"{key}.json")
    except OSError as exc:
        logger.warning(f"sleep changes cache not written: {type(exc).__name__}")


def forget(memory_path: Path, key: str) -> None:
    try:
        (_dir(memory_path, create=False) / f"{key}.json").unlink()
    except OSError:
        pass


def parse_name_status(out: str) -> list[tuple[str, str]]:
    """``(status letter, path)`` per file; a rename reads as its source deleted and its destination added."""
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0][:1]
        if status == "R" and len(parts) >= 3:
            rows.append(("D", parts[1].strip()))
        rows.append(("A" if status == "R" else status, parts[-1].strip()))
    return rows


async def _blobs(memory_path: Path, specs: list[str]) -> dict[str, str | None]:
    """The text at each ``<rev>:<path>`` (``None`` when absent), through one ``git cat-file --batch``."""
    if not specs:
        return {}
    proc = await asyncio.create_subprocess_exec(
        "git", "cat-file", "--batch", cwd=str(memory_path), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    out, _err = await proc.communicate("".join(f"{s}\n" for s in specs).encode())
    result: dict[str, str | None] = {}
    at = 0
    for spec in specs:
        end = out.find(b"\n", at)
        if end < 0:
            result[spec] = None
            continue
        header = out[at:end].decode("utf-8", "replace").split(" ")
        at = end + 1
        if len(header) == 3 and header[1] == "blob" and header[2].isdigit():
            size = int(header[2])
            result[spec] = out[at:at + size].decode("utf-8", "replace")
            at += size + 1
        else:
            result[spec] = None
    return result


async def versions(memory_path: Path, old_rev: str | None, new_rev: str | None, entity_id: str) -> tuple:
    """``(old text, new text, old ledger, new ledger)`` of one page between two revisions (``None`` for a revision
    where the file is absent, or ``old_rev`` is ``None``)."""
    specs: dict[str, str] = {}
    for tag, rev in (("old", old_rev), ("new", new_rev)):
        if rev:
            specs[f"{tag}_md"] = f"{rev}:entities/{entity_id}.md"
            specs[f"{tag}_ledger"] = f"{rev}:entities/{entity_id}.claims.jsonl"
    got = await _blobs(Path(memory_path), list(specs.values()))
    return tuple(got.get(specs.get(k, ""), None) for k in ("old_md", "new_md", "old_ledger", "new_ledger"))


async def commit_versions(memory_path: Path, shas: list[str], entity_id: str) -> list[tuple]:
    """For each commit of ``shas``, ``(text before, text after, ledger before, ledger after)`` of one page — that
    commit's own change, whoever else touched the page around it. One ``cat-file --batch`` for them all."""
    specs: dict[tuple[str, str, str], str] = {}
    for sha in shas:
        for tag, rev in (("old", f"{sha}^"), ("new", sha)):
            specs[(sha, tag, "md")] = f"{rev}:entities/{entity_id}.md"
            specs[(sha, tag, "ledger")] = f"{rev}:entities/{entity_id}.claims.jsonl"
    got = await _blobs(Path(memory_path), list(dict.fromkeys(specs.values())))
    return [tuple(got.get(specs[(sha, tag, kind)]) for tag, kind in
                  (("old", "md"), ("new", "md"), ("old", "ledger"), ("new", "ledger"))) for sha in shas]


def _meta(raw: str) -> tuple[str, str, list[tuple[str, str]]]:
    parts = raw.split("\x1e")
    head = parts[1] if len(parts) > 1 else ""
    subject, _, body = head.partition("\x1f")
    return subject.strip(), body, parse_name_status(parts[2] if len(parts) > 2 else "")


def _triggers(body: str) -> dict[str, str]:
    """``{page id: trigger}`` from a Sleep commit's manifest lines."""
    out: dict[str, str] = {}
    for raw in body.splitlines():
        m = _MANIFEST_LINE.match(raw.strip())
        if not m:
            continue
        found = page_change.page_of(m.group("path").strip())
        if found is None or found[1]:
            continue
        for part in m.group("rest").split(","):
            key, _, value = part.partition(":")
            if key.strip() == "trigger":
                out[found[0]] = value.strip()
    return out


async def _read_fences(memory_path: Path, commit: str, ids: list[str], patches: dict) -> None:
    """Where each of ``ids``' frontmatter ends, before and after the commit (one ``cat-file --batch`` for them all), so
    the fast path can tell a stamp in the header from a paragraph of prose that reads like one. A page whose fence cannot
    be read keeps none and is decided by the full comparison."""
    if not ids:
        return
    specs = {f"{tag}:{eid}": f"{rev}:entities/{eid}.md" for eid in ids
             for tag, rev in (("-", f"{commit}^"), ("+", commit))}
    got = await _blobs(memory_path, list(specs.values()))
    for eid in ids:
        ends = {sign: page_change.frontmatter_end(got.get(specs[f"{sign}:{eid}"])) for sign in ("-", "+")}
        if all(end is not None for end in ends.values()):
            patches[eid].fence = {sign: end for sign, end in ends.items() if end is not None}


async def classify_commit(memory_path: Path, commit: str) -> dict | None:
    """The classified commit as a plain dict — ``{subject, files: [[status, path]…], pages: {id: [kind, was, now]},
    triggers: {id: trigger}}`` — from the cache or from git. ``None`` when git cannot say (never cached)."""
    memory_path = Path(memory_path)
    if not _HASH.fullmatch(commit or ""):
        return None
    hit = cache_get(memory_path, commit)
    if hit is not None and "pages" in hit:
        return hit
    try:
        raw = await git_service._run_git(memory_path, "log", "-1", "--root", "--no-color", "-M", "--name-status",
                                         "--format=%x1e%s%x1f%b%x1e", commit)
    except Exception:  # noqa: BLE001 - a list for a dropdown, never worth failing a page
        return None
    subject, body, files = _meta(raw)
    state = {"v": VERSION, **(hit or {})}   # keep a decay tie remembered before
    modified = {found[0] for st, path in files if st == "M" and (found := page_change.page_of(path))}
    ledger_moved = {found[0] for st, path in files if st in ("A", "D") and (found := page_change.page_of(path))
                    and found[1]}
    pages: dict[str, tuple[str, str | None, str | None]] = {}
    if modified:
        try:
            patch_text = await git_service._run_git(
                memory_path, "-c", "core.quotepath=off", "diff-tree", "--root", "-r", "-p", "-U0", "--no-color",
                "--no-renames", "--diff-filter=M", "--no-commit-id", commit, "--", "entities/")
        except Exception:  # noqa: BLE001
            return None
        patches = page_change.parse_patch(patch_text)
        await _read_fences(memory_path, commit, [e for e in sorted(modified)
                                                  if e not in ledger_moved and e in patches
                                                  and page_change.wants_fence(patches[e])], patches)
        slow: list[str] = []
        for eid in sorted(modified):
            verdict = None if eid in ledger_moved else (page_change.fast_verdict(patches[eid])
                                                        if eid in patches else None)
            if verdict is None:
                slow.append(eid)
            else:
                pages[eid] = (verdict.kind, *(verdict.status or (None, None)))
        if slow:
            specs: dict[str, str] = {}
            for eid in slow:
                for tag, rev in (("old", f"{commit}^"), ("new", commit)):
                    specs[f"{tag}_md:{eid}"] = f"{rev}:entities/{eid}.md"
                    specs[f"{tag}_ledger:{eid}"] = f"{rev}:entities/{eid}.claims.jsonl"
            got = await _blobs(memory_path, list(specs.values()))
            for eid in slow:
                try:
                    verdict = page_change.classify(
                        got.get(specs[f"old_md:{eid}"]), got.get(specs[f"new_md:{eid}"]),
                        got.get(specs[f"old_ledger:{eid}"]), got.get(specs[f"new_ledger:{eid}"]))
                except Exception:  # noqa: BLE001 - a page that will not read is a change to look at, never hidden
                    verdict = page_change.Verdict(page_change.SUBSTANCE)
                pages[eid] = (verdict.kind, *(verdict.status or (None, None)))
    triggers = _triggers(body)
    state.update({
        "subject": subject, "files": [[s, p] for s, p in files],
        "pages": {k: list(v) for k, v in pages.items()},
        "triggers": {k: v for k, v in triggers.items() if pages.get(k, ("",))[0] != page_change.BOOKKEEPING},
    })
    cache_put(memory_path, commit, state)
    return state
