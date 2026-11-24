"""What a save may add to the bank, and how much (G245, ruling 80's plan, Track 2c).

A save is read as its author's words, never the person's (`saved_reading`); this module bounds what those words can
become, so reading every save does not bloat the bank with what strangers' posts say. Three bounds, one place each so
every one is a line to undo:

* **A page's save-derived facts** (:data:`MAX_OPEN_CLAIMS`, :func:`cap`): at most this many open claims on one page rest
  on saves alone. The newest by the post's own day stay; an older one is CLOSED (``valid_to``), never deleted, and git
  holds what it was. The same fact stated by several authors is one claim with every author's evidence
  (:func:`fold_target`), not one per author — a claim's belief slot is keyed by its observer, so two authors' wording
  of one thing would otherwise be two claims.
* **A name's held lines** (:data:`MAX_HELD_CLAIMS`): a name met only in saves keeps at most this many held claims
  (`pending_store.hold`); a fourth is refused at the door and counted.
* **A name's reach** (:func:`Saves.all_of`, used by `entity_resolver`): a person's name met only in saves joins an
  existing page on an exact name or alias alone — never through the judge, the first-name rule or the same-name
  planning — and raises no question.

A claim "rests on saves alone" when its observer is somebody else's (``external:<author>``, what `saved_reading`
stamps) and every conversation it cites is a saved item. A fact the person said, or a claim any conversation of theirs
also cites, is never counted and never closed here. A NAME is only a save's when every conversation that named it is a
saved item with no words of the person's at all: one reason or note of his makes it his. Nothing is stored: everything is derived
from the episodes' own records and bodies on read, and an episode that cannot be read is no save.

What was not kept is counted, never silent: ``save_folded`` and ``save_capped`` audit entries (the claim pipeline's
``saves_folded`` and ``saves_closed``), the pending store's ``saves_held_capped`` and Stage 2's ``saves_names_held``,
each carried into the run's ``sleep_run`` ledger row — integers only, never a name or a word.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from api.services import bank_index, saved_reading

#: Open claims on one page that rest on saves alone (invariant 12 of the saves plan).
MAX_OPEN_CLAIMS = 12
#: Held claims on a pending line whose every source is a save with no words of the person's (invariant 3).
MAX_HELD_CLAIMS = 3

_EPISODE = re.compile(r"^ep_[A-Za-z0-9._-]{1,200}$")
#: ``(bank, file name, mtime_ns, size) -> (is a saved item, holds words of his, its day)``: a body is read once per change.
_READ: dict[tuple[str, str, int, int], tuple[bool, bool, str]] = {}
_READ_LIMIT = 50_000


class Saves:
    """Which episodes of one bank are saved items, and which of those hold no words of the person's, read one at a time
    and only when asked."""

    def __init__(self, memory_path: Path | str | None):
        self.memory_path = Path(memory_path) if memory_path else None

    def _read(self, episode_id: str) -> tuple[bool, bool, str]:
        episode_id = str(episode_id or "")
        if self.memory_path is None or not _EPISODE.match(episode_id):
            return False, False, ""
        try:
            entry = bank_index.file(self.memory_path, "episodes", f"{episode_id}.md")
        except Exception:  # noqa: BLE001 - an unreadable episode is no save
            return False, False, ""
        if entry is None:
            return False, False, ""
        key = (str(self.memory_path), f"{episode_id}.md", entry.mtime_ns, entry.size)
        hit = _READ.get(key)
        if hit is not None:
            return hit
        fm = dict(entry.frontmatter or {})
        result = (False, False, "")
        if saved_reading.applies(fm):
            try:
                words = bool(saved_reading.person_ranges(entry.body()))
            except Exception:  # noqa: BLE001 - a body that cannot be read could hold his words
                words = True
            result = (True, words, self._day(fm))
        if len(_READ) >= _READ_LIMIT:
            _READ.clear()
        _READ[key] = result
        return result

    @staticmethod
    def _day(fm: dict) -> str:
        """The day the save's text was posted (``posted``, else ``published_at``), else the day it carries."""
        day = saved_reading.post_day(fm)
        if day is not None:
            return day.isoformat()
        return str(fm.get("timestamp") or "")[:10]

    def is_save(self, episode_id: str) -> bool:
        """Is this episode a saved item (a bookmark, a saved post, a feed entry), whether or not he wrote about it?"""
        return self._read(episode_id)[0]

    def of(self, episode_id: str) -> bool:
        """Is this episode a saved item holding no words of the person's?"""
        is_save, words, _day = self._read(episode_id)
        return is_save and not words

    def all_of(self, episode_ids: Iterable[str]) -> bool:
        """Is every one of these episodes a save with no words of the person's (and is there at least one)? What decides
        whether a NAME is only a save's: one conversation of his makes it his."""
        ids = [str(e) for e in episode_ids or () if str(e or "").strip()]
        return bool(ids) and all(self.of(e) for e in ids)

    def all_saves(self, episode_ids: Iterable[str]) -> bool:
        """Is every one of these episodes a saved item (and is there at least one)? What decides whether a CLAIM rests on
        saves alone: its observer already says whose words it is (:func:`is_save_only`)."""
        ids = [str(e) for e in episode_ids or () if str(e or "").strip()]
        return bool(ids) and all(self.is_save(e) for e in ids)

    def day(self, episode_id: str) -> str:
        return self._read(episode_id)[2]


def for_bank(memory_path: Path | str | None) -> Saves:
    return Saves(memory_path)


# --------------------------------------------------------------------------- #
# claims
# --------------------------------------------------------------------------- #


def refs(claim) -> list[str]:
    """The conversations a claim cites: its ``source_episodes`` and the ``ep_*`` documents its evidence cites."""
    out = [str(e) for e in getattr(claim, "source_episodes", None) or [] if e]
    for ev in getattr(claim, "evidence", None) or []:
        doc = str(getattr(ev, "episode", "") or "")
        if doc.startswith("ep_") and doc not in out:
            out.append(doc)
    return out


def is_save_only(claim, saves: Saves) -> bool:
    """Does this claim rest on saves alone? Somebody else's observer (a claim with a span in the person's own words is
    never given one, `saved_reading.observer_for`), and every cited conversation a saved item. Never an event, a
    withdrawal record, or a claim the person stated."""
    from api.services.claims import is_event, is_record

    if not str(getattr(claim, "observer", "") or "").startswith("external:"):
        return False
    if is_event(claim) or is_record(claim) or getattr(claim, "source_trust", "") == "user_stated":
        return False
    return saves.all_saves(refs(claim))


def claim_day(claim, saves: Saves) -> str:
    """The newest post day among the saves a claim cites, else its own ``valid_from``."""
    days = [d for d in (saves.day(e) for e in refs(claim)) if d]
    return max(days) if days else str(getattr(claim, "valid_from", "") or "")[:10]


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def fold_target(new, slot: list, saves: Saves):
    """The open claim on this page that already says what ``new`` says, from another author: same predicate, context and
    object, both resting on saves alone. ``None`` when there is none (the slot's own rules decide)."""
    from api.services.claim_reconciler import open_

    if not is_save_only(new, saves):
        return None
    obj = _norm(new.object)
    for c in slot:
        if (open_(c) and c.predicate == new.predicate and c.context == new.context and _norm(c.object) == obj
                and c.observer != new.observer and is_save_only(c, saves)):
            return c
    return None


def cap(slot: list, saves: Saves, *, today: str, limit: int = MAX_OPEN_CLAIMS) -> list:
    """Close the oldest open save-only claims on one page past ``limit`` — newest by the post's own day stay (then by
    when it was recorded, then by id, so the choice is the same on every run). Closed, never deleted: ``valid_to`` is
    the day it was set aside. Returns the claims closed."""
    from api.services.claim_reconciler import open_

    held = [c for c in slot if open_(c) and is_save_only(c, saves)]
    if len(held) <= limit:
        return []
    held.sort(key=lambda c: (claim_day(c, saves), str(c.recorded_at or ""), c.id), reverse=True)
    closed = held[limit:]
    for c in closed:
        c.valid_to = str(today)[:10]
    return closed
