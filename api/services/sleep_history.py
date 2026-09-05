"""Pure helpers for the Sleep page's consolidation history (G125 R4/R5)."""
from __future__ import annotations

from pathlib import Path

from api.services import bank_index


def attach_durations(entries, events) -> None:
    """Join `sleep_run` ledger rows onto history entries by `refs.commit` —
    a full-hash prefix match either way, ≥ 7 chars. No match → ``None`` (R5)."""
    runs = [(str(e.refs.get("commit") or ""), e.duration_ms) for e in events
            if getattr(e, "kind", "") == "sleep_run" and e.duration_ms is not None and e.refs.get("commit")]
    for entry in entries:
        h = entry.commit_hash
        for ref, ms in runs:
            if len(ref) >= 7 and (h.startswith(ref) or ref.startswith(h)):
                entry.duration_ms = int(ms)
                break


def episodes_by_origin(memory_path: Path, ep_ids: list[str]) -> dict[str, int]:
    """Resolve `source: ep_…` refs to their `origin` through the bank index
    (engine-free; a missing page counts as `unknown`)."""
    from api.services.sleep_cycle import _derive_origin

    wanted = set(ep_ids)
    by_id: dict[str, str] = {}
    for f in bank_index.files(Path(memory_path), "episodes"):
        fm = f.frontmatter or {}
        eid = str(fm.get("id") or f.path.stem)
        if eid in wanted:
            by_id[eid] = str(fm.get("origin") or _derive_origin(fm.get("source")))
    out: dict[str, int] = {}
    for eid in ep_ids:
        origin = by_id.get(eid, "unknown")
        out[origin] = out.get(origin, 0) + 1
    return out
