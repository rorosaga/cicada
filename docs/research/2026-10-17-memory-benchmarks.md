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
  never redone). The report counts unanswered and ungraded questions and gives the score with them as not correct. Slices are
  deterministic (first N per category / per unit).
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
