"""Offline eval of pages as articles (G194, owner 2026-10-09): what Sleep writes today vs. with the article writer.

Run: python -m benchmarks.system.page_articles --scratch <new-empty-directory>

A synthetic timeline (``fixtures/page_articles.json``: ``alpha-project`` over 15 conversations, the person
``bob-example`` over 5, ``gamma-tool`` once) goes through the production Stage 3 (`conflict_resolver.resolve_and_prune`)
and Stage 5 page writer (`apply_changes`), one conversation per batch, as Stage 2 would hand it over (a create, then
updates, each with its G118 inputs). No model is called:

* **today** — the owner's live setting, summary synthesis on: a fake orientation answer (the incoming summary) and a
  fake contradiction check (none);
* **articles** — ``page_articles_enabled``: a mechanical fake writer that turns the numbered inputs into a lead and
  sections, citing what it used. Its prose is the fake's, not a model's; what is measured is the pipeline — calls,
  prompt and answer sizes, the record kept item for item, provenance per paragraph;
* **rebuild** — `page_article_rebuild` over the *today* bank, answered by recorded articles written for this
  fixture (``recorded_articles``), to show before and after bodies the way the person's rebuild would produce them.

Time is modelled, not measured (no provider is called): each call costs ``BASE_S`` plus its input and output tokens
at ``IN_TOK_S`` / ``OUT_TOK_S`` (chars / 4), and a batch's Stage 3 is its pages' calls spread over ``concurrency``
workers in order, as `_overlap_pages` runs them. The constants are assumptions for a plan engine, stated in the output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import statistics
from pathlib import Path
from types import SimpleNamespace

FIXTURE = Path(__file__).with_name("fixtures") / "page_articles.json"
BASE_S, IN_TOK_S, OUT_TOK_S = 2.0, 5000.0, 70.0   # seconds per call; input and output tokens per second
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _month(day: str) -> str:
    return f"{_MONTHS[int(day[5:7]) - 1]} {day[:4]}"


def _data(prompt: str) -> dict:
    return json.loads(prompt.partition("\nDATA:\n")[2])


def mechanical_article(prompt: str) -> dict:
    """The incremental run's stand-in writer: every input used once, cited, in a fixed shape."""
    data = _data(prompt)
    by_kind: dict[str, list[dict]] = {}
    for item in data["INPUT"]:
        by_kind.setdefault(item["kind"], []).append(item)
    said = by_kind.get("said", []) + [i for i in by_kind.get("earlier", []) if " " in i["text"]][:2]
    days = sorted(d for i in data["INPUT"] for d in i.get("said_on", []) if re.match(r"\d{4}-\d{2}-\d{2}$", d))
    latest = f" As of {_month(days[-1])}." if days else ""
    lead = " ".join(dict.fromkeys(i["text"].rstrip(".") + "." for i in said)) + latest
    sections = []
    facts = by_kind.get("fact", [])
    if facts:
        sections.append({"title": "What it is", "paragraphs": [
            {"text": " ".join(f["text"].rstrip(".") + "." for f in facts[i:i + 4]), "from": [f["id"] for f in
                                                                                            facts[i:i + 4]]}
            for i in range(0, len(facts), 4)]})
    history = by_kind.get("history", [])
    if history:
        sentences = []
        for h in history:
            day, _, event = h["text"].partition(": ")
            sentences.append({"text": f"In {_month(day)}, {event[:1].lower() + event[1:]}" if event else h["text"],
                              "from": [h["id"]]})
        sections.append({"title": "How it developed", "paragraphs": [
            {"text": " ".join(s["text"] for s in sentences[i:i + 3]), "from": [x for s in sentences[i:i + 3]
                                                                             for x in s["from"]]}
            for i in range(0, len(sentences), 3)]})
    return {"summary": {"text": lead, "from": [i["id"] for i in said]}, "sections": sections}


def recorded_article(prompt: str, recorded: dict) -> dict | None:
    """A recorded answer for this page, its ``from`` given as words of the inputs it used; mapped to the ids."""
    data = _data(prompt)
    answer = recorded.get(data["NAME"])
    if answer is None:
        return None

    def ids(needles):
        out = []
        for needle in needles:
            out += [i["id"] for i in data["INPUT"] if needle.lower() in i["text"].lower() and i["id"] not in out]
        return out

    return {"summary": {"text": answer["summary"]["text"], "from": ids(answer["summary"]["from"])},
            "sections": [{"title": s["title"], "paragraphs": [{"text": p["text"], "from": ids(p["from"])}
                                                              for p in s["paragraphs"]]}
                         for s in answer["sections"]]}


class Fake:
    """The completion seam: answers by prompt, records every call with its page, stage and sizes."""

    def __init__(self, recorded: dict | None = None):
        self.calls: list[dict] = []
        self.recorded = recorded or {}

    async def __call__(self, **kwargs):
        text = kwargs["messages"][-1]["content"]
        if "You are writing a page of a personal wiki" in text:
            stage = "article"
            page = _data(text)["NAME"]
            answer = (recorded_article(text, self.recorded) if self.recorded else None) or mechanical_article(text)
            content = json.dumps(answer)
        elif "SECTION-AWARE ORIENTATION" in text:
            stage = "orientation"
            data = json.loads(text.partition("\nINPUT:\n")[2])
            page = data["name"]
            incoming = str(data["incoming"].get("summary") or "")
            old = str(data["existing_sections"].get("Summary") or "")
            content = json.dumps({"summary": incoming or old, "restated": [], "covered": []})
        elif "checking whether two descriptions" in text:
            stage = "contradiction"
            page = re.search(r"ENTITY: (.+)", text).group(1).strip()
            content = json.dumps({"has_unresolvable_contradiction": False})
        else:
            stage, page = "other", "?"
            content = "## Summary\nLegacy prose."
        self.calls.append({"stage": stage, "page": page, "in": len(text), "out": len(content)})
        return SimpleNamespace(model="offline-fake", choices=[SimpleNamespace(message=SimpleNamespace(
            content=content))])


def _latency(call: dict) -> float:
    return BASE_S + call["in"] / 4 / IN_TOK_S + call["out"] / 4 / OUT_TOK_S


def makespan(calls: list[dict], concurrency: int) -> float:
    """Stage 3's modelled wall time: each page's calls in order, pages started in order on ``concurrency`` workers."""
    per_page: dict[str, float] = {}
    for call in calls:
        per_page[call["page"]] = per_page.get(call["page"], 0.0) + _latency(call)
    workers = [0.0] * max(1, concurrency)
    for duration in per_page.values():
        i = workers.index(min(workers))
        workers[i] += duration
    return max(workers) if per_page else 0.0


def _seed(bank: Path, owner: str) -> None:
    from api.services import markdown_parser as md

    (bank / "entities").mkdir(parents=True)
    (bank / "episodes").mkdir()
    md.write(bank / "entities" / f"{_slug(owner)}.md",
             {"name": owner, "type": "person", "owner": True, "status": "active", "source_episodes": []},
             f"## Summary\n{owner} is the person this memory belongs to.")
    md.write(bank / "entities/sqlite.md", {"name": "SQLite", "type": "tool", "status": "active",
                                          "source_episodes": ["ep_2025-01-01_001", "ep_2025-01-02_001"]},
             "## Summary\nSQLite is an embedded database.")


def run_timeline(root: Path, mode: str, data: dict) -> dict:
    from api.config import Settings
    from api.services import conflict_resolver as cr, markdown_parser as md, section_provenance as sp

    bank = root / f"bank-{mode}"
    _seed(bank, data["owner"])
    os.environ["CICADA_MEMORY_PATH"] = str(bank)
    settings = Settings(_env_file=None, llm_mode="local", summary_synthesis_enabled=(mode == "today"),
                        page_articles_enabled=(mode == "articles"), agent_max_concurrency=10)
    fake = Fake()
    original = cr.litellm.acompletion
    cr.litellm.acompletion = fake
    batches, extracted = [], []
    try:
        for conversation in data["conversations"]:
            ep, ts = conversation["id"], conversation["timestamp"]
            text = "\n".join(f"user: {e['summary']} " + " ".join(e["key_facts"]) for e in conversation["entities"])
            md.write(bank / "episodes" / f"{ep}.md", {"id": ep, "timestamp": ts, "processed": True}, text)
            changes = []
            for entity in conversation["entities"]:
                fields = {**entity, "description": entity["summary"], "tags": [], "aliases": [],
                          "links": [], "open_questions": [], "confidence": 0.8}
                sp.attach(fields, ep, text)
                eid = _slug(entity["name"])
                action = "update" if (bank / "entities" / f"{eid}.md").exists() else "create"
                changes.append({"id": eid, "action": action, "entity": fields, "source_episode": ep,
                                "source_episodes": [ep], "source_episode_timestamps": [ts],
                                "source_episode_days": [ts[:10]]})
                extracted += [(eid, "Key Facts", f) for f in entity["key_facts"]]
                extracted += [(eid, "History", f"{h['date']}: {h['event']}") for h in entity["history_entries"]]
            existing = [{"id": p.stem, "frontmatter": (pg := md.parse(p)).frontmatter, "body": pg.body}
                        for p in sorted((bank / "entities").glob("*.md"))]
            before = len(fake.calls)
            from datetime import datetime
            out = asyncio.run(cr.resolve_and_prune(changes, existing, settings, decay=False,
                                                   now=datetime.fromisoformat(ts[:19])))
            cr.apply_changes(out, bank)
            calls = fake.calls[before:]
            stages: dict[str, int] = {}
            for call in calls:
                stages[call["stage"]] = stages.get(call["stage"], 0) + 1
            batches.append({"batch": ep, "calls": stages, "prompt_chars": sum(c["in"] for c in calls),
                            "answer_chars": sum(c["out"] for c in calls),
                            "modelled_s_c1": round(makespan(calls, 1), 1),
                            "modelled_s_c10": round(makespan(calls, 10), 1)})
    finally:
        cr.litellm.acompletion = original
    return {"bank": bank, "batches": batches, "extracted": extracted}


def page_stats(path: Path) -> dict:
    from api.services import claims, entity_body, markdown_parser as md, section_provenance as sp

    parsed = md.parse(path)
    sections = entity_body.parse_sections(claims.strip_claims_block(parsed.body))
    words = lambda t: len(re.findall(r"[\w'@./-]+", t or ""))  # noqa: E731
    article = sections.get("Article", "")
    matched = sp.matched(parsed.frontmatter, parsed.body)
    paragraphs = sp.scan(parsed.body).get("article", [])
    return {
        "conversations": len(parsed.frontmatter.get("source_episodes") or []),
        "summary_words": words(sections.get("Summary")), "article_words": words(article),
        "article_sections": article.count("### "), "article_paragraphs": len(paragraphs),
        "paragraphs_with_sources": len(matched.get("article", {})),
        "lead_has_sources": bool(matched.get("summary")),
        "key_facts": len(entity_body._bullet_lines(sections.get("Key Facts", ""))),
        "history": len(entity_body._bullet_lines(sections.get("History", ""))),
        "prose_words": words(sections.get("Summary")) + words(article),
    }


def lossless(bank: Path, extracted) -> list[str]:
    """Every extracted fact and dated line, on its page's record, exactly."""
    from api.services import claims, entity_body, markdown_parser as md

    lost = []
    for eid, section, item in extracted:
        path = bank / "entities" / f"{eid}.md"
        sections = entity_body.parse_sections(claims.strip_claims_block(md.parse(path).body))
        if item not in entity_body._bullet_lines(sections.get(section, "")):
            if not (section == "Key Facts" and item in sections.get("Summary", "")):
                lost.append(f"{eid} {section}: {item}")
    return lost


def rebuild(root: Path, today_bank: Path, data: dict) -> dict:
    from api.config import Settings
    from api.services import conflict_resolver as cr, page_article_rebuild as rb

    bank = root / "bank-rebuild"
    shutil.copytree(today_bank, bank)
    os.environ["CICADA_MEMORY_PATH"] = str(bank)
    settings = Settings(_env_file=None, llm_mode="local", agent_max_concurrency=10)
    fake = Fake(recorded=data["recorded_articles"])
    original = cr.litellm.acompletion
    cr.litellm.acompletion = fake
    try:
        dry = rb.survey(bank, settings).counts()
        result = rb.run(bank, settings, mode="preview", preview_dir=root / "rebuild-preview",
                        entity_ids=sorted(data["recorded_articles_ids"]))
    finally:
        cr.litellm.acompletion = original
    return {"dry_run": dry, "preview": result.counts(), "calls": fake.calls}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    args = parser.parse_args()
    root = args.scratch.resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ.update(HOME=str(root / "home"), CICADA_HOME=str(root / "config"), LITELLM_MODE="PRODUCTION",
                      CICADA_ALLOW_LOGO_FETCH="off", CICADA_ALLOW_CONNECTOR_FETCH="off")
    (root / "home").mkdir()
    data = json.loads(FIXTURE.read_text())
    data["recorded_articles_ids"] = [_slug(n) for n in data.get("recorded_articles", {})] + ["gamma-tool"]
    report = {"model": {"base_s": BASE_S, "input_tokens_per_s": IN_TOK_S, "output_tokens_per_s": OUT_TOK_S,
                        "tokens": "chars / 4", "note": "assumed plan-engine latency; no provider is called"}}
    runs = {}
    for mode in ("today", "articles"):
        out = run_timeline(root, mode, data)
        runs[mode] = out
        pages = {p.stem: page_stats(p) for p in sorted((out["bank"] / "entities").glob("*.md"))}
        b = out["batches"]
        report[mode] = {
            "calls": sum(sum(x["calls"].values()) for x in b),
            "calls_by_stage": {s: sum(x["calls"].get(s, 0) for x in b) for s in
                               sorted({s for x in b for s in x["calls"]})},
            "prompt_chars": sum(x["prompt_chars"] for x in b), "answer_chars": sum(x["answer_chars"] for x in b),
            "median_prompt_chars_per_batch": statistics.median(x["prompt_chars"] for x in b),
            "modelled_stage3_s_total_c1": round(sum(x["modelled_s_c1"] for x in b), 1),
            "modelled_stage3_s_total_c10": round(sum(x["modelled_s_c10"] for x in b), 1),
            "max_batch_modelled_s_c10": max(x["modelled_s_c10"] for x in b),
            "record_items_lost": lossless(out["bank"], out["extracted"]),
            "pages": pages, "batches": b,
        }
    report["rebuild"] = rebuild(root, runs["today"]["bank"], data)
    (root / "results.json").write_text(json.dumps(report, indent=1, default=str) + "\n")
    for mode in ("today", "articles"):
        r = report[mode]
        print(mode, json.dumps({k: v for k, v in r.items() if k not in ("batches",)}, indent=1))
    print("rebuild", json.dumps({k: v for k, v in report["rebuild"].items() if k != "calls"}, indent=1))


if __name__ == "__main__":
    main()
