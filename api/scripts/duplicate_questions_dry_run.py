"""What today's code would do with each open "Is A the same as B?" question — per item, writing nothing to the bank
(owner 2026-10-29; `entity_relations`, `web_settle.settle_pair`).

    api/.venv/bin/python -m api.scripts.duplicate_questions_dry_run --bank <copy> --out <dir>             # no engine
    api/.venv/bin/python -m api.scripts.duplicate_questions_dry_run --bank <copy> --out <dir> --judge     # + judge
    api/.venv/bin/python -m api.scripts.duplicate_questions_dry_run --bank <copy> --out <dir> --judge --check

For every pending ``merge_suggestion`` it writes ONE row to ``<out>/items.json`` (and a count summary to stdout):
where the question came from (``origin``: the alias lead between two pages, the judge unsure about a held mention —
a project name with no birth or any other — a person's held alias, a placeholder person, or an older question raised
before held mentions were marked), whether a web check may look it up (``web_settle.classify``'s scope and reason),
the relation judge's verdict on the pair today (``--judge``: the Claude plan, the disambiguation model — run it with
``CICADA_AGENT_DISAMBIGUATION_MODEL=haiku``), the check's cited answer (``--check``, public pairs only: each name
searched alone on the plan's own web search) and the ``outcome`` the new code would reach:

* ``lands_as_part`` — a project name with no birth the judge calls a part of the page: it lands there (owner
  2026-10-23), no question;
* ``relation_claim`` — the judge names a relation: a claim on the page, no question;
* ``settle_by_check`` — a public pair the check answers with a cited relation, undoable under "Settled by a check";
* ``not_asked`` — the judge says different, or the record already relates the two;
* ``would_join`` — the judge says same (a fresh run joins the mention; for the backlog the person's tap merges);
* ``keep_asking`` — a person, or the judge still cannot tell.

The rows carry names (for the eyes of the person running it — the output directory must be outside the repo); the
stdout summary is counts only. The bank is read, never written: no settle, no memo, no ledger row (the engine's usage
sink is a no-op), no commit. Exit 0 done, 2 not a bank.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from pathlib import Path


def _origin(fm: dict, body: str) -> str:
    cls = str(fm.get("suggested_classification") or "").lower()
    if not str(fm.get("source_episode") or "").strip():
        return "placeholder_person"
    if "already lists" in body or "links the" in body:
        return "alias_lead_person" if cls.startswith("person") else "alias_lead_thing"
    if fm.get("held_mention"):
        if cls.startswith("person"):
            return "held_person"
        return "unsure_held_project" if cls.startswith("project") else "unsure_held_other"
    if cls.startswith("person"):
        return "held_person"
    return "unsure_before_held_mark"


def _page(memory: Path, eid: str) -> dict | None:
    from api.services import markdown_parser

    path = memory / "entities" / f"{eid}.md"
    if not eid or not path.is_file():
        return None
    parsed = markdown_parser.parse(path)
    return {"id": eid, "frontmatter": parsed.frontmatter, "body": parsed.body}


def _pending_description(lines: dict, name: str) -> str:
    line = lines.get(name.strip().lower())
    return "" if line is None else " ".join(filter(None, [line.summary, line.description, *line.key_facts]))


async def _judge(rows: list[dict], memory: Path, settings, concurrency: int) -> None:
    from api.services import entity_resolver as er
    from api.services import pending_store

    lines = {line.name.strip().lower(): line for line in pending_store.load(memory)}
    gate = asyncio.Semaphore(max(1, concurrency))

    async def one(row: dict) -> None:
        a = _page(memory, row["target_id"])
        if a is None:
            row["judge"] = "no_target_page"
            return
        b = None if row["held"] else _page(memory, row["entity_id"])
        b_type = str(((b or {}).get("frontmatter") or {}).get("type") or row["subject_type"] or "concept").lower()
        b_text = (b or {}).get("body") or _pending_description(lines, row["entity_name"]) or row["context"]
        async with gate:
            try:
                row["judge"] = await er._llm_judge_same_entity(
                    row["entity_name"], b_type, b_text, row["target_name"],
                    str(a["frontmatter"].get("type") or "concept").lower(),
                    er._alias_page_context(a) if row["origin"].startswith("alias_lead") else a["body"], settings,
                    recorded_alias=row["origin"].startswith("alias_lead"), types_may_differ=True)
            except Exception as exc:  # noqa: BLE001 — one failed call is reported, never the run's end
                row["judge"] = f"error:{type(exc).__name__}"

    await asyncio.gather(*(one(r) for r in rows))


async def _check(rows: list[dict], memory: Path, settings) -> None:
    from datetime import date

    from api.services import web_lookup, web_settle

    wanted = {r["id"] for r in rows if r["scope"] == "public"}
    if not wanted:
        return
    facts = web_settle.bank_facts(memory)
    todo, _ = web_lookup.select(memory, facts, {}, date.today(), cap=10_000, include_recent=True)
    todo = [(c, ctx) for c, ctx in todo if c.item_id in wanted]
    resolved, label, why = await web_lookup.engine_for(settings, user_triggered=True)
    if resolved is None:
        for r in rows:
            if r["id"] in wanted:
                r["check"] = {"ok": False, "reason": why}
        return
    report = web_lookup.Report(engine=label)
    fn = web_lookup.default_llm_fn(resolved, sink=lambda *_a, **_k: None)
    by_id = {r["id"]: r for r in rows}
    for c, a in await web_lookup.look_up(fn, todo, report):
        by_id[c.item_id]["check"] = {"ok": a.ok, "reason": a.reason, "relation": a.relation, "url": a.url,
                                     "quote": a.quote, "queries": list(web_settle.queries_for(c))}


def _outcome(row: dict) -> tuple[str, str]:
    from api.services import entity_relations

    verdict = str(row.get("judge") or "")
    relation = entity_relations.relation_of(verdict)
    check = row.get("check") or {}
    if row["known_relation"]:
        return "not_asked", "the record already relates the two"
    if row["origin"] in ("placeholder_person", "alias_lead_person", "held_person") or row["subject_type"] == "person":
        return "keep_asking", "a person: who they are takes the person's own words"
    if relation == "part_of" and row["origin"] == "unsure_held_project":
        return "lands_as_part", entity_relations.phrase(relation, row["entity_name"], row["target_name"])
    if check.get("ok"):
        return "settle_by_check", entity_relations.phrase(check["relation"], row["entity_name"], row["target_name"])
    if relation is not None:
        return "relation_claim", entity_relations.phrase(relation, row["entity_name"], row["target_name"])
    if verdict == "different":
        return "not_asked", "the judge says two different things"
    if verdict == "same":
        return "would_join", "the judge says the same thing"
    return "keep_asking", "the judge still cannot tell" if verdict == "unsure" else (verdict or "not judged")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="duplicate_questions_dry_run", description=__doc__.splitlines()[0])
    parser.add_argument("--bank", required=True, help="a COPY of the bank (holds entities/ and inbox/)")
    parser.add_argument("--out", required=True, help="where items.json goes (outside the repo)")
    parser.add_argument("--judge", action="store_true", help="replay the relation judge on every pair (plan calls)")
    parser.add_argument("--check", action="store_true", help="look up the public pairs (plan web search)")
    parser.add_argument("--concurrency", type=int, default=3)
    args = parser.parse_args(argv)
    memory = Path(args.bank).expanduser().resolve()
    if not (memory / "entities").is_dir() or not (memory / "inbox").is_dir():
        print(json.dumps({"error": "not a bank: no entities/ or inbox/ directory"}))
        return 2
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    from api.config import Settings
    from api.services import entity_relations, inbox_service, markdown_parser, web_settle

    settings = Settings(memory_path=memory, llm_mode="agent", agent_model="haiku",
                        agent_disambiguation_model="haiku", web_check_agent_model="haiku")
    facts = web_settle.bank_facts(memory)
    visible = {i.id for i in inbox_service.load_inbox(memory)}
    rows: list[dict] = []
    for path in sorted((memory / "inbox").glob("inbox-*.md")):
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter
        if fm.get("kind") != "merge_suggestion" or fm.get("status") != "pending":
            continue
        target = str(fm.get("merge_target_hint") or "")
        target_fm = facts.pages.get(target) or {}
        scope, why = web_settle.classify(memory, fm, parsed.body, facts)
        page = facts.pages.get(str(fm.get("entity_id") or ""))
        rows.append({
            "id": path.stem, "created": str(fm.get("created_date") or ""), "visible": path.stem in visible,
            "said": str(fm.get("source_episode_timestamp") or "")[:10], "episode": str(fm.get("source_episode") or ""),
            "entity_id": str(fm.get("entity_id") or ""), "entity_name": str(fm.get("entity_name") or ""),
            "target_id": target, "target_name": str(target_fm.get("name") or target),
            "held": bool(fm.get("held_mention")),
            "subject_type": str((page or {}).get("type") if page is not None and not fm.get("held_mention") else
                                str(fm.get("suggested_classification") or "").split(" ")[0]).lower(),
            "target_type": str(target_fm.get("type") or "").lower(),
            "origin": _origin(fm, parsed.body), "scope": scope or "", "scope_reason": why,
            "known_relation": entity_relations.known(memory, str(fm.get("entity_id") or ""), target),
            "context": parsed.body.strip()[:600],
        })
    if args.judge:
        asyncio.run(_judge(rows, memory, settings, args.concurrency))
    if args.check:
        asyncio.run(_check(rows, memory, settings))
    for row in rows:
        row["outcome"], row["why"] = _outcome(row)
        row.pop("context", None)
    (out_dir / "items.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    summary = {
        "pending": len(rows),
        "by_origin": dict(collections.Counter(r["origin"] for r in rows)),
        "by_created": dict(sorted(collections.Counter(r["created"] for r in rows).items())),
        "by_scope": dict(collections.Counter(r["scope_reason"] for r in rows)),
        "by_judge": dict(collections.Counter(str(r.get("judge") or "") for r in rows)),
        "by_outcome": dict(collections.Counter(r["outcome"] for r in rows)),
        "by_origin_outcome": {o: dict(collections.Counter(r["outcome"] for r in rows if r["origin"] == o))
                              for o in sorted({r["origin"] for r in rows})},
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
