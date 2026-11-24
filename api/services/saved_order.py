"""The order Sleep reads in (ruling 80, owner 2026-11-24, G246): his conversations first, then his saves.

A run is a frozen list of everything waiting (ruling 13: "Consolidate reads everything"). Saves enter that list, so the
one thing left to decide is the order inside it, in three classes, each keeping its own order:

1. **everything that is not a save**, oldest first as the queue gave it — every conversation, note, meeting, book record,
   feed item: a save never goes ahead of one;
2. **saves he talked about** (``read_asked``, stamped by his own words naming it, ``saved_mentions``) and saves that carry
   his own words (a reason, a why-answer, a note), newest first;
3. **background saves** — the day's release from the pile (:func:`history_index.take_turns`) and the ones he made singly —
   grouped by origin, the origins ordered by their newest save, newest first inside an origin.

Nothing is cut. Decay and the page reads run before the third class (``sleep_cycle``), and a spending line or plan
limit reached with only the third class left finishes the run instead of pausing it, so a night never blocks the next.

Rails: frontmatter only (the cached ``bank_index``); no model, no write.
"""
from __future__ import annotations

from pathlib import Path

from api.services import bank_index, history_index

#: The three classes, as numbers a test can read.
OTHER, TALKED, BACKGROUND = 0, 1, 2


def classify(fm: dict | None) -> int:
    """Which class one waiting episode belongs to, by its own record."""
    if not history_index.SAVES_READ or history_index.save_state(fm) != "waiting":
        return OTHER
    fm = fm or {}
    if fm.get(history_index.WOKEN_KEY) or any(fm.get(key) for key in history_index.PERSON_KEYS):
        return TALKED
    return BACKGROUND


def _day(fm: dict, ep_id: str) -> tuple[str, str]:
    return history_index._saved_day(fm), ep_id


def order(memory_path: Path, ids: list[str]) -> tuple[list[str], frozenset[str]]:
    """``ids`` in the order Sleep reads them, and the ones that are background saves (class 3). A stable partition: the
    first class keeps the order it came in."""
    memory_path = Path(memory_path)
    other: list[str] = []
    talked: list[tuple[tuple[str, str], str]] = []
    background: dict[str, list[tuple[tuple[str, str], str]]] = {}
    for ep_id in ids:
        entry = bank_index.file(memory_path, "episodes", f"{ep_id}.md")
        fm = entry.frontmatter if entry is not None else None
        c = classify(fm)
        if c == OTHER:
            other.append(ep_id)
        elif c == TALKED:
            talked.append((_day(fm, ep_id), ep_id))
        else:
            origin = str(fm.get("origin") or fm.get("source") or "")
            background.setdefault(origin, []).append((_day(fm, ep_id), ep_id))
    talked.sort(reverse=True)
    groups = [sorted(rows, reverse=True) for rows in background.values()]
    groups.sort(key=lambda rows: rows[0][0], reverse=True)   # the origin with the newest save first
    ordered = [*other, *(i for _k, i in talked), *(i for rows in groups for _k, i in rows)]
    return ordered, frozenset(i for rows in groups for _k, i in rows)


def background_ids(memory_path: Path, ids: list[str]) -> frozenset[str]:
    """Which of ``ids`` are background saves now (a mention since the freeze moves one out of the class)."""
    memory_path = Path(memory_path)
    out = set()
    for ep_id in ids:
        entry = bank_index.file(memory_path, "episodes", f"{ep_id}.md")
        if entry is not None and classify(entry.frontmatter) == BACKGROUND:
            out.add(ep_id)
    return frozenset(out)


__all__ = ["BACKGROUND", "OTHER", "TALKED", "background_ids", "classify", "order"]
