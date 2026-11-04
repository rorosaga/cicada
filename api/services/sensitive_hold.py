"""The one door to every engine: what is on record as confident never goes through it (G235, ruling 60).

Every model call Cicada starts, for any job and on any engine, passes :func:`hold_back` inside
``providers.resolve_llm_fn``; every text for a hosted embedding model passes :func:`hold_texts`. A new caller gets it by
resolving a model the only way there is (`test_sensitive_hold` fails on any other way). So this is **by value, not by
offset or by caller**: a line built from a conversation can be a reply note, a question's evidence, a web query or a page's
prose, and a mask at one caller would miss the next one.

What is held: every confident hit (``Hit.sure``) in every conversation of the bank, minus what the person left
(`Leave it`), wherever the same value stands in a prompt. A value that could be an ordinary word or short number
(`sensitive_text.distinctive`) goes only on a line that speaks of a secret. A value cut in two by a line's length limit
is covered too. And the prompt is read once by itself, the way a coding session is read (a statement of one's own, or of
a named system), for words no conversation holds yet: a saved reason, a page's prose.

An unsure hit is still read and reported (ruling 60).

**Nothing stores a value.** This keeps per-file offsets, keyed on the file's stamp, in memory, and re-reads the few files
with a hit on each call. Reads files only. A failure here costs the bank-wide half and logs its class; a prompt is still
read by itself. Never raises.

**Agents the person talks to are not this.** recall, ``cicada_sources`` and Ask's cited sources hand the record as stored
to the person's own agent on the person's own ask, until they remove it. Ask's own model is an engine Cicada runs, so it
goes through here."""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from api.services import authorship, bank_index, evidence, sensitive_text
from api.services.sensitive_text import HELD_MARK


@dataclass(frozen=True)
class _Entry:
    stamp: tuple[int, int]
    #: (kind, start, end) of each confident hit still waiting, and (start, end) of each the person left.
    held: tuple[tuple[str, int, int], ...] = ()
    left: tuple[tuple[int, int], ...] = ()


_lock = threading.Lock()
_banks: dict[str, dict[str, _Entry]] = {}


def forget() -> None:
    with _lock:
        _banks.clear()


def _read(f) -> _Entry:
    from api.services import sensitive_flags

    stamp = (f.mtime_ns, f.size)
    fm = f.frontmatter or {}
    if authorship.of(fm) == evidence.SAVE_KIND:
        return _Entry(stamp)
    hits = sensitive_flags.hits_of(fm, f.body() or "")
    if not hits:
        return _Entry(stamp)
    live = sensitive_flags.not_left(fm, hits)
    held = tuple((h.kind, h.start, h.end) for h in live if h.sure)
    left = tuple((h.start, h.end) for h in hits if h not in live)
    return _Entry(stamp, held, left)


def on_record(memory_path) -> tuple[dict[str, str], frozenset[str]]:
    """``(value -> its mark, values the person left)`` as the bank's files say now. In memory, for this one call."""
    key = str(memory_path)
    files = {f.path.name: f for f in bank_index.files(Path(memory_path), "episodes")}
    with _lock:
        entries = _banks.setdefault(key, {})
        for name in set(entries) - set(files):
            del entries[name]
        for name, f in files.items():
            entry = entries.get(name)
            if entry is None or entry.stamp != (f.mtime_ns, f.size):
                try:
                    entries[name] = _read(f)
                except Exception as exc:  # noqa: BLE001 - one unreadable conversation is no value
                    logger.debug(f"sensitive hold skipped one: {type(exc).__name__}")
                    entries[name] = _Entry((f.mtime_ns, f.size))
        flagged = [(name, e) for name, e in entries.items() if e.held or e.left]
    marks: dict[str, str] = {}
    left: set[str] = set()
    for name, entry in flagged:
        try:
            body = files[name].body() or ""
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"sensitive hold skipped one: {type(exc).__name__}")
            continue
        for kind, start, end in entry.held:
            marks[body[start:end]] = HELD_MARK.format(kind=kind)
        left.update(body[start:end] for start, end in entry.left)
    return marks, frozenset(left - set(marks))


def _cut_in_two(text: str, marks: dict[str, str]) -> str:
    """A value a length limit cut: at least half of it right before an ellipsis, or at a line's end."""
    for value, mark in marks.items():
        if not sensitive_text.distinctive(value) or not 6 <= len(value) <= 128:
            continue
        heads = [re.escape(value[:n]) for n in range(len(value) - 1, max(3, len(value) // 2 - 1), -1)]
        rx = re.compile(rf"(?<![\w])(?:{'|'.join(heads)})(?=…|\.\.\.|[\"'”’»)\]]*\s*$)", re.M)
        text = rx.sub(lambda _m: mark, text)
    return text


def _view(text: str, marks: dict[str, str], left: frozenset[str], *, by_itself: bool) -> str:
    if not text:
        return text
    text, _n = sensitive_text.take_out(text, marks)
    if marks:
        text = _cut_in_two(text, marks)
    if by_itself:
        hits = [h for h in sensitive_text.find(text, harness=True) if h.sure and text[h.start:h.end] not in left]
        text = sensitive_text.replace_hits(text, hits, HELD_MARK)
    return text


def _known(memory_path) -> tuple[dict[str, str], frozenset[str]]:
    try:
        if isinstance(memory_path, (str, Path)) and (Path(memory_path) / "episodes").is_dir():
            return on_record(memory_path)
    except Exception as exc:  # noqa: BLE001 - never the reason a read fails; a prompt is still read by itself below
        logger.warning(f"Sensitive hold could not read the bank: {type(exc).__name__}")
    return {}, frozenset()


def warm(memory_path) -> None:
    """The first look at a bank reads every conversation once (about 7 ms for 25 KB of talk about logins, worst case);
    after that one ``os.scandir`` says what changed. Called off the loop at launch. Never raises."""
    _known(memory_path)


def hold_back(messages, memory_path):
    """``messages`` as an engine may read them. The same list when nothing changed; the caller's list is never touched,
    so a retry starts from what it built. System text is the caller's own: only a value on record is looked for there."""
    if not isinstance(messages, list):
        return messages
    try:
        marks, left = _known(memory_path)
        out = []
        changed = False
        for message in messages:
            content = message.get("content") if isinstance(message, dict) else None
            by_itself = isinstance(message, dict) and message.get("role") != "system"
            new = content
            if isinstance(content, str):
                new = _view(content, marks, left, by_itself=by_itself)
            elif isinstance(content, list):
                new = [{**part, "text": _view(part["text"], marks, left, by_itself=by_itself)}
                       if isinstance(part, dict) and isinstance(part.get("text"), str) else part for part in content]
            if new != content:
                changed = True
                message = {**message, "content": new}
            out.append(message)
        return out if changed else messages
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Sensitive hold skipped a prompt: {type(exc).__name__}")
        return messages


def hold_texts(texts, memory_path):
    """Passages on their way to a hosted embedding model. Values on record only: a passage is not read by itself, so what
    an index finds does not change with how a line happens to read."""
    try:
        marks, _left = _known(memory_path)
        return [sensitive_text.take_out(t, marks)[0] for t in texts] if marks else texts
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Sensitive hold skipped a batch: {type(exc).__name__}")
        return texts
