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


def load_rejected(memory_path: Path) -> set[tuple[str, str]]:
    p = Path(memory_path) / FILE
    if not p.exists():
        return set()
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return set()
    out: set[tuple[str, str]] = set()
    for row in (data.get("rejected") or []) if isinstance(data, dict) else []:
        if isinstance(row, (list, tuple)) and len(row) == 2:
            out.add(_pair(row[0], row[1]))
    return out


def is_rejected(memory_path: Path, a: str, b: str) -> bool:
    return _pair(a, b) in load_rejected(memory_path)


def add_rejected(memory_path: Path, a: str, b: str) -> Path:
    pairs = load_rejected(memory_path)
    pairs.add(_pair(a, b))
    p = Path(memory_path) / FILE
    p.write_text(
        yaml.safe_dump({"rejected": [list(x) for x in sorted(pairs)]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return p
