"""Source-grounded rewrite: re-read an entity's primary sources and rewrite its
page richer + strictly source-faithful. Preserves human sections + claims block.
Every rewrite is a git commit (caller commits in batch mode)."""
from __future__ import annotations
import json
from loguru import logger
from pathlib import Path
from api.services import markdown_parser, entity_body
from api.services.claims import MalformedClaimsBlockError, parse_claims, write_claims, strip_claims_block
from api.services.entity_sources import gather_entity_sources

_PROMPT = (
    "You are re-writing a personal knowledge-graph entity page using ONLY the source "
    "conversation excerpts below. Produce a richer, well-structured markdown body with the "
    "sections: ## Summary, ## Key Facts (bullets), and ## History (dated bullets) when supported. "
    "RULES: state ONLY facts present in the sources; never invent details; keep it faithful and "
    "specific (names, numbers, dates). Reply JSON {{\"body\": \"<markdown body>\"}}.\n\n"
    "CURRENT PAGE:\n{page}\n\nSOURCES:\n{sources}"
)


def _words(s: str) -> int:
    return len((s or "").split())


def rewrite_entity_from_sources(memory_path: Path, entity_id: str, settings, *,
                                corpus_path: Path | None = None, llm_fn=None,
                                max_source_chars: int = 12000) -> dict:
    ent = memory_path / "entities" / f"{entity_id}.md"
    if not ent.exists():
        return {"entity_id": entity_id, "changed": False, "before_words": 0, "after_words": 0}
    par = markdown_parser.parse(ent)
    before = _words(par.body)

    bundle = gather_entity_sources(memory_path, entity_id,
                                   mode="full" if corpus_path else "chunks",
                                   corpus_path=corpus_path)
    src_parts = []
    for e in bundle["episodes"]:
        src_parts.append(e.get("chunk", ""))
        conv = e.get("conversation")
        if conv:
            msgs = conv.get("chat_messages", [])[:40]
            src_parts.append("\n".join(m.get("text", "") for m in msgs))
    sources = "\n---\n".join(s for s in src_parts if s)[:max_source_chars]
    if not sources.strip():
        return {"entity_id": entity_id, "changed": False,
                "before_words": before, "after_words": before}

    if llm_fn is None:  # pragma: no cover - runtime
        from api.services.providers import resolve_llm_fn
        llm_fn = resolve_llm_fn(settings, model=settings.effective_consolidation_model)

    resp = llm_fn(messages=[{"role": "user",
                             "content": _PROMPT.format(page=par.body[:4000], sources=sources)}],
                  response_format={"type": "json_object"})
    txt = resp["choices"][0]["message"]["content"]
    s, e = txt.find("{"), txt.rfind("}")
    if s < 0 or e <= s:
        return {"entity_id": entity_id, "changed": False,
                "before_words": before, "after_words": before}
    try:
        new_body = json.loads(txt[s:e + 1]).get("body", "").strip()
    except Exception:
        return {"entity_id": entity_id, "changed": False,
                "before_words": before, "after_words": before}
    if not new_body:
        return {"entity_id": entity_id, "changed": False,
                "before_words": before, "after_words": before}

    # Preserve the existing ```claims block verbatim — the rewrite must not
    # introduce/alter claims. Capture it before merging, then merge on the
    # claims-stripped bodies so the fence can never end up mid-section.
    # strict: a corrupt block would otherwise read as "no claims" and the
    # rewrite below would drop it from the final body.
    try:
        existing_claims = parse_claims(par.body, strict=True)
    except MalformedClaimsBlockError as exc:
        logger.error(f"corrupt ```claims block on {entity_id}, skipping rewrite: {exc}")
        return {"entity_id": entity_id, "changed": False,
                "before_words": before, "after_words": before,
                "error": "corrupt_claims_block"}

    # Human-safe merge: never lose human sections or the claims block. Convert the
    # LLM's new body to the STRUCTURED new_fields shape via sections_to_fields
    # (a raw sections dict merges nothing).
    human = bool(par.frontmatter.get("human_edited"))
    new_sections = entity_body.parse_sections(strip_claims_block(new_body))
    new_fields = entity_body.sections_to_fields(new_sections)
    merged = entity_body.merge_sections_human_safe(
        entity_body.parse_sections(strip_claims_block(par.body)), new_fields, human_edited=human)
    # Preserve any non-canonical sections the model produced.
    for title, content in new_sections.items():
        if title and title not in entity_body.CANONICAL_SECTIONS and title not in merged:
            merged[title] = content
    final_body = "\n\n".join(f"## {t}\n{c}" if t else c
                             for t, c in merged.items() if c).strip()
    if existing_claims:
        final_body = write_claims(final_body, existing_claims)
    fm = dict(par.frontmatter)
    fm["layout_version"] = 2
    markdown_parser.write(ent, fm, final_body)
    return {"entity_id": entity_id, "changed": True,
            "before_words": before, "after_words": _words(final_body)}
