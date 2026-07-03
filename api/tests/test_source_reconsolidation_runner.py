from pathlib import Path
from benchmarks.run_source_reconsolidation import ordered_entities, run_batch


def _mk(ents, eid, words, conf):
    body = "## Summary\n" + ("w " * words) + "\n"
    (ents / f"{eid}.md").write_text(
        f"---\nname: {eid}\ntype: project\nstatus: active\nconfidence: {conf}\n---\n\n{body}")


def test_ordered_entities_thin_and_lowconf_first(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _mk(ents, "rich", 200, 0.9)
    _mk(ents, "thin", 5, 0.2)
    order = ordered_entities(tmp_path)
    assert order.index("thin") < order.index("rich")


def test_run_batch_is_resumable(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _mk(ents, "a", 5, 0.3); _mk(ents, "b", 5, 0.3)
    calls = []
    def rewrite_fn(mp, eid, settings, **kw):
        calls.append(eid)
        return {"entity_id": eid, "changed": True, "before_words": 5, "after_words": 40}
    marker = tmp_path / "done.txt"
    run_batch(tmp_path, None, limit=1, rewrite_fn=rewrite_fn, marker_path=marker)
    run_batch(tmp_path, None, limit=1, rewrite_fn=rewrite_fn, marker_path=marker)
    assert sorted(calls) == ["a", "b"]     # second run skipped the first, did the other
    assert len(set(calls)) == 2
