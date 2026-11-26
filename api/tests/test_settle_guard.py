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


def _dirty(bank: Path, *pages: str, spare: tuple[str, ...] | list[str] = ()) -> None:
    """Edits the person had not saved yet: a page the settle never writes, a new file, and (``pages``) pages the settle writes.

    ``spare`` names the pages the settle writes that must stay clean here. The untouched page is chosen by name, never by the
    folder's own listing order: that order differs between file systems, and on one of them the first page listed was the
    page the settle writes, so its unsaved edit was committed apart and the commit moved."""
    other = bank / "entities" / "owner-example.md"
    if not other.exists():
        taken = {Path(rel).name for rel in (*pages, *spare)}
        other = next(page for page in sorted((bank / "entities").glob("*.md")) if page.name not in taken)
    other.write_bytes(other.read_bytes() + b"\nAn unsaved edit that is not the settle's.\n")
    (bank / "entities" / "unsaved-new-page.md").write_bytes(b"---\nname: Unsaved\n---\nNot committed yet.\n")
    for rel in pages:
        page = bank / rel
        page.write_bytes(page.read_bytes() + b"\nAn unsaved edit on a page the settle also writes.\n")


class _Refused(git_service.GitError):
    pass


_REAL_GIT = git_service._git_sync
_REAL_COMMIT = git_service.commit_touched_sync


def _refuse(how: str, bank: Path, monkeypatch) -> None:
    if how == "stub":
        # The commit is refused as it starts: it has said which paths it takes (as the real one does first) and git has
        # staged and committed nothing.
        def boom(memory_path, message, paths, **kwargs):
            git_service._report_to_settle(memory_path, git_service._with_ledgers(memory_path, list(paths)))
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
    _dirty(bank, *(written if how == "stub" else ()), spare=written)
    before = _state(bank)
    _refuse(how, bank, monkeypatch)
    assert not settle(), "the settle did not happen"
    after = _state(bank)
    assert after[0] == before[0], "every file, the dirty ones with their own bytes, byte for byte"
    assert after[1:] == before[1:], "nothing committed, nothing staged, the same changes uncommitted"
    assert not list((bank / "inbox" / "settled").glob("*.md")) if (bank / "inbox" / "settled").exists() else True


def test_a_filing_from_the_pending_store_whose_commit_fails_leaves_every_file_as_it_was(tmp_path, monkeypatch, how):
    bank, path = wo._world(tmp_path, monkeypatch, conversations={wo.EP1: "user: My brother Nick is visiting.\nassistant: Nice."})
    _dirty(bank, *(["entities/nick-brother.md"] if how == "stub" else []), spare=["entities/nick-brother.md"])
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
    _refuse("stub", memory, monkeypatch)
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


def _wrote(mark, path: Path, data: bytes | None) -> None:
    """What a writer of a settle does around its write: say it is about to, write, say what it left."""
    settle_guard.writing(path)
    if data is None:
        path.unlink()
    else:
        path.write_bytes(data)
    settle_guard.wrote(path, data)


def test_the_picture_puts_back_what_the_settle_wrote_and_touches_nothing_outside_its_scope(memory):
    page = memory / "entities" / "owner-example.md"
    page.write_bytes(page.read_bytes() + b"\nmine\n")
    mine = page.read_bytes()
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, page, b"the settle's version\n")
        new = memory / "entities" / "new-page.md"
        _wrote(mark, new, b"a file the settle made\n")
        ledger = memory / "entities" / "owner-example.claims.jsonl"
        _wrote(mark, ledger, b"{}\n")
        _git(memory, "add", "entities/new-page.md")
    capture = memory / "episodes" / "ep_2026-11-26_001.md"
    capture.write_bytes(b"a conversation captured while the settle ran\n")
    assert settle_guard.put_back(mark) == 0
    assert page.read_bytes() == mine
    assert not new.exists() and not ledger.exists()
    assert capture.read_bytes() == b"a conversation captured while the settle ran\n", "outside the scope: never touched"
    assert _git(memory, "diff", "--cached", "--name-only") == ""


# --------------------------------------------------------------------------- 1. another writer's files are never touched


def test_a_failed_settle_never_touches_what_another_writer_wrote_meanwhile(memory, monkeypatch):
    """The reviewer's case 1: a source sync writes ``sync_state.json`` (no admission, no page lock), the person's answer to
    another question writes a new inbox file and edits a page, while a settle runs and then fails. Only the settle's own
    files go back."""
    (memory / "sync_state.json").write_text('{"cursor": 1}\n')
    (memory / "_state.md").write_text("cursor one\n")
    settle, _written, _paths = _retirement(memory)
    before = _state(memory)
    theirs = {
        "sync_state.json": b'{"cursor": 2}\n',
        "_state.md": b"cursor two\n",
        "inbox/inbox-099.md": b"---\nstatus: pending\n---\nAn answer another writer just wrote.\n",
        "entities/owner-example.md": (memory / "entities" / "owner-example.md").read_bytes() + b"\nAnother writer's edit.\n",
        "episodes/ep_2026-11-26_001.md": b"a capture landing meanwhile\n",
    }

    def boom(memory_path, message, paths, **kwargs):
        git_service._report_to_settle(memory_path, git_service._with_ledgers(memory_path, list(paths)))
        for rel, data in theirs.items():
            (memory / rel).write_bytes(data)
        raise _Refused("the commit failed")

    monkeypatch.setattr(git_service, "commit_touched_sync", boom)
    assert not settle()
    for rel, data in theirs.items():
        assert (memory / rel).read_bytes() == data, f"{rel} is another writer's: untouched"
    assert (memory / "inbox" / "inbox-001.md").exists(), "the question is back"
    assert not (memory / "inbox" / "settled" / "inbox-001.md").exists(), "and the settle's record is gone"
    mine = {k: v for k, v in _tree(memory).items() if k not in theirs}
    assert mine == {k: v for k, v in before[0].items() if k not in theirs}


def test_a_path_another_writer_changed_after_the_settle_wrote_it_is_left_alone(memory, monkeypatch):
    settle, _written, _paths = _retirement(memory)
    record = memory / "inbox" / "settled" / "inbox-001.md"
    rewritten = b"---\nstatus: pending\n---\nAnother writer replaced the settle's record.\n"

    def boom(memory_path, message, paths, **kwargs):
        git_service._report_to_settle(memory_path, git_service._with_ledgers(memory_path, list(paths)))
        record.write_bytes(rewritten)
        raise _Refused("the commit failed")

    monkeypatch.setattr(git_service, "commit_touched_sync", boom)
    assert not settle()
    assert record.read_bytes() == rewritten, "its bytes are no longer what the settle left: not the settle's to put back"
    assert (memory / "inbox" / "inbox-001.md").exists()


def test_a_settle_that_fails_before_its_commit_puts_back_what_it_reported(memory, monkeypatch):
    """The resolver raises before the commit says anything: the question's own removal and the record it wrote (through the
    page writers' funnel) are the settle's, and nothing else is."""
    settle, _written, _paths = _retirement(memory)
    (memory / "sync_state.json").write_text("one\n")
    before = _state(memory)

    def boom(memory_path, message, paths, **kwargs):
        (memory / "sync_state.json").write_text("two\n")
        raise _Refused("the commit failed before it started")

    monkeypatch.setattr(git_service, "commit_touched_sync", boom)
    assert not settle()
    after = _tree(memory)
    assert after.pop("sync_state.json") == b"two\n"
    expected = dict(before[0])
    expected.pop("sync_state.json")
    assert after == expected


def test_a_path_the_commit_names_that_the_settle_did_not_write_is_never_put_back(memory):
    page = memory / "entities" / "owner-example.md"
    page.write_bytes(page.read_bytes() + b"\nthe person's unsaved edit\n")
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        settle_guard.reported(memory, ["entities/owner-example.md", "sync_state.json", "episodes/ep_2026-11-26_001.md"])
    other = page.read_bytes() + b"and one more\n"
    page.write_bytes(other)
    assert settle_guard.put_back(mark) == 0
    assert page.read_bytes() == other, "equal to its picture when the commit named it: the settle never wrote it"
    assert not mark.recs


# --------------------------------------------------------------------------- 3. the index


def test_a_path_staged_by_another_writer_has_its_staging_back_after_a_failed_settle(memory):
    """The reviewer's case 2: another writer staged a page, the settle restaged different bytes and failed: the worktree and
    the index hold the earlier writer's bytes, and nothing else in the index is touched."""
    page = memory / "entities" / "owner-example.md"
    page.write_bytes(b"---\nname: Staged by another writer\n---\nBody.\n")
    _git(memory, "add", "entities/owner-example.md")
    elsewhere = memory / "entities" / "elsewhere.md"
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, page, b"the settle's bytes\n")
        new = memory / "entities" / "settle-new.md"
        _wrote(mark, new, b"a new page of the settle\n")
        _git(memory, "add", "entities/owner-example.md", "entities/settle-new.md")
        elsewhere.write_bytes(b"another writer's new page\n")
        _git(memory, "add", "entities/elsewhere.md")   # staged by someone else after the picture
    assert settle_guard.put_back(mark) == 0
    assert page.read_bytes() == b"---\nname: Staged by another writer\n---\nBody.\n"
    assert _git(memory, "show", ":entities/owner-example.md").startswith("---\nname: Staged by another writer")
    assert not new.exists()
    assert sorted(_git(memory, "diff", "--cached", "--name-only").split()) == ["entities/elsewhere.md", "entities/owner-example.md"]


def test_a_staged_removal_before_the_settle_is_still_a_staged_removal_after_it(memory):
    ti._entity(memory, "tool-b", type="tool", name="Tool B")
    ti._commit(memory)
    _git(memory, "rm", "-q", "entities/tool-b.md")
    gone = memory / "entities" / "tool-b.md"
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        _wrote(mark, gone, b"the settle brought it back\n")
        _git(memory, "add", "entities/tool-b.md")
    assert settle_guard.put_back(mark) == 0
    assert not gone.exists()
    assert _git(memory, "diff", "--cached", "--name-status").split() == ["D", "entities/tool-b.md"]


# --------------------------------------------------------------------------- 4. modes


def test_a_restored_file_has_the_mode_it_had(memory):
    page = memory / "entities" / "owner-example.md"
    page.write_bytes(page.read_bytes() + b"\nmine\n")
    page.chmod(0o600)
    mine = page.read_bytes()
    removed = memory / "entities" / "removed-by-the-settle.md"
    removed.write_bytes(b"a page\n")
    removed.chmod(0o640)
    ti._commit(memory)
    removed.write_bytes(b"an unsaved edit\n")
    mark = settle_guard.take(memory)
    with settle_guard.activate(mark):
        settle_guard.writing(page)
        tmp = page.with_name(".replacement")
        tmp.write_bytes(b"the settle's version\n")   # a new inode, the default mode: the writer lost the mode
        tmp.replace(page)
        settle_guard.wrote(page, b"the settle's version\n")
        _wrote(mark, removed, None)
    assert settle_guard.put_back(mark) == 0
    assert page.read_bytes() == mine and page.stat().st_mode & 0o777 == 0o600
    assert removed.read_bytes() == b"an unsaved edit\n" and removed.stat().st_mode & 0o777 == 0o640


# --------------------------------------------------------------------------- 2. the normalization branch


def _normalization(memory):
    ti._entity(memory, "tool-a", type="tool")
    ti._item(memory, "inbox-001", kind="normalization", entity_id="tool-a", raw_predicate="Built With",
             canonical_predicate="built-with", claim_id="clm_x")
    ti._commit(memory)
    d, _ = ti._decide(memory, "inbox-001")
    assert d.rule == "spelling_fold"
    d.fingerprint = (memory / "inbox" / "inbox-001.md").read_bytes()
    return d


@pytest.mark.parametrize("how_it_ends", ["fails", "cancelled"])
def test_a_normalization_settle_puts_back_on_a_worker_thread_and_after_the_resolver_is_done(memory, monkeypatch, how_it_ends):
    """The restore is never on the event loop, and a task cancelled while the resolver's thread is still writing waits that
    thread out (the page lock) before it puts anything back: the tree is whole once the task has ended."""
    import threading

    d = _normalization(memory)
    before = _state(memory)
    loop_thread = threading.current_thread()
    seen: list[tuple[str, bool]] = []
    for name in ("take", "put_back"):
        real = getattr(settle_guard, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            seen.append((_name, threading.current_thread() is loop_thread))
            return _real(*args, **kwargs)

        monkeypatch.setattr(settle_guard, name, spy)
    entered, release = threading.Event(), threading.Event()

    def slow_refusal(memory_path, message, paths, **kwargs):
        git_service._report_to_settle(memory_path, git_service._with_ledgers(memory_path, list(paths)))
        entered.set()
        assert release.wait(10)
        raise _Refused("the commit failed")

    monkeypatch.setattr(git_service, "commit_touched_sync", slow_refusal)

    async def scenario():
        task = asyncio.ensure_future(inbox_tend.apply(memory, ti._Settings(memory), d))
        for _ in range(500):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        if how_it_ends == "cancelled":
            task.cancel()
            await asyncio.sleep(0.05)   # the resolver's thread is still inside its commit, holding the lock
            assert not (memory / "inbox" / "inbox-001.md").exists(), "nothing was put back under a write still running"
        release.set()
        if how_it_ends == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 20)
        else:
            assert await asyncio.wait_for(task, 20) is False

    asyncio.run(scenario())
    assert _state(memory) == before
    assert ("take", False) in seen and ("put_back", False) in seen and not any(on_loop for _, on_loop in seen)


def test_a_tree_git_cannot_list_settles_nothing(memory, monkeypatch):
    settle, _written, _paths = _retirement(memory)
    before = _state(memory)

    def unreadable(*args, **kwargs):
        raise git_service.GitError("status failed")

    monkeypatch.setattr(git_service, "_git_sync", lambda memory_path, *args: unreadable() if args[0] == "status" else _REAL_GIT(memory_path, *args))
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
