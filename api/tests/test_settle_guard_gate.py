"""The gate: every file a settle writes is reported to the guard (G98, `settle_guard`).

A failed settle puts back only the files its writers reported. A writer that does not report is a hole the next refactor
falls into (the loser page's claims ledger was one: it came back without its claims). This test checks the property
directly, for every family of settle the suite has: it runs the settle on a scratch bank with the guard active, stops it at the
commit (the stub sees the tree just before git is asked to stage anything), and compares the tree with what it was before the
settle began. Every path that changed must be one a writer reported (or the settle's own question and record); a path that
changed in the guard's scope and was not reported fails the test, naming the path. Then the same run checks that the guard puts
every file back.

Synthetic banks, invented names, a scripted engine: no network.
"""
from __future__ import annotations

import pytest

from api.services import git_service, settle_guard
from api.tests import settle_families
from api.tests.test_settle_guard import (FAMILIES, _Refused, _bank_of, _state, _tree, join_memory, memory)  # noqa: F401


#: A path no settle's writer reports and none is in the guard's scope: the gate lists them so a new one is a decision, not a
#: surprise (the person's own index, the derived caches). Empty today.
ALLOWED_OUTSIDE_SCOPE: frozenset[str] = frozenset()


class Seen:
    """What the commit stub saw the moment the settle asked git to commit: the paths that changed since the settle began, the
    paths the guard held as reported by a writer (never the commit's own list), and the paths changed outside its scope."""

    def __init__(self) -> None:
        self.commits = 0
        self.changed: set[str] = set()
        self.reported: set[str] = set()
        self.outside: set[str] = set()

    def unreported(self) -> set[str]:
        return {p for p in self.changed if settle_guard.in_scope(p)} - self.reported


def watch(bank, monkeypatch) -> Seen:
    """Stub every commit function a settle reaches: at the first call, compare the tree with what it was before the settle (taken
    here), record what the guard holds, and refuse the commit."""
    seen = Seen()
    before = _tree(bank)

    def stub(memory_path, message, paths, **kwargs):
        seen.commits += 1
        if seen.commits == 1:
            now = _tree(bank)
            seen.changed = {p for p in set(before) | set(now) if before.get(p) != now.get(p)}
            mark = settle_guard.active()
            assert mark is not None, "a settle's commit runs with the guard active"
            seen.reported = {rel for rel, rec in mark.recs.items() if rec.left is not settle_guard._UNSET or rec.declared}
            seen.outside = {p for p in seen.changed if not settle_guard.in_scope(p)} - ALLOWED_OUTSIDE_SCOPE
        raise _Refused("the gate refuses the commit")

    monkeypatch.setattr(git_service, "commit_touched_sync", stub)
    monkeypatch.setattr(git_service, "commit_paths_sync", stub)
    return seen


def gate(bank, settle, monkeypatch) -> Seen:
    seen = watch(bank, monkeypatch)
    before = _state(bank)
    assert not settle(), "the settle did not commit"
    assert seen.commits >= 1, "the settle reached its commit"
    assert not seen.unreported(), f"changed in the guard's scope and reported by no writer: {sorted(seen.unreported())}"
    assert not seen.outside, f"changed outside the guard's scope: {sorted(seen.outside)}"
    assert _state(bank) == before, "and the guard put every file back"
    return seen


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_every_file_a_settle_writes_is_reported(family, request, monkeypatch):
    bank = _bank_of(family, request)
    settle, _written, _paths = FAMILIES[family](bank)
    gate(bank, settle, monkeypatch)


@pytest.mark.parametrize("family", sorted(settle_families.FAMILIES))
def test_every_file_of_every_other_branch_of_apply_is_reported(family, memory, monkeypatch):
    settle, _written = settle_families.FAMILIES[family](memory)
    gate(memory, settle, monkeypatch)


@pytest.mark.parametrize("family", sorted(settle_families.UNDO_FAMILIES))
def test_every_file_an_undo_writes_is_reported(family, memory, monkeypatch):
    """Each branch of ``inbox_tend.undo``, after a real settle: its writes are reported, and a refused commit puts them all back."""
    undo, _written = settle_families.UNDO_FAMILIES[family](memory)
    gate(memory, undo, monkeypatch)


def test_the_widest_merge_changes_every_kind_of_file_the_guard_must_cover(memory, monkeypatch):
    """The family that stands for the merge's whole footprint really does reach each writer the gate is about."""
    settle, _written = settle_families.FAMILIES["rich_merge"](memory)
    seen = gate(memory, settle, monkeypatch)
    expected = {"entities/tool-b.claims.jsonl", "entities/tool-bee.claims.jsonl", "entities/tool-bee.md", "entities/linker.md",
                "graph_edges.yaml", "_redirects.yaml", "assets/pictures/tool-bee.png", "assets/pictures/tool-b.png",
                "inbox/inbox-001.md", "inbox/inbox-002.md"}
    assert expected <= seen.changed, sorted(expected - seen.changed)
    assert any(p.startswith("design/") for p in seen.changed)
    assert expected <= seen.reported
