"""Does the conversation decide which one a mention was, and never the wrong one? (ruling 83, 2026-11-26, `which_one_reader`)

`which_one_cases.json` is a labelled set of invented stories (English and Spanish). Each story is its own scratch bank (the people and
things the mention could be, one or two conversations, one held line, the which-one question) and carries ``expect``: ``file:<page>``
where the conversation says which one and the record can tie it, ``left`` for the rest (``by: code`` when the code conditions alone
must refuse it, ``by: reader`` when only a careful reader can). Each story is run through the real tending step
(`which_one_reader.tend`: code guards, two reads a conversation, the code's checks, the filing through the resolver) with:

* ``yes`` / ``yes-last``: a reader rigged to always name the first / last candidate by name and to copy the turn that says the
  mention: what the CODE conditions alone let through. The bar is only on the ``by: code`` stories (none may file) and on any
  filing under a page other than the expected one; what files wrongly among the ``by: reader`` traps is the honest size of what
  rests on the reader;
* ``no``: a reader rigged to say "cannot tell": nothing files;
* ``real``: the engine's main model on the Claude plan (`--engine plan`, haiku: no key is read; no word leaves but the invented
  sentences). One call to decide "none"/"cannot tell", two for each conversation that names a candidate the code accepts.

    api/.venv/bin/python -m benchmarks.consolidation.which_one_battery --judges yes,yes-last,no,real --engine plan --model haiku
    api/.venv/bin/python -m benchmarks.consolidation.which_one_battery --set conv --judges yes,yes-last,no,oracle,real --engine plan --model haiku

``--set conv`` (ruling 83, per conversation, `which_one_file`): stories with one held fact per conversation and a label per conversation
(``file:<page>`` or ``left``). Each conversation's fact must land on the page ITS words meant or stay held, and the question must ask
about exactly the conversations left; reports per conversation filed right / filed wrong (zero is the bar, every judge) / left right /
missed, the model calls, and two scenarios without a model (an undo of one of two filings; a tap on a per-conversation question).

Prints per story and judge ``filed:<page>`` / ``left`` against the expectation, then ``right`` (filed under the expected page),
``wrong`` (filed under any other page, or filed where it must be left), ``missed`` (left and should have filed) and the number of
model calls. Exit 1 on a wrong filing by any judge but ``yes`` / ``yes-last`` on a ``by: reader`` story, or by a rigged judge on
a ``by: code`` story."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
CASES = HERE / "which_one_cases.json"
TODAY = date(2026, 11, 26)
FLAG = "  <- says the name"


class _Settings:
    inbox_defer_days = 30
    inbox_stale_after_days = 90
    litellm_model = "bench"
    llm_mode = "byok"

    def __init__(self, memory_path: Path) -> None:
        self.memory_path = memory_path


def _git(bank: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(bank), *args], check=True, capture_output=True, text=True)


def build_bank(root: Path, spec: dict, story: dict) -> tuple[Path, Path]:
    """One scratch bank: every page of the set, the story's conversations, one held line and the which-one question."""
    from api.services import bank_index, markdown_parser, pending_store, predicates, same_name, which_one
    from api.services.claims import Claim
    from api.services.id_utils import sanitize_id

    bank = root / "bank"
    for sub in ("entities", "episodes", "inbox"):
        (bank / sub).mkdir(parents=True)
    predicates.install_predicate_map(bank)
    for p in spec["pages"]:
        body = f"## Summary\n{p['name']} is someone or something the person knows.\n"
        if p.get("links"):
            body += "\nRelated: " + ", ".join(f"[[{x}]]" for x in p["links"]) + ".\n"
        markdown_parser.write(bank / "entities" / f"{p['id']}.md",
                              {"id": p["id"], "name": p["name"], "type": p["type"], "status": "active", "aliases": p.get("aliases", []),
                               **({"owner_roles": p["roles"]} if p.get("roles") else {}), "source_episodes": [], "tags": [],
                               "created": "2026-09-01", "last_referenced": "2026-09-01", "version": 1}, body)
    episodes = []
    for k, text in enumerate(story["conversations"]):
        text = re.sub(r"\{filler:(\d+)\}", lambda m: "filler words here. " * int(m.group(1)), text)
        ep = f"ep_2026-11-{18 + k:02d}_001"
        episodes.append(ep)
        markdown_parser.write(bank / "episodes" / f"{ep}.md", {"id": ep, "processed": True, "source": "import", "origin": "chatgpt",
                                                                 "timestamp": f"2026-11-{18 + k:02d}T10:00:00+00:00"}, text)
    mention = story["mention"]
    # One held fact per conversation for a per-conversation story (ruling 83), else the one the single-line stories hold.
    held = episodes if story.get("expect_conv") else episodes[:1]
    claims = [Claim(id=f"clm_held_{k + 1}", text=f"{mention} was mentioned", subject=sanitize_id(mention), predicate="mentioned-in",
                    object=f"conversation-{k + 1}", valid_from="2026-11-18", recorded_at="2026-11-18", source_episodes=[ep]).to_dict()
              for k, ep in enumerate(held)]
    pending_store.upsert(bank, pending_store.PendingEntity(
        name=mention, type="person", description=f"{mention}, said once.", source_episode=episodes[0], confidence=0.7, tags=[],
        history_entries=[], held_claims=claims, heard_in=[{"episode": e} for e in episodes]))
    for args in (("init", "-q"), ("config", "user.email", "bench@example.com"), ("config", "user.name", "bench")):
        _git(bank, *args)
    same_name.invalidate()
    ids = which_one.answering(bank, mention, exclude={sanitize_id(mention)})
    path = which_one.raise_question(bank, mention, episodes[0], ids, today=TODAY)
    assert path, (story["id"], ids)
    _git(bank, "add", "-A")
    _git(bank, "commit", "-qm", "seed")
    bank_index.invalidate()
    return bank, bank / path


_CAND = re.compile(r"^([A-F])\. (.+?)(?: \(|\s—)", re.M)
_MARKED = re.compile(r"^\[\d+\] [^:\n]+: (.*?)" + re.escape(FLAG) + r"$", re.M)


def oracle(spec: dict, story: dict):
    """A reader that answers each conversation as the labels say (by finding the conversation in the prompt) and copies its marked
    turn: the right reader, to exercise the filing, the undo and the tap without a model."""
    names = {p["id"]: p["name"] for p in spec["pages"]}

    async def ask(system: str, prompt: str) -> object:
        cands = {name: letter for letter, name in _CAND.findall(prompt)}
        said = _MARKED.search(prompt)
        for text, label in zip(story["conversations"], story["expect_conv"]):
            if " ".join(text.split("\n")[0].split()[1:6]) in prompt and label.startswith("file:"):
                return {"answer": cands.get(names[label.split(":", 1)[1]], "none"),
                        "sentence": " ".join((said.group(1) if said else "").split())[:200], "reason": "oracle"}
        return {"answer": "cannot_tell", "sentence": "", "reason": "oracle"}

    return ask


def rigged(mode: str):
    """A reader that always answers the same way, copying the turn that says the mention: ``first`` / ``last`` name the candidate
    that sorts first / last by name, ``none`` always cannot tell."""
    async def ask(system: str, prompt: str) -> object:
        if mode == "none":
            return {"answer": "cannot_tell", "sentence": "", "reason": "rigged"}
        cands = sorted(_CAND.findall(prompt), key=lambda c: c[1].lower())
        letter = (cands[0] if mode == "first" else cands[-1])[0] if cands else "none"
        said = _MARKED.search(prompt)
        return {"answer": letter, "sentence": " ".join((said.group(1) if said else "").split())[:200], "reason": "rigged"}

    return ask


async def run_story(spec: dict, story: dict, judge: str, real) -> dict:
    from api.services import markdown_parser, which_one_reader as wr
    from api.services.claims import parse_claims

    with tempfile.TemporaryDirectory(prefix="which-one-") as tmp:
        bank, path = build_bank(Path(tmp), spec, story)
        calls = {"n": 0}
        inner = real[0] if judge == "real" else rigged({"yes": "first", "yes-last": "last", "no": "none"}[judge])

        async def ask(system: str, prompt: str) -> object:
            calls["n"] += 1
            return await inner(system, prompt)

        await wr.tend(bank, _Settings(bank), ask, today=TODAY, model="bench")
        filed = ""
        for page in (bank / "entities").glob("*.md"):
            if any(c.id == "clm_held_1" for c in parse_claims(markdown_parser.parse(page).body)):
                filed = page.stem
        expect = story["expect"]
        right = expect.startswith("file:") and filed == expect.split(":", 1)[1]
        return {"id": story["id"], "judge": judge, "expect": expect, "by": story.get("by", ""), "filed": filed, "calls": calls["n"],
                "right": right, "wrong": bool(filed) and not right, "missed": expect.startswith("file:") and not filed,
                "question_open": path.exists()}


async def run_conv_story(spec: dict, story: dict, judge: str, real) -> dict:
    """A per-conversation story: each conversation's held fact must land on the page ITS words meant (or stay held), through the real
    tending step. Per conversation: right / wrong (a fact under any other page) / left; the question must then ask about exactly the
    conversations left."""
    from api.services import markdown_parser, pending_store, which_one_file as wf, which_one_reader as wr
    from api.services.claims import parse_claims

    with tempfile.TemporaryDirectory(prefix="which-one-") as tmp:
        bank, path = build_bank(Path(tmp), spec, story)
        calls = {"n": 0}
        inner = (real[0] if judge == "real" else oracle(spec, story) if judge == "oracle"
                 else rigged({"yes": "first", "yes-last": "last", "no": "none"}[judge]))

        async def ask(system: str, prompt: str) -> object:
            calls["n"] += 1
            return await inner(system, prompt)

        await wr.tend(bank, _Settings(bank), ask, today=TODAY, model="bench")
        where: dict[str, str] = {}
        for page in (bank / "entities").glob("*.md"):
            for c in parse_claims(markdown_parser.parse(page).body):
                if c.id.startswith("clm_held_"):
                    where[c.id] = page.stem
        per = []
        for k, label in enumerate(story["expect_conv"]):
            got = where.get(f"clm_held_{k + 1}", "")
            right = label.startswith("file:") and got == label.split(":", 1)[1]
            per.append({"conversation": k + 1, "expect": label, "filed": got, "right": right,
                        "wrong": bool(got) and not right, "left_right": not got and label == "left", "missed": label.startswith("file:") and not got})
        line = pending_store.held_line(bank, story["mention"])
        asked = wf.open_episodes(line) if line is not None else []
        return {"id": story["id"], "judge": judge, "per": per, "calls": calls["n"], "asked": len(asked),
                "asked_right": len(asked) == sum(1 for p in per if not p["filed"])}


def scenarios(spec: dict) -> list[dict]:
    """The undo of one of two filings and the tap on a per-conversation question, on the oracle reader / the reader that cannot tell
    (no model calls): the claim goes back to the line and is not refiled; a pick files that conversation's words only."""
    from api.models.schemas import InboxResolveRequest
    from api.services import inbox_service, markdown_parser, pending_store, which_one_file as wf, which_one_reader as wr
    from api.services.claims import parse_claims

    out = []
    by_id = {s["id"]: s for s in spec["conversation_stories"]}
    story = by_id["conv-two-people-two-conversations"]
    with tempfile.TemporaryDirectory(prefix="which-one-") as tmp:
        bank, path = build_bank(Path(tmp), spec, story)
        asyncio.run(wr.tend(bank, _Settings(bank), oracle(spec, story), today=TODAY, model="bench"))
        _git(bank, "add", "-A")
        subprocess.run(["git", "-C", str(bank), "commit", "-qm", "x"], capture_output=True)
        rec = next(p for p in sorted((bank / "inbox" / "settled").glob("land-*.md"))
                   if markdown_parser.parse(p).frontmatter["settled"]["entity_id"] == "nick-rowe")
        wf.undo(bank, rec.stem)
        subprocess.run(["git", "-C", str(bank), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(bank), "commit", "-qm", "undo"], capture_output=True)
        back = [d["id"] for d in pending_store.held_line(bank, "Nick").held_claims]
        question = next((p for p in (bank / "inbox").glob("inbox-*.md")), None)
        asyncio.run(wr.tend(bank, _Settings(bank), oracle(spec, story), today=TODAY, model="bench"))
        again = any(c.id == "clm_held_1" for c in parse_claims(markdown_parser.parse(bank / "entities" / "nick-rowe.md").body))
        out.append({"scenario": "undo one of two filings", "claim_back_on_line": back == ["clm_held_1"], "refiled": again,
                    "other_filing_stands": any(c.id == "clm_held_2" for c in parse_claims(
                        markdown_parser.parse(bank / "entities" / "nick-vale.md").body)),
                    "question_open": question is not None})
    story = by_id["conv-nobody-can-tell-either"]
    with tempfile.TemporaryDirectory(prefix="which-one-") as tmp:
        bank, path = build_bank(Path(tmp), spec, story)
        asyncio.run(wr.tend(bank, _Settings(bank), rigged("none"), today=TODAY, model="bench"))
        scoped = wf.scope_of(markdown_parser.parse(path).frontmatter)
        subprocess.run(["git", "-C", str(bank), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(bank), "commit", "-qm", "x"], capture_output=True)
        asyncio.run(inbox_service.resolve(path.stem, InboxResolveRequest(action="merge", merge_target="nick-rowe"), _Settings(bank)))
        on_page = [c.id for c in parse_claims(markdown_parser.parse(bank / "entities" / "nick-rowe.md").body) if c.id.startswith("clm_held_")]
        left = [d["id"] for d in pending_store.held_line(bank, "Nick").held_claims]
        out.append({"scenario": "tap on a per-conversation question", "asked_one_conversation": len(scoped) == 1,
                    "tap_filed_that_conversation_only": on_page == ["clm_held_1"] and left == ["clm_held_2"],
                    "next_conversation_asked": path.exists()})
    return out


def summarise_conv(rows: list[dict]) -> dict:
    out = {}
    for judge in dict.fromkeys(r["judge"] for r in rows):
        per = [p for r in rows if r["judge"] == judge for p in r["per"]]
        out[judge] = {"conversations": len(per), "filed_right": sum(p["right"] for p in per), "filed_wrong": sum(p["wrong"] for p in per),
                      "left_right": sum(p["left_right"] for p in per), "missed": sum(p["missed"] for p in per),
                      "question_asks_exactly_the_left_ones": sum(r["asked_right"] for r in rows if r["judge"] == judge),
                      "model_calls": sum(r["calls"] for r in rows if r["judge"] == judge)}
    return out


def summarise(rows: list[dict]) -> dict:
    out = {}
    for judge in dict.fromkeys(r["judge"] for r in rows):
        mine = [r for r in rows if r["judge"] == judge]
        out[judge] = {"stories": len(mine), "right": sum(r["right"] for r in mine), "wrong": sum(r["wrong"] for r in mine),
                      "wrong_code_must_refuse": sum(r["wrong"] and r["by"] == "code" for r in mine),
                      "wrong_reader_must_refuse": sum(r["wrong"] and r["by"] == "reader" for r in mine),
                      "missed": sum(r["missed"] for r in mine),
                      "left_right": sum(not r["filed"] and r["expect"] == "left" for r in mine),
                      "model_calls": sum(r["calls"] for r in mine)}
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--judges", default="yes,yes-last,no,real")
    p.add_argument("--engine", choices=("plan",), default="plan")
    p.add_argument("--model", default="haiku")
    p.add_argument("--only", default="", help="run the stories whose id contains this text")
    p.add_argument("--set", choices=("single", "conv"), default="single",
                   help="single: one held fact per story (the labelled set); conv: one held fact per conversation, each to its own page")
    p.add_argument("--json", type=Path)
    a = p.parse_args(argv)
    os.environ.pop("ANTHROPIC_API_KEY", None)   # `claude -p` must bill the plan, never a key found in the environment
    if "real" in a.judges:
        # The verify-cicada skill's `plan-claude` shim: the real HOME for that one child (the plan's sign-in), the pinned argv, one model.
        import shutil

        repo = HERE.parents[1]
        os.environ.update({"CICADA_CAPTURE": "off", "CICADA_RECALL": "off", "CICADA_VERIFY_MODEL": a.model,
                           "CICADA_CLAUDE_CLI": str(repo / ".claude" / "skills" / "verify-cicada" / "bin" / "plan-claude"),
                           "CICADA_VERIFY_REAL_CLAUDE": os.environ.get("CICADA_VERIFY_REAL_CLAUDE") or shutil.which("claude") or ""})
    spec = json.loads(CASES.read_text(encoding="utf-8"))
    stories = [s for s in spec["conversation_stories" if a.set == "conv" else "stories"] if a.only in s["id"]]
    judges = [j for j in a.judges.split(",") if j]
    home = Path(tempfile.mkdtemp(prefix="which-one-home-"))
    from benchmarks.engine_parity import _leg_environment, settings_for

    rows: list[dict] = []
    with _leg_environment(home, home / "scratch"):
        real = None
        if "real" in judges:
            from api.services import full_name_join, same_name_tend
            from benchmarks.consolidation.run import engine_model

            settings = settings_for("plan", home / "scratch", model=engine_model("plan", a.model), judge=engine_model("plan", a.model))
            strong = same_name_tend.main_tier(settings)

            async def ask(system: str, prompt: str) -> object:
                return await full_name_join.ask_main(strong, system, prompt)

            real = (ask,)
        if a.set == "conv":
            conv_rows: list[dict] = []
            for judge in judges:
                for story in stories:
                    row = asyncio.run(run_conv_story(spec, story, judge, real))
                    conv_rows.append(row)
                    cells = " ".join(f"{p['filed'] or 'left'}{'' if p['right'] or p['left_right'] else '(WRONG)' if p['wrong'] else '(missed)'}"
                                     for p in row["per"])
                    print(f"{judge:8} {row['id']:36} {cells:64} asked={row['asked']} calls={row['calls']}", flush=True)
            result = {"conversations": summarise_conv(conv_rows), "scenarios": scenarios(spec)}
            print(json.dumps(result, indent=1))
            if a.json:
                a.json.write_text(json.dumps({"rows": conv_rows, **result}, indent=1))
            wrong = any(p["wrong"] for r in conv_rows for p in r["per"])
            ok = all(v for sc in result["scenarios"] for k, v in sc.items() if k not in ("scenario", "refiled")) and not any(
                sc.get("refiled") for sc in result["scenarios"])
            return 1 if wrong or not ok else 0
        for judge in judges:
            for story in stories:
                row = asyncio.run(run_story(spec, story, judge, real))
                rows.append(row)
                state = f"filed:{row['filed']}" if row["filed"] else "left"
                verdict = "ok" if row["right"] or (not row["filed"] and row["expect"] == "left") else "WRONG" if row["wrong"] else "missed"
                print(f"{judge:8} {row['id']:34} {state:22} {verdict:6} expect={row['expect']:18} by={row['by'] or '-':6} calls={row['calls']}", flush=True)
    summary = summarise(rows)
    print(json.dumps(summary, indent=1))
    if a.json:
        a.json.write_text(json.dumps({"rows": rows, "summary": summary}, indent=1))
    bad = [r for r in rows if r["wrong"] and ((r["judge"] in ("yes", "yes-last") and r["by"] == "code") or
                                               (r["judge"] not in ("yes", "yes-last")))]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
