"""What a same-name split leaves on the old page, measured on a real git bank (2026-11-24).

`same_name_tend.split_page` moves a leaving conversation's beliefs and sourced Key Facts to a new page, but a page's
Summary (and any prose with no per-sentence source) was written when the page was a blend of two people: it stays. This
measures that, and where a thin mention (a conversation with nothing to tell the two people apart) ends up.

How: ``build`` runs the real Sleep (stager, `sleep_cycle.run`, Stage 1 and 3 page writer, a real engine) on a story of
one first name held by two people, with the same-name judge answering "one person" every time. That is the join this work
starts from (what Stage 2 did before the two-people rules, and what it still does whenever its judge reads a thin
description as the same person): one page holding both people's conversations, its Summary written by the product's own
page writer from both. The page is flagged. ``replay`` copies that bank (git history included) as many times as asked
and runs the real tail (`same_name_tend.run_tail`, the engine's main model) on each copy, then scores it. The stories
simulator has no page prose and cannot see this defect; this does.

Score, per story and per replay, no model: each person has marker words only their facts carry (``same_name_residue.json``);
a page "states a fact of the other person" when its whole text (Summary, sections, claims, tags) carries a marker of the
person it is NOT about. Pages are counted, not runs. The thin mention: which page holds its conversation, which page's
text carries its words, and whether that is the page of the person it truly belongs to (``thin_belongs``).

    api/.venv/bin/python -m benchmarks.consolidation.same_name_residue build --story dani --out DIR
    api/.venv/bin/python -m benchmarks.consolidation.same_name_residue replay --bank DIR/dani --story dani --repeats 4 --out DIR/after-dani
    api/.venv/bin/python -m benchmarks.consolidation.same_name_residue score --story dani --bank DIR/after-dani/r1/bank
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

FIXTURE = Path(__file__).with_name("same_name_residue.json")
CLOCK = date(2026, 11, 23)


def story(story_id: str) -> dict:
    for s in json.loads(FIXTURE.read_text(encoding="utf-8"))["stories"]:
        if s["id"] == story_id:
            return s
    raise SystemExit(f"no story {story_id!r}")


def _env_key() -> None:
    from benchmarks.consolidation.same_name_battery import key_from

    os.environ["ANTHROPIC_API_KEY"] = key_from(Path("~/.cicada/secrets.env"))


def _one_person(system: str, prompt: str):
    """The judge as the join this starts from: every conversation in one group."""
    letters = re.findall(r"^\(([A-Z])\)", prompt[prompt.find("Decide which"):], re.M)
    return {"people": [{"conversations": sorted(set(letters)), "reason": "one person"}], "pairs": []}


def build(story_id: str, out: Path) -> dict:
    from unittest.mock import patch

    from api.services import entity_resolver, providers, same_name_doubts, sleep_cycle
    from benchmarks.consolidation import run as bench
    from benchmarks.engine_parity import _leg_environment, _refuse_real_paths, settings_for, _git
    from benchmarks.system.engine import embed

    _env_key()
    _refuse_real_paths(out)
    fixture = story(story_id)
    bank, home = out / "bank", out / "home"
    home.mkdir(parents=True, exist_ok=True)
    fake_embed = lambda *a, **k: (embed, "fake-hash-v1")  # noqa: E731

    async def one(_settings, system, prompt, *a, **k):
        return _one_person(system, prompt)

    with _leg_environment(home, bank):
        bench.init_bank(bank, fixture["owner"])
        settings = settings_for("key", bank, model=bench.engine_model("key", "sonnet"), judge=bench.engine_model("key", "haiku"))
        for phase in sorted({c["phase"] for c in fixture["conversations"]}):
            convs = [c for c in fixture["conversations"] if c["phase"] == phase]
            bench.stage(bank, convs, CLOCK, f"Bench intake, phase {phase}")
            with patch.object(providers, "resolve_embed_fn", fake_embed), patch.object(entity_resolver, "_same_name_ask", one), \
                    patch.object(providers, "resolve_embed_fn_for_model", fake_embed), \
                    patch.object(providers, "cached_embed_fn_for_model", fake_embed):
                asyncio.run(sleep_cycle.run(settings, f"sleep_residue_{phase}", user_triggered=True, drain=True))
        pages = sorted(p.stem for p in (bank / "entities").glob("*.md"))
        slug = fixture["name"].lower().replace("í", "i")
        page = slug if slug in pages else next((p for p in pages if p.startswith(slug[:3])), None)
        if page:
            same_name_doubts.flag(bank, pages=[page])
            _git(bank, "add", "-A")
            _git(bank, "commit", "-q", "-m", "Flagged for the second look\n\nCicada-Author: cicada")
    return {"pages": pages, "flagged": page}


def _read(bank: Path, page_id: str):
    from api.services import markdown_parser

    return markdown_parser.parse(bank / "entities" / f"{page_id}.md")


def episode_map(bank: Path) -> dict[str, str]:
    """``{episode id: fixture conversation id}`` from each episode's ``source_id``."""
    from api.services import markdown_parser

    out = {}
    for p in sorted((bank / "episodes").glob("*.md")):
        sid = str((markdown_parser.parse(p).frontmatter or {}).get("source_id") or "")
        out[p.stem] = sid.split(":", 1)[-1]
    return out


def _who(conv: str, fx: dict) -> str:
    """``x`` / ``y`` for a conversation of that person; ``thin`` and ``clarifier`` carry no vote."""
    ids = [c["id"] for c in fx["conversations"]]
    if conv == fx["thin"]:
        return "thin"
    if conv == ids[-1]:
        return "clarifier"
    return "x" if ids.index(conv) < 2 else "y"


def hits(text: str, markers: list[str]) -> list[str]:
    low = text.casefold()
    return [m for m in markers if re.search(r"(?<!\w)" + re.escape(m.casefold()), low)]


def score(bank: Path, story_id: str) -> dict:
    """Per person page: whose it is (by its own conversations), and the other person's marker words in its whole text."""
    fx = story(story_id)
    emap = episode_map(bank)
    slug = fx["name"].lower().replace("í", "i")
    rows = []
    for path in sorted((bank / "entities").glob("*.md")):
        parsed = _read(bank, path.stem)
        fm = parsed.frontmatter or {}
        if str(fm.get("type") or "") != "person" or not str(fm.get("name") or "").lower().replace("í", "i").startswith(slug[:3]):
            continue
        eps = [emap.get(str(e), "?") for e in fm.get("source_episodes") or []]
        votes = [_who(c, fx) for c in eps if c in {x["id"] for x in fx["conversations"]}]
        nx, ny = votes.count("x"), votes.count("y")
        mine = "x" if nx > ny else "y" if ny > nx else "?"
        text = path.read_text(encoding="utf-8")
        other = {"x": "y", "y": "x"}.get(mine)
        leaked = hits(text, fx["people"][other]["markers"]) if other else []
        rows.append({"page": path.stem, "person": mine, "episodes": eps, "leaked": leaked, "holds_thin": fx["thin"] in eps})
    thin_on = [r for r in rows if r["holds_thin"]]
    thin_ok = None
    if fx["thin_belongs"] in ("x", "y") and thin_on:
        thin_ok = all(r["person"] == fx["thin_belongs"] for r in thin_on)
    return {"story": story_id, "pages": rows, "split": {r["person"] for r in rows if r["person"] in ("x", "y")} == {"x", "y"}, "thin_on": [r["page"] for r in thin_on], "thin_right": thin_ok}


def _count_gates(gates: dict) -> None:
    """Count what the leftovers gates refuse (2026-11-24): a line the judge named that is not tied to the leaving
    conversations by its own words, a cut not between clause edges, a cut the lock could not place exactly once."""
    from api.services import page_join, same_name_leftovers as sl

    tied, edges, still, apply_ = sl._tied, page_join.cut_edges_clean, sl.still_placeable, page_join._apply_cuts

    def count(name, ok):
        gates[name + "_asked"] = gates.get(name + "_asked", 0) + 1
        if not ok:
            gates[name + "_refused"] = gates.get(name + "_refused", 0) + 1
        return ok

    sl._tied = lambda *a, **k: count("tie", tied(*a, **k))
    page_join.cut_edges_clean = lambda *a, **k: count("edge", edges(*a, **k))

    def _still(memory_path, page_id, cuts):
        kept = still(memory_path, page_id, cuts)
        gates["revalidated"] = gates.get("revalidated", 0) + len(cuts)
        gates["revalidate_refused"] = gates.get("revalidate_refused", 0) + len(cuts) - len(kept)
        return kept

    def _apply(prose, cuts):
        kept, moved = apply_(prose, cuts)
        gates["applied"] = gates.get("applied", 0) + len(moved)
        gates["apply_refused"] = gates.get("apply_refused", 0) + len([c for c in cuts if c[0] != "tags"]) - len(moved)
        return kept, moved

    sl.still_placeable, page_join._apply_cuts = _still, _apply


def replay(bank: Path, story_id: str, out: Path, repeats: int) -> list[dict]:
    from api.services import same_name_tend
    from benchmarks.consolidation import run as bench
    from benchmarks.consolidation.same_name_battery import spend
    from benchmarks.engine_parity import _leg_environment, settings_for

    _env_key()
    results = []
    for k in range(1, repeats + 1):
        leg = out / f"r{k}"
        if leg.exists():
            continue
        shutil.copytree(bank, leg / "bank", symlinks=True)
        home = leg / "home"
        home.mkdir(parents=True, exist_ok=True)
        gates: dict = {}
        with _leg_environment(home, leg / "bank"):
            _count_gates(gates)
            settings = settings_for("key", leg / "bank", model=bench.engine_model("key", "sonnet"),
                                    judge=bench.engine_model("key", "haiku"))
            report = asyncio.run(same_name_tend.run_tail(leg / "bank", settings, user_triggered=True, today=CLOCK))
        row = score(leg / "bank", story_id)
        row.update(report={"looked": report.looked, "split": report.split, "skipped": report.skipped}, gates=gates,
                   spend=round(spend(home)["cost"], 4))
        (leg / "score.json").write_text(json.dumps(row, indent=1, ensure_ascii=False), encoding="utf-8")
        results.append(row)
        print(json.dumps({"r": k, "split": row["split"], "leaked": {r["page"]: r["leaked"] for r in row["pages"]},
                          "thin_on": row["thin_on"], "thin_right": row["thin_right"], "spend": row["spend"]},
                         ensure_ascii=False), flush=True)
    return results


def undo_check(base: Path, out: Path) -> str:
    """The person's undo of each split, on the replayed bank itself: every page (and the graph's edges) must come back
    byte for byte as the bank was before the split (``base``), Summary and tags included."""
    import subprocess

    from api.services import page_join
    from benchmarks.engine_parity import _leg_environment

    def snap(bank: Path) -> dict[str, bytes]:
        files = {p.name: p.read_bytes() for p in (bank / "entities").glob("*.md")}
        edges = bank / "graph_edges.yaml"
        return {**files, **({"graph_edges.yaml": edges.read_bytes()} if edges.exists() else {})}

    want, rows = snap(base), []
    for leg in sorted(out.glob("r*")):
        bank = leg / "bank"
        log = subprocess.run(["git", "-C", str(bank), "log", "--format=%H%x1f%s"], capture_output=True, text=True).stdout
        sha = next((line.split("\x1f")[0] for line in log.splitlines() if line.split("\x1f")[-1].startswith(page_join.SUBJECT_SPLIT)), None)
        if sha is None:
            continue
        with _leg_environment(leg / "home", bank):
            page_join.undo(bank, sha)
        got = snap(bank)
        rows.append(got == want)
        if got != want:
            print(leg.name, "differs:", sorted(k for k in set(got) | set(want) if got.get(k) != want.get(k)))
    return f"{out.name}: undo of the split put the bank back byte for byte in {sum(rows)} of {len(rows)} splits"


def summarize(out: Path) -> str:
    rows = [json.loads(p.read_text()) for p in sorted(out.glob("r*/score.json"))]
    split = [r for r in rows if r["split"]]
    pages = [p for r in split for p in r["pages"] if p["person"] in ("x", "y")]
    dirty = [p for p in pages if p["leaked"]]
    facts = sum(len(p["leaked"]) for p in pages)
    thin = [r for r in split if r["thin_right"] is not None]
    gates: dict = {}
    for r in rows:
        for k, v in (r.get("gates") or {}).items():
            gates[k] = gates.get(k, 0) + v
    return (f"{out.name}: gates {json.dumps(gates, sort_keys=True)}; runs {len(rows)}, split {len(split)}, pages {len(pages)}, pages stating the other person's fact "
            f"{len(dirty)} ({facts} marker words), thin mention on the right page {sum(1 for r in thin if r['thin_right'])}/{len(thin)}, "
            f"spend ${sum(r['spend'] for r in rows):.3f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--story", required=True)
    b.add_argument("--out", required=True)
    r = sub.add_parser("replay")
    r.add_argument("--bank", required=True)
    r.add_argument("--story", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--repeats", type=int, default=4)
    s = sub.add_parser("score")
    s.add_argument("--story", required=True)
    s.add_argument("--bank", required=True)
    t = sub.add_parser("summary")
    t.add_argument("--out", required=True)
    u = sub.add_parser("undo")
    u.add_argument("--bank", required=True)
    u.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        print(json.dumps(build(a.story, Path(a.out).expanduser() / a.story), ensure_ascii=False))
    elif a.cmd == "replay":
        replay(Path(a.bank).expanduser(), a.story, Path(a.out).expanduser(), a.repeats)
        print(summarize(Path(a.out).expanduser()))
    elif a.cmd == "score":
        print(json.dumps(score(Path(a.bank).expanduser(), a.story), indent=1, ensure_ascii=False))
    elif a.cmd == "undo":
        print(undo_check(Path(a.bank).expanduser(), Path(a.out).expanduser()))
    else:
        print(summarize(Path(a.out).expanduser()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
