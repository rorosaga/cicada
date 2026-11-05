"""Telling the person what may be sensitive and which engine read it, and taking it back out (G235, owner 2026-11-04).

`sensitive_text` finds; this module acts on what it finds. Engine-free throughout: no model reads text to decide whether a
model may read it. **Nothing here stores, logs, commits or returns a value**, nor a hash of one (a hash of a short
password is the password, to anyone with a wordlist): an episode's record holds kinds, counts, engine labels and dates, and
every value is re-derived in memory from the body when needed.

**Before an engine reads** (`sensitive_hold`, inside ``providers.resolve_llm_fn``: every model call Cicada starts). **Ruling
60 (owner 2026-11-04):** an engine reads a typed mark wherever a confident hit's value stands (``Hit.sure``); an unsure
one it reads, and the person is told. :class:`Guard`, at Stage 1's send point, records the read on the episode
(:func:`note_read`, Sleep only) and masks the same value on the conversation's other lines by offset, so the stored body
and every span stay as they are. Either way the value is taken back out of whatever the model answered, and an item built
only on it is dropped, so a page never repeats it (:meth:`Guard.clean`, and :func:`sweep_written` before the commit).

**The review** (:func:`sync_review`, the tail). One inbox item, one row per conversation: which conversation, what kind,
which engine read it. Never one question per hit. A row is checked against the body as it is now, so an edit that removed
the text removes the row. Conversations read before this existed are found once, by :func:`sweep_read`: a report only, which
writes nothing on an episode.

**Remove** (:func:`remove_rows`, the person's act alone). In this order, so a failure at any point leaves the value
findable and the row standing: **the older version is committed first** (a conversation still waiting has no other copy;
no commit, no removal); then the value leaves every file that repeated it, by what the file is (`sensitive_purge`), and
every other conversation holding the same distinctive value; **the conversation's own body goes last**. A word that is not
distinctive stays where it was called a secret, and on a tied file's line that speaks of one. The body goes through the
revision path (``revised`` record, ``processed: false``); the next Sleep reads it as a revision with no engine call and
closes what only those words said (`episode_revision`). The source may send the words again: :func:`reapply_draft` and
:func:`reapply_conversation` take them out on the way in, and :func:`reapply_waiting` catches any other writer before a
read. **Git history keeps the older version; history is never rewritten.** What an engine already read cannot be unread.

**Leave it** records how many of each kind the person saw (``kept``), so only a new one asks again."""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import (authorship, bank_index, episode_ids, episode_scrub, evidence, markdown_parser, sensitive_purge,
                          sensitive_text)
from api.services.sensitive_text import HELD_MARK, REMOVED_MARK, Hit

#: The episode frontmatter key: ``{read: [{engine, at, kinds, held?}], kept: {kind: n}, removed: {kinds, at, pending?}}``.
KEY = "sensitive"
KIND = "sensitive"
REMOVE, KEEP = "remove", "keep"
#: What a value becomes in what a model answered. An item that rests on nothing else is dropped.
STRIPPED = "[removed]"
TRIGGER_REVIEW = "sleep/sensitive-review"
TRIGGER_REMOVED = "inbox/sensitive/removed"
TRIGGER_KEPT = "inbox/sensitive/kept"
TRIGGER_OLDER = "inbox/sensitive/older-version"
#: Bump when the detector changes what it finds, so the already-read conversations are looked through once more.
DETECTOR_VERSION = 1
#: Who read it, in the person's terms. A name only ever says the person's own current or past choice.
_LOCAL_ENGINE = "ollama"


def _record(fm: dict | None) -> dict:
    record = (fm or {}).get(KEY)
    return record if isinstance(record, dict) else {}


def _session(fm: dict) -> bool:
    return bool(fm.get("harness") or fm.get("capture_kind") == "transcript")


def hits_of(fm: dict, body: str) -> list[Hit]:
    """What is likely sensitive in a stored episode, read the way its own record says."""
    return sensitive_text.find(body, harness=_session(fm), override=authorship.of(fm), gaps=evidence.gap_ranges(fm, body))


def _keep_turns_last(fm: dict) -> None:
    from api.services import episode_staging

    episode_staging.keep_turns_last(fm)


# ---- before the engine reads ----------------------------------------------------------------------------------------


def not_left(fm: dict, hits: list[Hit]) -> list[Hit]:
    """``hits`` without the kinds the person already looked at and left."""
    kept = _record(fm).get("kept")
    if not isinstance(kept, dict) or not hits:
        return hits
    counts = Counter(h.kind for h in hits)
    return [h for h in hits if counts[h.kind] > int(kept.get(h.kind) or 0)]


def _still_flagged(episode: dict) -> list[Hit]:
    """A Sleep episode's hits, without what the person left: a wrong alarm costs its word on the pages only until they
    say so (`Leave it`)."""
    return not_left(episode, sensitive_text.find_in_episode(episode))


@dataclass
class Guard:
    """One episode at the send point. Holds the values in memory for as long as this read takes. ``hits`` are the ones in
    the windows being sent, as reported; ``held`` everywhere a confident value of this conversation stands, by offset, so
    the prompt is masked before the chokepoint even looks; ``values`` every value of the conversation, read or held."""
    hits: tuple[Hit, ...] = ()
    values: tuple[str, ...] = ()
    held_at: tuple[Hit, ...] = ()

    @classmethod
    def of(cls, episode: dict, spans) -> "Guard":
        """A failure here is no hit: it logs its class and costs the report. The chokepoint still stands."""
        try:
            content = str(episode.get("content") or "")
            flagged = _still_flagged(episode)
            hits = tuple(h for h in flagged if any(h.start < hi and h.end > lo for lo, hi in spans))
            return cls(hits, sensitive_text.values_of(content, flagged),
                       tuple(h for h in sensitive_text.with_echoes(content, flagged) if h.sure))
        except Exception as exc:  # noqa: BLE001 - the detector never fails a read
            logger.warning(f"Sensitive check skipped: {type(exc).__name__}")
            return cls()

    def chunk(self, masked: str, lo: int, hi: int) -> str:
        """``masked[lo:hi]`` as the engine reads it."""
        return sensitive_text.held_text(masked, lo, hi, self.held_at) if self.held_at else masked[lo:hi]

    def kinds(self) -> dict[str, int]:
        return dict(Counter(h.kind for h in self.hits))

    def held(self) -> dict[str, int]:
        return dict(Counter(h.kind for h in self.hits if h.sure))

    def clean(self, entities: list, relationships: list, values: list) -> tuple[list, list, list]:
        """A model's answer without the values. A name, an end of a link or a value that WAS one is dropped: a page
        named after a password, or a claim whose object is only a mark, holds nothing worth keeping."""
        if not self.values:
            return entities, relationships, values

        def scrubbed(items: list, *fields: str) -> list:
            out = []
            for item in items:
                clean, _n = sensitive_text.strip_in(item, self.values, STRIPPED)
                if isinstance(clean, dict) and any(_marked(clean.get(f)) for f in fields):
                    continue
                out.append(clean)
            return out

        return (scrubbed(entities, "name"), scrubbed(relationships, "source", "target"),
                scrubbed(values, "entity", "value"))


def _marked(text) -> bool:
    return isinstance(text, str) and (STRIPPED in text or "[held back:" in text)


def note_read(episode: dict, kinds: dict[str, int], engine: str | None, *, held: dict[str, int] | None = None) -> None:
    """Record on the episode what this engine is about to be handed: ``kinds``, of which ``held`` are held back.
    Frontmatter only, so the body, its hash and its queue state stay as they are. ``engine`` omitted rather than guessed
    (the ``Cicada-Engine`` rule). Never raises."""
    path = Path(str(episode.get("filepath") or ""))
    try:
        with episode_ids.episode_lock(path.parent):
            parsed = markdown_parser.parse(path)
            fm = dict(parsed.frontmatter)
            record = dict(_record(fm))
            reads = [r for r in record.get("read") or [] if isinstance(r, dict) and r.get("engine") != engine]
            row: dict = {"at": episode_ids.utc_now_iso(), "kinds": dict(kinds)}
            if engine:
                row["engine"] = engine
            if held:
                row["held"] = dict(held)
            record["read"] = [*reads, row]
            fm[KEY] = record
            _keep_turns_last(fm)
            markdown_parser.write(path, fm, parsed.body)
        bank_index.invalidate(path.parent.parent)
    except Exception as exc:  # noqa: BLE001 - the record never fails a read
        logger.warning(f"Sensitive record skipped: {type(exc).__name__}")


def title_for_others(title: str) -> str:
    """A conversation's stored title on its way to an agent (the primer, a continuation). A capture's title is its first
    line, so it can be the line that holds the value. Whatever the switch: this is a list, not a read the person chose."""
    if not title:
        return title
    return sensitive_text.replace_hits(title, sensitive_text.find(title), HELD_MARK)


def sweep_written(memory_path: Path, episodes: list[dict], dirty) -> int:
    """Before the batch's commit, one engine-free pass over what it wrote: any value of the batch's conversations left
    in a page by any stage comes out. Stage 1's answer is cleaned already; this holds for every later writer. Returns
    how many files changed. Never raises."""
    try:
        values: list[str] = []
        for ep in episodes:
            content = str(ep.get("content") or "")
            values.extend(sensitive_text.values_of(content, _still_flagged(ep)))
        if not values:
            return 0
        marks = {v: STRIPPED for v in values}
        tied = tuple(str(ep.get("id") or "") for ep in episodes if ep.get("id"))
        changed = 0
        for rel in dirty:
            if sensitive_purge.in_scope(rel) and sensitive_purge.clean_file(Path(memory_path) / rel, marks, tied_ids=tied):
                changed += 1
        if changed:
            bank_index.invalidate(memory_path)
        return changed
    except Exception as exc:  # noqa: BLE001 - a guard on the way to a commit, never the reason it fails
        logger.warning(f"Sensitive sweep skipped: {type(exc).__name__}")
        return 0


# ---- the source sends the words again -------------------------------------------------------------------------------


def removed_kinds(fm: dict | None) -> frozenset[str]:
    removed = _record(fm).get("removed")
    kinds = removed.get("kinds") if isinstance(removed, dict) else None
    return frozenset(str(k) for k in kinds or [])


def removal_pending(fm: dict | None) -> bool:
    removed = _record(fm).get("removed")
    return isinstance(removed, dict) and bool(removed.get("pending"))


def _hits_of_kinds(text: str, kinds: frozenset[str], *, harness: bool, override: str | None) -> list[Hit]:
    return [h for h in sensitive_text.find(text, harness=harness, override=override) if h.kind in kinds]


def _echo_marks(pieces, kinds: frozenset[str], *, harness: bool, override: str | None) -> dict[str, str]:
    """The distinctive values a source's text states, across all of it: an echo on another turn goes with them."""
    marks: dict[str, str] = {}
    for prefix, text in pieces:
        whole = prefix + text
        for h in _hits_of_kinds(whole, kinds, harness=harness, override=override):
            value = whole[h.start:h.end]
            if sensitive_text.distinctive(value):
                marks[value] = REMOVED_MARK.format(kind=h.kind)
    return marks


def _out(text: str, kinds: frozenset[str], echoes: dict[str, str], *, harness: bool, override: str | None,
         prefix: str = "") -> str:
    """``text`` without the hits of ``kinds``, read as a line under ``prefix`` (a turn's marker), nor ``echoes``."""
    whole = prefix + text
    hits = _hits_of_kinds(whole, kinds, harness=harness, override=override)
    out = sensitive_text.replace_hits(whole, hits, REMOVED_MARK) if hits else whole
    return sensitive_text.take_out(out, echoes)[0][len(prefix):]


def reapply_draft(draft, fm: dict):
    """A source-keyed writer's draft for an episode the person removed text from: the same text taken out before it is
    rendered and hashed, so an unchanged source hashes as unchanged and a changed one never brings the words back."""
    kinds = removed_kinds(fm)
    if not kinds:
        return draft
    ctx = {"harness": _session(fm), "override": authorship.of(fm)}
    pieces = [(f"{t.speaker}: ", t.text) for t in draft.turns]
    if getattr(draft, "body", None) is not None:
        pieces.append(("", draft.body))
    echoes = _echo_marks(pieces, kinds, **ctx)
    changes: dict = {}
    if getattr(draft, "body", None) is not None:
        changes["body"] = _out(draft.body, kinds, echoes, **ctx)
    if getattr(draft, "title", None):
        changes["title"] = _out(draft.title, kinds, echoes, **ctx)
    return replace(draft, turns=[replace(t, text=_out(t.text, kinds, echoes, prefix=f"{t.speaker}: ", **ctx))
                                 for t in draft.turns], **changes)


def reapply_conversation(conv, fm: dict) -> None:
    """The Stop hook's writer rebuilds a session's body from its transcript on every turn: the same removal on each
    turn's text, in place, before the body, its hash and its sidecar are built from them."""
    kinds = removed_kinds(fm)
    if not kinds:
        return
    ctx = {"harness": True, "override": authorship.of(fm)}
    echoes = _echo_marks([(f"{t.role}: ", t.text) for t in conv.turns], kinds, **ctx)
    for turn in conv.turns:
        turn.text = _out(turn.text, kinds, echoes, prefix=f"{turn.role}: ", **ctx)


_OFFSET_KEYS = frozenset({"offset", "reply_to", "tail_at"})     # `tail_at`: ruling 58, where a chat's later turns start


def _shift_offsets(value, shift):
    """Every body offset in a frontmatter value moved by ``shift``: the sidecars index the body (`evidence.turn_stamps`), and
    a reply points at the offset of the turn it answers (`turn_extras`; a dict there is a reference to another sitting)."""
    if isinstance(value, dict):
        return {k: (shift(v) if k in _OFFSET_KEYS and isinstance(v, int) and not isinstance(v, bool)
                    else _shift_offsets(v, shift)) for k, v in value.items()}
    if isinstance(value, list):
        return [_shift_offsets(v, shift) for v in value]
    return value


def _mapper(hits: list[Hit], mark: str):
    """Where an offset of the old body lands in the new one. Inside a hit: the hit's start."""
    ordered = sorted(hits, key=lambda h: h.start)

    def shift(at: int) -> int:
        delta = 0
        for hit in ordered:
            if at <= hit.start:
                break
            if at < hit.end:
                return hit.start + delta
            delta += len(mark.format(kind=hit.kind)) - (hit.end - hit.start)
        return at + delta

    return shift


_SAID_FIELDS = frozenset({"title", "description", "summary"})


def _strip_fm_strings(value, marks: dict[str, str], *, key=None):
    """A value out of the strings a writer keeps beside the body (a title, a description). Keys and ids stay. A word that
    was called a secret once stays in a title that does not speak of one."""
    if isinstance(value, str):
        if episode_scrub._is_key_field(key):
            return value
        value, _n = sensitive_text.take_out(value, marks)
        if str(key or "") in _SAID_FIELDS:
            # A title is cut to a length, so it can hold a value cut in two that no exact match finds.
            value = sensitive_text.replace_hits(value, sensitive_text.find(value), REMOVED_MARK)
        return value
    if isinstance(value, dict):
        return {k: _strip_fm_strings(v, marks, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_fm_strings(v, marks, key=key) for v in value]
    return value


def _take_out(fm: dict, body: str, hits: list[Hit], kinds, *, at: str, pending: bool) -> tuple[dict, str, dict]:
    """``(frontmatter, body, value -> mark)`` with the hits out: the mark in the body, the offsets moved, the strings
    beside the body cleaned, and a ``revised`` record so Sleep reads it as a revision of itself. Writes nothing."""
    from api.services import episode_staging

    hits = sensitive_text.with_echoes(body, hits)
    marks = {body[h.start:h.end]: REMOVED_MARK.format(kind=h.kind) for h in hits}
    new_body = sensitive_text.replace_hits(body, hits, REMOVED_MARK)
    shift = _mapper(hits, REMOVED_MARK)
    out = {k: (v if k == KEY else _strip_fm_strings(_shift_offsets(v, shift), marks, key=k)) for k, v in fm.items()}
    out[episode_staging.REVISED_KEY] = episode_staging.revision_record(fm, at=at)
    out["content_hash"] = episode_staging.content_hash(new_body)
    if episode_staging.has_relayed_tail(out):       # ruling 58: the same export, taken out the same way, stays a skip
        out["relay"] = {**out["relay"], "imported_hash": episode_staging.content_hash(new_body[:out["relay"]["tail_at"] - 1])}
    out["processed"] = False
    out.pop("processed_by", None)
    record = dict(_record(fm))
    kept = {k: v for k, v in (record.get("kept") or {}).items() if k not in set(kinds)}
    if kept:
        record["kept"] = kept
    else:
        record.pop("kept", None)
    old = record.get("removed") if isinstance(record.get("removed"), dict) else {}
    record["removed"] = {"kinds": sorted(set(kinds) | set(old.get("kinds") or []), key=sensitive_text.KINDS.index),
                         "at": at, **({"pending": True} if pending else {})}
    out[KEY] = record
    _keep_turns_last(out)
    return out, new_body, marks


def reapply_waiting(episodes: list[dict]) -> int:
    """Just before a batch reads: an episode the person removed text from that some other writer rewrote with the words
    in it has them taken out again, before any engine sees them and before the revision is worked out. Returns how many.
    Never raises."""
    from api.services import episode_staging

    done = 0
    for ep in episodes:
        try:
            record = ep.get(KEY)
            if not isinstance(record, dict) or not record.get("removed"):
                continue
            path = Path(str(ep.get("filepath") or ""))
            with episode_ids.episode_lock(path.parent):
                parsed = markdown_parser.parse(path)
                fm = dict(parsed.frontmatter)
                kinds = removed_kinds(fm)
                hits = [h for h in hits_of(fm, parsed.body) if h.kind in kinds]
                if not hits:
                    continue
                new_fm, new_body, _marks = _take_out(fm, parsed.body, hits, kinds, at=episode_ids.utc_now_iso(),
                                                     pending=removal_pending(fm))
                markdown_parser.write(path, new_fm, new_body)
            ep["content"] = new_body
            ep["revision"] = episode_ids.body_revision(new_body)
            ep["gaps"] = evidence.gap_ranges(new_fm, new_body)
            ep[KEY] = new_fm[KEY]
            if isinstance(new_fm.get(episode_staging.REVISED_KEY), dict):
                ep[episode_staging.REVISED_KEY] = new_fm[episode_staging.REVISED_KEY]
            done += 1
        except Exception as exc:  # noqa: BLE001 - never a reason a batch fails; the mark below still holds the read back
            logger.warning(f"Sensitive removal could not be applied again: {type(exc).__name__}")
    if done:
        bank_index.invalidate(Path(str(episodes[0].get("filepath"))).parent.parent)
    return done


def _context_of_episode(episode: dict) -> dict:
    return {"harness": bool(episode.get("harness") or episode.get("capture_kind") == "transcript"),
            "override": episode.get(authorship.KEY)}


_REMOVED_RE = re.compile(r"\[removed: (?:" + "|".join(sensitive_text.KINDS) + r")\]")
#: Longer than any value the detector reports (a PEM block is the longest).
_MAX_REMOVED_CHARS = 8192


def same_after_removal(prior: str, body: str, episode: dict | None = None) -> bool:
    """Is the removal all that changed? Every stretch of the body between two marks stands, in order, in the earlier body,
    and only a value's length lies between them. Asked of the texts, not the detector: a conversation that only repeated
    a value elsewhere flagged has no hit of its own to compare."""
    pieces = _REMOVED_RE.split(body)
    if len(pieces) < 2 or not prior.startswith(pieces[0]) or not prior.endswith(pieces[-1]):
        return False
    at = len(pieces[0])
    for piece in pieces[1:-1]:
        found = prior.find(piece, at)
        if found < 0 or found - at > _MAX_REMOVED_CHARS:
            return False
        at = found + len(piece)
    return 0 <= len(prior) - len(pieces[-1]) - at <= _MAX_REMOVED_CHARS


def masked_against(before: str, after: str) -> str:
    """What a passage used to say, with whatever the passage it became marks as removed replaced by that mark. After a
    removal nothing else knows the value, and this needs only the two texts."""
    if not _REMOVED_RE.search(after):
        return before
    pattern = re.compile(r"\[removed: \w+\]|\S+|\s+")
    old, new = pattern.findall(before), pattern.findall(after)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        marks = [t for t in new[j1:j2] if _REMOVED_RE.fullmatch(t)] if tag != "equal" else []
        out.extend(marks or old[i1:i2])
    return "".join(out)


def masked_for_engine(text: str) -> str:
    """A passage of a conversation as it may reach a prompt on a revision. After a removal the chokepoint no longer knows
    the value, so what a body used to say is masked here, whichever mode is on."""
    return sensitive_text.replace_hits(text, sensitive_text.with_echoes(text, sensitive_text.find(text)),
                                       REMOVED_MARK) if text else text


def mark_read(fm: dict) -> None:
    """Sleep has read the revision a removal made: nothing further to close on this removal."""
    record = _record(fm)
    if isinstance(record.get("removed"), dict) and record["removed"].get("pending"):
        fm[KEY] = {**record, "removed": {k: v for k, v in record["removed"].items() if k != "pending"}}


# ---- the review -----------------------------------------------------------------------------------------------------


def row_id(episode_id: str) -> str:
    """Stable per conversation; derived from the id alone."""
    return "s" + hashlib.sha256(str(episode_id).encode("utf-8")).hexdigest()[:10]


def engine_name(label: str | None) -> str | None:
    """An engine label in the person's words, or ``None``. This row is the one place naming it is the point."""
    from api.services import engine_select

    if not label:
        return None
    if label == _LOCAL_ENGINE:
        return "this Mac"
    if label == "litellm":
        return "your API key"
    return engine_select.PLAN_NAMES.get(label) or None


#: Where a value was, in a row's title. The row already says what kind.
_TITLE_DOTS = "•••"


def safe_title(fm: dict, body: str, hits: list[Hit]) -> str:
    """The conversation's title without the value, so two rows can still be told apart. A capture's title is its first
    line, so it can hold the value whole, or cut in two by the title's length limit. Nothing left: a plain stand-in."""
    title = str(fm.get("title") or "").strip()
    title, _n = sensitive_text.strip_values(title, sensitive_text.values_of(body, hits), _TITLE_DOTS)
    title = sensitive_text.replace_hits(title, sensitive_text.find(title), _TITLE_DOTS)
    bare = title.rstrip("…. ")
    for value in sensitive_text.values_of(body, hits):
        for n in range(len(value) - 1, 0, -1):    # the last characters kept before the cut are the value's first
            if bare.endswith(value[:n]) and not bare[-n - 1:-n].isalnum():
                title = bare[:-n] + _TITLE_DOTS
                break
    return title if title.replace(_TITLE_DOTS, "").strip() else "A conversation"


def _row(fm: dict, body: str, stem: str) -> dict | None:
    """The conversation's row as of now, or ``None`` when nothing it holds is still waiting for the person."""
    record = _record(fm)
    hits = hits_of(fm, body)
    if not hits:
        return None
    kept = record.get("kept") if isinstance(record.get("kept"), dict) else {}
    counts = Counter(h.kind for h in hits)
    kinds = [k for k in sensitive_text.KINDS if counts[k] > int(kept.get(k) or 0)]
    if not kinds:
        return None
    reads = [r for r in record.get("read") or [] if isinstance(r, dict)]
    def _held(r: dict) -> dict:
        return r["held"] if isinstance(r.get("held"), dict) else {}
    def _named(rows) -> list[str]:
        return list(dict.fromkeys(n for n in (engine_name(r.get("engine")) for r in rows) if n))
    # What each engine was really handed: a kind counted beyond what was held back from it, it read.
    held_kinds = [k for k in kinds if reads and all(int(_held(r).get(k) or 0) >= int((r.get("kinds") or {}).get(k) or 0)
                                                    for r in reads)]
    read_rows = [r for r in reads if any(int((r.get("kinds") or {}).get(k) or 0) > int(_held(r).get(k) or 0) for k in kinds)]
    episode = str(fm.get("id") or stem)
    row: dict = {"id": row_id(episode), "episode": episode, "title": safe_title(fm, body, hits),
                 "day": str(fm.get("timestamp") or "")[:10], "kinds": kinds}
    if read_rows and _named(read_rows):
        row["read_by"] = _named(read_rows)
    if held_kinds:
        row["held_kinds"] = held_kinds
        if _named(reads):
            row["held_from"] = _named(reads)
    if not reads and str(fm.get("processed_by") or "") == "sleep":
        row["earlier"] = True    # read before this check existed: which engine is not guessed
    return row


def _sweep_path(memory_path: Path) -> Path:
    from api.services import reading_asks
    from api.services.runtime_layout import cicada_home

    return cicada_home() / "sensitive_sweep" / f"{reading_asks.bank_slug(memory_path)}.json"


def _load_sweep(memory_path: Path) -> dict:
    try:
        data = json.loads(_sweep_path(memory_path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def sweep_read(memory_path: Path) -> dict:
    """Once per bank and detector version: the conversations already read that hold a hit, and how many hold something
    already replaced. **A report only: no episode is written.** Ids and counts, kept outside every bank. A demo bank is
    made up; nothing to report."""
    from api.services import demo_guard

    memory_path = Path(memory_path)
    done = _load_sweep(memory_path)
    if done.get("version") == DETECTOR_VERSION or demo_guard.is_demo(memory_path):
        return done
    found: list[str] = []
    replaced = 0
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        if fm.get("processed") is not True:
            continue
        try:
            body = f.body() or ""
            replaced += int(episode_scrub.REDACTED in body)
            if hits_of(fm, body):
                found.append(str(fm.get("id") or f.stem))
        except Exception as exc:  # noqa: BLE001 - one unreadable conversation is no row
            logger.debug(f"sensitive sweep skipped one: {type(exc).__name__}")
    out = {"version": DETECTOR_VERSION, "episodes": found, "replaced": replaced}
    path = _sweep_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out), encoding="utf-8")
    os.replace(tmp, path)
    logger.info(f"Sensitive sweep: {len(found)} conversation(s) read earlier hold a likely value")   # a count only
    return out


def _review_words(rows: list[dict]) -> tuple[str, list[dict]]:
    n = len(rows)
    kinds = {k for r in rows for k in r["kinds"]}
    if n == 1 and len(kinds) == 1:
        title = f"1 conversation may hold {KIND_WORDS[next(iter(kinds))]}"
    else:
        title = f"{n} conversation{'' if n == 1 else 's'} may hold something sensitive"
    return title, [{"key": REMOVE, "label": "Remove"}, {"key": KEEP, "label": "Leave it"}]


KIND_WORDS = {sensitive_text.PASSWORD: "a password", sensitive_text.KEY: "a key", sensitive_text.CARD: "a card number",
              sensitive_text.BANK: "a bank account", sensitive_text.ID: "an ID number"}


def _body(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        said = ", ".join(KIND_WORDS[k] for k in r["kinds"])
        who = r.get("read_by") or r.get("held_from")   # engine names only; never a word of the conversation
        lines.append(f"- {r['title']} ({r['day']}): {said}" + (f", {', '.join(who)}" if who else ""))
    return "\n".join(lines) + "\n"


def _write_item(path: Path, item: dict, rows: list[dict], replaced: int | None) -> None:
    title, options = _review_words(rows)
    item.update({"title": title, "question": title, "options": options, "rows": rows})
    if replaced:
        item["replaced"] = int(replaced)
    else:
        item.pop("replaced", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    markdown_parser.write(path, item, _body(rows))


def _item(memory_path: Path) -> tuple[Path, dict] | None:
    for f in bank_index.files(memory_path, "inbox"):
        if str((f.frontmatter or {}).get("kind") or "") == KIND:
            return f.path, dict(f.frontmatter)
    return None


@dataclass
class Report:
    paths: list[str] = field(default_factory=list)
    rows: int = 0


def sync_review(memory_path: Path, skip=frozenset(), *, today: str | None = None) -> Report:
    """Keep the ONE review in step: a row for every conversation an engine read, or the sweep found, that still holds
    something the person has not answered. An item with nothing left is removed; one dirty before the run is left."""
    from api.services import inbox_service

    memory_path = Path(memory_path)
    report = Report()
    sweep = _load_sweep(memory_path)
    earlier = {str(e) for e in sweep.get("episodes") or []}
    rows: list[dict] = []
    for f in bank_index.files(memory_path, "episodes"):
        fm = f.frontmatter or {}
        stem_id = str(fm.get("id") or f.stem)
        if not (_record(fm).get("read") or stem_id in earlier):
            continue
        try:
            row = _row(fm, f.body() or "", f.stem)
        except Exception as exc:  # noqa: BLE001 - one unreadable conversation is no row
            logger.debug(f"sensitive row skipped: {type(exc).__name__}")
            continue
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda r: r["day"], reverse=True)
    current = _item(memory_path)
    if current is not None and current[0].relative_to(memory_path).as_posix() in skip:
        return report
    replaced = sweep.get("replaced")
    if current is None:
        if not rows:
            return report
        inbox = memory_path / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f"inbox-{inbox_service.next_inbox_num(inbox):03d}.md"
        item = {"kind": KIND, "required_input": "choice", "status": "pending", "priority": 0.5, "allow_other": False,
                "allow_defer": False, "created_date": today or str(date.today())}
        _write_item(path, item, rows, replaced)
        report.paths.append(path.relative_to(memory_path).as_posix())
    else:
        path, item = current
        rel = path.relative_to(memory_path).as_posix()
        if not rows:
            path.unlink(missing_ok=True)
            report.paths.append(rel)
        elif item.get("rows") != rows or item.get("replaced") != (int(replaced) if replaced else None):
            _write_item(path, item, rows, replaced)
            report.paths.append(rel)
    report.rows = len(rows)
    if report.paths:
        bank_index.invalidate(memory_path)
    return report


def commit_message(report: Report, day: date) -> str:
    from api.services import git_service

    return git_service.build_commit_message(
        f"Sensitive review {day.isoformat()}",
        [f"{rel}: updated (trigger: {TRIGGER_REVIEW})" for rel in report.paths], authors=["cicada"])


# ---- answering it: the person alone ---------------------------------------------------------------------------------


def _episode_path(memory_path: Path, episode_id: str) -> Path | None:
    path = evidence.source_path(Path(memory_path), episode_id)
    return path if path is not None and Path(path).is_file() else None


class RemovalRefused(RuntimeError):
    """A removal that did not start, in a sentence for the person. Nothing was changed."""


def _ids_to_kinds(body: str, hits: list[Hit]) -> dict[str, str]:
    return {body[h.start:h.end]: h.kind for h in sensitive_text.with_echoes(body, hits)}


def _spoken(f) -> str:
    """Everything a conversation's file says of itself: its words, and the strings a writer keeps beside them."""
    return f"{f.body() or ''}\n{json.dumps(f.frontmatter or {}, ensure_ascii=False, default=str)}"


def _conversations_holding(memory_path: Path, values, skip: Path) -> dict[str, list[Path]]:
    """Each value -> the other conversations holding it as an exact token, in their words or beside them. A substring test
    first, since this reads a whole bank."""
    out: dict[str, list[Path]] = {v: [] for v in values}
    if not out:
        return out
    for f in bank_index.files(memory_path, "episodes"):
        if f.path == skip:
            continue
        try:
            spoken = _spoken(f)
        except Exception as exc:  # noqa: BLE001 - one unreadable conversation is no echo
            logger.debug(f"sensitive echo skipped one: {type(exc).__name__}")
            continue
        for value, paths in out.items():
            if value in spoken and sensitive_text.holds(spoken, value):
                paths.append(f.path)
    return out


def _files_holding(memory_path: Path, values) -> Counter:
    """Each value -> how many files other than conversations hold it as an exact token."""
    found: Counter = Counter()
    if not values:
        return found
    for path in sensitive_purge.bank_files(memory_path):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found.update(v for v in values if v in text and sensitive_text.holds(text, v))
    return found


@dataclass
class Reach:
    """Where Remove takes one conversation's values, decided once before anything is written. ``kinds``: value -> its kind,
    a value that stays near home :class:`~sensitive_text.Guarded`. ``echoes``: the other conversations a value leaves."""
    path: Path
    kinds: dict[str, str]
    echoes: list[Path]

    @property
    def marks(self) -> dict[str, str]:
        return {v: REMOVED_MARK.format(kind=k) for v, k in self.kinds.items()}


#: A value on more pages than this has been written up as a thing, whatever one line called it. A password that reached a
#: page from each of a few conversations stays under it.
_RARE_FILES = 6


def _reach(memory_path: Path, episode_id: str) -> Reach | None:
    """**A wrong alarm never rewrites something unrelated.** A value leaves its own conversation and what cites it only when
    it is confident, distinctive and rare in this bank: any other is guarded, and stays out of every other conversation and
    every file not tied to this one. One that is common is left there and said in the count, not hunted."""
    path = _episode_path(memory_path, episode_id)
    if path is None:
        return None
    parsed = markdown_parser.parse(path)
    hits = hits_of(dict(parsed.frontmatter), parsed.body)
    kinds_of = _ids_to_kinds(parsed.body, hits)
    confident = {parsed.body[h.start:h.end] for h in hits if h.sure}
    candidates = [v for v in kinds_of if v in confident and sensitive_text.distinctive(v)]
    holding = _conversations_holding(memory_path, candidates, path)
    pages = _files_holding(memory_path, candidates)
    free = {v for v, paths in holding.items()
            if len(paths) <= sensitive_text.RARE_CONVERSATIONS and pages[v] <= _RARE_FILES}
    kinds = {(v if v in free or not sensitive_text.distinctive(v) else sensitive_text.Guarded(v)): k
             for v, k in kinds_of.items()}
    return Reach(path, kinds, list(dict.fromkeys(p for v in free for p in holding[v])))


def _take_out_echoes(path: Path, kinds_of: dict[str, str], at: str) -> bool:
    """Another conversation that repeated a value. It keeps its words around it. In its words, it reads as a revision too;
    only beside them (a description), the file changes and Sleep has nothing new to read."""
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        marks = {v: REMOVED_MARK.format(kind=k) for v, k in kinds_of.items()}
        hits = [h for value, kind in kinds_of.items() for h in sensitive_text.occurrences(parsed.body, value, kind)]
        new_fm, new_body = fm, parsed.body
        if hits:
            new_fm, new_body, _marks = _take_out(fm, parsed.body, hits, {h.kind for h in hits}, at=at, pending=True)
        new_fm = {k: (v if k == KEY else _strip_fm_strings(v, marks, key=k)) for k, v in new_fm.items()}
        if new_fm == fm and new_body == parsed.body:
            return False
        markdown_parser.write(path, new_fm, new_body)
    return True


def remove_episode(memory_path: Path, episode_id: str, touched: list[str] | None = None,
                   reach: Reach | None = None) -> tuple[list[str], dict[str, str]]:
    """Take what is flagged out of one conversation and out of what :func:`_reach` allows. ``(bank-relative paths written,
    value -> mark)``. The caller holds admission and the page lock, committed the older version and commits this; the values
    leave with its frame. **The body goes last:** when a write raises, the value is still findable in it, the row still
    stands, and what was already written (in ``touched``, when given) is whole, since each file is replaced atomically and
    doing it again changes nothing."""
    memory_path = Path(memory_path)
    written = touched if touched is not None else []
    reach = reach or _reach(memory_path, episode_id)
    if reach is None or not reach.kinds:
        return written, {}
    path, marks = reach.path, reach.marks
    at = episode_ids.utc_now_iso()
    tied = (episode_id,)
    for target in sensitive_purge.bank_files(memory_path):
        if sensitive_purge.clean_file(target, marks, tied_ids=tied):
            written.append(target.relative_to(memory_path).as_posix())
    travelling = {v: k for v, k in reach.kinds.items() if sensitive_text.distinctive(v)}
    for echo in reach.echoes:
        if _take_out_echoes(echo, travelling, at):
            written.append(echo.relative_to(memory_path).as_posix())
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        hits = hits_of(fm, parsed.body)
        if hits:
            new_fm, new_body, now = _take_out(fm, parsed.body, hits, {h.kind for h in hits}, at=at, pending=True)
            marks.update(now)
            markdown_parser.write(path, new_fm, new_body)
            written.append(path.relative_to(memory_path).as_posix())
    (memory_path / ".awake" / f"{episode_id}.json").unlink(missing_ok=True)
    for echo in reach.echoes:
        (memory_path / ".awake" / f"{echo.stem}.json").unlink(missing_ok=True)
    return written, marks


def _keep_older_versions(memory_path: Path, reaches: list[Reach]) -> None:
    """Commit what these conversations, and those holding the same value, say now, before a word changes: one still waiting
    for Sleep was never committed, so git would otherwise hold no copy at all. The owner's ruling: git is local, history
    keeps it. Verified against ``HEAD``; anything less refuses, and nothing has been written."""
    from api.services import git_service

    if not (memory_path / ".git").exists():
        raise RemovalRefused("This memory has no history to keep the older version in.")
    rels = list(dict.fromkeys(p.relative_to(memory_path).as_posix() for r in reaches for p in (r.path, *r.echoes)))
    if not rels:
        return
    day = date.today().isoformat()
    try:
        git_service.commit_touched_sync(
            memory_path, git_service.build_commit_message(f"Older version kept before a removal {day}",
                                                          [f"{rel}: updated (trigger: {TRIGGER_OLDER})" for rel in rels],
                                                          authors=[]), rels)
        for rel in rels:
            if (git_service._git_sync(memory_path, "rev-parse", f"HEAD:{rel}").strip()
                    != git_service._git_sync(memory_path, "hash-object", "--", rel).strip()):
                raise RemovalRefused("The older version could not be kept, so nothing was removed.")
    except git_service.GitError as exc:
        logger.warning(f"Older version not kept: {type(exc).__name__}")
        raise RemovalRefused("The older version could not be kept, so nothing was removed.") from exc


@dataclass
class Removed:
    """What :func:`remove_rows` did. ``done`` and ``failed`` are conversation ids; ``still_found`` a count of files."""
    done: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)
    marks: dict[str, str] = field(default_factory=dict)


def remove_rows(memory_path: Path, episode_ids_: list[str]) -> Removed:
    """Every step up to the commit, under the caller's page lock. One conversation failing stops only that one. Each row's
    reach is decided before any of them is written: taking one row out must not make another's value look rare."""
    out = Removed()
    reaches = {episode_id: _reach(memory_path, episode_id) for episode_id in episode_ids_}
    _keep_older_versions(memory_path, [r for r in reaches.values() if r is not None])
    for episode_id in episode_ids_:
        try:
            _written, marks = remove_episode(memory_path, episode_id, out.touched, reach=reaches[episode_id])
            for value, mark in marks.items():
                if sensitive_text.distinctive(value):
                    out.marks.pop(value, None)       # one row allowed it to travel: it is not guarded for the counts
                out.marks.setdefault(value, mark)
            out.done.append(episode_id)
        except Exception as exc:  # noqa: BLE001 - this row stands, its value still findable; the others go on
            logger.warning(f"Sensitive removal stopped on one conversation: {type(exc).__name__}")
            out.failed.append(episode_id)
    out.touched[:] = list(dict.fromkeys(out.touched))
    return out


def keep_episode(memory_path: Path, episode_id: str) -> list[str]:
    """The person looked and it is fine: remember how many of each kind they saw, so only a new one asks again."""
    memory_path = Path(memory_path)
    path = _episode_path(memory_path, episode_id)
    if path is None:
        return []
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        counts = Counter(h.kind for h in hits_of(fm, parsed.body))
        if not counts:
            return []
        record = dict(_record(fm))
        record["kept"] = dict(counts)
        fm[KEY] = record
        _keep_turns_last(fm)
        markdown_parser.write(path, fm, parsed.body)
    return [path.relative_to(memory_path).as_posix()]


#: The last index clean-up started, so a test can wait for it.
_cleanup: threading.Thread | None = None


def answer(memory_path: Path, path: Path, fm: dict, target: list[dict], label: str, before) -> dict:
    """The person's answer on these rows, committed as theirs: the conversations, the files that repeated a value, and the
    item. A row that could not be done stays in the item. A failed commit stays uncommitted and is said in the log:
    restoring would put the words back. Raises :class:`RemovalRefused` when the older version cannot be kept."""
    global _cleanup
    from api.services import git_service, page_lock

    memory_path = Path(memory_path)
    rows = [r for r in fm.get("rows") or [] if isinstance(r, dict)]
    trigger = TRIGGER_REMOVED if label == REMOVE else TRIGGER_KEPT
    rel_item = f"inbox/{Path(path).name}"
    touched: list[str] = []
    removed = Removed()
    with page_lock.page_lock(memory_path):
        if label == REMOVE:
            removed = remove_rows(memory_path, [str(r.get("episode") or "") for r in target])
            touched.extend(removed.touched)
        else:
            for row in target:
                touched.extend(w for w in keep_episode(memory_path, str(row.get("episode") or "")) if w not in touched)
        answered = [r for r in target if str(r.get("episode") or "") not in removed.failed]
        left = [r for r in rows if r not in answered]
        if left:
            _write_item(Path(path), dict(fm), left, fm.get("replaced"))
        else:
            Path(path).unlink(missing_ok=True)
        touched.append(rel_item)
        bank_index.invalidate(memory_path)
        if (memory_path / ".git").exists():
            lines = [f"{rel}: updated (trigger: {trigger})" for rel in touched]
            message = git_service.build_commit_message(f"Inbox resolution (sensitive) {date.today().isoformat()}", lines,
                                                       authors=["user"])
            day = date.today().isoformat()
            try:
                git_service.commit_touched_sync(memory_path, message, touched, before=before,
                                                kept_subject=f"Uncommitted edit kept apart {day}",
                                                kept_trigger="inbox/kept-apart")
            except Exception as exc:  # noqa: BLE001 - never restore: that would put the words back
                logger.warning(f"Sensitive answer left uncommitted: {type(exc).__name__}")
    if removed.marks:
        _cleanup = threading.Thread(target=forget_in_indexes, args=(memory_path, removed.marks, tuple(removed.done)),
                                    daemon=True)
        _cleanup.start()
    return {"failed": len(removed.failed)}


def plan(memory_path: Path) -> list[dict]:
    """Every conversation holding something the person has not left, read or waiting: what Remove would touch. No value,
    title or path: a row id, the kinds with their counts and how sure, the source as an enum (anything unknown ``other``,
    so a folder's name cannot reach it), the day, and whether Sleep has read it. Reads files only."""
    from api.services import source_overview

    known = {o for spec in source_overview.CATALOG for o in spec.origins} | set(episode_scrub.WRITERS) | _SESSION_SOURCES
    out: list[dict] = []
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        try:
            body = f.body() or ""
            hits = hits_of(fm, body)
        except Exception as exc:  # noqa: BLE001 - one unreadable conversation is no row
            logger.debug(f"sensitive plan skipped one: {type(exc).__name__}")
            continue
        kept = _record(fm).get("kept") if isinstance(_record(fm).get("kept"), dict) else {}
        counts = Counter(h.kind for h in hits)
        live = [h for h in hits if counts[h.kind] > int(kept.get(h.kind) or 0)]
        if not live:
            continue
        source = str(fm.get("source") or "unknown")
        out.append({"row": row_id(str(fm.get("id") or f.stem)), "episode": str(fm.get("id") or f.stem),
                    "kinds": dict(Counter(h.kind for h in live)), "unsure": sum(not h.sure for h in live),
                    "source": source if source in known else "other", "day": str(fm.get("timestamp") or "")[:10],
                    "read": fm.get("processed") is True})
    out.sort(key=lambda r: r["day"], reverse=True)
    return out


_SESSION_SOURCES = frozenset({"claude-code", "codex", "cursor", "gemini", "gemini-cli", "opencode", "chatgpt", "claude",
                              "mcp", "mcp-remote", "cli"})


def plan_reach(memory_path: Path, rows: list[dict]) -> dict[str, dict]:
    """What each row of a :func:`plan` would touch beyond itself: ``conversations`` and ``files`` rewritten, and ``stays``, how
    many of its tokens stay out of other files for being unsure or common in this bank. Counts by row id. Reads files only."""
    memory_path = Path(memory_path)
    files: list[tuple[Path, str]] = []
    for path in sensitive_purge.bank_files(memory_path):
        try:
            files.append((path, path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError):
            continue
    out: dict[str, dict] = {}
    for row in rows:
        reach = _reach(memory_path, row["episode"])
        marks = reach.marks if reach is not None else {}
        out[row["row"]] = {
            "conversations": len(reach.echoes) if reach is not None else 0,
            "files": sum(sensitive_purge.would_change(p, t, marks, tied_ids=(row["episode"],)) for p, t in files) if marks else 0,
            "stays": sum(isinstance(v, sensitive_text.Guarded) for v in marks)}
    return out


def plan_stamp(rows: list[dict]) -> str:
    """What a dry run saw, as one short word: each row's id, kinds with their counts and how many unsure. Ids and counts
    only, so it says nothing of what the rows hold. A row swapped, added or grown since changes it."""
    seen = sorted((r["row"], sorted(r["kinds"].items()), r["unsure"]) for r in rows)
    return hashlib.sha256(json.dumps(seen).encode("utf-8")).hexdigest()[:16]


def remove_planned(memory_path: Path, rows: list[str], *, stamp: str, before=None) -> dict:
    """Remove on exactly the rows a dry run listed, named by id with that run's :func:`plan_stamp`. A row gone or a plan
    changed refuses before a word changes, so nothing is removed that was never looked at. Commits as the person's, and
    brings the review in step. Counts only; ``still_found`` is how many files, conversations included, still hold what this
    was to take out (a key field, a file that does not parse), ``stayed`` how many tokens were left in other files on purpose
    (unsure, or common in this bank), and ``committed`` whether the commit took."""
    from api.services import git_service, page_lock

    memory_path = Path(memory_path)
    listed = {r["row"]: r for r in plan(memory_path)}
    if not set(rows) <= set(listed):
        raise ValueError("A conversation in the dry run is no longer waiting. Run the dry run again.")
    target = [listed[r] for r in dict.fromkeys(rows)]
    if plan_stamp(target) != stamp:
        raise ValueError("What the dry run listed has changed. Run the dry run again.")
    committed = True
    with page_lock.page_lock(memory_path):
        removed = remove_rows(memory_path, [r["episode"] for r in target])
        touched = removed.touched
        bank_index.invalidate(memory_path)
        review = sync_review(memory_path)
        touched.extend(p for p in review.paths if p not in touched)
        if touched:
            day = date.today().isoformat()
            message = git_service.build_commit_message(f"Sensitive removal {day}",
                                                       [f"{rel}: updated (trigger: {TRIGGER_REMOVED})" for rel in touched],
                                                       authors=["user"])
            try:
                git_service.commit_touched_sync(memory_path, message, touched, before=before,
                                                kept_subject=f"Uncommitted edit kept apart {day}",
                                                kept_trigger="inbox/kept-apart")
            except Exception as exc:  # noqa: BLE001 - never restore: that would put the words back
                committed = False
                logger.warning(f"Sensitive removal left uncommitted: {type(exc).__name__}")
    if removed.marks:
        forget_in_indexes(memory_path, removed.marks, tuple(removed.done))
    return {"removed": len(removed.done), "failed": len(removed.failed), "files": len(touched), "committed": committed,
            "left": len(plan(memory_path)), "still_found": sensitive_purge.residue(memory_path, removed.marks, tuple(removed.done)),
            "stayed": sum(isinstance(v, sensitive_text.Guarded) for v in removed.marks)}


def forget_in_indexes(memory_path: Path, marks: dict[str, str], episodes: tuple[str, ...] = ()) -> None:
    """The derived indexes hold text too. The word index is rebuilt on a new file (a dropped table's bytes stay in the
    old one). In the vector index the passages of these conversations, and any holding a distinctive value, are deleted
    now, their bytes overwritten (the next sync re-embeds what is left). A word that is not distinctive is found only by
    its conversation, so a passage that merely uses the word stays. Disposable, so a failure logs its class and never undoes
    the removal."""
    from api.services import search_index, vector_index

    try:
        search_index.rebuild_fresh(Path(memory_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Search index rebuild after a removal failed: {type(exc).__name__}")
    try:
        vector_index.forget_passages(Path(memory_path), tuple(v for v in marks if sensitive_text.distinctive(v)), episodes)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Vector index clean-up after a removal failed: {type(exc).__name__}")
