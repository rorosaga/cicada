"""G183(e) fix round 1 — a dedup merge is one transaction that is wholly its own.

Each merge runs under the page lock and the bank's git write lock from its dirty check to its commit or recovery:
- a merge whose changed paths were already dirty (winner, loser, a referencing page, the graph) is refused — and a
  merge that discovered such a path only after running is put back byte-for-byte; nothing anyone else wrote is ever
  committed under ``Cicada-Author: cicada``;
- a failed commit restores the exact pre-merge bytes and index entries (never HEAD), and an in-process whole-bank
  writer cannot slip in between the failure and the recovery;
- a recovery that fails is reported and stops the sweep;
- the Sleep write window is re-asked after the page lock is acquired.
Synthetic banks only.
"""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.services import dedup_sweep as ds
from api.services import git_service, page_lock, sleep_cycle


def _git(repo, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _page(ents: Path, eid: str, name: str, body: str = "## Summary\nx\n", **fm) -> None:
    front = {"name": name, "type": "person", "status": "active", "confidence": 0.6, "source_episodes": ["ep_1"], **fm}
    (ents / f"{eid}.md").write_text("---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n" + body)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    memory = tmp_path / "memory"
    ents = memory / "entities"
    ents.mkdir(parents=True)
    _page(ents, "esa", "ESA")
    _page(ents, "esta", "ESTA")
    _page(ents, "bob-example", "bob-example", "## Summary\nworks with [[ESTA]]\n")
    _page(ents, "carol-example", "carol-example")
    (memory / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "bob-example", "target": "carol-example", "label": "knows"}]}))
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


def _same(winner="esa"):
    return lambda a_body, b_body, a_id, b_id: {"verdict": "same", "confidence": 0.95, "winner": winner}


def _sweep(memory, pairs=(("esa", "esta"),), judge=None, **kw):
    return ds.dedup_sweep(memory, SimpleNamespace(), judge_fn=judge or _same(), seed_pairs=list(pairs), **kw)


def _files(memory) -> dict[str, bytes]:
    out = {p.relative_to(memory).as_posix(): p.read_bytes() for p in (memory / "entities").glob("*.md")}
    graph = memory / "graph_edges.yaml"
    if graph.exists():
        out["graph_edges.yaml"] = graph.read_bytes()
    return out


def _head(memory) -> str:
    return _git(memory, "rev-parse", "HEAD").strip()


# --- Finding 1: a merge never commits an edit that was already there ------------------------------------------------


@pytest.mark.parametrize("rel", ["entities/esa.md", "entities/esta.md", "entities/bob-example.md"])
def test_a_merge_touching_a_dirty_page_is_refused_and_the_edit_kept(bank, rel):
    with open(bank / rel, "a") as fh:
        fh.write("\nEXISTING DIRTY EDIT\n")
    before, head = _files(bank), _head(bank)

    out = _sweep(bank)

    assert out["merged"] == []
    assert out["skipped_dirty"] == [("esta", "esa")]
    assert _files(bank) == before, "every byte as it was, the dirty edit included"
    assert _head(bank) == head, "nothing committed"
    assert _git(bank, "status", "--porcelain").strip() == f"M {rel}"


def test_a_dirty_graph_the_merge_must_repoint_refuses_the_merge(bank):
    (bank / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "bob-example", "target": "carol-example", "label": "knows"},
        {"source": "esta", "target": "carol-example", "label": "knows"}]}))
    before, head = _files(bank), _head(bank)

    out = _sweep(bank)

    assert out["skipped_dirty"] == [("esta", "esa")]
    assert _files(bank) == before and _head(bank) == head


def test_a_dirty_graph_the_merge_does_not_touch_stays_out_of_its_commit(bank):
    edited = yaml.safe_dump({"edges": [
        {"source": "bob-example", "target": "carol-example", "label": "knows"},
        {"source": "carol-example", "target": "bob-example", "label": "unrelated-edit"}]})
    (bank / "graph_edges.yaml").write_text(edited)

    out = _sweep(bank)

    assert out["merged"] == [("esta", "esa")]
    files = set(_git(bank, "show", "--name-only", "--format=", "HEAD").split())
    assert files == {"entities/esa.md", "entities/esta.md", "entities/bob-example.md"}
    assert (bank / "graph_edges.yaml").read_text() == edited, "the other writer's edit is untouched"
    assert _git(bank, "status", "--porcelain").strip() == "M graph_edges.yaml"


def test_an_untracked_graph_naming_the_loser_is_never_rewritten_or_staged(bank):
    _git(bank, "rm", "-q", "--cached", "graph_edges.yaml")
    _git(bank, "commit", "-q", "-m", "untrack the graph")
    (bank / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "esta", "target": "carol-example", "label": "knows"}]}))
    before, head = _files(bank), _head(bank)

    out = _sweep(bank)

    assert out["skipped_dirty"] == [("esta", "esa")]
    assert _files(bank) == before and _head(bank) == head
    assert _git(bank, "status", "--porcelain").strip() == "?? graph_edges.yaml"


def test_unrelated_staged_content_stays_staged_and_out_of_the_commit(bank):
    (bank / "unrelated.txt").write_text("staged by someone else\n")
    _git(bank, "add", "unrelated.txt")

    out = _sweep(bank)

    assert out["merged"] == [("esta", "esa")]
    assert "unrelated.txt" not in _git(bank, "show", "--name-only", "--format=", "HEAD")
    assert _git(bank, "status", "--porcelain").strip() == "A  unrelated.txt"


def test_a_clean_merge_commits_exactly_its_changes_under_cicada(bank):
    out = _sweep(bank, engine="litellm")
    assert out["merged"] == [("esta", "esa")]
    files = set(_git(bank, "show", "--name-only", "--format=", "HEAD").split())
    assert files == {"entities/esa.md", "entities/esta.md", "entities/bob-example.md"}, "no untouched graph"
    message = _git(bank, "log", "-1", "--format=%B").splitlines()
    assert "Cicada-Author: cicada" in message and "Cicada-Engine: litellm" in message
    assert _git(bank, "status", "--porcelain") == ""


# --- Finding 2: a failed commit is put back exactly, and recovery is one locked step --------------------------------


def _fail_commit_subprocess(monkeypatch):
    """`git add` really runs; only `git commit` fails — the failure after real staging."""
    real = git_service._spawn

    def spawn(memory_path, args):
        if args and args[0] == "commit":
            return subprocess.CompletedProcess(args, 1, b"", b"simulated commit failure")
        return real(memory_path, args)

    monkeypatch.setattr(git_service, "_spawn", spawn)


def test_a_commit_that_fails_after_staging_puts_back_every_byte_and_the_index(bank, monkeypatch):
    with open(bank / "entities" / "carol-example.md", "a") as fh:
        fh.write("\npre-existing edit on a page the merge never touches\n")
    before, head = _files(bank), _head(bank)
    _fail_commit_subprocess(monkeypatch)

    out = _sweep(bank)

    assert out["merged"] == [] and out["failed"] == [("esta", "esa")]
    assert out["recovery_failed"] is False
    assert _files(bank) == before
    assert _head(bank) == head
    assert _git(bank, "status", "--porcelain").strip() == "M entities/carol-example.md", "nothing left staged"


def test_a_competing_whole_bank_writer_cannot_commit_a_failed_merge(bank, monkeypatch):
    """The reproduced interleaving: a `git add -A` writer between the failed commit and the recovery."""
    before, head = _files(bank), _head(bank)
    real_commit = git_service.commit_changes_sync
    competitor: dict = {}

    def competing():
        competitor["sha"] = real_commit(bank, "Sleep batch\n\nCicada-Author: some-model")

    def failing_commit(memory_path, message, paths):
        t = threading.Thread(target=competing)
        t.start()
        competitor["thread"] = t
        time.sleep(0.3)   # the competitor is now waiting on the bank's git write lock
        raise git_service.GitError("simulated")

    monkeypatch.setattr(git_service, "commit_paths_sync", failing_commit)
    out = _sweep(bank)
    competitor["thread"].join(10)

    assert out["failed"] == [("esta", "esa")]
    assert competitor["sha"] is None, "the recovery finished first: nothing of the merge was left to sweep"
    assert _head(bank) == head
    assert _files(bank) == before


def test_a_failed_recovery_is_reported_and_stops_the_sweep(bank, monkeypatch):
    judged = []

    def judge(a_body, b_body, a_id, b_id):
        judged.append((a_id, b_id))
        return {"verdict": "same", "confidence": 0.95, "winner": a_id}

    def failing_commit(memory_path, message, paths):
        raise git_service.GitError("simulated")

    def failing_restore(*a, **k):
        raise OSError("disk went away")

    monkeypatch.setattr(git_service, "commit_paths_sync", failing_commit)
    monkeypatch.setattr(ds, "_put_back", failing_restore)
    out = _sweep(bank, pairs=[("esa", "esta"), ("bob-example", "carol-example")], judge=judge)

    assert out["recovery_failed"] is True
    assert out["failed"] == [("esta", "esa")]
    assert judged == [("esa", "esta")], "no further pair is judged or merged"


# --- Finding 4: the window is re-asked once the page lock is held ---------------------------------------------------


def test_a_window_that_opens_while_the_merge_waits_for_the_page_lock_stops_it(bank, monkeypatch):
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "get_sleep_state",
                        lambda: SimpleNamespace(status="running", drain_run=True, writing=state["writing"]))
    judged = threading.Event()

    def judge(a_body, b_body, a_id, b_id):
        judged.set()
        return {"verdict": "same", "confidence": 0.95, "winner": "esa"}

    before, head = _files(bank), _head(bank)
    result: dict = {}
    with page_lock.page_lock(bank):
        t = threading.Thread(target=lambda: result.update(
            _sweep(bank, judge=judge, may_write=lambda: not sleep_cycle.is_writing())))
        t.start()
        assert judged.wait(5)
        time.sleep(0.3)            # past its last pre-lock check, waiting on the page lock
        state["writing"] = True    # Sleep's batch reaches Stage 2
    t.join(10)

    assert result["merged"] == []
    assert result["stopped_for_sleep"] is True
    assert _files(bank) == before and _head(bank) == head


def test_a_dry_run_also_stops_judging_once_sleep_is_writing(bank):
    state = {"writing": False}
    judged = []

    def judge(a_body, b_body, a_id, b_id):
        judged.append((a_id, b_id))
        state["writing"] = True
        return {"verdict": "different", "confidence": 0.9, "winner": None}

    out = _sweep(bank, pairs=[("esa", "esta"), ("bob-example", "carol-example")], judge=judge, dry_run=True,
                 may_write=lambda: not state["writing"])
    assert judged == [("esa", "esta")]
    assert out["stopped_for_sleep"] is True
