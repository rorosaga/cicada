# Why the whole conversation beats Ask on LoCoMo, and what Supermemory does

**Date:** 2026-11-09 · **Rows:** [G148](../goals/memory-evolution.md#g148) · **Status:** analysis plus one retrieval change, measured. Plan, not a key; haiku for Sleep, answers and judge; benchmark data only (the bank is never read).
**Why now:** Rodrigo, 2026-11-09: "i still think its really bad, how come the control win against cicada. Cicada should provide better results that that, how does supermemory do it for example, their results are better."

## 1. Every question full context got right and Ask got wrong

Stored run `locomo-20261107T224047Z` (slept, 200 questions, one judge pass): Ask 156, full context 168. **20 questions** are right for full context and wrong for Ask; **8** the other way (net 12). By category the whole gap is multi-hop:

| Category | Questions | Ask | Full context |
|---|---|---|---|
| multi-hop | 76 | 55 | 65 |
| temporal | 99 | 87 | 89 |
| open-domain | 22 | 11 | 11 |
| single-hop | 3 | 3 | 3 |

The cause of each of the 20, read from the stored prompt (`prompts.jsonl`) against the question's evidence turns (`evidence` ids, in the conversation) and the slept bank:

| Cause | Count | What it looks like |
|---|---|---|
| The fact is in the bank, the prompt did not carry it | **14** | A multi-hop question needs 2 to 4 turns; Ask showed some and not the rest ("which cities has X visited": one of two; "where has Y made friends": two of four places; "items X had as a child": none, the page line says *kid* where the question says *child*). A 72 KB person page holds the fact as one prose bullet no word of the question matches. |
| The prompt carried it, the answer step hedged or did not compute | **4** | Two relative dates ("tomorrow" said on the 19th, "last Friday" said on the 20th) left unresolved; two answers that name the right person or day and then say the record does not settle it. |
| The judge or the gold answer is the problem | **2** | An answer that matches the gold in other words; a gold that is a guess ("likely a friend"). |
| **Sleep dropped the fact** | **0** | Every evidence turn is in `episodes/`, and each fact checked is in a page. The bank is not what is missing. |

So the control wins on **coverage**, not on what Sleep keeps. Full context never has to decide which lines matter; Ask does, with a lexical-first ranker that fills the page's budget with the lines sharing the question's words and only then, for a few question shapes, asks the search model about the rest.

## 2. How Supermemory does it, and what is comparable

Sources: [research index](https://supermemory.ai/research), [LongMemEval-S report](https://supermemory.ai/research/longmembench). Their backend is closed; the report and the pipeline description are the only primary sources.

- **Benchmark and model.** LongMemEval_S, **500 questions**, answers and judge **gpt-4o** with the benchmark's own judge prompts: **97%** overall, 95% temporal, 96% multi-session (their "Recall@20 with aggregation" configuration). The same report scores the **full-context control at 60.2%** (temporal 45.1%, multi-session 44.3%) and Zep at 71.2%. With gpt-5 as the answer model theirs is 84.6%, with gemini-3-pro 85.2%.
- **LoCoMo.** Ranked "#1" on the page with **no score, answer model or judge given**. Not comparable to anything.
- **Pipeline (their description).** Sessions ingested whole; large ones split into semantic blocks; an **atomic memory per chunk** with ambiguous references resolved and the **source chunk kept attached**; two dates per memory, `documentDate` (when it was written) and `eventDate` (when it happened); new memories linked to old ones by `updates`, `extends`, `derives`; search over the memories and then **the source chunk of every hit is injected**; the answer prompt carries the question, the question's date, the memories, chunks, temporal context and profile.
- **What is comparable to ours.** Their design is the shape ours already has: atomic claims with provenance spans, two dates (ruling 39), versioned updates (bi-temporal validity, conflicts), and the source turn beside the claim (`WHAT WAS SAID`). Nothing in the description is a mechanism we lack.
- **What is not.** Their headline is on a different benchmark, a different and weaker answer model (gpt-4o, where a whole 115k-token history scores 60%; haiku with the whole LoCoMo conversation scores 84%), a different judge, and a metric the page itself labels "Recall@20" next to accuracy. On our LongMemEval_S the number to beat is 80 of 100 with haiku; theirs is not a number we can match by reading it. "Their results are better" is, on the evidence published, a statement about **their control being weak**: the control they beat scores 60%, ours 84%.
- **Their own research prototype** (ASMR, a model searching the memory agentically, reported near 99% on LongMemEval-S in third-party coverage) is not the product.

## 3. The change

Both into `ask_sources.py` / `ask_service.py`, no model, no rail touched (spans, dates and the handshake are untouched; the added reads are the page's own items and the already-indexed turns):

1. **The page's items are always ranked by meaning as well as by words.** The search model's ranking of a page's items (`Searched.similar`) used to be computed only for lists, inference, implied or advice questions and in another language, and used only for those pages; it now runs for every question, filling the page budget after the lexical hits. "Items he had as a child" now reaches "had a film camera as a kid".
2. **Ask's search window** (conversations 8 → 12, lines 12 → 24, characters 6,000 → 12,000). The window rarely fills (tokens moved 4% for this alone), so it costs nothing where the question is narrow and room where it is not.

## 4. Measured

Same 5 slept banks (cloned, no new Sleep), same 200 questions, haiku answers and judge, paired against the stored run.

| Ask | Right of 200 | Gained / lost | p | Tokens per question |
|---|---|---|---|---|
| Stored (`b55e47d7c`) | 156 | | | 10,563 |
| Window only | 162 | 12 / 6 | .24 | 11,019 |
| Window + page items by meaning | **163** | 12 / 5 | .14 | 11,688 |
| Whole conversation (control) | 168 | | | 33,384 |

- **The gap to the control goes from 12 to 5 at about a third of its tokens** (11,688 against 33,384 per question), but 12 gained against 5 lost is not significant on 200 questions: report it as "163, not shown to differ from 156".
- **The gain is not where the analysis predicted.** Net by category against the stored run: temporal +4 (5 / 1), open-domain +1 (4 / 3), multi-hop +2 (3 / 1). Multi-hop, where the control leads by 10, closed by 2. The wider window and the semantic fill lift questions broadly; the multi-hop shortfall (a question that needs 2 to 4 separate turns) is mostly still there. That is the next thing to look at, with the 14 in section 1 as the worked set.
- **LongMemEval_S, the same 100 questions, nothing slept: 79 against 80** (7 gained, 8 lost, p = 1.0), at 10,923 tokens per question against 8,121. No loss in accuracy; the wider window costs 35% more tokens there, where the fuller conversations fill it.

## 5. What is not fixed

- **Relative dates** (2 of 20): the answer step is given the day each line was said, but not asked to compute "tomorrow"/"last Friday" from it. A class fix in the answer instruction is next, not tuned to these two.
- **Hedging** (2 of 20): the answer names the right person and then declines. Wording of the answer step, not retrieval.
- **A 3-judge majority** on the new run (`rejudge.py`) has not been run; the figures above are single-pass judgments, as the stored run's 156 is.
- **Scale:** 5 conversations, 200 questions, one run, one model for everything. No figure here compares Cicada with Supermemory's product.

## 7. 2026-11-23: why multi-hop stayed 10 behind, and the change that moved its reach

**Question:** section 5 left multi-hop 57 against the control's 65, with 47 of 76 prompts missing at least one gold turn. Same 5 slept banks (cloned), same 200 questions, haiku for answers and judge, `4f0905856`-era stored run as the baseline. The loop was free: `--paths reach` (new) records Ask's prompt and how many gold turns it holds, with no model call; it reproduced the stored 29 / 37 / 10 (every / some / none) exactly. Reach flatters (section 4), so graded runs decide.

### Where the prompt's characters go, and what they buy (76 multi-hop prompts, stored run)

| Section | Mean characters | Gold turns it carries (of 222) |
|---|---|---|
| Pages (claims and prose) | 12,986 | 13 |
| WHAT WAS SAID (lines the pages cite) | 5,923 | 107 |
| OTHER CONVERSATIONS (lines the search finds) | 3,968 | 37 |

**Cause found.** The meaning leg (turns picked by the search model inside the nearest passages) was meant to fill "what the prompt has left", and `ask_service` measured that as `ASK_WINDOW_CHARS` (12,000) less the whole prompt so far, pages included. A slept memory's pages alone are about 13,000 characters, so the room was negative on every slept prompt and the leg added nothing: the 2026-11-09 "slept 159 → 159" for the meaning leg was this, not a verdict on it. A question such as "which cities has <name> visited" shares one weak word with the lines that answer it ("a short trip to Rome"), so the words found none and the leg that could was switched off. 11 of 200 prompts were unchanged by the fix (12 in run 1, where the harness reuses an identical prompt's answer); the other 188 or 189 changed, nearly all by growing.

### What was tried, by reach only (no model), 200 questions

| Change | Every gold turn shown, all / multi-hop | Mean prompt characters | Note |
|---|---|---|---|
| Stored | 131 / 29 | 21,379 | |
| Room counted against the lines, not the pages | 142 / 34 | +1,700 | |
| and 8 conversations read by meaning, not 4 (**kept**) | 145 / 37 | 24,780 | final code |
| and 2 lines from each of 8 | 151 / 41 | 27,669 | +3 multi-hop for +2,900 characters: dropped |
| and 3 lines from each, ranked across conversations, 200 turns embedded | 152 / 42 | 28,003 | context build several times slower: dropped |

Two things the loop ruled out. Embedding every turn of the nearest chunks and ranking the turns alone is weak on short chatty turns: from the 16 nearest chunks (138 turns), the top 25 hold 54 of the 222 gold turns and the top 60 hold 127, against 139 shown today; a turn like "took a short trip to Rome" ranked 144th of 149 for the cities question. The banks hold 43 to 91 chunks of about 1,300 characters, so with 64 chunks every gold turn is in the pool: at this size the problem is the turn, never the conversation, and a real memory, which cannot take the whole of it, will behave like 16 to 32.

### Graded, paired on the same 200 questions against the stored run (163, multi-hop 57)

| Run | Right | Gained / lost | p | Multi-hop | Open-domain | Temporal | Tokens / question | Per right answer |
|---|---|---|---|---|---|---|---|---|
| Stored | 163 | | | 57 | 12 | 91 | 11,688 | 14,341 |
| After, run 1 (12 prompts reused) | 167 | 8 / 4 | .39 | 62 (5 / 0, p = .06) | 10 | 92 | 12,879 | 15,424 |
| After, run 2 (all fresh) | 168 | 11 / 6 | .33 | 61 (6 / 2) | 14 | 90 | 12,844 | 15,290 |
| Baseline replicate: `origin/dev` Ask, all fresh | 160 | | | 56 | 11 | 90 | 11,492 | 14,365 |
| Control: whole conversation | 168 | | | 65 | | | 33,384 | |

- **Not shown to differ**, as in section 4: the final code is 4 and 5 above the baseline in two independent runs, and the two runs disagree with each other on 13 questions (6 right only in run 1, 7 only in run 2), which is the noise on a pass of 200. Multi-hop is the place it should move and it does in both (57 → 62, 61), open-domain and temporal do not, as expected. Say "+4 to +5 on 200, not significant, in the right category".
- **The baseline's own spread (added 2026-11-23, one more graded run).** The stored run is one draw, so `origin/dev` Ask was run again, all fresh, in a detached worktree (the Ask files are unchanged between it and the branch's base): 160 right, multi-hop 56, open-domain 11, temporal 90, 11,492 tokens a question, 14,365 per right answer; multi-hop by gold turns shown every 29 (26 right), some 37 (24), none 10 (6). The two baselines differ from each other by 3 overall (7 / 4 gained / lost, p = .55) and by 1 on multi-hop (3 / 2). The two final-code runs differ by 1 overall and 1 on multi-hop.

  | Baseline | After | Overall gained / lost, p | Multi-hop gained / lost, p |
  |---|---|---|---|
  | Stored 163 / 57 | Run 1 167 / 62 | 8 / 4, .39 | 5 / 0, .06 |
  | Stored 163 / 57 | Run 2 168 / 61 | 11 / 6, .33 | 6 / 2, .29 |
  | Fresh 160 / 56 | Run 1 167 / 62 | 10 / 3, .09 | 7 / 1, .07 |
  | Fresh 160 / 56 | Run 2 168 / 61 | 10 / 2, .04 | 6 / 1, .13 |

  **Reading, two against two:** every final-code run beats every baseline run, overall by 4 to 8 (the means are 161.5 and 167.5) and on multi-hop by 4 to 6 (56.5 and 61.5), while the baselines differ by 3 and 1 and the final runs by 1 and 1. So the multi-hop gain is clear of the baseline's own spread, and it is the one the reach change predicts (29 → 37 of 76 with every gold turn shown); the overall gain is the same size and direction but is carried mostly by multi-hop, and open-domain and temporal sit inside their noise (open-domain 11 and 12 against 10 and 14, temporal 90 and 91 against 92 and 90). No single pairing is significant except one overall (.04 of four), so with two runs a side this supports "a multi-hop gain of about 5 of 76 and an overall gain of about 6 of 200 beyond the baseline's observed spread, at +10% tokens", not a significance claim.
- **Reach moved far more than answers did**: every gold turn shown on multi-hop 29 → 37 of 76 (all 200: 131 → 145). Right with every gold turn shown stays 86 to 89%; with some, 68% → 69 to 75%; with none 7 of 10 → 3 of 3 (3 prompts left).
- **Cost:** +3,400 prompt characters (+16%), +1,160 tokens a question (+10% on the stored run, +12% on the fresh baseline's 11,492), +6.6% to +7.5% tokens per right answer (+6% to +7% on the fresh baseline's 14,365), one model call as before; context build p50 422 → 554 and 603 ms (a loaded machine), answer p50 6.5 s → 6.1 and 5.8 s (noise). The owner should see the +10%: the control is 33,000 and is not a target.
- **LongMemEval_S, unslept, the same 100:** 79 → 77 (0 gained, 2 lost, p = .5), tokens 10,923 → 10,990. Only 32 prompts changed (an unslept bank has few page lines, so the room was already there); the 2 losses have the same lines shown (reach 1 of 1 and 0 of 1 in both) and reworded answers, and the first states the same decline as before.
- **Recall:** unchanged by construction (`meaning_room` is Ask's argument; recall passes none) and checked: recall's, the hook's and pending's text is byte-identical on all 200 questions before and after, so no graded recall run was spent.

### The 16 questions right lines were shown for and the answer was wrong (stored run)

| Cause | Count | Questions' shape |
|---|---|---|
| Date arithmetic from a relative phrase | 6 | "last Friday", "this weekend", "last week", weeks between two days; two golds are themselves loose |
| Names the right thing and then declines or gives a partial list | 5 | a book list missing one title, a dessert named but "not said she made it", a person named and "not recorded" |
| Open-domain inference the record does not state | 5 | the gold is a guess ("hairless cats", "asthma", a brand); the answer declines or guesses another |

**Tried and dropped:** the weekday of every quoted day, plus one sentence in rule 9 ("count from it, and say the date you worked out"), commit `148eeb6ff` (discarded): graded on 200 with the retrieval change, 166 (8 / 5 against the stored run), temporal 92 → 92 (2 gained, 2 lost against run 1), the date questions unchanged, +3.6% tokens. A class fix, but no measured effect, so it is not shipped. The other two causes are wording of the answer step, not retrieval; no class fix was found that a 200-question pass could show.

### Not done, and what the owner decides

- A second model call (a query-planning step that names the cities, trips, books a "list" question is after) is the only mechanism seen that would find "a short trip to Rome" for "cities", since no embedding or word ranks it. Not built or measured: it adds a call and about 3 s to every Ask. If the owner wants multi-hop at the control's level, that is the next experiment, measured both ways.
- Whether +10% tokens for +4 to +5 questions on 200 (multi-hop +4 to +5 of 76) is the trade to ship.
- `--paths reach` and the `reach` per-question prompt capture are in `benchmarks.public`; the two scratch scripts that cross-tabbed reach by category are not committed (the table above is their output).
