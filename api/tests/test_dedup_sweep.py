from pathlib import Path
import yaml
from api.services.dedup_sweep import dedup_sweep, find_candidate_pairs


def _w(ents, eid, name, body="## Summary\nx\n"):
    (ents / f"{eid}.md").write_text(
        f"---\nname: {name}\ntype: person\nstatus: active\nconfidence: 0.6\n"
        f"source_episodes: [ep_1]\n---\n\n{body}")


def test_seed_pair_auto_merges_on_high_confidence_judge(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _w(ents, "esa", "ESA")
    _w(ents, "esta", "ESTA")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": []}))

    def judge_fn(a_body, b_body, a_id, b_id):   # deterministic "same" verdict
        return {"verdict": "same", "confidence": 0.95, "winner": "esa"}

    out = dedup_sweep(tmp_path, settings=None, judge_fn=judge_fn,
                      seed_pairs=[("esa", "esta")], auto_merge_threshold=0.9)
    assert ("esta", "esa") in [(l, w) for (l, w) in out["merged"]]
    assert not (ents / "esta.md").exists()


def test_uncertain_judge_nudges_not_merges(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _w(ents, "a", "A"); _w(ents, "b", "B")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": []}))
    def judge_fn(*a, **k):
        return {"verdict": "unsure", "confidence": 0.5, "winner": "a"}
    out = dedup_sweep(tmp_path, settings=None, judge_fn=judge_fn, seed_pairs=[("a", "b")])
    assert out["merged"] == [] and ("a", "b") in out["nudged"]
    assert (ents / "b.md").exists()


def test_malformed_winner_is_nudged_not_merged(tmp_path):
    """A judge that returns 'same' + high confidence but a winner id that
    isn't one of the two candidates (hallucinated/mis-cased) must NOT merge —
    the pair should be treated as uncertain and routed to nudged instead."""
    ents = tmp_path / "entities"; ents.mkdir()
    _w(ents, "a", "A"); _w(ents, "b", "B")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": []}))

    def judge_fn(*a, **k):
        return {"verdict": "same", "confidence": 0.95, "winner": "does-not-exist"}

    out = dedup_sweep(tmp_path, settings=None, judge_fn=judge_fn, seed_pairs=[("a", "b")])
    assert out["merged"] == []
    assert ("a", "b") in out["nudged"]
    assert (ents / "a.md").exists() and (ents / "b.md").exists()


def test_judge_exception_does_not_abort_sweep(tmp_path):
    """A judge that raises on one pair must not prevent a later, valid pair
    in the same sweep from being processed and merged."""
    ents = tmp_path / "entities"; ents.mkdir()
    _w(ents, "a", "A"); _w(ents, "b", "B")
    _w(ents, "c", "C"); _w(ents, "d", "D")
    (tmp_path / "graph_edges.yaml").write_text(yaml.safe_dump({"edges": []}))

    def judge_fn(a_body, b_body, a_id, b_id):
        if a_id == "a":
            raise RuntimeError("judge boom")
        return {"verdict": "same", "confidence": 0.95, "winner": "c"}

    out = dedup_sweep(tmp_path, settings=None, judge_fn=judge_fn,
                      seed_pairs=[("a", "b"), ("c", "d")])
    assert ("d", "c") in out["merged"]
    assert not (ents / "d.md").exists()
    # The pair that raised is neither merged nor nudged — it's simply skipped.
    assert ("a", "b") not in out["nudged"]
    assert (ents / "a.md").exists() and (ents / "b.md").exists()


def test_find_candidate_pairs_applies_type_gate_and_cosine_floor(tmp_path, monkeypatch):
    """Hermetic test of the embedding gate: monkeypatch
    SqliteVecIndexer.search_entities to return mixed-type + varied-score hits
    and assert only the same-type, above-floor hit survives."""
    ents = tmp_path / "entities"; ents.mkdir()
    _w(ents, "a", "A")  # type: person, from the _w() helper

    from api.services import vector_index as vi

    def fake_search_entities(self, query, top_k=5, include_archived=False):
        return [
            # same type, above floor -> should survive
            {"metadata": {"entity_id": "same-high", "type": "person"}, "score": 0.9},
            # same type, below floor -> should be dropped
            {"metadata": {"entity_id": "same-low", "type": "person"}, "score": 0.5},
            # different type, above floor -> should be dropped by the type gate
            {"metadata": {"entity_id": "diff-high", "type": "project"}, "score": 0.95},
        ]

    monkeypatch.setattr(vi.SqliteVecIndexer, "search_entities", fake_search_entities)

    pairs = find_candidate_pairs(tmp_path, min_cosine=0.85)
    ids = sorted((p[0], p[1]) for p in pairs)
    assert ids == [tuple(sorted(("a", "same-high")))]
