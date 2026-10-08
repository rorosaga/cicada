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

from pathlib import Path

from api.services import bank_index

#: Episode ``source`` values that carry facts but no time: the date they hold is the summary's, not a mention's.
UNTIMED_SOURCES = frozenset({"claude_memory"})


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
