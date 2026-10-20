# Memory benchmarks: which ones fit Cicada, and a harness that runs them on the plan

**Date:** 2026-10-17 · **Row:** [G148](../goals/memory-evolution.md#g148) · **Status:** research + implementation
(`benchmarks/public/`, `benchmarks/answer_eval.py`) + a first small slice, reported below.

**Why this exists.** Rodrigo 2026-10-17: *"I was also thinking whether we can do a benchmark for this. Maybe that
could help to see if answers are actually good. If you can look into what Super Memory or other companies' memory
benchmarks exist out there that we could use, maybe that can be research and also implementation. We can do
everything with my Claude plan."* The retrieval A/B of 2026-10-16 (MRR 0.786, R@1 0.667, R@10 0.967 over 60
auto-built queries on the owner's bank) shows the right **page** is found; it does not show the **answer** is right.
This note picks the public benchmarks that test answers, maps Cicada's design onto each, and documents the harness
that runs them end to end — capture → Sleep → `cicada_ask` → the benchmark's own judge — on throwaway banks and the
person's Claude plan.

It builds on [the 2026-09-24 note](2026-09-24-memory-benchmarks-and-implicit-recall.md) (MemoryBench read at source,
the ten pitfalls, the hooks-vs-tools question) and does not repeat it; what changed since is marked.

---

## Short answer

1. **Run LoCoMo first, with Mem0's "J" judge.** One conversation is one bank (Cicada's own model: a bank is a
   life), 19–32 dated sessions between two people, ~150 scorable questions per conversation. It is the number
   Mem0, Zep, Letta and most 2025–26 papers report, the conversations are short enough that a full-context control
   is cheap, and a conversation costs one Sleep. Its weaknesses are known and are reported beside every number
   (below).
2. **Run LongMemEval second, sliced by question type.** It is the benchmark that tests what Cicada is built
   around — knowledge updates, temporal reasoning, abstention, multi-session — but every question ships its own
   ~115k-token haystack (~48 sessions, ~490k characters, counted), so with Sleep it costs one full consolidation
   *per question*. The `oracle` variant (only the evidence sessions, ~1.9 sessions a question) is the cheap way to
   measure consolidation + answering per type; `S` is for a targeted slice.
3. **Do not adopt MemoryBench, BEAM or PersonaMem as the harness or first dataset** — reasons per row below.
4. **For "are the answers good on *my* life", the public sets are a proxy.** `benchmarks/answer_eval.py` grades
   Cicada's answers on the owner's own bank against facts the owner writes down (expected / forbidden / should
   abstain), on the plan. That is the number that answers the owner's question; the public ones make it comparable.

---

## The survey

Scores are as published by their authors unless marked; "reader" is the answering model. Vendor numbers on the
same dataset routinely disagree by 10–30 points because reader, judge, prompt, category filter and harness all
differ — the 2026 reproduction work (Redis, Penfield) makes that the main finding, not a caveat.

| Benchmark | Measures | Size | Licence | Judged by | Published scores (selected) | Fit for Cicada | Cost of a run on the plan |
|---|---|---|---|---|---|---|---|
| **LoCoMo** (Maharana et al., ACL 2024; `snap-research/locomo`) | QA over very long two-person conversations: single-hop, multi-hop, temporal, open-domain, adversarial | 10 conversations, 19–32 sessions each (~44–90k characters), 1,986 QA (282/321/96/841/446 for categories 1–5) | **CC BY-NC 4.0** | Originally token F1; since Mem0 (2025) an LLM "J" judge (CORRECT/WRONG, generous), categories 1–4 only | Mem0 paper (gpt-4o-mini reader): Mem0 66.9, Mem0g 68.4, Zep 66.0, LangMem 58.1, OpenAI memory 52.9, **full-context 72.9**. Zep's re-run of itself: 75.1. Letta's filesystem agent: 74.0. 2026 vendor claims run 90–95 with newer readers. | **Best fit.** A conversation is a life-sized bank; sessions are dated; questions span people and time. Categories map onto Cicada's claim layer (single-hop facts, temporal claims, multi-hop via the graph). | One Sleep per conversation (≈ one extraction call per session plus resolution) + 2 calls per question (answer, judge). Full set: 10 Sleeps + ~3,000 calls. |
| **LongMemEval** (Wu et al., ICLR 2025; `xiaowu0162/LongMemEval`, cleaned set on HF) | User–assistant chat memory: information extraction (single-session user/assistant/preference), multi-session reasoning, temporal reasoning, knowledge updates, abstention | 500 questions (133 temporal, 133 multi-session, 78 knowledge-update, 70 ss-user, 56 ss-assistant, 30 preference; 30 abstention) — `S`: ~48 sessions / ~115k tokens per question; `M`: ~500 sessions; `oracle`: evidence sessions only (~1.9) | **MIT** | GPT-4o, one yes/no prompt per type (>97% agreement with humans, per the paper) | Paper, GPT-4o reader: oracle 87.0, `S` full-context 60.6. Zep paper: 63.8 (gpt-4o-mini) / 71.2 (gpt-4o) vs full-context 55.4 / 60.2. Redis' Sept-2026 reproduction on a common GPT-4o backbone: 77–86 for current systems, and published figures off by +3 to −28 points. | **Closest to Cicada's purpose** (knowledge update = supersession; temporal = bi-temporal claims; abstention = gaps). Mismatch: the haystack is a pile of unrelated chats, built for retrieval, and a question is a unit — no shared life across questions. | `oracle`: ~2 sessions of Sleep + 2 calls per question. `S`: ~48 sessions of Sleep per question — the 500 set is ~24k sessions of extraction. Slice it. |
| **MemoryBench** (Supermemory, `supermemoryai/memorybench`, MIT) | A *harness*, not a dataset: runs LoCoMo, LongMemEval and ConvoMem against providers (Supermemory, Mem0, Zep) through ingest → search → answer → judge; reports "MemScore" (accuracy / latency / context tokens, kept apart) | — | MIT | Configurable LLM judge (GPT-4o default; Claude or Gemini possible) | The README ships no results. The relayed figures (Supermemory 85.9 vs "RAG" 58.3 vs "filesystem" 54.2) are not reproducible from the repo (2026-09-24 note). | The method is sound and its MemScore idea is kept here (accuracy always beside latency and calls). As the harness: TypeScript/Bun, providers are HTTP services, per-question containers re-ingest a LoCoMo conversation once per question, the judge wants an API key, and its LoCoMo loader grades 444 adversarial items against `"undefined"` and swaps categories 2/3. | Per-question re-ingest multiplies Sleep by ~150 on LoCoMo. Not on the plan without an adapter. |
| **Mem0's evaluation** (arXiv:2504.19413) and **the Zep dispute** | LoCoMo J + latency + tokens | — | — | Mem0's J prompt (appendix A; reproduced verbatim in `benchmarks/public/judges.py`) | as above | The J prompt is the de-facto LoCoMo judge, so this harness uses it. The dispute is the cautionary tale: Zep (blog, May 2025) says Mem0 mis-ran Zep (timestamps as text, both speakers as "user", sequential search) and that **full-context beats Mem0** on LoCoMo; Mem0's own table shows the same. | — |
| **LoCoMo audit** (Penfield Labs, 2026-04-08) | The benchmark itself | — | — | — | 99 score-corrupting answer-key errors in 1,540 questions (6.4%); the gpt-4o-mini J judge accepted **62.8%** of deliberately wrong but on-topic answers (caught ~89% of specific factual errors). | Means LoCoMo J differences under ~5 points are noise, and J flatters vague answers. This harness reports LoCoMo's token F1 beside J for exactly that reason, and the owner-question runner uses fact-level grading. | — |
| **BEAM** (Tavakoli et al., ICLR 2026, arXiv:2510.27246; HF `Mohammadta/BEAM`) | Long-term memory at 100K → 10M tokens; ten abilities including contradiction resolution, event ordering, knowledge update, abstention | 100 conversations, 2,000 validated questions | **CC BY-SA 4.0** | LLM judge with rubrics | Mem0 claims 64.1 (1M) and 48.6 (10M) — vendor figures. | Tests scale Cicada does not have yet (a 10M-token life). Good later, when the question is "does Sleep hold at years of capture". | 1M-token conversations through Sleep: thousands of extraction calls each. Out of plan budget for now. |
| **PersonaMem** (Jiang et al., 2025, arXiv:2504.14225) | Whether a model tracks an evolving user profile and responds in a personalised way | 180+ simulated user histories, up to 60 sessions / ~1M tokens | not verified | **Multiple choice** (4 options) — no judge | Frontier models (GPT-4.1, GPT-4.5, o4-mini, Gemini-2.0) ≈ 50% (chance 25%) | Personalisation, not recall of facts: its in-situ queries ask which *response* fits the person. Interesting for G112 (skills/how this person works), not for "is the answer right". | Large; MC answers are cheap to grade. |
| **MemBench** (Tan et al., ACL Findings 2025, arXiv:2506.21605) | Factual vs reflective memory, in participation vs observation scenarios; accuracy, memory-operation efficiency, capacity | — (not counted here) | no licence detected on the GitHub repo | Accuracy on generated QA | — | Observation mode is close to Cicada (it watches, it does not take part), but the data is synthetic per-agent traces and the metrics target an agent's memory operations, which Cicada does in batch. | — |
| **ConvoMem** (Salesforce, arXiv:2511.10523; HF `Salesforce/ConvoMem`) | User facts, assistant facts, preferences, changing facts, implicit connections, abstention | 75,336 QA | **CC BY-NC 4.0** | LLM judge | Full context 70–82% vs Mem0 30–45% under ~150 conversations | Its point is the control: **below ~150 conversations, pasting everything in beats retrieval.** A Cicada number without a full-context row means nothing at personal scale. | Small per item; the set is huge. |
| **MemoryAgentBench** (Hu, Wang, McAuley, ICLR 2026, arXiv:2507.05257) | Accurate retrieval, test-time learning, long-range understanding, selective forgetting / conflict resolution, over incremental multi-turn input | Repurposed long-context sets + EventQA, FactConsolidation | not verified | Per-task metrics | Current methods fall short on all four | FactConsolidation (later facts override earlier) is a clean knowledge-update probe; worth a slice later. | — |
| **Letta** (blog, 2025-08-12) | Not a dataset: an agent with `grep`/open/close over the raw LoCoMo history in files reached **74.0** with gpt-4o-mini | — | — | Mem0's J | 74.0 | The strongest argument for the full-context / filesystem control: a memory system has to beat "the files and a grep". | — |

**Not verified here:** PersonaMem's and MemoryAgentBench's licences; MemBench's dataset size; any vendor 2026
claim above 90 on LoCoMo or LongMemEval (vendor blogs, no reproduction); the exact reader/judge behind Zep's 75.1.

---

## How Cicada's design maps onto each

| Cicada mechanism | What it predicts on the benchmarks | Where it shows |
|---|---|---|
| **Episodic → consolidated graph.** Sessions are episodes; Sleep extracts entities and typed claims with evidence spans; `cicada_ask` reads **pages and claims, never raw episodes**. | A fact must survive extraction *and* promotion to be answerable. Single-hop details said once can be lost to extraction recall; the full-context control has no such loss. | LoCoMo single-hop vs full-context; LongMemEval single-session-user/assistant. |
| **Entity promotion** (2+ conversations, >3 exchanges with the person's words, or a link) and the **pending store**. | A name mentioned once in one short session may stay in `pending_entities.jsonl`; Ask does not read it. | LoCoMo single-hop/open-domain misses where the answer entity has no page (the run records pending lines per bank). |
| **Bi-temporal claims, supersession** (`valid_from`/`valid_to`, newest evidence wins). | Knowledge-update questions should be a strength: the old value is closed, not deleted. | LongMemEval knowledge-update; LoCoMo temporal. |
| **"Nothing relative is stored"** — Stage 1 resolves "yesterday" against the episode's own date. | Temporal questions ("when did X…") depend on that resolution being right on the session day. | LoCoMo temporal (gold answers are absolute dates). |
| **Temporal decay** (one-offs may archive by age; 2+ dated conversations floor at 0.39). | On a dataset replayed in one drain, decay is charged from each session's date to the run's clock (the last session). A one-off from months earlier can archive. Confidence does not rank recall, but an archived page's place in retrieval should be checked. | Visible as page status counts per bank (`state.json`). |
| **Provenance and gaps** — Ask cites entities/claims and names what it does not know. | Abstention should be honest (LongMemEval abstention, LoCoMo adversarial); a gap answer costs J on answerable questions. | Abstention rows; the run counts uncited answers. |
| **Speaker attribution** (G179: the other side's words are `speaker:<name>:` lines, claims `external:<name>`). | LoCoMo is two people: speaker A is the bank's owner, B a correspondent. Zep's critique of Mem0 (both speakers as "user") is avoided by construction. | LoCoMo questions about speaker B. |

---

## The recommendation, and why

**LoCoMo with the J judge as the headline, token F1 beside it, full-context as the control, adversarial apart.**
It is the only dataset where (a) the unit matches Cicada's bank, (b) the published numbers use one judge prompt we
can copy verbatim, (c) a full run fits a plan (10 Sleeps), and (d) the full-context baseline is published (72.9) so
"does consolidation lose information" has a reference. Its problems (6.4% bad gold answers, a lenient judge,
conversations that fit in context) are why the control row and F1 ride beside every number and why differences
under ~5 points are read as ties.

**LongMemEval by type, oracle first.** The oracle variant isolates Cicada's consolidation + answer on exactly the
abilities it is designed for (knowledge update, temporal, abstention) at ~2 sessions of Sleep a question, against
the paper's GPT-4o oracle 87.0. `S` is run as a targeted slice when retrieval inside a large bank is the question.

**Everything on the plan.** Sleep, the answer and the judge are all `claude -p` through Cicada's own plan engine.
The judge model therefore differs from the papers' (gpt-4o-mini / gpt-4o); the report names it on every line and
the comparison with published numbers is indicative. The pitfall the 2026-09-24 note ranked first — self-grading —
is reduced by keeping the judge prompts verbatim and the judge a separate call that sees only question, gold and
answer; a stronger judge than the reader can be pinned (`--judge-model opus`).

---

## The implementation

### `benchmarks/public/` — LoCoMo / LongMemEval end to end

```sh
api/.venv/bin/python -m benchmarks.public.run prepare --cache <folder> --dataset locomo [--embedding small|gemma2]
api/.venv/bin/python -m benchmarks.public.run run --cache <folder> --dataset locomo --units 1 --per-category 10 \
    [--paths ask,full-context] [--sleep-model sonnet --answer-model sonnet --judge-model sonnet]
api/.venv/bin/python -m benchmarks.public.run run --cache <folder> --resume <run folder>     # continue
api/.venv/bin/python -m benchmarks.public.run report --run <run folder>
```

- **Pinned data** (`datasets.py`): each file from one commit/revision, sha256-checked; `prepare` is the only
  network step (dataset + the on-device search model into the benchmark home, through the repo's own fetchers).
- **Isolation** (`run.py`): every unit gets a marked throwaway bank under the run folder and a child process whose
  environment is an allowlist — `HOME`/`CICADA_HOME` the benchmark home, `CICADA_MEMORY_PATH` the unit's bank,
  capture, telemetry and every fetch gate off, no provider keys, `HF_HUB_OFFLINE`. The person's bank, `~/.cicada`
  and `api/.env` are never read: the child turns off the settings file (`api.settings_file.disable()`, `api.config.disable_dotenv()`) before any service import, so the `get_settings()` calls inside Ask and the embedder see its allowlisted environment alone and a score never depends on whose checkout ran it (the gemma2 fetch in `prepare` does the same). `--cache` may not overlap the home folder, `~/.cicada`, `~/cicada` or the repo.
- **The plan** (`unit.py`): `CICADA_LLM_MODE=agent`, so every call is Cicada's own `claude -p` (`--safe-mode`, no
  tools, no settings, no session persistence, `CICADA_CAPTURE=off`). The CLI's sign-in lives under the person's
  real home, so `claude` children — and only they — get `HOME=<--claude-home>` (default: the user's home); Cicada
  itself never sees that folder. A wrapper refuses any other engine, so nothing can fall back to a metered API.
- **Production paths:** sessions → `episode_staging.stage` (dated with each session's own day; LoCoMo speaker A is
  the owner, B a `speaker:` correspondent with its `correspondent` record; LongMemEval user/assistant); Sleep →
  `sleep_cycle.run(drain=True)`; answer → `ask_service.answer_query` (`cicada_ask`'s body). The control path
  `full-context` gives the same answer prompt the whole raw history instead.
- **The clock:** `benchmarks.system.runtime.Runtime.frozen` (the system benchmark's) runs intake, Sleep and Ask on
  the dataset's day — LoCoMo: an hour after the last session; LongMemEval: the question date — so decay, expiry and
  "CURRENT LOCAL DAY" are the dataset's, not 2026's. `--sleep-schedule per-session` drains after each session on
  that session's day (the nightly rhythm) instead of once.
- **Judges** (`judges.py`): Mem0's J prompt and LongMemEval's per-type prompts, verbatim; LoCoMo's token F1 rules
  (category 1 multi-answer, category 3 first-of-`;`); LoCoMo category 5 off by default and, when on, scored apart
  with LongMemEval's abstention prompt. Category numbers map as LoCoMo's own scorer treats them
  (1 multi-hop, 2 temporal, 3 open-domain, 4 single-hop, 5 adversarial).
- **Resumable:** per-unit `state.json` (Sleep legs), `answers.jsonl`, `judgments.jsonl`; a plan limit pauses Sleep
  (exit 3), any other resumable stop (engine signed out, bank busy) exits 4 with its reason, a Sleep failure exits 1;
  `--resume` continues the paused drain and retries exactly the answers and judgments that failed (finished ones are
  never redone). `--sleep-schedule none` stages and indexes a unit without Sleep (Ask over the conversations'
  search leg alone — how LongMemEval_S fits a plan); `--gate <command>` runs a command before each unit and starts it
  only on exit 0 (a run waits out another Sleep sharing the plan). Every `ask` row keeps the prompt's size, the
  context-build time before the model call and whether the dataset's own answer turns reached the prompt verbatim (any
  40-character stretch; `prompts.jsonl` beside it), and the report prints them (2026-10-20). The report counts unanswered and ungraded questions and gives the score with them as not correct. Slices are
  deterministic (first N per category / per unit). `--questions <fixture>` asks only a fixture's questions, in its
  wording, every category it lists (`benchmarks/public/fixtures/locomo-es.json`: 50 LoCoMo questions in Spanish,
  10 of them adversarial; `--questions-lang en` asks the same questions in English) — pinned like the other settings.
- **Cost, measured:** every plan call is counted by phase (sleep / answer / judge) and stage with its wall seconds;
  `report.json` and the printed table carry them beside the scores. No dollar figure — a plan call has no price.
- **Tested offline:** `api/tests/test_public_benchmark.py` runs a synthetic LoCoMo-shaped conversation through the
  whole harness with the system benchmark's deterministic engine below the provider seam (no network), plus the
  loaders, judges, F1, report and environment allowlist.

### `benchmarks/answer_eval.py` — the owner's own questions

```sh
cp benchmarks/answer_eval.example.yaml benchmarks/answer_eval.local.yaml     # gitignored; write your questions
api/.venv/bin/python -m benchmarks.answer_eval --bank <bank folder> --questions benchmarks/answer_eval.local.yaml
```

Per question: `expect` (facts a right answer states), `forbid` (stale values it must not assert as current),
`abstain` (memory should not know), `tags`. Answers come from `ask_service.answer_query` on the named bank (as
`cicada ask` does, in-process); one judge call per question returns a verdict per fact. Scores: strict correctness,
fact recall, contradictions, stale facts asserted, declined-but-should-know, answered-but-should-decline, per tag.
Both calls on the plan by default (`--engine configured` answers with the bank's configured engine). Results are
written 0600 under `benchmark_results/` (gitignored); the terminal shows ids and scores unless `--show`.

**Repeats and the accept rule (2026-10-20).** Four runs of the owner's 60 questions on near-identical code scored 46,
44, 42 and 42 correct: 37 questions always right, 10 always wrong, 13 flipping — even between two runs of the same
code. One run therefore cannot judge a change, so every question is answered and judged `--repeats` times (default 3,
run-major, resumable per (question, run); a failed pair is asked again). The summary reports each measure (correct,
fact recall, contradicted, stale asserted, declined-but-should-know, answered-but-should-decline) as mean and min–max
across runs, overall and per tag, plus per question always right / always wrong / flips, flipping ids listed.
`--compare A.jsonl B.jsonl` takes each question's majority verdict over its runs and calls B better or worse than A
only when (1) the exact two-sided sign test on the questions whose majority changed gives p < 0.05 and (2) the change
in mean correct is wider than the wider min–max of either file, and (3) the two move the same way (more majorities
gained than lost and the mean up, or both down; when they disagree the verdict is "within noise (directions
disagree)"); otherwise "within noise". Why this rule: pairing by
question removes the between-question spread, which dwarfs any change; the majority over runs damps the flippers; the
sign test assumes nothing about distributions and stays valid however noisy the flippers are (under no change a moved
majority is equally likely to move either way — noise costs power, never false alarms); and the spread guard stops a
handful of borderline majority moves from passing while the totals sit inside run-to-run noise. Ties (an even number
of runs split evenly) have no majority and are left out. A results file holds runs of one set of settings: `--fresh` starts it over (with
`--only`, re-asks just those questions), and the eval refuses to resume into a file whose runs recorded another
model, effort, CLI version, engine or top-k. With 60 questions a real change needs about six or more
majority moves, all or nearly all in one direction (6–0 gives p = 0.031; 5–0 gives 0.0625).

**What can be pinned.** `claude -p` (2.1.304) has no temperature, top-p or seed flag, so the plan's sampling cannot be
fixed. Its other inputs are: the model (`--answer-model`/`--judge-model` take a full id such as `claude-sonnet-5-5`
as well as an alias, and every row records the model the plan reported), the effort (`--effort` pins `--effort` on
both calls through the seam's one effort channel and drops an inherited `CLAUDE_CODE_EFFORT_LEVEL`, which the CLI lets
override the flag; off by default so numbers stay comparable with earlier runs), and the CLI version (each run's header
row). User settings are already excluded by the seam (`--setting-sources ""`). `--compare` names any of these that
differ between the two files.

---

## First slice: results (2026-10-17)

Run on this branch (`c0ed923d` + the harness), on the Claude plan: Sleep `sonnet` (disambiguation `haiku`), answer
`sonnet`, judge `sonnet`, search model `intfloat/multilingual-e5-small` (the release's bundled floor; the owner's
bank uses EmbeddingGemma 2 where the Mac runs it), concurrency 3, one drain per unit. **Small slices: read the
numbers as direction, not as a score.** With 40 questions a 95% interval on a proportion near 50% is about ±15
points; re-answering the same 40 questions on the same bank moved Ask's J by 2.5 points.

### LoCoMo, conversation `conv-26` (19 sessions), 10 questions per category (40)

| Path | J (cat. 1–4) | single-hop | multi-hop | temporal | open-domain | token F1 |
|---|---|---|---|---|---|---|
| `ask` (`cicada_ask` after Sleep) | **52.5** (re-run: 50.0) | 30 | 50 | 60 | 70 | 10.0 |
| `full-context` (same reader, same prompt, the raw history) | **95.0** | 100 | 90 | 90 | 100 | 15.0 |

Published, for orientation only (gpt-4o-mini readers, other judges): Mem0 66.9, full-context 72.9, Zep 75.1,
Letta 74.0. A `sonnet` reader with the whole ~58k-character conversation in context scores 95 — LoCoMo's
conversations fit in context, which is exactly the critique of LoCoMo (Zep, Penfield) and ConvoMem's finding.

**Cost:** 181 plan calls, 5 min 18 s wall for the unit — Sleep 21 calls (19 extraction, 1 merge, 1 skills) in 73 s
wall; answers 80 calls; judgments 80 calls. Gross prompt tokens: Sleep 125k, answers 1.23M (≈1M of it the
full-context control's 40 × ~25k), judge 229k.

**What the misses are.** 19 of 40 `ask` answers were wrong (read one by one). 17 said, in their own words, that
memory does not hold the detail ("The memory does not say what Caroline's necklace symbolizes…"); one inferred a
date a day off (Saturday for the gold Sunday); one named one place where the gold lists three. No invented fact.
The bank after Sleep: 8 pages — the 2 people, 1 topic, and 5 Stage-4 "skill" pages drawn from the chat (1 already
archived by age) — 34 claims, all on the 2 people's pages, and 26 lines held in the pending store. The claims are the skeleton —
`Caroline treasures Caroline's necklace`, `Caroline is pursuing adoption` — and the benchmark asks for the detail
around them (what it symbolises, why that agency, how long married). Where that detail survived it sits in page
prose (the owner page is ~42k characters; Ask shows ≤ 2,400 characters of prose and ≤ 2,400 of claims per page)
or only in the episodes, which Ask never reads. One miss is a contradiction inside a page: a current claim
`Caroline is from Sweden` beside a stale open question "which home country she moved from is not stated", and the
answer trusted the open question.

**A diagnostic that did not help:** ordering each page's claims by the claims vector index instead of word overlap
(an ad-hoc patch, not committed) scored 52.5 against a same-bank re-run of 50.0 — inside the noise. The loss is not
the order of the claims; it is what the claims and the Ask context carry.

### LongMemEval `oracle`, 2 questions per type (+ 2 abstention per type where they exist): 20 units

| Path | accuracy | task-averaged | ss-user | ss-assistant | ss-preference | multi-session | knowledge-update | temporal | abstention |
|---|---|---|---|---|---|---|---|---|---|
| `ask` | **70.0** | 58.3 | 2/2 | 1/2 | 2/2 | 0/2 | **0/2** | 2/2 | 7/8 |
| `full-context` | **85.0** | 83.3 | 2/2 | 2/2 | 2/2 | 0/2 | 2/2 | 2/2 | 7/8 |

Published: GPT-4o reader on oracle 87.0 (paper). **Cost:** 193 plan calls (Sleep 113, answer 40, judge 40); Sleep
550 s wall over 20 one-to-four-session banks (≈ 28 s each).

**Knowledge update is where Cicada's design should win, and both misses were updates not captured as updates:** a
count that went from three to four stayed at three in the page prose; a personal-best time appeared twice in prose
with a current claim carrying no time. Neither became a superseding claim, so Ask could not prefer the newer value.
The assistant-side detail (a shift rota the assistant wrote) was not consolidated at all.

### What this says, and what to do next (proposals, not built)

1. **Cicada's answers are honest but thin.** On both datasets almost every wrong `ask` answer names the gap instead of
   inventing; the gap to the full-context control (−42 points LoCoMo, −15 LongMemEval oracle) is detail lost
   between the episode and the Ask prompt.
2. **The evidence spans are the cheapest bridge.** Every claim already points at the exact span of the episode it
   came from (G118). An Ask that, for its top claims, also shows the cited span's surrounding turns would put the
   detail back in front of the reader without changing Sleep — measurable with this harness on the same banks
   (Sleep is checkpointed; only answers and judgments re-run).
3. **Knowledge updates need to land as superseding claims**, not as a second number in prose — measure with a
   LongMemEval `knowledge-update` slice (78 questions in the set) before and after.
4. **Run the rest before trusting any number:** all 152 scorable LoCoMo questions of a conversation, then 2–3 more
   conversations; the owner's own `answer_eval` file. Validate the `sonnet` judge on ~50 hand-graded answers (the
   2026-09-24 note's pitfall 9) — the Penfield audit shows a lenient J judge can pass vague answers.

---

## Answer depth: closing the gap (2026-10-17, branch `feat/answer-depth`)

**What changed.** (1) Ask reads a page item by item (`section_provenance.scan`: an article paragraph, a key fact, a
history line), the items sharing the question's words first, each tagged with the day it was said; the old reader took
a blank-line paragraph at a time, so a whole `## Key Facts` list was one paragraph clipped to 600 characters. (2) Ask
follows the shown claims' evidence spans and the shown items' provenance into the cited episodes and puts those turns
in front of the model as **WHAT WAS SAID** — dated, each naming who spoke, read at answer time, never stored
(`api/services/ask_sources.py`). (3) Stage 1 returns stated values (`values[]`) as single-valued `value-of-<attribute>`
literal claims, so a later count or record supersedes the earlier one in Stage 3. Details: `docs/architecture/mcp.md`
("Ask reads pages item by item") and `docs/architecture/storage.md` ("A value that changes").

**Why the knowledge updates did not supersede.** Neither miss had a claim to supersede: Stage 1 emitted only
entity-to-entity relationships (`entities_to_claims`, `object_kind: node`), so "tried three" and "tried four" were two
undated key-fact lines and the Ask reader cut the second one off. Bi-temporal supersession was never reached; and an
unseen predicate is multi-valued by design (an uncertain cardinality never auto-closes), so even a literal claim would
have coexisted. Stated values fix both: the `value-of-` shape is single-valued by itself.

**Runs** — same model (`sonnet` for Sleep, answer and judge; `haiku` disambiguation), same judges, same slices
(first N per category, deterministic), e5-small search, the Claude plan. "Ask only" re-answers on the banks the
earlier Sleep built (only the answer changed); "full" re-runs Sleep with the new extraction too. conv-49 was not looked
at while tuning (held out).

| Slice | Path | Before (dev) | After: Ask only | After: full | Control (full context) |
|---|---|---|---|---|---|
| LoCoMo conv-26, 40 Qs | J | 52.5 (re-run 50.0) | **82.5** | 75.0 | 95.0 |
| — single-hop / multi-hop / temporal / open-domain | | 30 / 50 / 60 / 70 | 80 / 80 / 80 / 90 | 80 / 50 / 80 / 90 | 100 / 90 / 90 / 100 |
| LoCoMo **conv-49** (held out), 40 Qs | J | 52.5 | **85.0** | **92.5** | 92.5 |
| — single-hop / multi-hop / temporal / open-domain | | 40 / 60 / 40 / 70 | 90 / 70 / 90 / 90 | 100 / 90 / 90 / 90 | 100 / 100 / 80 / 90 |
| LongMemEval oracle, 20 Qs | accuracy | 70.0 | **85.0** | 80.0 | 85.0 |
| — knowledge-update / multi-session / abstention | | 0/2 / 0/2 / 7/8 | 2/2 / 0/2 / 7/8 | 2/2 / 0/2 / 6/8 | 2/2 / 0/2 / 7/8 |
| Ask answer latency (incl. the model call) | p50 / p95 s | conv-26 4.85 / 6.76 · conv-49 4.90 / 6.92 · LME 4.70 / 7.03 | conv-26 5.71 / 7.28 · conv-49 6.74 / 11.93¹ · LME 5.11 / 11.0 | conv-26 5.09 / 8.82 · conv-49 5.50 / 9.66 · LME 5.83 / 11.48 | — |

¹ run beside another benchmark process on the same plan. Context build without the model (conv-26 bank, warm,
40 questions): p50 15 → 20 ms, p95 20 → 27 ms; prompt p50 7.7k → 9.6k characters (max 9.3k → 17.8k).

**Reading it.** 40 questions is about ±15 points at 95%; Sleep is not deterministic run to run. The Ask change alone
closes most of the gap on both conversations (+30 and +32.5 J) and all of LongMemEval's (70 → 85 = the control), with
no confident wrong answers added. The full run's spread (conv-26 75.0, conv-49 92.5) is Sleep variance: on conv-26 the
fresh Sleep left "known these friends for 4 years" off the page and no shown line pointed at that turn. The one new
LongMemEval abstention miss in the full run answered "none … no recorded visits in December" to a question whose gold
is "0, you did not mention any"; the abstention judge rejected it. Knowledge updates: the full run wrote
`value-of-korean-restaurants-tried-recently` 3 (closed 2023-09-30, superseded) → 4 (current); the 5K record landed as a
value on two different pages (the race's and the owner's), which no key can join — Ask still answered it from the
dated lines. Plan calls: ~750 for all the runs above (answers, judges and four Sleeps; the conv-49 baseline 188 of them).

**Still open.** Multi-session counting (0/2 everywhere, the control too); list questions that need every mention
across sessions (multi-hop "what activities …"); a value split across two pages; the judge validation on ~50 hand
grades; larger slices.

## Older conversations no page points at: the search leg (2026-10-19, branch `feat/older-recall`)

**The problem.** The owner's own eval (60 questions about one conversation each; numbers measured by the owner, real
values redacted): correct 56.7%, 0 contradicted, 0 answered-but-should-decline, 12 "declined but should know"; 2025
conversations 33% (n=24). For the 51 questions with a known source conversation, Ask's prompt held that conversation's
own words for 18 of 26 right answers but only **5 of 25 wrong ones**, while plain episode search ranked it top-5 for 16
of the 25. Ask was page-first: a conversation's words arrived only through a shown page's evidence spans or line
provenance (#337), so a detail Sleep left off the page — or a page that was not retrieved — never reached the model.

**What changed.** A second, bounded leg beside the page leg (`ask_sources.search` + `gather_search`, `docs/architecture/mcp.md`
"OTHER CONVERSATIONS"): the word index's passages holding *any* of the question's subject words (bm25 over every
600-character passage, so the middle of a long export counts as much as its head), each word weighted by its rarity
across conversations (a word in more than half of them counts for nothing), fused by rank with the vector index's
episode chunks; the best 4 conversations' turns holding the rarer words, at most 6 excerpts / 3,000 characters, labelled
by speaker and day and by conversation id, never a turn the page leg showed, never an index-only episode. A rule tells
the model a shared word is not an answer; the response names the conversations it used. No model in retrieval, nothing
written, the query never logged, off without the `sources` scope.

**Why this design, not the others.** (1) *Better pages* (re-running Sleep to put more on pages) cannot reach the
conversations Sleep already read and summarised away, and costs a model pass per conversation; the words are already
in the bank. (2) *Episode search alone* already ranked the source conversation top-5 for 16 of the 25 misses — the
failure was that Ask never asked it. (3) *Vectors alone* miss text in long exports: an episode's vector chunk is 4,000
characters, but both local search models read 512 tokens (~2,000 characters) of it, so roughly half of every long
export is invisible to the vector leg. The word leg reads every passage. (4) *Whole conversations in the prompt*
would blow the budget on a 47k-character export; turns holding the rare words, clipped, keep it to ~3k characters.

**Retrieval on long, un-consolidated chats (LongMemEval_S, no Sleep, no model).** 48 questions (8 per type, abstention
excluded), each bank its ~50 haystack sessions (~485k characters), word + vector (e5-small) indexes only. With no
pages, Ask on dev answers every one of these with the honest gap (nothing to point from); the leg alone:

| | evidence conversation top-1 | top-4 | top-20 | a turn holding the answer reaches the prompt |
|---|---|---|---|---|
| ~50 sessions, one episode each (n=48) | 41 (words 38, vectors 39) | 47 | 48 | **39 / 48** |
| the same, 5 sessions merged into one ~45k-char export (n=24, ~10 exports) | 21 (words 18, vectors 18) | 24 | 24 | **22 / 24** |

Fusion beats either leg; preference questions ("can you recommend …") reach the answer turn least (5/12), since the
person's stated preference rarely shares the question's words. Leg latency p50 16–33 ms, p95 38–49 ms (loaded machine);
~3.5k prompt characters. **Vector chunks sized to the model's window** (1,600 characters, the same 48 banks re-embedded):
evidence top-1 39 → 42, top-20 46 → 48 — a real but smaller gain, and a full re-embed of every bank; left as a follow-up.

**Public slices, Ask only, same banks before/after** (the #337 full-run banks; dev `3430149a` vs this branch; sonnet
answer + judge on the plan):

| Slice | Before | After | Notes |
|---|---|---|---|
| LoCoMo conv-26, 40 Qs, J | 82.5 | 80.0 | the one flip is the judge on an unchanged answer ("Saturday 20 May" vs gold "the Sunday before 25 May"); 0 → 1 "confidently wrong" is that flip |
| LoCoMo conv-49, 40 Qs, J | 90.0 | 92.5 | the one flip is the judge on an unchanged answer |
| LongMemEval oracle, 20 Qs | 75.0 | 75.0 | two abstention answers swapped; the leg showed nothing for either (model variance) |
| Prompt chars p50 (max) | 9.6k / 14.2k / 9.6k (19.1k / 20.6k / 14.4k) | 10.6k / 15.4k / 9.6k (22.1k / 22.9k / 15.3k) | conv-26 / conv-49 / LME |
| Context build ms p50 / p95 | 21/40 · 27/45 · 21/42 | 28/41 · 33/43 · 25/45 | warm, stub model, loaded machine |
| Gold evidence turn in the prompt (no model) | conv-26 23/38 Qs, conv-49 27/37 | 26/38, 28/37 | the leg ran on 32/40 and 39/40 LoCoMo questions, 3/20 LME |

**Reading it.** On these slices the pages already cite nearly every conversation (19–25 sessions, all consolidated), so
the leg adds little the page leg had not shown, and the answer changes are inside judge noise; it adds no confidently
wrong answer and no abstention failure it caused. The slices that look like the owner's misses — long chats whose
detail is on no page — are the LongMemEval_S rows above, where the leg puts the answer turn in front of the model for
39 of 48 (22 of 24 inside 45k-character exports). The owner's eval is the deciding measurement and is re-run after merge.
Plan calls: 400 (200 before, 200 after: answers and judges, no Sleep).

**Still open.** Paraphrase: a turn sharing no word with the question is never chosen even when the vector leg ranks its
conversation first (LoCoMo "how does she prioritize self-care?" → "carving out some me-time"); window-sized vector chunks;
multi-session counting and list questions (unchanged); the judge validation on hand grades.

## Ask depth: which conversation is current, counts and lists, passages the model reads (2026-10-19, branch `feat/ask-depth-2`)

**The problems** (the owner's eval after #344, measured by the owner): two hedged-wrong answers where an earlier
conversation beat the later one that settled it (an outcome after a plan; an agreed price after a listing price); one
answer about one specific older conversation that broke after #344; counts and lists ("how many times …") that a
top-4 cut cannot answer; episode vectors cut at 4,000 characters for models that read 512 tokens.

**What changed** (`docs/architecture/mcp.md`, "Which conversation is current"; `storage.md`, the episode cut):

1. *Recency, by subject and by the question's own words, never by date alone.* `question_shape` (no model) reads the
   question: `lookup`, `latest` (final / ended up / currently / agreed …), `anchored` (a day it names, "the first
   time", "originally") or `enumerate` (how many / list every / which … have I). A conversation is on the subject when
   it holds half the weight of the question's words the best one holds (two of them), ranked in the fused top 20.
   `lookup` keeps the newest on-subject conversation in the window (one slot), `latest` two; a kept conversation shows
   its best turn before the budget fills by score; lines stay oldest first and rule 11 says the later line on one
   subject carries what happened after, and that a question about one past occasion is answered from it. `anchored`
   never adds a later conversation and keeps the named day's. *Why this and not a recency boost in the ranking:* a
   boost moves every question toward new conversations, including the ones about an older occasion (the #344
   regression's shape); a reserved slot only adds the newest conversation on the same subject beside the best ones,
   and never on an anchored question. *Why not reorder the prompt newest-first:* rule 9 already reads days; the
   failure was that the later conversation never reached the prompt.
2. *Counts and lists: breadth on top of depth.* `enumerate` reads the plain 4 as any question does, then one ≤ 300-
   character line from each further on-subject conversation, up to 10 conversations and 1,800 more characters, and
   tells the model to count distinct events once. A first version that replaced the plain 4 with ten short lines lost
   answer turns on value questions the gate takes for counts ("how many stars do I need", "how many weeks ago"):
   on LongMemEval_S the answer turn reached the prompt for 48 of 64 against dev's 52. The breadth-on-top form keeps 52.
3. *The leg counts what it can show.* The word index marks index-only episodes (`docs.meta.index_only`, schema 6);
   a word's rarity, the conversation count and the ranking skip them. Before, every watched day counted (the owner's
   bank: ~2,500 day episodes and ~3,100 list saves beside its conversations), so a word common in video titles read as
   common and was dropped, and their passages could fill the bm25 top 150. Passages are now scored by the conversation-
   level weights of the words they hold (top-1 unchanged on LongMemEval_S: 58 of 64 both).
4. *Passages the model reads.* `EPISODE_CHUNK_CHARS` 4,000 → 1,600 (overlap 200), recorded as `chunks:episodes`; an
   old table is re-cut by the background re-embed, never by Sleep (tests: Sleep embeds only the new conversation at the
   old cut; the job re-cuts; `pending_switch` names the episode table).
5. *Embed once:* measured — the question is embedded once per Ask already (the page leg's claim search and the search
   leg share the vector through the indexer's per-model query cache). No change.

**Search model:** EmbeddingGemma 2 (Core ML, the owner's model) for every number below; e5-small numbers taken
earlier are discarded.

**How much of a passage the model reads** (EmbeddingGemma 2 tokenizer, 512 tokens):

| Text | 4,000-char passages over 512 tokens / characters unread | 1,600-char passages |
|---|---|---|
| LongMemEval_S chats (3,048 sessions) | 82 % / 36 % | 0.7 % / 0.1 % |
| LoCoMo conv-26 | 74 % / 34 % | 0 / 0 |
| synthetic 1,500-episode bank (long English words) | 62 % / 12 % | 0 / 0 |

**Index size and sync** (synthetic 1,500 episodes, EmbeddingGemma 2 on the Neural Engine, full build): 3,094 → 7,415
vectors (2.1 → 4.9 per episode), 25.0 → 40.6 MB, full sync 87 → 97 s, an idle sync 413 → 471 ms.

**Retrieval, no model** (LongMemEval_S, un-consolidated, ~50 sessions a bank; 64 questions: 16 knowledge-update,
16 multi-session, 8 of each other type; dev vs this branch):

| | dev | this branch |
|---|---|---|
| vectors alone: evidence conversation top-1 / top-4 / top-10 | 56 / 61 / 63 | **60** / 62 / 64 |
| fused: evidence top-1 / top-4 | 58 / 63 | 58 / 64 |
| a turn holding the answer reaches the prompt | 52 | 52 |
| multi-session: evidence sessions whose answer turn is shown | 17 of 49 | **19** of 49 (21 at the old cut) |
| knowledge-update: the newer evidence session's answer turn shown | 15 of 16 | 14 of 16 |
| temporal: evidence sessions shown | 11 of 18 | 12 of 18 |
| preference: answer turn shown | 4 of 8 | 3 of 8 |
| leg chars p50 / max · leg ms p50 / p95 | 3.5k / 4.0k · 15.6 / 35.9 | 3.6k / 6.1k · 15.9 / 26.4 |
| 5 sessions merged into ~45k-char exports (24 Qs): answer turn shown · multi-session sessions | 20 · 6 of 24 | 21 · 9 of 24 |

**Answers, same banks before/after** (the dev Sleep banks re-embedded with EmbeddingGemma 2; sonnet answer and judge
on the plan; only questions whose prompt changed were answered again — an unchanged prompt is the same question to
the model): LoCoMo conv-26, 31 of 40 prompts changed: **26 → 25** right (single-hop 8 → 8 of 9, multi-hop 6 → 6 of 9,
temporal 5 → 5 of 6, open-domain 7 → 6 of 7); the flip is the judge on two near-identical "memory says nothing,
probably yes" inferences. LongMemEval oracle, 3 of 20 changed: 3 → 2; the flip is the judge on two equivalent
abstentions ("none recorded" vs "zero as far as the record goes"). Confidently wrong answers: 0 → 0 on both. conv-49:
37 of 40 prompts changed, not re-answered (plan budget) — context only. Context build without the model (warm, a
loaded machine): conv-26 p50 24.7 → 23.4 ms, p95 28.2 → 32.3; conv-49 30.3 → 28.8, 37.1 → 32.9; LongMemEval 14.9 →
15.0, 19.5 → 23.0. Prompt p50 (max): conv-26 12.1k → 12.4k (21.9k → 22.1k), conv-49 15.3k → 15.5k (23.8k → 23.3k),
LongMemEval 9.1k → 9.1k (17.1k → 17.4k).

**Reading it.** On the public slices the changes are neutral within noise: their questions rarely have a later
conversation that settles an earlier one (LongMemEval_S knowledge-update already shows both values for 15 of 16), and
their counts need answer turns that share few of the question's words, which breadth lines (the best-matching turn
of each conversation) only sometimes are (17 → 19 of 49). The window-sized cut is a real retrieval gain for the vector
leg (top-1 56 → 60 of 64) at 2.4 times the vectors and +11 % sync time. The owner's eval is where the outcome-after-
plan shape lives; it is re-run after merge. Plan calls: 526 (dev baselines with Sleep 370, of which 161 Sleep; the
Gemma re-answers 156).

**Still open.** The newest conversation's *answer* turn is not guaranteed — only its best-matching turn (one
knowledge-update question lost its answer turn to that); counts whose evidence turns share no rare word with the
question; the judge's strictness on abstentions phrased as "zero".

## Broad sample 2026-10-20

**Why.** Rodrigo 2026-10-20: *"using my plan and Gemma embeddings and all of the perfect setup we're using, run the
best benchmark to see how good the memory is."* The chosen size: all 10 LoCoMo conversations (40 questions each,
10 per category 1–4) and 100 LongMemEval_S questions, answers repeated where cheap.

**Setup (the production one, measured as run).** Branch `bench/broad-2026-10-20` (dev `966213be` + the harness
changes above, `5ba897f3`); `claude` CLI 2.1.304 on the owner's Claude plan; Sleep `haiku` with `haiku`
disambiguation (the owner's production Sleep model), batch 25, one drain per conversation on the dataset's clock;
answers and the judge `sonnet` (as every earlier run); search model **EmbeddingGemma 2** (`google/embeddinggemma-2:768`,
Core ML, recorded in every bank's index, episode passages 1,600/200); concurrency 3; embedding threads capped at 4.
Web lookups (the `sonnet` lookup tier) do not run in a benchmark — every fetch gate is off in the unit's environment —
so that setting is inert here. Every unit ran only while the owner's own backend reported Sleep not running and
never between 02:40 and 03:20 local (the gate waited out the nightly run).

**What "LongMemEval_S" means here.** Each question ships its own ~50-session haystack; Sleep over it costs ~50
extraction calls a question (≈ 5,000 for 100), past any plan budget. These banks are **staged and indexed, never
consolidated** (`--sleep-schedule none`): Ask answers from the search leg over the raw conversations (no pages). That
is the path the owner's own un-slept backlog takes, not the full system. 100 questions, stratified: temporal 20,
multi-session 20, knowledge-update 16, single-session-user 12, single-session-assistant 10, preference 8, abstention
14 (the first N of each in file order; ids in the run's `config.json`).

### Results

**LoCoMo, 10 conversations, 382 questions (categories 1–4; three conversations have fewer than 10 of a category)** —
J, Mem0's judge:

| Path | J | single-hop | multi-hop | temporal | open-domain | token F1 |
|---|---|---|---|---|---|---|
| `ask`, all 10 (n = 382) | **74.9** | 91.0 (100) | 65.0 (100) | 90.0 (100) | 48.8 (82) | 11.1 |
| `ask`, the 5 control conversations (n = 198) | 77.8 | 100 | 66.0 | 86.0 | 58.3 | 10.4 |
| `full-context` control, same 5 (n = 198) | **88.9** | 98.0 | 96.0 | 86.0 | 75.0 | 12.4 |
| `ask` repeat on conv-26/43/49 (n = 120): run 1 / run 2 | 79.2 / 79.2 (range 79.2–79.2) | 100 / 96.7 | 63.3 / 66.7 | 80 / 80 | 73.3 / 73.3 | — |

Per conversation (`ask` J): conv-26 85.0, conv-30 86.7, conv-41 81.6, conv-42 62.5, conv-43 67.5, conv-44 62.2,
conv-47 70.0, conv-48 70.0, conv-49 85.0, conv-50 81.1 — the spread (62–87) is wider than the repeat noise (4 of 120
answers flipped between repeats, the total unchanged). Control per conversation: 95.0 / 97.4 / 80.0 / 80.0 / 92.5
(conv-26/41/43/47/49). Published, for orientation only (gpt-4o-mini readers, other judges): Mem0 66.9, full-context
72.9, Zep 75.1, Letta 74.0.

**LongMemEval_S, 100 questions, no Sleep, three answer repeats** (the prompt is the same each time — retrieval is
deterministic — so the spread is the answer model and the judge):

| Type | n | mean | min–max |
|---|---|---|---|
| single-session-user | 12 | 97.2 | 91.7–100 |
| knowledge-update | 16 | 87.5 | 87.5–87.5 |
| temporal-reasoning | 20 | 73.3 | 70.0–75.0 |
| single-session-preference | 8 | 62.5 | 62.5–62.5 |
| single-session-assistant | 10 | 60.0 | 60.0–60.0 |
| multi-session | 20 | **11.7** | 10.0–15.0 |
| abstention | 14 | 92.9 | 92.9–92.9 |
| **all 100** | 100 | **66.7** | 66.0–67.0 |
| answerable 86 / task-averaged | 86 | 62.4 / 65.3 | 61.6–62.8 / 64.4–65.8 |

65 questions right in all three repeats, 32 wrong in all three, 3 flipped. Published, indicative only: the paper's
GPT-4o full-context on S 60.6; Zep 71.2 on S (both with GPT-4o judges and full systems; this row has no consolidation).

**Honesty.**

| | LoCoMo `ask` (382) | LoCoMo control (198) | LongMemEval_S run 1 (86 answerable + 14 abstention) |
|---|---|---|---|
| wrong answers | 96 | 22 | 32 |
| of them, the answer names the gap ("memory does not say …") | 70 | 15 | 21 |
| asserted something the judge rejected | 26 — 14 lists with items missing, 3 counts one off ("at least two" for "two" among them), 3 relative dates a day/week from the gold, 3 inferences unlike the gold's, 2 wrong details, 1 hedged "does not clearly show" | 7 | 11 — 8 counts or totals (7 one or two short, phrased "memory shows N"), 2 stale values on knowledge-update questions, 1 date arithmetic |
| contradicted outright (a definite wrong fact) | ≈ 7 (1.8 %): 3 dates, 2 counts, 2 details (one a "yes" where the gold is "no", conv-50:q042) | — | 3 (3.5 %): two stale values (9ea5eabc, 89941a93), one date (9a707b81) |
| answered but should have declined | — (category 5 not run) | — | **1 of 14** (031748ae_abs, the same in all three repeats) |

(The gap/assert split comes from the answer's own wording, read by hand for the asserted rows.) One LongMemEval answer
in 300 was Ask's degrade path: the model's reply was not JSON and Ask returned "could not synthesize" (gpt4_59149c77,
run 1); the control had one such reply in 199, retried on resume.

**Retrieval — did the dataset's own answer turn reach Ask's prompt?** (verbatim, any 40-character stretch)

| | questions with ≥ 1 answer turn shown | answer turns shown | J when shown / when not |
|---|---|---|---|
| LoCoMo all | 290 / 375 (77 %) | — | **83.8** (290) / **43.5** (85) |
| — single-hop / temporal | 87 / 100, 87 / 100 | 97 / 117, 91 / 112 | |
| — multi-hop | 76 / 100 | **147 / 322** | |
| — open-domain | 40 / 75 | 52 / 169 | |
| LongMemEval_S all | 76 / 89 (85 %) | — | 70.3 (74) / 16.7 (12) |
| — knowledge-update / ss-user / ss-assistant / temporal | 16/16, 12/12, 9/10, 19/20 | 29/33, 13/13, 9/10, 31/45 | |
| — multi-session | 15 / 20 | **28 / 71** | |
| — preference | 3 / 8 | 4 / 14 | |

**Timing and size** (answer = Ask's whole call including the model; context build = everything before the model call):

| | answer p50 / p95 s | context build p50 / p95 ms | prompt chars p50 / p95 / max |
|---|---|---|---|
| LoCoMo `ask` | 3.96 / 5.63 | 49 / 580 (warm, past each process's first three questions: 47.5 / 72.1; the first ones pay the search model's ~0.6 s load) | 15.2k / 22.5k / 25.1k |
| LoCoMo control | 4.52 / 7.09 | — | the whole conversation (~45–90k characters) |
| LongMemEval_S `ask` | 5.0 / 6.5 | 1,106 / 1,168 — every unit is a fresh process, so each is a cold search-model load (~1 s); the leg itself measured 15–26 ms warm on 2026-10-19 | 4.5k / 6.8k / 6.9k |

**Sleep** (haiku): 272 sessions in 10 drains, 1,405 s wall (86–176 s a conversation); 348 calls — 272 extraction,
26 merge, 17 skills, 16 conflict, 12 inbox tending, 5 disambiguation; no failed call. Banks: 7–23 pages, 40–123 claims
(838 in all), 13–56 lines held in the pending store. LongMemEval_S intake + index (no model): p50 14.0 s a question
(~50 sessions on Gemma 2).

**Plan calls: 2,349** (≤ 2,500 budget) — Sleep 348 (`haiku`); answers 1,001 and judge 1,000 (`sonnet`): LoCoMo
`ask` 382 + control 199 + repeat 120, LongMemEval 3 × 100, each judged once. No plan limit was hit and no call failed.

### The five most common failure shapes

1. **Open-domain inference declined** (37 of 42 open-domain misses named a gap). The question asks for a likely
   reading ("does he live near a beach or the mountains?", "which state…?"); the evidence is there in pieces and Ask's
   rules make the model say memory does not state it. The control is weakest here too (75.0). Example: conv-41:q041.
   A sub-shape is naming a thing from its description (a card game described by its rules, a composer by a film
   theme) with the turn shown: conv-47:q016.
2. **Lists and counts across sessions come up short.** LoCoMo multi-hop: 35 misses, only 147 of 322 answer turns
   reached the prompt; LongMemEval multi-session: 17–18 of 20 wrong in every repeat, 28 of 71 answer turns shown, the
   answer counts what it sees ("memory shows 2") one or two short. The control gets multi-hop to 96.0. Examples:
   conv-26:q015, LongMemEval 0a995998.
3. **A detail on no page and in no shown turn → an honest decline.** When no answer turn reached the prompt, J is
   43.5 against 83.8 when one did (LoCoMo). Example: conv-48:q018.
4. **The assistant's own long answer, clipped** (LongMemEval single-session-assistant, 4 of 10 wrong in every repeat
   with the answer turn shown for 9 of 10): the shown excerpt holds the start of a long assistant list, not the item
   asked for ("the 7th job"). Example: 1903aded.
5. **Relative dates a day or a week from the gold** ("last Saturday" / "last week" resolved against the session day,
   where the gold names another day or a different week): conv-26:q005, conv-44:q005, conv-43:q006; LongMemEval
   9a707b81. Some of these golds are themselves loose (the Penfield audit's point).

Smaller: preference questions declined for want of a stated taste (0edc2aef, 3 of 8 every repeat); two stale values on
knowledge-update without Sleep (9ea5eabc).

### Reading it

- **On a consolidated life (LoCoMo) Cicada answers 74.9 J over 382 questions, 11 points under the same reader with the
  whole conversation in context** (77.8 vs 88.9 on the five shared conversations). Single-hop (91) and temporal (90)
  are at the control; the gap is multi-hop (65 vs 96) and open-domain (49 vs 75).
- **The gap is retrieval breadth, not honesty.** 73 % of misses name the gap; outright contradictions are ≈ 2 %
  (LoCoMo) and 3.5 % (LongMemEval); one abstention question in 14 was answered. When an answer turn reached the prompt
  J was 84; when none did, 44.
- **Raw conversations alone (LongMemEval_S, no Sleep) reach 66.7 overall** — single-session and knowledge-update are
  strong (97 / 88), multi-session counting is near zero (12). Counting across sessions is the one category every run
  of this harness has missed (2026-10-17 oracle 0/2, control included).
- **Sleep model:** these banks were built by `haiku`; the 2026-10-17 conv-26 / conv-49 runs used `sonnet` Sleep (75.0
  / 92.5 full runs, 40 questions each) against 85.0 / 85.0 here — inside the ±15-point noise of 40 questions, so this
  sample shows no measurable cost from the cheaper Sleep model.
- Not run: LoCoMo category 5 (adversarial), a LongMemEval_S full-context control (~115k tokens a question), LongMemEval
  with Sleep (budget), the judge validation on hand grades (still open from 2026-10-17).

## Two ends: questions about two moments (2026-10-20, branch `feat/ask-two-ends`)

**The problem** (the owner's new hard set, measured by the coordinator, real values redacted): temporal 0 of 7. Ask
found one end of "when I first … and by the time I later …", "between <month> and <month>", "how many days between A
and B" and not the other (or an adjacent day's conversation for it), and estimated the gap (a "178–208 day" range; 16
for 17). One search over the whole question ranks first the conversation holding most of its words — one end.

**What changed** (`docs/architecture/mcp.md`, "Two ends"): `ask_sources.two_ends` reads the moments from the
question's words (no model); each end is searched on its own words through the same two legs and its best
conversation is kept in the window, on its own named month or day; each end leads with its own best turns; for
two-ends and elapsed-time questions the prompt carries TIME BETWEEN THE CONVERSATIONS — the shown days numbered from
the earliest, today, and the exact gap between the ends. Spanish dates and a month named alone count as named days.
#365/#367's single-sentence clip is not reintroduced; #349's search leg is unchanged for every other shape.

**Measured** on the broad sample's banks (EmbeddingGemma 2; sonnet answers and judge; the broad run's own answers on
dev as "before" — its r1–r3 repeats; only the questions whose prompt changed re-answered, 3 repeats):

| | prompts changed | before (r1 / r2 / r3) | after (3 repeats) |
|---|---|---|---|
| LongMemEval_S temporal-reasoning (23) | 18 | 17 / 18 / 18 | **19 / 19 / 19** |
| LoCoMo temporal (100, 10 conversations) | 2 | 90 | 90 (both changed ones right 3/3) |
| every other category (LME 77, LoCoMo 282) | 0 — byte-identical | — | — |

Gains: the order of three quoted events (0/3 → 3/3: all three conversations now reach the prompt, 2 → 3 answer turns
shown) and "how many days between MoMA and the Met" (2/3 → 3/3). No changed question got worse; the one abstention
among them stayed right 3/3. Answer turns shown for the 18 changed: 28 → 30 of 35. Prompt p50 5.2k → 6.5k
characters on the changed questions; context build p50 +27 ms (one more embed and word search per end). The two
LongMemEval misses left are one-moment "how many days ago … when I …" questions whose event is dated relative to its
session; out of scope here. Plan calls: 122.

*After review (same day):* "from A to B", "between A and B" and two named months now need a change, duration or order
word outside the matched words; "which … first" needs a past verb; Spanish counts and "first and foremost"-style
openers are excluded; a named day outside the ends and an outcome word keep their reservations; days are the local day
of each line's stamp (a line whose stored UTC date differs is named beside it); an end is dated by its own best turn,
and two ends may share a session resumed days later. The same 20 public questions changed (nothing else did); one
more repeat of them with the reviewed code: LongMemEval_S temporal 19/23, LoCoMo's two right. Plan calls: 40 (162 in
all).


## Lists and counts (2026-10-20, branch `feat/ask-lists`)

**The problem** (the broad sample above): LoCoMo multi-hop 65 J against the control's 96, its answer turns in the
prompt for 147 of 322; LongMemEval_S multi-session 11.7 %, 28 of 71 — answers counted what they saw, one or two short
(conv-26:q015, 0a995998). Reading the misses: on LongMemEval the evidence conversations were mostly found (fused rank
0–6) but the line shown from them was the agent's reply repeating the question's words, not the person's line that
told the event; on LoCoMo the subject's page held the items (the camping and swimming lines on the page of the person
asked about) but the page leg showed only the 7 of its 119 items sharing the question's words, and the turns that told
them share none ("what activities …" vs "went camping at the beach"); and 15 of the 100 multi-hop list questions were
read as one fact ("where has <name> camped?", "what are <name>'s hobbies?").

**Design** (`docs/architecture/mcp.md`, "Lists and counts"; no model in retrieval): (1) whose turn tells it — a count
or a list prefers the turns of whoever the question is about (the person, the agent, a named speaker), another
speaker's turn at half its words' weight less the asked speaker's name; (2) more list forms read as `enumerate`
(plain-question lists, Spanish counts; a superlative never); a list of only common words keeps them at low weight;
the search leg's breadth 10 → 16 conversations; (3) a page the list names is filled with its items nearest the
question by the search model (one batch of ≤ 120 items, computed now, never stored), and each leads to the turn that
told it by the item's own words, WHAT WAS SAID read breadth first. Tried and dropped: one line from each window
conversation before a second from any (lost a knowledge-update answer turn: "how many stars do I need" — 0f05491a);
embedding conversation turns (≈ 2.5 ms a turn and the asked person's name dominated the ranking); a computed list of
occurrences (without a model a retold event can't be told from a new one).

**Retrieval, no model** (the broad sample's banks, EmbeddingGemma 2; answer turns shown, of the dataset's answer turns):

| | before (dev) | after |
|---|---|---|
| LoCoMo multi-hop (100) — answer turns · questions with ≥ 1 · with all | 147 / 322 · 76 · 26 | **187** / 322 · 86 · 36 |
| LoCoMo multi-hop — gold list items whose words all reach the prompt (any form) | 179 / 242 | **199** / 242 |
| LongMemEval_S multi-session (25 incl. abstention) — answer turns · ≥ 1 · all | 28 / 72 · 15 · 3 | **45** / 72 · 19 · 9 |
| other categories whose prompt changed (count-shaped questions in them) | | LME knowledge-update 12, temporal 11, ss-assistant 1; LoCoMo single-hop 14, open-domain 3, temporal 1 |
| — their answer turns | KU 29, temporal 35, single-hop 97, open-domain 52 | 30, 42, 99, 54 — no question lost one |

Every other prompt is byte-identical. Prompt size on the changed questions: LoCoMo p50 16.2k → 23.7k characters, the
largest prompt of the sample 25.1k → 31.6k; LongMemEval_S max 7.6k → 8.7k. Context build: LoCoMo changed questions
+220 ms p50, +650–710 ms p95 (≤ 953 ms) — the page items' one embedding batch, warm ~1.7 ms an item; LongMemEval_S
(no pages) +0 ms p50.

**Answers** (sonnet answers and judge on the plan; the broad run's own answers on dev as "before"; only the changed
multi-hop and multi-session questions re-answered; repeat 2 on LongMemEval and on the three LoCoMo conversations the
broad run repeated):

| | before | after |
|---|---|---|
| LoCoMo multi-hop, 100 questions (59 changed; one repeat) | 65 | **73** |
| — the 17 changed in conv-26 / 43 / 49, two repeats each | 8, 9 | **11, 11** |
| LongMemEval_S multi-session, 20 (r1 / r2 / r3 · r1 / r2) | 3 / 2 / 2 (11.7 %) | **7 / 7 (35 %)** |
| LongMemEval_S multi-session abstention (5) | 15 of 15 | 9 of 10 — 88432d0a_abs's honest decline phrased "the count is 0" was judged wrong once (right in r2), the judge strictness noted 2026-10-19 |

Changed LoCoMo questions: 32 → 40 of 59 (10 right that were wrong, 2 the other way, both on near-identical
answers: conv-30:q024 now lists one more event than before and is still judged short; conv-42:q019 gives the same "3,
or 2 confirmed" in both). Plan calls: **258** (129 answers, 129 judgments). The owner's two sets are measured by the
coordinator with `--compare`.

**Still open.** LongMemEval's remaining misses count items whose turns hold none of the question's words ("citrus
fruits" told as "lime", "doctors" told as "my dermatologist"): only a turn-level semantic pick would reach them, and
measured here it cost more than it ranked. A question that names no page and asks in the first person ("how many
weddings have I attended") gets the search leg's breadth only: the person's own page holds a whole life and is never
item-ranked.

*After review (same day):* the page ranking runs only on a model this machine runs (a hosted embedding model would
have been sent page text at answer time), with one allowance of 120 items for the whole question, each clipped to 240
characters, and a bounded 1.5 s wait for the Core ML passage functions; more one-thing plurals, an age, a habit and
"what else" are no longer lists; Spanish first-person verbs and "the user" count as the person. Re-measured: answer
turns LoCoMo multi-hop 188 / 322, LongMemEval_S multi-session 45 / 72 (unchanged), gold items 199 / 242; no question
lost an answer turn against dev. Context build on the changed LoCoMo questions +217–222 ms p50, +242–648 ms p95, at
most +717 ms (the first question in a process loads the packed function); the largest prompt 29.9k characters. The
15 multi-hop questions whose prompt changed again were re-answered once: 9 → 10 right, so LoCoMo multi-hop is **74**
of 100 (one repeat; dev 65). Plan calls: 30 (288 in all).

## Judgements and Spanish (2026-10-20, branch `feat/ask-infer-es`)

**Why.** The broad sample: LoCoMo open-domain 48.8 J against 75 for the whole-conversation control, 37 of 42 misses
saying memory doesn't state what was a reasonable inference from what it found. The owner's hard set: Spanish 5 of 10,
the English counterparts much higher.

**Causes found.**
1. *Judgements declined as missing facts.* Rule 1 ("never guess") read every "would <name> likely …" as a fact to look
   up. Nothing told the model a judgement may be reasoned from the record.
2. *A Spanish question over English conversations reached none of their words.* Every word leg matches the question's
   words: claims and page items by shared words, WHAT WAS SAID through those, the search leg's turns by weighted words.
   With 40 LoCoMo questions translated to Spanish (fixture `benchmarks/public/fixtures/locomo-es.json`), the dataset's
   answer turns reached the prompt **8 of 74** times; the same 40 in English, **38 of 74**. The entities were found
   (the vector leg is multilingual), their conversations' words were not. Also: Spanish function words were subject
   words, the shape detectors and `_wants_history` read only English time phrasing, "ayer"/"hace tres días" named no day.

**Fixes.** See `docs/architecture/mcp.md`, "Judgements and Spanish": a judgement detector and a prompt note for those
questions only (the system prompt is unchanged); Spanish questions go *by meaning* — the vector leg's nearest passages
lead the search leg, ranked turn by turn by the search model, and the full-budget pages' claims and items are ranked by
it; Spanish stopwords, time phrasing and relative days. Tried and dropped: going by meaning also for an English question
whose words the record lacks — that is how an abstention looks ("what is the name of my hamster?" turned into a
lookup).

**Retrieval, no model:** Spanish answer turns **8 → 33 of 74** (English 38). Every English prompt of the broad
sample's banks (300 LoCoMo, 100 LongMemEval_S) is byte-identical to dev except the 42 open-domain judgement questions'.
The judgement detector fires on 49 of LoCoMo's 96 open-domain questions and on none of its other 1,890 (446
adversarial), nor on the 100 LongMemEval_S questions. Context build: Spanish 35 → 420 ms p50 (the search model ranks
up to 160 page texts and 48 turns); judgement questions +210 ms p50 (their named pages' items ranked). Prompt p50:
Spanish 9.0k → 19.4k characters (English 15.6k), max 26.1k.

**Answers on haiku** (answers and judge `haiku`, broad sample banks, EmbeddingGemma 2, one repeat):

| | dev | this branch |
|---|---|---|
| LoCoMo open-domain judgement questions (42 whose prompt changed) | 17 / 42 (40.5) | **26 / 42 (61.9)** |
| LoCoMo in Spanish, 40 answerable (fixture) | 20 / 40 (50.0) | **27 / 40 (67.5)** |
| — by category: single-hop / multi-hop / temporal / open-domain | 9/10 · 5/10 · 4/11 · 2/9 | 9/10 · 9/10 · 6/11 · 3/9 |
| LoCoMo adversarial in Spanish (10) | 10 / 10 | 9 / 10 |
| English adversarial, LongMemEval abstention, every other English question | — | prompt byte-identical: unchanged |

- **Open-domain:** 12 right that were wrong, 3 the other way: two "would Caroline …" answers inferred the wrong way
  from the right evidence, and a yes/no "did they meet" was answered "probably yes" from a plan to meet. Every
  inference was marked as one (confidence 0.3–0.6). The other 40 open-domain questions' prompts are unchanged and were
  not re-answered.
- **Spanish:** 10 right that were wrong, 3 the other way: one answer gave the right day (2023-05-07) and was judged
  wrong; two ask about a film by its Spanish title, which the record never uses. The adversarial miss is an honest
  decline ("memory holds no favourite DJ of Dave") that went on to name a related favourite.
- **Plan calls: 370** (2 translations, 184 answers, 184 judgments). The owner's two sets are measured by the
  coordinator with `--compare`.

**Still open.** Open-domain questions asked as plain facts ("does <name> live in <state>?", "how old is <name>?",
"what nickname does …") are not read as judgements and still decline. A Spanish question about something named only
in English (a film title translated) misses it. An English question over Spanish conversations is not helped: going
by meaning on missing words breaks abstention, so it would need the bank's own language, not the question's words.
