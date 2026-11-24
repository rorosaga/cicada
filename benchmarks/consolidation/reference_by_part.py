"""A thing named once, then spoken of by a part or a plain noun: does its later progress reach the thing? (2026-11-24)

`reference_by_part_stories.json` names a thing in two conversations and, weeks later, speaks of it only by a part or a
plain noun ("chapter 3", "the frame", "der Motor", "the boat"); `reference_by_part_counter.json` holds the counter-stories,
where the part or noun belongs to another thing or is a thing of its own (two projects that each have "the draft", a
kitchen that is its own renovation, a tool used on two builds). Each runs through the real Sleep on a scratch bank, one
night a phase (`run.run_leg`), and an engine-free check reads the bank:

* ``expect.stories[]``: ``whole`` (a regex over a page's id, name and aliases, the thing's own page), ``facts`` (regexes of
  what a later conversation said), ``others`` (regexes of the pages that must NOT carry those facts) and ``ask`` (a
  question and, per group, words any one of which the answer must hold).
* a fact is **on** a page when its regex matches the page's words or one of its claims; it **reaches** the whole when it is
  on the whole's page, or on a page the whole links to (a wikilink, a claim whose object is that page, ``related``) or that
  links to it. A fact only on the owner's page, or held under a name with no page, does not reach it. A fact **folded**
  is on a page an ``others`` regex names, or on another story's whole.

    api/.venv/bin/python -m benchmarks.consolidation.reference_by_part --fixture reference_by_part_stories.json --out /tmp/r1
    api/.venv/bin/python -m benchmarks.consolidation.reference_by_part --model haiku --out /tmp/r2 --trace

``--engine plan`` only (the signed-in Claude plan, no key is read). ``--trace`` writes ``trace.jsonl`` beside the bank:
what Stage 1 emitted per conversation, the candidates Stage 2 offered each name and what its judge answered.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
STORIES = HERE / "reference_by_part_stories.json"
WIKILINK = re.compile(r"\[\[([^\]|#]+)")


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def _slug(text) -> str:
    return re.sub(r"[^\w]+", "-", _fold(text), flags=re.U).strip("-")


def load_pages(bank: Path) -> dict[str, dict]:
    """Every page: its words (prose and claim texts), its names, and the ids it points to or lists as related."""
    from api.services import claims as claims_module, markdown_parser

    pages: dict[str, dict] = {}
    for path in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter or {}
        prose = claims_module.strip_claims_block(parsed.body)
        found = claims_module.parse_claims(parsed.body)
        aliases = fm.get("aliases") or []
        links = {_slug(m) for m in WIKILINK.findall(parsed.body)} | {_slug(r) for r in (fm.get("related") or [])}
        links |= {_slug(c.object) for c in found if isinstance(c.object, str)}
        pages[path.stem] = {
            "id": path.stem, "name": str(fm.get("name") or path.stem), "type": fm.get("type"), "owner": bool(fm.get("owner")),
            "aliases": [str(a) for a in (aliases if isinstance(aliases, list) else [aliases])],
            "text": prose + "\n" + "\n".join(str(c.text or "") for c in found),
            "links": links - {path.stem},
        }
    return pages


def _is(page: dict, pattern: str) -> bool:
    rx = re.compile(pattern, re.I)
    return any(rx.search(s) for s in [page["id"], page["name"], *page["aliases"]])


def check(bank: Path, expect: dict) -> dict:
    """Per story and fact: where it is, whether it reaches the thing's page, whether anything is folded."""
    pages = load_pages(bank)
    stories = expect["stories"]
    wholes = {s["id"]: {pid for pid, p in pages.items() if not p["owner"] and _is(p, s["whole"])} for s in stories}
    rows, ok = [], True
    for s in stories:
        mine = wholes[s["id"]]
        foreign = {pid for sid, held in wholes.items() if sid != s["id"] for pid in held} - mine
        conflated = sorted(mine & {pid for sid, held in wholes.items() if sid != s["id"] for pid in held})
        wrong = {pid for pid, p in pages.items() if not p["owner"] and any(_is(p, rx) for rx in s.get("others") or [])} - mine
        facts = []
        for rx in s["facts"]:
            hit = re.compile(rx, re.I)
            where = [pid for pid, p in pages.items() if hit.search(p["text"])]
            direct = sorted(set(where) & mine)
            linked = sorted(pid for pid in where if pid not in mine and not pages[pid]["owner"]
                            and (pages[pid]["links"] & mine or any(pid in pages[m]["links"] for m in mine)))
            folded = sorted((set(where) & (wrong | foreign)) - mine)
            facts.append({"fact": rx, "where": where, "direct": direct, "linked": linked, "folded": folded,
                          "reaches": bool(direct or linked)})
        # One thing on two pages is the defect this measures: two pages that name it, with nothing joining them, are split;
        # joined by a relation (a wikilink, a claim whose object is the other) they are a whole and its part.
        joined = all(any(b in pages[a]["links"] or a in pages[b]["links"] for b in mine if b != a) for a in mine) if len(mine) > 1 else True
        row = {"id": s["id"], "whole_pages": sorted(mine), "facts": facts,
               "reaches": all(f["reaches"] for f in facts), "direct": all(f["direct"] for f in facts),
               "folded": any(f["folded"] for f in facts), "own_page": bool(mine), "split": len(mine) > 1 and not joined, "conflated": conflated,
               "one_page": len(mine) == 1}
        row["ok"] = row["reaches"] and not row["folded"] and not row["split"] and not conflated
        ok = ok and row["ok"]
        rows.append(row)
    return {"ok": ok, "stories": rows}


class Trace:
    """What the chain did, one json line each: Stage 1's entities per conversation, a name's candidates, the verdicts."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, **row) -> None:
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

    def install(self, stack) -> None:
        from api.services import entity_extractor, entity_resolver

        trace = self
        extract = entity_extractor.extract

        async def traced_extract(episodes, settings, **kw):
            got = await extract(episodes, settings, **kw)
            for r in got:
                trace.write(kind="stage1", episode=r.get("episode_id") or r.get("id"), title=r.get("title"),
                            entities=[{k: e.get(k) for k in ("name", "type", "summary", "aliases") if e.get(k)}
                                      for e in r.get("entities") or []])
            return got

        import functools
        traced_extract = functools.wraps(extract)(traced_extract)
        judge = entity_resolver._judge_candidates

        async def traced_judge(new_entity, candidates, cache, settings, **kw):
            judged = await judge(new_entity, candidates, cache, settings, **kw)
            trace.write(kind="judge", name=new_entity.get("name"), type=new_entity.get("type"),
                        summary=entity_resolver._effective_summary(new_entity),
                        offered=[entity_resolver._candidate_display_name(c) for c in candidates],
                        candidates=[{"id": c.get("id"), "name": entity_resolver._candidate_display_name(c),
                                     "type": entity_resolver._candidate_type(c), "desc": entity_resolver._candidate_description(c),
                                     "note": c.get("note"), "shared": c.get("shared"), "source": c.get("source")} for c in candidates],
                        verdicts=[[entity_resolver._candidate_display_name(c), d] for c, d in judged])
            return judged

        from unittest.mock import patch
        stack.enter_context(patch.object(entity_extractor, "extract", traced_extract))
        stack.enter_context(patch.object(entity_resolver, "_judge_candidates", traced_judge))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--fixture", type=Path, default=STORIES)
    parser.add_argument("--out", type=Path, required=True, help="a new folder: the scratch bank and home are made in it")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--judge", default="haiku")
    parser.add_argument("--clock", type=date.fromisoformat, default=date(2026, 11, 24))
    parser.add_argument("--trace", action="store_true")
    a = parser.parse_args()
    import contextlib

    from benchmarks.consolidation import run as bench

    fixture = a.fixture if a.fixture.exists() else HERE / a.fixture
    bench.PEOPLE["e2e"] = fixture
    a.out.mkdir(parents=True, exist_ok=True)
    with contextlib.ExitStack() as stack:
        if a.trace:
            Trace(a.out / "trace.jsonl").install(stack)
        snap = bench.run_leg(a.model, a.out, clock=a.clock, engine="plan", judge=a.judge, person="e2e")
    expect = json.loads(fixture.read_text(encoding="utf-8")).get("expect") or {}
    result = check(a.out / "bank", expect)
    result.update(questions=snap.get("questions"), calls=snap["usage"]["calls"])
    (a.out / "reference.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    for r in result["stories"]:
        print(f"{r['id']:11} ok={int(r['ok'])} own_page={int(r['own_page'])} reaches={int(r['reaches'])} direct={int(r['direct'])} split={int(r['split'])} folded={int(r['folded'])} conflated={r['conflated']}"
              f"  pages={r['whole_pages']}")
    print(json.dumps({"ok": result["ok"], "calls": result["calls"]}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
