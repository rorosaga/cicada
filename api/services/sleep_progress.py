"""Engine-free counts a run reports about the bank (Sleep page v5).

Frontmatter only, through the cached ``bank_index`` — never a body, never an
engine, never a directory walk per SSE tick (callers compute these at a run's start,
at batch boundaries and at its end, and the stream reads the cached values).
Ids, counts and enums only.
"""
from __future__ import annotations

from pathlib import Path

from api.services import bank_index, claims, markdown_parser


def owner_beliefs(memory_path: Path) -> int | None:
    """How many current beliefs the owner's page holds, or ``None`` when the bank
    has no page marked ``owner: true`` (a run never creates one — G169 owns that)."""
    entities = bank_index.files(memory_path, "entities")
    for f in entities:
        if f.frontmatter.get("owner") is True:
            try:
                body = markdown_parser.parse(f.path).body
                rows = claims.parse_claims(body)
            except Exception:
                return 0
            return sum(1 for c in rows if c.valid_to is None and not claims.is_record(c))
    return None


def origin_of_ids(memory_path: Path, ids) -> dict[str, str]:
    """Each id's harness-normalised origin, from frontmatter alone."""
    from api.services.sleep_cycle import _derive_origin

    want = set(ids)
    out: dict[str, str] = {}
    for f in bank_index.files(memory_path, "episodes"):
        ep_id = str(f.frontmatter.get("id", f.stem))
        if ep_id in want:
            out[ep_id] = str(f.frontmatter.get("origin") or _derive_origin(f.frontmatter.get("source")))
    return out


def unprocessed_ids(memory_path: Path) -> dict[str, str]:
    """Every waiting episode id -> its origin (one cached frontmatter pass)."""
    from api.services.sleep_cycle import _derive_origin

    out: dict[str, str] = {}
    for f in bank_index.files(memory_path, "episodes"):
        if f.frontmatter.get("processed", False):
            continue
        out[str(f.frontmatter.get("id", f.stem))] = str(
            f.frontmatter.get("origin") or _derive_origin(f.frontmatter.get("source")))
    return out


def new_since_by_origin(waiting: dict[str, str], frozen: set[str]) -> dict[str, int]:
    """Waiting episodes that were not in the frozen list, per origin."""
    out: dict[str, int] = {}
    for i, o in waiting.items():
        if i not in frozen:
            out[o] = out.get(o, 0) + 1
    return out
