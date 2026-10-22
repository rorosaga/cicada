"""Does reading a conversation right after it lands make recall answer better before Sleep? (G207, ruling 36 D2)

    api/.venv/bin/python -m benchmarks.awake_bench --work <empty scratch dir> [--repeats 3] [--out results.jsonl]

A synthetic bank, built fresh in ``--work``: consolidated pages (with claims) and their already-read conversations,
plus six new conversations Sleep has not read. Every question is answerable only from a new conversation, or asks
about something a new conversation changed. One control question is answerable from the pages alone. Every name is a
placeholder. Three conditions, each answered from ``cicada_recall``'s real reply (the stdio server's own path, under
the ``sources`` scope):

- **(a) today**: recall's excerpt leg is the vector leg alone, and the new conversations have no vectors;
- **(b) step 0**: the new conversations embedded right after capture (``awake_read.index_now``), plus the word leg;
- **(c) step 0 + 1**: (b), plus each new conversation's quick read (``awake_read.quick_read``) on the Claude plan.

Answer and judge both use haiku on the Claude plan, through Cicada's own plan engine. The judge is
``answer_eval``'s, against the expected and forbidden facts. Each repeat redoes the quick reads, so their variance
counts too. Reported per condition: mean correct across repeats with the min–max, and the quick read's model calls,
tokens and seconds per conversation (from Cicada's own usage events).

Needs: ``CICADA_CAPTURE=off``, a signed-in ``claude`` (the plan), and the pinned search model in
``<work>/home/.cicada/models`` (``scripts/fetch-embedding-model.sh <work>/home/.cicada/models``). It never touches a
real bank: ``HOME`` and ``CICADA_HOME`` are pointed into ``--work`` before Cicada is imported.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLAN_CLAUDE = REPO / ".claude" / "skills" / "verify-cicada" / "bin" / "plan-claude"
OLD_DAY, NEW_DAY = "2026-10-15", "2026-10-21"

# --------------------------------------------------------------------------------------------------------------------
# The synthetic bank (placeholders only)
# --------------------------------------------------------------------------------------------------------------------

PAGES = {
    "verify-person": ("Verify Person", "person", "The person this memory belongs to.", [], True),
    "alpha-project": ("Alpha Project", "project",
                      "A web app for booking rooms. The deadline is November 14. It stores data in Postgres.",
                      [("has-deadline", "November 14"), ("uses-database", "Postgres")], False),
    "bob-example": ("Bob Example", "person",
                    "A friend from university. Lives in Lisbon and works at Example Corp as an engineer.",
                    [("lives-in", "Lisbon"), ("works-at", "Example Corp")], False),
    "harbor-garden": ("Harbor Garden", "project",
                      "A community garden plan by the harbor. Planning meetings are held at the public library.",
                      [("meets-at", "the public library")], False),
    "violin-lessons": ("Violin Lessons", "activity",
                       "Weekly violin lessons on Tuesdays with the teacher Carol Example.",
                       [("lesson-day", "Tuesday"), ("teacher", "Carol Example")], False),
}

OLD_CONVERSATIONS = {
    f"ep_{OLD_DAY}_001": "user: The Alpha Project deadline is November 14 and we're on Postgres.\n\n"
                         "assistant: Noted: November 14, Postgres.",
    f"ep_{OLD_DAY}_002": "user: Bob Example still lives in Lisbon, he works at Example Corp.\n\n"
                         "assistant: Got it.",
    f"ep_{OLD_DAY}_003": "user: Violin lessons with Carol Example are on Tuesdays.\n\nassistant: Okay.",
}

NEW_CONVERSATIONS = {
    f"ep_{NEW_DAY}_001": (
        "user: Bad news on Alpha Project: the deadline moved from November 14 to December 5, because we have to "
        "rewrite the whole authentication flow first.\n\nassistant: That's three more weeks. Is anything else "
        "changing?\n\nuser: Yes, we're dropping Postgres and moving Alpha Project to SQLite, it's simpler to host."
        "\n\nassistant: Understood: December 5, the auth rewrite first, and SQLite instead of Postgres."),
    f"ep_{NEW_DAY}_002": (
        "user: I talked to Bob Example yesterday. He moved from Lisbon to Porto last month and he started a new job "
        "at Northwind Example, he left Example Corp.\n\nassistant: A big change for him: Porto, and Northwind "
        "Example now."),
    f"ep_{NEW_DAY}_003": (
        "user: Harbor Garden update: the next planning meeting is at the community center, not the library anymore."
        " And the council approved a budget of 1,200 euros for seeds and tools.\n\nassistant: Great news. "
        "Community center, and 1,200 euros approved."),
    f"ep_{NEW_DAY}_004": (
        "user: I switched my Violin Lessons to Thursdays. Carol Example has me preparing a Bach partita for a "
        "recital on January 18.\n\nassistant: Thursdays now, and the Bach partita for the January 18 recital."),
    f"ep_{NEW_DAY}_005": (
        "user: A new person joined Alpha Project: Dana Example. She handles all the design work, the screens and "
        "the logo.\n\nassistant: So Dana Example is Alpha Project's designer."),
    f"ep_{NEW_DAY}_006": (
        "user: Big personal news: I adopted a cat this weekend! Her name is Pixel and she's a grey tabby.\n\n"
        "assistant: Congratulations! Pixel the grey tabby."),
}

#: ``--distractors N``: a day of other captures Sleep hasn't read either. They name the same pages and share the
#: questions' words, but state none of the facts asked about. Recall's three excerpt slots compete with them, as on a
#: real day.
DISTRACTOR_LINES = [
    "I spent the afternoon on Alpha Project's room list screen, mostly spacing and colours.",
    "Bob Example recommended a novel about lighthouses; I added it to my reading list.",
    "Harbor Garden needs volunteers for watering on weekends, I put up a note.",
    "Practised scales for the violin for twenty minutes, my bow arm is getting better.",
    "The deadline for my tax form is coming up, I need to find last year's receipts.",
    "Had a meeting with the dentist, nothing serious, a cleaning in spring.",
    "Alpha Project's login page has a typo in the footer, I should fix it.",
    "Bob Example and I watched a football match, his team lost again.",
    "Thinking about planting tomatoes and basil in Harbor Garden next year.",
    "Which database tutorial is good for beginners? A friend asked me.",
    "My neighbour's cat keeps visiting the balcony, it's a black one.",
    "The budget for my trip is tight, I'll take the train instead of flying.",
    "Alpha Project standup was short today, everyone is busy.",
    "Violin strings need replacing soon, the E string sounds dull.",
    "I moved my desk closer to the window, much better light for work.",
    "Bob Example sent photos of a hiking trip in the mountains.",
    "The community notice board at the library had a poster about a book fair.",
    "Ordered a new keyboard, it should arrive on Friday.",
    "Harbor Garden's compost bin smells, someone needs to turn it.",
    "Looking at recital videos online to get ideas for stage presence.",
    "Alpha Project code review took an hour, lots of small comments.",
    "My design sketchbook is almost full, I need a new one.",
    "Bob Example asked whether I still have his umbrella.",
    "I cooked a big pot of soup for the week.",
    "Read an article about how SQLite handles concurrent writes.",
    "The violin case latch is loose, I should get it repaired.",
    "Harbor Garden group chat was busy today with photos of the sunset.",
    "Updated my phone, the battery lasts longer now.",
    "Alpha Project might need a new logo at some point, nothing decided.",
    "Spent the evening sorting old photos from university.",
]


def distractors(n: int) -> dict[str, str]:
    return {f"ep_{NEW_DAY}_{i + 100:03d}": f"user: {DISTRACTOR_LINES[i % len(DISTRACTOR_LINES)]}\n\n"
            "assistant: Noted." for i in range(n)}


QUESTIONS = [
    {"id": "q01", "question": "When is the Alpha Project deadline now?", "expect": ["December 5"],
     "forbid": ["November 14 is the current deadline"]},
    {"id": "q02", "question": "Why did the Alpha Project deadline move?",
     "expect": ["the authentication flow has to be rewritten first"], "forbid": []},
    {"id": "q03", "question": "Which database does Alpha Project use?", "expect": ["SQLite"],
     "forbid": ["Postgres is the current database"]},
    {"id": "q04", "question": "Where does Bob Example live?", "expect": ["Porto"],
     "forbid": ["he lives in Lisbon now"]},
    {"id": "q05", "question": "Where does Bob Example work?", "expect": ["Northwind Example"],
     "forbid": ["he works at Example Corp now"]},
    {"id": "q06", "question": "Where is the next Harbor Garden planning meeting?", "expect": ["the community center"],
     "forbid": ["the public library is where the next meeting is"]},
    {"id": "q07", "question": "What budget was approved for Harbor Garden?", "expect": ["1,200 euros"],
     "forbid": []},
    {"id": "q08", "question": "Which day are my violin lessons?", "expect": ["Thursday"],
     "forbid": ["Tuesday is the current lesson day"]},
    {"id": "q09", "question": "What am I preparing in violin lessons, and for when?",
     "expect": ["a Bach partita", "a recital on January 18"], "forbid": []},
    {"id": "q10", "question": "Who does the design work on Alpha Project?", "expect": ["Dana Example"],
     "forbid": []},
    {"id": "q11", "question": "What is my cat's name?", "expect": ["Pixel"], "forbid": []},
    {"id": "q12", "question": "Who is my violin teacher?", "expect": ["Carol Example"], "forbid": [],
     "control": True},
]
for _q in QUESTIONS:
    _q.setdefault("abstain", False)
    _q.setdefault("tags", [])

ANSWER_SYSTEM = ("You answer a question about the person whose memory this is, using ONLY the memory text given. "
                 "When the memory holds an older and a newer statement, the newer one is current. If the memory "
                 "does not say, answer that it does not say. Answer in one or two sentences.")


def build_bank(bank: Path, extra: dict[str, str] | None = None) -> None:
    from api.services.claims import Claim, Evidence, write_claims

    (bank / "entities").mkdir(parents=True)
    (bank / "episodes").mkdir()
    for eid, (name, kind, body, facts, owner) in PAGES.items():
        claims = [Claim(id=f"clm_{OLD_DAY}_{eid[:6]}{i}", text=f"{name} {p} {o}", subject=eid, predicate=p,
                        object=o, object_kind="literal", valid_from=OLD_DAY, recorded_at=OLD_DAY,
                        source_episodes=[f"ep_{OLD_DAY}_001"], evidence=[Evidence()])
                  for i, (p, o) in enumerate(facts)]
        fm = (f"---\nname: {name}\ntype: {kind}\nstatus: active\nconfidence: 0.8\ncreated: {OLD_DAY}\n"
              f"last_referenced: {OLD_DAY}\naliases: []\n" + ("owner: true\n" if owner else "") + "---\n\n")
        text = fm + f"# {name}\n\n{body}\n"
        (bank / "entities" / f"{eid}.md").write_text(write_claims(text, claims) if claims else text, encoding="utf-8")

    def episode(eid: str, body: str, day: str, processed: bool) -> None:
        (bank / "episodes" / f"{eid}.md").write_text(
            f"---\nid: {eid}\nsource: claude-code\norigin: claude-code\ntimestamp: '{day}T18:00:00Z'\n"
            f"processed: {'true' if processed else 'false'}\n" + ("processed_by: sleep\n" if processed else "")
            + f"title: conversation {eid[-3:]}\n---\n\n{body}\n", encoding="utf-8")

    for eid, body in OLD_CONVERSATIONS.items():
        episode(eid, body, OLD_DAY, True)
    for eid, body in {**NEW_CONVERSATIONS, **(extra or {})}.items():
        episode(eid, body, NEW_DAY, False)
    subprocess.run(["git", "init", "-q", str(bank)], check=True)
    subprocess.run(["git", "-C", str(bank), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(bank), "-c", "user.name=Bench", "-c", "user.email=bench@example.invalid",
                    "commit", "-qm", "seed"], check=True)


# --------------------------------------------------------------------------------------------------------------------
# One run
# --------------------------------------------------------------------------------------------------------------------


def _usage_sink():
    from api.services import telemetry

    events: list = []
    real = telemetry.record

    def record(event) -> None:
        events.append(event)
        real(event)

    telemetry.record = record
    return events


def prepare(work: Path, condition: str, run: int, usage: list, new: dict[str, str]) -> tuple[Path, dict]:
    """A fresh copy of the bank for one (condition, run): its indexes built as that condition has them."""
    import shutil

    from api.services import awake_read, search_index, vector_index

    seed = work / "seed"
    bank = work / f"bank-{condition}-{run}"
    if bank.exists():
        shutil.rmtree(bank)
    shutil.copytree(seed, bank)
    # Before any capture: the consolidated part of the bank is indexed, as Sleep's sync left it.
    idx = vector_index.SqliteVecIndexer(bank)
    idx.index_entities()
    idx.index_claims()
    idx.index_episode_stems(list(OLD_CONVERSATIONS))
    search_index.ensure_fresh(bank, wait=True)
    cost = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "claims": 0, "held": 0}
    if condition in ("b", "c"):
        for ep in new:
            outcome = awake_read.index_now(bank, ep)
            assert outcome == "indexed", outcome
    if condition == "c":
        from api.config import get_settings

        before = len(usage)
        started = time.monotonic()
        for ep in new:
            outcome = asyncio.run(awake_read.quick_read(bank, ep, settings=get_settings()))
            if outcome != "read":
                print(f"  quick read {ep}: {outcome}", file=sys.stderr)
            rec = awake_read.load_record(bank, ep) or {}
            cost["claims"] += len(rec.get("claims") or [])
            cost["held"] += len(rec.get("held") or [])
        cost["seconds"] = time.monotonic() - started
        for ev in usage[before:]:
            if ev.stage == "quick_read":
                cost["calls"] += int(ev.invocations or 1)
                cost["input_tokens"] += int(ev.input_tokens or 0) + int(ev.cache_read_tokens or 0) + int(
                    ev.cache_write_tokens or 0)
                cost["output_tokens"] += int(ev.output_tokens or 0)
    return bank, cost


_SERVER = None


def _server():
    """The stdio MCP server module, loaded once (the path ``cicada_recall`` takes for a local harness)."""
    global _SERVER
    if _SERVER is None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("cicada_mcp_server_bench", REPO / "mcp" / "server.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _SERVER = module   # only once it is whole (main loads it before any worker thread asks)
    return _SERVER


def recall_text(bank: Path, question: str, condition: str) -> str:
    """``cicada_recall(question)`` on ``bank``. Condition (a) is recall before G207: no word leg over conversations
    (the vector leg already lacks the new ones, and there is no provisional record)."""
    server = _server()
    server.get_memory_path = lambda: bank
    tools = server.mcp_tools
    real = tools._lexical_search_episodes
    if condition == "a":
        tools._lexical_search_episodes = lambda *a, **k: []
    try:
        return server.handle_recall(question)
    finally:
        tools._lexical_search_episodes = real


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--conditions", default="abc")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--distractors", type=int, default=0, help="unslept filler conversations (the hard variant)")
    a = p.parse_args(argv)
    work = a.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if os.environ.get("CICADA_CAPTURE") != "off":
        print("set CICADA_CAPTURE=off", file=sys.stderr)
        return 2
    home = work / "home"
    os.environ.update({
        "HOME": str(home), "CICADA_HOME": str(home / ".cicada"), "CICADA_MEMORY_PATH": str(work / "seed"),
        "CICADA_LLM_MODE": "agent", "CICADA_AGENT_MODEL": "haiku", "CICADA_AGENT_DISAMBIGUATION_MODEL": "haiku",
        "CICADA_CLAUDE_CLI": str(PLAN_CLAUDE), "CICADA_VERIFY_REAL_CLAUDE": shutil.which("claude") or "",
        "CICADA_VERIFY_MODEL": "haiku", "CICADA_EMBED_WORKER": "off", "CICADA_BACKGROUND_REINDEX": "off",
        "CICADA_AWAKE_READ": "on", "HF_HUB_OFFLINE": "1", "LITELLM_MODE": "PRODUCTION",
        "CICADA_ALLOW_CONNECTOR_FETCH": "off", "CICADA_ALLOW_LOGO_FETCH": "off",
        "OMP_NUM_THREADS": "2", "ORT_NUM_THREADS": "2",   # ≤ 2 cores for embeddings on the shared server
    })
    sys.path.insert(0, str(REPO))
    from api.config import get_settings
    from api.services import awake_read, providers
    from benchmarks import answer_eval

    extra = distractors(a.distractors)
    new = {**NEW_CONVERSATIONS, **extra}
    if not (work / "seed").exists():
        build_bank(work / "seed", extra)
    awake_read.READS_PER_HOUR = max(awake_read.READS_PER_HOUR, len(new) * a.repeats)   # the bench reads them all
    usage = _usage_sink()
    _server()
    settings = get_settings().model_copy(update={"llm_mode": "agent", "agent_model": "haiku"})
    llm = providers.resolve_llm_fn(settings, stage="judge", is_async=False, scope="awake-bench")

    def ask(system: str, user: str, json_mode: bool) -> str:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        for attempt in (0, 1):
            try:
                return llm(messages=msgs, **kw).choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                if attempt or not answer_eval.is_transient(exc):
                    raise
                time.sleep(answer_eval.RETRY_BACKOFF_S)
        return ""

    out = a.out or work / "results.jsonl"
    rows, costs = [], {}
    for run in range(1, a.repeats + 1):
        for condition in a.conditions:
            bank, cost = prepare(work, condition, run, usage, new)
            costs[(condition, run)] = cost

            def one(q: dict) -> dict:
                memory = recall_text(bank, q["question"], condition)
                answer = ask(ANSWER_SYSTEM, f"MEMORY:\n{memory}\n\nQUESTION: {q['question']}", False)
                raw = ask(answer_eval.JUDGE_SYSTEM, answer_eval.judge_prompt(q, answer), True)
                try:
                    verdict = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
                except ValueError:
                    verdict = None
                g = answer_eval.grade(q, verdict)
                return {"run": run, "condition": condition, "id": q["id"], "control": bool(q.get("control")),
                        "recall_chars": len(memory), **g}

            with ThreadPoolExecutor(max_workers=a.workers) as pool:
                got = list(pool.map(one, QUESTIONS))
            rows.extend(got)
            ok = sum(1 for r in got if r.get("correct"))
            print(f"run {run} ({condition}): {ok}/{len(got)} correct"
                  + (f" — quick reads {cost['calls']} calls, {cost['input_tokens']}+{cost['output_tokens']} tokens, "
                     f"{cost['seconds']:.0f}s" if condition == "c" else ""), flush=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
        for (c, run), cost in costs.items():
            fh.write(json.dumps({"cost": cost, "condition": c, "run": run}) + "\n")
    os.chmod(out, 0o600)
    print("\nsummary (correct of 12, per run → mean, min–max):")
    for c in a.conditions:
        per = [sum(1 for r in rows if r["condition"] == c and r["run"] == run and r.get("correct"))
               for run in range(1, a.repeats + 1)]
        graded = sum(1 for r in rows if r["condition"] == c and r.get("graded"))
        print(f"  ({c}) {per} → {statistics.mean(per):.2f}, {min(per)}–{max(per)}  (graded {graded})")
    reads = [costs[("c", r)] for r in range(1, a.repeats + 1) if ("c", r) in costs]
    if reads:
        n = len(new)
        print("  quick read per conversation: "
              f"{statistics.mean(x['calls'] for x in reads) / n:.2f} calls, "
              f"{statistics.mean(x['input_tokens'] for x in reads) / n:.0f} input + "
              f"{statistics.mean(x['output_tokens'] for x in reads) / n:.0f} output tokens, "
              f"{statistics.mean(x['seconds'] for x in reads) / n:.1f}s; "
              f"{statistics.mean(x['claims'] for x in reads) / n:.1f} provisional claims, "
              f"{statistics.mean(x['held'] for x in reads) / n:.1f} held names")
    print(f"results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
