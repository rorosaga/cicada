"""The owner page as an agent and Sleep meet it: its size on disk, what `cicada_recall_detail` answers first and how
long it takes, whether the article writer's input fits its budget, and what one Sleep-stage write of the page costs.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.owner_page --bank <dir>/bank [--write]

``--write`` also times one claim write-back of the page (the bank is mutated: run it on a copy). Synthetic banks only.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import isolate

OWNER = "owner-example"


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def measure(bank: Path, *, write: bool) -> dict:
    isolate.pin_bank(bank)
    from api.config import Settings
    from api.services import claims, conflict_resolver, entity_body, markdown_parser, mcp_tools

    page = bank / "entities" / f"{OWNER}.md"
    ledger = page.with_name(f"{OWNER}.claims.jsonl")
    out: dict = {"page_bytes": page.stat().st_size,
                 "ledger_bytes": ledger.stat().st_size if ledger.exists() else 0}

    started = time.perf_counter()
    parsed = markdown_parser.parse(page)
    out["parse_ms"] = _ms(started)
    every = claims.parse_claims(parsed.body, strict=True)
    out["claims"] = len(every)
    out["claim_ids"] = len({c.id for c in every})
    out["evidence_spans"] = sum(len(c.evidence) for c in every)
    sections = entity_body.parse_sections(claims.strip_claims_block(parsed.body))
    out["related_lines"] = sum(1 for line in sections.get("Related", "").splitlines() if line.strip().startswith("- "))
    out["related_links"] = sections.get("Related", "").count("[[")
    raw = page.read_text(encoding="utf-8")
    fence = claims.claims_block_start(raw)
    out["page_fence_bytes"] = len(raw.encode()) - len(raw[:fence].encode()) if fence is not None else 0

    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="probe", harness="unknown")
    started = time.perf_counter()
    first = str(mcp_tools.recall_detail(ctx, OWNER))
    out["recall_detail_cold_ms"] = _ms(started)   # includes the bank's name index, built once per process
    started = time.perf_counter()
    first = str(mcp_tools.recall_detail(ctx, OWNER))
    out["recall_detail_ms"] = _ms(started)
    out["recall_detail_chars"] = len(first)
    out["recall_detail_first_part_has_summary"] = "## Summary" in first
    out["recall_detail_first_part_frontmatter_share"] = round(
        (first.index("\n---\n", 4) + 5) / len(first), 2) if first.startswith("---\n") and "\n---\n" in first[4:] \
        else 0.0

    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank), page_articles_enabled=True)
    existing = [{"id": OWNER, "frontmatter": parsed.frontmatter, "body": parsed.body}]
    for other in sorted((bank / "entities").glob("*.md"))[:3000]:
        if other.stem != OWNER:
            existing.append({"id": other.stem, "frontmatter": markdown_parser.parse(other).frontmatter, "body": ""})
    context = conflict_resolver._article_context(existing, settings, "2026-10-14", bank)
    change = {"id": OWNER, "action": "update", "source_episodes": ["ep_2026-10-14_001"],
              "entity": {"key_facts": ["Owner Example studies at a synthetic university."]}}
    started = time.perf_counter()
    job = conflict_resolver._article_job(change, existing[0], change["entity"], context)
    out["article_job_ms"] = _ms(started)
    out["article_budget"] = context["max_chars"]
    out["article_prompt_chars"] = len(job["prompt"]) if job else None
    out["article_inputs"] = len(job["inputs"].sources) if job else None

    if write:
        started = time.perf_counter()
        again = markdown_parser.parse(page)
        current = claims.parse_claims(again.body, strict=True)
        markdown_parser.write(page, again.frontmatter, claims.write_claims(again.body, current))
        out["stage_write_ms"] = _ms(started)
        from api.services import claim_pipeline
        started = time.perf_counter()
        loaded = claim_pipeline._load_existing_claims_by_subject(bank)
        out["load_all_claims_ms"] = _ms(started)
        out["owner_claims_after_write"] = len(loaded.get(OWNER, []))
        out["page_bytes_after_write"] = page.stat().st_size
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    print(json.dumps(measure(a.bank.resolve(), write=a.write), indent=1))


if __name__ == "__main__":
    main()
