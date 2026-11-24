"""Who asked a question — the one line a card says under the question ("Asked 13 days ago by Sleep's duplicate check").

Owner, 2026-11-24, looking at a "same person?" card: *which agent asked this, and when?* A question is a file the
step that raised it wrote, and the file already carries what that step stamped (``detected``, ``trigger``,
``proposed_by``, ``asks``, ``kind``). This reads those and nothing else: no git, no second store, no model, so it is
free on a 700-question inbox that is polled, and it covers every question already on disk the day it ships.

**Why not the commit.** The commit that first held the file carries ``Cicada-Author`` and ``Cicada-Engine``, but a Sleep
batch commits every question of the run in one commit under every author of the batch, so a per-file author read from
it would be a guess; and a question the person has not seen yet may have no commit at all. The question's own stamps
are its writer's word. **Unknown is nothing, never a guess:** a question none of these rules names keeps no ``by`` and
the card says only when it was asked (``of`` returns ``None`` only when nothing at all is known, and then nothing is
said).

What it answers (``Asked``):

* ``step`` — an enum, the step by what it does (``duplicate_check``, ``conflict_check``, ``decay_check`` ...);
* ``how`` — whether a model was called for it: ``rule`` (an engine-free step), ``model`` (a model read a conversation or
  a page to raise it), ``agent`` (an agent proposed it through a tool), ``check`` (a re-check of a source);
* ``by`` — the step in a person's words, provider-neutral (CLAUDE.md, "Copy is provider-neutral"): it never names a
  model. A model's name is shown where provenance already shows it (a claim's author, the card's "<model>'s guess");
* ``agent`` — only for ``how == "agent"``: the harness the record names, as an id the app words the way it words every
  contributor (``OriginIconography``). ``None`` when the record says only "an agent".

``SHAPE`` rides ``GET /inbox``'s ETag, so a server that learns a new step moves every client's tag once.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The wire shape (``InboxItem.asked_by``): bump when a step, a ``how`` or a field is added or reworded.
SHAPE = "asked2"

RULE, MODEL, AGENT, CHECK = "rule", "model", "agent", "check"
HOWS = (RULE, MODEL, AGENT, CHECK)

#: step -> (how, the step in words). One table, so the card, the hover and the agent's line say the same thing.
STEPS: dict[str, tuple[str, str]] = {
    "duplicate_check": (RULE, "Sleep's duplicate check"),
    "shared_name_check": (RULE, "Sleep's shared-name check"),
    "same_name_review": (MODEL, "Sleep's same-name review"),
    "conflict_check": (RULE, "Sleep's conflict check"),
    "page_read": (MODEL, "Sleep's read of a page"),
    "still_check": (RULE, "Sleep's check for what may have ended"),
    "wording_check": (RULE, "Sleep's wording check"),
    "decay_check": (RULE, "Sleep's decay check"),
    "number_check": (RULE, "Sleep's phone number check"),
    "followup_check": (RULE, "Sleep's follow-up check"),
    "unnamed_check": (RULE, "Sleep's check for people with no name"),
    "link_suggestions": (RULE, "Sleep's link suggestions"),
    "sensitive_check": (RULE, "Sleep's check for sensitive text"),
    "conversation_read": (MODEL, "Sleep's read of a conversation"),
    "meeting_read": (MODEL, "Sleep's read of a meeting"),
    "source_recheck": (CHECK, "Sleep's re-check of a source"),
    "source_sync": (RULE, "the sync of a watched source"),
}

#: ``detected`` — the stamp the engine-free duplicate steps write on their question.
_DETECTED = {
    "person_duplicate": "duplicate_check",
    "spelling": "duplicate_check",
    "alias_collision": "shared_name_check",
    "same_name_doubt": "same_name_review",
}
#: ``trigger`` — what a nudge or a proposal was raised under (the commit's own trigger vocabulary).
_TRIGGERS = {
    "sleep/conflict_resolution": "conflict_check",
    "sleep/decay": "decay_check",
    "sleep/phone_number": "number_check",
    "sleep/where-to-check": "link_suggestions",
    "sleep/source-refresh": "source_recheck",
    "sync/folder_removal": "source_sync",
    "maintenance/placeholder-people": "unnamed_check",
}
#: ``asks`` — a clarification that asks for one thing (`role_people`, `meeting_speakers`, `source_proposals`).
_ASKS = {"name": "unnamed_check", "speaker": "meeting_read", "sources": "link_suggestions", "still": "still_check"}
#: ``kind`` — only the kinds ONE step writes; a kind several steps write is never read from here.
_KINDS = {
    "decay": "decay_check",
    "followup": "followup_check",
    "normalization": "wording_check",
    "sensitive": "sensitive_check",
}
#: A proposal Cicada's own check makes through the page-edit door is Sleep's, not an agent's (``wrong_aliases.ORIGIN``).
_ORIGINS = {"wrong_alias": "shared_name_check"}
#: ``proposed_by`` values that name no harness.
_NO_HARNESS = frozenset({"", "agent", "unknown", "user", "none"})
#: The names Cicada itself writes under: a proposal under one is Sleep's, never an agent's.
_OWN = frozenset({"cicada", "sleep"})


@dataclass(frozen=True)
class Asked:
    step: str | None
    how: str | None
    by: str | None
    agent: str | None = None

    def to_dict(self) -> dict:
        return {"step": self.step, "how": self.how, "by": self.by, "agent": self.agent}


def _text(value) -> str:
    return str(value or "").strip()


def _step(fm: dict, kind: str) -> str | None:
    """The step that raised the question, from what the question itself says — or ``None``."""
    origin = _ORIGINS.get(_text(fm.get("origin")))
    if origin:
        return origin
    step = _DETECTED.get(_text(fm.get("detected")))
    if step:
        return step
    asks = _ASKS.get(_text(fm.get("asks")))
    if asks:
        return asks
    if _text(fm.get("owner_role")):
        return "unnamed_check"
    if _text(fm.get("speaker_marker")):
        return "meeting_read"
    # The nudge writer's default trigger is the conflict check's, so a kind that has its own step is read before it.
    if kind in _KINDS:
        return _KINDS[kind]
    trigger = _text(fm.get("trigger"))
    if trigger in _TRIGGERS:
        return _TRIGGERS[trigger]
    # A conflict with no trigger: the claim path always stamps one, so this is the page writer's (`inbox_generator`),
    # which carries no predicate or the literal "description" and is raised by a model reading the page against a
    # conversation (`conflict_resolver._detect_contradiction`). Any other bare conflict names no writer: nothing.
    if kind == "conflict":
        return "page_read" if _text(fm.get("predicate")) in ("", "description") else None
    # A clarification or a duplicate question a conversation raised, written by the Stage 1 / Stage 2 reads with the
    # conversation they read stamped on it. Without that conversation nothing here says who wrote it.
    if kind in ("clarification", "merge_suggestion") and _text(fm.get("source_episode")) and fm.get("uncertainty_type"):
        return "conversation_read"
    return None


def _agent(fm: dict) -> tuple[bool, str | None]:
    """``(proposed by an agent, its harness id or None)`` — a ``page_edit`` or a page join through a tool."""
    proposer = _text(fm.get("proposed_by"))
    trigger = _text(fm.get("trigger"))
    if not proposer and trigger.startswith("mcp/"):
        proposer = trigger[len("mcp/"):]
    if not proposer:
        return False, None
    if proposer.casefold() in _OWN:
        return False, None
    return True, (None if proposer.casefold() in _NO_HARNESS else proposer)


def of(fm: dict, kind: str | None = None) -> Asked | None:
    """Who asked this question, from its own record; ``None`` when the record says nothing about it."""
    if not isinstance(fm, dict):
        return None
    kind = _text(kind or fm.get("kind"))
    by_agent, harness = _agent(fm)
    if by_agent:
        return Asked(step=None, how=AGENT, by="an agent", agent=harness)
    step = _step(fm, kind)
    if step is None:
        return None
    how, words = STEPS[step]
    return Asked(step=step, how=how, by=words)


def wire(fm: dict, kind: str | None = None) -> dict | None:
    """``InboxItem.askedBy`` — the enums and the step in words; the day is the item's own ``createdDate``."""
    asked = of(fm, kind)
    return None if asked is None else asked.to_dict()


_HOW_WORDS = {
    RULE: "a rule found it; no model read anything for it",
    MODEL: "a model read a conversation to raise it",
    AGENT: "an agent proposed it through Cicada's tools",
    CHECK: "found by re-checking a source",
}


def line(fm: dict, today: str, kind: str | None = None) -> str | None:
    """One sentence for an agent (``cicada_check_nudges``): "Asked 13 days ago by Sleep's duplicate check (a rule found
    it; no model read anything for it)." ``None`` when the day is unknown — nothing is said rather than guessed."""
    from api.services import inbox_questions

    day = _text(fm.get("created_date"))[:10]
    when = inbox_questions.humanize_age(day, today) if day else "unknown"
    if when == "unknown":
        return None
    asked = of(fm, kind)
    if asked is None or asked.by is None:
        return f"Asked {when}."
    who = asked.by if asked.how != AGENT or not asked.agent else f"an agent ({asked.agent})"
    return f"Asked {when} by {who} ({_HOW_WORDS[asked.how or RULE]})."
