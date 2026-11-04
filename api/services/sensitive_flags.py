"""Telling the person what may be sensitive and which engine read it, and taking it back out (G235, owner 2026-11-04).

`sensitive_text` finds; this module acts on what it finds. Engine-free throughout: no model reads text to decide whether a
model may read it. **Nothing here stores, logs, commits or returns a value**, nor a hash of one (a hash of a short
password is the password, to anyone with a wordlist): an episode's record holds kinds, counts, engine labels and dates, and
every value is re-derived in memory from the body when needed.

**Before the engine reads** (:class:`Guard`, at ``entity_extractor.extract``'s send point; the quick read goes through it
too). The hits in the windows about to be sent are found, and the read is recorded on the episode (:func:`note_read`,
Sleep only). With hold back on (:func:`holds_back`) the engine reads a typed mark where each value was; the stored body is
untouched, so spans keep their offsets. Either way, the value is taken back out of whatever the model answered, and an item
built only on it is dropped, so a page never repeats it (:meth:`Guard.clean`, and :func:`sweep_written` before the commit).

**The review** (:func:`sync_review`, the tail). One inbox item, one row per conversation: which conversation, what kind,
which engine read it. Never one question per hit. A row is checked against the body as it is now, so an edit that removed
the text removes the row. Conversations read before this existed are found once, by :func:`sweep_read`: a report only, which
writes nothing on an episode.

**Remove** (:func:`remove_episode`, the person's act alone). The values leave the body through the revision path
(``revised`` record, ``processed: false``), and leave every page, claim, ledger line and inbox item that repeated them, at
once and by exact match. The next Sleep reads it as a revision with no engine call and closes what only those words said
(`episode_revision`). The source may send the words again: :func:`reapply_draft` and :func:`reapply_conversation` take
them out on the way in, and :func:`reapply_waiting` catches any other writer before a read. **Git history keeps the older
version; history is never rewritten.** What an engine already read cannot be unread.

**Leave it** records how many of each kind the person saw (``kept``), so only a new one asks again."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from loguru import logger

from api.services import authorship, bank_index, episode_ids, episode_scrub, evidence, markdown_parser, sensitive_text
from api.services.sensitive_text import HELD_MARK, REMOVED_MARK, Hit

#: The episode frontmatter key: ``{read: [{engine, at, kinds, held?}], kept: {kind: n}, removed: {kinds, at, pending?}}``.
KEY = "sensitive"
KIND = "sensitive"
REMOVE, KEEP = "remove", "keep"
#: The owner's pending decision, as one switch: on, an engine reads a typed mark where a hit was. Off: it only reports.
HOLD_ENV = "CICADA_SENSITIVE_HOLD_BACK"
#: What a value becomes in what a model answered. An item that rests on nothing else is dropped.
STRIPPED = "[removed]"
TRIGGER_REVIEW = "sleep/sensitive-review"
TRIGGER_REMOVED = "inbox/sensitive/removed"
TRIGGER_KEPT = "inbox/sensitive/kept"
#: Bump when the detector changes what it finds, so the already-read conversations are looked through once more.
DETECTOR_VERSION = 1
#: Directories of a bank a value may have reached: never ``episodes`` (each its own row) or git.
_PAGE_DIRS = ("entities", "hubs", "inbox", "backlog", "skills", "projects")
_PAGE_SUFFIXES = (".md", ".jsonl")
#: Who read it, in the person's terms. A name only ever says the person's own current or past choice.
_LOCAL_ENGINE = "ollama"


def holds_back(environ=os.environ) -> bool:
    return str(environ.get(HOLD_ENV) or "").strip().lower() in ("1", "on", "true", "yes")


def _record(fm: dict | None) -> dict:
    record = (fm or {}).get(KEY)
    return record if isinstance(record, dict) else {}


def _session(fm: dict) -> bool:
    return bool(fm.get("harness") or fm.get("capture_kind") == "transcript")


def hits_of(fm: dict, body: str) -> list[Hit]:
    """What is likely sensitive in a stored episode, read the way its own record says."""
    return sensitive_text.find(body, harness=_session(fm), override=authorship.of(fm), gaps=evidence.gap_ranges(fm, body))


def _keep_turns_last(fm: dict) -> None:
    if "turns" in fm:
        fm["turns"] = fm.pop("turns")   # R-PB4: the sidecar stays the last key


# ---- before the engine reads ----------------------------------------------------------------------------------------


@dataclass
class Guard:
    """One episode's hits at the send point. Holds the values in memory for as long as this read takes."""
    hits: tuple[Hit, ...] = ()
    values: tuple[str, ...] = ()
    held: bool = False

    @classmethod
    def of(cls, episode: dict, spans, *, hold: bool) -> "Guard":
        """The hits inside what is about to be sent (``spans``, the chunks' ranges). A failure here is no hit: it
        logs its class and costs the report, never the read."""
        try:
            content = str(episode.get("content") or "")
            hits = tuple(h for h in sensitive_text.find_in_episode(episode)
                         if any(h.start < hi and h.end > lo for lo, hi in spans))
            return cls(hits, sensitive_text.values_of(content, hits), hold and bool(hits))
        except Exception as exc:  # noqa: BLE001 - the detector never fails a read
            logger.warning(f"Sensitive check skipped: {type(exc).__name__}")
            return cls()

    def chunk(self, masked: str, lo: int, hi: int) -> str:
        """``masked[lo:hi]`` as the engine reads it."""
        if not self.held:
            return masked[lo:hi]
        return sensitive_text.held_text(masked, lo, hi, self.hits)

    def kinds(self) -> dict[str, int]:
        return dict(Counter(h.kind for h in self.hits))

    def clean(self, entities: list, relationships: list, values: list) -> tuple[list, list, list]:
        """A model's answer without the values. A name, an end of a link or a value that WAS one is dropped: a page
        named after a password, or a claim whose object is only a mark, holds nothing worth keeping."""
        if not self.hits:
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


def note_read(episode: dict, kinds: dict[str, int], engine: str | None, *, held: bool = False) -> None:
    """Record on the episode that this engine is about to read these kinds. Frontmatter only, so the body, its hash and
    its queue state stay as they are. ``engine`` omitted rather than guessed (the ``Cicada-Engine`` rule). Never raises."""
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
                row["held"] = True
            record["read"] = [*reads, row]
            fm[KEY] = record
            _keep_turns_last(fm)
            markdown_parser.write(path, fm, parsed.body)
        bank_index.invalidate(path.parent.parent)
    except Exception as exc:  # noqa: BLE001 - the record never fails a read
        logger.warning(f"Sensitive record skipped: {type(exc).__name__}")


def engine_view(text: str) -> str:
    """A line of a stored conversation on its way into a prompt outside Stage 1 (a question's evidence): with hold back
    on, without what it holds. Off, unchanged."""
    if not holds_back() or not text:
        return text
    return sensitive_text.replace_hits(text, sensitive_text.find(text), HELD_MARK)


def sweep_written(memory_path: Path, episodes: list[dict], dirty) -> int:
    """Before the batch's commit, one engine-free pass over what it wrote: any value of the batch's conversations left
    in a page by any stage comes out. Stage 1's answer is cleaned already; this holds for every later writer. Returns
    how many files changed. Never raises."""
    try:
        values: list[str] = []
        for ep in episodes:
            content = str(ep.get("content") or "")
            values.extend(sensitive_text.values_of(content, sensitive_text.find_in_episode(ep)))
        if not values:
            return 0
        ordered = tuple(sorted(set(values), key=len, reverse=True))
        changed = 0
        for rel in dirty:
            if not rel.endswith(_PAGE_SUFFIXES) or rel.split("/", 1)[0] not in _PAGE_DIRS:
                continue
            if _strip_file(Path(memory_path) / rel, ordered, STRIPPED):
                changed += 1
        if changed:
            bank_index.invalidate(memory_path)
        return changed
    except Exception as exc:  # noqa: BLE001 - a guard on the way to a commit, never the reason it fails
        logger.warning(f"Sensitive sweep skipped: {type(exc).__name__}")
        return 0


def _strip_file(path: Path, values: tuple[str, ...], mark: str) -> bool:
    """Replace whole-token ``values`` in one file, atomically. Raw text, so the file's YAML and fences stay byte-for-byte
    apart from the values."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if not any(v in text for v in values):
        return False
    cleaned, n = sensitive_text.strip_values(text, values, mark)
    if not n:
        return False
    tmp = path.with_name(f".{path.name}.sensitive.tmp")
    try:
        tmp.write_text(cleaned, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return True


# ---- the source sends the words again -------------------------------------------------------------------------------


def removed_kinds(fm: dict | None) -> frozenset[str]:
    removed = _record(fm).get("removed")
    kinds = removed.get("kinds") if isinstance(removed, dict) else None
    return frozenset(str(k) for k in kinds or [])


def removal_pending(fm: dict | None) -> bool:
    removed = _record(fm).get("removed")
    return isinstance(removed, dict) and bool(removed.get("pending"))


def _out(text: str, kinds: frozenset[str], *, harness: bool, override: str | None, prefix: str = "") -> str:
    """``text`` without the hits of ``kinds``, read as a line under ``prefix`` (a turn's marker)."""
    whole = prefix + text
    hits = [h for h in sensitive_text.find(whole, harness=harness, override=override) if h.kind in kinds]
    if not hits:
        return text
    return sensitive_text.replace_hits(whole, hits, REMOVED_MARK)[len(prefix):]


def reapply_draft(draft, fm: dict):
    """A source-keyed writer's draft for an episode the person removed text from: the same text taken out before it is
    rendered and hashed, so an unchanged source hashes as unchanged and a changed one never brings the words back."""
    kinds = removed_kinds(fm)
    if not kinds:
        return draft
    harness, override = _session(fm), authorship.of(fm)
    changes: dict = {}
    if getattr(draft, "body", None) is not None:
        changes["body"] = _out(draft.body, kinds, harness=harness, override=override)
    if getattr(draft, "turns", None):
        changes["turns"] = [replace(t, text=_out(t.text, kinds, harness=harness, override=override,
                                                 prefix=f"{t.speaker}: ")) for t in draft.turns]
    if getattr(draft, "title", None):
        changes["title"] = _out(draft.title, kinds, harness=harness, override=override)
    return replace(draft, **changes)


def reapply_conversation(conv, fm: dict) -> None:
    """The Stop hook's writer rebuilds a session's body from its transcript on every turn: the same removal on each
    turn's text, in place, before the body, its hash and its sidecar are built from them."""
    kinds = removed_kinds(fm)
    if not kinds:
        return
    harness, override = True, authorship.of(fm)
    for turn in conv.turns:
        turn.text = _out(turn.text, kinds, harness=harness, override=override, prefix=f"{turn.role}: ")


def _shift_offsets(value, shift):
    """Every ``offset`` in a frontmatter value moved by ``shift``: the sidecars index the body (`evidence.turn_stamps`)."""
    if isinstance(value, dict):
        return {k: (shift(v) if k == "offset" and isinstance(v, int) else _shift_offsets(v, shift))
                for k, v in value.items()}
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


def _strip_fm_strings(value, marks: dict[str, str], *, key=None):
    """A value out of the strings a writer keeps beside the body (a title, a description). Keys and ids stay."""
    if isinstance(value, str):
        if episode_scrub._is_key_field(key):
            return value
        for found, mark in marks.items():
            value, _n = sensitive_text.strip_values(value, (found,), mark)
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

    marks = {body[h.start:h.end]: REMOVED_MARK.format(kind=h.kind) for h in hits}
    new_body = sensitive_text.replace_hits(body, hits, REMOVED_MARK)
    shift = _mapper(hits, REMOVED_MARK)
    out = {k: (v if k == KEY else _strip_fm_strings(_shift_offsets(v, shift), marks, key=k)) for k, v in fm.items()}
    out[episode_staging.REVISED_KEY] = episode_staging.revision_record(fm, at=at)
    out["content_hash"] = episode_staging.content_hash(new_body)
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


def same_after_removal(prior: str, body: str, episode: dict) -> bool:
    """Is the removal all that changed? The earlier body, with the same text taken out, is this body."""
    kinds = removed_kinds({KEY: episode.get(KEY)})
    ctx = _context_of_episode(episode)
    hits = [h for h in sensitive_text.find(prior, **ctx) if h.kind in kinds]
    return sensitive_text.replace_hits(prior, hits, REMOVED_MARK) == body


def masked_for_engine(text: str) -> str:
    """A passage of a conversation as it may reach a prompt on a revision: never a value, whichever mode is on."""
    return sensitive_text.replace_hits(text, sensitive_text.find(text), REMOVED_MARK) if text else text


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


def safe_title(fm: dict, body: str, hits: list[Hit]) -> str:
    """The conversation's title, or a plain stand-in when the title itself may hold the value: a first line is often
    what a title is made from, and the review must never repeat it."""
    title = str(fm.get("title") or "").strip()
    values = sensitive_text.values_of(body, hits)
    if not title or any(v in title for v in values) or sensitive_text.find(title):
        return "A conversation"
    return title


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
    names = list(dict.fromkeys(n for n in (engine_name(r.get("engine")) for r in reads if not r.get("held")) if n))
    held_from = list(dict.fromkeys(n for n in (engine_name(r.get("engine")) for r in reads if r.get("held")) if n))
    episode = str(fm.get("id") or stem)
    row: dict = {"id": row_id(episode), "episode": episode, "title": safe_title(fm, body, hits),
                 "day": str(fm.get("timestamp") or "")[:10], "kinds": kinds}
    if names:
        row["read_by"] = names
    if held_from and not names:
        row["held_from"] = held_from
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
        who = r.get("read_by") or r.get("held_from")
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


def remove_episode(memory_path: Path, episode_id: str) -> tuple[list[str], dict[str, str]]:
    """Take what is flagged out of one conversation and out of every page that repeated it. ``(bank-relative paths
    written, value -> mark)``. The caller holds admission and the page lock, and commits; the values leave with its
    frame. The conversation's own words around them stay."""
    memory_path = Path(memory_path)
    path = _episode_path(memory_path, episode_id)
    if path is None:
        return [], {}
    with episode_ids.episode_lock(path.parent):
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        hits = hits_of(fm, parsed.body)
        if not hits:
            return [], {}
        kinds = {h.kind for h in hits}
        new_fm, new_body, marks = _take_out(fm, parsed.body, hits, kinds, at=episode_ids.utc_now_iso(), pending=True)
        markdown_parser.write(path, new_fm, new_body)
    written = [path.relative_to(memory_path).as_posix()]
    written.extend(_purge_pages(memory_path, marks))
    awake = memory_path / ".awake" / f"{episode_id}.json"
    awake.unlink(missing_ok=True)
    return written, marks


def _purge_pages(memory_path: Path, marks: dict[str, str]) -> list[str]:
    """Each value, by exact whole-token match, out of everything Sleep and agents wrote: pages, claim fences and
    ledgers, hubs, backlog items, inbox items."""
    written: list[str] = []
    ordered = sorted(marks, key=len, reverse=True)
    for name in _PAGE_DIRS:
        root = memory_path / name
        if not root.is_dir():
            continue
        for directory, _subdirs, files in os.walk(root):
            for filename in files:
                if not filename.endswith(_PAGE_SUFFIXES):
                    continue
                target = Path(directory) / filename
                changed = False
                for value in ordered:
                    changed = _strip_file(target, (value,), marks[value]) or changed
                if changed:
                    written.append(target.relative_to(memory_path).as_posix())
    return written


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


def answer(memory_path: Path, path: Path, fm: dict, target: list[dict], label: str, before) -> None:
    """The person's answer on these rows, committed as theirs: the conversations, the pages that repeated a value, and
    the item. A failed commit stays uncommitted and is said in the log: restoring would put the words back."""
    global _cleanup
    from api.services import git_service, page_lock

    memory_path = Path(memory_path)
    rows = [r for r in fm.get("rows") or [] if isinstance(r, dict)]
    trigger = TRIGGER_REMOVED if label == REMOVE else TRIGGER_KEPT
    rel_item = f"inbox/{Path(path).name}"
    touched: list[str] = []
    all_marks: dict[str, str] = {}
    with page_lock.page_lock(memory_path):
        for row in target:
            if label == REMOVE:
                written, marks = remove_episode(memory_path, str(row.get("episode") or ""))
                all_marks.update(marks)
            else:
                written = keep_episode(memory_path, str(row.get("episode") or ""))
            touched.extend(w for w in written if w not in touched)
        left = [r for r in rows if r not in target]
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
    if all_marks:
        _cleanup = threading.Thread(target=forget_in_indexes, args=(memory_path, all_marks), daemon=True)
        _cleanup.start()


def forget_in_indexes(memory_path: Path, marks: dict[str, str]) -> None:
    """The derived indexes hold text too. The word index is rebuilt on a new file (a dropped table's bytes stay in the
    old one); the passages in the vector index that hold a value are deleted now, their bytes overwritten (the next
    sync re-embeds what is left). Disposable, so a failure logs its class and never undoes the removal."""
    from api.services import search_index, vector_index

    try:
        search_index.rebuild_fresh(Path(memory_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Search index rebuild after a removal failed: {type(exc).__name__}")
    try:
        vector_index.forget_passages(Path(memory_path), tuple(marks))
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Vector index clean-up after a removal failed: {type(exc).__name__}")
