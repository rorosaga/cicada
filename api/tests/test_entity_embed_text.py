"""What an entity page's search vector is made from, and the side-by-side recall test that decides it (2026-10-16 perf,
owner decision 4).

At owner scale the entity vectors embed 43.7M characters, 82 % of them claims fences (the owner page alone 5.0M). The
``prose`` text leaves the fence out and caps the input — shipped behind ``entity_embed_text``, defaulting to today's
``full``, until ``benchmarks.recall_ab`` shows search no worse on the person's own queries. Synthetic pages only.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from api import config
from api.services import markdown_parser, vector_index
from api.services.vector_index import ENTITY_EMBED_MAX_CHARS, SqliteVecIndexer, _entity_embed_text

FENCE = '```claims\n{"id": "clm_1", "text": "Alpha Project uses beta tool", "subject": "alpha-project"}\n```'
BODY = f"## Summary\nAlpha Project is a synthetic page about gardening.\n\n{FENCE}"


def fake_embed(texts, *, is_query=False):
    vocab = ["gardening", "beta", "tool", "alpha", "orchids", "uses"]
    rows = []
    for text in texts:
        low = text.lower()
        vec = np.array([float(low.count(w)) for w in vocab], dtype=np.float32) + 1e-3
        rows.append(vec / np.linalg.norm(vec))
    return np.vstack(rows)


def test_full_is_todays_text_byte_for_byte():
    fm = {"name": "Alpha Project", "type": "project", "aliases": ["alpha"], "tags": ["x"]}
    assert _entity_embed_text(fm, BODY, "alpha-project") == f"Alpha Project (project) aka: alpha\n{BODY}"
    assert _entity_embed_text(fm, BODY, "alpha-project", mode="full") == \
        _entity_embed_text(fm, BODY, "alpha-project")


def test_prose_leaves_the_claims_fence_out_and_keeps_a_literal_example():
    fm = {"name": "Alpha Project", "type": "project"}
    text = _entity_embed_text(fm, BODY, "alpha-project", mode="prose")
    assert text == "Alpha Project (project)\n## Summary\nAlpha Project is a synthetic page about gardening."
    example = "## How\n~~~~markdown\n```claims\n[]\n```\n~~~~"
    assert "```claims" in _entity_embed_text(fm, example, "alpha-project", mode="prose")


def test_prose_is_capped_at_the_head_of_the_page():
    fm = {"name": "Owner Example", "type": "person"}
    body = "## Summary\n" + "orchids " * 5_000 + "\n\n" + FENCE
    text = _entity_embed_text(fm, body, "owner-example", mode="prose")
    assert len(text) <= ENTITY_EMBED_MAX_CHARS
    assert text.startswith("Owner Example (person)\n## Summary\norchids")
    assert "clm_1" not in text


def test_the_setting_defaults_to_full_and_an_unknown_value_is_full(monkeypatch):
    monkeypatch.delenv("CICADA_ENTITY_EMBED_TEXT", raising=False)
    config.get_settings.cache_clear()
    try:
        assert config.Settings(_env_file=None).entity_embed_text == "full"
        assert vector_index.entity_text_mode() == "full"
        monkeypatch.setenv("CICADA_ENTITY_EMBED_TEXT", "prose")
        config.get_settings.cache_clear()
        assert vector_index.entity_text_mode() == "prose"
        monkeypatch.setenv("CICADA_ENTITY_EMBED_TEXT", "everything")
        config.get_settings.cache_clear()
        assert vector_index.entity_text_mode() == "full"
        assert vector_index.entity_text_mode("prose") == "prose"
    finally:
        config.get_settings.cache_clear()


def _bank(tmp_path):
    (tmp_path / "entities").mkdir(parents=True)
    markdown_parser.write(tmp_path / "entities" / "alpha-project.md",
                          {"name": "Alpha Project", "type": "project"},
                          "## Summary\nAlpha Project is about gardening.\n\n" + FENCE)
    markdown_parser.write(tmp_path / "entities" / "beta-tool.md", {"name": "Beta Tool", "type": "tool"},
                          "## Summary\nBeta Tool grows orchids.")
    return tmp_path


def test_the_index_follows_the_setting_and_a_change_re_embeds_every_page(tmp_path, monkeypatch):
    bank = _bank(tmp_path)
    monkeypatch.delenv("CICADA_ENTITY_EMBED_TEXT", raising=False)
    config.get_settings.cache_clear()
    try:
        idx = SqliteVecIndexer(bank, embed_fn=fake_embed, model_name="fake")
        idx.index_entities()
        assert idx.last_sync["entities"]["embedded"] == 2
        idx.index_entities()
        assert idx.last_sync["entities"]["embedded"] == 0, "nothing changed: nothing re-embedded"
        monkeypatch.setenv("CICADA_ENTITY_EMBED_TEXT", "prose")
        config.get_settings.cache_clear()
        idx = SqliteVecIndexer(bank, embed_fn=fake_embed, model_name="fake")
        idx.index_entities()
        # Only the page whose text changed (the one with a fence) is embedded again.
        assert idx.last_sync["entities"]["embedded"] == 1
        texts = [h["text"] for h in idx.search_entities("gardening", top_k=2)]
        assert all("clm_1" not in t for t in texts)
    finally:
        config.get_settings.cache_clear()


# --- the side-by-side recall test ------------------------------------------------------------------------------------


def test_queries_load_from_the_benchmark_yaml_and_from_json_lines(tmp_path):
    from benchmarks import recall_ab

    y = tmp_path / "q.yaml"
    y.write_text("questions:\n  - id: 1\n    question: Who grows orchids?\n    expected_entities: [beta-tool]\n"
                 "  - id: 2\n    question: no answer key\n")
    j = tmp_path / "q.jsonl"
    j.write_text('# a comment\n{"query": "gardening", "relevant": ["Alpha Project"]}\n')
    assert recall_ab.load_queries(y) == [{"query": "Who grows orchids?", "relevant": ["beta-tool"]},
                                         {"query": "no answer key", "relevant": []}]
    assert recall_ab.load_queries(j) == [{"query": "gardening", "relevant": ["Alpha Project"]}]


def test_the_ab_harness_reports_both_ways_and_never_writes_into_the_bank(tmp_path, monkeypatch):
    from benchmarks import recall_ab

    bank = _bank(tmp_path / "bank")
    before = sorted(p.relative_to(bank) for p in bank.rglob("*"))
    queries = tmp_path / "q.jsonl"
    queries.write_text("".join(json.dumps(r) + "\n" for r in [
        {"query": "Alpha Project gardening", "relevant": ["alpha-project"]},
        {"query": "Alpha Project uses beta tool", "relevant": ["Alpha Project"]},
        {"query": "orchids", "relevant": []},
    ]))
    out = tmp_path / "result.json"
    code = recall_ab.main(["--bank", str(bank), "--queries", str(queries), "--embedder", "hash",
                           "--work", str(tmp_path / "work"), "--out", str(out)])
    assert code in (0, 1)
    assert sorted(p.relative_to(bank) for p in bank.rglob("*")) == before
    result = json.loads(out.read_text())
    s = result["summary"]
    assert s["queries"] == 3 and s["labeled"] == 2
    assert s["full"]["embedded_chars"] > s["prose"]["embedded_chars"]
    for surface in ("hybrid", "vector"):
        assert set(s[surface]["delta"]) == {"mrr", "recall@1", "recall@3", "recall@5", "recall@10"}
        assert s[surface]["wins"] + s[surface]["losses"] + s[surface]["ties"] == 2
        assert s[surface]["unlabeled_overlap@5"] is not None
    assert all("query" not in r for r in result["per_query"]), "query text only with --show-queries"
    assert code == (0 if recall_ab.no_worse(result, 0.0) else 1)
    from api.services import search_index

    assert search_index.db_path(bank) == bank / search_index.DB_FILE, "the throwaway words index is forgotten"


def test_the_ab_harness_refuses_a_work_folder_inside_the_bank_and_a_metered_model(tmp_path, monkeypatch):
    from benchmarks import recall_ab

    bank = _bank(tmp_path / "bank")
    queries = tmp_path / "q.jsonl"
    queries.write_text('{"query": "x", "relevant": ["beta-tool"]}\n')
    assert recall_ab.main(["--bank", str(bank), "--queries", str(queries), "--embedder", "hash",
                           "--work", str(bank / "tmp")]) == 2
    assert not (bank / "tmp").exists()
    from api.services import embedding_models

    monkeypatch.setattr(embedding_models, "build_model", lambda *a, **k: "text-embedding-3-small")
    with pytest.raises(SystemExit, match="metered"):
        recall_ab.main(["--bank", str(bank), "--queries", str(queries), "--work", str(tmp_path / "w")])
