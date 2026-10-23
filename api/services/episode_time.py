"""Which episodes are a time signal — "facts yes, activity no" (owner, 2026-10-08).

A chat export's memory entries (``source: claude_memory``, written by ``parse_anthropic_memories``) are a summary of
the person written by the assistant, stamped with the export entry's ``updated_at``. What they say is kept: pages,
claims and their sources are written from them like from any conversation. But the date on such an entry is when the
summary was last edited, not when anything in it came up, so a mention there never counts as the thing being
mentioned, coming up or active on that day. Time signals come from real conversations only.

This is the one predicate every time reader asks. It reads the stored ``source``, so it holds for banks consolidated
before the rule existed: nothing is rewritten, and the episodes themselves keep their timestamps.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from api.services import bank_index

#: Episode ``source`` values that carry facts but no time: the date they hold is the summary's, not a mention's.
#: ``agent_relay`` (owner, 2026-10-14): an agent's relay of what the person said when they answered an inbox
#: question in conversation. The conversation itself is captured on its own (the Stop hook), so counting the relay
#: too would count one conversation twice — and lift a one-off to the 2-conversation floor.
#: ``source-refresh`` (G61, ruling 26): a tracked source's dated re-check — what a page said, never the person mentioning
#: the thing (liveness is not mention); the re-check's own beliefs are dated by their capture instead.
#: ``web-check`` (TODO ruling 27): what a web lookup read about a public thing — never the person mentioning it either.
#: ``traces-day`` (G218): a day of activity traces, counted — what was on screen is not the person mentioning it.
#: ``notion-export-undated`` (G219, review of #455): a Notion page with no date of its own, stamped the day it was
#: imported — its facts are kept, but the import day is not when anything in it was said. Dated rows stay timed.
UNTIMED_SOURCES = frozenset({"claude_memory", "agent_relay", "source-refresh", "web-check", "traces-day",
                             "notion-export-undated"})


def counts_as_activity(frontmatter: dict | None) -> bool:
    """False for an episode whose date is not a mention's (a memory export entry); True for everything else."""
    source = str((frontmatter or {}).get("source") or "").strip().lower()
    return source not in UNTIMED_SOURCES


def untimed_ids(memory_path: Path | str | None) -> frozenset[str]:
    """Every episode id in the bank that is not a time signal, from the frontmatter cache (one ``scandir``)."""
    if memory_path is None:
        return frozenset()
    out: set[str] = set()
    try:
        for f in bank_index.files(Path(memory_path), "episodes"):
            if not counts_as_activity(f.frontmatter):
                out.add(f.stem)
                eid = str((f.frontmatter or {}).get("id") or "").strip()
                if eid:
                    out.add(eid)
    except OSError:
        return frozenset()
    return frozenset(out)


_SOURCE_LINE = re.compile(r"^source:[ \t]*['\"]?([^'\"\r\n#]*?)['\"]?[ \t]*(?:#.*)?$")


#: One awk pass prints each episode's top-level ``source:`` value, reading only its frontmatter (``nextfile`` at the
#: closing fence). One process instead of one open-and-read per episode: the card is often opened while a startup
#: index build holds the interpreter, and each of thousands of file reads then waited its turn (owner page, 2026-10-14:
#: 1.7 s of a cold open on a synthetic bank of 2,000 conversations, ~0.1 s of it the reads themselves).
_AWK = r"""
FNR == 1 { inside = ($0 == "---"); if (!inside) nextfile; next }
inside && $0 == "---" { nextfile }
inside && /^source:/ { v = $0; sub(/^source:[ \t]*/, "", v); sub(/[ \t]*#.*$/, "", v); gsub(/^['"]|['"]$/, "", v);
                       print FILENAME "\t" v; nextfile }
"""


#: ``{episodes dir: (its mtime, {path: source})}`` — an episode's source never changes, and a new or removed episode
#: changes the directory's mtime. Per process, disposable, like `bank_index`.
_MEMO: dict[str, tuple[int | None, dict[str, str]]] = {}


_AWK_BIN = "/usr/bin/awk" if os.path.exists("/usr/bin/awk") else "awk"


def _sources(paths: list[Path]) -> dict[str, str] | None:
    """``{path: source}`` for the episodes that state one (one awk pass, in batches); ``None`` when awk cannot run."""
    out: dict[str, str] = {}
    for start in range(0, len(paths), 500):
        batch = [str(p) for p in paths[start:start + 500]]
        try:
            proc = subprocess.run([_AWK_BIN, _AWK, *batch], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
            name, _, value = line.partition("\t")
            out[name] = value.strip()
    return out


def _source_of(path: Path) -> str | None:
    """One episode's ``source:`` read from its frontmatter lines without YAML; ``None`` when it cannot be read."""
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.readline().rstrip("\r\n") != "---":
                return ""
            for line in fh:
                line = line.rstrip("\r\n")
                if line == "---":
                    return ""
                match = _SOURCE_LINE.match(line)
                if match:
                    return match.group(1).strip()
    except OSError:
        return None
    return ""


def untimed_among(memory_path: Path | str | None, ids) -> frozenset[str]:
    """:func:`untimed_ids` restricted to ``ids`` — what one page's decay reads (its ``source_episodes``) — without a
    YAML parse of every episode in the bank: a cold card open used to parse every episode's frontmatter for it (owner
    page, 2026-10-14: seconds on a bank of imported conversations). The ``source:`` lines come from one awk pass
    (:data:`_AWK`), or a line-by-line read when awk cannot run. An id with no file of its own name falls back to the
    full scan, which also matches episodes by their ``id:`` field."""
    if memory_path is None:
        return frozenset()
    episodes = Path(memory_path) / "episodes"
    wanted = sorted({str(i) for i in ids or () if i})
    try:
        present = set(os.listdir(episodes))   # one listing, not a stat per episode
    except OSError:
        return frozenset()
    paths = []
    for eid in wanted:
        if "/" in eid or eid.startswith(".") or f"{eid}.md" not in present:
            return frozenset(untimed_ids(memory_path) & set(wanted))
        paths.append(episodes / f"{eid}.md")
    try:
        stamp = os.stat(episodes).st_mtime_ns
    except OSError:
        stamp = None
    memo = _MEMO.get(str(episodes))
    if memo is None or memo[0] != stamp:
        memo = (stamp, {})
        _MEMO[str(episodes)] = memo
    known = memo[1]
    missing = [p for p in paths if str(p) not in known]
    found = _sources(missing) if missing else {}
    if found is not None:
        for path in missing:
            known[str(path)] = found.get(str(path), "")
        found = known
    out: set[str] = set()
    for eid, path in zip(wanted, paths):
        source = found.get(str(path), "") if found is not None else _source_of(path)
        if (source or "").strip().lower() in UNTIMED_SOURCES:
            out.add(eid)
    return frozenset(out)
