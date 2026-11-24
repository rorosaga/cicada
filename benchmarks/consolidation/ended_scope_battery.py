"""Replay battery for what rested on the thing that ended (`value_ended.scope_candidates`, 2026-11-24).

Why: a person leaves an employer or a flat and names no replacement. The title at the employer, the project they led
there, the page that names them its lead and the landlord of the flat must close with it; their trade, a friend who
still works there, what they learned there and what the employer is must not. This replays the product's own judge call
(`value_ended.plan`: the same candidate rule, prompt and words read back from located spans) many times, for cents.
Every name, value and line below is invented.

    api/.venv/bin/python -m benchmarks.consolidation.ended_scope_battery --repeats 20

Needs ``ANTHROPIC_API_KEY`` in the environment or in ``--key-file`` (never printed). Exit 1 when a CLOSE case stays
open or a STAY case closes, in any repeat.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

OLD_EP, NEW_EP = "ep_2026-09-10_001", "ep_2026-11-10_001"
OLD_DAY, NEW_DAY = "2026-09-10", "2026-11-10"

# A claim is (subject, predicate, object, "node" | "literal", text, the person's line it rests on).
#   case = (name, should close, the ending (subject, label, thing, line), [the claim the case asks about],
#           [claims around it: ties and bystanders], what the person said earlier (one line))
CASES = [
    # --- a job that ended with no new title named -----------------------------------------------------------------
    ("a title whose attribute names the employer", True,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "value-of-job-title-at-brightwell-labs", "data analyst", "literal",
      "Nina Voss job title at Brightwell Labs: data analyst", "I work as a data analyst at Brightwell Labs."), []),
    ("a project she led there", True,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "leads", "brightwell-billing-migration", "node", "Nina Voss leads Brightwell billing migration",
      "I'm leading the billing migration at Brightwell."), []),
    ("a project that belongs to the employer, tied only by its own page", True,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "works-on", "invoice-engine", "node", "Nina Voss works on Invoice engine",
      "Most of my week goes into the invoice engine."),
     [("invoice-engine", "belongs-to", "brightwell", "node", "Invoice engine belongs to Brightwell Labs", "")]),
    ("the page of what she led names her its lead", True,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("billing-migration", "value-of-lead", "Nina Voss", "literal", "Billing migration lead: Nina Voss",
      "Nina is leading the billing migration at Brightwell."),
     [("billing-migration", "belongs-to", "brightwell", "node", "Billing migration belongs to Brightwell Labs", "")]),
    ("the same, said in Spanish", True,
     ("lucia-vera", "left", "brightwell", "Hoy fue mi último día en Brightwell, me tomo el invierno libre."),
     ("lucia-vera", "value-of-puesto-en-brightwell", "analista de datos", "literal",
      "Lucía Vera puesto en Brightwell: analista de datos", "Trabajo como analista de datos en Brightwell."), []),
    ("a manager's line on the manager's own page", True,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("dana-ortiz", "value-of-direct-report", "Nina Voss", "literal", "Dana Ortiz direct report: Nina Voss",
      "My manager at Brightwell is Dana Ortiz."),
     [("dana-ortiz", "works-at", "brightwell", "node", "Dana Ortiz works at Brightwell Labs", "")]),
    ("a flat's landlord after moving out of it", True,
     ("nina-voss", "moved out of", "calle-sol-flat", "I moved out of the Calle Sol flat on Friday."),
     ("nina-voss", "value-of-landlord-of-calle-sol-flat", "Mr. Duarte", "literal",
      "Nina Voss landlord of Calle Sol flat: Mr. Duarte", "My landlord at the Calle Sol flat is Mr. Duarte."), []),
    ("a platform's other use after dropping it", True,
     ("cartolina", "dropped", "shopify", "I dropped Shopify, the shop is on Etsy now."),
     ("cartolina", "runs-shop-on", "shopify", "node", "Cartolina runs shop on Shopify",
      "I run the shop on Shopify."), []),
    ("her role in a project named only in the attribute", True,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "value-of-role-in-billing-migration", "leading", "literal",
      "Nina Voss role in billing migration: leading", "I'm leading the billing migration."),
     [("billing-migration", "belongs-to", "brightwell", "node", "Billing migration belongs to Brightwell Labs", "")]),
    ("a commute to the office she left", True,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "value-of-commute-to-brightwell", "40 minutes by train", "literal",
      "Nina Voss commute to Brightwell: 40 minutes by train", "It's 40 minutes by train to the Brightwell office."), []),
    ("a manager named by attribute", True,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "value-of-manager-at-brightwell", "Dana Ortiz", "literal",
      "Nina Voss manager at Brightwell: Dana Ortiz", "My manager at Brightwell is Dana Ortiz."), []),
    # --- what is still true after the same endings ----------------------------------------------------------------
    ("a home that only mentions the office it was near", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "value-of-neighbourhood", "Alfama, near the Brightwell office", "literal",
      "Nina Voss neighbourhood: Alfama, near the Brightwell office",
      "We live in Alfama, near the Brightwell office, and we love it."), []),
    ("a colleague she mentors who is still there", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "mentors", "marta-kline", "node", "Nina Voss mentors Marta Kline",
      "I mentor Marta, she joined the Brightwell data team this spring."),
     [("marta-kline", "works-at", "brightwell", "node", "Marta Kline works at Brightwell Labs", "")]),
    ("writing she did about the work", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "wrote", "airflow-at-brightwell-series", "node", "Nina Voss wrote Airflow at Brightwell series",
      "I wrote a three-part blog series about Airflow at Brightwell."), []),
    ("a friend who still works there", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "friends-with", "marta-kline", "node", "Nina Voss friends with Marta Kline",
      "Marta is one of my closest friends."),
     [("marta-kline", "works-at", "brightwell", "node", "Marta Kline works at Brightwell Labs", "")]),
    ("what she learned there", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "value-of-airflow-skill-learned-at-brightwell", "intermediate", "literal",
      "Nina Voss Airflow skill learned at Brightwell: intermediate",
      "I got comfortable with Airflow at Brightwell, intermediate by now."), []),
    ("history of an earlier time", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "wrote-thesis-with", "brightwell", "node", "Nina Voss wrote thesis with Brightwell",
      "I wrote my master's thesis with the Brightwell data team years ago."), []),
    ("a degree", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "value-of-degree-before-brightwell", "statistics", "literal",
      "Nina Voss degree before Brightwell: statistics", "Before Brightwell I studied statistics."), []),
    ("a flatmate on the flat's page who is still there", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("marta-kline", "value-of-flatmate", "Nina Voss", "literal", "Marta Kline flatmate: Nina Voss",
      "Nina is my flatmate."),
     [("marta-kline", "works-at", "brightwell", "node", "Marta Kline works at Brightwell Labs", "")]),
    ("her opinion of a project of the employer", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "value-of-opinion-of-billing-migration", "well run", "literal",
      "Nina Voss opinion of billing migration: well run", "Honestly the billing migration was well run."),
     [("billing-migration", "belongs-to", "brightwell", "node", "Billing migration belongs to Brightwell Labs", "")]),
    ("a monthly lunch with the old team", False,
     ("nina-voss", "left", "brightwell", "Today was my last day at Brightwell Labs, I'm taking the winter off."),
     ("nina-voss", "value-of-lunch-with-brightwell-team", "monthly", "literal",
      "Nina Voss lunch with Brightwell team: monthly",
      "We keep a monthly lunch with the Brightwell team, whoever has left."), []),
    ("a flat's owner after moving out, a friendship", False,
     ("nina-voss", "moved out of", "calle-sol-flat", "I moved out of the Calle Sol flat on Friday."),
     ("nina-voss", "friends-with", "mr-duarte", "node", "Nina Voss friends with Mr. Duarte",
      "Mr. Duarte and I still have coffee on Sundays, he is a friend."),
     [("mr-duarte", "owns", "calle-sol-flat", "node", "Mr. Duarte owns Calle Sol flat", "")]),
    ("a lesson learned on the dropped platform", False,
     ("cartolina", "dropped", "shopify", "I dropped Shopify, the shop is on Etsy now."),
     ("cartolina", "value-of-lesson-from-shopify", "square crops sell best", "literal",
      "Cartolina lesson from Shopify: square crops sell best", "What Shopify's sales data taught me: square crops sell best."), []),
]


def build(case):
    from api.services import evidence
    from api.services.claims import Claim

    _name, _close, ending, target, around, *_ = case
    bank = Path(tempfile.mkdtemp(prefix="scope-bank-"))
    (bank / "episodes").mkdir()
    lines = {OLD_EP: [], NEW_EP: [ending[3]]}
    for _s, _p, _o, _k, _t, said in [target] + list(around):
        if said:
            lines[OLD_EP].append(said)
    for ep, day in ((OLD_EP, OLD_DAY), (NEW_EP, NEW_DAY)):
        body = "".join(f"user: {line}\n" for line in lines[ep]) or "user: (nothing relevant)\n"
        (bank / "episodes" / f"{ep}.md").write_text(
            f"---\nid: {ep}\ntimestamp: '{day}T10:00:00+00:00'\nsource: import\nprocessed: true\n---\n\n{body}",
            encoding="utf-8")

    def claim(i, spec):
        subject, predicate, obj, kind, text, said = spec
        c = Claim(id=f"c{i}", text=text, subject=subject, predicate=predicate, object=obj, object_kind=kind,
                  valid_from=OLD_DAY, source_episodes=[OLD_EP], source_trust="agent_extracted", origin="benchmark")
        if said:
            c.evidence = [evidence.verify(bank, OLD_EP, said)]
        return c

    existing: dict[str, list] = {}
    asked = claim(0, target)
    existing.setdefault(asked.subject, []).append(asked)
    for i, spec in enumerate(around, 1):
        c = claim(i, spec)
        existing.setdefault(c.subject, []).append(c)
    subject, label, thing, line = ending
    end = Claim(id="end", text=f"{subject} {label} {thing}", subject=subject, predicate=label, object=thing,
                object_kind="node", valid_from=NEW_DAY, source_episodes=[NEW_EP], source_trust="agent_extracted",
                origin="benchmark")
    end.predicate_raw = label
    end.evidence = [evidence.verify(bank, NEW_EP, line)]
    return [end], existing, bank, asked.id


def main(argv=None) -> int:
    from benchmarks.consolidation import engines

    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=20)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--key-file", default="~/.cicada/secrets.env")
    ap.add_argument("--only", default="", help="substring of the case's name (default: every case)")
    engines.add_argument(ap)
    args = ap.parse_args(argv)
    os.environ["CICADA_HOME"] = tempfile.mkdtemp(prefix="scope-home-")
    from api.services import value_alignment, value_ended

    if args.engine == "key":
        from benchmarks.engine_parity import read_key_file

        key = os.environ.get("ANTHROPIC_API_KEY") or read_key_file(Path(args.key_file))
        if not key:
            print("no ANTHROPIC_API_KEY", file=sys.stderr)
            return 2
        os.environ["ANTHROPIC_API_KEY"] = key
    engines.arm(args.engine)
    with engines.tally() as counted:
        judge = value_alignment.judge_for(engines.settings(args.engine, Path(tempfile.mkdtemp()), model=args.model, judge=args.model))
        cases = [c for c in CASES if args.only in c[0]]
        jobs = [(c, i) for c in cases for i in range(args.repeats)]

        def one(job):
            case, _i = job
            incoming, existing, bank, asked_id = build(case)
            closes, _audit = value_ended.plan(incoming, existing, judge, bank)
            return case, asked_id in {i for ids in closes.values() for i in ids}

        with ThreadPoolExecutor(8 if args.engine == "key" else 3) as pool:
            results = list(pool.map(one, jobs))
        wrong = 0
        for case in cases:
            closed = sum(1 for c, did in results if c is case and did)
            bad = (args.repeats - closed) if case[1] else closed
            wrong += bad
            print(f"{'CLOSE' if case[1] else 'STAY '}  {closed:>3}/{args.repeats} closed  {'WRONG x' + str(bad) if bad else 'ok'}  {case[0]}")
        print(f"wrong answers: {wrong} of {len(results)}")
        if args.engine == "plan":
            print(counted.report())
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
