"""Two-night revision stories through the real Sleep on a scratch bank (2026-11-24).

The consolidation benchmark has one edited conversation (U4: a sister's move date corrected after the first night) and it
was wrong in about half of its runs, so a defect that size needs more than three runs to see. This runs a small
invented bank of many such conversations at once: phase 1 is one night, then the listed conversations are edited in place
(the stager's revision, `episode_revision`) and a second night is drained. A story is one edit, and its ``expect`` is read
with no model from what the bank holds:

* ``about`` (optional): words every group below must also match, so one story's date is never read off another's;
* ``current``: the new value is in an open claim (a page's, or one held under a name with no page yet);
* ``stale``: the old value is in no open claim, under any predicate (`stale_open` lists the ones that are);
* ``kept``: what another conversation, or an unchanged line, says is still in an open claim (``kept_lost`` when the
  first night had it and the edit lost it);
* ``prose_stale`` / ``prose_new``: whether a page's prose still says the old value / says the new one.

The verdict is the benchmark's (`correct`, `both_current`, `stale_only`, `missing`); a story whose old value the first night
never made a claim of (``extracted_old`` false) has nothing to close and is reported apart. About 10 to 25 model calls a
night on the plan. Never a key.

    api/.venv/bin/python -m benchmarks.consolidation.revision_e2e --out /tmp/rev-1 --clock 2026-11-24
    api/.venv/bin/python -m benchmarks.consolidation.revision_e2e rescore --out /tmp/rev-1   # no model
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

STORIES = Path(__file__).with_name("revision_e2e_stories.json")


def _held(bank: Path) -> list[dict]:
    """Claims waiting under a name with no page yet (`pending_entities.jsonl`)."""
    path = bank / "pending_entities.jsonl"
    found: list[dict] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if isinstance(line, dict):
                found.extend(c for c in (line.get("held_claims") or []) if isinstance(c, dict))
    return found


def snapshot_claims(bank: Path) -> list[dict]:
    """Every claim a bank holds, on a page or held: the fields a story reads."""
    from benchmarks.consolidation import run as bench

    _, claims = bench.entity_rows(bank)
    return [{**c, "where": "page"} for c in claims] + [{**c, "where": "held"} for c in _held(bank)]


def _open(c: dict) -> bool:
    return not c.get("valid_to") and not c.get("superseded_by")


def judge_story(story: dict, claims: list[dict], prose: list[str], clock: date, first_night: list[dict] | None) -> dict:
    from benchmarks.consolidation import run as bench

    about = [story["about"]] if story.get("about") else []   # whose value it is: a date is never read off another story

    def groups(key):
        return [bench.expand_groups([*g, *about], clock) for g in story.get(key) or []]

    def hits(gs, pool, *, only_open):
        return [c for c in pool if (not only_open or _open(c)) and any(bench.matches(bench.claim_text(c), g) for g in gs)]

    current, stale, kept = groups("current"), groups("stale"), groups("kept")
    new_open = [c for g in current for c in hits([g], claims, only_open=True)]
    stale_open = [c for g in stale for c in hits([g], claims, only_open=True)]
    stale_any = [c for g in stale for c in hits([g], claims, only_open=False)]
    kept_ok = all(hits([g], claims, only_open=True) for g in kept)
    extracted_old = (any(hits([g], first_night or [], only_open=True) for g in stale) if stale and first_night is not None
                     else None)
    # What the first night had of the value that must stay current, and of what must stay: a value it never made cannot
    # be lost by the edit, so a story is judged on what it had (`had_current`, `kept_lost`).
    had_current = (all(hits([g], first_night or [], only_open=True) for g in current) if current and first_night is not None
                   else None)
    kept_first = (all(hits([g], first_night or [], only_open=True) for g in kept) if kept and first_night is not None
                  else None)
    if current:
        verdict = ("correct" if new_open and not stale_open else "both_current" if new_open and stale_open
                   else "stale_only" if stale_open else "missing")
    else:
        verdict = "correct" if not stale_open else "stale_current"
    page_says = lambda g: any(bench.matches(p, g) for p in prose)  # noqa: E731 - one use
    return {"id": story["id"], "shape": story["shape"], "lang": story["lang"], "verdict": verdict,
            "extracted_old": extracted_old, "kept_ok": kept_ok, "had_current": had_current,
            "kept_lost": bool(kept_first) and not kept_ok,
            "stale_open": [bench.claim_text(c)[:110] for c in stale_open],
            "stale_closed": len(stale_any) - len(stale_open),
            "new_open": [bench.claim_text(c)[:110] for c in new_open][:3],
            "prose_stale": any(page_says(g) for g in stale), "prose_new": all(page_says(g) for g in current) if current else None}


def score_bank(out: Path, fixture: dict, clock: date) -> dict:
    from benchmarks.consolidation import run as bench

    bank = out / "bank"
    pages, _ = bench.entity_rows(bank)
    prose = [bench.norm(f"{p['name']} {p.get('prose') or ''}") for p in pages]
    first = out / "first_night.json"
    first_night = json.loads(first.read_text(encoding="utf-8")) if first.exists() else None
    claims = snapshot_claims(bank)
    rows = [judge_story(s, claims, prose, clock, first_night) for s in fixture["expect"]["stories"]]
    return {"stories": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("action", nargs="?", choices=("run", "rescore"), default="run")
    parser.add_argument("--fixture", type=Path, default=STORIES)
    parser.add_argument("--out", type=Path, required=True, help="a new folder: the scratch bank and home are made in it")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--judge", default="haiku")
    parser.add_argument("--clock", type=date.fromisoformat, default=date(2026, 11, 24))
    a = parser.parse_args()
    fixture = json.loads(a.fixture.read_text(encoding="utf-8"))
    if a.action == "rescore":
        result = score_bank(a.out, fixture, a.clock)
        (a.out / "revision.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    from benchmarks.consolidation import engines, run as bench

    bench.PEOPLE["rev"] = a.fixture
    a.out.mkdir(parents=True, exist_ok=True)
    stage_again = bench.stage
    seen = {"n": 0}

    def stage_and_note(bank, convs, clock, label):
        # The bank as the first night left it, before the edits are staged: what each story's old value was made of.
        if seen["n"] == 1:
            (a.out / "first_night.json").write_text(json.dumps(snapshot_claims(bank), ensure_ascii=False, default=str))
        seen["n"] += 1
        return stage_again(bank, convs, clock, label)

    bench.stage = stage_and_note
    with engines.tally() as counted:
        snap = bench.run_leg(a.model, a.out, clock=a.clock, engine="plan", judge=a.judge, person="rev")
    engines.dump(counted, a.out / "tally.json")
    result = score_bank(a.out, fixture, a.clock)
    result.update(questions=snap.get("questions"), calls=counted.total(), unusable=counted.unusable(),
                  phases=[{k: p.get(k) for k in ("phase", "seconds", "error", "stop")} for p in snap.get("phases", [])])
    (a.out / "revision.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: v for k, v in result.items() if k != "stories"}, default=str))
    for row in result["stories"]:
        print(row["id"], row["shape"], row["verdict"], "old_made" if row["extracted_old"] else "", row["stale_open"][:2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
