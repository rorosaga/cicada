# Consolidation benchmark (G148)

How well does a model consolidate? This benchmark scores **what Sleep wrote** (pages, claims, questions) instead of the
answers Ask gives. The public answer benchmarks (`benchmarks/public/`) can't separate the two: on LoCoMo, 0 of the
20 questions full context won were facts Sleep dropped. The design follows HaluMem's operation-level idea (extraction,
then updating, each scored against reference memory points; arXiv:2511.03506). The dataset is our own, and it also
checks the rules that are specific to Cicada.

## The people

Two invented people, each on a bank of their own; a leg's score is the sum over them (`--people` picks).

`fixture.json` holds Ines Varga's two months, 26 conversations:

- **Phase 1** (13 conversations, days −60 to −31): a side project, a job, a race, people, a partner's own hobby, and a
  move the person asks about and decides against.
- **Phase 2** (12 later conversations, plus one phase-1 conversation edited in place): the values that change, a
  silent edit that moves a date, a long conversation where the person takes one of the assistant's four suggestions,
  changes another and refuses two, "in two weeks", and a third Sam with no surname.

`fixture_noor.json` holds Noor Haddad's, 18 conversations, for what Ines's leave out: two **meeting transcripts** in
Hex's format, staged by the real parser (`meeting_transcripts.draft_for_file`), where only the `You` lines are hers and
every other speaker's words are theirs; a long chat with facts buried among the assistant's suggestions; **French**;
**two people called Marc** (a brother-in-law who is a carpenter, a colleague moving to Berlin) that must not share a page;
a Slack **handle** that is Léa; a month said without a day ("in March"); and six values that change.

Phase 1 is consolidated with one drain. Phase 2 is then staged on the same bank and drained again, so updates meet a
memory that already holds the old values. Days count from the run's clock. A `{day:+N}` in a turn is written out from
the conversation's own day.

## What is scored

| Check | Graded by | The question |
|---|---|---|
| facts (52) | code, then the judge | Is each fact held as a claim (on a page)? A fact whose claim waits under a one-off name below the promotion bar (`pending_entities.jsonl` `held_claims`) is reported apart as `points_held`: a claim, not prose, just not on a page yet. A fact the spelling missed is put to the judge with every claim (`match.json`), reported apart as "judge-matched". Also reported: held anywhere on a page. |
| updates (13) | code | Is the new value current and the old one closed? An update marked `on_owner` (U1) counts only claims on the owner's own page or about it, never a colleague's "works at <the same employer>". Each one is *correct*, *both current*, *stale only* or *missing*. U4 is the silent edit (a revision). |
| two values kept apart (2) | code | Two real attributes of one thing said apart (a postcard's price and an A4 print's, a trip's budget and its flights) must both stay current: the counter-case to an update closing the wrong value (`apart_values` in the gold; Noor only). |
| others' words (7) | code | A suggestion the person declined or changed, a book only the assistant named, a partner's hobby, a move asked about and refused, and a third Sam are not held as the person's facts or joined to the wrong Sam. A claim that says the thing was declined is not a violation. |
| a role reads true (2) | code | A role someone holds to the person ("my brother-in-law Marc", "my landlord") must read true as the claim is written: never the person as the holder ("<person> brother-in-law of Marc"), never the holder as having it (`roles` in the gold). |
| people (4) | code | A nickname and a full name, a name and a handle, end up as one page; two people called Sam stay two pages; no page holds what is said of each of two people called Marc. |
| pages (10) | code | Whoever is mentioned in 2+ conversations gets a page; a one-off mention gets none. |
| dated (3) | code | "Yesterday" and "in two weeks" are dated from the conversation, not from the day Sleep ran. The day counts on a claim on a page or on one held under a waiting name (a one-off thing named once waits below the promotion bar by design); `dated_held` counts the ones only a held claim carries (2026-11-25). |
| fading (11 + 3, and a probe) | code | Does the right thing fade? The people and things the person keeps coming back to are not under the question line at the clock (`keeps`); the job they hold stands above the job they left, and a person in several recent conversations above a place named once (`outranks`). Then the finished bank is copied, the clock moved forward and only Sleep's decay step run (no model, a pass a week): after six weeks of silence the partner, the sister and the employer must not be under the question line (`lasting`), and a one-off that is over or a place named once should be (`ended`). The gold names roles, never a number (`gold["fading"]`, `fading.py`). |
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

**Cost.** Each leg runs two drains over 26 conversations. The judge makes one call per group of cited
conversations, about 20 per leg. `report` prints the calls and tokens for each leg.

**Every replay battery runs on the Claude plan too (2026-11-24).** Almost everything above was first measured on a key,
and a new user's default engine is the signed-in plan (`claude -p`), where a judge was once forced into another judge's
answer shape on every call and nobody saw it. Each battery below takes `--engine key|plan` (`engines.py`; default `key`,
unchanged; `full_name_battery` and `full_name_replay` keep their older default, the plan). `--engine plan` reads no key file,
removes any `ANTHROPIC_API_KEY` from the process, builds the plan's settings with the same tiers (Sonnet main, Haiku small
judge) and prints, per stage label, the calls, the ones that raised and the replies that were not a JSON object, with the
keys of the objects it saw (a judge answered in another judge's shape shows as an unusual key set). A plan call costs
plan usage, not money: keep the repeat count small (`value_join_battery --every K` runs every K-th pair). The key
numbers a docstring or the G148 row quotes do not compare with a plan run of three repeats unless the difference is
larger than the spread.

**The same-name rule has two replays of its own** (a run makes about six judge calls and one same-name pair, so it
cannot see a one-in-ten defect; both cost cents and need only `ANTHROPIC_API_KEY`):

- `same_name_battery.py`: 71 labelled single judge inputs (46 one person, 25 two), each replayed N times through the real
  `same_name_people.plan`. Scored as a false split (one person cut in two) or a missed split (two kept as one).
- `dropped_battery.py` (with `dropped_cases.json`, 28 invented conversations plus the benchmark's own book conversation):
  a fact the person says in passing inside a conversation about something else (a book finished, a film, a trip, a course,
  a purchase, a race, a doctor's visit, a decision; English, Spanish, French; and counter-cases that must not become the
  person's act), replayed N times through the real `entity_extractor.extract`, scored as claim / status / prose / dropped
  and, for counter-cases, written as the person's act. `rescore OUT` judges saved answers with no model.
- `same_name_stories.py`: 30 invented stories (English, Spanish, French) of a name that comes up over several batches:
  two people both new in one batch, one established first, a page that already holds two, two that nothing tells
  apart, a doubt a later conversation settles, one person in many settings, one whose life moves on, one with a thin
  first mention, one established page re-read. Each replay plays the batches through `plan`, applies the decisions to a
  small simulated bank as the resolver and `same_name_tend` do, runs the end-of-drain review, and scores wrong joins,
  wrong splits, questions asked and whether the end state is what the story expects. `--module OLD.py` replays the code
  before a change (the stories' baseline). Each batch is a night: the review runs after it, on the pairs and pages
  that batch flagged and no others, as the product does (2026-11-24; reviewing every doubt hid a pair nothing flagged).
- `same_name_e2e.py`: one small story through **the real Sleep** on a scratch bank (the stager, Stage 1's own
  descriptions, the store, the tail, git), about $0.20 a run. The stories above are a simulated bank and twice hid a
  defect only the real path has; run this before landing a change to who a mention belongs to. Its fixture
  (`same_name_e2e_join.json`) is a doubt a later conversation links, beside a pair nothing links and one person whose
  life moves on; `expect` names the first names that must end as one page and as two.

## The saves battery (G245, ruling 80's plan, Track M)

`saves_fixture.py` and `saves_battery.py` measure what reading a save costs and what it writes, before anything reads one
on purpose (the owner, 2026-11-24: "if i save it already has a reason"; every save will be read, as the page's and the
author's words, never his). The bank is invented: an owner called Alex Example, four seeded pages (a friend "Sam Example",
a colleague "Riley Example", an employer "Helio Example", a notes app "Quillnote") standing on two older conversations each,
eight waiting conversations, and **288 saves** written by the production capture writers (`media_ingestor.write_prepared` with
a stand-in page description in place of the fetch, `tab_groups.sync`), so each is stored as dev stores it. The saves are natural
English with `example.com` links, grouped by the trap each one sets: 50 posts that each state one fact about the one existing
page; six posts on one topic by different authors; an author whose name equals a person page; a stranger's "Sam" while a friend
"Sam Example" has a page; first names with no page; a post about an existing company and a 2021 post stating a present-tense
fact; posts saying "I", "my" and "the user"; three title-only bookmarks; the same link on two lists; two tab groups; two feed
items; two open Safari tabs; two saves with his own reason; two 40-day-old bookmarks; four connector tweets (two in today's shape,
the text in `note`, two in the shape the plan gives them, the text as the description); and a bulk list of 200 undated rows.

**Since ruling 80's switch (G246, Track 1) the `single` leg runs the real path**, not a `wake` shortcut: capture writes the saves as
it now does (a save made singly waits for tonight; the 200 list rows are a bulk door, `bulk=True`, and wait their turn in the
pile; a 40-day-old bookmark arrives late; a video's title and link has nothing to read) and Sleep's own first step releases the day's
number (`history_index.take_turns`). The `baseline` leg sets `history_index.SAVES_READ = False`, which is dev before the switch.
The waiting gate now reads the bulk list's saves waiting right after the list was read, against `history_index.SAVES_PER_DAY`.

    api/.venv/bin/python -m benchmarks.consolidation.saves_battery selfcheck           # no model: fixture, capture, a stand-in Sleep
    api/.venv/bin/python -m benchmarks.consolidation.saves_battery run --leg baseline --out OUT/baseline
    api/.venv/bin/python -m benchmarks.consolidation.saves_battery run --leg single   --out OUT/single1
    api/.venv/bin/python -m benchmarks.consolidation.saves_battery report OUT/baseline OUT/single1 OUT/single2
    api/.venv/bin/python -m benchmarks.consolidation.saves_battery rescore OUT/single1  # measure again, no model

**Isolation** is the verify-cicada skill's: scratch `HOME`, `CICADA_HOME`, bank and ledger, capture, recall and every fetch off,
and the engine's `claude` is the skill's `plan-claude` shim (the real HOME for that one child, the pinned argv, one model,
`haiku`). It reads nothing of anyone's. Only the web-lookup steps are off (`web_check_per_run`, `web_context_per_run` 0): the shim
lets one model through and a search is not what is measured.

**Legs.** *baseline*: dev as it is: the index reads bookmarks, list rows, tab groups and open tabs at capture; Sleep reads what dev
reads today (the saves with a reason, a feed item, a connector tweet whose text rides `note`). *single*: the same bank, then every save the index read is
woken with `history_index.wake`, the function a mention calls (`read_asked` stamped, `processed` false), except the 200 list rows,
which stay in the pile (`--wake-bulk` wakes them: about 200 more reads). Sleep then reads each save once, alone, with **today's**
reading. That proves what a model call per save costs, and what today's Stage 1 writes from a save: the gate failures are the work
of the content tracks (2a to 2c), not a verdict on the plan. It does not prove the reading ruling 80 will build (no saved-item
note, no `external:` observer, no owner guard, no caps exist yet), and it does not prove pacing (the day's allowance, class order,
the pile): every woken save waits at once, and the "waiting saves after the bulk list" count is taken on a copy with all 287 woken.
`read_asked` is read by nothing in Stage 1, so a woken save is read exactly as one that simply waits will be. *grouped*: a stub: it
needs Track 3 (`feat/grouped-save-read`) and says so.

**What it counts** (`battery.json`, `report`): calls, gross input, cache and **output tokens by stage** from the scratch ledger
(`benchmarks/perf/ledger.py`), and the marginal cost of a save (single minus baseline, over the extra saves read); pages made and
whether each is quiet; claims by observer; open save-derived claims per page; claims on the owner's page (split into "saved X"
acts and what a post says); claims on seeded person pages without the exact name; located evidence against `reasoning`; held names
per 100 saves; questions with only a save behind them; the 2021 fact written as current; the decay status of pages born from old
saves; waiting saves if all were woken; and ruling 62's retrieval cases (12 messages: the saved lookup by words, and the hook's
note; the meaning cases are not run, the search model is not loaded). A claim "from a save with no words of his" is any claim citing a save outside the
`own-reason` group. Twelve gates read these counts (`saves_battery.gates`, one of them, the grouped read's, not run); they are counts, never a score.

**Baseline numbers (2026-11-24, haiku, the Claude plan; claude-haiku-5-5 in the ledger).** One run of the baseline, two of the
single leg. Two runs of a small model share few exact claims, so read ranges.

- *Baseline*: 14 episodes read (8 conversations, 6 saves): 43 calls, 209k input tokens gross (124k from the prompt cache), 36.7k output
  tokens, 113 s. Nothing else is read: 281 saves stay indexed. Stage 1 alone: 14 calls, 10.5k input and 1.36k output tokens a call.
- *Single read*: 95 episodes (8 conversations, 87 saves): 203 and 218 calls, 1.27M and 1.31M input tokens gross (988k and 1.03M from the cache),
  **186k and 182k output tokens**, 573 s and 582 s. **A save costs, on top of the baseline, 2.0 to 2.2 calls, 13.1k to 13.6k input tokens gross
  (10.7k to 11.2k of them cache reads) and 1.79k to 1.84k output tokens**, by stage (two runs): extraction 1.00 call, 10.5k in, 0.98k to 1.04k out;
  merge 0.27 to 0.35 calls, 0.28k to 0.29k out; fact fold 0.16 to 0.20 calls, 0.22k to 0.27k out; disambiguation 0.36 to 0.46 calls,
  0.15k to 0.19k out; conflict, value match, skills and "in short" together about 0.2 calls and 0.1k out. Output is about 14 percent of the gross input tokens and, priced as the plan estimates (3.6: 70 to 85 percent of the
  dollars), most of the cost; the plan's own guess was 2 calls, 10.8k input and 2k output a save, close on calls (2.0 to 2.2 against 2.25) and output (1.8k against 2k), a quarter higher on input (13.4k against 10.8k).
  Extraction writes 1,083 and 1,039 output tokens a call in the two runs (the baseline's 1.36k is its longer conversations).
- *The baseline fails* (as the plan expects): claims on the owner's page from a save with no words of his (5: four from the two connector tweets in
  today's shape, one from a feed item; the two in the fixed shape and the indexed bookmarks put none), claims that are not `external:` (5),
  waiting saves after the bulk list (287 against a day's 25, counted if all were woken). It passes the rest: no pages from saves, 12/12 retrieval
  by words and 11/12 by the hook (the hook never brings up a list row, and a feed item has no page). The 2021 gate cannot fail on it (Sleep read
  none of the posts that carry it).
- *Single read fails* (today's reading, both runs): 10 and 11 claims on the owner's page that are not "saved X" (a stranger's "my day starts at four" as
  Alex's `daily start time`, "friend of Sam", "joined the logistics team", tab groups read as his plans), plus 33 and 32 "saved X" acts; 8 pages made from
  saves alone, all quiet (a page for each post author and one called `sam`, never joined to the friend page: that is the stranger-Sam case); 103 and 104 claims on saves
  alone, none `external:` (every one observer `agent`); **31 to 36 open save-derived claims on the one page 50 posts name** (the cap is 12); 28.7 and 29.9 held names per 100
  saves read (under 250, so the entity cap stays 8); one question with only a save behind it (at most 2 allowed); the 2021 fact written as current
  **in one run of two** (CEO, 40 employees, Porto, all `valid_from` the day Sleep ran, because today's note dates a save the day it was taken in); retrieval after
  Sleep one tab group short of before (a read tab group leaves the lookup: plan 0.11). Zero claims or aliases land on the friend "Sam Example" without his
  exact name, in both runs. Located evidence: 93 to 95 percent of spans on a save-derived claim are located, the rest `reasoning`.
- *Not measured*: grouped reads; the meaning cases of ruling 62; the plan's pacing and class order; dollars (the plan has no price; the ledger says subscription).
  A second baseline run was not made. Tab groups and the open tab are read as the owner's tabs: counted, not judged wrong.

