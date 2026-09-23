"""G118 slice 1 — evidence spans: WHERE in the stored text a belief came from.

The G118 row's first layer, "spans, not copies": a claim records character
offsets into text Cicada already holds — an episode body, or a media page's
stored description — plus a hash of that text, and never a quoted copy. The
bank already has the words; the claim only needs to point. That keeps the
ledger ids-only (G113), keeps a claim's YAML small, and makes staleness
detectable (R2) instead of silently mis-highlighting.

Three writers call :func:`verify`: Stage-1 extraction (the quote the model
says it relied on, against the exact body it chunked — R11), the agentic
write path (an agent citing what the person just said, through
``cicada_write_claim``), and link recon (the surface form it grounded on,
against the media page's prose — R12). One reader, the ``episodes`` router,
calls :func:`source_text` to slice a span back out.

Rails this module enforces rather than documents:

* **Engine-free** (G80): imports ``markdown_parser`` and ``claims`` only. A
  verification is string search over one parsed file.
* **Never fuzzy** (R5): exact, then whitespace-normalised, then
  case-insensitive — and an unlocatable quote becomes ``reasoning``, never a
  guessed span. Provenance must never block memory, so nothing here raises.
* **Only bank text** (G48): :func:`source_path` resolves ids inside the bank
  and refuses anything that is not a bare document id. Transcripts under
  ``~/.claude`` are never opened.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from api.services import markdown_parser
from api.services.claims import EVIDENCE_KINDS, Evidence, strip_claims_block

__all__ = [
    "EVIDENCE_KINDS", "MAX_QUOTE_CHARS", "body_hash", "is_episode_id", "source_path",
    "source_text", "locate", "speaker_kind", "reasoning", "verify", "verify_many",
    "attach_relationship_evidence",
    # G118 slice 2
    "SPAN_CURRENT", "SPAN_GROWN", "SPAN_STALE", "turn_starts", "span_status", "TurnSpan", "turns",
    "turn_stamps", "source_document",
    # G140 Q-R9
    "media_time",
]

# The longest quote a writer may cite. A longer one is clipped, not refused:
# the clipped head is still a verbatim substring, so the span is simply
# shorter than the writer offered. 240 chars is a sentence or two — enough to
# highlight, small enough that the prompt never asks for a paragraph.
MAX_QUOTE_CHARS = 240

# A source-document id (R3): a bare stem, no separators that could escape the
# bank. `episode_ids.EPISODE_ID_RE` is stricter for episodes; media ids are
# `media-<slug>`; both fit here.
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_EPISODE_PREFIX = "ep_"

# R4: the turn markers Cicada's own writers produce. Imported conversations
# write `<role>: <text>` per message (api/routers/conversations.py:792, the
# body at :911/:934), roles user/assistant/system and `unknown` for a message
# the export did not attribute; `human`/`ai` are accepted for hand-written or
# third-party episodes. `system` is the person's configured context and
# `unknown` is unattributed, so both count as `user` below — the only way a
# span is labelled the model's is a line that says so.
#
# G140 Q-R9: a `video`/`media` line is what a video said — a watch record's
# cited excerpt (`video [12:34]: …`, `watch_record`). Its `[m:ss]`/`[h:mm:ss]`
# is REQUIRED: "Video:" opens ordinary lines in a person's own messages, and
# reading those as a video's words would be R5 §2 defect 3 in reverse. The six
# original words keep their alternative byte for byte, so no stored episode
# reads differently. `media_time` reads the time back at read time.
_TURN_RE = re.compile(
    r"^(?:(user|human|assistant|ai|system|unknown)"
    r"|(video|media)\s*\[(?P<t>\d{1,2}(?::\d{2}){1,2})\])\s*:",
    re.IGNORECASE,
)
_ASSISTANT_ROLES = frozenset({"assistant", "ai"})
_MEDIA_ROLES = frozenset({"video", "media"})


def _marker_word(m: re.Match[str]) -> str:
    """The marker word a ``_TURN_RE`` match stands on, lower-cased — group 1
    for the six conversation words, group 2 for a timed video line."""
    return (m.group(1) or m.group(2) or "").lower()


def _role(marker: str | None) -> str:
    """The kind a marker word stands for — ONE mapping, read by both
    ``speaker_kind`` and ``turns``, so a turn's role and a span's kind can
    never disagree (R-PB3)."""
    word = (marker or "").lower()
    if word in _ASSISTANT_ROLES:
        return "assistant"
    if word in _MEDIA_ROLES:
        return "media"
    return "user"


def body_hash(text: str) -> str:
    """R2: ``sha256[:12]`` of the evidence text — same width as the episode
    ``content_hash`` the MCP seam already stamps."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def is_episode_id(doc_id: str) -> bool:
    return (doc_id or "").startswith(_EPISODE_PREFIX)


def source_path(memory_path: Path | None, doc_id: str) -> Path | None:
    """Resolve a source-document id to its file inside the bank, or ``None``.

    ``ep_*`` lives under ``episodes/``; everything else under ``entities/``
    (R3). An id that is not a bare stem is refused outright — the only text a
    span may index is text Cicada stored (G48), and this is the one place
    that rule is enforced for every reader and writer.
    """
    doc_id = (doc_id or "").strip()
    if memory_path is None or not _DOC_ID_RE.match(doc_id):
        return None
    subdir = "episodes" if is_episode_id(doc_id) else "entities"
    path = Path(memory_path) / subdir / f"{doc_id}.md"
    return path if path.is_file() else None


def source_document(memory_path: Path | None, doc_id: str) -> tuple[dict, str] | None:
    """``(frontmatter, evidence text)`` from ONE parse and the same resolver
    as :func:`source_text`, so the Reader's header and its text can never
    come from two different files (slice 2). ``None`` for an unknown or
    non-bare id."""
    path = source_path(memory_path, doc_id)
    if path is None:
        return None
    try:
        parsed = markdown_parser.parse(path)
    except Exception:
        return None
    body = parsed.body if is_episode_id(doc_id) else strip_claims_block(parsed.body)
    return (parsed.frontmatter or {}), body


def source_text(memory_path: Path | None, doc_id: str) -> str | None:
    """The evidence text of a document (R1): the parsed body for an episode;
    for an entity page, the body with the ```claims fence stripped — so the
    claim that cites a page never stales its own span by being written."""
    doc = source_document(memory_path, doc_id)
    return None if doc is None else doc[1]


def _pattern(quote: str, *, whole_word: bool, flags: int = 0) -> re.Pattern[str]:
    core = r"\s+".join(re.escape(tok) for tok in quote.split())
    if whole_word:
        core = rf"(?<![A-Za-z0-9]){core}(?![A-Za-z0-9])"
    return re.compile(core, flags)


def _exact_matches(text: str, quote: str) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    i = text.find(quote)
    while i != -1:
        out.append((i, i + len(quote)))
        i = text.find(quote, i + 1)
    return out


def _first(matches: list[tuple[int, int]], window: tuple[int, int] | None) -> tuple[int, int] | None:
    if window is not None:
        lo, hi = window
        for s, e in matches:
            if s >= lo and e <= hi:
                return (s, e)
    return matches[0] if matches else None


def locate(
    text: str,
    quote: str,
    *,
    window: tuple[int, int] | None = None,
    whole_word: bool = False,
) -> tuple[int, int] | None:
    """R5: find ``quote`` in ``text`` — exact, then whitespace-normalised,
    then case-insensitive — and stop. ``window`` (a Stage-1 chunk) prefers an
    occurrence inside it over the first in the document. ``whole_word``
    refuses a hit inside a longer token ("Go" in "Google") and skips the
    plain-substring rung for the same reason. ``None`` means "not there".
    """
    quote = (quote or "").strip()
    if not quote or not text:
        return None
    if len(quote) > MAX_QUOTE_CHARS:
        quote = quote[:MAX_QUOTE_CHARS].rstrip()
    rungs: list[list[tuple[int, int]]] = []
    if not whole_word:
        rungs.append(_exact_matches(text, quote))
    rungs.append([(m.start(), m.end()) for m in _pattern(quote, whole_word=whole_word).finditer(text)])
    rungs.append([
        (m.start(), m.end())
        for m in _pattern(quote, whole_word=whole_word, flags=re.IGNORECASE).finditer(text)
    ])
    for matches in rungs:
        hit = _first(matches, window)
        if hit is not None:
            return hit
    return None


def speaker_kind(text: str, start: int) -> str:
    """R4: ``assistant`` when the last turn marker at or before ``start`` is
    the model's, ``media`` when it is a timed video line (G140), ``user``
    otherwise — including no marker at all, because every marker-less writer
    captures the person's own input.

    Scans through the END of the line that contains ``start`` (not just
    ``text[:start]``): a marker only ever matches at a line's first column,
    which is at or before ``start`` by construction, so this is exactly "at
    or before" — and it is what makes a quote that begins with
    ``assistant: …`` land on that marker instead of the previous turn's.
    """
    text = text or ""
    start = max(int(start), 0)
    line_end = text.find("\n", start)
    head = text if line_end == -1 else text[:line_end]
    kind = "user"
    for line in head.splitlines():
        m = _TURN_RE.match(line)
        if m:
            kind = _role(_marker_word(m))
    return kind


def _seconds(raw: str | None) -> int | None:
    """``m:ss`` / ``h:mm:ss`` → seconds. Local on purpose: this module
    imports only ``markdown_parser`` and ``claims`` (G80)."""
    if not raw:
        return None
    total = 0
    for part in raw.split(":"):
        if not part.isdigit():
            return None
        total = total * 60 + int(part)
    return total


def media_time(text: str, start: int) -> int | None:
    """Seconds into the video for a span on a ``video [m:ss]:`` line (G140
    Q-R9) — read at read time from the marker line at or before ``start``,
    the same line ``speaker_kind`` reads, and never stored on the evidence.
    ``None`` on any other line."""
    text = text or ""
    start = max(int(start), 0)
    line_end = text.find("\n", start)
    head = text if line_end == -1 else text[:line_end]
    found = None
    for line in head.splitlines():
        m = _TURN_RE.match(line)
        if m:
            found = m
    if found is None or _role(_marker_word(found)) != "media":
        return None
    return _seconds(found.group("t"))


def _marker_lines(text: str) -> list[tuple[int, str, int, str | None]]:
    """``(line start, marker word, content start, time)`` for every
    turn-marker line — ``time`` is the raw ``m:ss`` of a timed video line
    (G140 Q-R9), ``None`` for the six conversation words.

    The SAME lines :func:`speaker_kind` treats as turn boundaries — same
    ``_TURN_RE``, same ``splitlines`` — so a turn's role and a span's kind can
    never disagree (slice 2, R-PB3: one parser, server-side). ``content start``
    skips the marker and the spaces after it, so no client runs a regex of its
    own. Ascending by construction.
    """
    out: list[tuple[int, str, int, str | None]] = []
    pos = 0
    for line in (text or "").splitlines(keepends=True):
        m = _TURN_RE.match(line)
        if m:
            content = m.end()
            while content < len(line) and line[content] in " \t":
                content += 1
            out.append((pos, _marker_word(m), pos + content, m.group("t")))
        pos += len(line)
    return out


def turn_starts(text: str) -> list[int]:
    """Offsets of every turn-marker line, ascending (R-PB3)."""
    return [start for start, *_ in _marker_lines(text)]


@dataclass
class TurnSpan:
    """One turn of a document, as offsets into its evidence text (slice 2).

    ``start`` is the first character of the turn's marker line (``user: …``),
    or of the document for a block before any marker; ``content_start`` skips
    the marker and the spaces after it; ``end`` is exclusive and stops before
    the newline that separates it from the next turn. ``role`` is exactly what
    :func:`speaker_kind` answers inside the turn (``user`` | ``assistant`` |
    ``media``), or ``page`` for an entity page. ``marker`` is the word as written, lower-cased
    — ``system``/``unknown`` count as the person under R4 and the Reader may
    say so — and ``None`` for a block with no marker line. ``ts``/``speaker``
    come only from a stored ``turns`` sidecar entry at exactly ``start``: a
    time is never inferred (§4.4). ``t`` is the seconds into the video for a
    ``video [m:ss]:`` turn (G140 Q-R9) — derived from the marker, never
    stored.
    """

    index: int
    start: int
    content_start: int
    end: int
    role: str
    marker: str | None = None
    ts: str | None = None
    speaker: str | None = None
    t: int | None = None


def turns(text: str, *, page: bool = False, stamps: dict[int, dict] | None = None) -> list[TurnSpan]:
    """The document as turns (R-PB3, R-PB5) — the marker lines
    :func:`speaker_kind` reads, so a turn's ``role`` and a span's ``kind``
    never disagree (``test_turns_agree_with_speaker_kind_at_every_offset``).

    A page is one ``page`` block. An episode with no marker at all (a legacy
    MCP note, a Telegram capture) is one ``user`` block — never an error — and
    text before the first marker is its own block under R4's default.
    """
    text = text or ""
    if not text:
        return []
    if page:
        return [TurnSpan(index=1, start=0, content_start=0, end=len(text), role="page")]
    stamps = stamps or {}
    blocks: list[tuple[int, str | None, int, str | None]] = list(_marker_lines(text))
    if not blocks or blocks[0][0] > 0:
        blocks.insert(0, (0, None, 0, None))
    out: list[TurnSpan] = []
    for i, (start, marker, content_start, stamp_raw) in enumerate(blocks):
        nxt = blocks[i + 1][0] if i + 1 < len(blocks) else len(text)
        end = start + len(text[start:nxt].rstrip("\r\n"))
        sidecar = stamps.get(start) or {}
        role = _role(marker)
        out.append(TurnSpan(
            index=i + 1, start=start, content_start=min(content_start, end), end=end,
            role=role, marker=marker, ts=sidecar.get("ts"), speaker=sidecar.get("speaker"),
            t=_seconds(stamp_raw) if role == "media" else None,
        ))
    return out


def turn_stamps(frontmatter: dict | None) -> dict[int, dict]:
    """The ``turns: [{offset, ts, speaker}]`` sidecar (R-PB4), keyed by offset.

    Written by the chat importer (``conversations._turn_stamps``) and by the
    Local-sources track's stager — the same key and shape, which IS the
    coordination contract. Tolerant by design: the Stop hook's
    ``turns: <count>`` (``transcript_capture``) is an int, not a sidecar, and
    reads as no stamps; a malformed or duplicate entry is skipped, never
    raised. ``ts``/``speaker`` pass through verbatim (``None`` when absent) —
    nothing here infers a time.
    """
    raw = (frontmatter or {}).get("turns")
    if not isinstance(raw, list):
        return {}
    out: dict[int, dict] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            offset = int(entry.get("offset"))
        except (TypeError, ValueError):
            continue
        if offset < 0 or offset in out:
            continue
        ts, speaker = entry.get("ts"), entry.get("speaker")
        out[offset] = {
            "ts": str(ts) if ts not in (None, "") else None,
            "speaker": str(speaker) if speaker not in (None, "") else None,
        }
    return out


# G118 slice 2 (design amendment A7) — what a stored span's hash says about the
# text it is read against NOW. `grown` is exact: the offsets still index the
# words that were cited, so it highlights; `stale` never does (§4.9).
SPAN_CURRENT = "current"
SPAN_GROWN = "grown"
SPAN_STALE = "stale"


def span_status(
    text: str,
    *,
    end: int,
    hash: str | None,  # noqa: A002 - the field's own name
    appendable: bool = True,
) -> str:
    """A7 (amends slice-1 R2): is a span minted against ``hash`` still exact here?

    Slice 1 compared the stored hash with the WHOLE current text, so every
    span in a conversation that continued after Sleep read ``stale``: the Stop
    hook rewrites a session's one episode in place with appended turns
    (``transcript_capture.capture_transcript``), G20 rewrites a grown chat
    export the same way, and ``transcript_extract.SESSION_CAP_CHARS`` is
    head-stable precisely so those offsets do not move. So when the whole text
    does not match, try every prefix that ends at the newline just before a
    turn-marker line and still covers the span (``cut >= end``): if one hashes
    to ``hash``, the cited text is byte-identical and the answer is ``grown``.

    One incremental pass (``update`` + ``copy``), so it costs O(len) however
    many turns there are. Exact — a 48-bit hash over a string that was once
    the whole body — and never fuzzy. ``appendable=False`` for a ``page``
    document: a description is rewritten, not appended, so a prefix match
    there would be a coincidence. No ``hash`` means nothing to be stale
    against: ``current`` (slice-1 R2).
    """
    if not hash:
        return SPAN_CURRENT
    text = text or ""
    if body_hash(text) == hash:
        return SPAN_CURRENT
    if not appendable:
        return SPAN_STALE
    digest = hashlib.sha256()
    pos = 0
    for start in turn_starts(text):
        cut = start - 1
        if cut < 0 or text[cut] != "\n":
            continue
        digest.update(text[pos:cut].encode("utf-8"))
        pos = cut
        if cut >= end and digest.copy().hexdigest()[:12] == hash:
            return SPAN_GROWN
    return SPAN_STALE


def reasoning(doc_id: str = "", *, hash: str = "") -> Evidence:  # noqa: A002 - the field's own name
    """R6: the contributor cited itself. ``hash`` is kept when the document
    was readable so a viewer can still open it."""
    return Evidence(episode=(doc_id or "").strip(), start=-1, end=-1, kind="reasoning", hash=hash)


def verify(
    memory_path: Path | None,
    doc_id: str,
    quote: str,
    *,
    text: str | None = None,
    window: tuple[int, int] | None = None,
    whole_word: bool = False,
) -> Evidence:
    """Turn a cited quote into an :class:`Evidence` — a span when the quote is
    in the document, ``reasoning`` when it is not. Never raises.

    ``text`` short-circuits the disk read when the caller already holds the
    evidence text (Stage 1 holds the body it chunked — R11). Kind is the
    speaker for an episode and ``page`` for an entity document.
    """
    doc_id = (doc_id or "").strip()
    if not doc_id:
        return reasoning("")
    if text is None:
        text = source_text(memory_path, doc_id)
    if text is None:
        return reasoning(doc_id)
    digest = body_hash(text)
    span = locate(text, quote, window=window, whole_word=whole_word)
    if span is None:
        return reasoning(doc_id, hash=digest)
    start, end = span
    kind = speaker_kind(text, start) if is_episode_id(doc_id) else "page"
    return Evidence(episode=doc_id, start=start, end=end, kind=kind, hash=digest)


def verify_many(memory_path: Path | None, items: Iterable | None) -> list[Evidence]:
    """The agent-write shape: ``[{episode, quote}, ...]`` → deduped evidence.
    Entries without an ``episode`` or that are not mappings are skipped — an
    agent's malformed citation must not fail its claim. An optional
    ``window: [start, end]`` per item is an internal hint for writers that
    know which section the words are in (the Telegram ``saved-because``
    claim, R13); the MCP schema does not advertise it and an agent passing
    it is harmless."""
    out: list[Evidence] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("episode") or "").strip()
        if not doc_id:
            continue
        raw_window = item.get("window")
        window: tuple[int, int] | None = None
        if isinstance(raw_window, (list, tuple)) and len(raw_window) == 2:
            try:
                window = (int(raw_window[0]), int(raw_window[1]))
            except (TypeError, ValueError):
                window = None
        ev = verify(memory_path, doc_id, str(item.get("quote") or ""), window=window)
        if ev not in out:
            out.append(ev)
    return out


def attach_relationship_evidence(
    rel: dict, episode_id: str, body: str, *, window: tuple[int, int] | None = None
) -> None:
    """Stage 1: consume ``rel["evidence_quote"]`` and set ``rel["evidence"]``.

    The quote is POPPED, not kept — spans, not copies, holds even for the
    transient extraction dict. ``body`` is the full episode content
    ``extract`` chunked (R11), so offsets land in the stored body and the
    hash is the stored hash without a second read. Mutates in place.
    """
    quote = rel.pop("evidence_quote", None)
    ev = verify(None, episode_id, str(quote or ""), text=body, window=window)
    rel["evidence"] = [ev.to_dict()]
