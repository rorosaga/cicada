"""A partial restore is never worse than none (G98, `settle_guard`): a page and its claims ledger are one unit, a commit that
landed is never taken back, and every writer a settle can reach says what it wrote.

The cases are the second review's: a failure before the commit lost the loser page's claims ledger (``claims_ledger.remove`` said
nothing, so the page came back without its claims); a failure after the commit put the settle back on top of the commit that
holds it; the rename of a page reported neither what it left nor where. Synthetic banks, invented names, a scripted engine.
"""
from __future__ import annotations

import asyncio

import pytest

from api.services import (claims_ledger, entity_picture, git_service, inbox_actor, inbox_service, inbox_tend, merge_closes,
                          merge_rejections, predicates, same_name_doubts, settle_guard)
from api.tests import settle_families
from api.tests import test_inbox_tend as ti
from api.tests.test_settle_guard import (FAMILIES, _bank_of, _fold_with_a_ledger, _git, _state, _tree, _wrote, join_memory,  # noqa: F401
                                         memory)

LEDGER = "entities/tool-bee.claims.jsonl"


# --------------------------------------------------------------------------- 1. a failure before the commit


def test_a_failure_before_the_commit_loses_no_claims(memory, monkeypatch):
    """The reviewer's probe: the settle's record cannot be written, so nothing reaches the commit. The merge had removed the
    loser's page and its claims ledger; both come back, with the winner and everything else, byte for byte."""
    settle, _written, _paths = _fold_with_a_ledger(memory)
    before = _state(memory)

    def full_disk(actor):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(inbox_actor, "write_record", full_disk)
    assert not settle()
    assert _state(memory) == before
    assert (memory / LEDGER).exists() and (memory / "entities" / "tool-bee.md").exists()


def _families():
    return [*sorted(FAMILIES), *(f"more:{n}" for n in sorted(settle_families.FAMILIES))]


@pytest.mark.parametrize("family", _families())
def test_a_settle_that_raises_before_its_commit_names_a_path_leaves_the_tree_as_it_was(family, request, monkeypatch):
    """The reviewer's second probe, for every family: the commit function raises before it says which paths it takes, so only
    what the writers reported can be put back. Nothing is lost, nothing is left, nothing is committed or staged."""
    if family.startswith("more:"):
        bank = request.getfixturevalue("memory")
        settle = settle_families.FAMILIES[family[5:]](bank)[0]
    else:
        bank = _bank_of(family, request)
        settle = FAMILIES[family](bank)[0]
    before = _state(bank)

    def boom(*args, **kwargs):
        raise git_service.GitError("raised before the commit named its paths")

    monkeypatch.setattr(git_service, "commit_touched_sync", boom)
    monkeypatch.setattr(git_service, "commit_paths_sync", boom)
    assert not settle()
    assert _state(bank) == before


# --------------------------------------------------------------------------- 1. a page and its ledger are one unit


def _ledger_world(memory):
    ti._entity(memory, "tool-bee", type="tool", name="Tool Bee", status="active", body=ti._big_claims("tool-bee"))
    ti._commit(memory)
    return memory / "entities" / "tool-bee.md", memory / LEDGER


def test_a_ledger_written_without_a_report_goes_back_with_its_reported_page(memory):
    page, ledger = _ledger_world(memory)
    before = _state(memory)
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, page, b"the settle's page\n")
        ledger.write_bytes(b"the settle's ledger, written by a writer that said nothing\n")
    assert settle_guard.put_back(mark) == 0
    assert _state(memory) == before


def test_a_page_written_without_a_report_goes_back_with_its_reported_ledger(memory):
    page, ledger = _ledger_world(memory)
    before = _state(memory)
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, ledger, b"the settle's ledger\n")
        page.write_bytes(b"the settle's page, written by a writer that said nothing\n")
    assert settle_guard.put_back(mark) == 0
    assert _state(memory) == before


def test_a_ledger_removed_without_a_report_comes_back_and_so_does_the_persons_own_edit_of_it(memory):
    page, ledger = _ledger_world(memory)
    ledger.write_bytes(ledger.read_bytes() + b'{"id": "clm_unsaved"}\n')   # the person's edit, not committed yet
    mine = ledger.read_bytes()
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, page, None)
        ledger.unlink()
    assert settle_guard.put_back(mark) == 0
    assert ledger.read_bytes() == mine and page.exists()


def test_an_unreported_write_of_a_unit_is_logged_by_id_only(memory, capture_logs):
    page, ledger = _ledger_world(memory)
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, page, b"x\n")
        ledger.write_bytes(b"y\n")
    settle_guard.put_back(mark)
    text = " ".join(capture_logs)
    assert "tool-bee" in text and "without reporting" in text
    assert "ledger" not in text.split("without reporting")[-1].split("(")[-1], "ids only, never the bytes"


@pytest.fixture
def capture_logs():
    from loguru import logger

    lines: list[str] = []
    handle = logger.add(lambda m: lines.append(str(m)), level="WARNING")
    yield lines
    logger.remove(handle)


def test_an_unrelated_unreported_path_is_never_touched_by_the_unit_rule(memory):
    page, ledger = _ledger_world(memory)
    other = memory / "entities" / "owner-example.md"
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, page, b"x\n")
    other.write_bytes(other.read_bytes() + b"\nanother writer's page\n")
    mine = other.read_bytes()
    assert settle_guard.put_back(mark) == 0
    assert other.read_bytes() == mine


def test_a_unit_one_half_of_which_another_writer_changed_is_left_whole(memory):
    """The reported page was rewritten by another writer after the settle: it is theirs, and so is its ledger."""
    page, ledger = _ledger_world(memory)
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, page, b"the settle's page\n")
        _wrote(mark, ledger, b"the settle's ledger\n")
    page.write_bytes(b"another writer's page\n")
    assert settle_guard.put_back(mark) == 0
    assert page.read_bytes() == b"another writer's page\n"
    assert ledger.read_bytes() == b"the settle's ledger\n", "not put back under a page that is another writer's now"


def test_a_staged_unreported_ledger_has_its_index_entry_back(memory):
    page, ledger = _ledger_world(memory)
    before = _state(memory)
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, page, b"the settle's page\n")
        ledger.write_bytes(b"the settle's ledger\n")
        _git(memory, "add", "entities/")
    assert settle_guard.put_back(mark) == 0
    assert _state(memory) == before, "the worktree and the index, both halves"


# --------------------------------------------------------------------------- 2. a commit that landed is never taken back


def _commit_then_raise(monkeypatch):
    real = git_service.commit_touched_sync

    def late(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("a step after the commit")

    monkeypatch.setattr(git_service, "commit_touched_sync", late)


def test_a_step_that_raises_after_the_commit_landed_leaves_the_settle_as_committed(memory, monkeypatch):
    """The reviewer's probe: the real commit function, wrapped to raise after it returns. The settle is committed, so the tree is
    clean at that commit and the answer is that it landed (a failure reported for a settle that exists would be a lie)."""
    settle, _written, _paths = _fold_with_a_ledger(memory)
    _commit_then_raise(monkeypatch)
    assert settle() is True
    assert _git(memory, "status", "--porcelain", "--untracked-files=all").strip() == ""
    assert not (memory / LEDGER).exists() and not (memory / "entities" / "tool-bee.md").exists()
    assert "Inbox settled by Sleep" in _git(memory, "log", "-1", "--format=%s")
    assert (memory / "inbox" / "settled" / "inbox-001.md").exists()


def test_the_same_for_a_retirement(memory, monkeypatch):
    from api.tests.test_settle_guard import _retirement

    settle, _written, _paths = _retirement(memory)
    _commit_then_raise(monkeypatch)
    assert settle() is True
    assert _git(memory, "status", "--porcelain").strip() == ""


def test_the_same_for_a_normalization_settle(memory, monkeypatch):
    settle, _written = settle_families.normalization_fold(memory)
    _commit_then_raise(monkeypatch)
    assert settle() is True
    assert _git(memory, "status", "--porcelain").strip() == ""
    assert "Inbox settled by Sleep" in _git(memory, "log", "-1", "--format=%s")


def test_the_same_for_a_nickname_title(memory, monkeypatch):
    settle, _written = settle_families.nickname(memory)
    _commit_then_raise(monkeypatch)
    assert settle() is True
    assert _git(memory, "status", "--porcelain").strip() == ""
    assert "Titled by a nickname" in _git(memory, "log", "-1", "--format=%s")


def test_an_undo_whose_commit_landed_is_not_reported_as_failed(memory, monkeypatch):
    settle, _written, _paths = _fold_with_a_ledger(memory)
    assert settle()
    _commit_then_raise(monkeypatch)
    inbox_tend.undo_committed(memory, "inbox-001")   # returns: the undo is committed
    assert _git(memory, "status", "--porcelain").strip() == ""
    assert (memory / "entities" / "tool-bee.md").exists() and (memory / LEDGER).exists()
    assert "Sleep's settle undone" in _git(memory, "log", "-1", "--format=%s")


def test_a_stop_after_the_commit_still_stops(memory, monkeypatch):
    """Only an error is swallowed once the commit landed: a stop (`KeyboardInterrupt`) propagates, and nothing is put back."""
    settle, _written, _paths = _fold_with_a_ledger(memory)
    real = git_service.commit_touched_sync

    def stopped(*args, **kwargs):
        real(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(git_service, "commit_touched_sync", stopped)
    with pytest.raises(BaseException):
        settle()
    assert _git(memory, "status", "--porcelain").strip() == ""


def test_a_path_the_moved_head_holds_is_left_and_one_that_differs_from_both_goes_back(memory):
    """HEAD moved since the picture: a path whose bytes equal what HEAD now holds is the commit's; a path that differs from
    what HEAD holds and from the picture is put back to the picture."""
    a, b = memory / "entities" / "owner-example.md", memory / "entities" / "other-example.md"
    ti._entity(memory, "other-example", type="tool", name="Other", status="active")
    ti._commit(memory)
    first_a, first_b = a.read_bytes(), b.read_bytes()
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, a, b"the settle's a\n")
        _wrote(mark, b, b"the settle's b\n")
    _git(memory, "add", "entities/owner-example.md")
    _git(memory, "commit", "-qm", "a commit that holds one path of the settle", "--", "entities/owner-example.md")
    assert settle_guard.put_back(mark) == 0
    assert a.read_bytes() == b"the settle's a\n", "the commit has it"
    assert b.read_bytes() == first_b, "only the path no commit holds goes back"
    assert first_a != a.read_bytes()
    assert _git(memory, "status", "--porcelain").strip() == ""


def test_a_guarded_body_that_fails_after_its_commit_ends_as_if_it_returned(memory):
    page = memory / "entities" / "owner-example.md"
    with settle_guard.guarded(memory):
        page.write_bytes(page.read_bytes() + b"\nsettled\n")
        git_service.commit_touched_sync(memory, "the settle", ["entities/owner-example.md"])
        raise RuntimeError("a step after the commit")
    assert page.read_bytes().endswith(b"\nsettled\n") and _git(memory, "status", "--porcelain").strip() == ""
    with pytest.raises(RuntimeError):
        with settle_guard.guarded(memory) as mark:
            _wrote(mark, page, b"not committed\n")
            raise RuntimeError("before any commit")
    assert page.read_bytes().endswith(b"\nsettled\n"), "put back"


# --------------------------------------------------------------------------- 3. the rename


def test_a_page_moved_by_git_in_a_failed_settle_is_back_where_it_was(memory):
    """``_git_move`` says what it left: the destination is removed and the source (and its ledger) restored, index included."""
    ti._entity(memory, "tool-bee", type="tool", name="Tool Bee", status="active", body=ti._big_claims("tool-bee"))
    ti._commit(memory)
    before = _state(memory)
    src, dst = memory / "entities" / "tool-bee.md", memory / "entities" / "tool-bees.md"
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        asyncio.run(inbox_service._git_move(memory, src, dst))
    assert dst.exists() and not src.exists() and (memory / "entities" / "tool-bees.claims.jsonl").exists()
    assert settle_guard.put_back(mark) == 0
    assert _state(memory) == before


def test_an_untracked_page_moved_by_the_fallback_is_back_too(memory):
    src, dst = memory / "entities" / "fresh.md", memory / "entities" / "fresher.md"
    src.write_bytes(b"---\nname: Fresh\n---\nnew\n")
    before = _state(memory)
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        asyncio.run(inbox_service._git_move(memory, src, dst))
    assert dst.exists() and not src.exists()
    assert settle_guard.put_back(mark) == 0
    assert _state(memory) == before


def test_a_page_removed_by_git_in_a_failed_settle_is_back(memory):
    ti._entity(memory, "tool-b", type="tool", name="Tool B", status="active")
    ti._commit(memory)
    before = _state(memory)
    target = memory / "entities" / "tool-b.md"
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        asyncio.run(inbox_service._git_remove(memory, target))
    assert not target.exists()
    assert settle_guard.put_back(mark) == 0
    assert _state(memory) == before


# --------------------------------------------------------------------------- every writer a settle reaches reports


def _w_ledger_remove(memory):
    ti._entity(memory, "tool-bee", type="tool", body=ti._big_claims("tool-bee"))
    ti._commit(memory)
    return lambda: claims_ledger.remove(memory / "entities" / "tool-bee.md")


def _w_ledger_move(memory):
    ti._entity(memory, "tool-bee", type="tool", body=ti._big_claims("tool-bee"))
    ti._commit(memory)
    return lambda: claims_ledger.move(memory / "entities" / "tool-bee.md", memory / "entities" / "tool-bees.md")


def _w_rejection(memory):
    return lambda: merge_rejections.add_rejected(memory, "tool-a", "tool-b")


def _w_doubts(memory):
    return lambda: same_name_doubts.add_pairs(memory, [("sam", "sam-2")])


def _w_predicates(memory):
    return lambda: predicates.update_runtime_map(memory, lambda data: data.update(confirmed_folds={"used": "uses"}) or True)


def _w_picture_merge(memory):
    (memory / "assets" / "pictures").mkdir(parents=True)
    (memory / "assets" / "pictures" / "tool-bee.png").write_bytes(settle_families.PNG)
    ti._commit(memory)
    loser = {"picture": {"kind": "upload", "ext": "png"}}
    return lambda: entity_picture.carry_on_merge(memory, "tool-bee", loser, "tool-b", {})


def _w_picture_removed(memory):
    (memory / "assets" / "pictures").mkdir(parents=True)
    (memory / "assets" / "pictures" / "tool-bee.png").write_bytes(settle_families.PNG)
    ti._commit(memory)
    loser, winner = {"picture": {"kind": "upload", "ext": "png"}}, {"picture": {"kind": "initials"}}
    return lambda: entity_picture.carry_on_merge(memory, "tool-bee", loser, "tool-b", winner)


def _w_picture_rename(memory):
    (memory / "assets" / "pictures").mkdir(parents=True)
    (memory / "assets" / "pictures" / "tool-bee.png").write_bytes(settle_families.PNG)
    ti._commit(memory)
    return lambda: entity_picture.carry_on_rename(memory, "tool-bee", "tool-bees", {"picture": {"kind": "upload", "ext": "png"}})


def _w_merge_closes(memory):
    ti._item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-bee", merge_target_hint="tool-b")
    ti._commit(memory)
    return lambda: merge_closes.close(memory, "tool-bee", "tool-b", loser_ends={"tool-bee"}, winner_ends={"tool-b"})


WRITERS = {f.__name__[3:]: f for f in (_w_ledger_remove, _w_ledger_move, _w_rejection, _w_doubts, _w_predicates, _w_picture_merge,
                                       _w_picture_removed, _w_picture_rename, _w_merge_closes)}


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_every_writer_a_settle_reaches_is_put_back_by_the_guard(writer, memory):
    act = WRITERS[writer](memory)
    before = _state(memory)
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        act()
    assert _tree(memory) != before[0], "the writer changed something"
    assert settle_guard.put_back(mark) == 0
    assert _state(memory) == before
    assert mark.recs, "and it said so itself (nothing relied on a commit's list)"
