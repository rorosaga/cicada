"""What a home that publishes admitted, kept so it can be offered back (G132 phase 2, ruling 51a).

If the home is taken over while it is away and it comes back, every commit it made after the take-over point is set
aside, never merged — and **offered back as transactions** to the new home (``home_move``). An episode travels as the
episode (its file, through the new home's writer); every other change — a claim, an inbox answer, a page edit, a
backlog item — travels as **the call that made it**, which this journal keeps: the tool calls (the tool door, the
stdio MCP door, the command line) and the app's writes this home admitted, in the shape of an outbox entry
(``tx_outbox``), with the commit the home's HEAD was at after the call (``headAfter``, what the call produced). At a
reconcile, an entry is offered when ``headAfter`` is not in the new home's history (review of #569: never by a seq
compare, which drops two writes that read the same seq). The remote connector's writes are journaled too, but as
``unofferable``: replayed through another device's door they would gain that device's trust (a remote claim is never
the person's own words), so they are counted and named in words instead, kept on the set-aside ref.

Only while publishing is on (a single-machine install writes nothing here), only answers that landed, and only for 8
days (the idempotency key's life). ``$CICADA_HOME/sync/<bank key>/admitted.jsonl`` (0600, outside every bank and git,
one JSON line per call, appended under an ``flock`` so several processes can write it). A call's arguments are the
person's own words, like the outbox's — never logged, never sent anywhere but the new home.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
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


def _head(memory_path) -> str | None:
    from api.services import sync_service

    try:
        return sync_service.git_head(Path(memory_path)) or None
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Track:
    """What one admitted call did to the history: the head before it, and the commits it made itself."""

    before: str | None
    made: list[str] = field(default_factory=list)

    def head_after(self) -> str | None:
        """The call's own last commit; with none, the head it started from (its effect is already in that history,
        or it is an episode offered as the episode)."""
        return self.made[-1] if self.made else self.before


@contextmanager
def tracking(memory_path):
    """Around one admitted call on a publishing home (review of #569): its ``headAfter`` is the commit the call made
    — never a HEAD another writer moved between the call and the journal line. Nothing at all while not publishing."""
    if not recording(memory_path):
        yield None
        return
    from api.services import git_service

    before = _head(memory_path)
    with git_service.recording_commits() as made:
        yield Track(before=before, made=made)


def _after(memory_path, track: Track | None) -> str | None:
    return track.head_after() if track is not None else _head(memory_path)


#: Tools whose one effect is an episode: on the set-aside range the episode itself is offered (``home_move._offers``),
#: so a remote app's call of one is never also counted as "not sent" (review of #569: it was counted twice).
EPISODE_TOOLS = frozenset({"cicada_save_episode", "cicada_save_url", "cicada_capture_turns"})


#: Mutating tools whose effect is a lease or a job on THIS computer's own stores outside every bank (the video and
#: exploring queues): never a change to the memory, so never offered to another home.
NOT_OFFERED = frozenset({"cicada_video_claim", "cicada_explore_claim", "cicada_explore_start"})


def record_tool(memory_path, *, tool: str, arguments: dict, caller: dict | None = None, surface: str = "mcp",
                options: dict | None = None, seq_before: int | None = None, offerable: bool = True,
                track: Track | None = None, key: str | None = None) -> None:
    """A mutating tool call this home ran (the stdio MCP server, the tool door, the command line; ``offerable=False``
    for the remote connector's). ``key`` is the ``Idempotency-Key`` of a call this computer's own token sent (review of
    #569): offered back under it, a resend of the same write after this computer follows another home is the same
    transaction there."""
    if tool in NOT_OFFERED or not recording(memory_path):
        return
    try:
        _append(memory_path, {"v": 2, "kind": "tool" if offerable else "unofferable", "tool": tool,
                              "arguments": (arguments or {}) if offerable else {}, "caller": caller or {},
                              "surface": surface, "options": options or {},
                              "seqBefore": seq_before if seq_before is not None else _seq(memory_path),
                              "headAfter": _after(memory_path, track), "at": time.time(),
                              **({"key": key} if key else {})})
    except Exception:  # noqa: BLE001 — a journal line never fails the write it records
        pass


def record_rest(memory_path, *, method: str, path: str, query: str, body: bytes, content_type: str | None,
                seq_before: int | None, track: Track | None = None, key: str | None = None) -> None:
    """One of the app's writes this home admitted (a ``forward`` route of the table, answered 2xx)."""
    if not recording(memory_path) or len(body or b"") > MAX_BODY:
        return
    try:
        _append(memory_path, {"v": 2, "kind": "rest", "method": method, "path": path, "query": query or "",
                              "body": base64.b64encode(body or b"").decode("ascii"), "contentType": content_type,
                              "seqBefore": seq_before, "headAfter": _after(memory_path, track), "at": time.time(),
                              **({"key": key} if key else {})})
    except Exception:  # noqa: BLE001
        pass


def entries(memory_path) -> list[dict]:
    """The journal's calls (8 days at most), oldest first."""
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
        if isinstance(entry, dict) and float(entry.get("at") or 0) >= cutoff:
            out.append(entry)
    return out


def not_in(memory_path, theirs: str, *, since_seq: int | None = None) -> list[dict]:
    """The calls whose effect the history ``theirs`` (the new home's head) does not hold: the commit the call produced
    (``headAfter``) is not an ancestor of it. A call that produced no commit of its own (``headAfter`` already in
    ``theirs``) is in it, or its episode is offered as the episode. An entry from before ``headAfter`` was recorded
    falls back to ``since_seq``."""
    out = []
    known: dict[str, bool] = {}
    for entry in entries(memory_path):
        after = entry.get("headAfter")
        if after:
            if after not in known:
                known[after] = _is_ancestor(memory_path, after, theirs)
            if not known[after]:
                out.append(entry)
        elif since_seq is not None and isinstance(entry.get("seqBefore"), int) and entry["seqBefore"] >= since_seq:
            out.append(entry)
    return out


def _is_ancestor(memory_path, a: str, b: str) -> bool:
    try:
        return subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=str(memory_path),
                              capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


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
