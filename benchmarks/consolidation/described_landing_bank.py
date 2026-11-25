"""The dry run: which facts, held under a label nobody said, would land on which page (2026-11-25, G148/G98).

    api/.venv/bin/python -m benchmarks.consolidation.described_landing_bank --bank PATH/TO/memory [--eyes FILE.jsonl]
                                                                        [--read [--max-reads N]] [--cache FILE]

Reads a bank's held lines, pages and conversations and runs the CODE conditions of `described_landing` (a label, the label as
the claim's subject, an open claim, located current words in the person's own turn, a conversation that names at least one
live project page; a tool or a concept is never a candidate). It WRITES NOTHING to the bank, opens no path a file names, never `~/.claude`, and calls no
model unless ``--read`` is given.

Without ``--read`` it prints, per claim that WOULD GO TO THE READER, one stable line of ids and enums, never a word of anyone's:

    to_read line=<8 hex: a hash of the held line's key> claim=<claim id> candidates=<n> turn=<user|speaker> conversation=<episode id>

With ``--read`` it also makes the reads (on whatever engine the environment selects, the main model, twice a group of claims
said in one conversation: `described_landing.read_group`; ``--engine plan --model haiku`` forces the Claude plan at haiku, the
benchmarks' path) and prints, per claim that WOULD LAND (both reads named the same candidate and each copied a sentence that
locates):

    would_land line=<8 hex> claim=<claim id> page=<page id> rule=land_described scope=<part|whole> turn=<kind> conversation=<id>

then counts: held lines, labels, claims looked at, the claims that reach the reader, what each code gate turned away
(``named_pages_not_projects``: the conversation names only tools or concepts, so nothing is read; stated on a line of its own), groups read, the calls made (this run and in
all), the claims that would land and why each other one stays held.

``--eyes FILE`` also writes, to a file OUTSIDE the repository (refused inside it), for the owner's eyes only, one JSON line per
claim that would land (the claim's text, the sentence copied, the held line's label, the chosen page and its name) and, for a
stable sample of up to ``--sample-left`` (40) claims that would NOT land, the same with the reason. The file holds words from the
bank; nothing else does.

**Stable and resumable.** Groups are read in a fixed order (line hash, conversation, claim id). Every group read is appended to
``--cache FILE`` (default: ``<eyes>.reads.jsonl`` beside the eyes file; with neither, nothing is kept) as soon as it is made, with
a digest of what the reader was shown; a run reads only groups the cache has no current answer for, at most ``--max-reads N``
groups (each is one call, or two when a read named a candidate), prints how many are still unread, and the next run continues.
An engine pause (a plan limit) stops the run cleanly with what was read kept. The cache holds the same words as the eyes file and
belongs outside the repository too."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def line_hash(name: str) -> str:
    from api.services.id_utils import sanitize_id

    return hashlib.sha1(sanitize_id(name).encode("utf-8")).hexdigest()[:8]


def group_key(group) -> str:
    ids = ",".join(sorted(i.claim.id for i in group.items))
    return f"{line_hash(group.line)}|{group.episode}|{hashlib.sha1(ids.encode()).hexdigest()[:8]}"


def stable_read(item, n_candidates: int) -> str:
    return (f"to_read line={line_hash(item.line)} claim={item.claim.id} candidates={n_candidates} turn={item.turn} "
            f"conversation={item.episode}")


def stable_land(row: dict) -> str:
    return (f"would_land line={row['line']} claim={row['claim']} page={row['page']} rule=land_described scope={row['scope']} "
            f"turn={row['turn']} conversation={row['conversation']}")


def load_cache(path: Path | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path is not None and path.is_file():
        for text in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(text)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("key"):
                out[row["key"]] = row
    return out


def make_ask(engine: str, model: str, bank: Path):
    """``(ask(system, prompt), settings)`` — the engine the environment selects, or the plan at ``model``."""
    import os

    from api.services import full_name_join, same_name_tend

    if engine == "plan":
        from benchmarks.consolidation.run import engine_model
        from benchmarks.engine_parity import settings_for

        os.environ.pop("ANTHROPIC_API_KEY", None)
        settings = settings_for("plan", bank, model=engine_model("plan", model), judge=engine_model("plan", model))
        strong = same_name_tend.main_tier(settings)
    else:
        from api.config import get_settings

        strong, why = asyncio.run(same_name_tend.main_engine(get_settings(), user_triggered=True))
        if strong is None:
            raise SystemExit(f"no engine to read with ({why}); choose one in Cicada's settings or pass --engine plan")

    async def ask(system: str, prompt: str) -> object:
        return await full_name_join.ask_main(strong, system, prompt)

    return ask, strong


async def read_all(bank: Path, groups, docs, cache: dict[str, dict], cache_path: Path | None, max_reads: int | None, ask) -> dict:
    from api.services import described_landing as dl
    from api.services import engine_errors

    stats = {"read": 0, "from_cache": 0, "unread": 0, "calls": 0, "stopped": ""}
    for g in groups:
        key = group_key(g)
        digest = dl._digest(bank, g, docs)
        if cache.get(key, {}).get("digest") == digest:
            stats["from_cache"] += 1
            continue
        if stats["stopped"] or (max_reads is not None and stats["read"] >= max_reads):
            stats["unread"] += 1
            continue
        try:
            got = await dl.read_group(bank, g, docs, ask)
        except engine_errors.EngineError as exc:
            stats["stopped"] = type(exc).__name__
            stats["unread"] += 1
            continue
        stats["read"] += 1
        stats["calls"] += got.calls
        rows = []
        for i, it in enumerate(g.items):
            pick = got.picks.get(i)
            seen = got.seen.get(i, ("", "", ""))
            rows.append({"claim": it.claim.id, "landed": pick is not None, "page": pick.page if pick else seen[0],
                         "scope": pick.scope if pick else "", "turn": it.turn, "reason": "" if pick else got.left.get(i, "failed_read"),
                         "sentence": " ".join(docs.get(g.episode)[1][pick.start:pick.end].split()) if pick else seen[1]})
        entry = {"key": key, "digest": digest, "line": line_hash(g.line), "line_name": g.line, "conversation": g.episode,
                 "calls": got.calls, "failed": got.failed, "claims": rows}
        if not got.failed:
            cache[key] = entry
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with cache_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bank", type=Path, required=True, help="a bank folder (read only)")
    p.add_argument("--eyes", type=Path, help="a file outside the repository: the same lines with the words, for the owner")
    p.add_argument("--read", action="store_true", help="make the reads (the engine's main model, twice a group)")
    p.add_argument("--max-reads", type=int, help="read at most this many groups this run (each is one or two calls)")
    p.add_argument("--cache", type=Path, help="where the reads are kept to continue (outside the repository)")
    p.add_argument("--sample-left", type=int, default=40, help="claims that would not land, shown in the eyes file")
    p.add_argument("--engine", choices=("env", "plan"), default="env", help="env: whatever the environment selects; plan: Claude plan")
    p.add_argument("--model", default="haiku", help="with --engine plan")
    a = p.parse_args(argv)
    if not (a.bank / "entities").is_dir():
        p.error(f"{a.bank} is not a bank (no entities folder)")

    def outside(path: Path | None, flag: str) -> Path | None:
        if path is None:
            return None
        path = path.expanduser().resolve()
        if path == REPO or REPO in path.parents:
            p.error(f"{flag} must name a file outside the repository")
        return path

    eyes = outside(a.eyes, "--eyes")
    cache_path = outside(a.cache, "--cache") or (eyes.with_name(eyes.name + ".reads.jsonl") if eyes is not None else None)
    from api.services import described_landing as dl

    plan = dl.plan_bank(a.bank)
    docs = dl.Docs(a.bank)
    groups = sorted(plan.groups, key=lambda g: (line_hash(g.line), g.episode, min(i.claim.id for i in g.items)))
    for g in groups:
        for it in sorted(g.items, key=lambda i: i.claim.id):
            if not a.read:
                print(stable_read(it, len(g.candidates)))
    cache = load_cache(cache_path) if a.read else {}
    stats = {"read": 0, "from_cache": 0, "unread": 0, "calls": 0, "stopped": ""}
    if a.read:
        ask, _strong = make_ask(a.engine, a.model, a.bank)
        stats = asyncio.run(read_all(a.bank, groups, docs, cache, cache_path, a.max_reads, ask))
    rows, staying = [], []
    for g in groups:
        entry = cache.get(group_key(g))
        if entry is None:
            continue
        for r in entry["claims"]:
            row = {**r, "line": entry["line"], "line_name": entry["line_name"], "conversation": entry["conversation"]}
            (rows if r["landed"] else staying).append(row)
    rows.sort(key=lambda r: (r["line"], r["conversation"], r["claim"]))
    staying.sort(key=lambda r: hashlib.sha1(r["claim"].encode()).hexdigest())
    for r in rows:
        print(stable_land(r))
    claims_in_groups = sum(len(g.items) for g in groups)
    print(f"held lines {plan.lines}; labels {plan.labels}; claims looked at {plan.claims}; "
          f"claims that reach the reader {claims_in_groups} in {len(groups)} group(s)")
    print(f"turned away because the conversation names only tools or concepts, no project: "
          f"{plan.skipped.get('named_pages_not_projects', 0)} claim(s)")
    print("turned away before the read: " + ", ".join(f"{k} {v}" for k, v in sorted(plan.skipped.items(), key=lambda kv: -kv[1])))
    if a.read:
        total_calls = sum(e.get("calls", 0) for e in cache.values())
        read_claims = sum(len(e["claims"]) for e in cache.values())
        print(f"groups read this run {stats['read']}, kept from earlier runs {stats['from_cache']}, still unread {stats['unread']}"
              + (f" (stopped: {stats['stopped']}; run again to continue)" if stats["stopped"] else
                 " (run again with --read to continue)" if stats["unread"] else ""))
        print(f"model calls made: {stats['calls']} this run, {total_calls} for the {read_claims} claim(s) read so far"
              + (f" ({total_calls / read_claims:.2f} a claim)" if read_claims else ""))
        why = Counter(r["reason"] for r in staying)
        print(f"would land {len(rows)} on {len({r['page'] for r in rows})} page(s); stay held {len(staying)}: "
              + ", ".join(f"{k} {v}" for k, v in sorted(why.items(), key=lambda kv: -kv[1])))
    if eyes is not None:
        from api.services import described_landing as dl2

        out = []
        for r in rows + staying[:max(0, a.sample_left)]:
            doc = docs.get(r["conversation"])
            claim = next((i.claim for g in groups for i in g.items if i.claim.id == r["claim"]), None)
            page = dl2._page_text(a.bank, r["page"]) if r["page"] else None
            out.append({"would_land": r["landed"], "reason": r["reason"], "claim_id": r["claim"], "claim_text": claim.text if claim else "",
                        "copied_sentence": r["sentence"], "label": r["line_name"], "page": r["page"], "page_name": page[0] if page else "",
                        "scope": r["scope"], "turn": r["turn"], "conversation": r["conversation"], "line": r["line"],
                        "conversation_title": str((doc[0].get("title") or "")) if doc else ""})
        eyes.parent.mkdir(parents=True, exist_ok=True)
        eyes.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + ("\n" if out else ""), encoding="utf-8")
        print(f"eyes-only file: {len(rows)} would-land line(s) and {len(out) - len(rows)} held, written")
    return 2 if stats["stopped"] else 0


if __name__ == "__main__":
    sys.exit(main())
