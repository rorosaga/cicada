"""What a conversation's interactions mean, told to Stage 1: replies, reactions, forwards, unsends (G179, G118).

The owner, 2026-10-28: "replies in messages should be used by sleep, anything relevant in message interaction chats
should be, such as reactions and such." Every chat source stores these beside the words, in the episode's
frontmatter (:mod:`turn_extras`) — never in the body, so no evidence offset moves. Before this module no Sleep step
read them: Stage 1 saw ``user: yes`` with no idea it answered a two-day-old question, and never saw the 👍 the person
put on a plan. This module turns the stored extras into one short note per chunk, placed with Cicada's other notes
BEFORE the conversation (the model sees the note; evidence is still verified against the stored body).

**Source-agnostic.** It reads only the :mod:`turn_extras` shape — ``reply_to`` (an offset in this episode, or
``{ref}``), ``reactions``, ``forwarded_from`` — and ``unsent_turns``, so any writer that fills it (Messages today; a
chat export through ``episode_staging.draft_from_export``; the WhatsApp reader to come) is covered with no new code.
A ``{ref}`` target in another episode resolves through the conversation's own ``message_keys`` record, within the
same ``conversation``: a source that wants cross-sitting replies records both.

**What each signal says, and what it never says.**

* A **reply** names the message it answers (``r<n>``). A target in this episode is quoted from the body; one in an
  earlier sitting from THAT episode's body, with its day; one Cicada does not hold is said to be unknown — never
  guessed. A reply to the line directly above it needs no note (reading order already says it; 195 of 741 same-sitting
  replies in the owner's bank, counted 2026-10-28).
* A **reaction** (``s<n>``) is a signal on the reacted turn — who reacted and with what — never the reactor's own
  sentence and never a claim by itself (the tapback row's quoted text was never stored, `messages_source`). The
  person's reaction to a texted agent's message is the person's signal (agreement, doubt); an agent's reaction is the
  agent's. It may strengthen or weaken a claim drawn from the reacted turn.
* A **forward** says whose words a line really are.
* An **unsend** says only that something was there; its words are gone and are never guessed.

Edits are not noted (the body already holds the final wording) and attachments are already named in the body.

**Evidence.** The model tags a relationship or value with the label it rests on (``"signal": "r2"``). The tag is
consumed here: the quote is then located inside the tagged turn first — the reply line, or the reacted turn — so a
short "yes" or "ok" lands on the right line, exact → whitespace → case-insensitive, never fuzzy (G118). A reaction's
evidence is that span on the reacted turn: the turn's offset is the reaction's own key in ``turn_extras``, so the
span names the reaction exactly. The tag only steers where a quote is looked for; it grants nothing by itself. The
PERSON's own reaction on the turn a claim's located spans sit in (:func:`person_stance`) adjusts that claim's
confidence and is recorded on it — it never changes whose claim it is: a texted agent's stays ``external:<agent>``
(#499 review; a 👍 often only means "got it"). No LLM here; nothing is written.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from api.services import evidence, turn_extras

#: How much of a line the note quotes: enough to find it, little enough to stay cheap.
HEAD_CHARS = 32
#: A target the chunk also shows needs only enough words to find it; one in another sitting is quoted longer.
NEAR_CHARS = 40
TARGET_CHARS = 100
#: An agent's routine tapback (a like on what the person said) is its acknowledgement and says nothing about the
#: person: all 195 reactions in the owner's bank were the texted agent's like or emoji (2026-10-28). Only an agent's
#: doubt or emphasis is noted; every person's reaction is.
AGENT_NOTED = frozenset({"dislike", "question", "emphasize"})
#: A long sitting is read in chunks; past this many signals in one chunk the rest are counted, not listed.
MAX_PER_CHUNK = 40
NOTE_PREFIX = "[Cicada's note, not part of the conversation and nobody's words:"
SIGNAL_KEY = "signal"

_VERBS = {"love": "loved", "like": "liked", "dislike": "disliked", "laugh": "laughed at", "emphasize": "emphasized",
          "question": "questioned", "sticker": "put a sticker on"}


@dataclass(frozen=True)
class Signal:
    label: str            # r1 / s1 / f1 / u1 — what the model tags a relationship with
    kind: str             # reply | reaction | forward | unsent
    at: int               # the line the signal belongs to (its turn start), for chunk placement
    line: str             # one compact note line
    window: tuple[int, int] | None = None   # where a tagged quote is looked for first
    by: str | None = None                   # a reaction's reactor marker (``user`` = the person)


#: ``ref -> (marker, words, day)`` for a message held in another episode of the same conversation, else ``None``.
Lookup = Callable[[str], "tuple[str, str, str] | None"]


def _head(text: str, cap: int) -> str:
    line = " ".join(str(text or "").split()).replace('"', "'")
    return line if len(line) <= cap else line[: cap - 1].rstrip() + "…"


def _who(marker: str | None) -> str:
    marker = str(marker or "user")
    return "user" if marker in ("user", "human", "system", "unknown") else marker


def _reads_so(turns: list, j: int, i: int) -> bool:
    """Does reading order already say turn ``i`` answers turn ``j``? It does when ``j`` is the last thing anyone else
    said before it — only the replier's own lines between (the line above, or the second of a burst)."""
    replier = turns[i].marker
    return j == i - 1 or turns[j].marker != replier and all(turns[k].marker == replier for k in range(j + 1, i))


def signals(frontmatter: dict | None, body: str, *, lookup: Lookup | None = None) -> list[Signal]:
    """Every signal an episode's stored extras carry, in body order. Tolerant: a malformed entry is skipped."""
    fm = frontmatter or {}
    if not body or not (fm.get(turn_extras.EXTRAS_KEY) or fm.get(turn_extras.UNSENT_KEY)):
        return []
    turns = [t for t in evidence.turns(body) if t.marker is not None]
    by_start = {t.start: i for i, t in enumerate(turns)}
    out: list[Signal] = []
    counters = {"r": 0, "s": 0, "f": 0, "u": 0}

    def label(prefix: str) -> str:
        counters[prefix] += 1
        return f"{prefix}{counters[prefix]}"

    def words(t) -> str:
        return body[t.content_start:t.end]

    for offset, extras in sorted(turn_extras.by_offset(fm).items()):
        i = by_start.get(offset)
        if i is None:
            continue
        turn = turns[i]
        own = (turn.start, turn.end)
        who = _who(turn.marker)
        reply = extras.get("reply_to")
        if isinstance(reply, int) and not isinstance(reply, bool):
            j = by_start.get(reply)
            if j is not None and j < i and not _reads_so(turns, j, i):
                target = turns[j]
                out.append(Signal(label("r"), "reply", turn.start,
                                  f'{{L}}: {who} "{_head(words(turn), HEAD_CHARS)}" replies to {_who(target.marker)} '
                                  f'"{_head(words(target), NEAR_CHARS)}"', window=own))
        elif isinstance(reply, dict) and reply.get("ref"):
            found = lookup(str(reply["ref"])) if lookup is not None else None
            if found is not None:
                marker, said, day = found
                out.append(Signal(label("r"), "reply", turn.start,
                                  f'{{L}}: {who} "{_head(words(turn), HEAD_CHARS)}" replies to {_who(marker)} in an '
                                  f'earlier sitting{f" ({day})" if day else ""}: "{_head(said, TARGET_CHARS)}"',
                                  window=own))
            else:
                out.append(Signal(label("r"), "reply", turn.start,
                                  f'{{L}}: {who} "{_head(words(turn), HEAD_CHARS)}" replies to a message Cicada does '
                                  "not hold; what it answers is unknown, never guess it", window=own))
        for reaction in extras.get("reactions") or []:
            if not isinstance(reaction, dict) or reaction.get("kind") not in turn_extras.REACTION_KINDS:
                continue
            kind = reaction["kind"]
            verb = f'reacted {reaction.get("emoji") or "with an emoji"} to' if kind == "emoji" else _VERBS.get(kind)
            if not verb:
                continue
            reactor = _who(reaction.get("by"))
            if reactor == "assistant" and kind not in AGENT_NOTED:
                continue
            out.append(Signal(label("s"), "reaction", turn.start,
                              f'{{L}}: {reactor} {verb} {who} "{_head(words(turn), NEAR_CHARS)}"',
                              window=own, by=reactor))
        if extras.get("forwarded_from"):
            name = _head(extras["forwarded_from"], 60)
            out.append(Signal(label("f"), "forward", turn.start,
                              f'{{L}}: {who} "{_head(words(turn), HEAD_CHARS)}" was forwarded from {name}: '
                              f"{name}'s words, not {who}'s", window=own))
    for gone in turn_extras.unsent(fm):
        at = int(gone["at"])
        nxt = next((t for t in turns if t.start >= at), None)
        where = f'before {_who(nxt.marker)} "{_head(words(nxt), HEAD_CHARS)}"' if nxt else "at the end"
        out.append(Signal(label("u"), "unsent", min(at, len(body)),
                          f"{{L}}: {_who(gone.get('speaker'))} unsent a message {where}; its words are gone, "
                          "never guess them"))
    out.sort(key=lambda s: (s.at, s.label))
    return [Signal(s.label, s.kind, s.at, s.line.replace("{L}", s.label, 1), s.window, s.by) for s in out]


def chunk_note(items: list[Signal], start: int, end: int) -> str | None:
    """The note for one chunk ``[start, end)``: the signals on its lines, or ``None`` when it has none."""
    mine = [s for s in items if start <= s.at < end]
    if not mine:
        return None
    lines = [s.line for s in mine[:MAX_PER_CHUNK]]
    if len(mine) > MAX_PER_CHUNK:
        lines.append(f"(and {len(mine) - MAX_PER_CHUNK} more not listed)")
    return (f"{NOTE_PREFIX} how messages below relate. r: a reply to that message, not the line above; "
            "s: a reaction, the reactor's signal on that message, never their sentence; f: forwarded; u: unsent. "
            "Never quote this note. A relationship or value resting on one adds "
            f'"{SIGNAL_KEY}": "<label>".\n' + "\n".join(lines) + "]\n\n")


def anchor(item: dict, items: list[Signal], body: str, default: tuple[int, int] | None) -> tuple[tuple[int, int] | None, Signal | None]:
    """``(window, signal)`` for one extracted relationship or value: its tag is consumed; the window is the tagged
    turn when the quote is in it (so a short reply lands on its own line), else ``default``."""
    raw = item.pop(SIGNAL_KEY, None)
    tag = str(raw).strip().lower() if isinstance(raw, (str, int)) else ""
    signal = next((s for s in items if s.label == tag), None) if tag else None
    if signal is None or signal.window is None:
        return default, signal
    quote = str(item.get("evidence_quote") or "")
    lo, hi = signal.window
    if quote and evidence.locate(body[lo:hi], quote) is not None:
        return signal.window, signal
    # The tag alone grants nothing (#499 review): a quote that is not in the tagged turn rests on no signal.
    return default, None


#: What a reaction says, deterministically: agreement or doubt. Laughter and an emoji outside these say neither.
AGREES = frozenset({"love", "like", "emphasize"})
DOUBTS = frozenset({"dislike", "question"})
_AGREE_EMOJI = frozenset({"👍", "❤️", "✅", "🙌", "💯", "👌", "🔥", "🙏"})
_DOUBT_EMOJI = frozenset({"👎", "❓", "🤔", "❌"})


def stance(kind: str, emoji: str | None = None) -> str | None:
    """``agree`` | ``doubt`` | ``None`` for one reaction."""
    if kind in AGREES or (kind == "emoji" and emoji in _AGREE_EMOJI):
        return "agree"
    if kind in DOUBTS or (kind == "emoji" and emoji in _DOUBT_EMOJI):
        return "doubt"
    return None


def person_stance(frontmatter: dict | None, body: str, item: dict) -> dict | None:
    """The PERSON's own reaction on the turn every located span of ``item`` sits in, as ``{by, stance, kind, turn}``
    (``stance`` agree | doubt; ``turn`` the reacted turn's offset, the reaction's own key in ``turn_extras``), or
    ``None`` — no reaction of theirs there, the spans in several turns, or one that says neither. Read from the stored
    extras by located spans only, never from the model's word or tag."""
    spans = [e for e in item.get("evidence") or [] if isinstance(e, dict) and e.get("kind") != "reasoning"]
    if not spans or not body:
        return None
    starts = {t.start for t in evidence.turns(body) if t.marker is not None}
    owners = {max((s for s in starts if s <= int(e.get("start", -1))), default=-1) for e in spans}
    if len(owners) != 1 or -1 in owners:
        return None
    turn = next(iter(owners))
    extras = turn_extras.by_offset(frontmatter).get(turn) or {}
    found = [(stance(r.get("kind"), r.get("emoji")), r.get("kind")) for r in extras.get("reactions") or []
             if isinstance(r, dict) and r.get("by") == "user"]
    found = [f for f in found if f[0]]
    if len({s for s, _ in found}) != 1:
        return None
    return {"by": "user", "stance": found[0][0], "kind": str(found[0][1]), "turn": turn}


# --- Cross-sitting lookup (the Sleep loader) --------------------------------------------------------------------------


class KeyIndex:
    """Where each message of each conversation is held — built once per Sleep load, from frontmatter only
    (``bank_index`` entries); a body is read only for a ref actually asked about (:meth:`lookup_for`)."""

    def __init__(self, files: list):
        self._where: dict[tuple[str, str], dict[str, tuple[object, int]]] = {}
        for f in files:
            fm = f.frontmatter or {}
            conversation = str(fm.get("conversation") or "")
            if not conversation or fm.get("source_deleted_at") or not fm.get("message_keys"):
                continue
            slot = self._where.setdefault((str(fm.get("origin") or ""), conversation), {})
            for i, key in enumerate(fm.get("message_keys") or []):
                slot.setdefault(str(key), (f, i))

    def lookup_for(self, frontmatter: dict) -> Lookup | None:
        """A :data:`Lookup` within ``frontmatter``'s own conversation, or ``None`` when it names none."""
        conversation = str((frontmatter or {}).get("conversation") or "")
        if not conversation:
            return None
        where = self._where.get((str(frontmatter.get("origin") or ""), conversation), {})

        def lookup(ref: str):
            hit = where.get(ref)
            if hit is None:
                return None
            f, i = hit
            try:
                body = f.body()
            except Exception:  # noqa: BLE001 - an unreadable sitting is a target Cicada does not hold
                return None
            fm = f.frontmatter or {}
            lines = body.split("\n") if body else []
            if len(lines) != len(fm.get("message_keys") or []) or i >= len(lines):
                return None
            marked = [t for t in evidence.turns(lines[i]) if t.marker is not None]
            if not marked:
                return None
            day = str(fm.get("sitting_first_at") or fm.get("timestamp") or "")[:10]
            return marked[0].marker, lines[i][marked[0].content_start:marked[0].end], day

        return lookup


def needs_keys(frontmatter: dict | None) -> bool:
    """Does this episode hold a reply whose target is in another episode (a ``{ref}``)?"""
    return any(isinstance(e.get("reply_to"), dict) for e in turn_extras.by_offset(frontmatter).values())
