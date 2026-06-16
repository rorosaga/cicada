"""Backfill existing entity pages to the v2 section layout.

Two tiers:
  --structural   Free, pure string transform. Lifts v1 flat bodies into the
                 canonical section layout (Summary / Key Facts / History /
                 Related / Links / Open Questions) and stamps layout_version: 2.
                 No LLM calls, content is preserved verbatim.
  --enrich       LLM pass on top of --structural: reorganizes the existing body
                 into a tighter Summary + Key Facts bullets. Never invents
                 facts — it only restructures what the page already says.
                 Prints a cost estimate and requires --yes to proceed.

Usage:
  python -m scripts.backfill_entity_pages --memory /path/to/memory --structural
  python -m scripts.backfill_entity_pages --memory /path/to/memory --enrich --yes

The --memory argument is REQUIRED and never defaults to the live memory dir.
A git commit is made at the end so the backfill is one provenance event.
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api.services import markdown_parser  # noqa: E402
from api.services.entity_body import (  # noqa: E402
    parse_sections,
    render_sections,
    upgrade_legacy_to_v2,
)

# Rough per-entity token budget for the enrich tier (prompt + completion),
# priced against a small model. Printed, not enforced.
_ENRICH_TOKENS_PER_ENTITY = 900
_ENRICH_USD_PER_MTOK = 0.60


def _candidates(entities_dir: Path) -> list[Path]:
    out = []
    for filepath in sorted(entities_dir.glob("*.md")):
        try:
            parsed = markdown_parser.parse(filepath)
        except Exception:
            continue
        fm = parsed.frontmatter or {}
        if int(fm.get("layout_version", 1) or 1) < 2:
            out.append(filepath)
    return out


def backfill_structural(memory_path: Path) -> int:
    entities_dir = memory_path / "entities"
    changed = 0
    for filepath in _candidates(entities_dir):
        parsed = markdown_parser.parse(filepath)
        fm = dict(parsed.frontmatter or {})
        sections = upgrade_legacy_to_v2(parsed.body, str(fm.get("type", "concept")))
        new_body = render_sections(sections)
        if not new_body.strip():
            continue
        fm["layout_version"] = 2
        markdown_parser.write(filepath, fm, new_body)
        changed += 1
    return changed


async def _enrich_one(filepath: Path, model: str) -> bool:
    import json

    import litellm

    parsed = markdown_parser.parse(filepath)
    fm = dict(parsed.frontmatter or {})
    sections = upgrade_legacy_to_v2(parsed.body, str(fm.get("type", "concept")))
    source_text = render_sections(sections)
    if len(source_text) < 80:
        # Too thin to restructure meaningfully — structural stamp only.
        fm["layout_version"] = 2
        markdown_parser.write(filepath, fm, source_text or parsed.body)
        return False

    prompt = (
        "Restructure this personal-knowledge entity page. Rewrite '## Summary' as "
        "1-3 tight sentences and extract '## Key Facts' as short bullets. Use ONLY "
        "information already present — never invent facts, names, or dates. Keep "
        "[[wikilinks]] exactly as written. Return JSON: "
        '{"summary": str, "key_facts": [str, ...]}\n\n'
        f"Entity type: {fm.get('type', 'concept')}\nPage:\n{source_text[:4000]}"
    )
    try:
        resp = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"  skip {filepath.name}: {type(e).__name__}: {e}")
        return False

    if data.get("summary"):
        sections["Summary"] = str(data["summary"]).strip()
    facts = [str(f).strip() for f in data.get("key_facts") or [] if str(f).strip()]
    if facts:
        sections["Key Facts"] = "\n".join(f"- {f}" for f in facts)

    fm["layout_version"] = 2
    markdown_parser.write(filepath, fm, render_sections(sections))
    return True


async def backfill_enrich(memory_path: Path, model: str) -> int:
    entities_dir = memory_path / "entities"
    candidates = _candidates(entities_dir)
    sem = asyncio.Semaphore(8)
    enriched = 0

    async def worker(fp: Path):
        nonlocal enriched
        async with sem:
            if await _enrich_one(fp, model):
                enriched += 1

    await asyncio.gather(*(worker(fp) for fp in candidates))
    return enriched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--memory", required=True, help="Path to the memory directory")
    tier = ap.add_mutually_exclusive_group(required=True)
    tier.add_argument("--structural", action="store_true")
    tier.add_argument("--enrich", action="store_true")
    ap.add_argument("--yes", action="store_true", help="Confirm the enrich tier (paid)")
    ap.add_argument("--model", default=None, help="Override the LLM for --enrich")
    args = ap.parse_args()

    memory_path = Path(args.memory).expanduser().resolve()
    if not memory_path.exists() or not (memory_path / "entities").exists():
        print(f"error: {memory_path} is not a memory directory (no entities/)")
        return 1

    n_candidates = len(_candidates(memory_path / "entities"))
    print(f"{n_candidates} entity pages below layout_version 2 in {memory_path}")
    if n_candidates == 0:
        return 0

    if args.enrich:
        from api.config import get_settings

        model = args.model or get_settings().litellm_model
        est = n_candidates * _ENRICH_TOKENS_PER_ENTITY / 1_000_000 * _ENRICH_USD_PER_MTOK
        print(f"enrich tier: ~{_ENRICH_TOKENS_PER_ENTITY} tok/entity via {model} "
              f"(~${est:.2f} total estimate)")
        if not args.yes:
            print("refusing to spend without --yes")
            return 1
        enriched = asyncio.run(backfill_enrich(memory_path, model))
        print(f"enriched {enriched} pages (others stamped structurally)")
    else:
        changed = backfill_structural(memory_path)
        print(f"restructured {changed} pages (no LLM calls)")

    import subprocess

    subprocess.run(["git", "add", "entities"], cwd=memory_path, check=False)
    subprocess.run(
        ["git", "commit", "-m",
         f"Backfill entity pages to v2 layout (trigger: user/manual_edit)", "--", "entities"],
        cwd=memory_path, check=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
