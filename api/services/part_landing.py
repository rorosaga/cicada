"""A second reading before a part lands on a page (2026-11-24, G148).

The pair judge (`entity_resolver._settle_unborn`) is a small model reading B's one-line Stage 1 summary beside a page's
description. When it calls B a part of the page, B lands there as a mention (the owner's rule of 2026-10-23: "a canoe,
its hull, the hull build — is one thing") and the two are one page. Measured on invented counter-stories, that one
answer is not enough: a kitchen renovation said to be "a separate job with its own budget" was a part of the person's
flat renovation in another city in 7 of 8 replays of the judge's own call when it weighed two pages together, and a
kitchen that one night's summary no longer places in any house is a part of whatever renovation the list holds.

This is the second reading: the engine's MAIN model reads what the part's own conversation says (what Stage 1's summary
may have dropped: whose house, which town, its own budget) beside the page, and lands the part only when it can say what
ties them. It runs only for a name the pair judge already called a part of a page (`_part_of_page`), never on every
name; any other answer, an unreadable one or a model that fails leaves the name as it was before the judge called it a
part (its own name, held or born by the usual promotion rule): a wrong join is worse than a missed one, and a part that
waits costs little.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from loguru import logger

from api.config import Settings
from api.services import engine_errors

#: What the call reads of each piece: enough to say what a thing is, never a whole page or a whole conversation.
BODY_CHARS = 1500
SUMMARY_CHARS = 700
CONVERSATION_CHARS = 2400
#: At most this many of the part's conversations are shown (the most recent first).
MAX_CONVERSATIONS = 3

SYSTEM = ("You decide whether one thing a person talks about is a part of another thing they work on, from the words "
          "you are given, and answer in JSON.")

PROMPT = """A person's knowledge graph holds the things they work on. The name B below was read from the conversation(s) shown and has no page of its own; a quick reading suggested B is a part of the existing thing A (a stage, component, section, task or aspect of it). If you agree, what the person says about B is written on A's page and B is never a thing of its own. A wrong yes joins two different things for good; a no costs little (B keeps its own name until more is said).

B: {name}
What was read about B:
{summary}

The conversation(s) B was read from (what the person and the assistant said):
{conversation}

A: {whole}
A's page:
{body}

Answer "part" only when the words above show what ties B to A: the conversation names A or something only A has, or A's page already has B's subject among its own, or the two share a place, people or budget and nothing says otherwise.
Answer "no" when any of these holds:
- B is described as separate from A, or as a job, event or endeavour of its own (its own budget, people, purpose or deadline);
- B sits in another place, home, organisation or among other people than A's;
- B is only the same KIND of thing as A, or the kind of part A also has, or it fits another thing the person has as well as A;
- nothing in these words ties B to A, and the only reason is that such a part usually belongs to such a whole.

Respond with JSON only:
{{"verdict": "part" | "no", "reason": "one short sentence"}}
"""


def _conversation(memory_path: Path | None, episodes: list[str]) -> str:
    """The text of the part's own conversations, newest first, each cut; ``(not available)`` when none can be read."""
    if memory_path is None:
        return "(not available)"
    from api.services import evidence

    parts: list[str] = []
    for episode in list(dict.fromkeys(str(e) for e in episodes if e))[::-1][:MAX_CONVERSATIONS]:
        try:
            text = evidence.source_text(Path(memory_path), episode) or ""
        except Exception:  # noqa: BLE001 — the second reading reads less, never fails on it
            continue
        text = text.strip()
        if text:
            parts.append(text[:CONVERSATION_CHARS])
    return "\n---\n".join(parts) or "(not available)"


def prompt_for(name: str, summary: str, conversation: str, whole: str, body: str) -> str:
    from api.services.claims import strip_claims_block

    body = strip_claims_block(body or "")
    return PROMPT.format(name=name, summary=(summary or "").strip()[:SUMMARY_CHARS] or "(empty)",
                         conversation=conversation, whole=whole, body=(body or "").strip()[:BODY_CHARS] or "(empty)")


def verdict_of(parsed: object) -> bool:
    """True only for an answer that says ``part``; every other shape is no."""
    return isinstance(parsed, dict) and str(parsed.get("verdict") or "").strip().lower() == "part"


async def confirms(name: str, summary: str, episodes: list[str], whole: str, body: str, settings: Settings, *,
                   memory_path: Path | None = None, ask: Callable | None = None) -> bool:
    """Whether the engine's main model, reading the part's own conversations beside the page, agrees B is a part of A.

    ``ask(settings, system, prompt)`` is the model call (`entity_resolver._same_name_ask`, JSON back); it is handed the
    settings with the main model standing where the small one does. An engine failure propagates (G74a); any other
    failure is a no."""
    from api.services import entity_resolver, same_name_tend

    prompt = prompt_for(name, summary, _conversation(memory_path, episodes), whole, body)
    ask = ask or entity_resolver._same_name_ask
    try:
        parsed = await ask(same_name_tend.main_tier(settings), SYSTEM, prompt)
    except engine_errors.EngineError:
        raise
    except Exception as e:   # noqa: BLE001 — a reading that fails lands nothing
        logger.debug(f"Part landing reading failed: {type(e).__name__}")   # never a name
        return False
    return verdict_of(parsed)
