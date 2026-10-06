"""G110 slice 1a T3: the disposable continuity index (plan C2).

Heads only inside a hook request; filter by the exact folder before any
order; persisted only when git is known to ignore it and a lock outside every
bank exists; otherwise in memory; never an error."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time

import pytest

from _continuity_fixtures import CWD, at, sid, write_other_episode, write_session
from api.services import bank_registry, continuity, markdown_parser

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


@pytest.mark.parametrize("junk", ['{"schema": 99, "entries": {}}', "[]", "not json",
                                  '{"schema": 1, "entries": {"ep_x.md": [1, 2, {"id": "../x"}]}}'])
def test_a_wrong_or_corrupt_index_is_rebuilt(bank, junk):
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    (bank / continuity.INDEX_FILE).write_text(junk)
    continuity.reset()
    snap = _refresh(bank)
    assert [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_001"]


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
    assert snap.complete and next(iter(snap.rows.values()))["project_dir"] == deep


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


def test_no_git_persists_the_index(bank):
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    _refresh(bank)
    doc = json.loads((bank / continuity.INDEX_FILE).read_text())
    assert doc["schema"] == 1 and "ep_2026-09-03_001.md" in doc["entries"]
    assert not list(bank.glob(".*.tmp"))


@pytest.mark.skipif(GIT is None, reason="git not installed")
def test_a_git_bank_is_excluded_before_the_index_exists_and_stays_clean(bank):
    subprocess.run([GIT, "init", "-q", str(bank)], check=True)
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    _refresh(bank)
    assert (bank / continuity.INDEX_FILE).exists()
    assert bank_registry.derived_exclusion_state(bank, continuity.INDEX_FILE) == "excluded"
    status = subprocess.run([GIT, "-C", str(bank), "status", "--porcelain", "--untracked-files=all"],
                            capture_output=True, text=True, check=True).stdout
    assert continuity.INDEX_FILE not in status


@pytest.mark.skipif(GIT is None, reason="git not installed")
def test_an_unprotectable_git_bank_keeps_the_index_in_memory(bank, monkeypatch):
    subprocess.run([GIT, "init", "-q", str(bank)], check=True)
    monkeypatch.setattr(bank_registry, "_append_exclude", lambda *a, **k: False)   # the write "failed"
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    snap = _refresh(bank)
    assert snap.rows and not (bank / continuity.INDEX_FILE).exists()
    assert _refresh(bank).rows                        # served from memory


def test_a_home_inside_the_bank_creates_no_lock_and_no_file(bank, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(bank / "home"))
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    snap = _refresh(bank)
    assert snap.rows and not (bank / continuity.INDEX_FILE).exists() and not (bank / "home").exists()


def test_derived_exclusion_state(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert bank_registry.derived_exclusion_state(plain, "x.json") == "no_git"
    if GIT:
        repo = tmp_path / "repo"
        subprocess.run([GIT, "init", "-q", str(repo)], check=True)
        assert bank_registry.derived_exclusion_state(repo, "x.json") == "unprotected"
        (repo / ".gitignore").write_text("x.json\n")
        assert bank_registry.derived_exclusion_state(repo, "x.json") == "excluded"


def test_the_index_is_a_derived_artifact():
    assert continuity.INDEX_FILE in bank_registry.DERIVED_ARTIFACTS


# --- fix round 1, finding 2: git itself decides whether the index is ignored ----


def _git(repo, *args):
    return subprocess.run([GIT, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.mark.skipif(GIT is None, reason="git not installed")
@pytest.mark.parametrize("where", ["gitignore", "exclude"])
def test_a_later_negation_keeps_the_index_in_memory(bank, where):
    subprocess.run([GIT, "init", "-q", str(bank)], check=True)
    if where == "gitignore":
        (bank / ".gitignore").write_text("continuity_index.json\n!continuity_index.json\n")
    else:
        (bank / ".git" / "info").mkdir(parents=True, exist_ok=True)
        (bank / ".git" / "info" / "exclude").write_text("continuity_index.json\n")
        (bank / ".gitignore").write_text("!continuity_index.json\n")
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    assert bank_registry.derived_exclusion_state(bank, continuity.INDEX_FILE) == "unprotected"
    snap = _refresh(bank)
    assert snap.rows and not (bank / continuity.INDEX_FILE).exists()
    assert continuity.INDEX_FILE not in _git(bank, "status", "--porcelain", "--untracked-files=all")


@pytest.mark.skipif(GIT is None, reason="git not installed")
def test_an_already_tracked_index_is_never_written(bank):
    subprocess.run([GIT, "init", "-q", str(bank)], check=True)
    _git(bank, "config", "user.email", "t@example.com")
    _git(bank, "config", "user.name", "t")
    (bank / continuity.INDEX_FILE).write_text("{}")
    _git(bank, "add", "-f", continuity.INDEX_FILE)
    _git(bank, "commit", "-qm", "tracked by mistake")
    (bank / ".git" / "info" / "exclude").write_text("continuity_index.json\n")
    assert bank_registry.derived_exclusion_state(bank, continuity.INDEX_FILE) == "unprotected"
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    assert _refresh(bank).rows
    assert (bank / continuity.INDEX_FILE).read_text() == "{}"      # left exactly as it was


@pytest.mark.skipif(GIT is None, reason="git not installed")
def test_a_busy_bank_lock_is_treated_as_unprotected(bank):
    from api.services import git_service

    subprocess.run([GIT, "init", "-q", str(bank)], check=True)
    (bank / ".gitignore").write_text("continuity_index.json\n")
    lock = git_service.write_lock(bank)
    done = threading.Event()
    result = {}

    def hold():
        with lock:
            done.wait(2)

    t = threading.Thread(target=hold)
    t.start()
    time.sleep(0.05)
    try:
        result["state"] = bank_registry.derived_exclusion_state(bank, continuity.INDEX_FILE, lock_timeout=0.05)
    finally:
        done.set()
        t.join()
    assert result["state"] == "unprotected"
    assert bank_registry.derived_exclusion_state(bank, continuity.INDEX_FILE) == "excluded"


# --- fix round 1, finding 3: the index lock and the index never follow a symlink --


def test_a_symlinked_index_lock_keeps_the_index_in_memory(bank):
    from api.services import continuity_sessions

    home = continuity_sessions.continuity_home((bank,))
    victim = bank / "victim.md"
    victim.write_text("bank page")
    os.chmod(victim, 0o644)
    (home / f"{continuity_sessions.bank_file_id(bank)}.index.lock").symlink_to(victim)
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    snap = _refresh(bank)
    assert snap.rows and not (bank / continuity.INDEX_FILE).exists()
    assert victim.read_text() == "bank page" and (victim.stat().st_mode & 0o777) == 0o644


def test_a_symlinked_index_file_is_never_read(bank, tmp_path):
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    outside = tmp_path / "planted.json"
    outside.write_text(json.dumps({"schema": 1, "entries": {"ep_2026-09-03_999.md": [1, 2, None]}}))
    (bank / continuity.INDEX_FILE).symlink_to(outside)
    continuity.reset()
    snap = _refresh(bank)
    assert [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_001"]
    assert json.loads(outside.read_text())["entries"] == {"ep_2026-09-03_999.md": [1, 2, None]}


# --- fix round 1, finding 4: the persisted index survives a restart -------------


def test_a_persisted_index_is_reused_after_a_restart_without_rereading_heads(bank, monkeypatch):
    write_session(bank, 1, [("user", "a"), ("assistant", "b")])
    write_session(bank, 2, [("user", "c"), ("assistant", "d")], extra_meta={"zz_note": "x" * 20_000})
    tool = _refresh(bank, allow_full_parse=20)                  # the tool recovers the oversized head
    assert len(tool.rows) == 2 and (bank / continuity.INDEX_FILE).exists()
    continuity._MEMO.clear()                                    # a new process: nothing in memory
    reads = []
    real = continuity.read_head
    monkeypatch.setattr(continuity, "read_head", lambda p: reads.append(p) or real(p))
    hook = _refresh(bank, deadline=time.monotonic() + 5)        # hook mode: no full parse allowed
    assert reads == [] and hook.complete and len(hook.rows) == 2


# --- fix round 1, finding 5: a failed scan is never an authoritative absence ----


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


# --- fix round 1, finding 6: lock and write failures stay inside the index -------


@pytest.mark.parametrize("fail", ["open", "flock", "write", "replace"])
def test_index_io_failures_fall_back_to_memory(bank, monkeypatch, fail):
    import errno
    import fcntl as real_fcntl

    from api.services import continuity_sessions

    write_session(bank, 1, A_TURNS_SHORT)

    def boom(*a, **k):
        raise OSError(errno.ENOLCK, "no locks available")

    if fail == "open":
        monkeypatch.setattr(continuity_sessions, "open_lock", boom)
    elif fail == "flock":
        monkeypatch.setattr(continuity.fcntl, "flock", boom)
    elif fail == "write":
        monkeypatch.setattr(continuity.Path, "write_text", boom)
    else:
        monkeypatch.setattr(continuity.os, "replace", boom)
    snap = _refresh(bank)
    assert [r["id"] for r in snap.rows.values()] == ["ep_2026-09-03_001"]
    assert not (bank / continuity.INDEX_FILE).exists() and not list(bank.glob(".*.tmp"))
    ctx = continuity.assemble(bank, bank_paths=(bank,), harness=None, session_id=None, cwd=CWD)
    assert "ep_2026-09-03_001" in continuity.full_text(ctx)
    assert real_fcntl is not None


A_TURNS_SHORT = [("user", "a"), ("assistant", "b")]
