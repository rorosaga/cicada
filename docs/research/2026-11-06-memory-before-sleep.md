# Memory before Sleep, efficiency, and every language

**Date:** 2026-11-06 · **Rows:** [G148](../goals/memory-evolution.md#g148), [G207](../goals/memory-evolution.md#g207) · **Status:** measurements; each change is its own PR.

Rodrigo 2026-11-06: what waits for Sleep should already help, and Sleep should then make it better; the system should be at least as efficient as Supermemory; and it's for worldwide use. All figures below are on public benchmarks, nothing slept, on the plan with haiku for answers and judge, EmbeddingGemma 2 at 768. Single runs, so a difference of a few questions is noise.

## What the harness can now say

`benchmarks/public` gained, per answer path:

- `closed-book` (no memory), `wrong-bank` (another person's memory), `recall` and `hook` (an agent holding only that door's words answers);
- `doors`: what each door hands over per question, no model call;
- real tokens per answer (input plus output as the engine reports them), per right answer, and the door's own size;
- `--banks-from` and `--reuse-from` (a changed prompt alone is read again), `compare` (who got what right).

Reach ("answer turn") means 40 characters of the dataset's answer turn verbatim in what a door returned. **It flatters a short clip,** because the clip can pass while the fact is cut, so sizes are decided by graded answers.

## LongMemEval_S, 100 questions (every category), before any change

| Door | Right | Tokens per question | Tokens per right answer | Door's own characters, p50 |
|---|---|---|---|---|
| Ask | 71 | 6,241 | 8,791 | prompt 8,106 |
| Recall | 31 | 3,590 | 11,579 | 1,054 |
| Hook | 14 | 2,733 | 19,522 | 0 |
| Closed-book | 16 | 966 | 6,038 | none |
| Wrong person's memory | 15 | 6,082 | 40,544 | prompt about 8k |

Ask by category: abstention 100 (14), knowledge-update 87.5 (16), multi-session 25 (20), single-session-assistant 80 (10), preference 12.5 (8), single-session-user 83.3 (12), temporal 95 (20). Closed-book and wrong-bank right answers are almost all abstentions, so 15 is the floor: Ask's gain from memory is about 56 points. None of 29 wrong Ask answers was confidently wrong.

The 2026-10-20 figures the comparison reports used were different in kind: multi-session 11.7 was before the list work (35 on sonnet after it), and "preference 3/8" was answer-turn reach, not accuracy.

Pending (a list of conversation heads) reached more multi-session answer turns than Ask (50 v 44 of 71). The conversation was found; the turn wasn't picked, because it doesn't use the question's word (orange for citrus, ENT for doctor).

## Comparing with Supermemory

Their "3×" counts a whole agent loop over documents on their own test set, so it isn't in the same unit as anything above:

- [supermemory.ai/research](https://supermemory.ai/research/): "cuts cumulative token usage by 3× on Claude and 1.75× on Codex while improving task accuracy across 110 questions". The page gives no protocol or accuracy figures.
- [smfs.ai](https://smfs.ai/): 20 retrieval tasks. Claude 643,668 → 410,797 total tokens (−36%), correct 16 → 18 of 20. Codex 1,212,380 → 203,427 (−83%), 19 → 19 of 20. It doesn't say whether cached input counts or how many runs.

A fair comparison means running Cicada as an agent loop over the same kind of task. Not done yet.

## Every language: what the word lists miss

150 questions from both benchmarks, translated by haiku into 10 languages. The detectors in `ask_sources` are English and Spanish:

| | English | Spanish | French, German, Portuguese, Chinese, Japanese, Korean, Arabic, Hindi, Russian |
|---|---|---|---|
| Requests for advice found, of 30 | 23 | 23 | 0 |
| Counts and lists found, of 60 | 60 | 39 | 0 |

One public conversation (LoCoMo conv-26) held and asked in each language, 38 questions with an answer turn. Ask reached an answer turn on:

| English | German | Arabic | Japanese | Chinese |
|---|---|---|---|---|
| 25 | 18 | 10 | 0 | 0 |

Two causes: `question_language` knew only English and Spanish, so the meaning leg stayed off for every other language; and the word index holds an unspaced run as one token, so a word inside it can't be found.

With overlapping pairs for unspaced scripts and the meaning leg on for any other language (#693), graded on Ask (haiku on answers and judge, 40 questions, one run each, nothing slept):

| | English | German | Arabic | Japanese | Chinese |
|---|---|---|---|---|---|
| Right, before | 60.0 | 35.0 | 25.0 | 0.0 | 0.0 |
| Right, after | not re-graded | 45.0 | 42.5 | 42.5 | 62.5 |
| Answer turn reached of 38, after | 25 | 21 | 14 | 15 | 20 |
| Tokens per right answer, before | 6,816 | 13,090 | 12,129 | none right | none right |
| Tokens per right answer, after | | 11,085 | 11,537 | 12,402 | 8,051 |

The same questions in German, Arabic, Japanese and Chinese over someone else's English memory: 0 of 160 right. One conversation, translations by a model and unchecked by a person, Korean, Hindi and others not run at this level, and nothing slept.

## How much Sleep adds, and what's missing before it

LoCoMo, 5 conversations, 200 questions, haiku on answers and judge. The unslept run is on dev at `4a6079491` (after #705, #715); the slept one is from before #705, so the slept Ask may be a little low.

| Door | Nothing slept | Slept |
|---|---|---|
| Ask | 61.5 (7,696 per right answer) | 81.5 (11,795) |
| Recall | 53.5 (7,901) | 64.0 (8,459) |
| Full-context control | | 83.5 (39,455) |
| Closed-book | | 3.5 (27,579) |
| Hook | | 2.0 (147,292) |

Before #705 and #715, unslept Ask was 55.5 and recall 52.8.

| Ask by category | Nothing slept | Slept |
|---|---|---|
| Multi-hop (76) | 44.7 | 77.6 |
| Open-domain (22) | 45.5 | 68.2 |
| Temporal (99) | 79.8 | 86.9 |

Slept Ask against full-context: multi-hop 59 v 68 of 76 (10 right only with full context, 1 only with Ask, p = .012), open-domain 15 v 8 (p = .039), overall p = .57. Its multi-hop misses are mostly partial lists and "both did X".

**Unslept multi-hop is a reach problem.** Right when every answer turn reached the prompt: 16 of 17. When only some did: 14 of 37. When none did: 4 of 22. The unslept prompt has room: p50 about 4,900 characters against about 18,800 slept, 54 of 200 under 2,000, and 7 empty, so the model isn't called. Temporal questions, which name their subject, reach far more often (82 of 99 had every turn).

**The fix, #738:** Ask searches by meaning for every question and fills only the room the prompt has left. Haiku, one run each, dev → #738, with tokens per right answer:

| Set | Right | Tokens per right answer |
|---|---|---|
| LoCoMo unslept, 200 | 123 → 138 (p = .004) | 7,695 → 8,527 |
| LoCoMo slept, 200 | 159 → 159 | 12,539 → 12,862 |
| LongMemEval_S unslept, 100 | 77 → 76 | 9,798 → 10,359 |
| The wrong person's memory, 100 | 15 → 15 | |
| One conversation translated, 160 | 94 → 95 | 10,437 → 11,042 |

So the gap to slept on LoCoMo is now 21 questions, was 36. Slept multi-hop depends less on reach: 25 of 29 right with every answer turn on the prompt, 25 of 38 with some, 6 of 9 with none, because pages carry it. The same lines on recall lost (slept 128 → 114), so recall stays on the words.

## An agent running a loop

20 LongMemEval_S questions, nothing slept, haiku, real `claude -p`, one run, before #705, #715 and #730. Tokens counted with cached reads, then without:

| Agent holds | Right of 20 | Per question | Per right answer | Turns |
|---|---|---|---|---|
| Cicada's tools | 13 | 23,586 / 9,187 | 36,286 / 14,133 | 4.5 |
| The bank as files (Read, Grep, Glob) | 15 | 29,079 / 8,753 | 38,772 / 11,670 | 4.9 |
| No memory | 3 (2 abstention) | 1,119 / 1,046 | 7,457 / 6,970 | |

20 questions can't separate tools from files, and plain files aren't worse. This isn't comparable with Supermemory's task set.

Re-run on dev after #715, #730, #734 and #738, the same 20 and the same 6 tools: tools 11 of 20 (3 lost, 1 gained), 22,260 / 9,098 per question, 40,473 / 16,543 per right answer, 4.4 turns. That's noise on answers, and the cost barely moved: these changes don't show in this loop. Recall was called more than Ask in both runs (25 v 20 now), and #738 only helps Ask.

The child `claude -p` named the owner of the plan login in about 1 run of 20 (6 of 20 with all tools), writing a query like "did <owner> buy…" for "did I buy…". Neither the primer nor the bank holds the name, and the memory was a scratch clone, so this looks like the account context Claude Code gives a signed-in session. It may cost a search a word on this loop; no Cicada memory was read.

## The tool list

Before #730 the list was 103,111 characters; #730 cut prose to 73,956 with the same structure. #734 then holds seven recording tools back until a reply names them, for clients that re-read the list: 73,094 to 51,305.

| Client | Re-reads a changed list? | Basis | Tokens saved on each call |
|---|---|---|---|
| Claude Code 2.1.319 | Yes | Tested | 125 of 25,526, measured. It defers MCP schemas |
| VS Code, Gemini CLI | Yes | Source | About 4,700: not measured in those clients; the rate below |
| Cursor, OpenCode | Handlers seen, refresh untested | Bundle, source | 0: they keep the whole list |
| Codex 0.165, Claude desktop | No | Source, bundle | 0: they keep the whole list |

**What a whole list costs when a client loads it:** with `claude -p --tools ""` there's no tool search, so schemas load in full. 50 tools against 6, the same 20 questions: cached reads per turn about 13,500 v 3,000, so about 10,500 tokens a turn for about 48k characters, 4.6 characters a token. The 21,789 characters held back are then about 4,700 tokens a turn. One run. The 50-tool run also scored 16 of 20, which at this size says nothing.

## Tried and dropped

- **Clue searches in Ask** (a model call to widen the search): on current dev, 30 LongMemEval_S questions, no model grading: turns 71 to 79 of 87, questions 28 to 29, prompt 11k to 23k, plus a model call each. #705 had taken the gain.
- **The hook by vectors:** everyday asks on a real clone score a top passage of p50 .744, p90 .756; real questions p50 about .73. No floor separates them, so it would speak on everything. Reach of 38 on one conversation, Ask / recall / hook: English 25/18/5, German 25/13/0, Arabic 18/13/2, Japanese 25/17/0. **The hook stays word-based and weak outside English.**
- **Reading a count or a list by examples outside English:** the word shape finds them 60 of 60 in English, 39 in Spanish, 0 elsewhere. Comparing with examples finds 30 to 42 of 60 per language, with 9 to 13 of 90 false alarms. On Ask, German, Arabic, Japanese and Chinese went 95 to 99 of 160, but the answer turn reached the prompt no more often (94 v 93 of 152) and multi-hop stayed flat, so that's noise. **The shape stays English and Spanish.**
- **The same meaning lines without counting pages:** slept Ask stayed 159 at 9% more tokens.
- **Lifting Ask's conversation order by recency:** 71 to 66 at weight .3, 71 to 71 at .1 with temporal 19 to 17. Ask keeps its reserved newest slot; recall and search take the lift (#722, #728).

## Noise, and what a stronger model doesn't fix

- **Judge:** haiku 77 v sonnet 75 on the same 100 Ask answers, 6 flips, no bias. A difference of a few questions is noise.
- **Multi-session:** of 12 misses, 6 had every answer turn on the prompt. The same 20 prompts answered by sonnet: 5 right v haiku's 8, haiku judging. Mostly over- and under-counting events. A stronger model doesn't fix it on this sample.
