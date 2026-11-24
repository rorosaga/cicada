"""Is a person or thing said once found by the words that were said? (2026-11-24, `findability_stories.json`)

The owner, 2026-11-24, about holding back a question on someone known only by a description: "if i ask claude about 'the
Portuguese guitar teacher' it should be able to find the mention easily, as claude code memory does, even if it was
mentioned once." Holding something back from a page or a question must never make it invisible to an agent. This measures
that, before anyone changes anything.

One bank, built by real Sleeps on the plan: the fixture's `conversations` are read by Sleep (Sonnet main, Haiku judge, the
product's own search model), its `unread` are staged after it (a conversation Sleep has not read), its `quiet` saves are
added as links with no conversation. Each story is then asked over the real MCP stdio server (`cicada_ask`,
`cicada_recall`) three ways: the person's own words, a rewording and a partial. A hit is a reply holding any one of the
words the story's fact is written with (`expect`); what state the mention was in after Sleep is read from the bank, never
assumed.

    api/.venv/bin/python -m benchmarks.consolidation.findability build --out ~/cicada-bench/fable/askname/bank1
    api/.venv/bin/python -m benchmarks.consolidation.findability ask --out ~/cicada-bench/fable/askname/bank1 --tag before
    api/.venv/bin/python -m benchmarks.consolidation.findability table --out ~/cicada-bench/fable/askname/bank1 --tag before

`--tools recall` asks only the tool that spends no model call. `ask --only p1,p2` limits the stories.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).parent
FIXTURE = HERE / "findability_stories.json"
WORKTREE = HERE.parent.parent
WORDINGS = ("own", "reworded", "partial")
TOOLS = ("cicada_recall", "cicada_ask")
SKILL = WORKTREE / ".claude/skills/verify-cicada"


def _fold(text) -> str:
    return " ".join(str(text or "").lower().split())


def _release_cache() -> Path:
    tmp = Path(os.environ.get("TMPDIR") or "/tmp")
    for cand in (tmp / "cicada-verify/_cache/release", Path.home() / "Library/Caches/cicada-release"):
        if any(cand.glob("model-multilingual-e5-small-*-model.onnx")):
            return cand
    raise SystemExit("no cached search model: run scripts/fetch-embedding-model.sh once")


def _fetch_model(home: Path) -> None:
    env = {**os.environ, "CICADA_RELEASE_CACHE": str(_release_cache())}
    subprocess.run([str(WORKTREE / "scripts/fetch-embedding-model.sh"), str(home / "models")], check=True, env=env,
                   capture_output=True)


def _settings(bank: Path, model: str, judge: str):
    from api.config import Settings

    return Settings(llm_mode="agent", agent_model=model, agent_disambiguation_model=judge, _env_file=None,
                    CICADA_MEMORY_PATH=str(bank), sleep_max_episodes_per_cycle=25, link_enrich_enabled=False)


def build(out: Path, fixture: Path, clock: date, model: str, judge: str) -> dict:
    """The bank: Sleep over the read conversations, then the unread ones and the quiet saves."""
    import asyncio

    from benchmarks.consolidation import run as bench
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths

    _refuse_real_paths(out)
    bank, home = out / "bank", out / "home"
    home.mkdir(parents=True, exist_ok=True)
    _fetch_model(home)
    data = json.loads(fixture.read_text(encoding="utf-8"))
    with _leg_environment(home, bank):
        from api.services import sleep_cycle

        bench.init_bank(bank, data["owner"])
        settings = _settings(bank, model, judge)
        bench.stage(bank, data["conversations"], clock, "Bench intake")
        asyncio.run(sleep_cycle.run(settings, "sleep_findability", user_triggered=True, drain=True))
        state = sleep_cycle.get_sleep_state()
        phases = {"error": state.error, "stop": state.drain.stop.reason if state.drain and state.drain.stop else None}
        if data.get("unread"):
            bench.stage(bank, [{**c, "phase": 2} for c in data["unread"]], clock, "Bench intake, unread")
        if data.get("quiet"):
            from api.services import media_ingestor

            items = [media_ingestor.RawItem(url=q["url"], title=q["title"]) for q in data["quiet"]]
            created, _dup = asyncio.run(media_ingestor.ingest_batch(items, bank, from_bookmark_file=True))
            phases["quiet_created"] = created
    (out / "build.json").write_text(json.dumps(phases, indent=1))
    return phases


def _pages(bank: Path) -> list[dict]:
    from api.services import claims as claims_module, markdown_parser

    rows = []
    for path in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter or {}
        text = " ".join([str(fm.get("name") or ""), *map(str, fm.get("aliases") or []),
                         claims_module.strip_claims_block(parsed.body),
                         *(c.text or "" for c in claims_module.parse_claims(parsed.body))])
        head = _fold(" ".join([str(fm.get("name") or ""), *map(str, fm.get("aliases") or [])]))
        rows.append({"id": path.stem, "name": fm.get("name"), "type": fm.get("type"), "text": _fold(text), "head": head,
                     "unnamed": bool(fm.get("unnamed")), "fm": fm})
    return rows


def state_of(bank: Path, story: dict, pages: list[dict] | None = None) -> dict:
    """Where the mention sits after Sleep, read from the bank by the story's ``marks`` (what Stage 1 may have called it, in
    any language): a page, a line held with no page, a quiet save, an episode Sleep has not read, or only a conversation
    Sleep read and kept nothing from. The owner's own page never counts as the mention's page."""
    marks = [_fold(m) for m in story.get("marks") or []]
    pages = pages if pages is not None else _pages(bank)
    on_pages = [p["id"] for p in pages if not p["fm"].get("owner") and any(m in p["head"] for m in marks)]
    held = []
    store = bank / "pending_entities.jsonl"
    if store.exists():
        for raw in store.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not raw.strip():
                continue
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            head = _fold(" ".join([str(line.get("name") or ""), str(line.get("summary") or line.get("description") or ""),
                                   *map(str, line.get("aliases") or [])]))
            if any(m in head for m in marks):
                held.append(str(line.get("name")))
    unread, read = [], []
    from api.services import markdown_parser

    words = [w for group in story["expect"] for w in group] + marks
    for path in sorted((bank / "episodes").glob("*.md")):
        parsed = markdown_parser.parse(path)
        if any(w in _fold(parsed.body) for w in words):
            (read if (parsed.frontmatter or {}).get("processed") else unread).append(path.stem)
    quiet = False
    try:
        from api.services import quiet_pages

        quiet = bool(on_pages) and all(quiet_pages.page_is_quiet(bank, pid) for pid in on_pages)
    except Exception:  # noqa: BLE001
        quiet = False
    if on_pages and quiet:
        label = "quiet page"
    elif on_pages:
        label = "page"
    elif held:
        label = "held line"
    elif unread:
        label = "unread"
    elif read:
        label = "conversation only"
    else:
        label = "nowhere"
    return {"state": label, "pages": on_pages, "held": held, "unread": unread, "read": read}


# Decoys and noise for a bigger memory: each line is said in a conversation Sleep has not read, near a story's words
# (another teacher, another van, another place that closes) and never carrying a story's fact.
DECOYS = [
    ("en", "My cousin's piano teacher moved to Lisbon last spring and now teaches online on Mondays, the lessons are about jazz standards."),
    ("en", "The neighbour with the blue scooter lent me a ladder on Saturday, he works at the post office."),
    ("en", "The physiotherapist at the gym on Elm Road has a cancellation list, I put my name down for a knee check."),
    ("en", "There is a tiny sushi place near Harbour station that opens at noon, we sat at the counter."),
    ("en", "I read a handbook on bird migration over the weekend, the chapter on swifts was the best."),
    ("en", "The label maker at the office jams every second day, facilities said they would replace it in March."),
    ("es", "La profesora de inglés de mi sobrino dice que debería leer más, le recomendó cuentos cortos."),
    ("es", "El libro sobre volcanes que me prestó Julia tiene unas fotos preciosas del Teide."),
    ("de", "Der Tischler im Baumarkt hat mir erklärt, wie man Buchenholz richtig ölt."),
    ("de", "Das Café am Bahnhof hat montags geschlossen, wir sind dann zum Bäcker gegangen."),
    ("fr", "Le plombier du bureau a changé le robinet de la cuisine en dix minutes, c'était simple."),
    ("fr", "La boulangerie près de la gare ferme à midi le dimanche, il faut y aller tôt."),
]
_TOPICS = [
    "my bike needs new brake pads", "planning the budget for the garden", "a recipe for lentil soup", "the train to Vienna was late",
    "reading about glaciers", "my sister's birthday gift", "learning to play chess openings", "the quarterly numbers for the warehouse",
    "a podcast about the Roman roads", "the new running shoes", "repainting the hallway", "booking a dentist appointment",
    "the film we saw on Friday", "tuning the piano before the party", "the leak in the shed roof", "a list of movies to watch",
    "my neighbour's dog barks at night", "the guitar I saw in a shop window", "a teacher who inspired me at school",
    "the new bakery on the corner", "ordering labels for the jam jars", "swimming at the lake in summer", "the printer at work is broken",
]


def scale(src: Path, dst: Path, count: int, clock: date) -> dict:
    """``dst`` = a copy of ``src`` plus ``count`` conversations Sleep has not read (noise on many topics, and a decoy near
    each story). A bigger memory is what a person has; a dozen conversations make everything easy to find."""
    import random

    from benchmarks.consolidation import run as bench
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths

    _refuse_real_paths(dst)
    if not dst.exists():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("findability-*.jsonl"))
    rng = random.Random(7)
    convs = []
    for i in range(count):
        a, b = rng.sample(_TOPICS, 2)
        convs.append({"id": f"n{i:03d}", "phase": 3, "day": -rng.randint(1, 80), "title": f"Chat {i}", "lang": "en",
                      "turns": [f"I was thinking about {a} today, and also {b}.", "Tell me more about it.",
                                f"Mostly {b}; I will decide after the weekend."]})
    for j, (lang, line) in enumerate(DECOYS):
        convs.append({"id": f"d{j:02d}", "phase": 3, "day": -rng.randint(1, 80), "title": f"Note {j}", "lang": lang,
                      "turns": [line, "Understood."]})
    with _leg_environment(dst / "home", dst / "bank"):
        made = bench.stage(dst / "bank", convs, clock, "Bench intake, noise")
    return made


def _run(out: Path) -> dict:
    home, bank = out / "home", out / "bank"
    real = shutil.which("claude")
    scratch = out / "mcphome"
    scratch.mkdir(exist_ok=True)
    return {"run_id": "findability", "run_dir": str(out), "python": str(WORKTREE / "api/.venv/bin/python"),
            "worktree": str(WORKTREE),
            "env": {"HOME": str(scratch), "CICADA_HOME": str(home), "CICADA_MEMORY_PATH": str(bank),
                    "PYTHONPATH": str(WORKTREE), "LITELLM_MODE": "PRODUCTION", "CICADA_LLM_MODE": "agent",
                    "CICADA_AGENT_MODEL": "haiku", "CICADA_AGENT_DISAMBIGUATION_MODEL": "haiku",
                    "CICADA_WEB_CHECK_AGENT_MODEL": "haiku", "CICADA_CLAUDE_CLI": str(SKILL / "bin/plan-claude"),
                    "CICADA_VERIFY_REAL_CLAUDE": real or "", "CICADA_VERIFY_MODEL": "haiku",
                    "CICADA_ALLOW_CONNECTOR_FETCH": "off", "CICADA_ALLOW_LOGO_FETCH": "off",
                    "CICADA_ALLOW_FEED_FETCH": "off", "HF_HUB_OFFLINE": "1", "OMP_NUM_THREADS": "4",
                    "TOKENIZERS_PARALLELISM": "false"}}


def ask(out: Path, fixture: Path, tag: str, tools: tuple[str, ...], only: set[str] | None) -> Path:
    from benchmarks.newuser import ask as newuser

    run = _run(out)
    stories = [s for s in json.loads(fixture.read_text(encoding="utf-8"))["stories"] if not only or s["id"] in only]
    path = out / f"findability-{tag}.jsonl"
    done = set()
    if path.exists():
        done = {(r["story"], r["wording"], r["tool"]) for r in map(json.loads, path.read_text().splitlines() if path.read_text() else [])}
    with path.open("a") as fh:
        for s in stories:
            for wording, query in zip(WORDINGS, s["queries"]):
                for tool in tools:
                    if (s["id"], wording, tool) in done:
                        continue
                    args = {"query": query}
                    reply = newuser.call(run, tool, args, timeout=300)
                    text = reply["text"]
                    low = _fold(text)
                    hit = any(any(w in low for w in group) for group in s["expect"]) and not reply["isError"]
                    row = {"story": s["id"], "kind": s["kind"], "wording": wording, "tool": tool, "query": query,
                           "hit": hit, "isError": reply["isError"], "seconds": reply["seconds"], "chars": len(text),
                           "text": text}
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    print(f"{s['id']:3} {wording:9} {tool:13} {'HIT ' if hit else 'MISS'} {len(text):6} chars {reply['seconds']:>6}s")
    return path


def own_episodes(bank: Path, data: dict) -> dict[str, list[str]]:
    """The episode each story was said in: the one whose text holds the story's first line (a distractor never does)."""
    from api.services import markdown_parser

    first = {}
    for c in [*data["conversations"], *data.get("unread", [])]:
        for s in data["stories"]:
            if s["id"] == c["id"]:
                first[s["id"]] = _fold(c["turns"][0])
    found: dict[str, list[str]] = {sid: [] for sid in first}
    for path in sorted((bank / "episodes").glob("*.md")):
        body = _fold(markdown_parser.parse(path).body)
        for sid, line in first.items():
            if line in body:
                found[sid].append(path.stem)
    return found


def _without_owner_page(text: str, owner: str) -> str:
    """The reply with the owner's page block taken out: in a memory of thousands of conversations that page holds a
    handful of its hundreds of facts, so a fact found only there is not a find."""
    out, skip = [], False
    for line in text.split("\n"):
        if line.startswith("### "):
            skip = line.startswith(f"### {owner}")
        elif line.startswith("**Related conversation excerpts") or line.startswith("<<<") or line.startswith("```"):
            skip = False
        if not skip:
            out.append(line)
    return "\n".join(out)


def strict_hit(row: dict, story: dict, eps: list[str], pages: list[str], owner: str) -> bool:
    """A find. An Ask answer holds a word of the story's fact (what an agent reads is the answer). A recall reply names the
    story's own conversation, or holds a fact word outside the owner's page block: in a memory of thousands of
    conversations that page holds a handful of its hundreds of facts, so a fact found only there is not a find."""
    if row["isError"]:
        return False
    if row["tool"] == "cicada_ask":
        return bool(row["hit"])
    if any(e in row["text"] for e in eps):
        return True
    low = _fold(_without_owner_page(row["text"], owner))
    return any(w in low for g in story["expect"] for w in g)


def _page_names_of(pages: list[dict], ids: list[str]) -> list[str]:
    return [x for p in pages if p["id"] in ids for x in (p["id"], str(p["name"]))]


def table(out: Path, fixture: Path, tag: str) -> str:
    data = json.loads(fixture.read_text(encoding="utf-8"))
    bank = out / "bank"
    rows = [json.loads(x) for x in (out / f"findability-{tag}.jsonl").read_text().splitlines() if x.strip()]
    pages = _pages(bank)
    eps = own_episodes(bank, data)
    owner = data["owner"]
    lines = ["story  kind    lang state              | recall own/reword/part | ask own/reword/part   (Y = found; recall not by the owner's page alone)"]
    totals: dict[str, list[int]] = {}
    for s in data["stories"]:
        st = state_of(bank, s, pages)["state"]
        cells = []
        for tool in TOOLS:
            marks = []
            for w in WORDINGS:
                r = next((x for x in rows if x["story"] == s["id"] and x["wording"] == w and x["tool"] == tool), None)
                ok = r is not None and strict_hit(r, s, eps.get(s["id"], []), _page_names_of(pages, state_of(bank, s, pages)["pages"]), owner)
                marks.append("." if r is None else ("Y" if ok else "-"))
                if r is not None:
                    t = totals.setdefault(f"{st}|{tool}|{w}", [0, 0])
                    t[0] += int(ok); t[1] += 1
            cells.append("/".join(marks))
        lines.append(f"{s['id']:5}  {s['kind']:6}  {s['lang']:4} {st:18} | {cells[0]:22} | {cells[1]}")
    lines.append("")
    lines.append("by state (hits/asked):  recall own/reworded/partial  |  ask own/reworded/partial")
    for st in sorted({k.split("|")[0] for k in totals}):
        parts = []
        for tool in TOOLS:
            parts.append("  ".join(f"{totals.get(f'{st}|{tool}|{w}', [0, 0])[0]}/{totals.get(f'{st}|{tool}|{w}', [0, 0])[1]}" for w in WORDINGS))
        lines.append(f"  {st:18} {parts[0]:24} | {parts[1]}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("verb", choices=("build", "ask", "table", "state", "scale"))
    ap.add_argument("--src", type=Path)
    ap.add_argument("--count", type=int, default=150)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fixture", type=Path, default=FIXTURE)
    ap.add_argument("--tag", default="before")
    ap.add_argument("--tools", default="recall,ask")
    ap.add_argument("--only")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--judge", default="haiku")
    ap.add_argument("--clock", type=date.fromisoformat, default=date(2026, 11, 24))
    a = ap.parse_args()
    sys.path.insert(0, str(WORKTREE))
    if a.verb == "build":
        os.environ.pop("ANTHROPIC_API_KEY", None)
        print(json.dumps(build(a.out, a.fixture, a.clock, a.model, a.judge)))
    elif a.verb == "ask":
        os.environ.pop("ANTHROPIC_API_KEY", None)
        tools = tuple(f"cicada_{t}" for t in a.tools.split(","))
        ask(a.out, a.fixture, a.tag, tools, set(a.only.split(",")) if a.only else None)
    elif a.verb == "scale":
        print(json.dumps(scale(a.src, a.out, a.count, a.clock)))
    elif a.verb == "state":
        data = json.loads(a.fixture.read_text(encoding="utf-8"))
        pages = _pages(a.out / "bank")
        for s in data["stories"]:
            print(s["id"], json.dumps(state_of(a.out / "bank", s, pages), ensure_ascii=False))
    else:
        print(table(a.out, a.fixture, a.tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
