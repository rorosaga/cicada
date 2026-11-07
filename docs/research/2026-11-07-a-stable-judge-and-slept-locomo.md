# A stable personalization judge, and LoCoMo slept on current dev

**Date:** 2026-11-07 · **Rows:** [G148](../goals/memory-evolution.md#g148) · **Status:** measurements; corrects [the 2026-11-06 note](2026-11-06-memory-before-sleep.md). Plan, not a key; haiku for Sleep, answers and judge; benchmark data only.

## 1. Why the same answers scored 13 to 40 of 90

**The system prompt.** A plain `claude -p` keeps Claude Code's own coding-agent system prompt and grades much more strictly. Every call that replaces it, the harness's included, grades alike. Same 90 stored PersonalizationV4 Ask answers, judge prompt unchanged, two runs of each call:

| Call (haiku, no tools) | Right, of 90 |
|---|---|
| Plain `claude -p` (Claude Code's system prompt) | 17, 21 |
| `--system-prompt` one line | 38, 30 |
| `--system-prompt` the harness's line plus its context guard | 32, 28 |
| The harness's own call (`providers.resolve_llm_fn`, stage judge) | 34, 38 (graded once at 30) |

- **Chosen call:** the harness's, since every run already uses it and its replies are a bare `Yes`/`No` that the parser reads. Nothing in it changes.
- **What stays:** two runs of one call flip 5 to 10 of 90. So each stored answer is judged **three times and the majority taken** (`benchmarks/public/rejudge.py`, no new answers). 77 to 83 of 90 are unanimous on PersonalizationV4; the rest are the noise.
- **A plain `claude -p` is no baseline for a judge.** The 13 to 21 readings in the earlier note were this prompt, not the harness.

## 2. The figures re-judged (majority of 3, same stored answers)

| Set | Before | Majority of 3 | Change | Paired |
|---|---|---|---|---|
| PersonalizationV4, Ask, 90 | 30 | 30 | | |
| PersonalizationV4, recall's words with general knowledge, 90 | 40 | 35 | | Ask only 11, recall's words only 16, p = .44 |
| PersonalizationV4, closed-book, 90 | 30 | 32 | | closed-book only 15, Ask only 13, p = .85 |
| PersonaMem-v2, Ask before the change, 90 | 18 | 16 | | |
| PersonaMem-v2, Ask after, 90 | 45 | 43 | 16 → 43 | 28 gained, 1 lost, p < .001 |
| PersonaMem-v2, closed-book / recall's words, 90 | 33 / 36 | 32 / 34 | | Ask after v closed-book 16 / 5, p = .027; v recall's words 14 / 5, p = .064 |
| Translated PersonaMem-v2 (de, ar, ja, zh), Ask before, 120 | 10 | 7 | 7 → 37 | 31 gained, 1 lost, p < .001 |
| Translated, closed-book, 120 | 30 | 32 | | Ask after v closed-book 14 / 9, p = .40 |

- **The gains hold, a little smaller.** PersonaMem-v2 18 → 45 is 16 → 43; translated 10 → 42 is 7 → 37. The direction was right and the sizes were 2 to 5 points high.
- **Against no memory, the gain is smaller than "from 18".** Ask after the change is above closed-book on PersonaMem-v2 (43 v 32, p = .027), and **level with it in translation** (37 v 32, p = .40) and **level with recall's words plus general knowledge** on PersonaMem-v2 (43 v 34, p = .064). Before the change Ask was far *below* closed-book; it now matches it and is ahead on the English set.
- **PersonalizationV4 shows no gap in either direction**: Ask 30, recall's words 35, closed-book 32. The earlier "30 v 40, behind recall's words" was one reading of a noisy judge. Whether Ask helps there is not shown.
- **Scale:** 3 users and 90 questions per English set; 30 questions in 4 languages; one model judges. Not covered: other judges, a slept bank (all of these are unslept), the papers' protocol, the full test splits.

**LoCoMo's judge is stable.** The same 200 slept Ask answers, three more judgments each with its own prompt: 194 of 200 unanimous, 162 by majority against 156 graded (+6, a slightly lenient tail, not a flip pattern). So only the personalization judge needed this.

## 3. LoCoMo, 200 questions, slept end to end, current dev

Cicada `b55e47d7c` (dev `c997f2b7a` plus the re-judge tool). 5 conversations, 128 sessions, **a fresh Sleep** (the earlier 159s re-graded one earlier Sleep's banks), the 5 paths, 40 questions each, adversarial left out.

| Path | Right, of 200 | Tokens per right |
|---|---|---|
| Ask | **156** (78.0%) | 13,543 |
| Full context | 168 (84.0%) | 39,743 |
| Recall's words | 127 (63.5%) | 8,961 |
| Closed-book | 9 (4.5%) | |
| Hook | 10 (5.0%) | |

- **Slept Ask against the earlier runs:** 159 on the earlier Sleep's banks (156 v 159, 8 gained, 11 lost, p = .65) and 163 on that Sleep's first grade (7 / 14, p = .19). **No change**; the fresh Sleep is a few points lower, inside the run-to-run spread. Against **unslept 138: +18** (26 gained, 8 lost, p = .003). What Sleep adds holds on current dev.
- **Ask is 12 below full context** (156 v 168), at a third of the tokens per right answer.
- 2,184 plan calls, 623 s of Sleep wall in all, about 64 min for the run. One full-context answer errored and was retried (`--resume`).
- **Scale:** 200 questions, one conversation set (10 long chats), one run. Not covered: other Sleep models, a bank with many pages, LongMemEval.

## 4. What it cost (calibration)

One conversation (conv-26, 19 sessions, 40 questions, 5 paths): **430 plan calls**, 2.31 M input tokens (0.49 M cache read, 1.83 M cache write), 0.22 M output, **$0.48 at haiku list**, 106 s of Sleep wall. The weekly plan counter read 59% before and 59% after. The full 200 run (2,184 calls, about 64 min) read 59% before and after as well. The counter moves in whole points, so each is **under one point**: that bounds the cost at under 0.46 point per 1,000 calls, which is the earlier bound (at most 0.48) and **no tighter**. A finer figure needs a counter with decimals, or a run long enough to move it several points. The whole session (about 6,500 calls, mostly 3,000 re-judgments and 1,000 probes) moved it from 58% to 59%.
