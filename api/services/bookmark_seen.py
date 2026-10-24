"""Per-channel "what the browser showed us last sync" seen-set (G129 slice 2).

Sibling to ``sources/url_index.json`` but answers a different question:
``url_index`` answers "have we ever ingested this URL" (forever); this answers
"was this URL in THIS channel's browser file the last time we looked" — the
only thing that makes a removal proposal correct rather than destructive.

Shape, ``sources/bookmark_seen.json``::

    {"chrome-bookmarks": {"folders": ["Reading"] | null, "hashes": ["ab12cd34ef56", ...], "at": "2026-09-05T10:00:00Z"},
     "safari-bookmarks": {...}}

**Rail 1 — the diff is only valid inside the folder scope that was synced.**
With a ``folders:`` selection, everything outside the chosen prefixes was
never looked at this pass and would look deleted for the wrong reason.
:func:`diff_removed` refuses (returns ``None``) whenever the current sync's
folder scope differs from the previous sync's recorded scope — the two sets
are simply not comparable, and the caller must record why rather than guess.

**Rail 2 — the diff is browser-then vs browser-now, NEVER browser vs memory.**
A URL the person chose to keep has already left the browser; diffing against
``url_index.json`` (which keeps every URL forever) would re-propose it after
every subsequent sync. Diffing against the PREVIOUS seen-set instead, and
always advancing the seen-set to the CURRENT sync's hashes regardless of what
the person eventually answers, means a URL that has left the browser drops out
of ``hashes`` on the very sync that notices it — the next sync's diff (browser
still lacking it, seen-set already lacking it) is empty, so nothing is ever
re-proposed. No bookkeeping of the person's answer is needed for this to hold.

**Left the browser (G191 v4, owner 2026-10-15: "I'd like to know that Cicada has the status, like it's not linked, or
is no longer a bookmark saved in Chrome").** Each channel's entry also keeps ``left`` — ``{url_hash: at}`` for every
link Cicada holds that dropped out of this browser's file, with the sync instant that first saw it gone. Cicada keeps
the bookmark, its page and its reasons; the status is all that changes, and nothing is asked. The map moves only by
the diff above, so the rails are the diff's rails: a channel's first sync and a folder-scope change add nothing (Rail
1 refuses the diff), a move or a rename keeps the URL in the file (never gone), and a link present again — the person
bookmarked it again — leaves the map on the sync that sees it (:func:`next_left`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from api.services import episode_ids

SEEN_FILENAME = "bookmark_seen.json"


def seen_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / SEEN_FILENAME


def read_seen(memory_path: Path) -> dict:
    path = seen_path(memory_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_channel_seen(
    memory_path: Path,
    channel: str,
    *,
    folders: list[str] | None,
    hashes: list[str],
    at: str | None = None,
    newest_added: str | None = None,
    left: dict[str, str] | None = None,
) -> None:
    """Replace ``channel``'s entry with the CURRENT sync's scope + hashes.

    Always called after a sync attempt for a channel that was actually looked
    at this pass — regardless of whether any removal was proposed or the
    person has answered one yet (Rail 2's "always advance" half).
    """
    state = read_seen(memory_path)
    state[channel] = channel_entry(folders=folders, hashes=hashes, at=at, newest_added=newest_added, left=left)
    path = seen_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def channel_entry(*, folders: list[str] | None, hashes: list[str], at: str | None = None,
                  newest_added: str | None = None, left: dict[str, str] | None = None) -> dict[str, Any]:
    """One channel's seen-set entry as :func:`write_channel_seen` stores it. Pure."""
    entry: dict[str, Any] = {
        "folders": sorted(set(folders)) if folders else None,
        "hashes": sorted(set(hashes)),
        "at": at or episode_ids.utc_now_iso(),
    }
    # G191 v3: the newest browser instant this sync saw, so the next one can tell a bookmark saved again (a newer
    # node for a known link) from one moved (the same node, the same instant). Absent when the file records none.
    if newest_added:
        entry["newest_added"] = newest_added
    # G191 v4: the links held that left this browser, each with when a sync first saw it gone (`next_left`).
    if left:
        entry["left"] = {str(h): str(when) for h, when in sorted(left.items())}
    return entry


def entry_unchanged(previous: dict[str, Any] | None, **wanted) -> bool:
    """Would writing ``wanted`` (:func:`channel_entry`'s arguments) leave ``previous`` as it is, but for its ``at``?

    Perf 2026-10-24: every wake of an unchanged bookmarks file (Chrome rewrites it on its own, and the watch fires on
    each write) rewrote ``bookmark_seen.json`` with a new ``at`` and committed it — one git commit per wake and an app
    refetch of the whole sources domain, for a seen-set that had not moved. ``at`` alone is no news: the next sync
    reads the previous ``newest_added`` first (``_resaved``), and falls back to ``at`` only for a file that records
    no instants, where no bookmark can read as saved later anyway."""
    if not isinstance(previous, dict):
        return False
    new = channel_entry(**{**wanted, "at": "-"})
    old = {k: v for k, v in previous.items() if k != "at"}
    new.pop("at")
    return old == new


def _normalize_folders(folders: list[str] | None) -> list[str] | None:
    """``None``, ``[]`` and ``[""]`` all mean "no filter" (matches
    ``bookmark_sync.filter_by_folders``'s own truthiness/``""`` rules) and
    compare equal; any other list compares as a sorted, deduped set so
    selection order never spuriously trips the mismatch check."""
    if not folders or "" in folders:
        return None
    return sorted(set(folders))


def diff_removed(
    previous: dict[str, Any] | None,
    current_hashes: list[str],
    *,
    previous_folders: list[str] | None,
    current_folders: list[str] | None,
) -> list[str] | None:
    """Hashes present in ``previous`` but missing from ``current_hashes``.

    Pure. Returns ``None`` (refuse — Rail 1/2) when there is no previous seen
    entry to diff against (nothing synced before; not an error, R6) or when
    the current sync's folder scope differs from the previous sync's (Rail 1
    — a real scope change, worth recording as a reason). Otherwise returns the
    sorted list of hashes that dropped out — possibly empty.
    """
    if previous is None:
        return None
    if _normalize_folders(previous_folders) != _normalize_folders(current_folders):
        return None
    prev_hashes = set(previous.get("hashes") or [])
    current = set(current_hashes)
    return sorted(prev_hashes - current)


def left_of(entry: dict[str, Any] | None) -> dict[str, str]:
    """``{url_hash: at}`` — the links that left this channel's browser (G191 v4); ``{}`` for none or an odd file."""
    raw = (entry or {}).get("left") if isinstance(entry, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {str(h): str(at) for h, at in raw.items() if isinstance(at, str) and at}


def next_left(
    previous: dict[str, Any] | None,
    current_hashes: list[str],
    removed: list[str] | None,
    *,
    at: str,
    held: set[str] | None = None,
) -> dict[str, str]:
    """The channel's ``left`` map after this sync (G191 v4). Pure.

    Starts from the previous map; every hash present in the browser now leaves it (the person bookmarked it again —
    whatever the folder scope, present is present); every hash in ``removed`` (the diff's answer: ``None`` when the
    rails refused it, so nothing is added) joins it with ``at`` unless it was already marked (the first day it was
    seen gone stays the day). ``held`` limits new marks to links Cicada holds — a link never ingested has no page to
    mark."""
    out = {h: when for h, when in left_of(previous).items() if h not in set(current_hashes)}
    for h in removed or []:
        if held is not None and h not in held:
            continue
        out.setdefault(h, at)
    return out


def left_by_hash(memory_path: Path) -> dict[str, list[tuple[str, str]]]:
    """Every link marked as gone from a browser, across channels: ``{url_hash: [(channel, at), ...]}``, channels in
    name order — what ``GET /sources`` and the channel item lists read."""
    out: dict[str, list[tuple[str, str]]] = {}
    for channel, entry in sorted(read_seen(memory_path).items()):
        for h, at in left_of(entry).items():
            out.setdefault(h, []).append((channel, at))
    return out
