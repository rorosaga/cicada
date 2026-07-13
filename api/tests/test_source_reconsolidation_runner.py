import subprocess
import types
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


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def test_run_batch_commits_per_entity_when_git_repo(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _mk(ents, "a", 5, 0.3)

    _git(["init", "-q"], cwd=tmp_path)
    _git(["config", "user.email", "bench@cicada.local"], cwd=tmp_path)
    _git(["config", "user.name", "cicada-bench"], cwd=tmp_path)
    _git(["add", "-A"], cwd=tmp_path)
    _git(["commit", "-q", "-m", "seed"], cwd=tmp_path)

    before_count = int(subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=tmp_path,
        check=True, capture_output=True, text=True,
    ).stdout.strip())

    def rewrite_fn(mp, eid, settings, **kw):
        # A real rewrite_fn edits the entity file on disk before reporting
        # changed=True; mirror that here so `git commit` has something staged.
        f = mp / "entities" / f"{eid}.md"
        f.write_text(f.read_text() + "rewritten body\n")
        return {"entity_id": eid, "changed": True, "before_words": 5, "after_words": 40}

    settings = types.SimpleNamespace(effective_consolidation_model="openrouter/z-ai/glm-5.2")
    run_batch(tmp_path, settings, rewrite_fn=rewrite_fn)

    after_count = int(subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=tmp_path,
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    assert after_count == before_count + 1

    log = subprocess.run(
        ["git", "log", "-1", "--format=%B"], cwd=tmp_path,
        check=True, capture_output=True, text=True,
    ).stdout
    assert "entities/a.md" in log
    assert "Cicada-Author: openrouter/z-ai/glm-5.2" in log
