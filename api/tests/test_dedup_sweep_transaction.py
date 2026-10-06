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
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.services import dedup_sweep as ds


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
