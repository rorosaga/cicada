"""Which model answered a turn, and how hard it thought — the two agent-turn
facts a capture may keep (round 4 D1, contract C1; G49's reservation lifted for
harness writes, TODO ruling 11).

A leaf on purpose, standard library only: the writers (`transcript_extract`,
`episode_staging`) and the readers (`turn_authorship`, `provenance`) share ONE
vocabulary, and the read paths must never import the transcript extractor
(`test_the_provenance_module_is_engine_free`). `evidence.turn_stamps` stays the
reader of `ts`/`speaker`; `stamps` here is the tolerant reader of the whole
entry, the two new keys included.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: The reasoning-effort words the harnesses write (Claude Code's top-level
#: `effort`, the Stop hook's `effort.level`, Codex's `turn_context.payload.effort`).
#: Anything else is dropped, never mapped (R4B-2).
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
# A model id looks like one: `claude-opus-5-5`, `gpt-5.5-codex`, `openrouter/x/y`.
# The first character rules out Claude Code's `<synthetic>` marker for a
# message no model produced (R4B-2).
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-\[\]]{0,127}$")


def clean_model(value) -> str | None:
    """The raw model id, or None when it does not look like one."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _MODEL_RE.match(text) else None


def clean_effort(value) -> str | None:
    """One of :data:`EFFORTS`, lower-cased, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if text in EFFORTS else None


@dataclass(frozen=True)
class Stamp:
    """One `turns` sidecar entry (R-PB4 + C1), cleaned. `model`/`effort` are
    None on every entry that is not an agent's."""

    offset: int
    ts: str | None
    speaker: str | None
    model: str | None = None
    effort: str | None = None


def stamps(frontmatter: dict | None) -> list[Stamp]:
    """The sidecar, ascending by offset. Tolerant like `evidence.turn_stamps`: a
    pre-PJ-4 integer count reads as no stamps, and a malformed or duplicate
    entry is skipped, never raised — a hand-edited episode must never fail a read."""
    raw = (frontmatter or {}).get("turns")
    if not isinstance(raw, list):
        return []
    out: dict[int, Stamp] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            offset = int(entry.get("offset"))
        except (TypeError, ValueError):
            continue
        if offset < 0 or offset in out:
            continue
        speaker = str(entry.get("speaker") or "") or None
        agent = speaker == "assistant"
        ts = entry.get("ts")
        out[offset] = Stamp(offset=offset, ts=str(ts) if ts not in (None, "") else None, speaker=speaker,
                            model=clean_model(entry.get("model")) if agent else None,
                            effort=clean_effort(entry.get("effort")) if agent else None)
    return [out[k] for k in sorted(out)]
