"""Where a thing known only by a part or a plain noun belongs (2026-11-24, G148).

A person names a thing once ("I'm building a cedar strip canoe") and afterwards speaks of it by a part ("the hull is
curing"), a stage ("the second draft"), a room ("the kitchen cabinets arrive") or a plain noun ("the boat"). Stage 1
reads one conversation and knows nothing of what the memory holds, so it emits a name of its own for it; Stage 2's pair
judge (`entity_resolver._settle_unborn`) then weighs that name against each page ALONE, and with nothing in the
conversation that names the whole it answers ``different`` for every page in turn: each pair, taken alone, may well
be two things. Which page the name is a part of is a question about the whole list ("the person has one app, one
thesis, one boat: the onboarding flow is the app's"), so it is asked once over the list.

This is the one call. It runs only for a name the pair judge left with no page (no ``same``, no ``unsure``, no part of a
page) and answers one listed thing or none; ``none`` is the answer for a name that fits two things, fits none, is
described as separate (its own budget, people, purpose or deadline) or is only the same KIND of thing (two writing
projects each have a draft). What the caller does with a choice is its own (`entity_resolver._settle_unborn`): the name
lands as a mention on that page, exactly as a part the pair judge named would, and a removal or an undo works the same.
"""
from __future__ import annotations

from typing import Callable

from loguru import logger

from api.config import Settings
from api.services import engine_errors

#: How much of a page or a name's description the call reads: enough to say what the thing is, never a whole page.
BODY_CHARS = 700
#: At most this many listed things in one call (the caller's own candidate cap, `MAX_UNBORN_CANDIDATES`).
MAX_LISTED = 12

SYSTEM = ("You place one new entry in one person's knowledge graph: you say which listed thing, if any, it is a part of, "
          "from the descriptions you are given, and answer in JSON.")

PROMPT = """A person's knowledge graph holds the things they work on: projects, builds, plans, studies, trips, products. The new entry B below was read from ONE conversation. People name one endeavour differently in different conversations: by its name, by a part of it (a chapter, a room, a component, a screen, a stage), by a draft or a version of it, or by a plain noun for it. Say whether B is a part of exactly one of the numbered things, so that what is said about B belongs on that thing's page.

NEW ENTRY (B)
Name: {name}
Description:
{description}

THE THINGS
{entries}
Rules:
- Choose a number only when B's own words, its subject matter and what the thing is all point to that one thing, and B is a part, stage, draft, component, room, chapter, feature or aspect of it, or a plain noun for the thing itself.
- Choose 0 when B could belong to two or more of the things, when it fits none, when it is described as separate from them or as its own endeavour (its own budget, people, purpose or deadline), or when it is only the same KIND of thing as one (two writing projects each have a draft: a draft belongs to the one it is about; a tool used on two builds is a tool, not part of either).
- Never choose because the person or the time is the same: every entry here is the same person's.
- When B is the larger thing that includes a listed one, choose it with relation "has_part".

Respond with JSON only:
{{"entry": <the number, or 0 for none>, "relation": "part_of" | "has_part", "reason": "one short sentence"}}
"""

_ENTRY = "[{index}] {name}\n{body}\n"


def _block(index: int, name: str, body: str) -> str:
    return _ENTRY.format(index=index, name=name, body=(body or "").strip()[:BODY_CHARS] or "(empty)")


def prompt_for(name: str, description: str, things: list[tuple[str, str]]) -> str:
    """The call's prompt: B, then each listed thing as ``(name, description)``, numbered from 1."""
    entries = "\n".join(_block(i, n, b) for i, (n, b) in enumerate(things[:MAX_LISTED], start=1))
    return PROMPT.format(name=name, description=(description or "").strip()[:1500] or "(empty)", entries=entries)


def choice_of(parsed: object, listed: int) -> tuple[int, str] | None:
    """``(index into the list, relation)`` the answer chose, or ``None``: none, an index off the list, or no answer."""
    if not isinstance(parsed, dict):
        return None
    try:
        number = int(parsed.get("entry"))
    except (TypeError, ValueError):
        return None
    if not 1 <= number <= min(listed, MAX_LISTED):
        return None
    relation = str(parsed.get("relation") or "part_of").strip().lower()
    return number - 1, ("has_part" if relation == "has_part" else "part_of")


async def place(name: str, description: str, things: list[tuple[str, str]], settings: Settings, *,
                ask: Callable | None = None) -> tuple[int, str] | None:
    """Which of ``things`` (``(name, description)``, in order) B is a part of: ``(index, relation)`` or ``None``.

    ``ask(settings, system, prompt)`` is the model call (the same-name judge's seam, `entity_resolver._same_name_ask`:
    Stage 2's small model, JSON back); a failure of the model is ``None`` (nothing placed, the name is held or made as
    before), an engine failure propagates (G74a)."""
    if not things:
        return None
    if ask is None:
        from api.services.entity_resolver import _same_name_ask as ask   # noqa: PLW0127 — the shared seam
    try:
        parsed = await ask(settings, SYSTEM, prompt_for(name, description, things))
    except engine_errors.EngineError:
        raise
    except Exception as e:   # a judge that fails places nothing
        logger.debug(f"Part placement failed for {name}: {e}")
        return None
    return choice_of(parsed, len(things))
