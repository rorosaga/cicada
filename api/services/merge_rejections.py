"""G113 — remembered "these are NOT the same entity" rulings.

``<memory>/_merge_rejected.yaml`` holds sorted ``[a, b]`` slug pairs. A pair the
user rejected is never re-proposed by ``clarification_manager.create`` (Sleep's
duplicate clarifications) or ``dedup_sweep`` (the maintenance sweep). Fuzzy
mention resolution in ``entity_resolver`` is deliberately NOT consulted here —
it resolves mentions to pages, it does not propose merges.
"""
from __future__ import annotations

from pathlib import Path

import yaml

FILE = "_merge_rejected.yaml"


def _pair(a: str, b: str) -> tuple[str, str]:
    x, y = sorted((str(a or "").strip(), str(b or "").strip()))
    return x, y


#: G227 follow-up (owner 2026-10-29): two PAGES the person split apart. Kept beside ``rejected`` and read apart from
#: it, because a ``rejected`` pair is also read as "this NAME is not that page" (`entity_resolver._rejected_pair`): a
#: split leaves two pages under one title, and the name must still be able to reach either of them. A split pair keeps
#: the PAGES apart — never proposed, swept or settled as duplicates (`kept_apart`) — and nothing else.
SPLIT_KEY = "split"


def _read(memory_path: Path) -> dict:
    p = Path(memory_path) / FILE
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _pairs(data: dict, key: str) -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for row in data.get(key) or []:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            out.add(_pair(row[0], row[1]))
    return out


def _write(memory_path: Path, data: dict) -> Path:
    p = Path(memory_path) / FILE
    out = {"rejected": [list(x) for x in sorted(_pairs(data, "rejected"))]}
    split = sorted(_pairs(data, SPLIT_KEY))
    if split:
        out[SPLIT_KEY] = [list(x) for x in split]
    for key, value in data.items():   # anything another writer keeps here stays
        if key not in out and key not in ("rejected", SPLIT_KEY):
            out[key] = value
    p.write_text(yaml.safe_dump(out, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def load_rejected(memory_path: Path) -> set[tuple[str, str]]:
    return _pairs(_read(memory_path), "rejected")


def load_split(memory_path: Path) -> set[tuple[str, str]]:
    return _pairs(_read(memory_path), SPLIT_KEY)


def kept_apart(memory_path: Path) -> set[tuple[str, str]]:
    """Every pair of PAGES never to be joined as duplicates: the person's "different" answers and their splits."""
    data = _read(memory_path)
    return _pairs(data, "rejected") | _pairs(data, SPLIT_KEY)


def is_rejected(memory_path: Path, a: str, b: str) -> bool:
    return _pair(a, b) in load_rejected(memory_path)


def is_split(memory_path: Path, a: str, b: str) -> bool:
    return _pair(a, b) in load_split(memory_path)


def add_rejected(memory_path: Path, a: str, b: str) -> Path:
    data = _read(memory_path)
    data["rejected"] = [list(x) for x in _pairs(data, "rejected") | {_pair(a, b)}]
    return _write(memory_path, data)


def add_split(memory_path: Path, a: str, b: str) -> Path:
    data = _read(memory_path)
    data[SPLIT_KEY] = [list(x) for x in _pairs(data, SPLIT_KEY) | {_pair(a, b)}]
    return _write(memory_path, data)


def clear_pairs(memory_path: Path, pairs) -> bool:
    """The person joined these: every listed pair leaves both lists. Returns whether the file changed."""
    gone = {_pair(a, b) for a, b in pairs}
    data = _read(memory_path)
    rejected, split = _pairs(data, "rejected"), _pairs(data, SPLIT_KEY)
    if not (gone & rejected or gone & split):
        return False
    data["rejected"] = [list(x) for x in rejected - gone]
    data[SPLIT_KEY] = [list(x) for x in split - gone]
    _write(memory_path, data)
    return True
