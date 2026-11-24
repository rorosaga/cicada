> **Status note, 2026-11-24 (added by the docs PR that records rulings 79 and 80; the planner's draft follows unchanged except that
> machine-local paths are removed, "map" references now read "the reading notes, not kept in the repo", and code names that carried the
> retired word for the old behaviour are described instead of spelled).** What has been decided differently or built since the draft:
>
> - **Ruling 80 as recorded in `docs/goals/TODO.md` is the truth; section 5.1 below is the draft.**
> - **The owner withdrew the index-only rule of ruling 62 and the saved-list half of ruling 30.** Built so far: what a saved post says is its
>   author's, never the person's, and connector posts no longer read as his words (#858, Track 2a, with its repair report-only); the
>   saves benchmark with today's baseline (#861, Track M). Being built: saves alone make no page or mention, and the per-page and per-name
>   bounds (Tracks 2b, 2c). **Not yet on:** saves do not wait for Sleep yet. That switch (Track 1) waits for the owner's answer on pace and
>   cost (he was given measured numbers: about 2 model calls, 13k input and 1.8k output tokens a save) and ships with a daily allowance for the
>   older pile, which amends his rulings 13 and 16 in one place: **pending his confirmation.**
> - **The coordinator's readings, not the owner's words:** watch history, feed items and records he did not save stay as they are; a
>   save nobody talked about raises no question; going deeper follows his talking; and Sleep reads the public page behind a saved link
>   (section 3.7 below had this off by default; it is now the coordinator's reading that Sleep does, through the existing page reads and
>   their gates). "A save with nothing but a title and a link is not sent to a model" (3.3) and the 25-a-day first number (3.2) are the
>   plan's, not decided.
> - Section 0.3 (b)'s live defect (a connector post read as his words) is fixed (#858). Ruling 79's (a) reposts are built (#860).
> - Track 0 of this plan is the docs PR that carries this note.

# Saving is the reason: ruling 80 and its tracks (G246)

Planner output, 2026-11-24, revised after two critics (section 12). Code read at dev head `0f63882ba` in the sources worktree; every `file:line` was opened again unless it says "per
map" (the reading notes, not kept in the repo). Placeholders only; nothing run, built or written in the repo; no bank read. Track 0 commits this as `docs/plans/2026-11-24-saves-are-read.md`. The other
plan (`2026-11-24-sources-answers.md`, ruling 79) is "plan2", its tracks "plan2 Track N".

The owner's words that settle this, verbatim: "Omg no. remve that ruling. if i save it already has a reason. Maybe i didnt write it explicitly but should work still. This is for every
source." Earlier the same day, still standing: saves should be kept "but those that i actually go ahead and talk about are way more important and maybe worth
using the claude video skill to pull the transcription, maybe even frames and watch it"; "a clear logic i believe should be established to not blote cicada memory with shit, but making it
aware and powerful to go deeper in the things i save"; "I want to leverage the power of the embeddings model we use which is multimodal". And he wants to be asked less.

---

## 0. What the reading found that shapes the plan

1. **One predicate carries the whole old rule.** `history_index.kind` (`api/services/history_index.py:110-143`) says `list` or `saved` for a save, and `waits_for_model` (`:254-258`) keeps any
   `kind` that is not `None` out of Sleep. Capture stamps `processed: true, processed_by: index` at write (`media_ingestor.py:2249-2256`) and Sleep's first step retires what still waits
   (`sleep_cycle.py:1849`, called at `:2108` before ids freeze at `:2407`). Most readers of the rule are derived from that one predicate and change by themselves.
2. **A code change alone does not make the saves already kept wait.** What keeps one out of the queue is the stored pair `processed: true`, `processed_by: index` (`history_index.py:152`). Old saves need a
   step that puts them back, the inverse of `retire`; the pattern exists in `wake` and `mark_person_words` (`:216-251`).
3. **Reading a save today gives the wrong picture of it, in two ways.** (a) Stage 1 is told it is reading a "conversation" (the source-note chain at `entity_extractor.py:1157-1161` has no
   saved-item note) and a claim from a save is Cicada's own reading, observer `agent` (`assistant_observer` finds no correspondent or harness for a save, `:540-546`; default at `:1603`, per the reading notes).
   (b) **X API and Pinterest connector saves are read today as the person's own words.** The tweet text rides `RawItem.note` (`connectors/x.py:389-415`, "lands in the episode body's '## User note'
   section"; Pinterest `connectors/pinterest.py:201`), `## User note` is a PERSON section (`evidence.py:132`), and `write_media_episode` stamps `has_note` for any note (`media_ingestor.py:2252`),
   which makes `kind()` None (`history_index.py:132`), so Sleep reads them now with the post as his words. This is a live defect, independent of ruling 80, and the one place a stranger's words
   can land on the owner's page today. Reading everything else before fixing both would write other people's words as Cicada's own belief and his. So the content tracks ship BEFORE reading turns on.
4. **Each save counts as its own conversation for the 2+ page rule** (`promotion.conversation_keys`, `promotion.py:177-232`: only a captured session, an agent-memory note and an agent-saved note
   collapse). Two posts naming one thing would mint a page. A save is a dated mention for decay (`episode_time.counts_as_activity`, `episode_time.py:61-65`, false only for untimed sources
   and feed items), so a bookmark dated years ago would start a page's clock years ago.
5. **Questions are mostly handled by a derived rule.** `inbox_service._subject_quiet` (`inbox_service.py:552-559`) never serves a question about a quiet page, and `quiet_pages.is_quiet` never
   lets a claim whose observer starts with `external:` light a page (`quiet_pages.py:108-125`). Once a save's claims are `external:`, pages born only from saves stay quiet and ask nothing.
   The belief slot is keyed by observer (`claim_reconciler.slot_observer`, `claim_reconciler.py:103-128`), so an `external:<author>` claim never conflicts with the person's own.
6. **There is no per-run cap, and the owner forbade one** ("i dont want to cap the max episodes per sleep", ruling 13, `TODO.md:1811`; scheduled runs drain too, ruling 16, `TODO.md:1952`). A run is a
   frozen oldest-first list of everything waiting (`sleep_cycle.py:2407`; `sleep_drain.py:281-296`), so the cost design cannot cut a run, only decide **how a backlog becomes waiting** (3.2).
7. **"Waiting" feeds four other things, so it must never hold a backlog.** `sleep_debt` counts `waits_for_model` (`sleep_debt.py:181`) and measures the queue against one cycle's cap; the
   `after_import` probe starts a run every five minutes while something readable waits and has settled (`sleep_scheduler.py:370-385`); the missed-run catch-up fires on the same count
   (`sleep_catch_up.py:264-268`). Thousands of waiting saves would pin the gauge and chain runs.
8. **Which stops block tomorrow.** A scheduled run's pause blocks the scheduler unless its reason is `restart`, `engine` or `busy`, or a plan window after its reset; `spend`, `reserve`, `overage` and
   `key_limit` stay the person's (`sleep_paused.py:41,46,108-125`; ruling 16). The drain loop already ends a reserve stop with nothing left waiting as a finished run (`sleep_cycle.py:2646-2649`).
9. **Decay and the page reads run in the batch that empties the queue** (`is_last = more == 0`, `sleep_cycle.py:2605`; `decay=is_last and not ds.decay_ran`, `:2614`). With saves read last, a stop
   anywhere in them would skip decay for the night.
10. **Feed items: the code and the docs disagree.** A pageless feed item has `media_entity_id: ""` (`media_ingestor.py:2539`), `_is_bare_save` needs `media_entity_id` and `url` (`history_index.py:156`), so
    `kind()` is None and a model reads it today with `feed_note` and no mention (`entity_extractor.py:1148-1151`), though the docs say indexed (`capture-and-sleep.md:4815-4821`, per the reading notes). This plan keeps the
    code's behaviour (question 2) and fixes the docs.
11. **The saved-item finder already serves media pages, read or not** (the finder module, `:184-185`). Only two things in it are tied to "unread": the `read` flag (`:96-103`, `kind in (saved, list)`, wrong for a save
    waiting in the queue) and the tab-group hit (`:111`, `is_unread_save`).
12. **CLAUDE.md is 59,655 characters** (`test_claude_md_size.py` fails above 60,000); ruling 80's rail edits are about +15 (5.2), so plan2 Track 0's 345 stay its own.

---

## 1. The behaviour, as a person sees it

**The rule in one sentence.** When he saves something, Cicada takes that as his reason. Sleep reads what he saved the way it reads anything else he gives Cicada, after his conversations, and
keeps only what the thing itself says, marked as the author's words and never his.

### 1.1 From the moment a save is kept, by kind of source

- **A bookmark in a browser he turned on, a link he pastes or sends from the notch or the phone, a link his own agent saves for him, a save he clicks inside a site.** Kept the moment it arrives:
  title, link, site, day and whatever description the site gave. That night Sleep reads it. If he wrote why, his words are the reason and are read as his. If he did not, the save is the reason and
  the page's text is read as what the page says. A save that holds nothing but a title and a link has nothing for a model to read: it is kept as a page, searchable, and read the day he talks about it
  or his agent opens it (3.3).
- **A tab group.** One record per group, read once. A later change to the group is not read again; the record is updated in place. What he says about a group in a conversation reads it again.
- **A post from a saved list he turned on, an upvote, a like, and (plan2) a repost; an export archive.** X bookmarks and likes, Instagram saved and liked, LinkedIn saved, Reddit saved and upvoted,
  Pinterest, TikTok, Spotify library, Substack saved, GitHub stars, YouTube playlists. All are his acts and are read like a bookmark, **a day's worth at a time** (3.2). What Cicada holds is the words
  the list showed (at most 500 characters) plus author and day. Nothing more is fetched for a walled site.
- **The pile.** Everything that arrives in bulk (a first whole list read, an export, a browser import of years of bookmarks), everything already kept, and a save received long after the day it
  was saved, waits its turn: each night Sleep takes a fixed number of them, newest first, after all his conversations (3.2). They are kept and findable meanwhile.
- **What stays as it was** (question 2 asks about each): watch history (not a save: he did not save each video); follows (a directory no model reads); his own repositories, joined communities and
  open Safari tabs (records another service keeps for him); a locked note; books (their own rules, 61 to 71); feed items stay exactly as the code treats them today (read as the publisher's
  words, no mention). A like, an upvote and a repost on a list he turned on are his act and are saves.

### 1.2 What Sleep leaves behind (said without internal words)

- On the save's own page: one sentence of what it is about, marked as from the post's author (or the site when there is no author), dated by when the post was written, the lists it came from, and a
  few connections to pages he already has that the post names in full (at most five). The page's picture and link card stay as they are.
- On pages he already has: a fact the post states about them, marked as the post author's, dated, never written over what he said himself, at most twelve such facts on one page, the same fact
  from several posts folded into one with all its sources (4(b)). It never becomes his belief.
- Not left: a page for every name in a post; a fact on his own page from someone else's words; a question; a skill. A name met only in saves is held (three lines at most per name, from saves)
  and waits. It gets a page when he talks about it too, because then it has two kinds of source. Saves with no words of his count together as one source for that rule, however many.
- A name in a post joins a page he already has only on an exact full name or alias ("Sam" in a stranger's post never joins his friend Sam). A save with no words of his starts no page's clock when it
  creates the page; on a page with other sources it is a mention on the post's own day, once a day (4(b)).

### 1.3 What the Sleep queue and a source's page show (words only; no layout change)

- A save that waits for Sleep is a row in the Waiting list like any item, under its source. A save that waits its turn is one line where the Waiting list's last card sits today
  (the Sleep page's last Waiting card, per the reading notes; copy `Theme/Copy.swift:159-161`): "N saves not read yet. Sleep reads about 100 a night, newest first, about M nights. Talk about one and it
  is read first." The API field stays `kept` (`routers/sleep.py:420`, per the reading notes); only its meaning and copy change.
- A source's stream for a saved list says "read by Sleep" (the existing `depthRead`, `Theme/Copy+Streams.swift:78-79`, per the reading notes). A row says one word: **Read**, **Not read yet** (waiting, or in the
  older pile; the line above says how long), **Nothing to read yet** (3.3), **Waiting for your agent** (his words named it and an ask is open) or **Watched**. Feed items say "read as the
  publisher's words"; watch history, follows, open tabs and records say "kept, never read: you did not save it".
- Recall, Ask and the hook's note stop saying "no reason given and nobody has read them" (`mcp_tools.py:2712`, `ask_service.py:1652`, `recall_text.py:30-34`, per the reading notes). A save not read yet says "saved, not
  read yet". A read save is an ordinary page with its sentence and facts. What is embedded for a save not read yet is its words only (the search index, the saved-item finder's `by_meaning`); pictures
  and frames follow his talking (plan2 Track 6) and are not embedded for a plain save (question 5).

### 1.4 What changes for the things he talks about

A save he talks about is read first, ahead of every other save and the pile. Talking about it still does what ruling 78 (e) built: it leaves an ask for his own agent to go deeper (a transcript for a video,
the post itself for a walled site, pictures if he turned that on in plan2), only while agent reading and that list are on, at most 5 a conversation and 5 a day. Cicada starts no agent. His words also light
the page, so questions about it may then be asked. A save he never mentions is never asked about.

---

## 2. The invariants any implementation must keep

Each is a test or a measured gate (section 6).

1. **Whose words.** A save's text is its author's, never the person's, **for every door including the X API and Pinterest connectors** (3(b) above): connector post text is written as a
   `## Description`, never `## User note`, and no `has_note` is stamped for it. Spans in a save are `page` outside his reason sections (`authorship.of`, `authorship.py:90-102`;
   `evidence.PERSON_SECTIONS`). Claims drawn only from page spans carry `external:<author or site>`. Only the person's own reason, note or why-answer sections count as his.
2. **Nothing on the owner's page from someone else's post.** No claim whose subject is the owner (`owner_identity`, `entity_extractor.py:708-712`) and whose located evidence is not in his
   own sections. "I", "my" and "the user" inside a post never resolve to him (G169). Nothing from a post lands as an alias on a person page.
3. **No page for every name in a post.** A save alone never mints a page. At most 8 entities are taken from one save. A name in a post is held, never lost (`pending_store`), at most 3 held
   lines per name from saves.
4. **The 2+ rule counts saves with no words of his together as one source** (`promotion.conversation_keys` returns one shared key for them). A save with his own reason, note or why-answer keeps its own
   key and counts as a conversation. No rung of promotion can fire from a save alone: `substantive` needs `named_by_person` and 3 exchanges (`promotion.py:146-148`), and a save yields exchanges only
   from his own sections.
5. **No questions from a save nobody talked about** (reading c). A page whose only evidence is saves is quiet (`inbox_service.py:552-559`, `quiet_pages.py:100-125`). Stage 1's `ask_person` is dropped for
   a save (`entity_extractor.py:1317-1319`). A same-name doubt or a conflict whose only evidence is saves raises nothing. Gate: zero.
6. **Conversations never starved, and a night never blocks the next.** Every non-save is ahead of every save in every run. A run that stops inside the saves part has already filed every conversation
   (each batch is committed). **A line the person set (spending limit, plan reserve, key limit, extra usage) or a plan window reached while only background saves remain is a finished run, not
   a pause** (3.4): no pause record, the scheduler is free the next night, the saves not read go back to the pile. The test goes through `sleep_paused.schedule_may_replace`.
7. **The spending limit and plan pauses hold, unchanged.** `SpendGuard` shrinks the next batch to what the allowance buys and a model with no known price stops the run (`sleep_spend.py:56-124`).
   A scheduled run uses a plan only through its switch (ruling 4/4b/4c). No new guard.
8. **Waiting never holds a backlog** (section 0.7): the count of waiting saves at any moment is at most the day's allowance plus the saves he made singly in the last day or two. Gate: after a
   bulk list read of 5,000 rows, `sleep_debt` counts at most the day's allowance; the `after_import` probe fires no second run in the same local day for saves.
9. **Retrieval does not regress.** Ruling 62 measured recall 12/12 by words, 3/3 by meaning and the hook's note 12/12 (`TODO.md:4061-4082`). After this change the same cases pass for a save in the
   pile, a fresh save waiting, a save with nothing to read, and a read save.
10. **A read save is not read again.** The exception is the one that exists: the person's own words added to it (a why-answer) read as a revision of that save only (G104).
11. **Dated honestly.** What a post says is dated by when it was posted (`posted`, else `published_at`), never by the day Cicada took it in; with no date the model is told not to write it as current.
12. **Bounded per page.** At most 12 open save-derived claims on one page (the newest by evidence date win, an older one is closed with the git history behind it); one claim per predicate and object, with
    many sources, when several authors say the same thing.
13. **No LLM at capture time.** Capture stays file I/O (the nothing-to-read check, 3.3, only looks at what capture already holds). The quick read stays opt-in (ruling 36 D2).
14. **Every existing rail not named in 5.1 stands.** Walled sites are never fetched (ruling 30's ToS rail, `_excluded_media`); the connector fetch gate still gates Sleep's own page reads;
    rulings 53, 64, 71, 68, 56 (links by a recorded fact; 5.1 (e) records the one narrowing), 55, 60 (a save passes `sensitive_flags` like any episode, `entity_extractor.py:1137`), 12 (no prices
    outside Past reads: the new line shows counts, not dollars). Copy is provider-neutral.

---

## 3. How a save is read without swamping a night or the bill

### 3.1 Order (one stable partition of the frozen ids, at `sleep_cycle.py:2407`)

Three classes, each keeping its own order:
1. everything that is not a save, oldest first as today;
2. saves he talked about (`read_asked` stamped by his own words), newest first;
3. background saves (the day's released pile and the singles he made), grouped by origin, origins ordered by their newest save, newest first within an origin (so a batch holds one origin and
   Track 3's grouped read has something to group).

No class is cut: the freeze reads everything waiting at its start (ruling 13). New module `api/services/saved_order.py` (one function) so the change is one call at the freeze. Decay and chronology are
unaffected: a conversation read late counts as read the day it was said, and entity writes use each source's own timestamp (`sleep_cycle.py:4000-4010`, per the reading notes).

### 3.2 Pace: how a backlog becomes waiting

A save **waits its turn** when it is stored `processed: true, processed_by: index` (the old pair, kind `saved`/`list`). A save is stored that way at write (`write_media_episode`,
`media_ingestor.py:2249-2256`) when (i) it came through a bulk door: `ingest_batch` with more than `BULK_ITEMS = 10` new items in one call, an export or archive parse, or a list pass, whatever
its dates; or (ii) its own saved day is more than 30 days before it was received. Every save already kept in the bank is stored that way today. A single save (a click, a paste, a notch or
site save, a connector poll of a few) is written waiting (`processed: false`) and is read that night.

Once a local day, `history_index.take_turns(memory_path, budget)` (a new step in `_index_without_model_safely`, after `retire` and `wake_lit`, `sleep_cycle.py:1849-1863`) **releases** saves from
the pile: `budget = SAVES_PER_DAY - released_today`, where `released_today` counts episodes whose frontmatter `turn_released_on` is today's local day, newest saved day first (else `posted`, else
received; ties by id), skipping dirty files and deleted sources, flipping `processed: false`, dropping `processed_by`, stamping `turn_released_on`, in the existing `COMMIT_STEP` commits
(`history_index.py:321-390`; manifest line `queued`). It does nothing on a `tail_only` run. Because the budget is the day's, not the run's, a person's "Sleep now" for one conversation, an
`after_import` run and a catch-up run together read at most `SAVES_PER_DAY` saves a day from the pile and the probe never chains: once released saves are read, nothing readable waits.

`SAVES_PER_DAY = 25` when this ships; the coordinator reads the first nights' results one save at a time (7) and raises it by a one-line PR (the target is 100, 3.6). **Kill switch:**
`history_index.SAVES_READ = False` restores today's behaviour (capture writes every save index-only, `take_turns` releases nothing, `retire` retires again). **Revert:** `return_to_pile` (the
inverse of `take_turns`, also used by 3.4) puts any released day's saves back; each release is a commit whose manifest names its paths.

This amends ruling 13 and 16 in one place and ruling 80 says so plainly (5.1 (c)): **an allowance on how many saves enter the queue a day.** Nothing that is waiting is ever cut, and the
owner is asked (question 1).

### 3.3 A save with nothing to read is not sent to a model

A save whose capture holds no words beyond title, link, site and day (no `## Description`, no preview, note or reason: `write_media_episode` builds the body at `media_ingestor.py:2118-2141`; a
LinkedIn export row, an Instagram export row, a Reddit export permalink, a Spotify track, a YouTube playlist row, a bookmark whose page gave no description) is stamped
`processed: true, processed_by: no-words` at write: file I/O, no model. Its page keeps the link, it is found by title (the saved-item finder), and it is read when he talks about it or his agent opens it,
exactly what a title-only bookmark gets today. Ruling 62 measured that reading such a save mostly restated its title (25 bookmarks, 56 calls, `TODO.md:4061-4082`); sending a link with no text to a
model can only invent. A mention leaves the ask for his agent and wakes nothing (there is nothing to read). `history_index.NO_WORDS_BY` and one helper `history_index.not_read(fm)` (kind
`saved`/`list`, `no-words`, or a waiting save) are the one place the words "not read yet" come from. Question 1 asks him to confirm.

### 3.4 Stops, decay and the pile

- **A line reached with only background saves left finishes the run.** At the line check (`sleep_cycle.py:2596-2600`) and where a batch's stop is read (`:2641-2650`, which already ends a reserve
  stop with nothing left), a stop of kind reserve, spend, key limit, extra usage or plan window while only class-3 saves remain is `stop = None`: the unread class-3 ids go back to the pile
  (`return_to_pile`, which **keeps** `turn_released_on` so the day's budget stays spent), no pause record is written, nothing needs Continue, and the scheduler is free the next night. An `engine`
  stop stays a pause (the engine is broken for everything). His conversations and talked-about saves stop as they do today.
- **Decay and the page reads run in the batch that holds the last non-background id** (or the first batch when none): `is_last` for `decay` and `links` becomes
  `more == 0 or ds.decay_batch in taken` (`sleep_cycle.py:2605-2615`, `ds.decay_batch` set at the freeze in `DrainState`, `sleep_drain.py`). The existing once-only guard (`ds.decay_ran`) and the
  fallback pass at `:2678` stay, so a run that stops in the saves part has already decayed.
- **Per-page and per-name bounds** (invariants 3 and 12) are Track 2c.
### 3.5 Short saves from one origin are read together (Track 3)

Today Stage 1 is one call per episode (`entity_extractor._extract_chunk`, per the reading notes `:871-931`; no grouped read exists, not found), and a save's 60 to 250 tokens ride a 7,900-token fixed prompt
(ruling 62's measure). A grouped read sends up to 25 saves of one origin (at most 1,500 characters each) in one call with the same prompt, each block labelled with its own text and its
own date note (3.8), and reads the answer only when it lines up exactly (`json_parse.numbered_rows`, `json_parse.py:98-127`, per the reading notes). Otherwise the whole group falls back to one call per save: a bad
answer costs money, never facts. Each claim's evidence is located only in the save it came from; a quote lifted from a neighbour becomes `reasoning` and the claim is still written. Everything after
Stage 1 stays per save. A tab group and any save over 1,500 characters read alone. Because 3.1 groups by origin, a batch is mostly one origin; Track 3 asks for the 50 ceiling on a batch of
background saves only (`sleep_run_prefs.py:12-17`, `sleep_drain.py:247-269`) and skips Stage 4's skills call for it (`sleep_cycle.py:3458`). It ships only if grouped evidence locates at least as well and
the measured calls per save over mixed origins are under two.

### 3.6 Cost, with basis (estimates are marked; the first nights replace them)

Measured (scratch banks, Claude plan at haiku, ruling 62 and the G236 row, `TODO.md:4061-4082`): 25 bookmarks read in full = 56 to 57 calls, 269k to 272k input tokens (gross of cache), about 2.5
minutes; Stage 1 is 25 calls of about 7,900 input tokens each. The owner's real run of 25 was 78 calls and 469k tokens (with the tail). **Output tokens were never measured** (`saves-cost.md` 1.3) and
are 70 to 85 percent of the dollars below, so every dollar figure is an estimate (2k output a save single, 1.5k grouped, mine).

| | calls/save | input tokens/save | basis |
|---|---|---|---|
| Single read (what ships first) | 2.25 | 10.8k | 56/25 and 272k/25, measured |
| Single, real-bank shape | 3.1 | 18.8k | 78/25 and 469k/25, measured |
| Grouped (Track 3) | about 1.25 to 2 | 3.5k to 6k | my arithmetic; replaced by Track M's mixed-origin leg |

Dollars a save, single read (`price_supplement.py:28-43`, per million tokens: haiku 5.5 is 0.1 in, 0.01 cache read, 0.5 out; haiku 4.5 is 1, 0.1, 5; 70 percent of input cached on the Anthropic
engine, `anthropic_engine.py:15-22`): **about $0.0014 on 5.5, $0.014 on 4.5**; on a path with no cache control (LiteLLM keys) about $0.0021 and **$0.021**. A day at `SAVES_PER_DAY` (the 20 he
saves singly add about $0.28): 25 saves, $0.35 on 4.5 ($0.52 uncached), 2.5 minutes; 100, $1.4 ($2.1), 10 minutes; 300, $4.2 ($6.2), 30 minutes. Against the $5 default line per run (`DEFAULT_USD = 5.0`,
`sleep_spend.py:40-42`) 300 a day would hit the line on 4.5 once conversations are counted, which is why the pace is a daily number small enough to leave room and why 3.4 finishes the run, not pauses it.
On a plan there is no dollar figure; the Past reads run detail shows plan use (ruling 12) and the first night's ledger is the measurement. The grouped read, if Track 3 measures it, is about 0.6 of the
single (estimate).

The pile: 3,450 assumed (450 list saves, 3,000 bookmarks). The repo's own figures are larger (one export held 3,156 playlist saves, `TODO.md:2465`, plus 377 and 76 list posts per the reading notes); the dry run
replaces this. Nights = pile / `SAVES_PER_DAY`: 138 at 25, 35 at 100, 12 at 300, less every nothing-to-read save (3.3). **Track M's single-read leg (output tokens by stage,
`benchmarks/perf/ledger.py`) is a precondition of Track 1**; `SAVES_PER_DAY` is set from it and the allowance, not from the table.

### 3.7 Public pages of saved links (what reading adds)

The page-read exclusion for saves (`link_enrichment.py:301-310`) keeps page reads off a page every one of whose episodes is `saved` or `list`. Left alone, a save read by Sleep, or released and waiting
(kind None), would join the page reads, a new network behaviour set by silence. **This plan ships it off:** Track 2b changes the page-read exclusion for saves (`link_enrichment`, the function that skips a page every one of whose episodes is a save) to "every episode is a save with no words of his and no
mention", whatever its read state, so a saved link's page is still never fetched or summarized unless he gave a reason or talked about it. Question 4 asks whether to turn it on. If on, the page
reads are the existing ones: 20 summaries in a run and 20 backfills a night (`config.py:259,269`), behind the connector fetch gate, never for a walled site, a video, arXiv, LinkedIn or Instagram
(`_excluded_media`). The in-cycle pass takes the most recent first (`link_enrichment.py:321`) and the whole-bank backfill the **oldest-imported first** (`:1168`), so a 3,000-bookmark pile
gets summaries slowly (months) and not in the order of his interest.

### 3.8 Dating what a post says

A save's `timestamp` is the day he saved it, or the day Cicada took it in when no save day exists, and a list read sets only `posted` (`media_ingestor.py:2235-2238`, per the reading notes). The old
`date_note` would tell Stage 1 "this conversation is dated <that day>" and a 2021 post's "X is the CEO of Y" would be written as current. `source_dates.saved_note(episode, today)` (new, beside
`feed_note`, `source_dates.py:105-115`, the ruling 39 shape) says: "this is a saved item the person did not write, posted <day>; today is <day>; it is the author's text, not the person's words;
what it says holds as of its post day", and for a post older than the 90-day rule (`source_dates.py:72-92`) "write it as of <month year>, never as current"; with no `posted` or `published_at`:
"its post date is unknown: never write it as current". Claims take `valid_from` from the post day when known (`_claim_date`, `entity_extractor.py:1495-1499`, reads it from the same record).

---

## 4. The readings (a) to (d) in code

All constants live in two places: `history_index.py` (what is index-only) and a new `api/services/saved_reading.py` (note, observer, mention, caps), so each reading is one line to undo.

**(a) Watch history is not a save; a like, upvote or repost is.** `kind()` keeps `history`, `month`, `traces`, `reading`, `listening`, `locked`, and gains one kind, `record` (origins
`github-owned`, Reddit "Joined communities", `safari-tab`: today's `NOT_MENTIONABLE_*`, `history_index.py:160-175`, plus the open tab, which the module itself says is not something he kept,
per the reading notes `safari_tabs.py:189-196`), index-only as today and shown "kept, never read: you did not save it". **No `feed` kind** (section 0.10): a feed item keeps what the code does today.
`kind()` returns `saved`/`list` only for a save stored waiting its turn: `_is_bare_save` and the `LIST_ORIGINS`/`LIST_FOLDERS` branches (`history_index.py:68-77,143-157`) require
`processed_by == index`. Likes, upvotes and reposts need no change: their origins are in `LIST_ORIGINS`/`LIST_FOLDERS` and plan2 Track 4's `x-reposts` row works unchanged. Questions 1 and 2 ask
about `no-words` and about each record kind. To undo: remove `record` or `SAVES_READ`.

**(b) A save's words are its author's.** Edits, all behind `saved_reading` unless named:
- **Connector text** (invariant 1): `connectors/x.py:414` and `connectors/pinterest.py:201` pass the text as `preview=` (`RawItem.preview`, `media_ingestor.py:127`, which `prepare` turns into the
  page description when the page gave none, `:2638-2639`) and not `note=`; for a walled origin (`x-bookmarks`) the connector's text wins over enrichment (a host in `_excluded_media` is never
  enriched, so the implementer confirms no login-wall text can arrive first). `reading_walls._TEXT_IN_NOTES_ORIGINS` (`reading_walls.py:52,161-162`) folds into `_TEXT_IS_DESCRIPTION_ORIGINS`.
  A one-pass heal (`api/services/connector_text.py`, called from `_index_without_model_safely`, one commit, undoable) finds episodes of those origins whose body has `## User note` and `has_note`,
  no `saved_why` and no reason, and renames the heading to `## Description` and drops `has_note`. Claims Sleep already wrote from such episodes stay in git; the dry run counts them for the owner.
- A saved-item source note to Stage 1 beside `agent_save_note` (`entity_extractor.py:548-559`, chain at `:1157-1161`): "This is a saved item. The text is the page's or the post author's words,
  not the person's. The person saved it and nothing more is known of why. Take only what it is about and what it says about named things. Say nothing about the person. At most 8 entities."
  With the dated note of 3.8 in place of `date_note`.
- The observer rule: for a save, claims whose located evidence is all `page` get `external:<slug>`, the slug the post's author (`channel`), else the site. Per author, because the belief slot is keyed by
  observer (`claim_reconciler.py:103-128`). `_observer_for` today refuses `page` spans (`entity_extractor.py:825-852`), so this is a new branch. Consumers of the `external:` prefix to check in
  Track 2a: `quiet_pages.is_quiet`, `promotion.claim_cites_person` (`promotion.py:160-170`), `claim_reconciler.slot_observer`, the group-member code that mints `external:` slugs.
- The owner guard: drop any relationship whose subject or object is the owner or a self-reference unless its located evidence is in his own sections.
- **Promotion and decay** (Track 2b): saves with no words of his share one promotion key; a save with his own reason, note or why-answer keeps its own key (`promotion.conversation_keys`,
  `promotion.py:177-232`). `counts_as_activity` stays false for a save with no words of his (the ruling 39 shape, `episode_time.py:61-65`), with one split in the writer where `untimed` is applied
  (`entity_extractor.py:1146`; Track 2b reads where create and touch part): a page the save creates starts its silence clock the day Cicada learned it; **a page that already has a source that
  is not a save is touched as a dated mention on the post's own day, once per page per day.** "Normal rules" read literally would let two posts mint a page for an author (450 posts about three
  topics would mint concept, tool and person pages from strangers' words, per the reading notes); the shared key keeps the useful half. To undo: remove the shared key; make the split always untimed.
- **Names from a post join existing person pages only exactly** (Track 2c): in `entity_resolver.resolve`'s per-name match (`match_existing`'s two matchers, `entity_resolver.py:1633-1662`), an entity
  whose only source episodes are saves skips the judge, `_first_name_across` and the same-name planning and matches only on exact name or alias (`existing_by_name`, `:1619`); otherwise it is held.
  The same-person rules (ruling 65, `pair_evidence`) need the person's own turns, which a save has none of.
- **Per-page and per-name caps** (Track 2c): at most 12 open save-derived claims on one page, folded by predicate and object across authors (`claim_reconciler.py`); at most 3 held lines per name
  from saves (`pending_store.MAX_HELD_CLAIMS` is 50 and per name only, `pending_store.py:52`).
- Edges: `inject_media_edges` (`media_ingestor.py:3002-3060`) today makes a media `about` edge to every entity resolved from the page's episodes. For a save it makes one only to a page whose name
  or alias the save's text states in full, at most 5 (5.1 (e) states that this is the one narrowing of ruling 56: an edge that exists for a media page's own `about`).

**(c) A save nobody talked about raises no question.** Mostly derived (invariant 5). `quiet_pages.episode_kind` calls an episode with no `media_entity_id` a conversation (`quiet_pages.py:66-73`), which
makes a tab group light its page: make `source: tab-group` an import. Drop `ask_person` for a save. Held names whose episodes are all saves raise no held-alias question (`entity_resolver.py:2617`, Track 2c).
To undo: remove the `ask_person` drop.

**(d) Going deeper follows his talking; Sleep uses what Cicada holds.** `saved_mentions._saves` selects by `history_index.kind in ("saved","list")` and skips the rest unless woken
(`saved_mentions.py:70-95`); a save written waiting (`processed: false`) has kind None, so **the most common case, a save yesterday and a mention today before it is read, would be dropped**.
Track 1 selects by `mention_asks.list_key` / `is_list_origin` / bookmark origin whatever the kind (`from_list`, `:79-84`, is already that), and for a save still waiting stamps `read_asked` (no flip:
it is already queued) so it moves to class 2 and leaves the ask; for a save in the pile `wake` (`history_index.py:216-251`) flips it as today; for one already read, only the ask; for one with
nothing to read, only the ask. The widening of "what Cicada already holds" to Sleep's own page read is **not in the build**: 3.7 ships it off and question 4 asks.

---

## 5. Ruling 80 and the rail lines

### 5.1 The ruling text for `docs/goals/TODO.md`

Insert directly above ruling 79 (or above 78 if 79 has not merged; the file keeps rulings newest-first within a day). House style.

```
80. **Saving is the reason: Sleep reads what the person saves (owner, 2026-11-24; G246; withdraws the index-only rule of ruling 62 and
    the saved-list half of ruling 30 point 1; amends rulings 13 and 16, 77 (d), 78 (e), G102 and G236; plan
    `docs/plans/2026-11-24-saves-are-read.md`).**
    The owner, told that his saved X posts were in no Sleep queue because of ruling 62: "Omg no. remve that ruling. if i save it
    already has a reason. Maybe i didnt write it explicitly but should work still. This is for every source." (He also asked what the word he had been shown meant; Cicada now says what it does or does not do with the item.)
    Earlier the same day, still standing: saves "but those that i actually go ahead and talk about are way more important and maybe
    worth using the claude video skill to pull the transcription, maybe even frames and watch it"; "a clear logic i believe should
    be established to not blote cicada memory with shit, but making it aware and powerful to go deeper in the things i save"; "I want
    to leverage the power of the embeddings model we use which is multimodal"; and that he wants to be asked less.
    **(a) What he said, built as said.** A save is its own reason, for every source: a bookmark, tab group, saved link, a post from
    a platform's saved list, a like, an upvote, a repost, a save clicked inside a site, an export archive. Sleep reads it like any
    episode, after his conversations. Ruling 62 points 1 to 3 and ruling 30 point 1's "a save from a platform's saved list" are
    withdrawn; ruling 62 point 5 (a save a model already read keeps what it made) and point 6 (a batch is bounded by what it
    holds) stand. The saved-item retrieval and its check stand and now serve a save whether or not it is read.
    **(b) My reading of his words, built, one line to undo each:** (i) watch history and records (his own repositories, joined
    communities, open tabs on other devices) are not saves and stay indexed (ruling 30 points 2 and 3); feed items stay as the code
    reads them, as the publisher's words with no mention (ruling 39); follows are a directory no model reads. (ii) A save's words
    are its author's, never his, for every door including the X API and Pinterest connectors (their post text is a description, not
    his note): a saved-item note to Stage 1 that dates what a post says by when it was posted, claims `external:<author or site>`,
    nothing on his page from them unless his own sections say it, at most 8 entities, at most 12 save-derived claims on a page, a
    name from a post joins an existing person page only by exact name or alias. (iii) Saves with no words of his count together as
    one source for the 2+ rule, so a save alone never makes a page; a name in saves and in a conversation does; a save with his own
    reason keeps its own key; a save with no words of his starts no page's clock and, on a page that has other sources, is a dated
    mention on the post's day, once a day. Amends ruling 65's and the Entity promotion rail's "counted on the conversation" only to
    say such saves are one. (iv) Questions: a page only saves named is quiet; Stage 1 asks nothing from a save. (v) A save that holds
    nothing but a title and a link is not sent to a model (it has nothing to read); it is read when he talks about it or his agent
    opens it. (vi) Going deeper (an agent in his browser, a video's transcript, frames, pictures when on) still follows his talking
    or asking, ruling 78 (e) unchanged except that a mention of a save already read leaves only the ask and one not yet read is read
    first. Sleep fetches no page behind a saved link unless he turns that on. An unread save is embedded by its words only; pictures
    and frames follow his talking.
    **(c) Order and pace.** Every non-save is read before any save; his talked-about saves come first among saves, then newest first.
    A save that arrives in bulk, a save already kept, and a save received over 30 days after its saved day wait their turn: a fixed
    number a day (25 at first; the coordinator raises it) enter the queue, newest first, and nothing that is waiting is ever cut.
    **This amends rulings 13 and 16 in one place: an allowance on how many saves enter the queue a day, which the owner is asked
    to confirm.** A line the person set, or a plan limit, reached while only such saves remain finishes the run, not pauses it,
    and the saves go back; decay runs after his conversations. The spending limit, plan pauses and ruling 4's switch hold.
    Short saves of one origin may be read in one call; a group that does not line up is read one by one.
    **(d) Amended with it:** ruling 77 (d) "a noticed save is index-only until the person gives a reason" and 77's folder reason
    "makes them readable" (a reason now only adds his words), ruling 78 (e)'s "a save the person talks about wakes for one Sleep
    read" (it is read anyway; the ask stays), G102 (a read save's page is read like any, at the existing caps, only if he turns it
    on), the G236 row, G221, G206, G232 and `docs/plans/2026-11-24-sources-answers.md` (ruling 79 (a) "index-only save" and (d)
    "Rulings 30, 62, 68 stand" become "Ruling 68 stands").
    **(e) Amends ruling 56 for one edge:** a media page's own `about` edge to a page its save names in full, at most 5; no other link
    is made from a co-mention.
    *Why:* the owner's own words; ruling 62's measure (25 bookmarks cost 56 calls to restate titles) was true of one call per save
    on text with nothing in it, and a daily allowance, the order, the nothing-to-read rule and a grouped read remove the harm it
    measured; reading a save as its author's words, never his, and counting saves as one source for pages keeps the harm ruling 62
    feared (pages and claims made from other people's words) out.
    **Revisit on:** a page or a claim on his page found that only saves made; a question raised only by a save; a night that
    starved a conversation or left a pause; the first nights' results saying the day's number is wrong; or a save he talked about
    that was not read first.
```

### 5.2 CLAUDE.md lines that change (stays under 60,000; net about +15 characters)

Line numbers at dev head `0f63882ba`, rechecked. Plan2 Track 0's 345 characters are untouched.
1. **Lines 174-177** (Capture rail, "it and saves from a platform's saved list are indexed ... one already read keeps what it made (`capture-and-sleep.md`).", 477 characters). Replace with
   (about 470): "it is indexed, never read by a model (ruling 30). **Ruling 80 (owner 2026-11-24, withdraws 62 and 30's saved-list half):** saving is the reason, so every save the person made (bookmark, tab
   group, saved link, like, upvote, repost, list post) is read by Sleep after their conversations, its words the author's, never the person's, no page from saves alone; records and watch history
   stay indexed; older saves enter a number a day, newest first (`capture-and-sleep.md`)."
2. **Line 252** (Sleep rail): "(rulings 13, 16; the old reduced-read clause, ruling 62)" becomes "(rulings 13, 16, 80)". -20.
3. **Line 458** (reading with the person's own agent): "each item an indexed save (G206" becomes "each item a save (G206". -8.
4. **Line 326** (decay): "a memory export entry or a watched day is no mention" becomes "a memory export entry, a watched day or a save is no mention". +8.
5. **Line 296** (promotion): "counted on the conversation, never guessed (`promotion`)" becomes "counted on the conversation (saves with no words of his are one), never guessed (`promotion`)". +40.
Nothing else in the file names ruling 62's reduced pass (grep for "indexed save", "index-only", "nobody has read"; line 397's "index-only" is traces). Area docs, same PRs as their code:
`capture-and-sleep.md` ("The reduced pass" `:1273-1363`, "Indexed, not consolidated" `:1365-1402`, feed item `:4800-4821` fixed to the code, before-the-freeze `:3298-3312`), `mcp.md` (21 lines per the reading notes),
`storage.md` (15), `api.md:1139-1141`, `app.md`, `features.md:951`, `network.md:536`.

---

## 6. Tracks

Each is one pull request to `dev` from its own worktree (`git worktree add .worktrees/<name> -b feat/<branch> dev`, venv linked). Every PR updates its area doc, its `feature-status.md` line and the G246
row. Tests: the touched files, their importers and `make test-crucial`, niced, one at a time. No bank is read. **Turning reading on (Track 1) and the words that say so (Track R) ship in the same release.**

### Track 0: `docs/ruling-80`. Docs only. First.
- Files: `CLAUDE.md` (5.2), `docs/goals/TODO.md` (80; a pointer at 62, 30, 77 (d), 78 (e) and in 79's text), `memory-evolution.md` (G246 row; the G236, G245, G221 rows edited, never a second row for the
  same argument), `feature-status.md`, `docs/plans/2026-11-24-saves-are-read.md` (this plan).
- Collides with plan2 Track 0 (the same four docs). **This Track 0 merges first** (plan2's rail sentences, lines 256, 275, 318, 408-410, 454, 461, are not the ones it edits; 252 and 256 are 4 apart, so a
  hunk may need a hand merge). Plan2's ruling 79 text is edited as in 5.1 (d); if 79 landed first, plan2 Track 0's author applies it.
- Verified by: `api/tests/test_claude_md_size.py`, `test_crucial_tier.py`. Out of scope: any code.

### Track M: `bench/saves-battery`. Benchmarks only. Parallel with Track 0, before everything else.
- Files (all new): `benchmarks/consolidation/saves_fixture.py`, `benchmarks/consolidation/saves_battery.py`, a paragraph in `benchmarks/consolidation/README.md`. Collides with no plan2 track.
- A synthetic bank of conversations plus about 80 saves, natural-language text (word-salad `synth` data does not work, `benchmarks/perf/README.md:66-69`, per the reading notes), `example.com` links. It holds:
  a topic named in many posts; an author whose name equals a Contacts card; a first-name-only "Sam" in a post while a friend page "Sam Example" exists; a first-name-only mention; a post stating
  a fact about an existing page; **50 posts that each state a fact about one existing page**; a 2021 post stating a present-tense fact; posts saying "I" and "my"; a post quoting a claim about "the
  user"; a title-only bookmark; the same link on two lists; a tab group; a feed item; an open Safari tab; a save with his own reason; a 40-day-old bookmark; **a connector-saved tweet in
  today's shape (text in `note`) and in the fixed shape (text as a description)**; a bulk list of 200 undated rows.
- It counts, per leg (today's baseline, single read, grouped read): calls and tokens **and output tokens** by stage (`benchmarks/perf/ledger.py`), pages made and whether each is quiet, claims by
  observer, **claims per page (max)**, claims on the owner's page, claims or aliases on any person page from a save without an exact name or alias match, located evidence versus `reasoning`,
  held names **per 100 saves** and held lines per name, wrong same-person joins, questions raised with a save as their only source, decay status of pages born from old saves, the retrieval cases of
  ruling 62, and the number of waiting saves after the bulk list.
- **The baseline leg runs on dev as it is, before Track 1.** Gates (counts, not a score; repeats required, two haiku runs share only about a quarter of exact claims,
  `benchmarks/consolidation/README.md`, per the reading notes): zero claims on the owner's page from a save (**the connector-saved tweet in today's shape fails this gate on the baseline leg, the fixed shape
  passes**); zero pages from a single save; every save-derived claim `external:`; at most 12 save-derived claims on the page 50 posts name; zero save-derived claims or aliases on a person page
  without an exact match (the "Sam" case); questions with only a save behind them at or near zero; the 2021 fact never written as current; waiting saves after the bulk list at most one day's
  allowance; retrieval cases unchanged; for Track 3, the `reasoning` share of grouped reads no higher than single reads; held names per 100 saves reported (if over 250 the entity cap drops from 8 to 5).
- Out of scope: any change under `api/`.
### Track 2a: `feat/saves-words`. Whose words, and when. Before Track 1. Ships on its own and fixes a live defect.
- Files: `api/services/entity_extractor.py` (the saved-item note, observer branch, owner guard, entity cap, `ask_person` drop, the dated note via `source_dates`), `api/services/source_dates.py`
  (`saved_note`), new `api/services/saved_reading.py`, new `api/services/connector_text.py` (the heal), `api/services/connectors/x.py`, `connectors/pinterest.py`, `api/services/reading_walls.py`,
  `api/services/media_ingestor.py` (`prepare` only, `:2638`: the connector's text wins for the walled origins), `api/services/sleep_cycle.py` (one added call in `_index_without_model_safely`),
  new `api/tests/test_saved_words.py`, `test_entity_extractor*.py` and the connector tests as touched, `capture-and-sleep.md`.
- Safe alone: it changes only how a save is read today (a connector save, one with a reason or a mention), so merging it before reading is turned on harms nothing, and it ends the live case.
- Verified by: a post saying "I" and "my" writes nothing on the owner's page; claims from page spans are `external:<channel>`, else the site; a claim in his own reason section is his; two authors'
  differing claims never share a slot; 9 entities in one save keep 8; `ask_person` dropped; **an X API bookmark's text is a description, has no `has_note`, and its claims are `external:<author>`
  (a test through the real writer and `bookmarks_to_items`, same for a Pinterest pin)**; the heal renames an old connector episode and is idempotent; a 2021 post's fact is dated as of that
  month; a post with no date is told not to be written as current; Track M's gates on the single-read leg; the old reduced-pass test module cases that read a woken save (`:386`), `make test-crucial`.
- Collides with: plan2 Tracks 2 and 5 (they add defs near `sleep_cycle.py:1755`; this edit is one line in `:1849-1863`) and with Track 2b, Track 1 in `media_ingestor.py` and
  `entity_extractor.py` (different regions; order 2a, 2b, 1). Out of scope: grouping, pages, decay, the queue.

### Track 2b: `feat/saves-no-pages`. No page and no mention from saves alone. After 2a (`entity_extractor.py`), before Track 1.
- Files: `api/services/promotion.py` (one shared key for saves with no words of his), `api/services/episode_time.py` (`counts_as_activity` false for such a save),
  `api/services/entity_extractor.py` (the create/touch split where `untimed` is applied, `:1146`, a few lines), `api/services/quiet_pages.py` (a tab group is an import),
  `api/services/media_ingestor.py` (`inject_media_edges` only, `:3002-3060`), `api/services/link_enrichment.py` (the page-read exclusion, 3.7), tests `test_promotion*`, `test_quiet_pages*`,
  `test_episode_time*`, the old reduced-pass test module, page-read exclusion case (`:424`), new `test_saves_no_pages.py`, `capture-and-sleep.md`.
- Verified by: two saves naming one thing and nothing else make no page; one save plus one conversation do (the page keeps both sources); **a save with his own reason counts as its own
  conversation**; a tab group's page is quiet; a save dated years ago starts no clock on a page it creates and a page that has a conversation source is touched at the post's day once a day; a
  saved link's page is not fetched or summarized unless he gave a reason; Track M gates (zero pages from a single save, zero questions).
- Collides with: nothing in plan2. Out of scope: any queue or capture change.

### Track 2c: `feat/saves-bounded`. Per-page and per-name bounds, exact names. Before Track 1; after plan2 Tracks 1 and 2b (`entity_resolver.py`).
- Files: `api/services/claim_reconciler.py` (the 12-claim cap and the fold across authors), `api/services/pending_store.py` (3 held lines per name from saves), `api/services/entity_resolver.py`
  (exact name or alias only for a name whose sources are all saves; `_held_alias_questions`, `:2617`, raises nothing for them), tests `test_claim_reconciler*`, `test_pending_store*`,
  `test_entity_resolver*`, new `test_saves_bounded.py`, `capture-and-sleep.md`, `storage.md`.
- Verified by: 50 posts that state a fact about one page leave at most 12 open save-derived claims on it, the same fact from several authors one claim with many sources; "Sam" in a post stays held
  beside a "Sam Example" page and writes no alias or claim there; a held name from saves keeps 3 lines; a held name with only saves raises no question; Track M's gates.
- Collides with: **plan2 Track 1 (`entity_resolver.py:368-372,741`) and plan2 Track 2b (`:696-745`)**: they merge first, this rebases. Out of scope: promotion, decay, the queue.

### Track 1: `feat/saves-wait-for-sleep`. Turns reading on. After 2a, 2b, 2c, after Track M's single-read leg, and after plan2 Track 4 has merged.
- Files: `api/services/history_index.py` (`kind()` returns `saved`/`list` only for a save stored waiting its turn; `record`, `NO_WORDS_BY`, `not_read`, `SAVES_READ`; `retire` no longer touches
  saves; `take_turns`, `return_to_pile`; `mentionable` and `wake` follow), new `api/services/saved_order.py`, `api/services/saved_mentions.py` (select by `list_key`, stamp `read_asked` on a waiting
  save), `api/services/media_ingestor.py` (`write_media_episode` only, `:2249-2256`: waiting its turn for a bulk door, an old save, none for feed or record; `no-words`; `ingest_batch` passes `bulk`),
  `api/services/tab_groups.py` and `api/services/episode_staging.py` (a tab group's later change is an update in place; `EpisodeDraft` gains one flag; `_apply_common` `:451-469` leaves `processed`
  alone when set), `api/services/sleep_cycle.py` (`_index_without_model_safely` calls `take_turns`; the freeze `:2407` calls `saved_order`; the line stop `:2596-2600` and `:2641-2650`;
  `is_last` for decay and links `:2605-2615`), `api/services/sleep_drain.py` (`DrainState.decay_batch`), new `api/scripts/saves_night_report.py` (per-save ids and enums for the coordinator,
  never titles in the repo), `api/scripts/history_index_dry_run.py` (counts by origin, `no-words`, nights at the day's number), tests the old reduced-pass test module (about 26 flip), `test_history_index.py`
  (about 8), `test_depth_on_mention_g245.py` (the wake half, about 7), `test_tab_groups.py`, `test_save_folders.py`, `test_site_save.py`, `test_saved_lists.py`, `test_more_lists_g245.py`,
  `test_ways_in_g232.py`, `test_spotify_export.py`, `test_substack.py`, `test_github_repos.py`, `test_ask_unread.py`, `test_sources.py`, `test_source_streams.py` (about 15 to 25 more, mostly one
  assertion each, per the reading notes), new `test_saves_read_g246.py`, `capture-and-sleep.md`, `storage.md`.
- Collides with: **plan2 Track 4** in `history_index.py` (its `x-reposts` entry in `LIST_ORIGINS`, `:68`): plan2 Track 4 first; its gate test (`test_more_lists_g245.py:133`) keeps passing because
  `LIST_ORIGINS` stays the registry. `media_ingestor.py` with 2a and 2b (regions differ): 2a, 2b first. `sleep_cycle.py` with plan2 Tracks 2 and 5 (defs near `:1755`) and Track 3: different regions.
- New tests and what they pin: a single fresh save is written waiting and a bulk write, a 40-day-old one and a title-only one are not (`waits its turn` / `no-words`); `take_turns` brings the
  day's number back, newest first, skips dirty files, is idempotent, spends the day once across two runs, does nothing on `tail_only`, and restores on a failed commit; **a bulk list of 5,000
  rows leaves `sleep_debt` at most one day's number and the `after_import` probe starts no second run**; the freeze order (non-saves, talked-about saves, grouped background saves) and no cut at the
  freeze; **a spending line, a key limit, extra usage and a plan window each reached with only background saves left end the run with no pause record, `schedule_may_replace` is moot, the unread saves
  return keeping `turn_released_on`, and the next night's run is not blocked; with a conversation left they pause as today**; **decay ran before the first saves batch and a run killed in the saves
  part has decayed**; a pageless feed item written through the real writer is read, untimed, with `feed_note` (section 0.10); a tab group edited after its read stays read; **a mention of a save
  still waiting moves it to class 2 and leaves the ask; of one in the pile wakes it; of one read leaves only the ask; of a `no-words` one leaves only the ask**; the retrieval cases of ruling 62 for
  a fresh waiting save, one in the pile, a `no-words` one and a read one (the finder's `page_hit` `read` flag, `:96-103`, and the tab-group gate, `:111`, move here from Track R).
- Scratch check (`verify-cicada`, section 7). Out of scope: Stage 1 grouping, any note, observer, page or decay-rule change (2a, 2b, 2c, 3), every word shown (Track R).

### Track R: `feat/saves-words-on-screen`. Retrieval and what the app says. Same release as Track 1; starts after Track 1 merges.
- Files: `api/services/mcp_tools.py` (the id read `:3424-3443`; record-list replies `:2079, 2113, 2177`; recall's heading `:2712`; `:5873`), `api/mcp/server.py` (tool descriptions `:381, 423`),
  `api/services/ask_service.py` (`:1652`), `api/services/hook_recall.py` (`:738-750`), `api/services/recall_text.py` (`:30-34`), `api/routers/sleep.py` (`kept` counts `saved` and `list`; copy
  only), `api/routers/sources.py` (the folder-reason sentences `:918-935`), `api/services/save_folders.py` (copy), `api/services/source_overview.py` and `api/services/source_streams.py`
  (`_depth`/`_READ_KINDS`: a saved-list stream is `read`; the row words of 1.3), `api/models/schemas.py` (doc strings only), Swift copy only: `Theme/Copy.swift`, `Copy+Sources.swift`,
  `Copy+Streams.swift`, `Copy+Catalog.swift`, `Copy+Reading.swift`, `Copy+SleepV5.swift`, the one line in the Sleep page's last Waiting card (`Views/Sleep`), `SourcePageStreams.swift`, tests
  the Sleep page's last-card test, `SourcesV4Tests`, `SleepSourceCardsSnapshotTests`, the old reduced-pass test module's retrieval cases that are about words, `docs/architecture/mcp.md, app.md, api.md, features.md, network.md`.
- No API field is renamed (Hyrum's law): `kept`, `SleepKept*`, `KEPT_SHAPE kept-1` keep their names; the ETag mapping needs no change because no new field is added.
- Collides with: `source_streams.py`, `source_overview.py` and `SourcePageStreams.swift` with plan2 Tracks 4, 5, 6, 7b: **plan2 Tracks 4 and 5 first**, then this, then 6 and 7b rebase.
  **`mcp_tools.py` and `mcp/server.py`**: plan2 Tracks 2, 4, 5, 6, 7b edit `record_saved_list` (`mcp_tools.py:1842-2080`), and the reply strings at `:2079, 2113, 2177` are inside it or next to
  it, so this track follows plan2 Tracks 4 and 5 in that function as it does in `source_streams.py`; `server.py:381,385` are adjacent lines, a rebase.
- Verified by: the copy tests; **a grep test over the Swift copy and MCP descriptions for the save rows: none of the retired word for the old behaviour, "indexed", "its turn" or "ask"** (the row says "Waiting for your
  agent"); `test_cli_map.py`, `test_handshake_r12.py`, `test_mcp_schema_size.py`; scratch app check (section 7).
- Out of scope: any layout, tab or card change on the Sleep page (the owner withdrew that request).
### Track 3: `feat/grouped-save-read`. Optional until measured. After Track 1 and Track 2a.
- **Status (2026-11-24): built and OFF** (`grouped_save_read.ON = False`), stacked on the held switch. No new stage name or enum: a grouped call is Stage 1's own `extraction` call and states no answer shape. Measured once each by `saves_battery` (single leg and grouped leg, haiku on the plan); numbers in `docs/architecture/capture-and-sleep.md`.
- Files: `api/services/entity_extractor.py` (a grouped branch beside the chunk loop; Track 2a's note and rules apply per block), `api/services/json_parse.py` (reuse `numbered_rows`),
  `api/services/agent_engine.py` (`SCHEMA_BY_STAGE` entry), `api/services/sleep_spend.py` (`LINE_STAGES`) and the ledger stage enum and `providers.resolve_llm_fn` if a new stage name is used
  (the implementer lists each enum touched), `api/services/sleep_run_prefs.py` (the 50 ceiling for a save-only batch), `api/services/sleep_cycle.py` (the skills-call skip at `:3458`),
  tests `test_grouped_save_read.py` (new), `test_entity_extractor*`, `capture-and-sleep.md`.
- Collides with: `entity_extractor.py` with Track 2a (2a first); `sleep_cycle.py` with Track 1 (different region, 1 first). Nothing in plan2.
- Verified by: a malformed or misaligned answer falls back to one call per save with the same facts; evidence is located only in its own save; a lifted quote becomes `reasoning` and the claim is
  written; per-save sensitive guard, retry, parking and callbacks still per save (`entity_extractor.py:1264-1316`, per the reading notes); Track M's grouped leg on mixed origins: calls by stage against single,
  `reasoning` share not higher, pages, claims and questions diffed through `benchmarks/scale/sleep_calls.py diff`; the TLA+ video queue model is not touched.
- Out of scope: Stage 2 or 3 batching changes; any model change.
### Order
Wave 1 (parallel, no shared file): Track 0, Track M, Track 2a, Track 2c (after plan2 Tracks 1 and 2b). Then 2b (after 2a). Wave 2: plan2 Track 4 merged, Track M's single-read leg run, then Track 1.
Wave 3: Track R (after 1 and plan2 Tracks 4 and 5), Track 3 (after 1 and 2a; only if measured). Release only with 0, 2a, 2b, 2c, 1 and R. Before Track 1 merges the coordinator runs
`history_index_dry_run` (counts only) on the live bank: the real pile, the `no-words` count, the connector episodes the heal touches, the nights at the day's number.

---

## 7. How each is checked in the real thing

- **Scratch run of Sleep (`verify-cicada`, haiku on the plan, scratch HOME, bank and port):** the Track M fixture plus eight conversations; run Sleep on dev as it is (baseline), after Tracks 2a, 2b, 2c,
  after Track 1, after Track 3. Per run record: calls by stage, pages created (each quiet or not), claims by observer, any claim on the owner's page, claims per page, held names, questions whose only
  evidence is a save, commits (`Indexed without a model` commits carry `queued`), the batch order (non-saves first), the batch that ran decay, and **one run killed in the saves part and one given a
  spending line it reaches inside the saves part (every conversation filed, decay done, no pause record, the next scheduled run not blocked)**.
  Repeat each leg twice; the cheapest model on the plan only.
- **Scratch app (`verify-cicada` second copy of the app, `macos-harness`):** the Sleep queue shows a waiting save as a row and the one older-saves line; a saved list's source page says "read by Sleep"
  and each row's word; a save's page shows its sentence marked as the author's, dated, and no fact on the owner's page; app recall and MCP `cicada_recall` find a read, a waiting and a nothing-to-read
  save; a screenshot of each for the PR. No layout is judged.
- **The first real night (the coordinator, not an agent).** Ship at `SAVES_PER_DAY = 25`. The coordinator runs `saves_night_report` and reads the night one save at a time (claims by observer, pages made,
  joins, aliases, held names, questions, anything on the owner's page), then raises the number by a one-line PR (25, then 100) only when nothing is wrong. Counts alone do not decide it (the 2026-10-20
  sweep wrote eight wrong settles from counts). Revert: `SAVES_READ = False` or `return_to_pile` for the day.

---

## 8. What in plan2 this change alters (exactly)

1. **Depth words.** plan2 never names the stream depth word for a repost stream or for follows. After ruling 80: a saved list's stream says "read by Sleep" (including `x-reposts`), a row says Read, Not
   read yet, Nothing to read yet, Waiting for your agent or Watched; follows, watch history, open tabs and records say "kept, never read: you did not save it", feed items "read as the publisher's
   words". plan2 Track 4's `kind` field (`posts|people|accounts|books`) is the right switch: `_depth` reads `read` for `posts`, `index` for `accounts`. plan2 Track 4's wording "one index-only save" (1.1)
   and "Index-only: `x-reposts` MUST join `LIST_ORIGINS` ... or Sleep would read every repost" (1.1) are reversed in meaning: the membership is still needed (mention asks, `mentionable`, the gate
   test), but the consequence of membership is no longer "never read". Track 0 edits those two sentences.
2. **The mention ask.** Unchanged in what it does. Changed in how it is reached (`saved_mentions` selects by `list_key`, so a repost row added by plan2 Track 4 is covered with no code) and in "wakes
   for one read": a save is read anyway; a mentioned one is read first. plan2 1.1's "a model reads nothing else about it" is no longer true.
3. **Pictures at depth (plan2 Track 6).** No behaviour change: pictures follow an ask or a mention, never a plain save, and Sleep reads no pixels (ruling 68 (e)). Only ruling 79 (d)'s "Rulings 30,
   62, 68 stand" changes to "Ruling 68 stands"; "a plain save keeps nothing" stays true.
4. **The daily run (plan2 Track 7a, 7b).** A list read now adds saves the same night's Sleep does **not** read at once: a first whole read of a long list is a bulk write and waits its turn, so it
   reads `SAVES_PER_DAY` a night, not hundreds in one (plan2 4.4's rule "never the first whole read of a list that has not reached its end" in an unattended run stays, for the plan's own
   spend). A repeat read adds a few, written waiting, read that night. The first-use sheet's line "it spends his plan" gains "and what it brings in is read by Sleep a few at a time" (Track 7b's file;
   this plan asks, does not edit). No change to the window, the power gate or the caps.
5. **Not altered:** the arrival join (plan2 section 3) and the connection mention page (1.5): both already refuse a save as his words, and plan2 3.3's "first day" ignores saves. Follows are not saves.
6. **Files shared with plan2** (who goes first) are listed under each track's "Collides with"; in short: `history_index.py` (plan2 Track 4, then Track 1); `source_streams.py`, `source_overview.py`,
   `SourcePageStreams.swift`, `mcp_tools.py` (`record_saved_list`) (plan2 Tracks 4 and 5, then Track R); `entity_resolver.py` (plan2 Tracks 1 and 2b, then Track 2c); `sleep_cycle.py` (whoever merges second
   rebases); `CLAUDE.md`, `TODO.md`, `memory-evolution.md`, `feature-status.md` (Track 0 first).

---

## 9. Open questions for the owner (five; each changes what is built; each has a safe default if he does not answer)

1. **How many saves a night, and should a link with only a title be read at all?** Sleep reads his conversations first, then a fixed number of saves a night, newest first. Recommendation: 25 the
   first nights while I check what it writes, then 100 (about 35 nights for 3,450; 12 nights at 300 would cost about $4 a night on a key at the higher haiku price before conversations). This is the
   one place ruling 80 limits anything: a number of saves that enter the queue a day, never a cut of what is waiting (rulings 13 and 16). A link that holds only a title and a link (no description) is not
   sent to a model, because it has nothing to read; it is kept, found by title and read when you talk about it. Default: 25 then 100; title-only not read.
2. **Which things are saves?** Watch history, accounts you follow, your own repositories, joined communities and open tabs on other devices are kept and never read ("you did not save it"). Feed items
   (RSS) are read today as the publisher's words and stay so. Recommendation: exactly that. If you say any of the first group should be read, they ride the same daily number. Default: as above.
3. **A topic you saved many posts about but never talked about: should it get a page?** Recommendation: no; saves with no words of yours count as one source, so it gets a page the first time you mention
   it, with the saved posts attached. Default: no page until you mention it.
4. **Should Sleep read the public page behind a saved link?** One sentence about each (the same read it makes for a link you gave a reason for), at most 20 a night, never a login-walled site or a video;
   it sends one request per page to the site you saved from. Recommendation: yes for links you give a reason for or talk about (as today), **no for every saved link until you say**. Default: no.
5. **Should the pictures or frames of every saved post be embedded too (the multimodal search model)?** Today an unread save is searched by its words; pictures follow when you talk about it and your agent
   goes deeper (plan2 Track 6). For every save it means pictures from sites that block fetching, or read on your Mac, at an unmeasured cost. Recommendation: not until measured. Default: no.

---

## 10. Considered and kept

- **Read every save at capture, with no Sleep.** Rejected: ruling 36 D2 (a quick read only in a separate pass, off unless measured better); capture stays file I/O.
- **A new kind name for every old shape.** Not done. `kind()` keeps `saved` and `list` for "kept, waiting its turn", so about a dozen readers (`routers/sleep.py:420`, `source_overview.py:388-391`,
  `save_folders.py:261,464`, search `meta.index_only` at `search_index.py:567-572`) are right without edits, and a read save's file changes, so it is reindexed. The one new kind, `record`, keeps what was index-only.
- **Each save its own conversation (today's code, "normal page rules").** Not chosen; see 4(b) and question 3.
- **A cut at the freeze or a per-run cap.** Dropped after critique: it was a per-run cap on waiting items, the thing ruling 13 refused, and left unread saves counted as waiting (0.7). Pace is now on entry
  to the queue, per local day, with the amendment said plainly and asked (3.2, question 1).
- **One `external:` observer per site, not per author.** Kept per author: the slot is keyed by observer, so two authors saying different things never meet in one slot and nothing is overwritten. The
  critics' cost, a parallel claim per author on one page, is met by the 12-claim cap and the fold (4(b)), not by merging authors.
- **The saved-item finder serving read saves "from the start".** It already does for every media page (section 0.11); what was wrong was the `read` flag and the tab-group gate, which Track 1 fixes. No conditional.
- **Counting a save as no mention at all.** Narrowed after critique (4(b)): untimed for a page the save creates, a dated mention once a day on a page that has another source. Kept for everything else: ten
  thousand bookmarks naming a page do not hold it at the floor.
- **Fetching the page behind a saved link by default.** Dropped after critique (3.7, question 4): a new network behaviour, and reading (d) said what Cicada already holds.

## 11. Not verified (said plainly)

The tab-group `quiet_pages` classification, the pageless-feed read (0.10) and the connector read-as-his case (0.3 (b)) are by code reading, no run. How Stage 3 treats an `external:` claim next to his own is
by the slot rule, not observed. Where `untimed` is applied for a page a save creates against one it touches (4(b)) is not read: Track 2b reads it and reports back if both share one path. Whether enrichment can
return login-wall text for x.com before the connector's text is for Track 2a to confirm. Output tokens, the grouped numbers and every dollar figure are estimates (3.6). The `external:` prefix consumers in
4(b) are from the map, not all opened. The owner's engine tonight and his real pile are not in the repo.

---

## 12. What changed after critique

Two critics, 28 flaws (some the same): changed (where), or kept with the reason.

**Blockers**
- *Connector saves read as his words (both critics).* Changed: section 0.3 (b) names it as a live defect; invariant 1; 4(b) first bullet (text as `preview`, not `note`; `reading_walls`
  follows; a one-pass heal); Track 2a ships first with the tests; Track M fixture and a gate that the baseline leg fails and the fixed shape passes.
- *Paused run starves tomorrow (both critics).* Changed: 3.4 and invariant 6: a line or plan stop reached with only background saves left is a finished run with no pause record, the saves return to the pile
  keeping the day's stamp; Track 1 tests it through `schedule_may_replace` and a real killed run. Decided in ruling 80 (c), not left to Track 1. (`SCHEDULE_REPLACEABLE` read, section 0.8.)
- *Per-run 300 is a cap, and per run not per night (both critics).* Changed: the freeze cut is gone. Saves enter the queue by a per-local-day allowance, bulk doors write waiting-its-turn whatever their dates,
  so "waiting" never holds a backlog (0.7, 3.2, invariant 8); no top-up on `tail_only`; the ruling says plainly it amends 13 and 16 on entry and the owner is asked (question 1). `sleep_debt`,
  `sleep_scheduler` and `sleep_catch_up` were read first (0.7).

**Serious**
- *Feed items and `safari-tab` index-only again (owner).* Changed: no `feed` kind; feed items keep what the code does today (0.10); `record` keeps only what was index-only before (adds nothing
  but the open tab, which already was); both are question 2 with a stream word "kept, never read: you did not save it". Watch history is the one clear exception.
- *Saved note does not date the post (owner).* Changed: 3.8, `source_dates.saved_note` modelled on `feed_note`, dated by `posted`/`published_at`, "date unknown" otherwise; invariant 11; Track 2a test.
- *Per-save caps only (owner, engineering).* Changed: invariants 3 and 12, 4(b), Track 2c (12 claims per page, fold across authors, 3 held lines per name); Track M counts and gates them. "Per author" kept (10).
- *No nothing-to-read rule (owner).* Changed: 3.3 and ruling (b)(v): a save with no words is stamped read with no model call, read when he talks about it; question 1.
- *Fresh unread save dropped by `saved_mentions` (owner).* Changed: 4(d) and Track 1: select by list or bookmark origin whatever the kind, stamp `read_asked` on a waiting save, tests for all four states.
- *Dated pacing keyed on saved day (engineering).* Changed: the pace keys on how the save arrived (bulk door) as well as its age (3.2).
- *Decay and page reads attached to the saves batch (engineering).* Changed: 3.4, `is_last` for decay and links is the batch holding the last non-background id; Track 1 test.
- *`counts_as_activity` too broad (engineering).* Changed in part: 4(b), Track 2b split (created page untimed; a page with another source is touched at the post's day once a day). Kept for the rest (section 10).
- *Name resolves onto an existing person page (engineering).* Changed: 4(b), Track 2c exact name or alias only; Track M "Sam" case and gate.
- *Grouped estimate assumed one-origin batches (engineering).* Changed: 3.1 groups class 3 by origin; 3.5 says the 50 ceiling is Track 3's and that the gate is measured calls over mixed origins; the
  table now shows a range and says the measurement replaces it.
- *Cost model unmeasured, `$5` claim only for grouped (engineering).* Changed: 3.6 states single and grouped, cached and uncached, per save and per day; drops "under $5" as a claim; Track M's
  output-token leg is a precondition of Track 1; the pile size is flagged as larger than assumed.
- *First night on the real bank with counts only (engineering).* Changed: ships at 25, per-save report by the coordinator (`saves_night_report`), kill switch `SAVES_READ`, revert `return_to_pile` (7, 3.2).

**Minor** (all folded in)
- Page summaries "newest first" was wrong: corrected, backfill is oldest-imported first (3.7). Fetch widening "defaulted yes" and was set by silence: now off by default, question 4 (3.7, 4(d)).
- Copy: one unread word ("Not read yet"), "about M nights", no "ask" or "turn" in save copy, grep test (1.3, Track R). The embeddings request: a sentence in the ruling and 1.3, question 5.
- A save with his own words keeps its own promotion key (4(b), invariant 4, Track 2b test).
- `inject_media_edges` and ruling 56: ruling 80 (e) states the one narrowing; the edge is existing behaviour, narrowed to full names, at most 5.
- File overlaps: `entity_resolver.py` is in Track 2c's files and ordered after plan2 Tracks 1 and 2b; Track R's `mcp_tools.py` edits follow plan2 Tracks 4 and 5 in `record_saved_list` (8.6).
- The saved-item finder: read saves are already served; the two real defects (the `read` flag, the tab-group gate) are fixed in Track 1 (section 0.11); the conditional is gone.
- A row for a month-old bookmark: not added; it is in the pile line, and talking about it reads it first (1.3, 1.4).
