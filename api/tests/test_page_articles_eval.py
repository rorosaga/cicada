"""The offline articles eval (G194) runs end to end on its synthetic fixture: no model, nothing lost, stubs stay stubs."""
import json

from benchmarks.system import page_articles as ev


def test_the_eval_keeps_every_record_item_and_writes_articles_only_where_the_material_is(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_LOGO_FETCH", "off")
    # The eval points CICADA_MEMORY_PATH at each scratch bank; monkeypatch puts the suite's value back after.
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(tmp_path))
    data = json.loads(ev.FIXTURE.read_text())
    today = ev.run_timeline(tmp_path, "today", data)
    articles = ev.run_timeline(tmp_path, "articles", data)
    assert ev.lossless(today["bank"], today["extracted"]) == []
    assert ev.lossless(articles["bank"], articles["extracted"]) == []
    stats = {p.stem: ev.page_stats(p) for p in (articles["bank"] / "entities").glob("*.md")}
    assert stats["alpha-project"]["conversations"] == 15 and stats["alpha-project"]["article_paragraphs"] > 3
    assert stats["bob-example"]["article_sections"] >= 1
    assert stats["gamma-tool"]["article_words"] == 0          # one conversation: a stub, no call
    calls = [c for b in articles["batches"] for c in [b["calls"]]]
    # One call per page update, as today's orientation call — plus alpha-project's create, whose first conversation
    # already gives the writer enough to connect (owner 2026-10-17: a new page is born an article); gamma-tool's does not.
    assert calls[0] == {"article": 1}
    assert sum(c.get("article", 0) for c in calls) == 1 + sum(c.get("orientation", 0) for b in today["batches"]
                                                            for c in [b["calls"]])
    data["recorded_articles_ids"] = ["alpha-project", "bob-example", "gamma-tool"]
    result = ev.rebuild(tmp_path, today["bank"], data)
    assert result["preview"]["written"] == 2 and result["preview"]["invalid"] == 0
    assert result["preview"]["paragraphs_left_out"] == {}
    after = (tmp_path / "rebuild-preview" / "alpha-project.after.md").read_text()
    assert "### How it developed" in after and "## Key Facts" in after
