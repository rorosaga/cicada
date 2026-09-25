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
) -> None:
    """Replace ``channel``'s entry with the CURRENT sync's scope + hashes.

    Always called after a sync attempt for a channel that was actually looked
    at this pass — regardless of whether any removal was proposed or the
    person has answered one yet (Rail 2's "always advance" half).
    """
    state = read_seen(memory_path)
    state[channel] = {
        "folders": sorted(set(folders)) if folders else None,
        "hashes": sorted(set(hashes)),
        "at": at or episode_ids.utc_now_iso(),
    }
    path = seen_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
