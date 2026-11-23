# Consolidation benchmark (G148)

How well does a model consolidate? This benchmark scores **what Sleep wrote** (pages, claims, questions) instead of the
answers Ask gives. The public answer benchmarks (`benchmarks/public/`) can't separate the two: on LoCoMo, 0 of the
20 questions full context won were facts Sleep dropped. The design follows HaluMem's operation-level idea (extraction,
then updating, each scored against reference memory points; arXiv:2511.03506). The dataset is our own, and it also
checks the rules that are specific to Cicada.

## The people

Two invented people, each on a bank of their own; a leg's score is the sum over them (`--people` picks).

`fixture.json` holds Ines Varga's two months, 25 conversations:

- **Phase 1** (13 conversations, days −60 to −31): a side project, a job, a race, people, a partner's own hobby, and a
  move the person asks about and decides against.
- **Phase 2** (11 later conversations, plus one phase-1 conversation edited in place): the values that change, a
  silent edit that moves a date, a long conversation where the person takes one of the assistant's four suggestions,
  changes another and refuses two, "in two weeks", and a third Sam with no surname.

`fixture_noor.json` holds Noor Haddad's, 15 conversations, for what Ines's leave out: two **meeting transcripts** in
Hex's format, staged by the real parser (`meeting_transcripts.draft_for_file`), where only the `You` lines are hers and
every other speaker's words are theirs; a long chat with facts buried among the assistant's suggestions; **French**;
**two people called Marc** (a brother-in-law who is a carpenter, a colleague moving to Berlin) that must not share a page;
a Slack **handle** that is Léa; a month said without a day ("in March"); and five values that change.

Phase 1 is consolidated with one drain. Phase 2 is then staged on the same bank and drained again, so updates meet a
memory that already holds the old values. Days count from the run's clock. A `{day:+N}` in a turn is written out from
the conversation's own day.

## What is scored

| Check | Graded by | The question |
|---|---|---|
| facts (52) | code, then the judge | Is each fact held as a claim? A fact the spelling missed is put to the judge with every claim (`match.json`), reported apart as "judge-matched". Also reported: held anywhere on a page. |
| updates (6) | code | Is the new value current and the old one closed? Each one is *correct*, *both current*, *stale only* or *missing*. U4 is the silent edit (a revision). |
| two values kept apart (2) | code | Two real attributes of one thing said apart (a postcard's price and an A4 print's, a trip's budget and its flights) must both stay current: the counter-case to an update closing the wrong value (`apart_values` in the gold; Noor only). |
| others' words (7) | code | A suggestion the person declined or changed, a book only the assistant named, a partner's hobby, a move asked about and refused, and a third Sam are not held as the person's facts or joined to the wrong Sam. A claim that says the thing was declined is not a violation. |
| people (4) | code | A nickname and a full name, a name and a handle, end up as one page; two people called Sam stay two pages; no page holds what is said of each of two people called Marc. |
| pages (10) | code | Whoever is mentioned in 2+ conversations gets a page; a one-off mention gets none. |
| dated (3) | code | "Yesterday" and "in two weeks" are dated from the conversation, not from the day Sleep ran. |
| integrity | code | A password said in a chat reaches no page; Sleep makes no project; nothing is evergreen; the share of claims with a located span. |
| precision | one judge | Each claim against the conversations it cites: *supported*, *inferred*, *misattributed* or *unsupported*. A meeting's other speakers count as someone else, never the person. |
| the judge itself | one judge | Plausible errors planted among real claims (a date a day off, a number a little off, a page swapped for another of the same type), judged with the real claims of the same conversations (`canary.json`): how many it catches. |

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

- `--engine key` runs on the Claude key in `--key-file` (default `~/.cicada/secrets.env`, `ANTHROPIC_API_KEY` only,
  never printed or written); it spends money, and `report` prints the cost of each leg. `--engine plan` (the default)
  runs on the Claude plan.
- `--sleep-judge` is Sleep's own Stage 2 judge (default `haiku`, the product's default on both engines); `judge`'s
  `--judge-model` is the benchmark's precision judge, a different thing.
- Report columns are folder names less the repeat suffix (`key-sonnet-jhaiku`), so a folder of links to legs from
  several runs compares them side by side.
- `run` skips legs that are already done, so a stopped run resumes when given the same `--out`.
- `score OUT` re-scores the legs after a gold edit, with no model calls.
- `--parallel N` runs N people-legs at once; a key takes 4 comfortably, a plan should stay at 1.
- `compare OUT A B` sets two settings side by side: each measure's mean, `clear` when their ranges do not overlap, and
  each fact or update one setting gets in every run and the other in none.
- `judge --plant N` (default 6) plants N errors per person; `--no-match` skips the judge-matched facts.
- Keep `--clock` the same across legs that you compare; `run` sets it once for all of its legs.

**Repeats matter.** The Claude plan exposes no temperature or seed, and two Haiku runs on the same input share only
about a quarter of their exact claims (`engine_parity`, 2026-11-04). A gap between two models means something only
when it is wider than each model's own spread across repeats.

**Cost.** Each leg runs two drains over 25 conversations. The judge makes one call per group of cited
conversations, about 20 per leg. `report` prints the calls and tokens for each leg.
