# Consolidation benchmark (G148)

How well does a model consolidate? This benchmark scores **what Sleep wrote** (pages, claims, questions) instead of the
answers Ask gives. The public answer benchmarks (`benchmarks/public/`) can't separate the two: on LoCoMo, 0 of the
20 questions full context won were facts Sleep dropped. The design follows HaluMem's operation-level idea (extraction,
then updating, each scored against reference memory points; arXiv:2511.03506). The dataset is our own, and it also
checks the rules that are specific to Cicada.

## The person

`fixture.json` holds Ines Varga's two months, 25 conversations, all invented:

- **Phase 1** (13 conversations, days −60 to −31): a side project, a job, a race, people, a partner's own hobby, and a
  move the person asks about and decides against.
- **Phase 2** (11 later conversations, plus one phase-1 conversation edited in place): the values that change, a
  silent edit that moves a date, a long conversation where the person takes one of the assistant's four suggestions,
  changes another and refuses two, "in two weeks", and a third Sam with no surname.

Phase 1 is consolidated with one drain. Phase 2 is then staged on the same bank and drained again, so updates meet a
memory that already holds the old values. Days count from the run's clock. A `{day:+N}` in a turn is written out from
the conversation's own day.

## What is scored

| Check | Graded by | The question |
|---|---|---|
| facts (34) | code | Is each fact held as a claim? Also reported: held anywhere on a page. |
| updates (6) | code | Is the new value current and the old one closed? Each one is *correct*, *both current*, *stale only* or *missing*. U4 is the silent edit (a revision). |
| others' words (7) | code | A suggestion the person declined or changed, a book only the assistant named, a partner's hobby, a move asked about and refused, and a third Sam are not held as the person's facts or joined to the wrong Sam. A claim that says the thing was declined is not a violation. |
| people (2) | code | A nickname and a full name end up as one page; two people called Sam stay two pages. |
| pages (10) | code | Whoever is mentioned in 2+ conversations gets a page; a one-off mention gets none. |
| dated (3) | code | "Yesterday" and "in two weeks" are dated from the conversation, not from the day Sleep ran. |
| integrity | code | A password said in a chat reaches no page; Sleep makes no project; nothing is evergreen; the share of claims with a located span. |
| precision | one judge | Each claim against the conversations it cites: *supported*, *inferred*, *misattributed* or *unsupported*. |

Matching is by spelling, with accents folded and hyphens read as spaces, so it can be fooled. `score.json` lists the
claims each check matched: read them before quoting a number.

## Running it

Every leg is one model on a fresh scratch bank and home, in its own process (`engine_parity`'s isolation). It never
reads the person's bank or home. The models run on the Claude plan that this machine's `claude` is signed in to.

```sh
api/.venv/bin/python -m benchmarks.consolidation.run run --models opus,sonnet,haiku --repeats 2 --out OUT
api/.venv/bin/python -m benchmarks.consolidation.run judge OUT --judge-model opus
api/.venv/bin/python -m benchmarks.consolidation.run report OUT
```

- `run` skips legs that are already done, so a stopped run resumes when given the same `--out`.
- `score OUT` re-scores the legs after a gold edit, with no model calls.
- Keep `--clock` the same across legs that you compare; `run` sets it once for all of its legs.

**Repeats matter.** The Claude plan exposes no temperature or seed, and two Haiku runs on the same input share only
about a quarter of their exact claims (`engine_parity`, 2026-11-04). A gap between two models means something only
when it is wider than each model's own spread across repeats.

**Cost.** Each leg runs two drains over 25 conversations. The judge makes one call per group of cited
conversations, about 20 per leg. `report` prints the calls and tokens for each leg.
