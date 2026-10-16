"""Build a synthetic bank at the owner's whole-bank scale (coordinator's count, 2026-10-16): ~4,700 entity pages
(~850 of them saved items), a few thousand episodes and an inbox of ~240 questions — on top of ``synth``'s owner page.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.owner_scale --bank <dir>/bank

Every name, URL and sentence is synthetic (``example.com``/``alpha-0001``); no fetch is made (saved items are written
through the offline half of the ingest path, ``media_ingestor.write_prepared``).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

from . import isolate, synth


def add_saved_items(bank: Path, rng: random.Random, n: int, processed: int) -> int:
    from api.services import media_ingestor
    from api.services.media_ingestor import MediaMeta, PreparedItem, RawItem

    idx = media_ingestor.load_url_index(bank)
    kinds = ["url", "url", "bookmark", "youtube", "url"]
    for i in range(n):
        kind = kinds[i % len(kinds)]
        if kind == "youtube":
            url = f"https://www.youtube.com/watch?v=synth{i:06d}"
        else:
            url = f"https://site{i % 120}.example.com/{rng.choice(synth.WORDS)}/{i}"
        title = synth.sentence(rng, rng.randint(4, 10)).rstrip(".")
        item = RawItem(url=url, title=title, origin="chrome-bookmark" if kind == "bookmark" else None)
        meta = MediaMeta(title=title, description=synth.sentence(rng, rng.randint(15, 40)),
                         site=f"site{i % 120}.example.com", media_type=kind)
        media_ingestor.write_prepared(PreparedItem(item, meta, kind == "bookmark"), bank, idx)
    media_ingestor.save_url_index(bank, idx)
    # Most saved items in a lived-in bank were read by an earlier Sleep.
    flipped = 0
    for path in sorted((bank / "episodes").glob("*.md")):
        if flipped >= processed:
            break
        text = path.read_text(encoding="utf-8")
        if "media_entity_id:" in text and "processed: false" in text:
            path.write_text(text.replace("processed: false", "processed: true", 1), encoding="utf-8")
            flipped += 1
    return len(idx)


def add_inbox(bank: Path, rng: random.Random, n: int) -> int:
    from api.services import inbox_generator
    from api.services.inbox_generator import DecayBudget

    pages = sorted(p.stem for p in (bank / "entities").glob("*.md") if not p.name.endswith(".claims.jsonl"))
    nudges = []
    for i in range(n):
        eid = pages[(i * 37) % len(pages)]
        kind = i % 4
        if kind == 0:
            nudges.append({"id": eid, "action": "decay_nudge", "entity": {"name": eid.title()},
                           "new_confidence": round(rng.uniform(0.2, 0.39), 2), "claim_id": f"clm_{eid}_000",
                           "source_episode": "", "trigger": "sleep/decay"})
        elif kind == 1:
            nudges.append({"id": eid, "action": "conflict_nudge", "entity": {"name": eid.title()},
                           "predicate": f"pred{i}", "conflict_context": synth.sentence(rng, 20),
                           "options": ["Keep A", "Take B", "Both true"], "claim_id": f"clm_{eid}_{i:03d}"})
        elif kind == 2:
            nudges.append({"id": eid, "action": "divergence_nudge", "entity": {"name": eid.title()},
                           "conflict_context": synth.sentence(rng, 20), "options": ["Keep X", "Update to Y"],
                           "trigger": "sleep/conflict_resolution", "claim_id": f"clm_{eid}_{i:03d}"})
        else:
            nudges.append({"id": eid, "action": "normalization_audit", "entity": {"name": eid.title()},
                           "conflict_context": f"Predicate 'p{i}' was folded to 'uses'. Confirm.",
                           "options": ["Correct fold", "Wrong fold"], "trigger": "sleep/conflict_resolution",
                           "claim_id": f"clm_{eid}_{i:03d}", "raw_predicate": f"p{i}", "predicate": "uses"})
    inbox_generator.write_claim_nudges(nudges, bank, DecayBudget(cap=None))
    return len(list((bank / "inbox").glob("inbox-*.md")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--pages", type=int, default=3850, help="conversation pages (saved items are added on top)")
    ap.add_argument("--claims", type=int, default=5400, help="owner-page claims")
    ap.add_argument("--episodes", type=int, default=3000)
    ap.add_argument("--processed", type=int, default=2800)
    ap.add_argument("--saved", type=int, default=850)
    ap.add_argument("--inbox", type=int, default=240)
    ap.add_argument("--commits", type=int, default=40)
    ap.add_argument("--turns-max", type=int, default=60)
    a = ap.parse_args()
    bank = a.bank.resolve()
    started = time.perf_counter()
    synth.JSONL = True
    synth.TURNS_MAX = a.turns_max
    synth.LABELS.append("asked about")
    out = synth.build(bank, a.claims, a.pages, a.episodes, a.processed, a.commits, 7, related=2024,
                      related_section=True, activity=True, owner_facts=30, owner_history=800)
    rng = random.Random(11)
    out["saved_items"] = add_saved_items(bank, rng, a.saved, int(a.saved * 0.95))
    out["inbox_items"] = add_inbox(bank, rng, a.inbox)
    synth.git(bank, "add", "-A")
    synth.git(bank, "commit", "-q", "-m", "Synthetic saved items and inbox\n\nCicada-Author: cicada")
    out["entity_pages"] = sum(1 for p in (bank / "entities").glob("*.md"))
    out["episode_files"] = sum(1 for _ in (bank / "episodes").glob("*.md"))
    out["queued"] = sum(1 for p in (bank / "episodes").glob("*.md")
                        if re.search(r"^processed: false$", p.read_text(encoding="utf-8"), re.M))
    out["build_seconds"] = round(time.perf_counter() - started, 1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
