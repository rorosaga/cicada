"""Stage 1 names things nobody named: how often, in which source, and what Sleep does with each. (2026-11-25, G148/G98)

`coined_label_stories.json` holds invented conversations of the kinds a real memory holds (an exported chat, a harness session
where an agent lists what it did, a note an agent saved, an agent's memory file, a ticked chat with a person), in several
languages, about named projects whose parts and features the person speaks of without naming them. Three steps, each its own
mode, on a scratch bank and home, the Claude plan with haiku (`--engine plan`; no key is read):

    # 1. the birth: Stage 1 alone, repeated; for each entity, is its name (or an alias) in the conversation, and whose turn?
    api/.venv/bin/python -m benchmarks.consolidation.coined_labels birth --out OUT --repeats 3
    # 2. the fate: one real Sleep over the same conversations; where did each coined entity end up?
    api/.venv/bin/python -m benchmarks.consolidation.coined_labels fate --out OUT
    # 3. a table from either, no model
    api/.venv/bin/python -m benchmarks.consolidation.coined_labels table --out OUT

`--fixture` takes another file of the same shape (the held-out one is `coined_label_heldout.json`). Every entity Stage 1 returned is
sorted by `coined_names.said_in`: ``person`` (in a turn of the person's own), ``others`` (only in an assistant's turn, an agent's
note, a record's own text) or ``nowhere`` (in no text of the conversation: the label this measures).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
FIXTURE = HERE / "coined_label_stories.json"
KINDS = ("chat", "session", "agent_note", "memory_note", "messages")


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def drafts(stories: list[dict], clock: date):
    """One staged conversation per story, in the form the real door writes it."""
    from api.services import episode_staging as es

    out = []
    for n, s in enumerate(stories):
        day = (clock - timedelta(days=len(stories) - n)).isoformat()
        ts = f"{day}T10:00:00+00:00"
        sid = f"ses_coined_{s['id']}"
        kind = s["kind"]
        common = dict(title=s["title"], source_id=f"coined:{s['id']}", timestamp=ts, original_date=day)
        if kind == "chat":
            turns = [es.Turn(text=t, speaker="user" if i % 2 == 0 else "assistant", ts=f"{day}T10:{i:02d}:00+00:00")
                     for i, t in enumerate(s["turns"])]
            out.append(es.EpisodeDraft(source="import", origin="chatgpt", turns=turns, extra={"session_id": sid}, **common))
        elif kind == "session":
            turns = [es.Turn(text=t, speaker="user" if i % 2 == 0 else "assistant", ts=f"{day}T10:{i:02d}:00+00:00")
                     for i, t in enumerate(s["turns"])]
            out.append(es.EpisodeDraft(source="claude-code", origin="claude-code", turns=turns,
                                       extra={"session_id": sid, "harness": "claude-code", "capture_kind": "transcript"}, **common))
        elif kind == "agent_note":
            out.append(es.EpisodeDraft(source="mcp", origin="mcp", body=s["body"],
                                       extra={"session_id": sid, "harness": "claude-code"}, **common))
        elif kind == "memory_note":
            out.append(es.EpisodeDraft(source="agent-memory", origin="claude-code", turns=[es.Turn(text=s["body"], speaker="assistant", ts=ts)],
                                       extra={"evidence_kind": "assistant", "harness": "claude-code", "origin_session_id": sid,
                                              "agent_memory": {"project": "alpha", "file": f"{s['id']}.md", "type": "project"}}, **common))
        elif kind == "messages":
            turns = [es.Turn(text=t, speaker="speaker" if i % 2 == 0 else "user", ts=f"{day}T10:{i:02d}:00+00:00")
                     for i, t in enumerate(s["turns"])]
            out.append(es.EpisodeDraft(source="imessage", origin="imessage", turns=turns,
                                       extra={"correspondent": {"name": s.get("other") or "Friend", "kind": "person"}}, **common))
        else:
            raise SystemExit(f"{s['id']}: unknown kind {kind!r}")
    return out


def build_bank(bank: Path, home: Path, fixture: dict, clock: date) -> dict[str, str]:
    """A scratch bank holding the fixture's conversations; returns story id -> episode id."""
    from api.services import episode_staging, git_service, markdown_parser
    from benchmarks.consolidation import run as bench

    bench.init_bank(bank, fixture["owner"])
    result = episode_staging.stage(drafts(fixture["stories"], clock), bank / "episodes")
    git_service.commit_paths_sync(bank, git_service.build_commit_message("Coined labels intake", [], authors=["user"]), result.paths)
    ids: dict[str, str] = {}
    for path in sorted((bank / "episodes").glob("*.md")):
        fm = markdown_parser.parse(path).frontmatter or {}
        sid = str(fm.get("source_id") or "")
        if sid.startswith("coined:"):
            ids[sid.split(":", 1)[1]] = str(fm.get("id") or path.stem)
    return ids


def given(episode: dict, owner: str) -> str:
    """What the model was handed besides the conversation (`entity_extractor`: the owner's name and the source note): the
    owner, the other side of a message conversation, the harness a session ran in. A name from these is not coined."""
    from api.services.episode_title import PRODUCT

    harness = str(episode.get("harness") or "").strip().lower()
    other = (episode.get("correspondent") or {}).get("name") if isinstance(episode.get("correspondent"), dict) else ""
    return " ".join([owner or "", str(other or ""), PRODUCT.get(harness, harness), str(episode.get("title") or "")])


def classify(entity: dict, episode: dict, owner: str = "") -> dict:
    """Where an entity's name (and aliases) is in the conversation it came from, by whose turn."""
    from api.services import authorship, coined_names, promotion

    names = [entity.get("name"), *[a for a in entity.get("aliases") or [] if isinstance(a, str)]]
    text = episode["content"]
    where = coined_names.said_in(names, text, override=authorship.of_episode(episode), gaps=tuple(episode.get("gaps") or ()),
                                 persons=promotion.person_kinds(episode), extra=given(episode, owner))
    name = str(entity.get("name") or "")
    return {"name": name, "type": entity.get("type"), "aliases": [a for a in entity.get("aliases") or [] if isinstance(a, str)],
            "where": where, "words": coined_names.words_of(name, text),
            "facts": len([f for f in entity.get("key_facts") or [] if isinstance(f, str)])}


def resting_on(entity: dict, result: dict, text: str = "") -> dict:
    """What hangs on an entity in a Stage 1 result: the claims (relationships and values) it is the subject of, whether it
    asks the person a question, and how many of its claims name another entity of the same conversation in their cited words."""
    name = _fold(entity.get("name"))
    others = [e for e in result.get("entities") or [] if e is not entity and e.get("type") != "person" and _fold(e.get("name"))]
    mine = [r for r in result.get("relationships") or [] if _fold(r.get("source")) == name]
    vals = [v for v in result.get("values") or [] if _fold(v.get("entity")) == name]
    from api.services import coined_names

    def names_other(claim: dict) -> bool:
        quote = " ".join(text[int(e["start"]):int(e["end"])] for e in claim.get("evidence") or []
                         if isinstance(e, dict) and int(e.get("start", -1)) >= 0)
        return any(coined_names.located(quote, str(o.get("name"))) for o in others)
    return {"rels": len(mine), "values": len(vals), "ask": bool(entity.get("ask_person")),
            "claims_naming_another": sum(1 for c in mine + vals if names_other(c))}


def run_birth(args) -> int:
    from api.services import sleep_cycle, entity_extractor
    from benchmarks.consolidation import engines
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths

    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    stories = {s["id"]: s for s in fixture["stories"]}
    out: Path = args.out
    _refuse_real_paths(out)
    bank, home = out / "bank", out / "home"
    home.mkdir(parents=True, exist_ok=True)
    engines.arm("plan")
    rows = []
    with _leg_environment(home, bank), engines.tally() as counts:
        ids = build_bank(bank, home, fixture, args.clock)
        by_episode = {v: k for k, v in ids.items()}
        settings = engines.settings("plan", bank, model=args.model, judge=args.model)
        episodes = sleep_cycle._get_unprocessed_episodes(bank)
        for rep in range(args.repeats):
            got = asyncio.run(entity_extractor.extract(episodes, settings, today=args.clock))
            by_id = {e["id"]: e for e in episodes}
            for result in got:
                ep = by_id[result["episode_id"]]
                story = stories[by_episode[result["episode_id"]]]
                for entity in result.get("entities") or []:
                    row = classify(entity, ep, fixture["owner"])
                    row.update(story=story["id"], kind=story["kind"], lang=story["lang"], repeat=rep, model=args.model,
                               **resting_on(entity, result, ep["content"]))
                    rows.append(row)
            print(f"repeat {rep + 1}/{args.repeats}: {len(got)} conversations read, {len(rows)} entities so far", flush=True)
        report = counts.as_dict()
    (out / "birth.json").write_text(json.dumps({"model": args.model, "repeats": args.repeats, "rows": rows,
                                                "calls": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(table_birth(rows))
    print(f"model calls: {sum(report['calls'].values())} ({report['calls']}), unusable {report['unusable']}")
    return 0


def _pct(n: int, d: int) -> str:
    return f"{n:>3}/{d:<3} ({(100 * n / d if d else 0):4.0f}%)"


def table_birth(rows: list[dict]) -> str:
    lines = []
    repeats = max([r["repeat"] for r in rows] + [0]) + 1
    lines.append(f"entities {len(rows)} over {repeats} repeat(s); each cell: entities whose name and aliases are said ...")
    lines.append(f"{'':14}{'total':>8}   person-turn            others-only            nowhere")
    for key in ("kind", "lang", "type"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[str(r[key])].append(r)
        lines.append(f"-- by {key}")
        for g, rs in sorted(groups.items()):
            c = Counter(r["where"] for r in rs)
            lines.append(f"{g:14}{len(rs):>8}   {_pct(c['person'], len(rs))}   {_pct(c['others'], len(rs))}   {_pct(c['nowhere'], len(rs))}")
    c = Counter(r["where"] for r in rows)
    lines.append(f"{'ALL':14}{len(rows):>8}   {_pct(c['person'], len(rows))}   {_pct(c['others'], len(rows))}   {_pct(c['nowhere'], len(rows))}")
    nowhere = [r for r in rows if r["where"] == "nowhere"]
    lines.append(f"-- the {len(nowhere)} named nowhere: how many of the name's words the conversation says")
    w = Counter(r["words"] for r in nowhere)
    lines.append("   " + ", ".join(f"{k}: {w[k]}" for k in ("all", "some", "none")))
    notp = [r for r in rows if r["type"] != "person"]
    lines.append(f"-- of the {len(notp)} entities that are not persons, {len([r for r in nowhere if r['type'] != 'person'])} are named nowhere; of those:")
    cn = [r for r in nowhere if r["type"] != "person"]
    lines.append(f"   asking the person a question: {sum(1 for r in cn if r.get('ask'))}; with relationships: {sum(1 for r in cn if r.get('rels'))}; "
                 f"with values: {sum(1 for r in cn if r.get('values'))}; with a claim whose cited words name another entity: "
                 f"{sum(1 for r in cn if r.get('claims_naming_another'))}; key facts: {sum(r.get('facts', 0) for r in cn)}")
    seen = Counter()
    lines.append("-- the distinct names said nowhere (story, kind, type, words, repeats it appeared in)")
    agg: dict[tuple, set] = defaultdict(set)
    for r in nowhere:
        agg[(r["story"], r["kind"], r["type"], r["name"], r["words"])].add(r["repeat"])
    for (story, kind, typ, name, words), reps in sorted(agg.items()):
        lines.append(f"   {story:3} {kind:11} {str(typ):9} words={words:4} x{len(reps)}  {name}")
    return "\n".join(lines)


# ---- the fate of each coined entity in a real Sleep -----------------------------------------------------------------------

def run_fate(args) -> int:
    import contextlib
    from unittest.mock import patch

    from api.services import entity_extractor, entity_resolver, markdown_parser, providers, sleep_cycle
    from benchmarks.consolidation import engines
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths
    from benchmarks.system.engine import embed

    fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    stories = {s["id"]: s for s in fixture["stories"]}
    out: Path = args.out
    _refuse_real_paths(out)
    bank, home = out / "bank", out / "home"
    home.mkdir(parents=True, exist_ok=True)
    engines.arm("plan")
    stage1: list[dict] = []
    with _leg_environment(home, bank), engines.tally() as counts:
        ids = build_bank(bank, home, fixture, args.clock)
        by_episode = {v: k for k, v in ids.items()}
        settings = engines.settings("plan", bank, model=args.model, judge=args.judge)
        episodes = {e["id"]: e for e in sleep_cycle._get_unprocessed_episodes(bank)}
        real_extract = entity_extractor.extract

        async def traced(eps, settings_, **kw):
            got = await real_extract(eps, settings_, **kw)
            for r in got:
                ep = episodes.get(r["episode_id"])
                for entity in r.get("entities") or []:
                    row = classify(entity, ep, fixture["owner"]) if ep else {"name": entity.get("name"), "where": "?", "words": "?"}
                    row.update(story=by_episode.get(r["episode_id"]), kind=stories[by_episode[r["episode_id"]]]["kind"],
                               episode=r["episode_id"], summary=str(entity.get("summary") or "")[:160])
                    stage1.append(row)
            return got

        fake_embed = lambda *a, **k: (embed, "fake-hash-v1")  # noqa: E731 — the search model is not what is compared
        with patch.object(entity_extractor, "extract", traced), patch.object(providers, "resolve_embed_fn", fake_embed), \
                patch.object(providers, "resolve_embed_fn_for_model", fake_embed), patch.object(providers, "cached_embed_fn_for_model", fake_embed):
            asyncio.run(sleep_cycle.run(settings, "sleep_coined", user_triggered=True, drain=True))
        state = sleep_cycle.get_sleep_state()
        report = counts.as_dict()
        snapshot = read_bank(bank)
    snapshot.update(stage1=stage1, error=state.error, calls=report, fixture=str(args.fixture))
    (out / "fate.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(table_fate(snapshot, stories))
    print(f"model calls: {sum(report['calls'].values())} ({report['calls']}), unusable {report['unusable']}")
    return 0


def read_bank(bank: Path) -> dict:
    """What a Sleep left: pages (name, aliases, type, words), held lines (name, claims), open questions (name, target)."""
    from api.services import claims as claims_module, markdown_parser, pending_store

    pages = []
    for path in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter or {}
        found = claims_module.parse_claims(parsed.body)
        pages.append({"id": path.stem, "name": str(fm.get("name") or path.stem), "type": fm.get("type"),
                      "owner": bool(fm.get("owner")), "aliases": [str(a) for a in fm.get("aliases") or []],
                      "text": claims_module.strip_claims_block(parsed.body) + "\n" + "\n".join(str(c.text or "") for c in found)})
    held = [{"name": line.name, "type": line.type, "episodes": line.episodes(), "text": " ".join([line.summary, *line.key_facts,
             *[str(c.get("text") or "") for c in line.held_claims]]), "claims": len(line.held_claims), "against": line.held_against}
            for line in pending_store.load(bank)]
    questions = []
    for path in sorted((bank / "inbox").rglob("*.md")):
        fm = markdown_parser.parse(path).frontmatter or {}
        questions.append({"kind": fm.get("kind"), "name": fm.get("entity_name") or fm.get("entity_mention") or fm.get("entity"),
                          "target": fm.get("merge_target_hint"), "status": fm.get("status")})
    return {"pages": pages, "held": held, "questions": questions}


def fate_of(row: dict, snap: dict) -> str:
    """Where one Stage 1 entity ended: ``page`` (its own), ``landed`` (an alias of another page), ``held`` (a pending line,
    asked or not) or ``lost`` (no trace of the name)."""
    key = _fold(row["name"])
    for p in snap["pages"]:
        if _fold(p["name"]) == key:
            return "page"
    for p in snap["pages"]:
        if key in {_fold(a) for a in p["aliases"]}:
            return "landed"
    held = [h for h in snap["held"] if _fold(h["name"]) == key]
    asked = [q for q in snap["questions"] if _fold(q["name"]) == key]
    if held:
        return "held+asked" if asked else "held"
    return "asked-only" if asked else "lost"


def table_fate(snap: dict, stories: dict) -> str:
    rows = snap["stage1"]
    lines = [f"{len(rows)} entities from Stage 1 in one Sleep; pages {len(snap['pages'])}, held lines {len(snap['held'])}, "
             f"open questions {len(snap['questions'])}"]
    by = defaultdict(Counter)
    for r in rows:
        by[r["where"]][fate_of(r, snap)] += 1
    for where in ("person", "others", "nowhere"):
        lines.append(f"  said {where:8} " + ", ".join(f"{k} {v}" for k, v in sorted(by[where].items())) + f"   (total {sum(by[where].values())})")
    lines.append("-- the entities said nowhere and where each ended")
    for r in rows:
        if r["where"] == "nowhere":
            lines.append(f"   {r['story']:3} {r['kind']:11} {str(r['type']):9} -> {fate_of(r, snap):10} {r['name']}")
    lines.append("-- facts of the stories still held somewhere (a page, a claim, a held line)")
    blob = "\n".join([p["text"] for p in snap["pages"]] + [h["text"] for h in snap["held"]])
    kept = lost = 0
    for sid, s in stories.items():
        for rx in s.get("facts") or []:
            if re.search(rx, blob, re.I):
                kept += 1
            else:
                lost += 1
                lines.append(f"   not found: {sid} /{rx}/")
    lines.append(f"   facts found {kept} of {kept + lost}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("mode", choices=("birth", "fate", "table"))
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--out", type=Path, required=True, help="a new folder: the scratch bank and home are made in it")
    parser.add_argument("--model", default="haiku", help="Stage 1's model, by the plan's tier name")
    parser.add_argument("--judge", default="haiku")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--clock", type=date.fromisoformat, default=date(2026, 11, 24))
    args = parser.parse_args()
    if args.mode == "birth":
        return run_birth(args)
    if args.mode == "fate":
        return run_fate(args)
    stories = {s["id"]: s for s in json.loads(Path(args.fixture).read_text(encoding="utf-8"))["stories"]}
    if (args.out / "fate.json").exists():
        print(table_fate(json.loads((args.out / "fate.json").read_text()), stories))
    if (args.out / "birth.json").exists():
        print(table_birth(json.loads((args.out / "birth.json").read_text())["rows"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
