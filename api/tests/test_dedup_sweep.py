from pathlib import Path
import yaml
from api.services.dedup_sweep import dedup_sweep


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
