"""What a home that publishes admitted, kept so it can be offered back (G132 phase 2, ruling 51a).

If the home is taken over while it is away and it comes back, every commit it made after the take-over point is set
aside, never merged — and **offered back as transactions** to the new home (``home_move``). An episode travels as the
episode (its file, through the new home's writer); every other change — a claim, an inbox answer, a page edit, a
backlog item — travels as **the call that made it**, which this journal keeps: the tool calls and the app's writes
this home admitted, in the shape of an outbox entry (``tx_outbox``), with the home's sequence number when it admitted
them. Only while publishing is on (a single-machine install writes nothing here), only answers that landed, and only
for 8 days (the idempotency key's life).

``$CICADA_HOME/sync/<bank key>/admitted.jsonl`` (0600, outside every bank and git, one JSON line per call, appended
under an ``flock`` so the stdio MCP server and the backend can both write it). A call's arguments are the person's
own words, like the outbox's — never logged, never sent anywhere but the new home.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import time
from pathlib import Path

FILE = "admitted.jsonl"
KEEP_S = 8 * 24 * 3600
MAX_BODY = 8 * 1024 * 1024


def _path(memory_path, *, create: bool) -> Path:
    from api.services import sync_publish

    return sync_publish.bank_dir(memory_path, create=create) / FILE


def recording(memory_path) -> bool:
    from api.services import sync_publish

    try:
        return sync_publish.publishable(memory_path)
    except Exception:  # noqa: BLE001 — never fails the write it records
        return False


def _append(memory_path, entry: dict) -> None:
    path = _path(memory_path, create=True)
    line = (json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, line)
    finally:
        os.close(fd)


def seq_before(memory_path) -> int | None:
    """The home's sequence number before a write, when this home publishes — else None: nothing is kept, and a
    single-machine install pays one environment read and one ``stat``."""
    if not recording(memory_path):
        return None
    return _seq(memory_path) or 0


def _seq(memory_path) -> int | None:
    from api.services import sync_log

    try:
        return sync_log.head_seq(memory_path)
    except Exception:  # noqa: BLE001
        return None


#: Mutating tools whose effect is a lease or a job on THIS computer's own stores outside every bank (the video and
#: exploring queues): never a change to the memory, so never offered to another home.
NOT_OFFERED = frozenset({"cicada_video_claim", "cicada_explore_claim", "cicada_explore_start"})


def record_tool(memory_path, *, tool: str, arguments: dict, caller: dict | None = None, surface: str = "mcp",
                options: dict | None = None, seq_before: int | None = None) -> None:
    """A mutating tool call this home ran (the stdio MCP server, the tool door)."""
    if tool in NOT_OFFERED or not recording(memory_path):
        return
    try:
        _append(memory_path, {"v": 1, "kind": "tool", "tool": tool, "arguments": arguments or {},
                              "caller": caller or {}, "surface": surface, "options": options or {},
                              "seqBefore": seq_before if seq_before is not None else _seq(memory_path),
                              "at": time.time()})
    except Exception:  # noqa: BLE001 — a journal line never fails the write it records
        pass


def record_rest(memory_path, *, method: str, path: str, query: str, body: bytes, content_type: str | None,
                seq_before: int | None) -> None:
    """One of the app's writes this home admitted (a ``forward`` route of the table, answered 2xx)."""
    if not recording(memory_path) or len(body or b"") > MAX_BODY:
        return
    try:
        _append(memory_path, {"v": 1, "kind": "rest", "method": method, "path": path, "query": query or "",
                              "body": base64.b64encode(body or b"").decode("ascii"), "contentType": content_type,
                              "seqBefore": seq_before, "at": time.time()})
    except Exception:  # noqa: BLE001
        pass


def entries(memory_path, *, since_seq: int | None = None) -> list[dict]:
    """The journal's calls (8 days at most), oldest first; ``since_seq``: only those admitted while the home's head
    was at or past it."""
    path = _path(memory_path, create=False)
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    cutoff = time.time() - KEEP_S
    out = []
    for line in raw.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or float(entry.get("at") or 0) < cutoff:
            continue
        before = entry.get("seqBefore")
        if since_seq is not None and not (isinstance(before, int) and before >= since_seq):
            continue
        out.append(entry)
    return out


def prune(memory_path) -> None:
    """Drop lines past their 8 days (the next start of a publishing home)."""
    keep = entries(memory_path)
    path = _path(memory_path, create=False)
    if not path.exists():
        return
    tmp = path.with_name(f".{FILE}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for entry in keep:
            fh.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def clear(memory_path) -> None:
    _path(memory_path, create=False).unlink(missing_ok=True)
