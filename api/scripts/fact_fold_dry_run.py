"""What the fact fold would do to each page of a bank copy — per item, writing nothing (`fact_fold`, G148; owner 2026-11-23).

    api/.venv/bin/python -m api.scripts.fact_fold_dry_run --bank <copy> --out <dir>                     # no engine
    api/.venv/bin/python -m api.scripts.fact_fold_dry_run --bank <copy> --out <dir> --judge --limit 20  # + the judge
    api/.venv/bin/python -m api.scripts.fact_fold_dry_run --pairs --out <dir> [--judge]                  # invented pairs

**What is replayed.** A write folds a fact the page already says only when that write brings a fact no bullet equals.
To show what the next write of each page would do, each machine page with 2+ Key Facts is replayed as one: its newest
bullets that an earlier, different bullet resembles (shared words, names or numbers) arrive as NEW (at most
``fact_fold.MAX_NEW``), the rest are the page. That is the case the fold exists for — a fact said again — and the page's
real next write may bring other facts; the pairs below are the ones the judge would be shown and the code would let through.

**No engine** (the default): per page whether it would be asked, how many lines the ask would carry, and, as a count, the
pairs of bullets that are the same text once a link is written under its page's own name (`link_names`) — equal pairs
the existing union folds with no model. **With ``--judge``** (the Claude plan, the small tier: run it with
``CICADA_AGENT_DISAMBIGUATION_MODEL=haiku``; one ask and at most one check per page, so at most two calls a page): for
each page the pairs the judge proposed, whether the code check (`fact_fold.covers`) passed, whether the second reader
agreed, and the fold that would result. **``--pairs``** runs the invented pairs of ``tests/fixtures/fact_fold_pairs.json``
through the judge and reports false folds (a pair a person would keep, folded) and missed folds (one they would let go,
kept): that needs ``--judge``; without it only the code check is run.

The rows carry bullet text (for the eyes of the person running it — the output directory must be outside the repo);
the stdout summary is counts only. The bank is read, never written: no commit, no ledger row, no index. Exit 0 done, 2
not a bank.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "fact_fold_pairs.json"


def _pages(memory: Path) -> list[dict]:
    from api.services import markdown_parser

    out = []
    for path in sorted((memory / "entities").glob("*.md")):
        try:
            parsed = markdown_parser.parse(path)
        except Exception:  # noqa: BLE001 - an unreadable page is skipped, never an error
            continue
        out.append({"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    return out


def _replay(page: dict, names, owner: str | None):
    """``(ask or None, bullets)``: the page replayed as a write that brings its own most-repeated newest facts again."""
    from api.services import conflict_resolver, entity_body, fact_fold, fact_policy
    from api.services.claims import strip_claims_block

    fm = page.get("frontmatter") or {}
    if str(fm.get("status") or "") in ("dropped",):
        return None, []
    sections = entity_body.parse_sections(strip_claims_block(page.get("body", "")))
    bullets = entity_body._bullet_lines(sections.get("Key Facts", ""))
    if len(bullets) < 2:
        return None, bullets
    tails = [i for i in range(len(bullets) - 1, 0, -1)
             if any(fact_fold._overlap(bullets[i], bullets[j]) > 0 and not fact_policy.restates(bullets[i], bullets[j])
                    for j in range(i))][:fact_fold.MAX_NEW]
    if not tails:
        return None, bullets
    incoming = [bullets[i] for i in sorted(tails)]
    existing = [b for i, b in enumerate(bullets) if i not in set(tails)]
    pinned = frozenset(fact_policy.normalized(str(r.get("new") or "")) for r in (fm.get("corrections") or [])
                       if isinstance(r, dict))
    ask = fact_fold.build(page["id"], str(fm.get("name") or page["id"]), existing, incoming,
                          heal=not conflict_resolver._is_human_edited(fm, sections), pinned=pinned, names=names,
                          own=[*(str(a) for a in fm.get("aliases") or []), *([owner] if owner else [])], owner=owner)
    return ask, bullets


def _equal_after_links(bullets: list[str], names) -> int:
    from api.services import fact_policy, link_names

    before, after = {}, {}
    pairs = 0
    for b in bullets:
        k0, k1 = fact_policy.normalized(b), fact_policy.normalized(link_names.rewrite(b, names)[0])
        if k1 in after and k0 not in before:
            pairs += 1
        before[k0] = 1
        after.setdefault(k1, 1)
    return pairs


def _settings(memory: Path, model: str):
    from api.config import Settings

    return Settings(_env_file=None, llm_mode="agent", agent_model=model, agent_disambiguation_model=model,
                    CICADA_MEMORY_PATH=str(memory))


def run_bank(memory: Path, out: Path, *, judge, limit: int | None) -> dict:
    from api.services import fact_fold, link_names

    pages = _pages(memory)
    names = link_names.Names(pages)
    owner = next((str((p["frontmatter"] or {}).get("name") or "") for p in pages if (p["frontmatter"] or {}).get("owner")),
                 None)
    rows, summary = [], {"pages": len(pages), "with_facts": 0, "would_be_asked": 0, "lines_shown": 0,
                         "equal_after_links": 0, "proposed": 0, "guard_refused": 0, "checked_ok": 0, "folds": 0,
                         "judged_pages": 0}
    asked = 0
    for page in pages:
        ask, bullets = _replay(page, names, owner)
        if bullets:
            summary["with_facts"] += 1
            summary["equal_after_links"] += _equal_after_links(bullets, names)
        if ask is None:
            continue
        summary["would_be_asked"] += 1
        summary["lines_shown"] += len(ask.lines)
        row = {"page": page["id"], "lines": [{"n": ln.n, "new": ln.new, "text": ln.text} for ln in ask.lines]}
        if judge is not None and (limit is None or asked < limit):
            asked += 1
            summary["judged_pages"] += 1
            reply = judge(fact_fold.prompt(ask))
            raw = reply.get("answers") if isinstance(reply, dict) else []
            proposed = fact_fold.proposals(reply, ask)
            summary["proposed"] += len(raw) if isinstance(raw, list) else 0
            summary["guard_refused"] += (len(raw) if isinstance(raw, list) else 0) - len(proposed)
            oriented = fact_fold.orient(proposed, ask)
            summary["link_refused"] = summary.get("link_refused", 0) + len(proposed) - len(oriented)
            confirmed = fact_fold.checks(oriented, ask, judge)
            summary["checked_ok"] += len(confirmed)
            decided = fact_fold.folds(confirmed, ask)
            summary["folds"] += len(decided)
            row["proposed"] = [{"drop": d.text, "by": k.text} for d, k in proposed]
            row["folds"] = [{"drop": d, "into": k, "path": ask.paths.get(d, "plain")} for d, k in decided.items()]
            for path in {ask.paths.get(d, "plain") for d in decided}:
                paths = summary.setdefault("fold_paths", {})
                paths[path] = paths.get(path, 0) + sum(1 for d in decided if ask.paths.get(d, "plain") == path)
        rows.append(row)
    (out / "items.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def run_pairs(out: Path, *, judge) -> dict:
    from api.services import fact_fold

    pairs = json.loads(FIXTURE.read_text(encoding="utf-8"))["pairs"]
    rows, false_folds, missed, blind_false = [], [], [], []
    for pair in pairs:
        ask = fact_fold.ask_from_pair(pair)
        guard = fact_fold.covers(pair["keep"], pair["drop"], allowed=fact_fold._allowed(ask, pair["keep"]),
                                 people=ask.people)
        folded = None
        if judge is not None:
            # A fold is the NEW line going: the other direction (the page's bullet replaced by a fuller new fact) loses
            # nothing the new fact does not say, and is not a fold of the pair under test.
            folded = pair["drop"] in fact_fold.decide(ask, judge)
            if folded and not pair["fold"]:
                (blind_false if pair.get("blind") else false_folds).append(pair["id"])
            if not folded and pair["fold"]:
                missed.append(pair["id"])
        rows.append({"id": pair["id"], "should_fold": pair["fold"], "guard_passes": guard, "folded": folded})
    (out / "pairs.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    must_not = [p for p in pairs if not p["fold"]]
    return {"pairs": len(pairs), "must_fold": sum(p["fold"] for p in pairs), "must_not": len(must_not),
            "guard_alone_false_folds": sum(1 for p, r in zip(pairs, rows) if r["guard_passes"] and not p["fold"]
                                           and not p.get("blind")),
            **({"false_folds": len(false_folds), "false_folds_blind_to_code": len(blind_false),
                "missed_folds": len(missed), "false_ids": false_folds + blind_false, "missed_ids": missed}
               if judge is not None else {})}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--bank", type=Path, help="a COPY of a bank (read only)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--judge", action="store_true", help="ask Sleep's small judge (the Claude plan)")
    ap.add_argument("--limit", type=int, default=None, help="at most this many pages go to the judge")
    ap.add_argument("--pairs", action="store_true", help="the invented pairs instead of a bank")
    ap.add_argument("--model", default="haiku")
    args = ap.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    import os

    # Nothing of the person's: the engine's ledger rows and any capture hook go to a scratch home.
    os.environ.update({"CICADA_HOME": str(args.out / "home"), "CICADA_CAPTURE": "off", "CICADA_RECALL": "off",
                       "CICADA_TELEMETRY": "off", "CICADA_ALLOW_CONNECTOR_FETCH": "off"})
    memory = args.bank or args.out
    if not args.pairs and not (args.bank and (args.bank / "entities").is_dir()):
        print("not a bank: --bank must hold entities/", file=sys.stderr)
        return 2
    judge = None
    if args.judge:
        from api.services import fact_fold

        judge = fact_fold.judge_for(_settings(memory, args.model))
        if judge is None:
            print("no engine can answer", file=sys.stderr)
            return 2
    summary = run_pairs(args.out, judge=judge) if args.pairs else run_bank(args.bank, args.out, judge=judge,
                                                                           limit=args.limit)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
