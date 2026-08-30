"""G61 — the entity ``sources:`` key: *where to look a fact up*.

Distinct from two neighbours it is easy to confuse:

- ``source_episodes`` (frontmatter) is **provenance** — where a belief CAME from.
- ``api/services/entity_sources.py`` resolves those episodes back to whole
  conversations. Different concept, different module; this one is ``fact_sources``.
- The body's ``## Links`` section is a loose bookmark list.

A *source* is a cheat-sheet for REFRESHING a specific fact: a URL, a local path,
or a plain-English instruction ("ask me — I announce job changes"). Stored as::

    sources:
      - ref: https://www.linkedin.com/in/rodrigo
        kind: url              # url | path | note
        predicate: works-at    # optional — which fact this refreshes
        added_by: user         # model id, or "user"
        added_at: '2026-08-30'

This slice never FETCHES anything (that is the G61 follow-up); it stores, lists,
deletes, and produces the conflict-card ``hint``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from api.services import markdown_parser

KIND_URL = "url"
KIND_PATH = "path"
KIND_NOTE = "note"


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


def list_sources(memory_path: Path, entity_id: str) -> list[dict]:
    """The entity's declared sources, in file order. ``[]`` when absent."""
    path = _entity_path(memory_path, entity_id)
    if not path.exists():
        return []
    try:
        fm = markdown_parser.parse(path).frontmatter
    except Exception:
        return []
    raw = fm.get("sources") or []
    return [dict(s) for s in raw if isinstance(s, dict) and s.get("ref")]


def add_source(
    memory_path: Path,
    entity_id: str,
    ref: str,
    *,
    kind: str | None = None,
    predicate: str | None = None,
    added_by: str = "user",
    added_at: str | None = None,
) -> dict | None:
    """Append one source to the entity's ``sources:`` key. Idempotent on ``ref``.

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
        if str(source.get("ref", "")).strip() == text:
            return dict(source)

    entry: dict = {
        "ref": text,
        "kind": (kind or infer_kind(text)),
        "added_by": added_by or "user",
        "added_at": added_at or str(date.today()),
    }
    if predicate:
        # `predicate` sits between kind and added_by for readability.
        entry = {
            "ref": entry["ref"],
            "kind": entry["kind"],
            "predicate": predicate,
            "added_by": entry["added_by"],
            "added_at": entry["added_at"],
        }

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


def hint_for(memory_path: Path, entity_id: str, predicate: str | None) -> str | None:
    """The conflict-card hint: which source refreshes this fact (§2.5).

    Prefers a source whose ``predicate`` matches — of ANY kind, a predicate-
    matched ``note`` included, since the user pointed at it for exactly this
    fact. With no predicate match, falls back to the first ``url`` source; a
    bare ``note`` with no matching predicate yields no hint.
    """
    sources = list_sources(memory_path, entity_id)
    if not sources:
        return None
    want = (predicate or "").strip().lower()
    match = next(
        (s for s in sources if str(s.get("predicate", "") or "").strip().lower() == want and want),
        None,
    )
    if match is None:
        match = next((s for s in sources if s.get("kind") == KIND_URL), None)
    if match is None:
        return None
    return f"You said {match['ref']} is where to check this"
