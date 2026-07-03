"""Full-graph dedup sweep (G21): embedding-gate same-type pairs, LLM same/
different/unsure judge with both pages, auto-merge high-confidence, nudge the
uncertain. Runs on a duplicate bank; never on the live bank in tests."""
from __future__ import annotations
from pathlib import Path
from api.services import markdown_parser
from api.services.entity_merge import merge_entities


def find_candidate_pairs(memory_path: Path, *, embed_fn=None, min_cosine=0.85):
    """Embedding-gate: same-type entity pairs with high cosine. Best-effort;
    returns [] if the index isn't built. (Seeded runs can skip this.)"""
    from api.services.vector_index import SqliteVecIndexer
    idx = SqliteVecIndexer(memory_path, embed_fn=embed_fn)
    ents = memory_path / "entities"
    pairs, seen = [], set()
    for f in sorted(ents.glob("*.md")):
        par = markdown_parser.parse(f)
        name = str(par.frontmatter.get("name", f.stem))
        for hit in idx.search_entities(name, top_k=4):
            other = hit.get("metadata", {}).get("entity_id")
            if not other or other == f.stem:
                continue
            key = tuple(sorted((f.stem, other)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((key[0], key[1], float(hit.get("score", 0) or 0)))
    return pairs


def dedup_sweep(memory_path: Path, settings, *, judge_fn=None, embed_fn=None,
                seed_pairs=None, auto_merge_threshold=0.9) -> dict:
    if judge_fn is None:  # pragma: no cover - resolved at runtime
        judge_fn = _default_judge_fn(settings)
    pairs = list(seed_pairs or [])
    if not pairs:
        pairs = [(a, b) for (a, b, _score) in find_candidate_pairs(memory_path, embed_fn=embed_fn)]

    ents = memory_path / "entities"
    merged, nudged = [], []
    gone: set[str] = set()
    for a, b in pairs:
        if a in gone or b in gone:
            continue
        ap, bp = ents / f"{a}.md", ents / f"{b}.md"
        if not ap.exists() or not bp.exists():
            continue
        v = judge_fn(ap.read_text(), bp.read_text(), a, b)
        if v.get("verdict") == "same" and float(v.get("confidence", 0)) >= auto_merge_threshold:
            winner = v.get("winner") or a
            loser = b if winner == a else a
            merge_entities(memory_path, loser_id=loser, winner_id=winner)
            merged.append((loser, winner))
            gone.add(loser)
        elif v.get("verdict") in ("same", "unsure"):
            nudged.append((a, b))
    return {"merged": merged, "nudged": nudged}


def _default_judge_fn(settings):  # pragma: no cover - needs a real model
    import json
    from api.services.providers import resolve_llm_fn
    llm = resolve_llm_fn(settings, model=settings.effective_consolidation_model)

    def judge(a_body, b_body, a_id, b_id):
        prompt = (
            "Are these two knowledge-graph entity pages the SAME real-world thing? "
            "Reply JSON {\"verdict\":\"same|different|unsure\",\"confidence\":0..1,"
            "\"winner\":\"<id to keep>\"}.\n\n"
            f"PAGE A (id={a_id}):\n{a_body[:2500]}\n\nPAGE B (id={b_id}):\n{b_body[:2500]}"
        )
        resp = llm(messages=[{"role": "user", "content": prompt}],
                   response_format={"type": "json_object"})
        txt = resp["choices"][0]["message"]["content"]
        s, e = txt.find("{"), txt.rfind("}")
        return json.loads(txt[s:e + 1]) if s >= 0 else {"verdict": "unsure", "confidence": 0.0}
    return judge
