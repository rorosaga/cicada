"""Where a merged-away page went: old ids keep resolving after a merge or a rename (G227 follow-up, owner 2026-10-29).

A merge deletes the loser's page and a keep-the-cleaner-name answer renames one; before this, an id held anywhere
outside the bank's own pages — an agent's note, a link the person copied, an inbox item, a conversation that named it
— resolved to nothing. ``<memory>/_redirects.yaml`` holds ``{"redirects": {old_id: new_id}}``, written by the one merge
primitive (``entity_merge.merge_entities``) and the one rename (``entity_merge.rename_references``), so every door that
merges or renames leaves one, and committed with that change (it is in the change's paths), so an undo takes it back.

**Reading** (:func:`resolve`): a page that exists always wins — a redirect is only consulted for an id with no page —
and a chain is followed to its end (at most :data:`MAX_HOPS`), never round a loop. ``id_utils.resolve_entity_file``
falls back on it, so every MCP tool, the CLI and the app's card resolve an old id to the page it became. Cached on
the file's (inode, mtime, size): one ``stat`` per call when nothing changed.

**Writing** (:func:`add`): ``old → new``; an entry that pointed at ``old`` now points at ``new`` (flat, so a read is
one hop), and ``new``'s own entry, if any, is dropped (it is a page again). Atomic (``markdown_parser.write_yaml``).
Engine-free; never raises on a read.
"""
from __future__ import annotations

import threading
from pathlib import Path

FILE = "_redirects.yaml"
MAX_HOPS = 8

_cache: dict[str, tuple[tuple[int, int, int], dict[str, str]]] = {}
_lock = threading.Lock()


def path(memory_path) -> Path:
    return Path(memory_path) / FILE


def _stamp(p: Path) -> tuple[int, int, int] | None:
    try:
        st = p.stat()
    except OSError:
        return None
    return st.st_ino, st.st_mtime_ns, st.st_size


def load(memory_path) -> dict[str, str]:
    """``{old_id: new_id}`` as stored; ``{}`` for no file or one that cannot be read."""
    p = path(memory_path)
    stamp = _stamp(p)
    if stamp is None:
        return {}
    with _lock:
        hit = _cache.get(str(p))
    if hit is not None and hit[0] == stamp:
        return dict(hit[1])
    from api.services import markdown_parser

    try:
        data = markdown_parser.load_yaml(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — an unreadable file redirects nothing
        data = {}
    raw = data.get("redirects") if isinstance(data, dict) else None
    out = {str(k): str(v) for k, v in (raw or {}).items() if isinstance(k, str) and isinstance(v, str) and k != v} \
        if isinstance(raw, dict) else {}
    with _lock:
        _cache[str(p)] = (stamp, out)
    return dict(out)


def resolve(memory_path, entity_id: str) -> str | None:
    """The page ``entity_id`` became, when it has no page of its own and a redirect names one that exists; else
    ``None``."""
    eid = str(entity_id or "").strip()
    if not eid or "/" in eid or len(eid) > 200:
        return None   # never a path, never a sentence someone passed as a name
    table = load(memory_path)
    if eid not in table:
        return None   # the common case: one stat of the table, no page probe
    ents = Path(memory_path) / "entities"
    if _is_page(ents, eid):
        return None
    seen = {eid}
    current = eid
    for _ in range(MAX_HOPS):
        nxt = table.get(current)
        if nxt is None or nxt in seen:
            break
        seen.add(nxt)
        current = nxt
        if _is_page(ents, current):
            return current
    return None


def _is_page(ents: Path, eid: str) -> bool:
    try:
        return (ents / f"{eid}.md").is_file()
    except OSError:
        return False


def add(memory_path, old_id: str, new_id: str) -> bool:
    """Record ``old_id → new_id``. Returns whether the file changed (the caller commits :data:`FILE` then)."""
    from api.services import markdown_parser

    old, new = str(old_id or "").strip(), str(new_id or "").strip()
    if not old or not new or old == new:
        return False
    table = load(memory_path)
    before = dict(table)
    table = {k: (new if v == old else v) for k, v in table.items()}
    table.pop(new, None)
    table[old] = new
    table = {k: v for k, v in table.items() if k != v}
    if table == before:
        return False
    markdown_parser.write_yaml(path(memory_path), {"redirects": dict(sorted(table.items()))})
    return True


def reverse(current: bytes | None, after: bytes | None, before: bytes | None) -> bytes | None:
    """``current`` with one change ``before → after`` taken back by meaning (an undo): the entries that change added
    are removed and the ones it removed or repointed are put back, anything written since stays. ``None`` when a side
    cannot be read."""
    import yaml

    def table(raw: bytes | None) -> dict | None:
        if raw is None:
            return {}
        try:
            data = yaml.safe_load(raw.decode("utf-8")) or {}
        except (yaml.YAMLError, UnicodeDecodeError):
            return None
        value = data.get("redirects") if isinstance(data, dict) else None
        return dict(value) if isinstance(value, dict) else {}

    b, a, c = table(before), table(after), table(current)
    if b is None or a is None or c is None:
        return None
    for key, value in a.items():
        if b.get(key) != value and c.get(key) == value:
            c.pop(key)
    for key, value in b.items():
        if a.get(key) != value and key not in c:
            c[key] = value
    return yaml.safe_dump({"redirects": dict(sorted(c.items()))}, allow_unicode=True, sort_keys=False).encode("utf-8")


def invalidate() -> None:
    with _lock:
        _cache.clear()
