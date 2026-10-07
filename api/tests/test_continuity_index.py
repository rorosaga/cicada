"""G110 slice 1a T3: the disposable continuity index (plan C2, as amended in
fix round 2).

Heads only inside a hook request; filter by the exact folder before any order;
persisted beside the registry in the guarded continuity home — never inside a
bank, and no git anywhere on this path — else in memory; never an error."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time

import pytest

from _continuity_fixtures import CWD, at, sid, write_other_episode, write_session
from api.services import continuity, continuity_sessions, markdown_parser

GIT = shutil.which("git")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    continuity.reset()
    m = tmp_path / "memory"
    (m / "episodes").mkdir(parents=True)
    return m


def _refresh(bank, **kw):
    kw.setdefault("deadline", None)
    return continuity.refresh_index(bank, bank_paths=(bank,), **kw)


def _select(bank, snap):
    return continuity.select(snap, {}, cwd=CWD, exclude_session=sid(99))


def test_the_latest_session_is_found_behind_600_newer_unrelated_episodes(bank):
    write_session(bank, 1, [("user", "alpha work"), ("assistant", "ok")], start=100)
    for i in range(600):
        write_other_episode(bank, i)
    for i in range(5):
        write_session(bank, 10 + i, [("user", "elsewhere"), ("assistant", "ok")], cwd=f"/home/example/p{i}", start=200)
    snap = _refresh(bank)
    sel = _select(bank, snap)
    assert sel.kind == "latest" and sel.chosen[1]["id"] == "ep_2026-09-03_001" and snap.complete


def test_a_fresh_mtime_never_outranks_captured_activity(bank):
    old = write_session(bank, 1, [("user", "old"), ("assistant", "ok")], start=0)
    write_session(bank, 2, [("user", "new"), ("assistant", "ok")], start=100)
    os.utime(old, (time.time() + 60, time.time() + 60))          # touched by Sleep or a copy
    assert _select(bank, _refresh(bank)).chosen[1]["id"] == "ep_2026-09-03_002"


def test_a_deleted_episode_drops_its_row(bank):
    p = write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    assert _refresh(bank).rows
    p.unlink()
    assert _refresh(bank).rows == {}


def test_an_oversized_head_is_unreadable_and_never_fully_parsed_in_a_hook(bank, monkeypatch):
    write_session(bank, 1, [("user", "a"), ("assistant", "b")], extra_meta={"zz_note": "x" * 20_000}, start=100)
    write_session(bank, 2, [("user", "c"), ("assistant", "d")], start=0)
    calls = []
    real = markdown_parser.parse
    monkeypatch.setattr(continuity.markdown_parser, "parse", lambda p: calls.append(p) or real(p))
    snap = _refresh(bank, deadline=time.monotonic() + 5)
    assert not snap.complete and snap.unreadable == 1 and calls == []
    assert [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_002"]
    tool = _refresh(bank, allow_full_parse=20)
    assert tool.complete and len(tool.rows) == 2 and len(calls) == 1


def test_a_long_folder_path_is_read_from_the_head(bank):
    deep = "/home/example/" + "/".join(["a long folder name with spaces"] * 120)
    write_session(bank, 1, [("user", "a"), ("assistant", "b")], cwd=deep)
    snap = _refresh(bank)
    row = next(iter(snap.rows.values()))
    assert snap.complete and row["cwd_hash"] == continuity_sessions.cwd_hash(deep)
    assert "project_dir" not in row


def test_concurrent_refreshes_read_the_same_rows(bank):
    for i in range(40):
        write_session(bank, i + 1, [("user", f"q{i}"), ("assistant", "ok")], start=i)
    out = []

    def run():
        out.append(sorted(r["id"] for r in _refresh(bank).rows.values()))

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(out) == 4 and all(o == out[0] for o in out) and len(out[0]) == 40


def test_a_scan_error_keeps_the_known_rows_and_is_incomplete(bank, monkeypatch):
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    assert _refresh(bank).complete
    real = os.scandir

    def denied(path):
        if str(path).endswith("episodes"):
            raise PermissionError(13, "denied")
        return real(path)

    monkeypatch.setattr(continuity.os, "scandir", denied)
    snap = _refresh(bank)
    assert not snap.complete and [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_001"]


def test_a_missing_episodes_directory_is_a_complete_empty_answer(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    continuity.reset()
    empty = tmp_path / "empty"
    empty.mkdir()
    snap = continuity.refresh_index(empty, bank_paths=(empty,), deadline=None)
    assert snap.rows == {} and snap.complete


def test_a_file_that_vanishes_between_listing_and_stat_costs_only_itself(bank, monkeypatch):
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    write_session(bank, 2, [("user", "c"), ("assistant", "d")])
    real = os.scandir

    class Entry:
        def __init__(self, e):
            self._e, self.name, self.path = e, e.name, e.path

        def is_file(self, follow_symlinks=True):
            return self._e.is_file(follow_symlinks=follow_symlinks)

        def stat(self, follow_symlinks=True):
            if self.name == "ep_2026-09-03_002.md":
                raise FileNotFoundError(2, "gone")
            return self._e.stat(follow_symlinks=follow_symlinks)

    class Scan:
        def __init__(self, path):
            self._it = real(path)

        def __enter__(self):
            return (Entry(e) for e in self._it)

        def __exit__(self, *a):
            self._it.close()

    monkeypatch.setattr(continuity.os, "scandir", Scan)
    snap = _refresh(bank)
    assert [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_001"] and snap.complete


def test_an_explicit_episode_beyond_the_parse_allowance_is_looked_up_directly(bank):
    for i in range(21):
        write_session(bank, i + 1, [("user", f"q{i}"), ("assistant", "ok")], extra_meta={"zz": "x" * 20_000},
                      start=i)
    ctx = continuity.assemble(bank, bank_paths=(bank,), harness=None, session_id=None, cwd=CWD,
                              session="ep_2026-09-03_001", allow_full_parse=continuity.TOOL_UNREADABLE_PARSES)
    assert ctx.selection.kind == "explicit" and ctx.chosen.episode_id == "ep_2026-09-03_001"


def test_an_explicit_session_id_missed_by_an_incomplete_search_says_so(bank):
    for i in range(21):
        write_session(bank, i + 1, [("user", f"q{i}"), ("assistant", "ok")], extra_meta={"zz": "x" * 20_000},
                      start=i)
    ctx = continuity.assemble(bank, bank_paths=(bank,), harness=None, session_id=None, cwd=CWD,
                              session=sid(1), allow_full_parse=0)
    text = continuity.full_text(ctx)
    assert "could not establish" in text and "No captured session in this bank matches" not in text


A_TURNS_SHORT = [("user", "a"), ("assistant", "b")]


A_TURNS_SHORT = [("user", "a"), ("assistant", "b")]


def _index(bank):
    return continuity.index_path(bank, (bank,))


@pytest.mark.parametrize("junk", ['{"schema": 99, "entries": {}}', "[]", "not json",
                                  '{"schema": 1, "entries": {"ep_x.md": [1, 2, {"id": "../x"}]}}'])
def test_a_wrong_or_corrupt_index_is_rebuilt(bank, junk):
    write_session(bank, 1, A_TURNS_SHORT)
    _index(bank).write_text(junk)
    continuity.reset()
    snap = _refresh(bank)
    assert [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_001"]


# --- fix round 2: the index lives beside the registry, never in a bank --------


def test_the_index_is_written_beside_the_registry_never_in_the_bank(bank):
    write_session(bank, 1, A_TURNS_SHORT)
    _refresh(bank)
    target = _index(bank)
    assert target.parent == continuity_sessions.continuity_home((bank,))
    assert target.name == f"{continuity_sessions.bank_file_id(bank)}.index.json"
    doc = json.loads(target.read_text())
    assert doc["schema"] == 2 and "ep_2026-09-03_001.md" in doc["entries"]
    assert (target.stat().st_mode & 0o777) == 0o600
    assert not [p for p in bank.rglob("*") if "index" in p.name or p.name.endswith(".tmp")]


@pytest.mark.skipif(GIT is None, reason="git not installed")
def test_a_git_bank_stays_clean_and_no_git_runs(bank, monkeypatch):
    subprocess.run([GIT, "init", "-q", str(bank)], check=True)
    write_session(bank, 1, A_TURNS_SHORT)
    before = subprocess.run([GIT, "-C", str(bank), "status", "--porcelain", "--untracked-files=all"],
                            capture_output=True, text=True, check=True).stdout

    def no_git(*a, **k):
        raise AssertionError("no git on the continuity path")

    monkeypatch.setattr(subprocess, "run", no_git)
    snap = _refresh(bank)
    monkeypatch.undo()
    assert snap.rows
    after = subprocess.run([GIT, "-C", str(bank), "status", "--porcelain", "--untracked-files=all"],
                           capture_output=True, text=True, check=True).stdout
    assert after == before


def test_an_older_in_bank_index_is_ignored_and_never_deleted(bank):
    write_session(bank, 1, A_TURNS_SHORT)
    stale = bank / "continuity_index.json"
    stale.write_text(json.dumps({"schema": 1, "entries": {"ep_2026-09-03_999.md": [1, 2, None]}}))
    snap = _refresh(bank)
    assert [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_001"]
    assert stale.exists() and "ep_2026-09-03_999.md" in stale.read_text()


@pytest.mark.parametrize("where", ["bank", "root", "alias"])
def test_a_home_inside_a_bank_creates_nothing_and_keeps_the_index_in_memory(tmp_path, monkeypatch, where):
    continuity.reset()
    root = tmp_path / "memory"
    bank = root / "banks" / "alpha"
    (bank / "episodes").mkdir(parents=True)
    write_session(bank, 1, A_TURNS_SHORT)
    if where == "alias":
        link = tmp_path / "alias"
        link.symlink_to(bank, target_is_directory=True)
        home = link / "home"
    else:
        home = (bank if where == "bank" else root) / "home"
    monkeypatch.setenv("CICADA_HOME", str(home))
    snap = continuity.refresh_index(bank, bank_paths=(root, bank), deadline=None)
    assert snap.rows and continuity.index_path(bank, (root, bank)) is None and not home.exists()
    assert continuity.refresh_index(bank, bank_paths=(root, bank), deadline=None).rows    # from memory


def test_the_index_survives_a_restart_without_rereading_heads(bank, monkeypatch):
    write_session(bank, 1, A_TURNS_SHORT)
    write_session(bank, 2, [("user", "c"), ("assistant", "d")], extra_meta={"zz_note": "x" * 20_000})
    tool = _refresh(bank, allow_full_parse=20)                  # the tool recovers the oversized head
    assert len(tool.rows) == 2 and _index(bank).exists()
    continuity._MEMO.clear()                                    # a new process: nothing in memory
    reads = []
    real = continuity.read_head
    monkeypatch.setattr(continuity, "read_head", lambda p: reads.append(p) or real(p))
    hook = _refresh(bank, deadline=time.monotonic() + 5)        # hook mode: no full parse allowed
    assert reads == [] and hook.complete and len(hook.rows) == 2


def test_a_symlinked_index_lock_keeps_the_index_in_memory(bank):
    home = continuity_sessions.continuity_home((bank,))
    victim = bank / "victim.md"
    victim.write_text("bank page")
    os.chmod(victim, 0o644)
    (home / f"{continuity_sessions.bank_file_id(bank)}.index.lock").symlink_to(victim)
    write_session(bank, 1, A_TURNS_SHORT)
    snap = _refresh(bank)
    assert snap.rows and not _index(bank).exists()
    assert victim.read_text() == "bank page" and (victim.stat().st_mode & 0o777) == 0o644


def test_a_symlinked_index_file_is_never_read_or_written_through(bank, tmp_path):
    write_session(bank, 1, A_TURNS_SHORT)
    outside = tmp_path / "planted.json"
    planted = json.dumps({"schema": 1, "entries": {"ep_2026-09-03_999.md": [1, 2, None]}})
    outside.write_text(planted)
    _index(bank).symlink_to(outside)
    continuity.reset()
    snap = _refresh(bank)
    assert [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_001"]
    assert outside.read_text() == planted


@pytest.mark.parametrize("fail", ["open", "flock", "write", "replace"])
def test_index_io_failures_fall_back_to_memory(bank, monkeypatch, fail):
    import errno

    write_session(bank, 1, A_TURNS_SHORT)

    def boom(*a, **k):
        raise OSError(errno.ENOLCK, "no locks available")

    if fail == "open":
        monkeypatch.setattr(continuity_sessions, "open_lock", boom)
    elif fail == "flock":
        monkeypatch.setattr(continuity.fcntl, "flock", boom)
    elif fail == "write":
        monkeypatch.setattr(continuity.json, "dump", boom)
    else:
        monkeypatch.setattr(continuity.os, "replace", boom)
    snap = _refresh(bank)
    assert [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_001"]
    home = continuity_sessions.continuity_home((bank,))
    assert not _index(bank).exists() and not list(home.glob(".*.tmp"))
    ctx = continuity.assemble(bank, bank_paths=(bank,), harness=None, session_id=None, cwd=CWD)
    assert "ep_2026-09-03_001" in continuity.full_text(ctx)


# --- slice 1b P0: no plaintext folder or conversation outside the bank -------


def test_private_path_and_text_stay_in_the_episode_across_index_restart(bank, monkeypatch, capfd):
    cwd = "/home/example/private-cwd-sentinel/alpha-project"
    turns = [("user", "private-title-and-request-sentinel"),
             ("assistant", "private-reply-sentinel")]
    source = write_session(bank, 1, turns, cwd=cwd)
    before = source.read_bytes()
    assert continuity_sessions.apply(
        bank, bank_paths=(bank,), harness="claude-code", session_id=sid(99), deadline=None,
        events={"cwd_hash": continuity_sessions.cwd_hash(cwd), "continues": "ep_2026-09-03_001",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())},
    ) == "ok"
    snap = _refresh(bank)
    row = next(iter(snap.rows.values()))
    assert row["cwd_hash"] == continuity_sessions.cwd_hash(cwd)
    assert "project_dir" not in row

    def no_head_read(path):
        raise AssertionError("a clean persisted hash row must survive restart")

    continuity.reset()
    monkeypatch.setattr(continuity, "read_head", no_head_read)
    ctx = continuity.assemble(bank, bank_paths=(bank,), harness=None, session_id=None, cwd=cwd)
    assert ctx.chosen.episode_id == "ep_2026-09-03_001"
    assert ctx.chosen.project_dir == cwd
    assert all(text in ctx.chosen.body for _, text in turns)
    assert source.read_bytes() == before
    home = continuity_sessions.continuity_home((bank,))
    for artifact in home.rglob("*"):
        if artifact.is_file():
            raw = artifact.read_bytes()
            for sentinel in (cwd, *(text for _, text in turns)):
                assert sentinel.encode() not in raw, artifact.name
    console = capfd.readouterr()
    assert all(sentinel not in console.out + console.err for sentinel in (cwd, *(text for _, text in turns)))


@pytest.mark.parametrize("state", ["populated", "empty", "missing", "unreadable"])
def test_old_path_index_is_replaced_even_without_readable_episodes(bank, monkeypatch, state):
    cwd = "/home/example/old-cached-path-sentinel"
    source = write_session(bank, 1, A_TURNS_SHORT, cwd=cwd)
    before = source.read_bytes()
    stamp = source.stat()
    row = continuity.read_head(source)
    row.pop("cwd_hash", None)
    row["project_dir"] = cwd
    target = _index(bank)
    target.write_text(json.dumps({"schema": 1, "entries": {
        source.name: [stamp.st_mtime_ns, stamp.st_size, row]}}))
    if state in ("empty", "missing"):
        source.unlink()
    if state == "missing":
        source.parent.rmdir()
    if state == "unreadable":
        real_scan = continuity.os.scandir

        def denied(path):
            if str(path) == str(source.parent):
                raise PermissionError("synthetic scan denied")
            return real_scan(path)

        monkeypatch.setattr(continuity.os, "scandir", denied)
    reads = []
    real_head = continuity.read_head
    monkeypatch.setattr(continuity, "read_head", lambda path: reads.append(path) or real_head(path))
    continuity.reset()
    snap = _refresh(bank)
    persisted = json.loads(target.read_text())
    assert persisted["schema"] == 2
    assert cwd not in target.read_text() and "project_dir" not in target.read_text()
    if state == "populated":
        assert reads == [source] and snap.complete
        assert continuity.select(snap, {}, cwd=cwd, exclude_session=None).chosen[1]["id"] == row["id"]
        assert source.read_bytes() == before
    else:
        assert reads == [] and snap.rows == {}
        assert snap.complete is (state != "unreadable")
        if state == "unreadable":
            assert source.read_bytes() == before


def test_extra_cached_path_and_text_fields_are_removed_before_reuse(bank):
    source = write_session(bank, 1, A_TURNS_SHORT)
    _refresh(bank)
    target = _index(bank)
    doc = json.loads(target.read_text())
    doc["entries"][source.name][2].update(project_dir="cached-path-sentinel", title="cached-title-sentinel")
    doc["extra"] = "cached-body-sentinel"
    target.write_text(json.dumps(doc))
    continuity.reset()
    snap = _refresh(bank)
    assert _select(bank, snap).chosen[1]["id"] == "ep_2026-09-03_001"
    assert "sentinel" not in target.read_text()


def test_a_forged_cached_folder_hash_cannot_supply_another_folders_context(bank):
    source = write_session(bank, 1, [("user", "source-only-context-sentinel"), ("assistant", "ok")])
    _refresh(bank)
    target = _index(bank)
    doc = json.loads(target.read_text())
    other = "/home/example/another-project"
    doc["entries"][source.name][2]["cwd_hash"] = continuity_sessions.cwd_hash(other)
    target.write_text(json.dumps(doc))
    continuity.reset()
    ctx = continuity.assemble(bank, bank_paths=(bank,), harness=None, session_id=None, cwd=other)
    assert ctx.chosen is None
    assert "source-only-context-sentinel" not in continuity.full_text(ctx)


def test_changed_source_folder_is_revalidated_without_trusting_frontmatter_hash(bank):
    source = write_session(bank, 1, A_TURNS_SHORT)
    chosen = _select(bank, _refresh(bank)).chosen
    doc = markdown_parser.parse(source)
    doc.frontmatter["project_dir"] = "/home/example/another-project"
    doc.frontmatter["cwd_hash"] = continuity_sessions.cwd_hash(CWD)
    markdown_parser.write(source, doc.frontmatter, doc.body)
    assert continuity.view(bank, chosen) is None
    snap = _refresh(bank)
    assert _select(bank, snap).chosen is None


@pytest.mark.parametrize("bad_hash", ["not-a-hash", "a" * 15, "A" * 16, 42, None])
def test_malformed_cached_hash_is_rebuilt_from_source(bank, bad_hash):
    source = write_session(bank, 1, A_TURNS_SHORT)
    _refresh(bank)
    target = _index(bank)
    doc = json.loads(target.read_text())
    doc["entries"][source.name][2]["cwd_hash"] = bad_hash
    target.write_text(json.dumps(doc))
    continuity.reset()
    snap = _refresh(bank)
    assert _select(bank, snap).chosen[1]["cwd_hash"] == continuity_sessions.cwd_hash(CWD)
