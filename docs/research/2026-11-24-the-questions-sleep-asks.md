# The questions Sleep asks, audited (2026-11-24)

The owner, 2026-11-24: "the fewer the asks the better." This audits every inbox question the stored consolidation
benchmark banks hold (two invented people, Ines and Noor; 281 banks, 543 question files; invented names only), reads each
against the fixture's conversations, and says which could have been answered by the record.

Readings: **(a)** the record already answers it; **(b)** nothing on the record can, and the answer changes what an agent
reads; **(c)** nothing answers it but the answer changes nothing an agent would read; **(d)** malformed, or not in doubt.
"Settled by Sleep" rows were raised and closed in the same run by Sleep itself: the person never sees them as an open ask.

## The table (pending = asked of the person)

"Current" is the last 15 runs (27 banks: ended-after, ended-before, samename-final, samename-join); "older" the other 254 banks.

| Question | Reading | Current | Older |
|---|---|---|---|
| `sensitive`: "1 conversation may hold a password" (one per Ines run) | b (rail, ruling 60) | 12 | 120 |
| `merge_suggestion`: a held full name vs the page of its short name ("Is <Full Name> the same as <Short>?") | a (the raising turn names both) but ruling 29 / 74 make it a question | 12 | 119 |
| `merge_suggestion`: a held study mention vs the page of the same study | a or b (see below) | 5 | 89 |
| `merge_suggestion`: first name vs a full-name page | b | 2 | 9 |
| `merge_suggestion`: two people sharing a first name | b (other worker's code) | 1 | 5 |
| `clarification` "Who or what is <name>?" | a | 3 | 15 |
| `clarification` "What's <role>'s name?" (a person known by a description, said once) | c | 1 | 7 |
| `conflict`: "signed up" vs "registered" | a? | 0 | 6 |
| `page_edit`: a revision's date | b | 0 | 1 |
| settled by Sleep: "Who or what is <name>?" (`said_on_record`) | a | 7 | 74 |
| settled by Sleep: "Confirm a predicate fold" (`subject_gone`) | d | 8 | 36 |
| settled by Sleep: decay on a trip page (`not_fading`) | ? | 3 | 3 |

Where the question stays and why (engine-free replay of `inbox_tend.policy` over every pending file): all 106 held-name
questions stay as `person` (who someone is stays the person's); all 77 study questions stay as `judgement`; every
"Who or what" clarification stays as `needs_person` until the record read (move 3) settles it.

## Readings worth stating

* **Held name vs short-name page (the largest class, 131 of 281 banks).** The person's own turn says "Teo today. <Full
  Name>, my old teammate"; two later turns say Teo works at the same company. A reader would say one person. Sleep asks
  because rulings 29 and 74 never let it join a person on a name alone, and ruling 74's "never named together" clause
  reads this raising turn as two names. Not changed (a ruling); see the owner question in the report.
* **Study vs study (94).** `inbox_tend._merge_rule` compares the stored type: the page is a `concept` (ruling 56's
  fallback page, `proposed_type: project`), the mention a `project`, so the judge never ran. Stage 2 already reads a
  fallback page as a project (`entity_resolver._candidate_types`). Tried: reading it so in the tend. The judge then
  answers `different` 0.6 to 0.8 on 16 of 16 (the pair reads as "a feature of the app" against the app), adding the raising
  conversation's title and the person's lines changed nothing (15 `different`, 1 `unsure`). Nothing was gained and a
  wrong `different` would keep two pages of one study apart, so it was dropped. The fixture's own answer ("the eight
  participants" of both) is an inference no judge made.
* **"Who or what is <name>?" (18 pending).** The record answers all of them but two. The settle is refused by
  `answer_supported` ("every word of the answer is in the quote") when the engine writes the answer in its own words or
  language: 11 of 18 replays refused, "Their sister, who is moving to Valencia" against "Mi hermana Lucía se muda …".
* **"What's <label>'s name?" (8).** Stage 1 titled a guitar teacher of the owner's partner "Portuguese guitar teacher"; the
  page is marked a nickname (`nickname_title`) and asked for a name, once, on a page of confidence 0.3 that is already
  decaying. Once the question was "What's the name of your teacher?", a relation to the owner the person never stated.
  Not changed (no language-free way to tell a label the model wrote from a name the person used, short of asking only on
  2+ conversations, which the nickname ruling of 2026-10-27 may not want).
* **Decay on a trip page.** Raised and settled `not_fading` by Sleep in all 6 stored cases; never an open ask here. The
  lead (a trip page, last mention 6 days before the run) is the benchmark clock: Sleep counts silence from the real day.

## The change

A free-text answer is now the quote's own words, and a second read of the line alone decides that it states the answer
(`inbox_tend._confirmed`). Replay of the product's own move 3 over the 18 stored pending "Who or what" questions
(Haiku, three repeats): settled 6 of 18 before; 16, 16, 14 of 18 after. Forcing every single line the record holds through
the new prompt, one at a time: the second read alone rejected 5 of 5 weak lines (a line that only names the subject:
"Cartolina is at 85 cards sold", "Tomas and I adopted a cat") and kept the 4 defining ones; end to end, 15 of 16 lines the
old check refused were defining and one weak line ("cartes Cartolina") was accepted once.

Benchmark, three runs each side, clock 2026-11-24: questions asked of the person 3, 3, 3 before and 3, 4, 5 after; the
extra after were a person-pair merge, a conflict on a moving van and a "who is Idris" the first read did not answer, none on
the changed path. Run-to-run variation in what Stage 2 raises is larger than the change; the benchmark cannot show it.
