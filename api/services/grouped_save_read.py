"""Short saves of one origin are read together in Stage 1 (G246, ruling 80, Track 3; ``docs/plans/2026-11-24-saves-are-read.md`` 3.5).

Reading one short save alone costs about two model calls and 13k input tokens, because Stage 1 is one call per item and a
60 to 250 token post rides a fixed prompt of about 8k tokens. This module is the small part of the fix that is not the
model call itself: which saves may be read together, how the one question is put, how the one answer is checked, and the
meeting point that lets each save's own reader wait for it without holding a slot.

* **Who is grouped** (:func:`eligible`, :func:`plan`): a save that holds none of the person's words and was not talked
  about, of at most :data:`MAX_CHARS` characters, that is no tab group, no feed item, no book, no conversation of any
  kind — up to :data:`MAX_GROUP` of one origin. Everything else is read alone, as before.
* **The question** (:data:`GROUP_PROMPT`, :func:`render`): the same Stage 1 prompt, plus a paragraph saying the message
  holds several separate items, each with its own date note and source note and between its own markers.
* **The answer** (:func:`align`): used only when it lines up exactly — one result block per save, numbered 1 to N
  (``json_parse.numbered_rows``). Anything else is ``None`` and the caller reads each save alone with the same facts: a
  bad grouped answer costs money, never facts.
* **Per save from there on.** The answer is split into one ordinary Stage 1 result per save, and everything that follows —
  locating each quote in *that save's* text only, whose words it is, the owner guard, the entity cap, the date rule,
  the sensitive-text hold, the per-item callbacks — is the per-save code in ``entity_extractor``, untouched.

It is **off** (:data:`ON`) until the saves battery's grouped leg is measured (``benchmarks/consolidation/saves_battery.py``):
the coordinator flips the one constant. A batch of background saves may then hold up to :data:`BATCH_CEILING` and
skips Stage 4's skills call (:func:`saves_only_batch`).
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from api.services import json_parse

#: THE switch. Off: every save is read alone, exactly as before this module existed. A measurement decides it.
ON = False
#: Most saves in one call.
MAX_GROUP = 25
#: A save longer than this (characters of its body) is read alone: its text is no longer small beside the prompt.
MAX_CHARS = 1_500
#: A batch of background saves alone may hold this many (``sleep_run_prefs.BATCH_CHOICES``' own ceiling: a commit
#: records at most ``MAX_SESSION_TRAILERS`` conversations), two groups' worth.
BATCH_CEILING = 50
#: What such a batch may hold in bytes of episode files (``sleep_drain.BATCH_BYTES`` is five chunks' worth for a
#: conversation; fifty saves of 1,500 characters and their record lines are about this).
BATCH_BYTES = 150_000
#: The one answer holds up to 25 results: more time than one conversation's chunk gets.
TIMEOUT_S = 600
#: The key a result block is numbered by.
KEY = "save"
#: Where a save's own text may not contain what the question uses as a marker (such a save is read alone).
_MARKER = re.compile(r"<<<\s*(END\s+)?SAVE\b", re.IGNORECASE)
_TAB_GROUPS = frozenset({"tab-group", "chrome-tab-group"})

GROUP_PROMPT = """

SEVERAL SAVED ITEMS IN ONE MESSAGE. The user message holds several separate saved items, each between its own
"<<<SAVE n>>>" and "<<<END SAVE n>>>" markers and each with its own date note and source note. Read each as if it were
the only message you were given: its notes apply to it alone; never use one item's text, quote or facts for another, and
an evidence_quote is copied from the item that states the fact, never from a neighbour. Everything above about entities,
relationships and values holds inside each result. Answer one JSON object with exactly one result per item, in order:
{"results": [{"save": 1, "entities": [], "relationships": [], "values": []}, {"save": 2, "entities": [], "relationships": [], "values": []}]}
An item with nothing worth taking gets empty lists, and still its own result."""


def eligible(episode: dict | None) -> bool:
    """May this episode be read together with others? From its own record and body; no model, no write. ``False`` for a
    conversation, a book, a feed item, a tab group, a save he talked about or said something of, a long save, one edited
    since it was read, and one whose text holds the question's own marker."""
    from api.services import episode_revision, history_index, saved_reading

    ep = episode if isinstance(episode, dict) else {}
    if not saved_reading.no_words_of_his(ep) or ep.get(history_index.WOKEN_KEY):
        return False
    content = str(ep.get("content") or "")
    if not content.strip() or len(content) > MAX_CHARS or _MARKER.search(content):
        return False
    if str(ep.get("source") or "") in _TAB_GROUPS or str(ep.get("origin") or "").endswith(("tab-group", "tab-groups")):
        return False
    if any(ep.get(key) for key in ("gaps", "signals", "correspondent", "participants", "group", "meeting", "book", "relay",
                                   episode_revision.KEY, episode_revision.REVISED_KEY)):
        return False
    return not saved_reading.nothing_to_read(ep)


def plan(episodes: list[dict], *, on: bool | None = None) -> list[list[int]]:
    """The groups to read together: each a list of indexes into ``episodes``, of one origin, in order, at most
    :data:`MAX_GROUP` long and never one alone. Empty while the switch is off."""
    if not (ON if on is None else on):
        return []
    by_origin: dict[str, list[int]] = {}
    for i, episode in enumerate(episodes):
        if eligible(episode):
            by_origin.setdefault(str(episode.get("origin") or ""), []).append(i)
    groups: list[list[int]] = []
    for indexes in by_origin.values():
        for k in range(0, len(indexes), MAX_GROUP):
            part = indexes[k:k + MAX_GROUP]
            if len(part) >= 2:
                groups.append(part)
    return groups


def render(texts: list[str]) -> str:
    """The one user message: each save's text (its date note, its source note, its body), between its own markers."""
    n = len(texts)
    blocks = [f"<<<SAVE {k}>>>\n{text.rstrip()}\n<<<END SAVE {k}>>>" for k, text in enumerate(texts, 1)]
    return f"{n} saved items follow. Answer with exactly {n} results, numbered 1 to {n}.\n\n" + "\n\n".join(blocks)


def align(parsed, count: int) -> list[dict] | None:
    """One ordinary Stage 1 result (``entities``, ``relationships``, ``values``) per save, in the order they were sent, or
    ``None`` when the answer does not line up exactly: not an object, no ``results`` list, a missing, extra, duplicated or
    out-of-range block, or a block whose lists are not lists."""
    rows = parsed.get("results") if isinstance(parsed, dict) else None
    ordered = json_parse.numbered_rows(rows, count, KEY)
    if ordered is None:
        return None
    out: list[dict] = []
    for row in ordered:
        item: dict = {}
        for name in ("entities", "relationships", "values"):
            value = row.get(name)
            if value is None:
                value = []
            if not isinstance(value, list):
                return None
            item[name] = value
        out.append(item)
    return out


def lifted(results: list[dict], texts: list[str]) -> int:
    """How many quotes a result cites that its own save does not hold but a neighbour does (what a lifted quote looks like;
    only counted, for the log: the locating code reads each save's own text alone and files such a quote as ``reasoning``)."""
    def fold(s: str) -> str:
        return " ".join(str(s or "").split()).casefold()

    own = [fold(t) for t in texts]
    n = 0
    for k, result in enumerate(results):
        for item in (*result.get("relationships", []), *result.get("values", [])):
            quote = fold(item.get("evidence_quote")) if isinstance(item, dict) else ""
            if quote and quote not in own[k] and any(quote in other for j, other in enumerate(own) if j != k):
                n += 1
    return n


def saves_only_batch(batch) -> bool:
    """Is this drain batch nothing but background saves (and the switch on)? Then Stage 4's skills call is skipped: a
    skill needs two conversations and a save is no conversation (ruling 65)."""
    if not ON or batch is None or getattr(batch, "ds", None) is None:
        return False
    ids = list(getattr(batch, "only_ids", None) or ())
    return bool(ids) and all(i in batch.ds.background_ids for i in ids)


@dataclass
class Outcome:
    """What the one call came to: each member's ordinary result by index, ``None`` when every member reads alone, or why
    no call was made (``skipped``: ``"cancel"`` or ``"stop"``)."""

    parsed: dict[int, dict] | None = None
    skipped: str | None = None


@dataclass
class Group:
    """The meeting point of a group's readers. Each reader prepares its own save alone, then :meth:`join` s with its text;
    one that will not read with the others (it stopped, was filed with nothing to read, or turned out to need its own
    read) :meth:`leave` s. Once every member has done one or the other, ``reader`` runs once over those who joined and every
    joiner gets its :class:`Outcome` — or the error the call raised. Nobody holds a slot while waiting."""

    indexes: list[int]
    reader: object   # async (list[tuple[int, str]]) -> Outcome
    items: dict[int, str] = field(default_factory=dict)
    left: set[int] = field(default_factory=set)
    done: asyncio.Future | None = None

    def __post_init__(self) -> None:
        self.done = asyncio.get_running_loop().create_future()
        self._started = False

    def _settled(self) -> bool:
        return len(self.items) + len(self.left) >= len(self.indexes)

    def _go(self) -> None:
        if self._started or not self._settled():
            return
        self._started = True
        asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        try:
            outcome = await self.reader([(i, self.items[i]) for i in sorted(self.items)]) if self.items else Outcome()
        except BaseException as exc:  # noqa: BLE001 - every waiting reader gets the call's own error
            if not self.done.done():
                self.done.set_exception(exc)
            if isinstance(exc, asyncio.CancelledError):
                raise
            return
        if not self.done.done():
            self.done.set_result(outcome)

    def leave(self, index: int) -> None:
        """This member reads alone (or not at all). Idempotent; a no-op once it has joined."""
        if index in self.indexes and index not in self.items and index not in self.left:
            self.left.add(index)
            self._go()

    async def join(self, index: int, text: str) -> Outcome:
        self.items[index] = text
        self._go()
        return await self.done
