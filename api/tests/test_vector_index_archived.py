from api.services.vector_index import SqliteVecIndexer


def _fake_embed(texts, *, is_query: bool = False):
    # bag-of-words deterministic embedder. MUST match the indexer's contract:
    # accepts `*, is_query` and returns a float32 numpy array (see existing
    # api/tests fake_embed). A plain list breaks the indexer's np.vstack path.
    import re
    import numpy as np
    vocab = ["esa", "rejected", "chile", "space", "active", "thing", "mongodb", "misc"]
    rows = []
    for t in texts:
        toks = set(re.findall(r"[a-z]+", t.lower()))
        v = np.array([1.0 if w in toks else 0.0 for w in vocab], dtype=np.float32)
        n = float(np.linalg.norm(v))
        v = v / n if n > 0 else np.ones(len(vocab), dtype=np.float32) / np.sqrt(len(vocab))
        rows.append(v)
    return np.vstack(rows).astype(np.float32)


def _mk(dir_, eid, status, body):
    (dir_ / f"{eid}.md").write_text(
        f"---\nname: {eid}\ntype: project\nstatus: {status}\nconfidence: 0.5\n---\n\n{body}\n")


def test_archived_entity_surfaces_when_active_set_thin(tmp_path):
    ents = tmp_path / "entities"; ents.mkdir()
    _mk(ents, "esa-rejected", "archived", "ESA rejected Chile space application")
    idx = SqliteVecIndexer(tmp_path, embed_fn=_fake_embed)
    idx.index_entities()
    # query overlaps only the archived entity; default (archived-excluded) would return []
    hits = idx.search_entities("esa rejected chile", top_k=5)
    ids = [h["metadata"]["entity_id"] for h in hits]
    assert "esa-rejected" in ids
    assert any(h["metadata"]["status"] == "archived" for h in hits)
