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


# --- Finding 4, closed by admission (G183): a merge admitted before Sleep's flip commits before Sleep reads ---------

from api.services import write_admission


def _flip_when_admitted(bank, state, seen) -> threading.Thread:
    """Sleep's order once the merge holds admission: the flag first, then the wait; records what Sleep would read."""
    def flip():
        deadline = time.monotonic() + 10
        while write_admission.holders(bank) == 0:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        state["writing"] = True
        seen["drained"] = write_admission.wait_for_writers(bank, give_up_after=10)
        seen["head_at_read"] = _head(bank)
    t = threading.Thread(target=flip)
    t.start()
    return t


@pytest.mark.parametrize("held", ["page", "git"])
def test_a_window_that_opens_while_an_admitted_merge_waits_for_a_lock_waits_for_its_commit(bank, monkeypatch, held):
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "get_sleep_state",
                        lambda: SimpleNamespace(status="running", drain_run=True, writing=state["writing"]))
    judge = lambda *a: {"verdict": "same", "confidence": 0.95, "winner": "esa"}   # noqa: E731
    result: dict = {}
    seen: dict = {}
    lock = page_lock.page_lock(bank) if held == "page" else git_service.write_lock(bank)
    with lock:
        t = threading.Thread(target=lambda: result.update(_sweep(
            bank, pairs=[("esa", "esta"), ("bob-example", "carol-example")], judge=judge,
            may_write=lambda: not write_admission.holding())))
        t.start()
        flip = _flip_when_admitted(bank, state, seen)
        flip.join(0.3)
        assert flip.is_alive(), "Sleep must not read while an admitted merge is mid-transaction"
    t.join(10)
    flip.join(10)

    assert result["merged"] == [("esta", "esa")], "the admitted merge finishes and commits"
    assert result["stopped_for_sleep"] is True, "the next pair sees the window and stops"
    assert seen["drained"] is True and seen["head_at_read"] == _head(bank)
    assert _git(bank, "status", "--porcelain") == ""


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


# --- Fix round 2: the merge's footprint is known before any write, and nothing outside it is touched ---------------

import os
import stat

from api.services import entity_merge


def _index(memory) -> str:
    return _git(memory, "ls-files", "-s", "-z")


def test_an_unmerged_reference_page_refuses_the_merge_and_keeps_every_index_stage(bank):
    rel = "entities/bob-example.md"
    blob = _git(bank, "rev-parse", f"HEAD:{rel}").strip()
    info = "".join(f"100644 {blob} {n}\t{rel}\n" for n in (1, 2, 3))
    subprocess.run(["git", "update-index", "--force-remove", "--", rel], cwd=bank, check=True)
    subprocess.run(["git", "update-index", "--index-info"], cwd=bank, input=info, text=True, check=True)
    before_index, before, head = _index(bank), _files(bank), _head(bank)

    out = _sweep(bank)

    assert out["merged"] == [] and out["skipped_unsafe"] == [("esta", "esa")]
    assert _index(bank) == before_index, "all three conflict stages still there"
    assert _files(bank) == before and _head(bank) == head


def test_a_symlinked_winner_refuses_the_merge_and_leaves_link_and_target_alone(bank):
    target = bank / "target.md"
    target.write_bytes((bank / "entities" / "esa.md").read_bytes())
    (bank / "entities" / "esa.md").unlink()
    os.symlink("../target.md", bank / "entities" / "esa.md")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "link the winner")
    target_bytes, index, head = target.read_bytes(), _index(bank), _head(bank)

    out = _sweep(bank)

    assert out["skipped_unsafe"] == [("esta", "esa")]
    assert os.readlink(bank / "entities" / "esa.md") == "../target.md"
    assert target.read_bytes() == target_bytes
    assert (bank / "entities" / "esta.md").exists()
    assert _index(bank) == index and _head(bank) == head
    assert _git(bank, "status", "--porcelain") == ""


def test_an_executable_loser_comes_back_with_its_mode_after_a_failed_commit(bank, monkeypatch):
    loser = bank / "entities" / "esta.md"
    loser.chmod(0o755)
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "exec loser")
    before, index, head = _files(bank), _index(bank), _head(bank)

    def failing_commit(memory_path, message, paths):
        raise git_service.GitError("simulated")

    monkeypatch.setattr(git_service, "commit_paths_sync", failing_commit)
    out = _sweep(bank)

    assert out["failed"] == [("esta", "esa")]
    assert stat.S_IMODE(loser.stat().st_mode) == 0o755
    assert _files(bank) == before and _index(bank) == index and _head(bank) == head
    assert _git(bank, "status", "--porcelain") == ""


def _unguarded_write_after_the_merge(monkeypatch, bank):
    """Sleep takes no page lock: a page the merge never touches is written while the transaction runs."""
    real = ds.merge_entities

    def merge_then_sleep_writes(memory_path, **kw):
        result = real(memory_path, **kw)
        with open(bank / "entities" / "carol-example.md", "a") as fh:
            fh.write("\nwritten by an unguarded writer\n")
        return result

    monkeypatch.setattr(ds, "merge_entities", merge_then_sleep_writes)


def test_an_unguarded_write_to_an_unrelated_page_never_rides_the_merge_commit(bank, monkeypatch):
    _unguarded_write_after_the_merge(monkeypatch, bank)
    out = _sweep(bank)
    assert out["merged"] == [("esta", "esa")]
    assert "entities/carol-example.md" not in _git(bank, "show", "--name-only", "--format=", "HEAD").split()
    assert "written by an unguarded writer" in (bank / "entities" / "carol-example.md").read_text()
    assert _git(bank, "status", "--porcelain").strip() == "M entities/carol-example.md"


def test_an_unguarded_write_to_an_unrelated_page_is_never_reverted_by_a_recovery(bank, monkeypatch):
    _unguarded_write_after_the_merge(monkeypatch, bank)

    def failing_commit(memory_path, message, paths):
        raise git_service.GitError("simulated")

    monkeypatch.setattr(git_service, "commit_paths_sync", failing_commit)
    out = _sweep(bank)
    assert out["failed"] == [("esta", "esa")]
    assert "written by an unguarded writer" in (bank / "entities" / "carol-example.md").read_text()
    assert (bank / "entities" / "esta.md").exists()
    assert _git(bank, "status", "--porcelain").strip() == "M entities/carol-example.md"


def test_a_merge_that_writes_outside_its_footprint_is_put_back_and_stops_the_sweep(bank, monkeypatch):
    real = ds.merge_entities

    def merge_claiming_more(memory_path, **kw):
        result = real(memory_path, **kw)
        result["paths"] = [*result["paths"], "entities/carol-example.md"]
        return result

    monkeypatch.setattr(ds, "merge_entities", merge_claiming_more)
    before, head = _files(bank), _head(bank)
    out = _sweep(bank, pairs=[("esa", "esta"), ("bob-example", "carol-example")])
    assert out["recovery_failed"] is True and out["merged"] == []
    assert _files(bank) == before and _head(bank) == head


def test_the_footprint_is_exactly_what_the_merge_writes(tmp_path):
    """One matcher: the footprint and `merge_entities`' repointing are the same per-page code."""
    ents = tmp_path / "entities"
    ents.mkdir()
    _page(ents, "alpha-project", "Alpha Project")
    _page(ents, "beta-project", "Beta Project")
    _page(ents, "by-id", "by-id", related=["beta-project"])
    _page(ents, "by-name", "by-name", related=["BETA PROJECT"])
    _page(ents, "by-link", "by-link", "## Summary\nsee [[Beta Project|the beta]] and [[beta-project#notes]]\n")
    _page(ents, "by-source", "by-source", sources=[{"ref": "https://example.com/b", "entity": "beta-project"}])
    _page(ents, "by-claim", "by-claim",
          "## Summary\nx\n\n```claims\n- id: c1\n  subject: by-claim\n  predicate: works_on\n"
          "  object: beta-project\n  object_kind: entity\n```\n")
    _page(ents, "unrelated", "unrelated", "## Summary\nmentions alpha only: [[Alpha Project]]\n")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "beta-project", "target": "by-id", "label": "x"}]}))

    footprint = entity_merge.merge_footprint(tmp_path, loser_id="beta-project", winner_id="alpha-project")
    written = entity_merge.merge_entities(tmp_path, loser_id="beta-project", winner_id="alpha-project")["paths"]

    assert set(footprint) == set(written)
    assert {"entities/by-id.md", "entities/by-name.md", "entities/by-link.md", "entities/by-source.md",
            "entities/by-claim.md", "graph_edges.yaml"} <= set(footprint)
    assert "entities/unrelated.md" not in footprint


def test_the_footprint_leaves_out_a_graph_no_edge_of_which_names_the_loser(tmp_path):
    ents = tmp_path / "entities"
    ents.mkdir()
    _page(ents, "alpha-project", "Alpha Project")
    _page(ents, "beta-project", "Beta Project")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": [
        {"source": "alpha-project", "target": "gamma", "label": "x"}]}))
    assert "graph_edges.yaml" not in entity_merge.merge_footprint(tmp_path, "beta-project", "alpha-project")
