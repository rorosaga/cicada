"""Who an unnamed meeting speaker is (ROR-142), worked out in Sleep from the transcript's own words.

A recorder labels people it cannot name by role or number: Hex's ``Them`` (everything the call's audio carried), a
diarizer's ``Speaker 1``/``SPEAKER_00``, Otter's ``Unknown Speaker`` (``meeting_transcripts.is_placeholder``). Before
Stage 1 reads such a meeting, one call asks the engine which name each placeholder stands for, and code keeps an
answer only when it holds up on the record:

* the answer quotes a line of the transcript, the quote is found in it (exact, then whitespace, then case-insensitive —
  never fuzzy, like every evidence span) and the name is said in that quote: someone addresses them by it, or they
  introduce themselves. A calendar's attendee list may correct a name's spelling, never name anyone on its own (a
  filing label is never anyone's words, CLAUDE.md storage rail);
* never the person themselves (ruling 52a: only ``You``/``Me`` lines are theirs; "a name is never guessed to be the
  person's"), never another placeholder, never two names for a label that is one voice.

What is kept reaches Stage 1 as a line of the meeting note, with the quote; the stored body, its labels and every
offset stay as they are. Nothing kept means the note's plain placeholder sentence. A failed or refused call never
fails the read: the meeting is read as it would have been.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from loguru import logger

from api.services import meeting_transcripts as mt

#: The most transcript the call reads: people are named early, and a two-hour call should not cost two reads.
MAX_CHARS = 60_000
TIMEOUT_S = 120
STAGE = "meeting_speakers"

SYSTEM_PROMPT = """You read a meeting transcript. Each line starts with who said it: "user:" is the person whose \
memory this is, "speaker:<label>:" is someone else. Some labels are placeholders the recorder used for people it \
could not name. For each placeholder you are given, say who it is ONLY when a line of the transcript names them: \
another speaker addresses them by name right before or after their line ("<name>, go ahead"), or they introduce \
themselves ("I'm <name>"). Copy that line's words exactly as the quote; the quote must contain the name.

Rules:
- Never answer the person whose memory this is (the "user:" lines) for a placeholder.
- A label marked "several people" may be more than one person: give one entry per person you can name.
- Any other label is one person: give at most one name.
- The attendee list, when given, only helps spell a name the transcript says; never name anyone from it alone.
- When unsure, leave the label out. An empty list is a good answer.

Answer only JSON: {"speakers": [{"label": "speaker:...", "name": "...", "quote": "..."}]}"""


@dataclass(frozen=True)
class Named:
    marker: str   # ``speaker:<slug>``, as the body writes it
    name: str
    quote: str


def unnamed(episode: dict) -> list[tuple[str, bool]]:
    """The placeholder markers a meeting episode's speakers carry, each with whether it may be several people."""
    meeting = episode.get("meeting")
    if not isinstance(meeting, dict):
        return []
    out: dict[str, bool] = {}
    for label in meeting.get("speakers") or []:
        label = str(label)
        if mt.is_placeholder(label):
            m = mt.marker(label)
            out[m] = out.get(m, False) or mt.is_group_placeholder(label)
    return list(out.items())


def _norm(s: str) -> str:
    return " ".join(str(s).split()).casefold()


def _found(quote: str, text: str) -> bool:
    """Exact, then whitespace-folded, then case-insensitive — never fuzzy (the evidence-span ladder)."""
    q = str(quote or "").strip().strip('"“”')
    if len(q) < 4:
        return False
    return q in text or " ".join(q.split()) in " ".join(text.split()) or _norm(q) in _norm(text)


def _says(name: str, quote: str) -> bool:
    """Whether the quote says the name — the whole name, or each of its words, on word boundaries."""
    words = [w for w in re.split(r"\s+", name.strip()) if w]
    return bool(words) and all(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", quote, re.IGNORECASE) for w in words)


def _is_owner(name: str, owner: str | None) -> bool:
    from api.services import owner_identity

    if owner_identity.is_self_reference(name):
        return True
    if not owner:
        return False
    n, o = _norm(name), _norm(owner)
    return n == o or n in o.split() or o in n.split()


def keep(answer: dict, placeholders: list[tuple[str, bool]], text: str, *, owner: str | None) -> list[Named]:
    """The answers that hold up on the record (module docstring); everything else is dropped."""
    group = dict(placeholders)
    by_marker: dict[str, list[Named]] = {}
    rows = answer.get("speakers") if isinstance(answer, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        marker = str(row.get("label") or "").strip()
        name = mt.clean_label(row.get("name"))
        quote = " ".join(str(row.get("quote") or "").split())
        if marker not in group or not name or mt.is_placeholder(name) or mt.is_own(name):
            continue
        if _is_owner(name, owner) or not _found(quote, text) or not _says(name, quote):
            continue
        named = by_marker.setdefault(marker, [])
        if all(_norm(n.name) != _norm(name) for n in named):
            named.append(Named(marker, name, quote[:200]))
    kept: list[Named] = []
    for marker, named in by_marker.items():
        if len(named) > 1 and not group[marker]:
            logger.info(f"  meeting speakers: {marker} got {len(named)} names for one voice; left unnamed")
            continue
        kept.extend(named)
    return kept


async def identify(ep_id: str, text: str, placeholders: list[tuple[str, bool]], settings, *,
                   owner: str | None = None, attendees: list[str] | None = None, stage: str = STAGE) -> list[Named]:
    """One engine call for the placeholders in ``text`` (the masked text Stage 1 reads); ``[]`` on any refusal."""
    if not placeholders or not text.strip():
        return []
    import litellm

    from api.services import engine_errors
    from api.services.entity_extractor import _EXTRACT_RETRYABLE, _parse_json_lenient
    from api.services.providers import resolve_llm_fn

    asked = "\n".join(f'- "{m}"' + (" (several people)" if g else "") for m, g in placeholders)
    who = f"\nAttendees on the calendar (spelling help only): {', '.join(attendees)}" if attendees else ""
    try:
        llm_fn = resolve_llm_fn(settings, model=settings.litellm_model, completion=litellm.acompletion, stage=stage)
        response = await llm_fn(
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": f"Placeholders:\n{asked}{who}\n\nTranscript:\n{text[:MAX_CHARS]}"}],
            response_format={"type": "json_object"},
            timeout=TIMEOUT_S,
        )
        answer = _parse_json_lenient(response.choices[0].message.content)
    except (engine_errors.EngineRefused, *_EXTRACT_RETRYABLE, json.JSONDecodeError) as e:
        logger.info(f"  {ep_id}: meeting speakers not identified ({type(e).__name__}); read as labelled")
        return []
    kept = keep(answer, placeholders, text, owner=owner)
    if kept:
        logger.info(f"  {ep_id}: identified {len(kept)} meeting speaker(s) from the transcript's own words")
    return kept
