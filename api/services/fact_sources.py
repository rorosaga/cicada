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
        kind: url              # url | path | note
        predicate: works-at    # optional — which fact this refreshes
        added_by: user         # user | <harness label> | cicada | <model id>
        added_at: '2026-08-30'

G61 phase 2 S0 (spec ``docs/superpowers/specs/2026-09-23-g61-agent-first-clarification-design.md``
§5.5; plan ``docs/superpowers/plans/2026-09-23-g61-s0-s2.md``): an entry is keyed
on ``(ref, predicate)`` so one link can serve two facts, and a conflict card's
``hint`` is DERIVED at read (:func:`served_hint`) instead of being written into
the item — a source added after a question opened reaches the card at once — in
a voice that says who added it. This module never FETCHES anything.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from api.services import markdown_parser

KIND_URL = "url"
KIND_PATH = "path"
KIND_NOTE = "note"

USER = "user"
CICADA = "cicada"


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


def add_source(
    memory_path: Path,
    entity_id: str,
    ref: str,
    *,
    kind: str | None = None,
    predicate: str | None = None,
    added_by: str = USER,
    added_at: str | None = None,
) -> dict | None:
    """Append one source to the entity's ``sources:`` key. Idempotent on
    ``(ref, predicate)``.

    G61 phase 2 S0 (spec §5.1, plan R-AC20): the same link may be where to check
    two different facts — a team page for ``works-at`` and for ``located-in`` —
    and keying on ``ref`` alone silently dropped the second. A repeat returns the
    STORED entry unchanged: the first adder keeps the credit, and the voice the
    hint speaks in.

    Returns the stored dict, or ``None`` when the ref is blank or the entity
    does not exist. Every other frontmatter key and the body are untouched.
    """
    text = (ref or "").strip()
    if not text:
        return None
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return None

    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    existing = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    for source in existing:
        if str(source.get("ref", "")).strip() == text and same_predicate(source.get("predicate"), predicate):
            return dict(source)

    entry: dict = {"ref": text, "kind": (kind or infer_kind(text))}
    if predicate:
        # `predicate` sits between kind and added_by for readability.
        entry["predicate"] = predicate
    entry["added_by"] = added_by or USER
    entry["added_at"] = added_at or str(date.today())

    fm["sources"] = existing + [entry]
    markdown_parser.write(path, fm, parsed.body)
    return entry


def delete_source(memory_path: Path, entity_id: str, index: int) -> bool:
    """Remove the source at ``index``. Returns whether anything was removed.

    Removing the last source drops the ``sources:`` key entirely, so an entity
    that never had one stays byte-identical.
    """
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return False
    parsed = markdown_parser.parse(path)
    fm = parsed.frontmatter
    existing = [s for s in (fm.get("sources") or []) if isinstance(s, dict)]
    if index < 0 or index >= len(existing):
        return False
    existing.pop(index)
    if existing:
        fm["sources"] = existing
    else:
        fm.pop("sources", None)
    markdown_parser.write(path, fm, parsed.body)
    return True


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


def hint_from(sources, predicate: str | None) -> str | None:
    """Which source refreshes this fact, voiced — pure over a ``sources:`` value.

    Prefers a source whose ``predicate`` matches — of ANY kind, a predicate-
    matched ``note`` included, since someone pointed at it for exactly this
    fact. With no predicate match, falls back to the first ``url`` source; a
    bare ``note`` with no matching predicate yields no hint.
    """
    usable = as_sources(sources)
    want = str(predicate or "").strip().lower()
    match = next((s for s in usable if want and same_predicate(s.get("predicate"), want)), None)
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
    derived = hint_from(sources, str(item_fm.get("predicate") or "").strip() or "description")
    return derived if derived is not None else stored
