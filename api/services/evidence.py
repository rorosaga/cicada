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
from pathlib import Path
from typing import Iterable

from api.services import markdown_parser
from api.services.claims import EVIDENCE_KINDS, Evidence, strip_claims_block

__all__ = [
    "EVIDENCE_KINDS", "MAX_QUOTE_CHARS", "body_hash", "is_episode_id", "source_path",
    "source_text", "locate", "speaker_kind", "reasoning", "verify", "verify_many",
    "attach_relationship_evidence",
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
_TURN_RE = re.compile(r"^(user|human|assistant|ai|system|unknown)\s*:", re.IGNORECASE)
_ASSISTANT_ROLES = frozenset({"assistant", "ai"})


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


def source_text(memory_path: Path | None, doc_id: str) -> str | None:
    """The evidence text of a document (R1): the parsed body for an episode;
    for an entity page, the body with the ```claims fence stripped — so the
    claim that cites a page never stales its own span by being written."""
    path = source_path(memory_path, doc_id)
    if path is None:
        return None
    try:
        body = markdown_parser.parse(path).body
    except Exception:
        return None
    return body if is_episode_id(doc_id) else strip_claims_block(body)


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
    the model's; ``user`` otherwise — including no marker at all, because
    every marker-less writer captures the person's own input.

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
            kind = "assistant" if m.group(1).lower() in _ASSISTANT_ROLES else "user"
    return kind


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
