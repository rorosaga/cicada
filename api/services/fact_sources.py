"""G61 — the entity ``sources:`` key: *where to look a fact up*.

Distinct from two neighbours it is easy to confuse:

- ``source_episodes`` (frontmatter) is **provenance** — where a belief CAME from.
- ``api/services/entity_sources.py`` resolves those episodes back to whole
  conversations. Different concept, different module; this one is ``fact_sources``.
- The body's ``## Links`` section is a loose bookmark list.

A *source* is a cheat-sheet for REFRESHING a specific fact: a URL, a local path,
or a plain-English instruction ("ask me — I announce job changes"). Stored as::

    sources:
      - ref: https://example.com/bob-example/team
        kind: url              # url | path | note | app | repo
        predicate: works-at    # optional — which fact this refreshes
        access: public         # public | signed_in | local | unknown — stated, else inferred at read
        added_by: user         # user | <harness label> | cicada | <model id>
        added_at: '2026-08-30'
        accepted: true         # an agent-found source the person took
        only_me: true          # the person's "Only I know" (a note, one predicate)

G61 phase 2 S0 (spec ``docs/specs/2026-09-23-g61-agent-first-clarification-design.md``
§5.5; plan ``docs/plans/2026-09-23-g61-s0-s2.md``): an entry is keyed
on ``(ref, predicate)`` so one link can serve two facts, and a conflict card's
``hint`` is DERIVED at read (:func:`served_hint`) instead of being written into
the item — a source added after a question opened reaches the card at once — in
a voice that says who added it. Phase 2 S1 adds what a checker needs to know:
``kind: app|repo``, a stated ``access`` (else :func:`effective_access` infers it
at read), ``accepted`` and the person's ``only_me``; and :func:`attach_cited_urls`
turns a link a claim's own cited words contain into a source for that fact.
This module never FETCHES anything.

G61 S3-a (sources as a living set, 2026-09-30): a page holds MANY sources — per
predicate, capped (:data:`MAX_SOURCES`, :data:`MAX_PER_PREDICATE`) — and they
are managed after they are added: :func:`change_source` updates, replaces or
removes an entry (the person any entry; an agent only one it added,
:func:`owns_source`), a removal leaves a ``sources_removed:`` tombstone that
every non-person writer respects (:func:`is_tombstoned`), an entry may point
at the page that knows more about it (``entity:``, :func:`resolve_entity_link`),
and :func:`rank` is the one function every reader uses to pick among many.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from api.services import markdown_parser

KIND_URL = "url"
KIND_PATH = "path"
KIND_NOTE = "note"

USER = "user"
CICADA = "cicada"

# G61 phase 2 S1 (spec §5.1, plan R-AC27): the kinds a checker can route and
# the access a source needs. `app` and `repo` are never inferred — a caller says so.
KIND_APP = "app"
KIND_REPO = "repo"
KINDS = (KIND_URL, KIND_PATH, KIND_NOTE, KIND_APP, KIND_REPO)
LOCAL_KINDS = frozenset({KIND_PATH, KIND_REPO})

ACCESS_PUBLIC = "public"
ACCESS_SIGNED_IN = "signed_in"
ACCESS_LOCAL = "local"
ACCESS_UNKNOWN = "unknown"
ACCESS_VALUES = (ACCESS_PUBLIC, ACCESS_SIGNED_IN, ACCESS_LOCAL, ACCESS_UNKNOWN)

MAX_REF_CHARS = 2048
# G61 S3-a (D7): a page cannot balloon. Caps refuse an agent's add in words;
# the person's is never refused for size.
MAX_SOURCES = 30
MAX_PER_PREDICATE = 8
MAX_TOMBSTONES = 20
MAX_REASON_CHARS = 160
REMOVED_KEY = "sources_removed"
REMOTE_PREFIX = "remote:"
_UNSET = object()
MAX_CITED_URLS = 3
# The capture writers' URL shape (`telegram_capture._URL_RE`), trailing
# sentence punctuation stripped after the match.
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
_URL_TRAIL = ".,;:!?"


class InvalidSource(ValueError):
    """A value the source record does not allow. ``POST /entities/{id}/sources``
    answers 400 with the message; agent paths drop the field instead."""


class SourceRemoved(InvalidSource):
    """The key was removed earlier and a writer that is not the person's must not
    put it back (the tombstone, :func:`is_tombstoned`)."""


class SourceCapReached(InvalidSource):
    """A page already holds as many sources as an agent may add."""


def _validate(ref: str, kind: str, access: str | None) -> None:
    if len(ref) > MAX_REF_CHARS:
        raise InvalidSource(f"a source is at most {MAX_REF_CHARS:,} characters")
    if kind not in KINDS:
        raise InvalidSource(f"kind must be one of {', '.join(KINDS)}")
    if access is not None and access not in ACCESS_VALUES:
        raise InvalidSource(f"access must be one of {', '.join(ACCESS_VALUES)}")
    if access == ACCESS_LOCAL and kind not in LOCAL_KINDS:
        raise InvalidSource("access 'local' is for a path or a repo on this Mac")


def _apply_persons_fields(source: dict, access: str | None, accepted: bool | None, only_me: bool) -> bool:
    """The person's repeat of an existing entry (plan R-AC21): the fields that are
    theirs to say. ``accepted`` only on someone else's entry; ``only_me`` only on
    a note. Returns whether anything changed."""
    changed = False
    if access and source.get("access") != access:
        source["access"] = access
        changed = True
    if accepted and str(source.get("added_by") or USER) != USER and not source.get("accepted"):
        source["accepted"] = True
        changed = True
    if only_me and source.get("kind") == KIND_NOTE and not source.get("only_me"):
        source["only_me"] = True
        changed = True
    return changed


def infer_kind(ref: str) -> str:
    """``http(s)://`` -> url; a leading ``/`` or ``~`` -> path; else note."""
    text = (ref or "").strip()
    if text.startswith(("http://", "https://")):
        return KIND_URL
    if text.startswith(("/", "~")):
        return KIND_PATH
    return KIND_NOTE


def _entity_path(memory_path: Path, entity_id: str) -> Path:
    return Path(memory_path) / "entities" / f"{entity_id}.md"


def as_sources(raw) -> list[dict]:
    """Every usable entry of a ``sources:`` value, as copies — dicts with a ``ref``.

    One reader for the page on disk (:func:`list_sources`) and for a frontmatter a
    caller already holds (``InboxContext``'s page cache), so the two can never
    disagree about what counts as a source. A hand-edited value that is not a
    list (``sources: https://…``) reads as no sources: the hint is derived on
    every inbox read now, and ``load_inbox`` skips an item whose read raises —
    a malformed page must never hide a question (plan R-AC23)."""
    if not isinstance(raw, list):
        return []
    return [dict(s) for s in raw if isinstance(s, dict) and s.get("ref")]


def same_predicate(a, b) -> bool:
    """Predicates compare case-insensitively; a missing one is its own value (a
    source for the page as a whole), never a wildcard (plan R-AC20)."""
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def list_sources(memory_path: Path, entity_id: str) -> list[dict]:
    """The entity's declared sources, in file order. ``[]`` when absent."""
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return []
    try:
        fm = markdown_parser.parse(path).frontmatter
    except Exception:
        return []
    return as_sources(fm.get("sources"))


def trusted(source: dict) -> bool:
    """The person's own, or one they took (``accepted``), or one Cicada's own read
    confirmed (``verified``, written only by PR2's fetch). One rule for every
    reader that must decide how far to lean on an entry; it never means "true"."""
    who = str(source.get("added_by") or USER).strip() or USER
    return who == USER or bool(source.get("accepted")) or bool(source.get("verified"))


source_trusted = trusted


def _order(source: dict) -> int:
    who = str(source.get("added_by") or USER).strip() or USER
    if who == USER:
        return 0
    if source.get("accepted") or source.get("verified"):
        return 1
    return 2 if who == CICADA else 3


def rank(entries, predicate: str | None = None, *, person_only: bool = False, match=None) -> list[dict]:
    """The sources that serve ``predicate``, best first — the ONE function every
    reader that must pick among many uses (a check's targets, a hint). No reader
    takes "the" source.

    ``match(source, predicate)`` says which entries serve the fact (default: the
    same predicate); order is the person's, then a taken or verified one, then
    Cicada's, then an agent's — file order within each. An "Only I know" note is
    never returned, and ``person_only`` (the owner's own page, R-AC9) keeps just
    what the person added or took.
    """
    usable = [s for s in as_sources(entries) if not s.get("only_me")]
    if person_only:
        usable = [s for s in usable if (str(s.get("added_by") or USER).strip() or USER) == USER or s.get("accepted")]
    match = match or (lambda s, p: bool(p) and same_predicate(s.get("predicate"), p))
    return sorted((s for s in usable if match(s, predicate)), key=_order)


def owns_source(entry: dict, *, author: str, origin: str | None = None) -> bool:
    """May this AGENT change or remove ``entry``? Only one it added (mirrors
    ``agentic_write.owns``). Never the person's, one they took (``accepted``) or
    silenced with (``only_me``), Cicada's own, or one a Sleep model added — a
    model id is not a harness label, and the unidentified ``agent`` label owns
    nothing (Stage 1's proposals carry it too). A connection owns exactly the
    entries stamped ``origin: remote:<its id>``; a local agent never edits a
    remote app's, nor the reverse."""
    who = str(entry.get("added_by") or USER).strip() or USER
    if who in (USER, CICADA) or entry.get("accepted") or entry.get("only_me"):
        return False
    entry_origin = str(entry.get("origin") or "")
    if origin and origin.startswith(REMOTE_PREFIX):
        return entry_origin == origin
    if entry_origin.startswith(REMOTE_PREFIX):
        return False
    return bool(author) and author != "agent" and who == author


# ---- the tombstone: a removal that sticks --------------------------------------------------------------------


def _tombstones(fm: dict) -> list[dict]:
    raw = fm.get(REMOVED_KEY)
    return [dict(r) for r in raw if isinstance(r, dict) and r.get("ref")] if isinstance(raw, list) else []


def _site(ref: str) -> str:
    from api.services import reading_hosts

    try:
        return reading_hosts.site_of(ref) if str(ref).startswith(("http://", "https://")) else ""
    except Exception:
        return ""


def _key_matches(row: dict, ref: str, predicate) -> bool:
    if not same_predicate(row.get("predicate"), predicate):
        return False
    if str(row.get("ref", "")).strip() == ref:
        return True
    # An official site is the same site whichever page of it was named.
    return str(predicate or "").strip().lower() == "website" and bool(_site(ref)) and _site(row.get("ref", "")) == _site(ref)


def find_tombstone(fm: dict, ref: str, predicate=None) -> dict | None:
    return next((r for r in _tombstones(fm) if _key_matches(r, str(ref).strip(), predicate)), None)


def is_tombstoned(fm: dict, ref: str, predicate=None, *, via_agent: bool = False) -> bool:
    """Would a writer that is not the person be refused this key? Every machine
    writer (Stage 1's proposal, the backfill, ``attach_cited_urls``) is refused
    any tombstone. A local or remote AGENT (``via_agent``) is refused what the
    person or Cicada removed, but may put back what an agent removed — it learns
    the source is relevant again and the reply says who removed it (D6)."""
    tomb = find_tombstone(fm, ref, predicate)
    if tomb is None:
        return False
    if not via_agent:
        return True
    return str(tomb.get("by") or "") in (USER, CICADA)


def _who_words(by: str) -> str:
    return "the person" if by == USER else "Cicada" if by == CICADA else "an agent"


def _removed_message(tomb: dict) -> str:
    reason = str(tomb.get("reason") or "").strip()
    return (f"that source was removed on {tomb.get('at') or 'an earlier day'} by {_who_words(str(tomb.get('by') or ''))}"
            + (f": {reason}" if reason else ""))


def removed_note(fm: dict, ref: str, predicate=None) -> str | None:
    """The sentence about an earlier removal of this key, or None."""
    tomb = find_tombstone(fm, ref, predicate)
    return _removed_message(tomb) if tomb is not None else None


def _push_tombstone(fm: dict, entry: dict, *, by: str, reason: str | None, at: str | None = None) -> None:
    row: dict = {"ref": str(entry.get("ref") or "").strip()}
    if str(entry.get("predicate") or "").strip():
        row["predicate"] = entry["predicate"]
    row["by"] = by
    row["at"] = at or str(date.today())
    if reason:
        row["reason"] = reason
    keep = [r for r in _tombstones(fm)
            if not (str(r.get("ref", "")).strip() == row["ref"] and same_predicate(r.get("predicate"), row.get("predicate")))]
    fm[REMOVED_KEY] = (keep + [row])[-MAX_TOMBSTONES:]


def _clear_tombstone(fm: dict, ref: str, predicate) -> bool:
    rows = _tombstones(fm)
    keep = [r for r in rows if not _key_matches(r, ref, predicate)]
    if len(keep) == len(rows):
        return False
    if keep:
        fm[REMOVED_KEY] = keep
    else:
        fm.pop(REMOVED_KEY, None)
    return True


# ---- scrub + entity links --------------------------------------------------------------------------------------


def clean_text(text: str, *, what: str = "a source") -> str:
    """The text as it may be stored: stripped, and REFUSED (never stored redacted)
    when the scrub would alter it — a URL carrying a token or a one-time code is
    not a source."""
    from api.services import episode_scrub

    text = (text or "").strip()
    scrubbed, changed = episode_scrub.scrub(text)
    if changed or scrubbed != text:
        raise InvalidSource(f"{what} that holds a secret or a one-time code can't be kept")
    return text


def _clean_reason(reason: str | None) -> str | None:
    text = " ".join(str(reason or "").split())
    if not text:
        return None
    from api.services import episode_scrub

    scrubbed, changed = episode_scrub.scrub(text)
    if changed:
        raise InvalidSource("the reason holds a secret or a one-time code")
    return scrubbed[:MAX_REASON_CHARS]


def resolve_entity_link(memory_path: Path, value, *, self_id: str | None = None) -> str:
    """``entity:`` on a source — the page that knows more about it. The page must
    exist, is not the entry's own page and is not ``dropped``; a source NEVER
    creates a page. Returns the canonical id; raises :class:`InvalidSource`."""
    from api.services.id_utils import resolve_entity_file, sanitize_id

    raw = str(value or "").strip()
    if not raw:
        raise InvalidSource("entity must name a page")
    file = resolve_entity_file(Path(memory_path), raw)
    if file is None:
        raise InvalidSource(f"there is no page '{sanitize_id(raw)}' to link the source to")
    if self_id and file.stem == self_id:
        raise InvalidSource("a source can't link to the page it is on")
    try:
        status = str(markdown_parser.parse(file).frontmatter.get("status") or "")
    except Exception:
        status = ""
    if status == "dropped":
        raise InvalidSource(f"'{file.stem}' was dropped, so a source can't link to it")
    return file.stem


def linked_entity(memory_path: Path, source: dict, *, self_id: str | None = None) -> str | None:
    """The ``entity:`` of a source when it still resolves — a stale id (a page
    deleted or merged away) reads as no link everywhere."""
    value = str(source.get("entity") or "").strip()
    if not value:
        return None
    try:
        return resolve_entity_link(memory_path, value, self_id=self_id)
    except InvalidSource:
        return None


def add_source(
    memory_path: Path,
    entity_id: str,
    ref: str,
    *,
    kind: str | None = None,
    predicate: str | None = None,
    added_by: str = USER,
    added_at: str | None = None,
    access: str | None = None,
    accepted: bool | None = None,
    only_me: bool | None = None,
    origin: str | None = None,
    entity: str | None = None,
    via_agent: bool = False,
) -> dict | None:
    """Append one source to the entity's ``sources:`` key. Idempotent on
    ``(ref, predicate)``.

    G61 phase 2 S0 (spec §5.1, plan R-AC20): the same link may be where to check
    two different facts, and keying on ``ref`` alone silently dropped the second.
    A repeat returns the STORED entry: the first adder keeps the credit.

    Phase 2 S1 (plan R-AC21, R-AC27, R-AC28) — each field written only when it
    says something: ``kind`` may be ``app`` or ``repo`` (never inferred);
    ``access`` is the adder's statement, otherwise inferred at read by
    :func:`effective_access` and never stored; ``only_me`` is the PERSON's "Only
    I know" for one predicate — a ``note``, never without a predicate. When the
    person repeats an existing entry, ``access``/``accepted``/``only_me`` are
    applied to it (the card's "Use this source" needs no second route); an
    agent's repeat never changes an entry.

    S3-a: a page holds MANY sources. The ref must survive the scrub unchanged
    (a secret-bearing link is refused); a writer that is not the person is
    refused a key that was removed (:class:`SourceRemoved`) and, past the caps,
    a new entry (:class:`SourceCapReached`); the person's add clears a
    tombstone. ``origin`` (``remote:<id>``) marks a connection's own entry —
    what :func:`owns_source` compares. ``entity`` links the entry to a page that
    knows more about it (:func:`resolve_entity_link`); ``via_agent`` says the
    caller is an MCP agent, which the tombstone treats differently from a
    machine writer (:func:`is_tombstoned`).

    Raises :class:`InvalidSource` for a value the record does not allow; returns
    ``None`` when the ref is blank or the entity does not exist.
    """
    text = (ref or "").strip()
    if not text:
        return None
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return None
    by_person = (added_by or USER) == USER
    only_me = bool(only_me) and by_person
    if only_me:
        if not str(predicate or "").strip():
            raise InvalidSource("only_me needs a predicate: it silences one fact, never a whole page")
        kind = KIND_NOTE
    kind_value = (kind or infer_kind(text)).strip().lower()
    access_value = (access or "").strip().lower() or None
    _validate(text, kind_value, access_value)
    text = clean_text(text)
    if not by_person and kind_value == KIND_URL:
        text = text.split("#", 1)[0]
    entity_id_link = resolve_entity_link(memory_path, entity, self_id=entity_id) if entity else None

    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    existing = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    for source in existing:
        if str(source.get("ref", "")).strip() == text and same_predicate(source.get("predicate"), predicate):
            if by_person and _apply_persons_fields(source, access_value, accepted, only_me):
                fm["sources"] = existing
                markdown_parser.write(path, fm, parsed.body)
            return dict(source)

    if by_person:
        _clear_tombstone(fm, text, predicate)
    else:
        tomb = find_tombstone(fm, text, predicate)
        if tomb is not None and is_tombstoned(fm, text, predicate, via_agent=via_agent):
            raise SourceRemoved(_removed_message(tomb))
        if len(existing) >= MAX_SOURCES or sum(
                1 for s in existing if same_predicate(s.get("predicate"), predicate)) >= MAX_PER_PREDICATE:
            raise SourceCapReached(
                "this page already lists as many sources as it can hold for that fact; remove one that is no "
                "longer relevant first")

    entry: dict = {"ref": text, "kind": kind_value}
    if predicate:
        entry["predicate"] = predicate
    if access_value:
        entry["access"] = access_value
    entry["added_by"] = added_by or USER
    entry["added_at"] = added_at or str(date.today())
    if origin and str(origin).startswith(REMOTE_PREFIX):
        entry["origin"] = str(origin)
    if entity_id_link:
        entry["entity"] = entity_id_link
    if only_me:
        entry["only_me"] = True

    fm["sources"] = existing + [entry]
    markdown_parser.write(path, fm, parsed.body)
    return entry


def delete_source(memory_path: Path, entity_id: str, index: int, *, remembered_by: str | None = None) -> bool:
    """Remove the source at ``index``. Returns whether anything was removed.

    Removing the last source drops the ``sources:`` key entirely, so an entity
    that never had one stays byte-identical. ``remembered_by`` leaves a
    tombstone for the entry (the person's removal by index, for older clients).
    """
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return False
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    existing = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    if index < 0 or index >= len(existing):
        return False
    removed = existing.pop(index)
    if remembered_by and str(removed.get("ref") or "").strip():
        _push_tombstone(fm, removed, by=remembered_by, reason=None)
    if existing:
        fm["sources"] = existing
    else:
        fm.pop("sources", None)
    markdown_parser.write(path, fm, parsed.body)
    return True


@dataclass
class ChangeResult:
    """``action`` is one of ``updated | replaced | removed | not_found | not_yours | refused``."""

    action: str
    entry: dict | None = None
    message: str = ""


def change_source(
    memory_path: Path,
    entity_id: str,
    ref: str,
    predicate: str | None = None,
    *,
    actor: str = USER,
    origin: str | None = None,
    action: str = "update",
    reason: str | None = None,
    new_ref: str | None = None,
    new_predicate: str | None = None,
    access: str | None = None,
    entity=_UNSET,
    accepted: bool | None = None,
    only_me: bool | None = None,
    via_agent: bool = False,
) -> ChangeResult:
    """Update, replace or remove ONE source, keyed ``(ref, predicate)`` — the
    page's frontmatter only, never its body, never a commit (the caller commits,
    under the right author).

    ``actor`` is ``user`` (any entry) or an agent's harness label (only an entry
    it owns, :func:`owns_source`). ``update`` changes ``access`` and ``entity``
    in place (``entity=None``/``""`` clears the link); a new ``new_ref`` or
    ``new_predicate`` REPLACES the entry — the old key goes, the new one takes its
    place, ``added_by``/``added_at`` kept, ``verified`` dropped (another link).
    ``remove`` drops the entry and leaves a tombstone (``sources_removed:``) so a
    machine writer never puts it back; an agent must say why."""
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return ChangeResult("not_found", message=f"No page '{entity_id}'.")
    person = actor == USER
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    existing = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    key = (ref or "").strip()
    at = next((i for i, s in enumerate(existing)
               if str(s.get("ref", "")).strip() == key and same_predicate(s.get("predicate"), predicate)), None)
    if at is None:
        return ChangeResult("not_found", message="Nothing is listed there under that key.")
    entry = existing[at]
    if not person and not owns_source(entry, author=actor, origin=origin):
        return ChangeResult("not_yours", entry=dict(entry), message=(
            "That source was not added by this agent, so it can't be changed here. Add a corrected one, or let "
            "the person decide in the Cicada app."))
    try:
        if action == "remove":
            why = _clean_reason(reason)
            if not why and not person:
                return ChangeResult("refused", message="Say why it is being removed in `reason`.")
            existing.pop(at)
            _push_tombstone(fm, entry, by=USER if person else actor, reason=why)
            if existing:
                fm["sources"] = existing
            else:
                fm.pop("sources", None)
            markdown_parser.write(path, fm, parsed.body)
            return ChangeResult("removed", entry=dict(entry), message="removed")
        if action != "update":
            return ChangeResult("refused", message="action must be 'update' or 'remove'.")

        changed = False
        replaced = False
        updated = dict(entry)
        new_key_ref = (new_ref or "").strip() or key
        new_key_pred = entry.get("predicate") if new_predicate is None else (new_predicate.strip() or None)
        if new_key_ref != key or not same_predicate(new_key_pred, entry.get("predicate")):
            if new_key_ref != key:
                new_key_ref = clean_text(new_key_ref)
                kind_new = str(entry.get("kind") or "")
                if kind_new in (KIND_URL, KIND_PATH, KIND_NOTE, ""):
                    kind_new = infer_kind(new_key_ref)
                _validate(new_key_ref, kind_new, str(updated.get("access") or "") or None)
                if not person and kind_new == KIND_URL:
                    new_key_ref = new_key_ref.split("#", 1)[0]
                updated["kind"] = kind_new
            for i, other in enumerate(existing):
                if i != at and str(other.get("ref", "")).strip() == new_key_ref \
                        and same_predicate(other.get("predicate"), new_key_pred):
                    return ChangeResult("refused", message="Already listed under that key.")
            if not person and (tomb := find_tombstone(fm, new_key_ref, new_key_pred)) is not None \
                    and is_tombstoned(fm, new_key_ref, new_key_pred, via_agent=via_agent):
                return ChangeResult("refused", message=f"Not changed: {_removed_message(tomb)}.")
            if not person and not same_predicate(new_key_pred, entry.get("predicate")) and sum(
                    1 for i, s in enumerate(existing)
                    if i != at and same_predicate(s.get("predicate"), new_key_pred)) >= MAX_PER_PREDICATE:
                return ChangeResult("refused", message=(
                    "That fact already lists as many sources as it can hold; remove one that is no longer "
                    "relevant first."))
            updated["ref"] = new_key_ref
            if new_key_pred:
                updated["predicate"] = new_key_pred
            else:
                updated.pop("predicate", None)
            updated.pop("verified", None)
            if person:
                _clear_tombstone(fm, new_key_ref, new_key_pred)
            replaced = changed = True
        if access is not None and str(access).strip():
            value = str(access).strip().lower()
            _validate(str(updated["ref"]), str(updated.get("kind") or infer_kind(str(updated["ref"]))), value)
            if updated.get("access") != value:
                updated["access"] = value
                changed = True
        if entity is not _UNSET:
            if entity is None or not str(entity).strip():
                if "entity" in updated:
                    updated.pop("entity")
                    changed = True
            else:
                link = resolve_entity_link(memory_path, entity, self_id=entity_id)
                if updated.get("entity") != link:
                    updated["entity"] = link
                    changed = True
        if person and _apply_persons_fields(updated, None, accepted, bool(only_me)):
            changed = True
        if not changed:
            return ChangeResult("refused", entry=dict(entry), message="Nothing to change.")
        existing[at] = updated
        fm["sources"] = existing
        markdown_parser.write(path, fm, parsed.body)
        return ChangeResult("replaced" if replaced else "updated", entry=dict(updated), message="ok")
    except InvalidSource as exc:
        return ChangeResult("refused", entry=dict(entry), message=str(exc))


def voiced_hint(source: dict) -> str:
    """The conflict card's sentence for one source, in the voice of whoever added
    it (G61 phase 2 S0, spec §5.5, plan R-AC22).

    The minimal slice said "You said …" for every source, so an agent's suggestion
    and Cicada's own DOI lookup (``paper_metadata``) both read as the person's
    words. Now only ``user`` says "You said"; a harness is named through
    ``source_overview.HARNESS_LABELS`` (the one harness→name map; its ``unknown``
    bucket is not a name), ``cicada`` is Cicada, and anything else — a model id,
    ``agent`` — is "An agent". The ref stays in every sentence: the app finds its
    "Open source ↗" link by scanning the hint for a URL (``QuestionView.firstURL``)
    and the MCP render prints the hint as it is. An entry with no ``added_by`` is
    the person's — the wire model's default (``EntitySource.added_by``), and what
    a hand-written entry means.
    """
    ref = str(source.get("ref") or "").strip()
    # Round 4 (G154, R-SR16): a Contacts card is said as one, in words; the ref stays in the sentence (the app's
    # "Open source ↗" scans the hint for it).
    if ref.startswith("addressbook://"):
        return f"Their card in your Contacts ({ref}) is where to check this"
    who = str(source.get("added_by") or USER).strip() or USER
    if who == USER:
        return f"You said {ref} is where to check this"
    if who == CICADA:
        return f"Cicada found {ref} as where to check this"
    from api.services.source_overview import HARNESS_LABELS, UNKNOWN

    label = HARNESS_LABELS.get(who) if who != UNKNOWN else None
    if label:
        return f"{label} added {ref} as where to check this"
    return f"An agent found {ref} as where to check this"


def silenced(sources, predicate: str | None) -> bool:
    """True when the person marked this predicate "Only I know" (``only_me``).

    That note is a silence for the fact, not just a skipped entry: without this,
    ``hint_from`` fell through to another predicate's URL and ``served_hint`` to
    the stored pre-S0 sentence, so a card whose ``check`` said ``only_me`` still
    read "You said <url> is where to check this" (spec §4.2 clamp 6 / §5.5; G61
    final review, finding 3). Only the person's own note silences — an agent
    cannot mute a fact on their behalf.
    """
    want = str(predicate or "").strip().lower()
    if not want:
        return False
    return any(
        s.get("only_me")
        and (str(s.get("added_by") or USER).strip() or USER) == USER
        and same_predicate(s.get("predicate"), want)
        for s in as_sources(sources)
    )


def hint_from(sources, predicate: str | None) -> str | None:
    """Which source refreshes this fact, voiced — pure over a ``sources:`` value.

    Prefers a source whose ``predicate`` matches — of ANY kind, a predicate-
    matched ``note`` included, since someone pointed at it for exactly this
    fact. With no predicate match, falls back to the first ``url`` source; a
    bare ``note`` with no matching predicate yields no hint. An "Only I know"
    note (``only_me``, S1) is a silence, never a hint.
    """
    if silenced(sources, predicate):
        return None
    usable = [s for s in as_sources(sources) if not s.get("only_me")]
    want = str(predicate or "").strip().lower()
    match = next(iter(rank(usable, want)), None)
    if match is None:
        match = next((s for s in usable if s.get("kind") == KIND_URL), None)
    return voiced_hint(match) if match is not None else None


def hint_for(memory_path: Path, entity_id: str, predicate: str | None) -> str | None:
    """:func:`hint_from` over the entity page on disk."""
    return hint_from(list_sources(memory_path, entity_id), predicate)


def served_hint(item_fm: dict, sources) -> str | None:
    """The ``hint`` an inbox item is SERVED with — one rule for the wire
    (``inbox_service._item_from_file``), the MCP render
    (``mcp_tools._agent_question``) and the lexical row
    (``search_index._index_inbox``). G61 phase 2 S0, spec §5.5, plan R-AC23.

    A ``conflict`` derives it from the subject's CURRENT ``sources:``, so a
    source added after the question opened reaches the card at once; nothing is
    written, and no ETag moves that did not already (``/inbox`` ETags over
    ``entities``). An item written before this slice whose sources no longer
    match keeps the sentence it stored. Every other kind serves what it stored,
    untouched — a bookmark ``removal`` stores its own "Also saved via <origin>"
    (``bookmark_sync``).
    """
    stored = str(item_fm.get("hint") or "").strip() or None
    if str(item_fm.get("kind") or "") != "conflict":
        return stored
    predicate = str(item_fm.get("predicate") or "").strip() or "description"
    if silenced(sources, predicate):
        return None
    derived = hint_from(sources, predicate)
    return derived if derived is not None else stored


def is_refused_host(ref: str) -> bool:
    """A host Cicada never reads on its own (ToS rail): LinkedIn, Instagram,
    YouTube/video, arXiv and DOI pages — ``link_enrichment._excluded_media``,
    which folds in ``papers.never_scraped``. One list, so the fetch path and the
    check path can never disagree (D-AC2: such a source is inform-only)."""
    from api.services.link_enrichment import _excluded_media

    return _excluded_media(ref, "")


def effective_access(source: dict) -> str:
    """The access a source needs, derived at read (plan R-AC27, spec §5.1).

    A valid stored value wins — the person can say "this page needs my login".
    Otherwise: a path or a repo is ``local``; an app is ``signed_in``; a ``url``
    on a refused host, or one ``link_enrichment.classify_page`` flags as a login
    or consent page, is ``signed_in``; any other url and every note is
    ``unknown`` — S4's one rung-1 attempt is what turns ``unknown`` into
    ``public`` or ``signed_in``. Zero network: host and path only.
    """
    stored = str(source.get("access") or "").strip().lower()
    if stored in ACCESS_VALUES:
        return stored
    ref = str(source.get("ref") or "").strip()
    kind = str(source.get("kind") or infer_kind(ref))
    if kind in LOCAL_KINDS:
        return ACCESS_LOCAL
    if kind == KIND_APP:
        return ACCESS_SIGNED_IN
    if kind == KIND_URL:
        from api.services.link_enrichment import classify_page

        if is_refused_host(ref) or classify_page("", ref) is not None:
            return ACCESS_SIGNED_IN
    return ACCESS_UNKNOWN


def urls_in(text: str) -> list[str]:
    """Every http(s) URL in ``text``, in order, deduplicated, trailing
    punctuation stripped."""
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(_URL_TRAIL)
        if url and url not in out:
            out.append(url)
    return out


def attach_cited_urls(memory_path: Path, subject: str, claim, locus_of) -> list[str]:
    """Stage 5.56: a link the claim's OWN cited words contain becomes a source for
    that fact (G61 phase 2 S1, spec §5.2, plan R-AC33).

    A regex over text the claim already cites — zero LLM, no prompt change, and
    never a URL Stage 1 invented or completed. Only a ``world`` or ``artifact``
    predicate (a page cannot say what someone prefers); only a real span, never a
    ``reasoning`` entry, and never a stale one (``evidence.span_status``: the
    offsets must still point at the words they were minted on); at most
    :data:`MAX_CITED_URLS`. ``added_by`` is the claim's stamped author — a model
    id — so the hint says "An agent found …" and the source is not settle-grade
    until the person accepts it (spec §4.3). Returns the refs it attached.
    """
    if locus_of(getattr(claim, "predicate", "")) not in ("world", "artifact"):
        return []
    from api.services import evidence

    found: list[str] = []
    for ev in getattr(claim, "evidence", None) or []:
        if not ev.is_span():
            continue
        text = evidence.source_text(memory_path, ev.episode)
        if text is None or ev.end > len(text):
            continue
        if evidence.span_status(text, end=ev.end, hash=ev.hash,
                                appendable=evidence.is_episode_id(ev.episode)) == evidence.SPAN_STALE:
            continue
        for url in urls_in(text[ev.start:ev.end]):
            if url not in found:
                found.append(url)
    attached: list[str] = []
    for url in found[:MAX_CITED_URLS]:
        try:
            if add_source(memory_path, subject, url, kind=KIND_URL, predicate=claim.predicate,
                          added_by=claim.authored_by or "agent") is not None:
                attached.append(url)
        except InvalidSource:
            continue
    return attached


MAX_AGENT_SOURCES = 10


def agent_items(raw, *, remote: bool = False) -> list[tuple[str, str | None]]:
    """``cicada_write_claim(sources=…)`` as ``(ref, access)`` pairs (G61 phase 2
    S1, spec §5.3, plan R-AC30): a bare string — the minimal slice's form — or
    ``{ref, access?}``.

    Anything else (no ref, a number, a ref over :data:`MAX_REF_CHARS`) is
    dropped, and an ``access`` the record does not allow for that ref falls back
    to inference: the claim beside it is already written, and a malformed source
    must never turn that write into an error (provenance never blocks memory). A
    remote caller's path or repo is dropped — a cloud app never names a file on
    this Mac (R-AC31). At most :data:`MAX_AGENT_SOURCES`.
    """
    out: list[tuple[str, str | None]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, str):
            ref, access = item.strip(), None
        elif isinstance(item, dict):
            ref = str(item.get("ref") or "").strip()
            access = str(item.get("access") or "").strip().lower() or None
        else:
            continue
        if not ref or len(ref) > MAX_REF_CHARS:
            continue
        kind = infer_kind(ref)
        if remote and kind in LOCAL_KINDS:
            continue
        if access not in ACCESS_VALUES or (access == ACCESS_LOCAL and (remote or kind not in LOCAL_KINDS)):
            access = None
        out.append((ref, access))
        if len(out) >= MAX_AGENT_SOURCES:
            break
    return out
