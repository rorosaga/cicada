"""Transactional Stage 2 (Devin PR #27 round 1, CRITICAL).

`entity_resolver.resolve` used to write clarification files and mutate the
pending-entity index INLINE, interleaved with the per-name judging loop —
before `sleep_cycle` ever got to check `cancel_check()` and discard the
returned graph changes. A cancel after even one name had already left those
side effects behind: a dirty bank (the exact thing "cancel must never leave
a dirty bank" is supposed to prevent), and worse, `check_organic_resolution`
could permanently DELETE an inbox item whose corresponding entity update
never reached Stage 5 — silent data loss on an action advertised as safe.

These tests cancel mid-Stage-2 AFTER at least one name has been judged and
assert directly: the bank is clean, no clarification file was written, and
no inbox item was deleted. A REAL `ClarificationManager` (real file I/O
under a temp bank) proves the file-level claims; a spy in place of
`SqliteVecIndexer` proves no index write happened either, without touching
real embeddings (`rebuild_pending_index` would otherwise need one).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

from api.services import entity_resolver, markdown_parser
from api.services.clarification_manager import ClarificationManager


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _init_bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    (memory / "inbox").mkdir(parents=True)
    # Git doesn't track empty directories — a placeholder file so the seed
    # commit below actually has something to commit.
    (memory / ".gitkeep").write_text("")
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


def _settings(memory: Path) -> SimpleNamespace:
    return SimpleNamespace(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        sleep_promotion_threshold=2,
    )


def _seed_existing_entity(memory: Path, entity_id: str, name: str) -> dict:
    """A resolvable existing entity page — real file, real git commit — so
    `_find_direct_candidate_match` finds it with no LLM call."""
    filepath = memory / "entities" / f"{entity_id}.md"
    markdown_parser.write(filepath, {"id": entity_id, "name": name, "confidence": 0.8}, "body")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", f"seed entity {entity_id}")
    return {"id": entity_id, "frontmatter": {"name": name, "confidence": 0.8}, "body": "body", "filepath": filepath}


def _seed_pending_clarification(memory: Path, entity_name: str) -> str:
    """A real, committed pending clarification — real file I/O via the same
    `ClarificationManager` Stage 2 itself uses, so the dedup/id-numbering
    logic is exercised identically to production."""
    clarifier = ClarificationManager(memory)
    clar_id = clarifier.create(
        entity_name=entity_name,
        source_episode="ep_prior",
        uncertainty_type="Unknown relationship details",
        suggested_classification="person — unclear",
        suggested_confidence=0.4,
        source_context="mentioned once before",
    )
    assert clar_id is not None
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", f"seed clarification {clar_id}")
    return clar_id


class _SpyIndexer:
    """Stands in for `SqliteVecIndexer` — records every call, never touches
    real embeddings (`rebuild_pending_index` would otherwise need one)."""

    def __init__(self, *_a, **_k) -> None:
        self.pending: dict[str, object] = {}
        self.calls: list[tuple[str, str | None]] = []

    def pending_by_name(self, name: str):
        self.calls.append(("pending_by_name", name))
        return self.pending.get(name.lower())

    def index_pending_entity(self, entity) -> None:
        self.calls.append(("index_pending_entity", entity.name))
        self.pending[entity.name.lower()] = entity

    def promote_from_pending(self, name: str):
        self.calls.append(("promote_from_pending", name))
        return self.pending.pop(name.lower(), None)

    def rebuild_pending_index(self) -> int:
        self.calls.append(("rebuild_pending_index", None))
        return len(self.pending)


def _install_spy_indexer(monkeypatch) -> _SpyIndexer:
    spy = _SpyIndexer()
    monkeypatch.setattr(entity_resolver, "SqliteVecIndexer", lambda *a, **k: spy)
    return spy


def _cancel_after(n: int):
    """A `cancel_check` that returns False for the first `n` calls, then
    True forever — lets exactly `n` names get judged before cancelling."""
    calls = {"count": 0}

    def _check() -> bool:
        calls["count"] += 1
        return calls["count"] > n

    return _check


# --------------------------------------------------------------------------- #
# The exact silent-data-loss scenario: an organic resolution must not fire
# --------------------------------------------------------------------------- #


def test_cancel_after_one_name_never_deletes_an_inbox_item(tmp_path, monkeypatch):
    memory = _init_bank(tmp_path)
    existing_entity = _seed_existing_entity(memory, "rodrigo-sagastegui", "Rodrigo Sagastegui")
    clar_id = _seed_pending_clarification(memory, "Rodrigo Sagastegui")
    spy = _install_spy_indexer(monkeypatch)

    # "Rodrigo Sagastegui" is a direct-name match against the existing entity
    # (no LLM call) with confidence well above ORGANIC_RESOLUTION_THRESHOLD
    # (0.6) — exactly the shape that would organically resolve (and DELETE)
    # the seeded clarification if this were applied inline. It sorts first
    # by specificity (more tokens, longer name) so it is judged BEFORE the
    # second name, which cancellation must never reach.
    extracted = [{
        "episode_id": "ep1",
        "entities": [
            {"name": "Rodrigo Sagastegui", "type": "person", "confidence": 0.9,
             "source_episode": "ep1"},
            {"name": "Cicada", "type": "project", "confidence": 0.9, "source_episode": "ep1"},
        ],
        "relationships": [],
    }]

    cancel_check = _cancel_after(1)   # judges Rodrigo Sagastegui, cancels before Cicada
    result = asyncio.run(entity_resolver.resolve(
        extracted, [existing_entity], _settings(memory), cancel_check=cancel_check,
    ))

    # The bank is clean — nothing written, nothing deleted.
    assert _git(memory, "status", "--porcelain").strip() == ""

    # The seeded clarification is still there — organic resolution never fired.
    clar_path = memory / "inbox" / f"{clar_id}.md"
    assert clar_path.exists(), "the pending clarification must NOT have been deleted"
    parsed = markdown_parser.parse(clar_path)
    assert parsed.frontmatter.get("status") == "pending"

    # No index write happened either — not even the read-only lookup should
    # have produced a mutating call.
    mutating = [c for c in spy.calls if c[0] != "pending_by_name"]
    assert mutating == [], f"no index mutation may happen on a cancelled resolve(): {mutating}"

    # And the graph change itself was, correctly, never allowed to matter —
    # sleep_cycle discards `changes`/`relationships` wholesale on a cancelled
    # cycle; this just confirms resolve() itself made no side effects.
    assert clar_id.startswith("inbox-")


def test_uncancelled_run_still_organically_resolves_as_before(tmp_path, monkeypatch):
    """Control: the SAME scenario, but never cancelled — the fix must not
    have silently broken organic resolution for the normal path."""
    memory = _init_bank(tmp_path)
    existing_entity = _seed_existing_entity(memory, "rodrigo-sagastegui", "Rodrigo Sagastegui")
    clar_id = _seed_pending_clarification(memory, "Rodrigo Sagastegui")
    _install_spy_indexer(monkeypatch)

    extracted = [{
        "episode_id": "ep1",
        "entities": [
            {"name": "Rodrigo Sagastegui", "type": "person", "confidence": 0.9,
             "source_episode": "ep1"},
        ],
        "relationships": [],
    }]

    asyncio.run(entity_resolver.resolve(extracted, [existing_entity], _settings(memory)))

    clar_path = memory / "inbox" / f"{clar_id}.md"
    assert not clar_path.exists(), "an UNCANCELLED run must still organically resolve it"


# --------------------------------------------------------------------------- #
# Low-confidence path: no NEW clarification, no pending-index write
# --------------------------------------------------------------------------- #


def test_cancel_after_one_name_writes_no_clarification_and_no_pending_entry(tmp_path, monkeypatch):
    memory = _init_bank(tmp_path)
    spy = _install_spy_indexer(monkeypatch)

    # Both names are brand new, low confidence, no existing match, single
    # mention — the "else" branch: would create a clarification AND index a
    # pending entity. "Ambiguous Person" is more specific (two tokens) so it
    # sorts first and gets judged; "X" is blocked by cancellation.
    extracted = [{
        "episode_id": "ep1",
        "entities": [
            {"name": "Ambiguous Person", "type": "person", "confidence": 0.2,
             "source_episode": "ep1", "description": "someone mentioned in passing"},
            {"name": "X", "type": "concept", "confidence": 0.2, "source_episode": "ep1"},
        ],
        "relationships": [],
    }]

    cancel_check = _cancel_after(1)
    asyncio.run(entity_resolver.resolve(
        extracted, [], _settings(memory), cancel_check=cancel_check,
    ))

    assert _git(memory, "status", "--porcelain").strip() == ""
    assert list((memory / "inbox").glob("inbox-*.md")) == [], (
        "no clarification file may exist after a cancelled resolve()"
    )
    mutating = [c for c in spy.calls if c[0] != "pending_by_name"]
    assert mutating == [], f"no index mutation may happen on a cancelled resolve(): {mutating}"


def test_uncancelled_run_still_creates_the_clarification_and_pending_entry(tmp_path, monkeypatch):
    """Control: the SAME low-confidence scenario, never cancelled — the fix
    must not have silently broken clarification creation for the normal
    path."""
    memory = _init_bank(tmp_path)
    spy = _install_spy_indexer(monkeypatch)

    extracted = [{
        "episode_id": "ep1",
        "entities": [
            {"name": "Ambiguous Person", "type": "person", "confidence": 0.2,
             "source_episode": "ep1", "description": "someone mentioned in passing"},
        ],
        "relationships": [],
    }]

    asyncio.run(entity_resolver.resolve(extracted, [], _settings(memory)))

    created = list((memory / "inbox").glob("inbox-*.md"))
    assert len(created) == 1, "an UNCANCELLED run must still create the clarification"
    assert ("index_pending_entity", "Ambiguous Person") in spy.calls
    assert ("rebuild_pending_index", None) in spy.calls
