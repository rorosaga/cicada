"""G118 slice 2 (server half) — reading provenance back out of the bank.

Slice 1 made every new claim point at the words it came from (``evidence``
spans, ``api/services/evidence.py``); nothing could yet show them. This module
builds the read payloads the viewer needs, and nothing else:

* :func:`episode_document` — ``GET /episodes/{id}/text``: the whole evidence
  text with its turns, so the Reader can scroll to a span and highlight it
  (design §4.4 / §4.8.1).
* :func:`entity_provenance` — ``GET /entities/{id}/provenance`` (§4.5 / §4.8.4).
* :func:`episode_citations` — ``GET /episodes/{id}/citations`` (§4.8.3, G106).

Rails, enforced here rather than documented:

* **Engine-free, bank text only** (G80, G48). No LLM, no vector index, and
  never a transcript under ``~/.claude`` — every document is a bank file
  resolved by ``evidence.source_path``. ``test_the_provenance_module_is_engine_free``
  pins the import list.
* **Spans, not copies; computed at read, never stored.** Excerpts and derived
  offsets are recomputed per call, and nothing here writes a file.
* **Never fuzzy; stale never highlights** (§4.9). An asserted span is the
  stored offsets judged by ``evidence.span_status``; a ``derived`` span is a
  name match (``inbox_context.locate_mention``), labelled and never written
  back (R-PB9); a stale span travels WITHOUT wash offsets (R-PB2).
"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

from api.models.schemas import EpisodeFocus, EpisodeText, EpisodeTurn
from api.services import evidence, inbox_context, markdown_parser
from api.services.id_utils import resolve_entity_file

# The Reader's cap (R-PB5). A Stop-hook episode is already capped at 100,000
# chars (`transcript_extract.SESSION_CAP_CHARS`); an import is not, and one
# pasted log in a chat export must not become a multi-megabyte response.
# Characters, not bytes: offsets index code points and the cut must land on one.
MAX_TEXT_CHARS = 400_000


class SpanOutOfRange(ValueError):
    """A caller-supplied ``[start, end)`` that is not inside the document."""


def _opt(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _asserted_focus(text: str, start: int, end: int, hash: str | None, *,  # noqa: A002
                    is_episode: bool) -> EpisodeFocus:
    status = evidence.span_status(text, end=end, hash=hash, appendable=is_episode)
    kind = evidence.speaker_kind(text, start) if is_episode else "page"
    if status == evidence.SPAN_STALE:
        return EpisodeFocus(kind=kind, stale=True)  # R-PB2: no offsets to wash
    return EpisodeFocus(start=start, end=end, kind=kind, grown=status == evidence.SPAN_GROWN)


def _derived_focus(memory_path: Path, text: str, entity_ref: str) -> EpisodeFocus | None:
    page = resolve_entity_file(memory_path, entity_ref)
    # `focus` is a free query string and `resolve_entity_file` joins it onto
    # `entities/` as given, so `../<name>` would reach a file the bank never
    # stored as a page. Only a page that lives in `entities/` may name the
    # mention — the `evidence.source_path` rail, applied to the hint too.
    if page is None or page.resolve().parent != (Path(memory_path) / "entities").resolve():
        return None
    try:
        name = str(markdown_parser.parse(page).frontmatter.get("name") or page.stem)
    except Exception:
        name = page.stem
    hit = inbox_context.locate_mention(text, name, page.stem)
    if hit is None:
        return None
    return EpisodeFocus(start=hit[0], end=hit[1], kind="derived", derived=True)


def episode_document(
    memory_path: Path,
    doc_id: str,
    *,
    start: int | None = None,
    end: int | None = None,
    hash: str | None = None,  # noqa: A002 - the field's own name
    focus: str | None = None,
) -> EpisodeText | None:
    """The whole evidence text of ``doc_id`` with its turns, or ``None``.

    ``start``/``end`` (both or neither) ask for an asserted focus, judged by
    ``evidence.span_status`` against ``hash``; ``focus`` names an entity whose
    first mention becomes a derived focus. Raises :class:`SpanOutOfRange` for
    a half or out-of-range pair. Reads one file; writes nothing.
    """
    doc = evidence.source_document(memory_path, doc_id)
    if doc is None:
        return None
    fm, text = doc
    is_episode = evidence.is_episode_id(doc_id)
    length = len(text)
    if (start is None) != (end is None):
        raise SpanOutOfRange("start and end go together")
    if start is not None and not (0 <= start < end <= length):
        raise SpanOutOfRange(f"span [{start}, {end}) is outside the document (length {length})")

    stamps = evidence.turn_stamps(fm) if is_episode else {}
    spans = evidence.turns(text, page=not is_episode, stamps=stamps)
    truncated = length > MAX_TEXT_CHARS
    if truncated:
        spans = [
            replace(t, content_start=min(t.content_start, MAX_TEXT_CHARS), end=min(t.end, MAX_TEXT_CHARS))
            for t in spans if t.start < MAX_TEXT_CHARS
        ]

    focus_model: EpisodeFocus | None = None
    if start is not None:
        focus_model = _asserted_focus(text, start, end, hash, is_episode=is_episode)
    elif focus:
        focus_model = _derived_focus(memory_path, text, focus)

    return EpisodeText(
        episode=doc_id,
        kind="episode" if is_episode else "page",
        text=text[:MAX_TEXT_CHARS],
        length=length,
        hash=evidence.body_hash(text),
        truncated=truncated,
        title=_opt(fm.get("title") if is_episode else fm.get("name")) or doc_id,
        timestamp=_opt(fm.get("timestamp")),
        harness=_opt(fm.get("harness")),
        origin=_opt(fm.get("origin")) or _opt(fm.get("source")),
        conversation_id=_opt(fm.get("session_id")) or _opt(fm.get("source_id")),
        capture_kind=_opt(fm.get("capture_kind")),
        turns=[EpisodeTurn(**asdict(t)) for t in spans],
        focus=focus_model,
    )
