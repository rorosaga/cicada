"""One fact said in many conversations, under many names: what a page's Key Facts hold (G148, owner report 2026-11-23).

Run: python -m benchmarks.system.fact_fold_eval --scratch <new-empty-directory> [--variants dev,links,fold] [--model haiku]

Seven invented conversations each say something about one artist, five of them the same fact ("the partner's favourite
artist") worded differently — under the partner's name, her alias, a nickname, the owner's relation to her, a
translation. The recorded Stage-1 answer of each (invented names only) goes through the production Stage 3
(`conflict_resolver.resolve_and_prune`) and Stage 5's writer (`apply_changes`) in a scratch bank, in order, and the
artist's Key Facts are read after the last.

Variants: ``dev`` (nothing: how a page was written before), ``links`` (`link_names`: a link in new text is written under
the page's own name), ``fold`` (+ `fact_fold`: Sleep's small judge on the Claude plan, ``--model`` its tier; one ask and
one check per page per conversation, so at most 12 calls here). ``dev`` and ``links`` call no model.

Reported: Key Facts on the page, how many restate the favourite-artist fact, near-duplicate pairs (the page-quality
eval's own measure, `page_quality.near_duplicate`), the facts the conversations gave that are no longer on the page
(each has a marker that must survive: a date, a number, a name), the sources each marker keeps, and calls by stage."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path

from benchmarks.system.page_quality import near_duplicate

OWNER, PARTNER, ARTIST = "Owner Example", "Alice Example", "Artist Example"

#: Each conversation's recorded extraction for the artist page, in order. The fact "favourite of the partner" appears in
#: 1, 2, 3, 4, 5, 6 and 7; the others are one-off facts whose marker must stay on the page.
CONVERSATIONS = [
    ("ep_2026-11-01_001", [f"Favourite artist of [[{PARTNER}]]"]),
    ("ep_2026-11-03_001", ["Favorite artist of [[Girlfriend]]", "Toured Europe in 2025"]),
    ("ep_2026-11-05_001", ["Musical artist who is the favorite of [[Ally]].",
                           f"{OWNER} planned to buy one of his records as a gift."]),
    ("ep_2026-11-08_001", [f"{OWNER}'s girlfriend's favourite artist.", "Debut album released in 2019"]),
    ("ep_2026-11-12_001", [f"[[{OWNER}'s girlfriend]]'s favourite artist is {ARTIST}.",
                           f"{OWNER} plans to buy a vinyl copy for her birthday on 19 March"]),
    ("ep_2026-11-15_001", [f"Es el artista favorito de [[{PARTNER}]]", "Giró por Europa en 2025"]),
    ("ep_2026-11-19_001", ["Is [[Girlfriend]]'s favourite artist, noted in the gift guide.", "Won a Grammy in 2024"]),
]
#: What must still be on the page after the last conversation.
MARKERS = {"tour": r"2025|Europa", "debut": r"2019", "grammy": r"Grammy", "birthday": r"19 March", "gift": r"gift"}
FAVOURITE = re.compile(r"favou?rite|favorito", re.I)


def _entity(facts, episode):
    from api.services import section_provenance

    entity = {"name": ARTIST, "type": "person", "summary": "", "key_facts": list(facts), "aliases": []}
    section_provenance.attach(entity, episode, "the conversation")
    return entity


def _pages(bank: Path) -> list[dict]:
    from api.services import markdown_parser

    out = []
    for path in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        out.append({"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    return out


def run_variant(variant: str, scratch: Path, model: str) -> dict:
    from api.config import Settings
    from api.services import conflict_resolver as cr
    from api.services import fact_fold, link_names, markdown_parser, section_provenance

    bank = scratch / variant / "bank"
    (bank / "entities").mkdir(parents=True)
    base = {"type": "person", "status": "active", "confidence": 0.8, "source_episodes": ["ep_2026-10-01_001"]}
    markdown_parser.write(bank / "entities" / "owner-example.md", {**base, "name": OWNER, "owner": True, "aliases": []},
                          "## Summary\nThe person this memory belongs to.\n")
    markdown_parser.write(bank / "entities" / "alice-example.md",
                          {**base, "name": PARTNER, "aliases": ["Girlfriend", "Ally", f"{OWNER}'s girlfriend"]},
                          "## Summary\nThe owner's partner.\n")
    settings = Settings(_env_file=None, llm_mode="agent", agent_model=model, agent_disambiguation_model=model,
                        CICADA_MEMORY_PATH=str(bank))
    judge = fact_fold.judge_for(settings) if variant == "fold" else None
    calls = {"n": 0}
    if judge is not None:
        inner = judge

        def counting(prompt: str) -> dict:
            calls["n"] += 1
            return inner(prompt)
        judge = counting
    original = link_names.rewrite_changes
    if variant == "dev":
        link_names.rewrite_changes = lambda changes, names: 0
    try:
        for i, (episode, facts) in enumerate(CONVERSATIONS):
            change = {"id": "artist-example", "action": "create" if i == 0 else "update", "source_episode": episode,
                      "entity": _entity(facts, episode)}
            if i == 0:
                cr.apply_changes([change], bank)
                continue
            out = asyncio.run(cr.resolve_and_prune([change], _pages(bank), settings, decay=False,
                                                   now=datetime(2026, 11, 20), fact_judge=judge))
            cr.apply_changes(out, bank)
    finally:
        link_names.rewrite_changes = original
    parsed = markdown_parser.parse(bank / "entities" / "artist-example.md")
    scanned = section_provenance.scan(parsed.body).get("key_facts", [])
    facts = [i.text for i in scanned]
    proof = section_provenance.matched(parsed.frontmatter, parsed.body).get("key_facts", {})
    pairs = sum(near_duplicate(a, b) for k, a in enumerate(facts) for b in facts[k + 1:])
    favourite = [f for f in facts if FAVOURITE.search(f)]
    lost = [name for name, pattern in MARKERS.items() if not any(re.search(pattern, f) for f in facts)]
    sources = {item.text: sorted({ev.episode for ev in proof.get(item.key, (None, []))[1]}) for item in scanned}
    fav_sources = sorted({ep for f in favourite for ep in sources.get(f, [])})
    return {"variant": variant, "key_facts": len(facts), "favourite_bullets": len(favourite),
            "near_duplicate_pairs": pairs, "markers_lost": lost, "favourite_sources": len(fav_sources),
            "judge_calls": calls["n"], "facts": facts}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scratch", required=True, type=Path, help="a new, empty directory (nothing real is read)")
    ap.add_argument("--variants", default="dev,links,fold")
    ap.add_argument("--model", default="haiku")
    args = ap.parse_args(argv)
    if args.scratch.exists() and any(args.scratch.iterdir()):
        ap.error("--scratch must be new or empty")
    args.scratch.mkdir(parents=True, exist_ok=True)
    os.environ.update({"CICADA_HOME": str(args.scratch / "home"), "CICADA_CAPTURE": "off", "CICADA_RECALL": "off",
                       "CICADA_TELEMETRY": "off", "CICADA_ALLOW_CONNECTOR_FETCH": "off"})
    rows = [run_variant(v, args.scratch, args.model) for v in args.variants.split(",")]
    for row in rows:
        print(json.dumps({k: v for k, v in row.items() if k != "facts"}))
    for row in rows:
        print(f"\n[{row['variant']}] Key Facts:")
        for fact in row["facts"]:
            print(f"  - {fact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
