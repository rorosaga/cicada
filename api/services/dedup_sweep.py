"""Full-graph dedup sweep (G21): embedding-gate same-type pairs, LLM same/
different/unsure judge with both pages, auto-merge high-confidence, nudge the
uncertain. Runs on a duplicate bank; never on the live bank in tests."""
from __future__ import annotations
import logging
from pathlib import Path
from api.services import markdown_parser
from api.services.entity_merge import merge_entities

logger = logging.getLogger(__name__)


def find_candidate_pairs(memory_path: Path, *, embed_fn=None, min_cosine=0.85):
    """Embedding-gate: same-type entity pairs with high cosine. Best-effort;
    returns [] if the index isn't built. (Seeded runs can skip this.)

    Score direction: ``search_entities`` -> ``SqliteVecIndexer._knn`` computes
    ``score = 1.0 - cosine_distance`` (see api/services/vector_index.py), so
    ``hit["score"]`` is a SIMILARITY where HIGHER means closer. The floor
    below is therefore ``score >= min_cosine``.
    """
    from api.services.vector_index import SqliteVecIndexer
    idx = SqliteVecIndexer(memory_path, embed_fn=embed_fn)
    ents = memory_path / "entities"
    pairs, seen = [], set()
    for f in sorted(ents.glob("*.md")):
        par = markdown_parser.parse(f)
        name = str(par.frontmatter.get("name", f.stem))
        own_type = par.frontmatter.get("type")
        for hit in idx.search_entities(name, top_k=4):
            meta = hit.get("metadata", {})
            other = meta.get("entity_id")
            if not other or other == f.stem:
                continue
            score = float(hit.get("score", 0) or 0)
            if score < min_cosine:
                continue  # below the similarity floor
            other_type = meta.get("type")
            if own_type and other_type and own_type != other_type:
                continue  # same-type gate: skip known-differing types
            key = tuple(sorted((f.stem, other)))
            if key in seen:
                continue
            seen.add(key)
            pairs.append((key[0], key[1], score))
    return pairs


def dedup_sweep(memory_path: Path, settings, *, judge_fn=None, embed_fn=None,
                seed_pairs=None, auto_merge_threshold=0.9, dry_run=False,
                limit=None) -> dict:
    """Run the full-graph dedup sweep.

    ``dry_run`` (G21 maintenance endpoint): when True, a pair the judge calls
    "same" with high enough confidence is reported under ``proposed`` instead
    of actually calling ``merge_entities`` — nothing is written to disk.
    ``limit`` caps how many candidate pairs are considered, bounding judge
    (LLM) calls on a large graph.
    """
    if judge_fn is None:  # pragma: no cover - resolved at runtime
        judge_fn = _default_judge_fn(settings)
    pairs = list(seed_pairs or [])
    if not pairs:
        pairs = [(a, b) for (a, b, _score) in find_candidate_pairs(memory_path, embed_fn=embed_fn)]
    if limit is not None:
        pairs = pairs[:limit]

    ents = memory_path / "entities"
    merged, proposed, nudged = [], [], []
    gone: set[str] = set()
    for a, b in pairs:
        if a in gone or b in gone:
            continue
        ap, bp = ents / f"{a}.md", ents / f"{b}.md"
        if not ap.exists() or not bp.exists():
            continue
        try:
            v = judge_fn(ap.read_text(), bp.read_text(), a, b)
            verdict = v.get("verdict")
            confidence = float(v.get("confidence", 0) or 0)
            winner = v.get("winner")
            if (
                verdict == "same"
                and confidence >= auto_merge_threshold
                and winner in (a, b)
            ):
                loser = b if winner == a else a
                if dry_run:
                    proposed.append((loser, winner))
                else:
                    merge_entities(memory_path, loser_id=loser, winner_id=winner)
                    merged.append((loser, winner))
                gone.add(loser)
            elif verdict in ("same", "unsure"):
                # Either genuinely uncertain, or "same" with a high enough
                # confidence but a winner that isn't one of the two
                # candidates (hallucinated/mis-cased id) — treat as uncertain
                # rather than guessing which side to keep.
                nudged.append((a, b))
        except Exception as exc:  # noqa: BLE001 - one bad pair must not abort the sweep
            logger.warning("dedup_sweep: skipping pair (%s, %s) after error: %s", a, b, exc)
            continue
    return {"merged": merged, "proposed": proposed, "nudged": nudged, "candidate_pairs": len(pairs)}


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
