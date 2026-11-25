"""The dry run: which facts, held under a label nobody said, would land on which page (2026-11-25, G148/G98).

    api/.venv/bin/python -m benchmarks.consolidation.described_landing_bank --bank PATH/TO/memory [--eyes FILE.jsonl] [--read]

Reads a bank's held lines, pages and conversations and runs the CODE gates of `described_landing` (the rule's first six
conditions: a label, the label as subject, an open claim, located words in the person's own turn, a sentence that names exactly
one page that may hold a part, the label's words as one run joined to the page by containment or possession). It WRITES
NOTHING to the bank, opens no path a file names, never `~/.claude`, and calls no model unless ``--read`` is given.

For every claim that would land (the gates passed; the second reading of the main model still has to agree) it prints one stable
line of ids and enums, never a word of anyone's:

    would_land line=<8 hex: a hash of the held line's key> claim=<claim id> page=<page id> rule=land_described turn=<user|speaker> conversation=<episode id>

then counts: how many held lines are labels, how many claims were looked at, and how many each gate turned away (the reasons are
the gates' own names). ``--eyes FILE`` also writes, to a file OUTSIDE the repository (refused inside it), the same lines WITH the
held line's name, the sentence and the claim's text, for the owner's eyes only. ``--read`` asks the engine's main model the two
questions the live step asks (`described_landing.read`, the plan; the bank's own words go to that model) and prints only what it
confirmed, as ``confirmed`` lines with the verdict (``part`` or ``whole``); the file holds the verdict too."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def line_hash(name: str) -> str:
    from api.services.id_utils import sanitize_id

    return hashlib.sha1(sanitize_id(name).encode("utf-8")).hexdigest()[:8]


def stable(item, verdict: str | None = None) -> str:
    head = "would_land" if verdict is None else f"confirmed({verdict})"
    return (f"{head} line={line_hash(item.line)} claim={item.claim.id} page={item.page} rule={item.rule} "
            f"turn={item.turn} conversation={item.episode}")


async def read_all(bank: Path, plan, docs) -> dict[tuple[str, str], dict[int, str]]:
    import os

    from api.services import full_name_join, pending_store, same_name_tend
    from benchmarks.consolidation.run import engine_model
    from benchmarks.engine_parity import settings_for

    os.environ.pop("ANTHROPIC_API_KEY", None)
    from api.services import described_landing

    settings = settings_for("plan", bank, model=engine_model("plan", "haiku"), judge=engine_model("plan", "haiku"))
    strong = same_name_tend.main_tier(settings)

    async def ask(_settings, system, prompt):
        return await full_name_join.ask_main(strong, system, prompt)

    lines = {l.name: l for l in pending_store.load(bank)}
    pairs: dict[tuple[str, str], list] = defaultdict(list)
    for it in plan.items:
        pairs[(it.line, it.page)].append(it)
    out = {}
    for (name, page), items in pairs.items():
        out[(name, page)] = await described_landing.read(bank, strong, lines[name], page, items, docs, ask=ask)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bank", type=Path, required=True, help="a bank folder (read only)")
    p.add_argument("--eyes", type=Path, help="a file outside the repository: the same lines with the words, for the owner")
    p.add_argument("--read", action="store_true", help="also ask the engine's main model (the plan)")
    a = p.parse_args(argv)
    if not (a.bank / "entities").is_dir():
        p.error(f"{a.bank} is not a bank (no entities folder)")
    eyes = a.eyes.expanduser().resolve() if a.eyes else None
    if eyes is not None and (eyes == REPO or REPO in eyes.parents):
        p.error("--eyes must name a file outside the repository")
    from api.services import described_landing as dl

    plan = dl.plan_bank(a.bank)
    docs = dl.Docs(a.bank)
    verdicts = asyncio.run(read_all(a.bank, plan, docs)) if a.read else None
    rows = []
    for it in sorted(plan.items, key=lambda i: (i.page, i.claim.id)):
        said = None
        if verdicts is not None:
            index = [x for x in plan.items if (x.line, x.page) == (it.line, it.page)].index(it)
            said = verdicts.get((it.line, it.page), {}).get(index)
            if said is None:
                continue
        print(stable(it, said))
        doc = docs.get(it.episode)
        rows.append({"line": line_hash(it.line), "line_name": it.line, "claim": it.claim.id, "claim_text": it.claim.text,
                     "page": it.page, "rule": it.rule, "turn": it.turn, "conversation": it.episode, "verdict": said,
                     "sentence": " ".join(doc[1][it.sentence[0]:it.sentence[1]].split()) if doc else ""})
    print(f"held lines {plan.lines}; labels {plan.labels}; claims looked at {plan.claims}; "
          f"would land {len(plan.items)} on {len({i.page for i in plan.items})} pages"
          + (f"; confirmed {len(rows)}" if verdicts is not None else ""))
    print("turned away: " + ", ".join(f"{k} {v}" for k, v in sorted(plan.skipped.items(), key=lambda kv: -kv[1])))
    if eyes is not None:
        eyes.parent.mkdir(parents=True, exist_ok=True)
        eyes.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""), encoding="utf-8")
        print(f"eyes-only file: {len(rows)} line(s) written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
