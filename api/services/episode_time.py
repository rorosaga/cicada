"""Which episodes are a time signal — "facts yes, activity no" (owner, 2026-10-08).

A chat export's memory entries (``source: claude_memory``, written by ``parse_anthropic_memories``) are a summary of
the person written by the assistant, stamped with the export entry's ``updated_at``. What they say is kept: pages,
claims and their sources are written from them like from any conversation. But the date on such an entry is when the
summary was last edited, not when anything in it came up, so a mention there never counts as the thing being
mentioned, coming up or active on that day. Time signals come from real conversations only.

Feed items join the rule under ruling 39 (owner 2026-10-24, :data:`FEED_ORIGINS`): what a feed published is no
mention by the person either, whether it is dated by its publisher or by the poll that fetched it.

This is the one predicate every time reader asks. It reads the stored ``source`` (and a feed's ``origin`` and
``published_at``), so it holds for banks consolidated before the rule existed: nothing is rewritten, and the episodes
themselves keep their timestamps.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
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
#: ``agent-memory`` (ruling 43, 2026-10-27): an agent's own memory note (``agent_memory_notes``) — like a memory export
#: entry, its date is when the summary was last edited, and the session that wrote it is captured on its own.
UNTIMED_SOURCES = frozenset({"claude_memory", "agent_relay", "source-refresh", "web-check", "traces-day",
                             "notion-export-undated", "agent-memory"})

#: Ruling 39 (owner 2026-10-24): a feed item (RSS/Atom) is dated by when it was published (``timestamp``, and its
#: ``published_at``) and records when Cicada received it (``received_at``). It is something the outside world
#: published, never the person mentioning anything — so it is no time signal, whichever date it carries: a new
#: subscription's back catalogue is no burst of fresh activity (it used to be, dated the day it was polled), and a
#: years-old article neither starts a page's clock years ago nor charges anything (its facts land like a memory
#: export entry's: a page it creates starts its silence clock the day Cicada learned it; a page it touches keeps its
#: last mention). ``origin: rss`` covers the feed items written before the ruling (dated their poll day);
#: ``published_at`` covers every feed item since, the subscribed poll's, ``/sources/rss``'s and an uploaded feed
#: file's alike.
FEED_ORIGINS = frozenset({"rss"})
#: The frontmatter key of a feed item's own published moment (aware UTC) — only a feed's writer sets it.
PUBLISHED_KEY = "published_at"


def is_feed_item(frontmatter: dict | None) -> bool:
    """A feed item: published by someone else and received by subscription or a feed import (ruling 39)."""
    fm = frontmatter or {}
    return bool(fm.get(PUBLISHED_KEY)) or str(fm.get("origin") or "").strip().lower() in FEED_ORIGINS


def counts_as_activity(frontmatter: dict | None) -> bool:
    """False for an episode whose date is not a mention's (a memory export entry, a feed item); True for everything
    else."""
    source = str((frontmatter or {}).get("source") or "").strip().lower()
    return source not in UNTIMED_SOURCES and not is_feed_item(frontmatter)


#: Ruling 39: the received date is shown beside an item's own date only when it is at least this many days later —
#: a conversation captured the evening it began, or a save posted the next morning, says its one date once.
RECEIVED_SHOWN_AFTER_DAYS = 2


def received_shown(frontmatter: dict | None) -> str | None:
    """The episode's ``received_at`` when a surface should show it beside the item's own date ("published 2023-05-01 ·
    added today"), else ``None``: unknown (an episode from before ruling 39), unreadable, or within
    :data:`RECEIVED_SHOWN_AFTER_DAYS` of the item's own day. Days are the person's (``episode_ids.local_day``)."""
    from api.services import episode_ids

    fm = frontmatter or {}
    parsed = episode_ids.parse_episode_id(str(fm.get("id") or ""))
    return received_after(fm.get("timestamp") or (parsed[0] if parsed else None), fm.get(episode_ids.RECEIVED_KEY))


#: CIC8 (2026-10-29) — the stamps that say when Cicada GOT an episode: ``received_at`` (ruling 39, stamped once at
#: create), the capture writer's ``captured_at`` (every create and update) and a session's ``last_turn_at``.
DELIVERY_KEYS = ("received_at", "captured_at", "last_turn_at")


def instant(ts) -> float:
    """An ISO stamp as epoch seconds, ``0.0`` when absent or unreadable. Stamps compare lexically only within one shape
    (``Z`` against ``+00:00``, a bare date against a time), so every recency comparison goes through this. A naive
    stamp reads as UTC."""
    if not ts:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def is_later(a, b) -> bool:
    """Whether stamp ``a`` is a later instant than ``b`` (an empty ``b`` is never later). Two stamps of one shape —
    the same length and the same offset suffix, which is nearly every pair in a bank — compare as strings; any other
    pair is parsed (:func:`instant`). The fast path keeps list routes from parsing a date per episode."""
    if not a:
        return False
    if not b:
        return True
    a, b = str(a), str(b)
    if len(a) == len(b) and a[-6:] == b[-6:] and (a[-6] in "+-" or a.endswith("Z")):
        return a > b
    return instant(a) > instant(b)


def delivered_at(frontmatter: dict | None) -> str:
    """When a source last DELIVERED this episode — the one rule behind every "connected · 3 min ago" a source shows
    (the overview's ``last_activity_at``, an import channel's ``last_sync``). Ruling 39: an import's recency is when
    Cicada received it, never the conversation's own date, so a year-old chat imported today reads "today". The
    newest of :data:`DELIVERY_KEYS`; an episode written before ``received_at`` existed, with none of them, falls back
    to its ``timestamp`` (nothing better is known). ``""`` when there is nothing."""
    fm = frontmatter or {}
    stamps = [s for s in (fm.get(k) for k in DELIVERY_KEYS) if s]
    if not stamps:
        return str(fm.get("timestamp") or "")
    # One stamp (the usual case) needs no parse: this runs once per episode on every list route.
    best = str(stamps[0])
    for s in stamps[1:]:
        if is_later(s, best):
            best = str(s)
    return best


def received_after(own, received) -> str | None:
    """``received`` (as stored) when its day is at least :data:`RECEIVED_SHOWN_AFTER_DAYS` after ``own``'s, else
    ``None`` — the one rule behind every "· added <day>" (an episode's two dates, a saved link's own date and its
    ingest). Either unreadable is ``None``: nothing is guessed."""
    from api.services import episode_ids

    got, day = episode_ids.local_day(received), episode_ids.local_day(own)
    if got is None or day is None or (got - day).days < RECEIVED_SHOWN_AFTER_DAYS:
        return None
    return str(received)


def untimed_ids(memory_path: Path | str | None) -> frozenset[str]:
    """Every episode id in the bank that is not a time signal, from the frontmatter cache (one ``scandir``)."""
    if memory_path is None:
        return frozenset()
    mp = Path(memory_path)
    # Remembered per state of the folder (speed 2026-10-29: the inbox asked once per load, ~75 ms over 8.5k episodes);
    # the fingerprint and the listing below share one scan.
    with bank_index.shared_scans():
        stamp = bank_index.dir_fingerprint(mp / "episodes")
        hit = _UNTIMED.get(str(mp))
        if hit is not None and hit[0] == stamp:
            return hit[1]
        ids = _untimed_ids(mp)
    _UNTIMED[str(mp)] = (stamp, ids)
    return ids


#: bank -> (the episodes folder's fingerprint, its untimed ids). Process-local and disposable.
_UNTIMED: dict[str, tuple[str, frozenset[str]]] = {}


def _untimed_ids(memory_path: Path) -> frozenset[str]:
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


_KEY_LINE = re.compile(r"^(source|origin|published_at):[ \t]*['\"]?([^'\"\r\n#]*?)['\"]?[ \t]*(?:#.*)?$")


#: One awk pass prints each episode's top-level ``source:``, ``origin:`` and ``published_at:`` values — what
#: :func:`counts_as_activity` reads — from its frontmatter only (``nextfile`` at the closing fence, or once all three
#: are seen). One process instead of one open-and-read per episode: the card is often opened while a startup index
#: build holds the interpreter, and each of thousands of file reads then waited its turn (owner page, 2026-10-14:
#: 1.7 s of a cold open on a synthetic bank of 2,000 conversations, ~0.1 s of it the reads themselves).
_AWK = r"""
FNR == 1 { inside = ($0 == "---"); seen = 0; if (!inside) nextfile; next }
inside && $0 == "---" { nextfile }
inside && /^(source|origin|published_at):/ {
    k = $0; sub(/:.*$/, "", k); v = $0; sub(/^[a-z_]+:[ \t]*/, "", v); sub(/[ \t]*#.*$/, "", v);
    gsub(/^['"]|['"]$/, "", v); print FILENAME "\t" k "\t" v; if (++seen == 3) nextfile }
"""


#: ``{episodes dir: (its mtime, {path: keys})}`` — an episode's source, origin and published date never change, and a
#: new or removed episode changes the directory's mtime. Per process, disposable, like `bank_index`.
_MEMO: dict[str, tuple[int | None, dict[str, dict]]] = {}


_AWK_BIN = "/usr/bin/awk" if os.path.exists("/usr/bin/awk") else "awk"


def _sources(paths: list[Path]) -> dict[str, dict] | None:
    """``{path: {key: value}}`` of the keys :data:`_AWK` reads, for the episodes that state any (one awk pass, in
    batches); ``None`` when awk cannot run."""
    out: dict[str, dict] = {}
    for start in range(0, len(paths), 500):
        batch = [str(p) for p in paths[start:start + 500]]
        try:
            proc = subprocess.run([_AWK_BIN, _AWK, *batch], capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
            name, _, rest = line.partition("\t")
            key, _, value = rest.partition("\t")
            out.setdefault(name, {}).setdefault(key, value.strip())
    return out


def _source_of(path: Path) -> dict | None:
    """One episode's ``source:``, ``origin:`` and ``published_at:`` read from its frontmatter lines without YAML;
    ``None`` when it cannot be read."""
    found: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            if fh.readline().rstrip("\r\n") != "---":
                return found
            for line in fh:
                line = line.rstrip("\r\n")
                if line == "---":
                    return found
                match = _KEY_LINE.match(line)
                if match:
                    found.setdefault(match.group(1), match.group(2).strip())
    except OSError:
        return None
    return found


def untimed_among(memory_path: Path | str | None, ids) -> frozenset[str]:
    """:func:`untimed_ids` restricted to ``ids`` — what one page's decay reads (its ``source_episodes``) — without a
    YAML parse of every episode in the bank: a cold card open used to parse every episode's frontmatter for it (owner
    page, 2026-10-14: seconds on a bank of imported conversations). The ``source:``, ``origin:`` and ``published_at:``
    lines come from one awk pass
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
            known[str(path)] = found.get(str(path), {})
        found = known
    out: set[str] = set()
    for eid, path in zip(wanted, paths):
        keys = found.get(str(path), {}) if found is not None else _source_of(path)
        if not counts_as_activity(keys or {}):
            out.add(eid)
    return frozenset(out)
