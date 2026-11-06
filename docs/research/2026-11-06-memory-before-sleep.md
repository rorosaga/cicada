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
