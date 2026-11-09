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
