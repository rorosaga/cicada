"""A merge or a rename keeps every edge of ``graph_edges.yaml`` whole (2026-10-14).

Measured on the owner's bank (real values redacted): one placeholder-people merge rewrote a 45,786-edge
``graph_edges.yaml`` as 31,545 edges, and only 59 of its 14,298 claim-backed rows (``claim_id``, ``observer``,
``context``, ``valid_from`` beside ``source``/``target``/``label``) kept those fields. The cause was
``entity_merge.repoint_edges``: it deduped the WHOLE file by (source, target, label), so a claim-backed row sharing
a triple with a bare one was dropped. Every door that merges or renames a page runs it. Each one is driven here over
one synthetic file mixing bare and claim-backed edges, and the result must be exactly: every edge that did not name
the moved page, byte-for-byte and in order; every edge that did, with only that endpoint changed; nothing else gone
but a self-loop the merge made or an exact copy of an edge already there.
"""
from __future__ import annotations

import asyncio
import copy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from api.models.schemas import InboxResolveRequest
from api.services import dedup_sweep, entity_merge, inbox_service, markdown_parser, role_people
from api.services.claims import Claim, write_claims

OWNER = "alpha-owner"


def _claim_row(source, target, label, cid, observer="agent", context="general"):
    return {"source": source, "target": target, "label": label, "observer": observer, "context": context,
            "claim_id": cid, "valid_from": "2026-01-02"}


def _edges(old: str, new: str) -> list[dict]:
    """``old`` is the page that goes away (or moves), ``new`` the page it becomes."""
    return [
        {"source": "gamma", "target": "delta", "label": "uses"},
        _claim_row("gamma", "delta", "uses", "c-gd"),                       # same triple as a bare edge: both stay
        _claim_row("gamma", "delta", "uses", "c-gd-2", observer=OWNER),    # differs only in its claim fields
        {"source": "gamma", "target": "delta", "label": "uses"},           # an exact copy, untouched: stays too
        {"source": old, "target": "gamma", "label": "works at"},
        _claim_row(old, "gamma", "works-at", "c-old-1"),
        _claim_row("delta", old, "mentors", "c-old-2", context="work"),
        {"source": new, "target": "gamma", "label": "works at"},           # the moved bare edge becomes its copy
        _claim_row(new, "gamma", "works-at", "c-new-1"),                   # a different claim: never collapsed
        {"source": old, "target": new, "label": "same as"},                # becomes a self-loop
        {"source": "epsilon", "target": "gamma", "label": "part of", "weight": 2},   # an unknown field survives
    ]


def _expected(old: str, new: str) -> list[dict]:
    out, seen = [], set()
    before = _edges(old, new)
    untouched = [e for e in before if old not in (e["source"], e["target"])]
    keys = {yaml.safe_dump(e, sort_keys=True) for e in untouched}
    for e in before:
        if old not in (e["source"], e["target"]):
            out.append(e)
            continue
        moved = {k: (new if k in ("source", "target") and v == old else v) for k, v in e.items()}
        key = yaml.safe_dump(moved, sort_keys=True)
        if moved["source"] == moved["target"] or key in keys or key in seen:
            continue
        seen.add(key)
        out.append(moved)
    return out


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True, text=True).stdout


def _page(memory: Path, eid: str, fm: dict, prose: str = "## Summary\nA person.", claims=None) -> None:
    body = write_claims(prose, claims) if claims else prose
    markdown_parser.write(memory / "entities" / f"{eid}.md",
                          {"type": "person", "status": "active", "confidence": 0.8, **fm}, body)


def _bank(tmp_path: Path, old: str, new: str, *, old_fm: dict, new_fm: dict | None) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _page(memory, OWNER, {"name": "Alpha Owner", "owner": True})
    for eid, name, kind in (("gamma", "Gamma Studio", "company"), ("delta", "Delta Example", "person"),
                            ("epsilon", "Epsilon Lab", "company")):
        _page(memory, eid, {"name": name, "type": kind})
    _page(memory, old, old_fm, claims=[Claim(id="c-old-1", text="works at", subject=old, predicate="works-at",
                                             object="gamma", valid_from="2026-01-02")])
    if new_fm is not None:
        _page(memory, new, new_fm, claims=[Claim(id="c-new-1", text="works at", subject=new, predicate="works-at",
                                                 object="gamma", valid_from="2026-01-02")])
    (memory / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": _edges(old, new)}, sort_keys=False))
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


def _after(memory: Path) -> list[dict]:
    return yaml.safe_load((memory / "graph_edges.yaml").read_text())["edges"]


def _resolve(memory: Path, item: str, **request) -> None:
    asyncio.run(inbox_service.resolve(item, InboxResolveRequest(**request), SimpleNamespace(memory_path=memory)))


def _merge_item(memory: Path, mention: str, entity_id: str, hint: str, **extra) -> str:
    fm = {"kind": "merge_suggestion", "required_input": "merge", "status": "pending", "entity_name": mention,
          "entity_id": entity_id, "merge_target_hint": hint, "created_date": "2026-10-01", **extra}
    markdown_parser.write(memory / "inbox" / "inbox-001.md", fm, "Possible duplicate.")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "item")
    return "inbox-001"


# --- the primitive ------------------------------------------------------------------------------------------------


def test_the_primitive_keeps_every_field_of_every_edge(tmp_path):
    memory = _bank(tmp_path, "bob-ex", "bob-example", old_fm={"name": "Bob Ex"}, new_fm={"name": "Bob Example"})
    assert entity_merge.repoint_edges(memory, "bob-ex", "bob-example") == 4   # endpoints that named bob-ex
    assert _after(memory) == _expected("bob-ex", "bob-example")
    claim_rows = [e for e in _after(memory) if "claim_id" in e]
    assert {e["claim_id"] for e in claim_rows} == {"c-gd", "c-gd-2", "c-old-1", "c-old-2", "c-new-1"}


def test_an_edges_file_that_names_no_moved_page_is_never_rewritten(tmp_path):
    memory = _bank(tmp_path, "bob-ex", "bob-example", old_fm={"name": "Bob Ex"}, new_fm={"name": "Bob Example"})
    before = (memory / "graph_edges.yaml").read_bytes()
    assert entity_merge.repoint_edges(memory, "zeta", "bob-example") is None
    assert (memory / "graph_edges.yaml").read_bytes() == before


# --- every door -------------------------------------------------------------------------------------------------


def _door_merge_entities(tmp_path):
    memory = _bank(tmp_path, "bob-ex", "bob-example", old_fm={"name": "Bob Ex"}, new_fm={"name": "Bob Example"})
    entity_merge.merge_entities(memory, loser_id="bob-ex", winner_id="bob-example")
    return memory, "bob-ex", "bob-example"


def _door_rename_references(tmp_path):
    memory = _bank(tmp_path, "bob-ex", "bob-example", old_fm={"name": "Bob Ex"}, new_fm=None)
    (memory / "entities" / "bob-ex.md").replace(memory / "entities" / "bob-example.md")
    entity_merge.rename_references(memory, "bob-ex", "Bob Ex", "bob-example", "Bob Example")
    return memory, "bob-ex", "bob-example"


def _door_dedup_sweep(tmp_path):
    memory = _bank(tmp_path, "bob-ex", "bob-example", old_fm={"name": "Bob Ex"}, new_fm={"name": "Bob Example"})
    out = dedup_sweep.dedup_sweep(memory, SimpleNamespace(), seed_pairs=[("bob-ex", "bob-example")],
                                  judge_fn=lambda *_a: {"verdict": "same", "confidence": 0.99, "winner": "bob-example"})
    assert out["merged"] == [("bob-ex", "bob-example")], out
    return memory, "bob-ex", "bob-example"


def _door_inbox_merge_into_the_survivor(tmp_path):
    # "Keep the cleaner name" when that name is already a page: the target folds into it (merge_entities).
    memory = _bank(tmp_path, "bob-ex", "bob-example", old_fm={"name": "Bob Ex"}, new_fm={"name": "Bob Example"})
    item = _merge_item(memory, "Bob Example", "bob-example", "bob-ex")
    _resolve(memory, item, action="merge", merge_target="bob-ex", merge_survivor="Bob Example")
    return memory, "bob-ex", "bob-example"


def _door_inbox_merge_rename(tmp_path):
    # "Keep the cleaner name" when it is no page yet: the target moves to it (rename_references).
    memory = _bank(tmp_path, "bob-ex", "bob-example", old_fm={"name": "Bob Ex"}, new_fm=None)
    item = _merge_item(memory, "Bob Example", "bob-example", "bob-ex")
    _resolve(memory, item, action="merge", merge_target="bob-ex", merge_survivor="Bob Example")
    return memory, "bob-ex", "bob-example"


def _door_inbox_fold_page(tmp_path):
    # A possible-duplicate question about a page (`fold_page`): that page folds into the target.
    memory = _bank(tmp_path, "bob-ex", "bob-example", old_fm={"name": "Bob Ex"}, new_fm={"name": "Bob Example"})
    item = _merge_item(memory, "Bob Ex", "bob-ex", "bob-example", fold_page=True)
    _resolve(memory, item, action="merge", merge_target="bob-example")
    return memory, "bob-ex", "bob-example"


def _door_name_answer_merge(tmp_path):
    memory = _bank(tmp_path, "partner", "bob-example",
                   old_fm={"name": "Partner", "unnamed": True, "owner_roles": ["partner"]},
                   new_fm={"name": "Bob Example"})
    path = role_people.ensure_question(memory, "partner", owner_fm={"name": "Alpha Owner"})
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "q")
    _resolve(memory, path.stem, action="resolve", answer="Bob Example")
    return memory, "partner", "bob-example"


def _door_name_answer_rename(tmp_path):
    memory = _bank(tmp_path, "partner", "bob-example",
                   old_fm={"name": "Partner", "unnamed": True, "owner_roles": ["partner"]}, new_fm=None)
    path = role_people.ensure_question(memory, "partner", owner_fm={"name": "Alpha Owner"})
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "q")
    _resolve(memory, path.stem, action="resolve", answer="Bob Example")
    return memory, "partner", "bob-example"


def _door_repair_merge(tmp_path):
    memory = _bank(tmp_path, "alpha-owner's-father", "bob-example", old_fm={"name": "Alpha Owner's father"},
                   new_fm={"name": "Bob Example"})
    _page(memory, "bob-example", {"name": "Bob Example"}, claims=[
        Claim(id="c-new-1", text="works at", subject="bob-example", predicate="works-at", object="gamma",
              valid_from="2026-01-02"),
        Claim(id="c-father", text="father of", subject="bob-example", predicate="father-of", object=OWNER,
              valid_from="2026-01-02")])
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "evidence")
    plan = role_people.apply(memory, sleep_running=lambda: False)
    assert len(plan.merges) == 1, plan.counts()
    return memory, "alpha-owner's-father", "bob-example"


def _door_repair_retitle(tmp_path):
    memory = _bank(tmp_path, "alpha-owner's-friend", "friend", old_fm={"name": "Alpha Owner's friend"}, new_fm=None)
    plan = role_people.apply(memory, sleep_running=lambda: False)
    assert len(plan.retitles) == 1 and plan.dirty == 0, plan.counts()
    return memory, "alpha-owner's-friend", "friend"


DOORS = [_door_merge_entities, _door_rename_references, _door_dedup_sweep, _door_inbox_merge_into_the_survivor,
         _door_inbox_merge_rename, _door_inbox_fold_page, _door_name_answer_merge, _door_name_answer_rename,
         _door_repair_merge, _door_repair_retitle]


@pytest.mark.parametrize("door", DOORS, ids=[d.__name__[6:] for d in DOORS])
def test_every_merge_door_keeps_every_field_of_every_edge(tmp_path, door):
    memory, old, new = door(tmp_path)
    assert not (memory / "entities" / f"{old}.md").exists()
    assert _after(memory) == _expected(old, new)
    if door not in (_door_merge_entities, _door_rename_references):   # the primitives leave committing to the caller
        assert _git(memory, "status", "--porcelain", "--", "graph_edges.yaml") == ""


# --- the repair's dirty check ------------------------------------------------------------------------------------


def test_the_repairs_own_writes_never_make_a_later_page_dirty(tmp_path):
    """On the real bank: 1 merge, then `skipped_dirty: 5` on a clean tree. The merge rewrote `graph_edges.yaml`
    (and pages it repointed), and every later retitle whose footprint held one of them asked git and saw the
    run's own uncommitted write. What another writer left dirty is read once, before anything is written."""
    memory = _bank(tmp_path, "alpha-owner's-father", "bob-example", old_fm={"name": "Alpha Owner's father"},
                   new_fm={"name": "Bob Example"})
    _page(memory, "bob-example", {"name": "Bob Example"}, claims=[
        Claim(id="c-father", text="father of", subject="bob-example", predicate="father-of", object=OWNER,
              valid_from="2026-01-02")])
    for i, role in enumerate(("friend", "teacher", "mentor", "neighbor", "cousin")):
        eid = f"alpha-owner's-{role}"
        _page(memory, eid, {"name": f"Alpha Owner's {role}"}, f"## Summary\nKnows [[Alpha Owner's father]] ({i}).")
    edges = _edges("alpha-owner's-father", "bob-example") + [
        {"source": f"alpha-owner's-{r}", "target": "gamma", "label": "visits"}
        for r in ("friend", "teacher", "mentor", "neighbor", "cousin")]
    (memory / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": edges}, sort_keys=False))
    (memory / "episodes" / "ep_2026-10-01_001.md").write_text("an unrelated episode someone is writing\n")
    _git(memory, "add", "-A", "--", "entities", "graph_edges.yaml")
    _git(memory, "commit", "-q", "-m", "seed")

    plan = role_people.apply(memory, sleep_running=lambda: False)
    assert (len(plan.merges), len(plan.retitles), plan.dirty) == (1, 5, 0), plan.counts()
    assert _git(memory, "status", "--porcelain", "--untracked-files=all") == "?? episodes/ep_2026-10-01_001.md\n"
    after = _after(memory)
    assert len([e for e in after if "claim_id" in e]) == len([e for e in edges if "claim_id" in e])
    assert {e["source"] for e in after if e["label"] == "visits"} == {
        "friend", "teacher", "mentor", "neighbor", "cousin"}


def test_a_page_another_writer_left_dirty_is_still_skipped(tmp_path):
    memory = _bank(tmp_path, "alpha-owner's-friend", "friend", old_fm={"name": "Alpha Owner's friend"}, new_fm=None)
    _page(memory, "delta", {"name": "Delta Example"}, "## Summary\nClimbs with [[Alpha Owner's friend]].")
    _git(memory, "commit", "-q", "-am", "a link to the placeholder")
    page = memory / "entities" / "delta.md"
    page.write_text(page.read_text() + "\nA hand edit.\n")   # someone else's, uncommitted, on a page the retitle touches
    plan = role_people.apply(memory, sleep_running=lambda: False)
    assert plan.dirty == 1 and plan.retitles == []
    assert (memory / "entities" / "alpha-owner's-friend.md").exists()
    assert copy.deepcopy(_after(memory)) == _edges("alpha-owner's-friend", "friend")


# --- Sleep's own edge writer (Stage 5, 5.5 wikilinks, 5.55 media) -------------------------------------------------


def test_sleeps_edge_writer_keeps_every_existing_edge_and_adds_only_new_bare_ones(tmp_path):
    from api.services import inbox_generator

    memory = tmp_path / "memory"
    memory.mkdir()
    before = _edges("bob-ex", "bob-example")
    (memory / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": before}, sort_keys=False))
    inbox_generator._write_graph_edges(memory, [
        {"source": "gamma", "target": "delta", "label": "Uses"},          # a bare one is there: not added
        {"source": "bob-example", "target": "gamma", "label": "works-at"},  # only a claim row has it: added bare
        {"source": "zeta", "target": "gamma", "label": "visits"},
        {"source": "zeta", "target": "gamma", "label": "visits"},         # twice in one batch: once
    ])
    assert _after(memory) == before + [{"source": "bob-example", "target": "gamma", "label": "works-at"},
                                       {"source": "zeta", "target": "gamma", "label": "visits"}]


def test_an_unreadable_edges_file_is_never_replaced_by_the_new_edges_alone(tmp_path):
    from api.services import inbox_generator

    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "graph_edges.yaml").write_text("edges: [unterminated")
    inbox_generator._write_graph_edges(memory, [{"source": "a", "target": "b", "label": "c"}])
    assert (memory / "graph_edges.yaml").read_text() == "edges: [unterminated"


# --- one atomic write for graph_edges.yaml -----------------------------------------------------------------------


def _writers(memory: Path):
    """Each of the four writers, called so that it writes the file."""
    from api.services import graph_builder, inbox_generator

    return {
        "repoint_edges": lambda: entity_merge.repoint_edges(memory, "bob-ex", "bob-example"),
        "sleep_edges": lambda: inbox_generator._write_graph_edges(memory, [{"source": "z", "target": "y", "label": "x"}]),
        "regenerate": lambda: graph_builder.regenerate_edges_from_claims(memory),
        "upsert": lambda: graph_builder.upsert_claim_edges(memory, ["bob-example"]),
    }


@pytest.mark.parametrize("writer", ["repoint_edges", "sleep_edges", "regenerate", "upsert"])
def test_a_write_that_fails_part_way_leaves_the_old_edges_file_whole(tmp_path, monkeypatch, writer):
    memory = _bank(tmp_path, "bob-ex", "bob-example", old_fm={"name": "Bob Ex"}, new_fm={"name": "Bob Example"})
    if writer == "upsert":   # a claim the file does not show yet, so the projection has a row to write
        _page(memory, "bob-example", {"name": "Bob Example"}, claims=[
            Claim(id="c-new-2", text="mentors", subject="bob-example", predicate="mentors", object="delta",
                  valid_from="2026-01-03")])
    before = (memory / "graph_edges.yaml").read_bytes()
    real_fdopen = __import__("os").fdopen

    class Torn:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()
            return False

        def write(self, data):
            self.fh.write(data[: len(data) // 2])   # half the file lands, then the disk is full
            raise OSError(28, "No space left on device")

    monkeypatch.setattr("api.services.markdown_parser.os.fdopen", lambda fd, mode: Torn(real_fdopen(fd, mode)))
    with pytest.raises(OSError):
        _writers(memory)[writer]()
    assert (memory / "graph_edges.yaml").read_bytes() == before
    assert sorted(p.name for p in memory.iterdir() if p.name.startswith(".graph_edges")) == []   # no temp left


def test_every_writer_of_the_edges_file_goes_through_the_one_atomic_write():
    import ast
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in sorted((root / "services").glob("*.py")):
        text = path.read_text()
        if "graph_edges" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "write_text", "write_bytes") and "edges" in ast.unparse(node.func.value):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []
