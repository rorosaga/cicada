"""ask_memory — auditable natural-language synthesis over the knowledge graph.

The flagship, thesis-novel retrieval surface (decision D3 = BOTH in
``docs/goals/memory-evolution.md``): an answer that **cites its sources** and
**admits what it does not know**. Unlike an opaque RAG substrate, every claim is
traceable back to the markdown entity that grounded it (entity-level citations
now; line-level git-blame citations are a documented follow-up), and thin
evidence produces an explicit *gap* ("I don't have information about X") rather
than a confident hallucination.

The service is dependency-injected for hermetic testing:

- ``retrieve_fn(query, top_k) -> list[hit]`` — defaults to
  :meth:`SqliteVecIndexer.search_entities`. Each hit follows the indexer's
  contract: ``{"score", "text", "metadata": {entity_id, entity_name, type,
  status, confidence, file_path}}``.
- ``llm_fn(prompt) -> str`` — defaults to a litellm JSON-mode call per
  :class:`api.config.Settings`. Returns the model's raw string, which the
  service parses as JSON.

No real embedding/LLM/network calls happen unless the defaults are used, so unit
tests inject both.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from loguru import logger

from api.services import markdown_parser

RetrieveFn = Callable[[str, int], list[dict]]
LlmFn = Callable[[str], str]

# Body excerpt length carried into each citation (enough to audit the claim,
# short enough not to dump the whole page into the response).
_SNIPPET_CHARS = 280

ASK_SYSTEM_PROMPT = """You answer questions using ONLY the retrieved memory context below. \
This is a personal knowledge graph; the context is the ONLY source of truth you may use. \
Do NOT use outside knowledge and do NOT invent facts.

You are given a list of ENTITIES, each with an id, name, type, and body text.

Rules:
1. Ground every claim in the provided entities. If the context does not contain \
the answer, say so plainly — never guess.
2. List the entity ids you actually used in ``used_entities`` (only ids that appear \
in the context).
3. Populate ``gaps`` with explicit, honest statements of what you could NOT answer \
or what is missing from memory (e.g. "No information about the database choice"). \
If you are confident and the context fully answers the question, ``gaps`` may be empty.
4. ``confidence`` is 0.0–1.0 reflecting how well the retrieved context supports your \
answer. Thin or tangential evidence => low confidence and a populated ``gaps`` list.
5. If the context is irrelevant to the question, set a low confidence, give an \
answer that admits you don't know, and explain the gap.

Return ONLY a JSON object with exactly these keys:
{
  "answer": "natural-language answer grounded in the context",
  "confidence": 0.0,
  "used_entities": ["entity-id", "..."],
  "gaps": ["explicit gap statement", "..."]
}"""


def _snippet(body: str, limit: int = _SNIPPET_CHARS) -> str:
    text = " ".join((body or "").split())
    return (text[:limit] + "…") if len(text) > limit else text


def _load_entity(memory_path: Path, entity_id: str) -> dict | None:
    """Read an entity's markdown to back a citation. Returns None if missing."""
    filepath = memory_path / "entities" / f"{entity_id}.md"
    if not filepath.exists():
        return None
    try:
        parsed = markdown_parser.parse(filepath)
    except Exception:
        return None
    fm = parsed.frontmatter or {}
    return {
        "entity_id": entity_id,
        "entity_name": str(fm.get("name", entity_id.replace("-", " ").title())),
        "file_path": str(filepath),
        "snippet": _snippet(parsed.body),
        "source_episodes": list(fm.get("source_episodes", []) or []),
        "type": str(fm.get("type", "concept") or "concept"),
        "body": parsed.body or "",
    }


def _coerce_str_list(value) -> list[str]:
    """Normalize an LLM field that should be a list of strings.

    Guards against the common JSON-mode slip where the model returns a bare
    string (``"gaps": "no info"``) instead of a list — iterating that directly
    would shred it into one entry per character. A bare string becomes a
    one-element list; non-string scalars are coerced; non-iterables are dropped.
    """
    if value is None:
        return []
    if isinstance(value, str):
        v = value.strip()
        return [v] if v else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    # Some other scalar (number/bool) — treat as a single value.
    s = str(value).strip()
    return [s] if s else []


def _substring_match(memory_path: Path, query: str, top_k: int) -> list[dict]:
    """Disk-backed substring fallback for a cold/empty vector index.

    Mirrors the graceful-degrade pattern in ``routers/search.py``: when the
    vector index returns nothing on a populated graph (fresh install before the
    index is built), fall back to a name/tag/body substring scan so ``ask`` can
    still ground an answer instead of falsely claiming ignorance. Returns hits in
    the ``search_entities`` shape so the rest of the pipeline is unchanged.
    """
    q = (query or "").lower().strip()
    entities_dir = memory_path / "entities"
    if not q or not entities_dir.exists():
        return []
    scored: list[tuple[int, dict]] = []
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        name = str(fm.get("name", filepath.stem.replace("-", " "))).lower()
        tags = [str(t).lower() for t in (fm.get("tags", []) or [])]
        relevance = 0
        if q in name:
            relevance += 10
        if any(q in t for t in tags):
            relevance += 5
        if q in (parsed.body or "").lower():
            relevance += 2
        if relevance <= 0:
            continue
        scored.append(
            (
                relevance,
                {
                    "score": float(relevance),
                    "text": parsed.body or "",
                    "metadata": {
                        "entity_id": filepath.stem,
                        "entity_name": str(fm.get("name", filepath.stem)),
                        "type": str(fm.get("type", "concept") or "concept"),
                        "status": str(fm.get("status", "active") or "active"),
                        "confidence": float(fm.get("confidence", 0.5) or 0.0),
                        "file_path": str(filepath),
                    },
                },
            )
        )
    scored.sort(key=lambda x: -x[0])
    return [hit for _, hit in scored[:top_k]]


def _retrieved_entities(memory_path: Path, hits: list[dict]) -> list[dict]:
    """Map retrieval hits to loaded entity records, de-duped, order preserved."""
    out: list[dict] = []
    seen: set[str] = set()
    for hit in hits:
        meta = hit.get("metadata", {}) or {}
        eid = meta.get("entity_id")
        if not eid or eid in seen:
            continue
        seen.add(eid)
        loaded = _load_entity(memory_path, eid)
        if loaded is None:
            # Index points at an entity whose file is gone — fall back to the
            # indexed text so the entity can still be cited/grounded.
            loaded = {
                "entity_id": eid,
                "entity_name": str(meta.get("entity_name", eid)),
                "file_path": str(meta.get("file_path", "")),
                "snippet": _snippet(hit.get("text", "")),
                "source_episodes": [],
                "type": str(meta.get("type", "concept")),
                "body": str(hit.get("text", "")),
            }
        loaded["score"] = float(hit.get("score", 0.0) or 0.0)
        # Carry claim provenance from a claim-first hit so the citation can point
        # at claim_id + valid-window + observer (M5e). Absent for entity-only hits.
        claim_prov = {
            k: meta.get(k)
            for k in ("claim_id", "observer", "context", "valid_from", "source_trust")
            if meta.get(k) is not None
        }
        if claim_prov:
            loaded["claim_provenance"] = claim_prov
        out.append(loaded)
    return out


def _build_prompt(query: str, entities: list[dict]) -> str:
    blocks: list[str] = []
    for ent in entities:
        body = ent.get("body", "") or ent.get("snippet", "")
        blocks.append(
            f"### entity_id: {ent['entity_id']}\n"
            f"name: {ent['entity_name']}\n"
            f"type: {ent.get('type', 'concept')}\n"
            f"body:\n{body[:3000]}"
        )
    context = "\n\n".join(blocks)
    return (
        f"QUESTION:\n{query}\n\n"
        f"RETRIEVED MEMORY CONTEXT ({len(entities)} entities):\n\n{context}"
    )


def _clamp_confidence(value, default: float) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, conf))


def _gap_response(query: str) -> dict:
    """The honest-ignorance answer when nothing relevant was retrieved."""
    return {
        "answer": (
            f"I don't have information in memory to answer that. Nothing in the "
            f"knowledge graph matches \"{query}\"."
        ),
        "confidence": 0.05,
        "citations": [],
        "gaps": [
            f"No entities in memory relate to: {query}",
        ],
        "used_entities": [],
    }


def _default_llm_fn() -> LlmFn:
    """Production LLM call: litellm JSON-mode per Settings (mirrors extractor)."""
    import litellm

    from api.config import get_settings

    settings = get_settings()

    def _call(prompt: str) -> str:
        response = litellm.completion(
            model=settings.litellm_model,
            messages=[
                {"role": "system", "content": ASK_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    return _call


def _default_retrieve_fn(memory_path: Path) -> RetrieveFn:
    """The default retrieve seam — **claim-first** with an entity fallback (M5e)."""
    return build_claim_first_retrieve_fn(memory_path)


def build_claim_first_retrieve_fn(memory_path, *, embed_fn=None) -> RetrieveFn:
    """Claim-first retrieval that degrades to entity search on un-consolidated banks.

    Strategy (D2 "Retrieval / /ask", reduced to what the ask pipeline consumes):

    1. **KNN over the derived ``claims`` index** (``search_claims`` — only
       currently-valid, non-superseded claims). Each claim hit is mapped back to
       its **subject entity** so the rest of the ask pipeline (citations, prompt
       building) is unchanged; the claim's provenance (``claim_id``, ``observer``,
       ``context``, ``valid_from``, ``source_trust``) rides along in the hit
       metadata so a citation can point at the claim + its valid-window + observer.
    2. **1-hop graph expansion:** the claim's ``object`` (when it is a node) is
       added as a low-weight neighbour subject so relational depth is retrievable.
    3. **Entity fallback:** when the bank has **no claims yet** (legacy /
       un-consolidated), fall back to ``search_entities`` so ``/ask`` never
       regresses on a graph that was indexed before M5 consolidation.

    ``embed_fn`` is injected by hermetic tests; ``None`` resolves the production
    embedder inside the indexer.
    """
    from api.services.id_utils import resolve_entity_file
    from api.services.vector_index import SqliteVecIndexer

    memory_path = Path(memory_path)
    indexer = SqliteVecIndexer(memory_path, embed_fn=embed_fn)

    def _subject_to_entity_id(subject: str) -> str | None:
        page = resolve_entity_file(memory_path, subject)
        return page.stem if page is not None else None

    def _claim_hit_to_entity_hit(hit: dict) -> dict | None:
        meta = hit.get("metadata", {}) or {}
        subject = str(meta.get("subject", "") or "")
        entity_id = _subject_to_entity_id(subject) or subject
        if not entity_id:
            return None
        return {
            "score": float(hit.get("score", 0.0) or 0.0),
            "text": hit.get("text", "") or "",
            "metadata": {
                "entity_id": entity_id,
                "entity_name": entity_id.replace("-", " ").title(),
                "type": "concept",
                "status": "active",
                "confidence": float(meta.get("confidence", 0.5) or 0.5),
                "file_path": str(meta.get("file_path", "")),
                # claim provenance carried into the citation (M5e contract):
                "claim_id": meta.get("claim_id"),
                "observer": meta.get("observer"),
                "context": meta.get("context"),
                "valid_from": meta.get("valid_from"),
                "source_trust": meta.get("source_trust"),
                "predicate": meta.get("predicate"),
                "object": meta.get("object"),
            },
        }

    def _retrieve(query: str, top_k: int) -> list[dict]:
        try:
            claim_hits = indexer.search_claims(query, top_k=top_k) or []
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"claim search failed, falling back to entities: {exc}")
            claim_hits = []

        if not claim_hits:
            # No claims in this bank (un-consolidated) — graceful entity fallback.
            return indexer.search_entities(query, top_k=top_k)

        # Map claim hits → subject-entity hits, preserving order + de-duping by
        # entity (keep the strongest-scoring claim per subject).
        out: list[dict] = []
        seen: set[str] = set()
        neighbours: list[str] = []
        for hit in claim_hits:
            mapped = _claim_hit_to_entity_hit(hit)
            if mapped is None:
                continue
            eid = mapped["metadata"]["entity_id"]
            if eid not in seen:
                seen.add(eid)
                out.append(mapped)
            # 1-hop expansion: the claim's object node becomes a neighbour subject.
            obj = str(hit.get("metadata", {}).get("object", "") or "")
            if obj and obj not in neighbours:
                neighbours.append(obj)

        # Add object-neighbours (1-hop) as low-weight grounding if room remains.
        for obj in neighbours:
            if len(out) >= top_k:
                break
            eid = _subject_to_entity_id(obj)
            if not eid or eid in seen:
                continue
            seen.add(eid)
            out.append({
                "score": 0.1,
                "text": "",
                "metadata": {
                    "entity_id": eid,
                    "entity_name": eid.replace("-", " ").title(),
                    "type": "concept",
                    "status": "active",
                    "confidence": 0.5,
                    "file_path": "",
                },
            })

        return out[:top_k]

    return _retrieve


def answer_query(
    memory_path,
    query: str,
    top_k: int = 6,
    *,
    retrieve_fn: RetrieveFn | None = None,
    llm_fn: LlmFn | None = None,
) -> dict:
    """Synthesize an auditable, gap-aware answer grounded only in retrieved memory.

    Returns a dict with: ``answer``, ``confidence`` (0..1 float), ``citations``
    (entity-level, each ``{entity_id, entity_name, file_path, snippet,
    source_episodes}``), ``gaps`` (explicit list of what could not be answered),
    and ``used_entities`` (the retrieved ids).
    """
    memory_path = Path(memory_path)
    query = (query or "").strip()

    # Empty/whitespace query: nothing to ground on — short-circuit before
    # spending a retrieval + LLM round-trip on garbage.
    if not query:
        return _gap_response(query)

    retrieve = retrieve_fn or _default_retrieve_fn(memory_path)
    try:
        hits = retrieve(query, top_k) or []
    except Exception as exc:  # noqa: BLE001 — retrieval must never crash the answer
        logger.warning(f"ask retrieval failed: {exc}")
        hits = []

    entities = _retrieved_entities(memory_path, hits)

    # Cold-index degrade: the vector index found nothing, but entities may exist
    # on disk (fresh install before the index is built). Fall back to a
    # substring scan so we don't falsely claim ignorance on a populated graph —
    # same graceful pattern as routers/search.py.
    if not entities:
        fallback_hits = _substring_match(memory_path, query, top_k)
        entities = _retrieved_entities(memory_path, fallback_hits)

    # Honest-gap fast path: nothing to ground on => do NOT call the LLM, do NOT
    # hallucinate. This is the key auditable-synthesis behaviour.
    if not entities:
        return _gap_response(query)

    retrieved_ids = [e["entity_id"] for e in entities]
    prompt = _build_prompt(query, entities)

    llm = llm_fn or _default_llm_fn()
    parsed: dict | None = None
    try:
        raw = llm(prompt)
        parsed = json.loads(_strip_fences(raw))
        if not isinstance(parsed, dict):
            parsed = None
    except Exception as exc:  # noqa: BLE001 — malformed reply must degrade, not 500
        logger.warning(f"ask synthesis parse failed: {exc}")
        parsed = None

    if parsed is None:
        # Degrade to an honest low-confidence answer over the retrieved entities
        # rather than inventing content from a broken model reply.
        names = ", ".join(e["entity_name"] for e in entities)
        return {
            "answer": (
                "I retrieved related memory but could not synthesize a reliable "
                f"answer. Relevant entities: {names}."
            ),
            "confidence": 0.15,
            "citations": _citations_for(entities, retrieved_ids),
            "gaps": ["Could not synthesize a grounded answer from the retrieved context."],
            "used_entities": retrieved_ids,
        }

    answer = str(parsed.get("answer", "")).strip()
    # Coerce list-shaped fields defensively: a model may return a bare string,
    # which must not be iterated character-by-character into the flagship fields.
    gaps = _coerce_str_list(parsed.get("gaps"))
    cited_raw = _coerce_str_list(parsed.get("used_entities"))
    # Only entities that were actually retrieved may be cited — drop any id the
    # model invented (anti-hallucination guard on the citation set).
    used = [eid for eid in cited_raw if eid in retrieved_ids]
    # Distinguish "model omitted used_entities" (benign: fall back to retrieved)
    # from "model cited only hallucinated ids" (a grounding failure: do NOT
    # silently attribute the answer to entities the model said it did not use).
    model_named_sources = bool(cited_raw)
    all_cited_invalid = model_named_sources and not used

    # Default confidence is conservative; an empty answer is itself a gap.
    confidence = _clamp_confidence(parsed.get("confidence"), default=0.5)

    if all_cited_invalid:
        # The answer claims grounding in entities that were never retrieved.
        # Treat as an ungrounded gap rather than fabricating provenance.
        if not gaps:
            gaps = [
                "The answer could not be grounded in any retrieved entity "
                f"for: {query}"
            ]
        return {
            "answer": (
                "I don't have grounded information in memory to answer that "
                "reliably."
            ),
            "confidence": min(confidence, 0.15),
            "citations": [],
            "gaps": gaps,
            "used_entities": [],
        }

    if not answer:
        answer = (
            "I don't have enough grounded information in memory to answer that."
        )
        if not gaps:
            gaps = [f"Memory did not yield a usable answer for: {query}"]
        confidence = min(confidence, 0.2)

    # used_entities reflects the model's actual selection where it named valid
    # sources; only when it omitted the field do we fall back to the retrieved
    # set. citations and used_entities therefore agree.
    cite_ids = used if used else retrieved_ids
    return {
        "answer": answer,
        "confidence": confidence,
        "citations": _citations_for(entities, cite_ids),
        "gaps": gaps,
        "used_entities": cite_ids,
    }


def _citations_for(entities: list[dict], cite_ids: list[str]) -> list[dict]:
    """Assemble entity-level citations for the given ids, preserving order."""
    by_id = {e["entity_id"]: e for e in entities}
    citations: list[dict] = []
    seen: set[str] = set()
    for eid in cite_ids:
        ent = by_id.get(eid)
        if ent is None or eid in seen:
            continue
        seen.add(eid)
        citation = {
            "entity_id": ent["entity_id"],
            "entity_name": ent["entity_name"],
            "file_path": ent["file_path"],
            "snippet": ent["snippet"],
            "source_episodes": ent["source_episodes"],
        }
        # When the grounding came from a claim, the citation points at the claim
        # id + its valid-window + observer (M5e), not just the entity page.
        prov = ent.get("claim_provenance")
        if prov:
            citation["claim_provenance"] = prov
        citations.append(citation)
    return citations


def _strip_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[len("json"):]
        text = text.strip()
    return text
