"""The skill hold — Stage-4 skills grounded on ONE conversation, waiting for a second (G112, owner ruling 2026-10-09).

``<bank>/pending_skills.jsonl``, one JSON object per line, keyed by the page id the skill would get
(``sanitize_id(name)``): ``{slug, name, description, confidence, source_episode, evidence_ids}``. A new skill page needs
two or more conversations, the bar entity promotion sets; a skill seen in one is parked here instead of being written
or dropped, and the batch that grounds it on another conversation writes the page citing both and removes the line
(``skill_grounding``).

**Its own file, not ``pending_entities.jsonl``.** That store is keyed by name alone and Stage 2 promotes any line whose
name a Stage-1 entity repeats — under the entity's own type, crediting only the new conversation, and deleting the line.
A held skill sharing it would be turned into a concept or tool page and lose its description and first conversation;
and a skill create taking a same-named Stage-1 line would drop the history, description and tags that line held. Two
key spaces cannot consume each other's lines. The cost: a Stage-1 mention of the same name does not count toward a
skill's bar (a name heard is not the pattern seen), and claims about a held skill's name are not held with it — as
before this hold existed.

Not derived: deleting it costs a conversation's worth of evidence, so it is tracked in the bank's git and committed by
the cycle that changed it, like the pending store. Written only by Sleep's Stage 5 (``skill_grounding.settle``), after
the pages; every read-modify-write is under one lock and every save is atomic. Nothing expires a line, so a skill seen
in batch 3 and again in batch 9 meets the bar.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from api.services.id_utils import sanitize_id

HOLD_FILE = "pending_skills.jsonl"
_LOCK = threading.Lock()


@dataclass
class HeldSkill:
    name: str
    description: str
    confidence: float
    source_episode: str
    evidence_ids: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return sanitize_id(self.name)

    def to_dict(self) -> dict:
        return {"slug": self.slug, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict) -> "HeldSkill":
        try:
            confidence = float(data.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        return cls(name=str(data.get("name") or ""), description=str(data.get("description") or ""),
                   confidence=confidence, source_episode=str(data.get("source_episode") or ""),
                   evidence_ids=[str(e) for e in data.get("evidence_ids") or [] if e])


def hold_path(memory_path: Path) -> Path:
    return Path(memory_path) / HOLD_FILE


def load(memory_path: Path) -> list[HeldSkill]:
    """Every readable line, in file order; a line that is not JSON or has no name is skipped."""
    path = hold_path(memory_path)
    if not path.exists():
        return []
    out: list[HeldSkill] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            held = HeldSkill.from_dict(json.loads(line))
        except (ValueError, AttributeError):
            continue
        if held.name and held.source_episode:
            out.append(held)
    return out


def _save(memory_path: Path, entries: list[HeldSkill]) -> None:
    """Replace the file atomically; a failed write leaves the old file and no stray temp file (the next
    ``git add -A`` would commit it)."""
    path = hold_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(e.to_dict(), ensure_ascii=False) + "\n" for e in entries)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".pending_skills-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def settle(memory_path: Path, hold: Iterable[HeldSkill], release: Iterable[str]) -> tuple[int, int]:
    """One read-modify-write: drop the lines whose slug is in ``release``, then add or replace (by slug) each of
    ``hold``. Writes nothing when nothing changes. Returns ``(held, released)``."""
    hold = list(hold)
    gone = set(release)
    if not hold and not gone:
        return 0, 0
    with _LOCK:
        entries = load(memory_path)
        kept = [e for e in entries if e.slug not in gone]
        released = len(entries) - len(kept)
        new = {h.slug: h for h in hold}
        kept = [e for e in kept if e.slug not in new] + list(new.values())
        if kept != entries:
            _save(memory_path, kept)
        return len(new), released
