"""A settle whose commit does not land leaves nothing behind (G98 / G113, `settle_guard`).

Sleep settles a question through the person's own resolver, which writes several files and then commits them as one commit.
When the commit fails, every file is put back exactly as it was (an uncommitted edit gets its own bytes, a new file is removed,
a deleted one comes back), nothing is committed or staged, and the settle is reported as not having happened. One test per
family of rule: a retirement, a merge that folds a page and its ledger, a merge that folds a held line into a page, a page
join, a "different" that records a rejection, a filing from the pending store, and the undo of one of them. Each runs twice: the
commit refused by a stub, and refused by a real pre-commit hook (git has staged the files by then). Then the same settle runs
with nothing failing and its commit is what it always was.

Synthetic banks, invented names, a scripted engine: no network.
"""
from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path

import pytest

from api.services import (bank_index, git_service, inbox_tend, markdown_parser, pending_store, predicates, settle_guard,
                          typo_join, web_settle)
from api.services import question_revisit as qr
from api.services.claims import Claim
from api.tests import test_inbox_tend as ti
from api.tests import test_name_revisit as nr
from api.tests import test_typo_join as tj
from api.tests import test_which_one_reader as wo


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True).stdout


def _tree(bank: Path) -> dict[str, bytes]:
    derived = ("search_index.db", "vector_index.db")   # git ignores them: rebuilt, never memory
    return {p.relative_to(bank).as_posix(): p.read_bytes() for p in sorted(bank.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(bank).parts and not p.name.startswith(derived)}


def _state(bank: Path) -> tuple:
    """Every file, the commit, the porcelain status and what is staged: what 'exactly as it was' means."""
    return (_tree(bank), _git(bank, "rev-parse", "HEAD").strip(), _git(bank, "status", "--porcelain", "-z", "--untracked-files=all"),
            _git(bank, "diff", "--cached", "--name-only"))


def _dirty(bank: Path, *pages: str) -> None:
    """Edits the person had not saved yet: a page the settle never reads, a new file, and (``pages``) pages the settle writes."""
    other = bank / "entities" / "owner-example.md"
    if not other.exists():
        other = next((bank / "entities").glob("*.md"))
    other.write_bytes(other.read_bytes() + b"\nAn unsaved edit that is not the settle's.\n")
    (bank / "entities" / "unsaved-new-page.md").write_bytes(b"---\nname: Unsaved\n---\nNot committed yet.\n")
    for rel in pages:
        page = bank / rel
        page.write_bytes(page.read_bytes() + b"\nAn unsaved edit on a page the settle also writes.\n")


class _Refused(git_service.GitError):
    pass


_REAL_COMMIT = git_service.commit_touched_sync


def _refuse(how: str, bank: Path, monkeypatch) -> None:
    if how == "stub":
        def boom(*args, **kwargs):
            raise _Refused("the commit failed")

        monkeypatch.setattr(git_service, "commit_touched_sync", boom)
        return
    hook = bank / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)


def _allow(bank: Path, monkeypatch) -> None:
    monkeypatch.setattr(git_service, "commit_touched_sync", _REAL_COMMIT)
    (bank / ".git" / "hooks" / "pre-commit").unlink(missing_ok=True)


@pytest.fixture(params=["stub", "hook"])
def how(request):
    return request.param


# --------------------------------------------------------------------------- the worlds


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(inbox_tend, "_RECORD_READ", {})
    monkeypatch.setattr("api.services.pair_evidence.FRESH_S", 0.0)
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    ti._entity(m, "owner-example", type="person", owner=True, name="Owner Example", status="active")
    ti._commit(m)
    return m


def _retirement(memory):
    ti._item(memory, "inbox-001", kind="conflict", entity_id="merged-away", entity_name="Merged Away")
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "subject_gone"

    def settle():
        d.fingerprint = (memory / "inbox" / "inbox-001.md").read_bytes()
        return asyncio.run(inbox_tend.apply(memory, ti._Settings(memory), d))

    return settle, [], {"inbox/inbox-001.md", "inbox/settled/inbox-001.md"}


def _fold_with_a_ledger(memory):
    ti._entity(memory, "tool-b", type="tool", name="Tool B", status="active")
    ti._entity(memory, "tool-bee", type="tool", name="Tool Bee", status="active", body=ti._big_claims("tool-bee"))
    assert (memory / "entities" / "tool-bee.claims.jsonl").exists()
    ti._item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-bee", entity_name="Tool Bee",
             merge_target_hint="tool-b", suggested_classification="tool")
    ti._commit(memory)
    fn = ti._judge_fn({"verdict": "same", "confidence": 0.97, "reason": "one tool"})

    def settle():
        return asyncio.run(inbox_tend.tend(memory, ti._Settings(memory), episodes=[], run_policy=True, llm_fn=fn)).settled == 1

    return settle, ["entities/tool-b.md"], {"_redirects.yaml", "entities/tool-b.md", "entities/tool-b.claims.jsonl",
                                           "entities/tool-bee.md", "inbox/inbox-001.md", "inbox/settled/inbox-001.md"}


def _different(memory):
    ti._entity(memory, "tool-b", type="tool", name="Tool B")
    ti._entity(memory, "tool-bee", type="tool", name="Tool Bee")
    ti._item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-bee", entity_name="Tool Bee",
             merge_target_hint="tool-b", suggested_classification="tool")
    ti._commit(memory)
    fn = ti._judge_fn({"verdict": "different", "confidence": 0.95})

    def settle():
        return asyncio.run(inbox_tend.tend(memory, ti._Settings(memory), episodes=[], run_policy=True, llm_fn=fn)).settled == 1

    return settle, [], {"_merge_rejected.yaml", "inbox/inbox-001.md", "inbox/settled/inbox-001.md"}


def _held_line_into_a_page(memory):
    claim = Claim(id="clm_2026-11-14_aaaa1111", text="QL runs the Friday deploy", subject="ql", predicate="runs", object="friday deploy",
                  object_kind="literal", source_episodes=["ep_2026-11-14_001"])
    path = nr._world(memory, "QL", "QL, also called Quartzline, is the thing I deploy on Fridays.", claims=[claim])
    judge = nr._judge(nr._same("QL, also called Quartzline, is the thing I deploy on Fridays."))

    def settle():
        return nr._look(memory, judge)[0].settled == 1

    return settle, ["entities/quartzline.md"], {"entities/quartzline.md", "pending_entities.jsonl", f"inbox/{path.stem}.md",
                                                f"inbox/settled/{path.stem}.md"}


def _page_join(memory):
    tj._world(memory)
    judge = tj._judge(tj._one())

    def settle():
        return asyncio.run(typo_join.tend(memory, tj._Settings(memory), judge)).joined == 1

    return settle, ["entities/marisol-quinn.md"], None


FAMILIES = {
    "retirement": _retirement,
    "fold_with_ledger": _fold_with_a_ledger,
    "different_records_a_rejection": _different,
    "held_line_into_a_page": _held_line_into_a_page,
    "page_join": _page_join,
}


@pytest.fixture
def join_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    predicates.install_predicate_map(m)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    tj._page(m, "ines-varga", "Ines Varga", owner=True)
    tj._commit(m)
    return m


def _bank_of(family: str, request) -> Path:
    return request.getfixturevalue("join_memory" if family == "page_join" else "memory")


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_a_settle_whose_commit_fails_leaves_every_file_as_it_was(family, how, request, monkeypatch):
    bank = _bank_of(family, request)
    settle, written, _paths = FAMILIES[family](bank)
    # A real refusal comes after the "kept apart" commit of an unsaved edit on a page the settle writes (own test below); here
    # that edit is on the stub's side only, so "nothing committed" means HEAD does not move at all.
    _dirty(bank, *(written if how == "stub" else ()))
    before = _state(bank)
    _refuse(how, bank, monkeypatch)
    assert not settle(), "the settle did not happen"
    after = _state(bank)
    assert after[0] == before[0], "every file, the dirty ones with their own bytes, byte for byte"
    assert after[1:] == before[1:], "nothing committed, nothing staged, the same changes uncommitted"
    assert not list((bank / "inbox" / "settled").glob("*.md")) if (bank / "inbox" / "settled").exists() else True


def test_a_filing_from_the_pending_store_whose_commit_fails_leaves_every_file_as_it_was(tmp_path, monkeypatch, how):
    bank, path = wo._world(tmp_path, monkeypatch, conversations={wo.EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    _dirty(bank, *(["entities/nick-brother.md"] if how == "stub" else []))
    before = _state(bank)
    _refuse(how, bank, monkeypatch)
    ask = wo.scripted(name="Nick Rowe", sentence="My brother Nick is visiting.")
    assert wo._run(bank, path, ask).settled == 0
    assert _state(bank) == before
    assert pending_store.held_line(bank, "Nick").held_claims


def test_an_unsaved_edit_committed_apart_before_the_refusal_keeps_its_own_bytes(memory, monkeypatch):
    """`commit_touched_sync` commits an edit that was uncommitted before the settle on a page the settle also writes FIRST, alone,
    with no author, so the settle's commit carries only its own change. If the settle's commit is then refused, that commit of the
    person's own bytes stays (it is theirs, not the settle's); the page holds those bytes, and nothing of the settle is left."""
    settle, _written, _paths = _fold_with_a_ledger(memory)
    page = memory / "entities" / "tool-b.md"
    page.write_bytes(page.read_bytes() + b"\nAn unsaved edit on a page the settle also writes.\n")
    mine = page.read_bytes()
    head = _git(memory, "rev-parse", "HEAD").strip()
    _refuse("hook", memory, monkeypatch)
    assert not settle()
    assert page.read_bytes() == mine, "the page holds the person's own bytes, not the merge's"
    assert (memory / "entities" / "tool-bee.md").exists() and (memory / "inbox" / "inbox-001.md").exists()
    assert not list((memory / "inbox").glob("settled/*.md"))
    assert _git(memory, "status", "--porcelain").strip() == "", "and it is committed, apart, as theirs"
    assert _git(memory, "rev-list", "--count", f"{head}..HEAD").strip() == "1"
    assert _git(memory, "log", "-1", "--format=%s").startswith("Uncommitted edit kept apart")
    assert _git(memory, "show", "--name-only", "--format=", "HEAD").split() == ["entities/tool-b.md"]


def test_a_failed_filing_is_not_swept_into_the_next_writers_commit(memory, monkeypatch):
    """The defect: the next writer's commit carried the half-settle in under its own name."""
    settle, _written, _paths = _retirement(memory)
    monkeypatch.setattr(git_service, "commit_touched_sync", lambda *a, **k: (_ for _ in ()).throw(_Refused("no")))
    assert not settle()
    _allow(memory, monkeypatch)
    assert git_service.commit_changes_sync(memory, "A later writer") is None, "there is nothing of the failed settle to sweep in"
    assert (memory / "inbox" / "inbox-001.md").exists() and not list((memory / "inbox").glob("settled/*.md"))


# --------------------------------------------------------------------------- the undo


def test_an_undo_whose_commit_fails_leaves_every_file_as_it_was(memory, how, monkeypatch):
    ti._entity(memory, "tool-b", type="tool", name="Tool B", status="active")
    ti._entity(memory, "tool-bee", type="tool", name="Tool Bee", status="active", body=ti._big_claims("tool-bee"))
    ti._item(memory, "inbox-001", kind="merge_suggestion", entity_id="tool-bee", entity_name="Tool Bee",
             merge_target_hint="tool-b", suggested_classification="tool")
    ti._commit(memory)
    fn = ti._judge_fn({"verdict": "same", "confidence": 0.97, "reason": "one tool"})
    assert asyncio.run(inbox_tend.tend(memory, ti._Settings(memory), episodes=[], run_policy=True, llm_fn=fn)).settled == 1
    _dirty(memory)
    before = _state(memory)
    _refuse(how, memory, monkeypatch)
    with pytest.raises(Exception):
        inbox_tend.undo_committed(memory, "inbox-001")
    assert _state(memory) == before, "the duplicate is still gone, the settle's record still there: the undo did not happen"
    assert (memory / "inbox" / "settled" / "inbox-001.md").exists() and not (memory / "inbox" / "inbox-001.md").exists()
    _allow(memory, monkeypatch)
    inbox_tend.undo_committed(memory, "inbox-001")
    assert (memory / "entities" / "tool-bee.md").exists() and (memory / "inbox" / "inbox-001.md").exists()
    assert "Sleep's settle undone" in _git(memory, "log", "-1", "--format=%s")


# --------------------------------------------------------------------------- when nothing fails, the commit is what it was


def _commit_shape(bank: Path) -> tuple[str, list[str], str]:
    subject = _git(bank, "log", "-1", "--format=%s").strip().rsplit(" ", 1)[0]
    names = sorted(_git(bank, "show", "--name-only", "--format=", "HEAD").split())
    body = _git(bank, "show", "--format=", "-p", "HEAD", "--", *[n for n in names if not n.startswith("inbox/settled/")])
    return subject, names, hashlib.sha256(body.encode()).hexdigest()


@pytest.mark.parametrize("family", sorted(FAMILIES))
def test_a_settle_that_commits_is_the_commit_it_always_was(family, request):
    bank = _bank_of(family, request)
    settle, written, paths = FAMILIES[family](bank)
    _dirty(bank, *written)
    assert settle()
    subject, names, _diff = _commit_shape(bank)
    assert subject.startswith("Inbox settled by Sleep") or subject.startswith("Inbox settled")
    if paths is not None:
        assert set(names) == paths
    status = _git(bank, "status", "--porcelain").split("\n")
    assert any("An unsaved" in (bank / line[3:]).read_text() for line in status if line.strip() and line[3:].endswith(".md")
               and (bank / line[3:]).is_file() and "unsaved-new-page" not in line), "the person's edit stays uncommitted"


# --------------------------------------------------------------------------- the mechanism itself


def test_the_picture_puts_back_exactly_and_touches_nothing_outside_its_scope(memory):
    page = memory / "entities" / "owner-example.md"
    page.write_bytes(page.read_bytes() + b"\nmine\n")
    mark = settle_guard.take(memory)
    page.write_bytes(b"the settle's version\n")
    new = memory / "entities" / "new-page.md"
    new.write_bytes(b"a file the settle made\n")
    git_gone = memory / "entities" / "owner-example.claims.jsonl"
    git_gone.write_bytes(b"{}\n")
    capture = memory / "episodes" / "ep_2026-11-26_001.md"
    capture.write_bytes(b"a conversation captured while the settle ran\n")
    _git(memory, "add", "entities/new-page.md")
    assert settle_guard.put_back(mark) == 0
    assert page.read_bytes().endswith(b"\nmine\n") and b"settle's version" not in page.read_bytes()
    assert not new.exists() and not git_gone.exists()
    assert capture.read_bytes() == b"a conversation captured while the settle ran\n", "outside the scope: never touched"
    assert _git(memory, "diff", "--cached", "--name-only") == ""


def test_a_tree_git_cannot_list_settles_nothing(memory, monkeypatch):
    settle, _written, _paths = _retirement(memory)
    before = _state(memory)

    def unreadable(*args, **kwargs):
        raise git_service.GitError("status failed")

    monkeypatch.setattr(git_service, "dirty_paths_sync", unreadable)
    assert not settle()
    assert _state(memory) == before


def test_a_commit_that_landed_is_never_taken_back(memory):
    mark = settle_guard.take(memory)
    page = memory / "entities" / "owner-example.md"
    page.write_bytes(page.read_bytes() + b"\nsettled\n")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-qm", "the settle landed")
    assert settle_guard.put_back(mark) == 0
    assert page.read_bytes().endswith(b"\nsettled\n") and not _git(memory, "status", "--porcelain").strip()
