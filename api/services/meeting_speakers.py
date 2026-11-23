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
from pathlib import Path

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


# --- Asking the person (ROR-142 slice 2) ---------------------------------------------------------------------------
#
# The owner, 2026-11-23: "the labeling can be a quick question from cicada, saying smth like (in the meeting "meeting
# name" you were speaking with ... who was speaker 1, or the guy who said x and y". A voice the identification left
# unnamed is asked about once, on the existing ``clarification`` kind (``asks: speaker``). The answer is stored by
# source in ``meetings/speaker-names.yaml`` — this module its one writer — which the parser applies on every sync
# (``meeting_transcripts.draft_for_file``), and the stored episode is relabelled in place at once, a revision Sleep
# reads where it changed. Only the person's answer names anyone; no rule, judge or other conversation settles it.

#: An extraction result's record of a meeting's placeholders: ``{"named": [names], "unnamed": [markers]}``.
RESULT_KEY = "meeting_speakers"
ASKS = "speaker"
NAMES_FILE = "meetings/speaker-names.yaml"
DECLINE_KEY = "dont_know"
DECLINE_LABEL = "Someone I don't know"
#: A voice with fewer lines than this is not worth a question.
MIN_LINES = 5
MAX_QUOTE_CHARS = 110
MAX_OPTIONS = 4


class NotAName(ValueError):
    """The answer cannot name this speaker (empty, a placeholder, or the person themselves)."""


def result_record(placeholders: list[tuple[str, bool]], named: list[Named]) -> dict:
    """What Stage 5.4c needs from Stage 1: the names kept, and the one-voice placeholders still unnamed."""
    done = {n.marker for n in named}
    return {"named": sorted({n.name for n in named}),
            "unnamed": [m for m, group in placeholders if not group and m not in done]}


def _names_path(memory_path: Path) -> Path:
    return Path(memory_path) / NAMES_FILE


def _load(memory_path: Path) -> dict:
    import yaml

    path = _names_path(memory_path)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        logger.warning("meeting speakers: the names file is unreadable; answers wait until it is repaired")
        return {}
    return data if isinstance(data, dict) else {}


def _save(memory_path: Path, data: dict) -> None:
    import os
    import tempfile

    import yaml

    path = _names_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".speaker-names.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=True)
    os.replace(tmp, path)


def names_for(memory_path: Path | None, source_id: str) -> dict[str, str]:
    """The person's answers for one meeting file: placeholder label → name (a declined one is no name)."""
    if memory_path is None:
        return {}
    rows = _load(memory_path).get(source_id)
    return {str(label): str(row["name"]) for label, row in (rows or {}).items()
            if isinstance(row, dict) and row.get("name")} if isinstance(rows, dict) else {}


def _answered(memory_path: Path, source_id: str, label: str) -> bool:
    rows = _load(memory_path).get(source_id)
    return isinstance(rows, dict) and label in rows


def _record(memory_path: Path, source_id: str, label: str, row: dict) -> None:
    data = _load(memory_path)
    data.setdefault(source_id, {})[label] = row
    _save(memory_path, data)


def _episode(memory_path: Path, episode_id: str) -> tuple[Path, dict, str] | None:
    from api.services import markdown_parser

    path = Path(memory_path) / "episodes" / f"{episode_id}.md"
    if not path.is_file():
        return None
    parsed = markdown_parser.parse(path)
    return path, parsed.frontmatter, parsed.body


def _label_of(fm: dict, marker: str) -> str | None:
    meeting = fm.get("meeting") if isinstance(fm.get("meeting"), dict) else {}
    return next((str(s) for s in meeting.get("speakers") or []
                 if mt.is_placeholder(str(s)) and mt.marker(str(s)) == marker), None)


def _lines_of(body: str, marker: str) -> list[str]:
    prefix = f"{marker}: "
    return [line[len(prefix):].strip() for line in body.split("\n") if line.startswith(prefix)]


def _clip(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= MAX_QUOTE_CHARS:
        return text.rstrip(".")
    cut = text[:MAX_QUOTE_CHARS].rsplit(" ", 1)[0]
    return cut.rstrip(",;:.") + "…"


def _open_question(memory_path: Path, episode_id: str, marker: str) -> Path | None:
    from api.services import markdown_parser

    inbox = Path(memory_path) / "inbox"
    for path in sorted(inbox.glob("inbox-*.md")) if inbox.is_dir() else []:
        try:
            fm = markdown_parser.parse(path).frontmatter
        except Exception:  # noqa: BLE001 - an unreadable item is no question
            continue
        if (fm.get("asks") == ASKS and fm.get("source_episode") == episode_id
                and fm.get("speaker_marker") == marker and str(fm.get("status") or "pending") == "pending"):
            return path
    return None


def _with(names: list[str]) -> str:
    if not names:
        return "people the recording didn't name"
    if len(names) == 1:
        return f"{names[0]} and someone else"
    return ", ".join(names[:-1]) + f" and {names[-1]}, and someone else"


def ensure_question(memory_path: Path, episode_id: str, marker: str, *, named: list[str] | None = None,
                    owner: str | None = None, today: str | None = None) -> Path | None:
    """"Who was Speaker 1?" about one voice of one meeting, once. ``None`` when it is not a one-voice placeholder of
    that meeting, has too few lines, was answered or declined, or is already asked."""
    from datetime import date

    from api.services import markdown_parser
    from api.services.role_people import _next_item

    found = _episode(memory_path, episode_id)
    if found is None:
        return None
    _path, fm, body = found
    label = _label_of(fm, marker)
    source_id = str(fm.get("source_id") or "")
    if not label or mt.is_group_placeholder(label) or not source_id or fm.get("source_deleted_at"):
        return None
    lines = _lines_of(body, marker)
    if len(lines) < MIN_LINES or _answered(memory_path, source_id, label):
        return None
    if _open_question(memory_path, episode_id, marker) is not None:
        return None
    title = str(fm.get("title") or "a meeting")
    day = str(fm.get("original_date") or fm.get("timestamp") or "")[:10]
    said = [q for q in sorted({_clip(x) for x in lines if len(x.split()) >= 4}, key=len, reverse=True)][:2]
    quotes = " and ".join(f"“{q}”" for q in said)
    question = (f"In “{title}”{f' ({day})' if day else ''} you talked with {_with(named or [])}. "
                f"Who was {label}{f', the one who said {quotes}' if quotes else ''}?")
    meeting = fm.get("meeting") if isinstance(fm.get("meeting"), dict) else {}
    taken = {n.casefold() for n in (named or [])}
    picks = [a for a in (str(x) for x in meeting.get("attendees") or [])
             if a.strip() and a.casefold() not in taken and not _is_owner(a, owner) and not mt.is_placeholder(a)]
    options = [{"key": f"name:{i}", "label": a} for i, a in enumerate(picks[:MAX_OPTIONS])]
    options.append({"key": DECLINE_KEY, "label": DECLINE_LABEL})
    item = {
        "kind": "clarification",
        "asks": ASKS,
        "required_input": "freetext",
        "status": "pending",
        "priority": 0.6,
        "entity_id": episode_id,
        "entity_name": title,
        "title": f"Who was {label} in “{title}”?",
        "question": question,
        "options": options,
        "allow_other": True,
        "allow_defer": True,
        "uncertainty_type": "Unnamed meeting speaker",
        "suggested_classification": "person",
        "suggested_confidence": 0.5,
        "source_episode": episode_id,
        "speaker_marker": marker,
        "speaker_label": label,
        "meeting_source": source_id,
        "created_date": today or str(date.today()),
    }
    inbox = Path(memory_path) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    path = _next_item(inbox)
    context = "\n".join(f"> {_clip(x)}" for x in lines[:3])
    markdown_parser.write(path, item, f"What {label} said in this meeting:\n\n{context}")
    return path


def ask_after_read(memory_path: Path, extracted: list[dict], *, owner: str | None = None) -> list[Path]:
    """Sleep, Stage 5.4c: one question per voice its meetings left unnamed (``RESULT_KEY`` on each result)."""
    asked = []
    for result in extracted or []:
        record = result.get(RESULT_KEY) if isinstance(result, dict) else None
        if not isinstance(record, dict):
            continue
        for marker in record.get("unnamed") or []:
            path = ensure_question(memory_path, str(result.get("episode_id") or ""), str(marker),
                                   named=list(record.get("named") or []), owner=owner)
            if path is not None:
                asked.append(path)
    return asked


def answer(memory_path: Path, item: dict, name: str, *, owner: str | None = None) -> list[str]:
    """The person named the voice: stored for the file, and the stored meeting relabelled in place (a revision Sleep
    reads where it changed). Returns the manifest lines. Raises :class:`NotAName`."""
    from api.services import episode_ids, episode_staging

    name = mt.clean_label(name)
    if not name or mt.is_placeholder(name) or mt.is_own(name):
        raise NotAName("that isn't a name")
    if _is_owner(name, owner):
        raise NotAName("your own lines are already yours (labelled You)")
    episode_id = str(item.get("source_episode") or "")
    label, marker = str(item.get("speaker_label") or ""), str(item.get("speaker_marker") or "")
    source_id = str(item.get("meeting_source") or "")
    if not (episode_id and label and marker and source_id):
        raise NotAName("this question is missing its meeting")
    _record(memory_path, source_id, label, {"name": name, "at": episode_ids.utc_now_iso()})
    lines = [f"{NAMES_FILE}: updated"]
    found = _episode(memory_path, episode_id)
    if found is not None:
        def named_in_record(fm: dict) -> None:
            meeting = dict(fm.get("meeting") or {})
            meeting["speakers"] = [name if str(s) == label else s for s in meeting.get("speakers") or []]
            meeting["named_by_person"] = {**(meeting.get("named_by_person") or {}), label: name}
            fm["meeting"] = meeting

        if episode_staging.relabel_in_place(found[0], marker, mt.marker(name), update=named_in_record):
            lines.append(f"episodes/{episode_id}.md: updated")
    return lines


def decline(memory_path: Path, item: dict) -> list[str]:
    """"Someone I don't know": remembered, so the voice is never asked about again; nothing else changes."""
    from api.services import episode_ids

    source_id, label = str(item.get("meeting_source") or ""), str(item.get("speaker_label") or "")
    if source_id and label:
        _record(memory_path, source_id, label, {"declined": True, "at": episode_ids.utc_now_iso()})
    return [f"{NAMES_FILE}: updated"]


def gone(memory_path: Path, item: dict) -> bool:
    """The meeting this question is about is no longer in memory (removed, or its file deleted)."""
    found = _episode(memory_path, str(item.get("source_episode") or ""))
    return found is None or bool(found[1].get("source_deleted_at"))
