# The MCP surface

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

The interface between any LLM and the memory system. On `initialize` the server returns the G75
handshake as `instructions`. On query: check `memory/inbox/` for an open question about what the query is about
(the ask gate below) → search the vector index → search the markdown graph → follow wikilinks for relational depth → progressive
disclosure (cluster pages → entity pages → episodic sources).
Recall prose summaries, including related-page blurbs, strip closed claims fences
before truncation; `cicada_recall_detail` returns the complete page for structured reads — the file, then, when
its older claims live in its ledger (`claims_ledger`, `storage.md`), a `## Claims ledger` block with those lines. A
page over the caller's budget answers first with its prose (`_page_digest`, owner page 2026-10-14): a header (name,
type, status, aliases, how many conversations, related pages and claims it rests on), then the body from Summary
on, in page order, without the frontmatter lists or the claims — on the owner's page three quarters of the old first
part was `related:` and `source_episodes:` — and a footer naming the call that reads the whole page from line 1 (and
where the prose shown stops). Read with `start`, a page over the
caller's budget (`RECALL_DETAIL_BUDGET` 60,000 characters; `REMOTE_DETAIL_BUDGET` 20,000 on the remote connector,
under its 24,000-character result cap) comes in consecutive line ranges: each part is whole lines and ends with
one line naming its range and the exact next call (`start=<line>`), so every byte — claim ids, evidence, old
history — stays reachable through the tool under the default scopes (a 3,500-claim page was 3.1 M characters,
past any client's limit; eliding its fence instead lost the ids an agent needs to withdraw its own claim, review
round 1). `cicada get --start N` is the same; `--from`/`--count`/`--line-numbers` slice the whole page.

**Recall's size (2026-10-22).** A `cicada_recall` reply stays under `RECALL_BUDGET` (40,000 characters, about
10,000 tokens, well under Claude Code's default 25,000-token MCP cap; `REMOTE_RECALL_BUDGET` 20,000 on the remote
connector) whatever the bank holds — a recall that named the owner's page was 221,719 characters and reached the agent
only as an error. Each hit's `Related:` line shows at most `RECALL_RELATED_SHOWN` (12) names, those this recall also
returned first, then `… and N more — <page read, start=1> lists them all`; `summarize_for_recall` keeps Summary and Key
Facts first but cuts them at whole lines within the hit's budget (Key Facts keep at least a third), ending a cut list
with `- … and N more on the full page`; a hit's body is backstopped at 6,000 characters; the inbox block shows at most
5 questions, the cold-start hub list 8,000 characters. A reply still over the budget leaves out its lowest-ranked page
blocks first (never the top one) and says which in one line (`_fit_recall`); under the budget it is unchanged byte
for byte. Headings and line shapes are the same; only lengths change.

**Lean reads (2026-10-27, G140/G148/G149).** A real session (values redacted) spent ~6.3k tokens over 5 calls and still
grepped transcripts: one recall was 14,400 characters — 7 pages, 5 off-topic, the relevant page saying its facts three
times — and Ask said "the assistant" where the episode recorded a Claude Code session. Now:
- **A relevance floor** (`_above_floor`). A fused page is shown only when some leg ranks it among its first
  `RECALL_LEG_KEEP` (3) and close to that leg's best: within `RECALL_VECTOR_GAP` (0.05) of the best cosine, at least
  `RECALL_WORD_SHARE` (half) of the best word score, or simply ranked there (the claim leg). At most
  `RECALL_PAGES_SHOWN` (5), never fewer than the fused top one. A page whose name or alias is the query, or appears
  in it as a whole phrase (`_named_hits`, folded, three letters or more), is always shown, past the cap if it must. The hints block's `suggested_entities`, "Changed
  recently" and the provisional block follow the pages shown.
- **A body budget.** The best page's body gets `RECALL_TOP_BODY` (1,800 characters), every other `RECALL_OTHER_BODY`
  (700) — skills and deadlines too. `summarize_for_recall(collapse=True)` folds a Key Facts, History or Open
  Questions bullet that only repeats what is already shown (`entity_body.collapse_repeats`: every anchor — a number, a
  date, a link, a wikilink, a capitalised name — already shown as a whole token, never inside a longer one: `40` is
  not shown by `400`, nor `5` by `2025` — and 80% of its subject words), saying how many in one line. A bullet carrying anything new is kept; the page is never edited.
- **The extras earn their place.** "Related (one hop out)" only when a single page passed the floor (160 characters a
  head); excerpts one passage per conversation, a passage that is mostly a link skipped, each naming who the person
  was talking to (`episode_actor`), and one line naming the read (`cicada_sources`, only for a caller holding it).
- **Pictures that match (vision item 3, 2026-10-28).** On a local door (stdio, the CLI, a per-device client) recall
  adds at most `RECALL_PICTURES_SHOWN` (3) pictures from the one meaning index (`image_index`, `storage.md` "Pictures
  in the meaning index"), each as its title, where it came from (a look you saved, a screenshot of the saved site, the
  saved link's own picture, the video's still, or the still of a video watched on a day with that day's episode id),
  the API path that serves it, and its page with the call that reads it. Only pictures whose lift clears
  `image_index.LIFT_MIN`, so most recalls carry none. It embeds only the query's words with the table's text model —
  the vector the entity leg already made — and never the image encoder. **The remote connector never sees it:** no
  G135 scope covers pictures (`sources` covers the person's verbatim words), so `ctx.is_remote` skips the section
  (decided 2026-10-28: no picture hits on remote doors). A frame of a video the person added names its time.
- **From recordings and videos you added (meaning index 2, 2026-10-28).** On the same local doors only, at most
  `RECALL_FILE_LINES` (3) passages of the words of a recording or video the person added (`media_files`), each its
  file's name, kind, where in it ("at 12:34") and a short excerpt, under a header that says they are **the
  recording's words, not the person's**. Hits only (G195: the whole file only on the person's ask); a passage shows only
  above `media_files.TEXT_LIFT_MIN`. The remote connector never sees it (G195: "the remote connector never sees file
  search").
- **Measured** on a 7,962-page bank copy with its own search model, 25 questions (people, events, projects, "who did
  X", "did I send Y"): 457,788 → 150,672 characters in all (median 18,713 → 6,038, largest 22,453 → 8,625), the answer-bearing fact in 23
  of 25 replies before and after. The two misses are the same before and after: both facts sit only on the 482 KB
  owner page, one without its event's name (a Sleep write, not a read).

**Every episode id reads (2026-10-27).** `cicada_sources(entity_id)` takes an episode id Cicada printed (`ep_<day>_<n>`
from Ask, recall's excerpts, a page) and returns that conversation: a header (id, day, title), `With: <actor>`, a
removed-from-source or not-yet-read note when true, then its words as stored — scrubbed at capture, the dropped-middle
marker labelled (gate B2). An index-only episode (ruling 30: a watched day, a month's summary, a saved-list item, a
trace day — `history_index.kind`) answers one line saying what it is and that it is indexed for lookup, never its
text. The door is `cicada_sources` and not a new tool: it is the `sources` scope's own tool, so a
remote connection reads a conversation only with that scope, at R-R28's 1,000 characters, and every door fences it as
a read; no schema, CLI row or `/v1` operation changed (a page id still reads as before, and a page that happens to be
named like an episode id still wins). A stdio read returns up to `EPISODE_READ_MAX` (12,000 characters) and names
`cicada_continue(session=<id>)` for the rest — only where that stdio-only tool is held.

**Who was on the other side (2026-10-27).** `episode_actor.actor(fm)` names it from the episode's own fields, never
guessed: `a Claude Code session (id <session>, resumable, model <m>)` (resumable for Claude Code and Codex), `an
agent's saved note from a … session`, `Claude, relayed through the remote connector` (ruling 32), `<name> (an AI
agent), over Messages` or `<name>, over Messages` (the episode's `correspondent`), `ChatGPT, from the person's
exported conversations`; `None` — and no label — for the person's own capture. Ask's prompt labels an agent's turn
`a Claude Code session — the assistant, not the person` (no id; a caller without the person's verbatim words — a remote
connection without `sources` — gets the agent named and no session id in Ask's reply, since an id resumes the
conversation's words; a record that names nobody keeps the old words, so a
benchmark conversation's prompt is byte for byte what it was). Ask's reply adds `· with <actor>` to each "From
conversations no page cites" line, a **Who spoke in the cited conversations** block (at most 4, agents before an
export's app) and the `cicada_sources` read line.

**Factual questions go to Ask (contract 22, remote 15).** Item 1 now reads "A factual question: `cicada_ask`, no recall
first" and names `cicada_sources(entity_id)` for an `ep_…` conversation; the remote contract
says the same, each tool only where the connection holds it (R12). The empty-state primer is ~1,381 proxy tokens (was
~1,368), inside the 1,800 budget.

**Before Sleep (G207, 2026-10-22).** Recall's "Related conversation excerpts" (under the `sources` scope, R-R22)
rank-fuse two legs, keeping 3: the vector leg (`_leann_search_episodes`), which step 0 fills right after capture
(`capture-and-sleep.md`, "After capture"), and a word leg over the FTS passages (`_lexical_search_episodes`:
`search_service.search(kinds=("episode",), vectors=False)`, bm25, ~400 characters of the stored body around the
matched line, the dropped-middle marker blanked). An excerpt from a conversation still `processed: false` reads
`- [<episode>] (<day>, not yet read by Sleep) …`; a read one is unchanged. When a quick read ran, a block **"Not yet
read by Sleep (provisional …)"** follows the page summaries. It holds up to 12 provisional claim lines
(`- [[Page]] <claim text> — \`<claim id>\`, from <episode>`): the top hits' pages first, then claims sharing a word
with the query. Then one line names up to 5 held names that match a query word. It is shown only while the episode
is unread, it is an ordinary block under `_fit_recall`'s budget, and it is Cicada's reading, not the person's
verbatim words, so it follows the claim leg's scope.

**Merge, split, undo — in the conversation (G227 follow-up; owner 2026-10-29: "the separation of entities should mainly
happen by talking to an agent"; `page_join`, `storage.md`).** The agent is the primary door. When the person says "that's
two different things": `cicada_split_page(page, preview=true)` lists the page's numbered sentences and beliefs; the agent
picks those about the other thing and calls `preview=true` again with them — a plain-text proposal ("Proposal (nothing
changed yet): 3 of 5 sentences … move to a new page also called …; links that would follow …") it shows the person;
only on their yes does it call without `preview`, their own words as `reason` (the commit's `Reason:`). "Those are the
same": `cicada_merge_pages(page, into, reason)` after asking. "Undo that split": `cicada_undo_join(page, reason?)` takes
back the newest merge or split on the page still in place (`page_join.latest`; a merged-away id resolves). The
handshake's item 4 and the skill's *Fixing what memory says* name all three and when to offer them (contract 23). The
trust list is G198's (`page_editors`): a listed harness applies at once under its own `Cicada-Author`; any other — a
remote app (`/v1` `page_merge`/`page_split`/`page_undo`, `record` scope) always — files a `page_edit` proposal with a
`join` payload (`op` merge, split or undo) the person applies or leaves with one tap. **Scopes fail closed (R-R3, #552 review):** a preview answers with a page's prose, beliefs, sources, conversations and linking pages, so on a remote call it needs what `cicada_recall_detail` needs (`read`); a `record`-only token gets a refusal naming the scope and nothing of any page, and its merge, split and undo replies carry ids only. `cicada page merge|split|undo`
are exposed in the CLI (`cli_map`, `cli.py`) with the same rule; an edit already uncommitted on a page is committed
apart first. A refusal (no such page, nothing picked, nothing to undo, Sleep holding the pages, a demo bank) writes
nothing.

**Same name, different things (G227, 2026-10-29).** Every door names a page whose title another page shares by
its qualifier (`same_name`): recall's heading is `### <name> (<qualifier>) (<type>, …) — id `<id>``;
`cicada_recall_detail` with a name two pages share answers with each one, its qualifier and its id, instead of picking
one, and a shared page's text ends with a "Shown as: …" line naming the others by id; `cicada_ask` shows the model
`name: <name> (<qualifier>)` and links its citation by id (`[[<id>|<name> (<qualifier>)]]`); a related-page hop, a hub
member or any `_entity_id_for_name` lookup never resolves a shared name to one page unless it is a page's own id as
written. The CLI and `/v1` run the same bodies; `cicada find` lists `displayName`. A same-title inbox question
(owner 2026-10-29, pick the page) reaches every door with the options `GET /inbox` serves (`_agent_question`): the list
and ask lines show "Which <name> is this?" and each page by name, qualifier and `option_key="page:<id>"`, plus
"Another one" (`option_key="another"`, its own thing);
catch-up mode lists them as its answers and records the pick with `cicada_resolve_inbox(id, option_key, quote)`.

**Recall (G140).** Three legs fused by one RRF (`search_service.rrf_fuse`): the stored vectors, the
FTS lexical leg (names, aliases and prose, word by word), and current claims mapped to their
subject — so an alias or a relationship label reaches its page. Each leg is filtered against the pages as their
markdown says now before fusion (`_live_pages`): a page that is gone or `dropped` is never ranked, suggested in the
hints block or rendered (audit 2026-10-05 P2-5). **A cold recall reads what it needs, not the bank** (the CLI and
every MCP session's first call run in a fresh process): one recall lists each directory once
(`bank_index.shared_scans`); the FTS freshness check compares stamps without parsing; a name (one-hop links, a hub's
members, `cicada get <name>`) resolves through `search_index.entity_names` — the index's recorded names for pages whose
`(mtime_ns, size)` did not move, a parse for the ones that did — with a stem match winning over a name match; the inbox
block's causes parse only the pages they land on; and `litellm` is imported only when a model is called. Measured on a
synthetic 3,600-page / 1,500-episode bank with a model-free embedder: 2.15 s → 0.45 s median per fresh-process call,
warm 0.35–1.0 s → 0.08 s, byte-identical replies (2026-10-09). **Each page's heading says its age and state, never a
raw confidence (G210, 2026-10-22):** `### <name> (<type>, last said 3 weeks ago on <day> · fading)`
(`entity_bands.said_line`: today, yesterday, N days under two weeks, N weeks under two months, N months under two years,
then years; `active`/`fading`/`archived`; no day, only the state). Confidence still ranks nothing. The top three pages
carry a bounded "Changed recently" block (claims closed in the last 30 days, ≤ 5 lines), each line saying the day the
fact stopped: `"X" — superseded on <day> by "Y"`, `ended on <day> (its stated end)`, `withdrawn on <day> by …`,
`closed on <day>`;
`cicada_get_perspective(history=true)` lists every earlier claim. **`cicada_timeline(since)`**
answers "what changed" from the commit manifests on demand — ids and counts only, nothing stored,
`read` scope remotely. **`cicada_record_watch`** records what an agent's own tools saw in a saved
video — a summary and ≤ 12 timestamped quotes as `media` spans; Cicada never downloads or watches a
video, and never keeps a transcript. **`cicada_project(project, since?, tz?)`** (G141 PJ-2, `read`
scope remotely) answers where a project stands — next milestones, what passed with no word, the Sleep
queue, what happened and what is around it — from the engine-free read model, printing every relative
word beside its absolute date ("yesterday (2026-09-22)"); a quote of the person's words needs
`sources` remotely. Its first line is the status from evidence (2026-10-23, `project_text.status_word`): `active`
inside the quiet threshold, `quiet` past it, `resting` past 90 days, `fading`/`archived` from decay — never
`planned` because a milestone exists; the milestone count follows as its own fact. Activity is every day a claim
about the project was said, a progress note's day, and every day an agent session ran in its repository
(`project_timeline._repo_days`: the hook's own observation in an episode's frontmatter, consolidated or not; the wire's
`lastRepoDay`, PROJECT_SHAPE g141-6). "Happened" lists a conversation only where the project is discussed in substance
(`_substantive`: two claims about it, or a quarter of what was said there), led by what was said about the project.
**`cicada_continue(session?, before?)`** (G110 slice 1a, stdio only — `catalog.NEVER_REMOTE`,
because it reads the person's verbatim words for a folder the caller names; slice 4 decides its scope) reads where the
work stopped: exact folder first, then the same hook-observed git checkout; other worktrees are related choices,
never an automatically adopted role. An exact episode id or full session id selects its history explicitly.
The bank is resolved once and pinned; the backend never probes this MCP process's workspace.
Use it on demand when the person asks about previous work or asks to continue; a startup hint alone is not a request
to retrieve history. If this session's start named an episode, pass that id as `session`.
Without `session`, a recognised current conversation leads with its recorded source's exact read call and labels
itself as the current conversation; it returns no current turns or possible-role framing. Explicitly read the source
to retrieve the earlier working history. Current means a matching harness/session identity whose registry start is
the newest registered start in this folder/observed checkout, or the newest captured session here carrying registry `continues`
whose registry `started_at` is strictly after the source's activity (including its later registered prompt). The
fallback does not rely on a Codex MCP identity. It requires a complete index, the newest registered start,
a unique newest captured activity and one known source row. The candidate's activity must also be at least every other
same-folder registry row's `started_at` and `last_prompt_at`, including rows without an episode. Equal/earlier or unknown
source activity does not establish current. The current episode is fully parsed
and its folder hash revalidated before the reply. A fresh recognised current session without a recorded source says
so, without promoting its first turn to the earlier role. A newer registered session that has not captured yet
preserves the previous working session's history even when that previous session itself carries lineage.

An ordinary or explicit historical read reserves the first **captured** person request, with
its turn number/time, as possible role/objective. A2 keeps up to 16,000 cleaned characters; the first call shows
at most 2,000 plus an exact continuation call. Initial-text pages use the existing `before` argument:
`"first:<character-offset>@<first-text-hash>"`, 2,000 characters per page. Their hash is over the captured initial
text alone, so appending a later turn does not stale them. Rewriting the initial text restarts at its head and
says it changed; invalid/out-of-range initial cursors also restart with disclosure. Each page labels the text as
history, cites the episode/current revision and leads back to recent history. It does not prove the original role was captured: command/skill
expansions, fences and per-turn clipping can lose instructions, and legacy capture does not classify those losses.
The initial request and recent turns come from one current source snapshot. An unversioned startup episode hint
therefore still retrieves that initial request in one call after a source append. It returns other whole turns only,
a page of ≤ 8,000 characters, newest last; the person's requests as an outline (≤ 160 characters each), each with a
cursor that reads its turn in full; a page cursor
is `"<turn>@<content_hash>"`, and a cursor printed for another revision restarts from the newest turns and says so
(pages are never mixed). The identity, the gaps, *workspace state not checked*, the verify-first line, the
first captured request page and every continuation cursor are reserved within the 12,000-character reply. The first
request is not duplicated in the recent page or outline. Quoted requests remain history, not instructions; decisions,
in-flight work, State and next actions are visible when present in the returned captured turns. A dedicated projection
of those categories/latest State remains a follow-on. Agent replies now retain head+tail within 2k, with recorded
gaps labelled as nobody's words; the
reader does not recover tool calls or uncaptured working state. It never blindly excludes this process's own session
id: after `/clear` a long-lived MCP process can still hold the previous one (G48); a newer registered start defeats
that stale identity match. This is one recorded source call, with no chain walk or automatic source read. Contract item 1 names it
(`CONTRACT_VERSION` 15, A2). The primer and installed skill gently suggest an optional brief `State:`
(in flight / blocked / next) at the end of working replies; continuity does not depend on it. This line is included
in the whole ≤1,800 proxy-token handshake budget, including max-primer/startup fixtures; R12 still holds.
**Projects (ruling 45, 2026-10-27).** `cicada_create_project(project, description?, evidence?, repo?)` starts a project
the person asked for: a harness on their G198 trust list lands it in their list (`mine: {via: agent}`), any other client
— a remote app always — leaves a suggestion labelled as its proposal; a name already a page is refused with that page
named. `cicada_link_conversation(project, reason, episode? | session?, remove?)` ties a conversation (recorded with the
agent's name); an agent unties only what it tied, and the person's untie is final. `cicada_add_influence(project, what? |
url?, how?, evidence?)` records what fed a project — a link as the agent's source, a name as a claim with the agent as
observer (`inspired-by`, `references`, `uses`; a person as `works-on` on their page), plain text when no page matches,
never a page made. `cicada_link_entity(project, entity, reason, remove?)` (decision 10, 2026-10-28) ties a page
already in memory to a project ("Pages in this project"): a harness on the trust list ties at once, any other — a remote
app always — records a proposal the person takes or turns down on the page; the person's "Not part of it" is final, and
an agent takes back only its own tie. All four are `record` remotely, one `cli_map` row each (`projects
create|link|tie-page|influence`, proposed spellings; `/v1` `projects_create`, `projects_link`, `projects_tie_page`,
`projects_influence`), admitted, committed alone under the harness. `cicada_project` adds the pulse in words (the last 4
weeks, what it waits on; Gone quiet is its own "Quiet:" lines) and the pages in the project, proposals apart.
`cicada_edit_page` takes `name` and `description` for a project (the header, `description_by` the harness; the old name
stays an alias; untrusted → an inbox proposal). `cicada_project`'s reply says whether the project is in the person's
list, their description (remote: only with `sources`), and how many conversations and influences are tied. Handshake
Option A: the primer names none of them; the skill does. `cicada_capture_turns` takes an optional `project` — the
relaying app's word on which project the conversation is in, only from its own context, kept as `relay.project`.
**`cicada_note_progress`** (G141) records a happening or a milestone the person
described — observer always the agent, `record` scope remotely, never creates a page, echoes how the date
was decided; `cicada_retract_claim` withdraws an event the same way.
**`cicada_add_source(subject, ref, predicate?, access?, kind?)`** (G61 phase 2 S1) records where a
fact can be checked when there is no claim to write — only a source the person named, never one the
agent guessed; it is not `cicada_sources` (conversations). `record` scope remotely, where a path, a
repo or `access: local` is refused; it commits alone under the harness. `cicada_write_claim(sources=)`
takes a string or `{ref, access}`. Since G61 S3-a (contract 12, remote 9) the primer names it, and takes an optional
`entity` (an existing page that knows more about the source). **Where to check (ruling 36 D5, contract 20, remote 14,
2026-10-22):** the tool, the primer and the skill carry one definition — *a link where the current state of this thing
can be checked — a profile, a personal site, a publication list, a repository or any page; Cicada re-checks it on a
schedule and agents check it before answering about the thing* — and the tool takes `inferred: true` with `evidence:
[{episode, quote}]` (≤ 3, the first located one kept as a span) for a source the agent found itself, on the record or
in research. That lands as a proposal (`proposed: true`, `storage.md` "Where to check"): untrusted, no picture, no
re-check, joined to the page's one question on the next Sleep; the reply says it waits for the person's yes. A profile
ref is stored in its canonical form with its kind as the predicate when none is given. The direct add (the person
named it) is unchanged. The CLI table's proposed `source add` row (`cli_map`, not exposed yet) names both arguments,
so the CLI↔MCP parity test holds when it ships. **`cicada_change_source(subject, ref, predicate, action,
reason, new_ref?, new_predicate?, access?, entity?)`** corrects (`update`) or removes (`remove`, `reason` required) a source
the caller added — keyed `(ref, predicate)`; `record` scope remotely, a remote caller never names a path, a repo or `access:
local`; refused with nothing written in a demo bank, while Sleep runs, for no such page or key, for an entry that is not the
caller's, for a ref that holds a secret; one commit under the harness whose manifest line names neither the ref nor the reason
(both are in the diff and the tombstone). Its ledger row is ids and enums only (`source_added|source_changed|source_removed`).
**The agent check (G61 S3, 2026-09-30; shadow — recommend-only).** "Give agents a place to look for information to update
memory before surfacing it to the user." A source on a page that could answer a PENDING inbox question is a **check entry**
in the reading queue (`reading_queue.check_entries`, derived at read from `inbox_service.load_inbox`: the item is
`checkable`, or `inform_only` for a host only the person's own session may open, and the source is one of the item's own
ranked targets — `source_check.targets_for`, `fact_sources.rank`, least recently checked first within a trust class; **the
owner's own page counts only what the person added or took ("Use this source")**, D2). The one consent is the **per-site
permission** (D5: no one-off ask): an entry exists only while agent reading is on, the link may be handed to an agent at
all (`agent_may_read`), the person allowed its SITE, the site is not paused by a `needs_login`, no non-waiting ask row holds
the link and no agent looked at it in the last 7 days. `cicada_reading_queue` lists it ("a source to check for `inbox-012`:
<question>", one per site per call) and names `cicada_record_check` only where the caller holds it; the recall hook's and the
Feed's waiting counts include checks; Settings' site list also shows a site only sources reach, with how many questions it
could answer (`checks`, counts only; `SITES_SHAPE` reading-sites-4, `inbox` joins its stamp).
**`cicada_record_check(item_id, source, outcome, option_key?, proposed_value?, quotes?, summary?, via?)`** (`record` scope;
`check_record.py`) writes what the caller's own tools saw: outcomes `supports | proposes | unclear | contradicts_all`
(findings) and `needs_login | blocked | not_found | failed` (not findings: only the machine-wide ask store, exactly as
`cicada_record_read`, no bank write and no Sleep gate). Refusals, in order, write nothing: demo bank, reading off, unknown
outcome, malformed id, a link that may never be handed to an agent, a source that is not one of THAT item's listed targets on
an allowed, unpaused site (`reading_queue.authorizes_check`, recomputed now so a resolved item, a removed source or a
switched-off site revokes it), a source an agent already looked at for this question in the last week (UTC days — one row per
source means the day cap alone would never bite), a finding without a quote, an option the item lacks, Sleep running, and the
caps (3 a day per question, 30 a session). The candidates are memoised on the inbox+entities+sources stamp; the recall hook
only reads the memo (a cold one is not counted yet and warms in the background; it never turns the site count "unknown"), so it never loads the inbox on its 300 ms. A finding is one **`source-check` episode** (`assistant:` summary, then `attachment [<host>]: as
<harness> read it` and ≤ 3 quoted lines ≤ 240 characters, so the quotes are `page`-kind spans — D4, no seventh evidence kind;
`processed: true`, no `evidence_kind`, `media_entity_id` = the source's own `entity:` page when it still resolves) and one
row in the item's `checks:` (`{at, checker, checker_kind, ref, host, outcome, option_key?, proposed_value?, quote?, episode,
via?}`, newest per source, ≤ 5), committed alone under the harness. **It never writes a claim, adds an option, resolves,
defers or reorders anything**; a `proposes` value lives on the row only. `GET /inbox` serves `checks[]` and `lastCheckedAt`;
`cicada_check_nudges` prints `Check first: <ref> (<access>) — … cicada_record_check(…)` for a queue-listed source and
`Checked by <who> · <host> · <day>: "<quote>" — supports <option> (reported, not verified; the person still answers)`, the
quote only where the item's `Cause:` quote shows (never to a remote connection without `sources`). The ledger row
(`check_agent`, beside `read_agent`, out of every Usage view) is ids and enums only. The card shows "Your agent looked at
<host> · <day>", the quote, what it points to and "What your agent reported, not checked by Cicada. Nothing changed; you
decide." — no highlight, no tag, no reorder.
**Public things settle (owner ruling 2026-10-16, TODO ruling 27; amends S3).** "A web lookup answers 'what is X' for
public things and closes the question. The answer is saved with its link and quote, and you can undo it from a 'Settled
by a check' list. Never searched: people's names, your own files, your projects, your life." The S3 rule above — a check
settles nothing — still holds for every other question. **Which:** a pending conflict or clarification whose subject is
a `company`, `concept`, `tool` or `media` page (or such a suggested type with a pending line); never a `person`, an
untyped name Cicada's own description says is someone (person words; "the user"/"the person" as the speaker aside, and
one it says is the speaker's own kept home — 2026-10-19), a person page's name or alias, the owner's page, a question
about Cicada's own runtime settings on its own page (`own_settings`: the Sleep engine choice, the scheduled-plan
switch, the schedule's time — never searched, never asked, 27b),
a file, path or handle, a page with `path:`/`repos:`, a project, a question that says "you/your", an option naming a
person or saying "my"/"her" (labels ride in the prompt), a conflict tied to the person in any way — first person, the
owner's name, a project's name, "currently uses", "planned for", "<owner>'s thesis" — or two different things sharing a
name with no option that is the page's own name (2026-10-20, `features.md`), a question the person already took a check back on
(`web_check: undone`), a multi-valued predicate other than what the thing *is*, or a conflict whose predicate is not
world-truth (`locus` world/artifact or a short public list: `description`, `is-a`… — `web_settle.classify`). **What it
is** (owner, 2026-10-16, his own example "Is <tool-a> an agent harness or an AI agent itself?"): a type question
(`web_settle.TYPE_PREDICATES`: `is-a`, `type`, `kind`, `category`, `genre`, `description`) is eligible though `is-a` is
multi-valued; one option settles only when the page rules the others out — defines it as that option and nowhere as
another (Sleep's answer must say `others_ruled_out: true`) — the item's own `both` option when the page describes it as
more than one of them (2026-10-19) — one cited claim per
option, nothing closed — and never an option the item does not have. **What leaves the machine:** the search query is the
subject's name plus at most one generic category word from a fixed list, read from Cicada's own description (Sleep's
lookup and the sweep also from a mention line where the word stands beside the name, `web_settle.context_category`),
none on a type question and none when unsure (`web_settle.query_for`); nothing else. **What the model may read (ruling 27a,
owner 2026-10-16: "Yes, use local context"):** Sleep's lookup prompt carries `web_settle.local_context` — the
description and up to two mention lines, ≤ 600 characters, scrubbed, no one's name, no link or path — only to judge
which search result is the thing the person meant; it never enters the query (capture-and-sleep.md). **The person's own agent:** `cicada_check_nudges` adds `Public: look it up on the web (search only
"<query>"), then settle it — cicada_record_check(item_id, source=<the page>, outcome="settles", option_key|proposed_value,
quotes=[{quote}])` for such a question; `outcome="settles"` writes one cited claim (`web_settle.settle`: a `web-check`
episode holding the link and the quote as a `page`-kind span, the claim observer `agent`, `source_trust: external`,
`origin: web-check`; a conflict's other open option claims close today in its favour; a name with no page is held on
its pending line, no page is created), moves the question to `inbox/settled/`, and commits alone under the harness
(`Web check <date>`, the session trailer). Refused, writing nothing: a connected app (it reports, never settles), a
question that is not public, a link that is not a public page (`reading_hosts.classify`, no walled host), no quote, no
option key / answer, Sleep running, ten settles a session. **A "same as?" pair of two public things (2026-10-29, G21):**
the nudge line reads `Public pair: look each name up alone (search only "<a>" and "<b>"), then settle it with how "<a>"
relates to "<b>" — cicada_record_check(…, outcome="settles", proposed_value=<part_of|has_part|made_by|makes|
alternative_to|version_of|has_version|different>, …)`; the answer goes through `web_settle.settle_pair`, the writer
Sleep's tail uses — one cited relation claim on the page the name was weighed against, the question to `settled/`,
undoable under "Settled by a check", and a proposal to remove the alias that made them meet (`storage.md`). "Same" or
any other value is refused (the person's tap merges); a pair with a person or the person's own work is not public and
is refused as before. **Repository state** ("did PR #n merge", "is G<n> shipped")
is never searched: `From the repository: answer it from its commit — cicada_record_check(…, source="commit:<sha>",
outcome="settles", …, quotes=[{quote: <the commit's subject>}])` is shown to, and accepted from, a harness on the
person's trust list only (`page_editors`); the source is `commit:<sha>` or a GitHub/GitLab commit or pull-request link,
and the backend never runs git in a declared repo. **Sleep's own lookup** is `web_lookup` on the tail (capture-and-sleep.md).
The ledger row (`web_check`) is ids and enums only. The person sees and undoes all of them under "Settled by a check"
(features.md).
**Tracked sources re-checked (G61, TODO ruling 26, owner 2026-10-14: "Update, dated; the newest evidence wins").** The
inbox check above still settles nothing; a *tracked* source is different: the person's own, one they took, or one
Cicada's read confirmed (`fact_sources.trusted`) is re-checked on a cadence (30 days, the person's `recheck_days` 7–365)
or when the person asks, and what it says now is a new dated belief (`source_refresh`). A public page is Cicada's own
read on the Sleep tail (`network.md`); a login-walled one (LinkedIn and the like) and a public one Cicada saw change
without a machine-readable fact are the person's own agent's, through two stdio-only tools on a small lease queue outside
every bank (`$CICADA_HOME/refresh_queue/<bank>.json`, the explore queue's rules: one live lease per site across every
agent, 15 minutes, a wall pauses the site a week). **`cicada_refresh_claim(limit?, release?)`** leases due sources (default
1, ≤ 5) only while agent reading is on and acknowledged, the site is turned on in Reading in your browser, not Never explore, and —
for a walled page — the signed-in session is allowed (ruling 25 D2); it lists what memory holds now for that fact.
`release` hands one back (`needs_login | blocked` pause the site; `failed | skipped`). **`cicada_record_refresh(entity_id,
source, lease_token, outcome, predicate?, value?, ended?, quotes?, captured_at?, summary?, via?)`** records `read` (the
value now and/or `ended` values with their day, one to three quotes required) or a miss (`not_found | gone | parked |
moved`); `captured_at` must be within the last two days. It writes one `source-refresh` episode (`attachment [<host>]: as
<harness> read it on <day>` and the quotes: `page`-kind spans), folds the reading with the one rule (`source_refresh.fold`:
a belief last said before the capture closes as history, one said after it stands, the same day or undated asks once — a
`kind: divergence` item, trigger `sleep/source-refresh`), updates the source's `refresh` state, and commits alone under the
harness (`Agent write`). Refused, writing nothing: a demo bank, reading off, an unknown outcome, a lease that is not this
session's, a reading with no quote, a stale capture, Sleep running. **The hook's one line:** the SessionStart note adds "N
tracked sources are due for a check …" (`recall_text.refresh_line`, counted from the warm cache by
`source_refresh.agent_due`, only while the switches allow) — a statement; nothing scheduled works them (ruling 4). The CLI
rows (`source refresh-claim`, `source refresh-record`) are proposed spellings, not exposed.
**`cicada_edit_page(subject, reason, edits?, section?, text?, add_aliases?, remove_aliases?, evidence?, resolves?)`**
(G198, owner ruling 2026-10-14; `page_edits`, `page_editors`) changes a page's **words or aliases**, never its facts:
`edits` are exact `{old, new}` replacements in the prose before the claims fence (`all` for every occurrence, `pin` to keep
the fix through Sleep's rewrites — on by default with `all`), `section` + `text` rewrites one `##` section or an Article
`###` section (`Related` is refused: it is rebuilt from the graph), `add_aliases` / `remove_aliases` change its other names
(a removal is remembered in `aliases_removed`). A code fence or a `#`/`##` heading in any of them is refused. The `reason`
(one line, ≤ 500 characters) becomes the commit's `Reason:` line; `evidence` quotes become `Evidence:` span lines (offsets,
never words). **Trust decides the path:** a harness on the person's list (`$CICADA_HOME/editors.json`, edited only by
`PUT /settings/editors`; `claude-code` and `codex` until the person changes it, then exactly their list, an empty one
included — owner 2026-10-14; `agent` and remote apps can never be on it, and a remote caller is refused whatever its label) writes the page at once and commits
it alone — `Page edit <date>`, `entities/<id>.md: edited (trigger: mcp/<harness>)`, `Cicada-Author: <harness>`,
`Cicada-Session:`; any other files a `page_edit` inbox item (validated against the page first) committed as `Page edit
proposed <date>`, and the reply says the person decides. `resolves: [{id, option_key|answer}]` answers inbox items through
the same backend route as `cicada_resolve_inbox`, after the edit's commit and outside its page lock, and only when
`evidence` holds a span located as the person's own words (`kind: user`) — never for a proposal, never a `normalization`
or `page_edit` item. The edit's commit carries those quotes as `Evidence:` lines, and the person's located words go with
each answer as `cicada_resolve_inbox`'s `quote` (a relay episode, `relayed_by` the harness — G115), so the answer cites
them too. A relayed quote never reaches a `page_edit`: the tool refuses the item, `inbox_ask_gate.NEVER_ASKED` keeps it
out of every ask path, and the backend refuses (403) any answer to one that says `via: "agent"` or carries a relay. A `page_edit` item is app-only: `cicada_check_nudges`, recall's inbox block and the recall hook never
serve it, and `cicada_resolve_inbox` refuses it (an agent never applies its own proposal). Review round 1 (B1): every
caller's inbox id must be exactly `inbox-<digits>` (a case variant or a percent-encoded id named the same file on a
case-insensitive disk), the backend's resolve (every door) takes only a lowercase stem with no dot, slash or `%` that
the inbox directory lists exactly — a spelling that resolves only through the disk's case folding is a 400 — and every
answer an agent's
tool posts says `via: "agent"`, which the backend refuses for a `page_edit` (403) — defense in depth: a process that
skips the tool can write the bank's files anyway. The result of an edit is checked as well as the request (B2): an edit
whose result moves the claims block, opens a code fence or changes a `#`/`##` heading is refused. Refused with nothing written: a
remote caller, a demo bank, Sleep holding the pages (asked inside the write admission, `EDIT_SLEEPING`), words not on the
page or on it more than once without `all`, words only in the claims. Admission → page lock → commit, like every agent
write. Stdio and the command line only (`catalog.NEVER_REMOTE`); the CLI spelling `cicada page edit` is a proposed row.
The primer names it in one clause of item 4 (contract 16).
**`cicada_backlog`**, **`cicada_add_backlog_item`** and **`cicada_add_backlog_note`** (G150) read and file a
project's backlog — see Backlogs.
**`cicada_save_design`** and **`cicada_design_search`** (design taste, 2026-10-14; `design_refs`, `design_index`).
Save: when the person says they like how a site or screen looks, the agent sends the screenshot it took — `image_path`
(an absolute path to a PNG or JPEG it saved, ≤ 4 MB) or `image_base64` — with `url`, a `note` on what they liked, and any
HTML/CSS they pointed at as `snippets` (`title`, `tags`, `region` optional), and since looks v2 the page's computed type
and colour roles as `tokens` (`design_tokens.JSON_SCHEMA`, `storage.md`; what is out of bounds is listed back as
"tokens left out"). **`subject`** (owner 2026-10-20) is the id of the page the look shows — a page recall returned; an
unknown id is refused with nothing written, and none given lets the writer place it (the one page whose trusted site it
is, else the saved link's page, else nowhere — `storage.md`); the reply says which page, and `design_search` rows say
"on page <id>". The note is the agent's: it is shown as "Noted by <harness>", never as the person's words. The stdio server reads that file as the
agent's own child process, and only a regular PNG/JPEG outside `~/.claude`, `~/.codex`, `~/.cicada` / `CICADA_HOME`,
`~/Library` and the bank (the transcript rail, and the app-reads-`~/Library` rail). The refusal is **by file identity,
never by spelling** (review 2026-10-14): the resolved file and every folder above it are compared by `(st_dev,
st_ino)` with each refused folder, so a re-cased path (case-insensitive APFS), another Unicode form or a firmlink
(`/System/Volumes/Data/…`) is refused like the plain one; the file is opened once with `O_NOFOLLOW | O_NONBLOCK` and
judged on that descriptor (`fstat`: a regular file under 4 MB, the same identity as the path), so the file checked is
the file read. A remote caller can never name a path. The palette is read before the write admission; the write holds it through its own commit as the harness with
`Cicada-Session:`; refused in a demo bank and while Sleep runs. Search: words, a picture (`image_path` /
`image_base64`) or nothing (the newest); each row gives the link, palette, look words, fonts, what the person liked, and
the screenshot's and reference's file paths so a local agent can open the picture. **Both are stdio-only in this slice**
(`catalog.NEVER_REMOTE`): which scope a remote picture belongs under is an open question for the owner. CLI spellings
`cicada design save` / `cicada design search` are proposed rows, not exposed. The portable skill
`skills/design-taste/SKILL.md` tells an agent to search the board before building UI and to cite what it drew from. **A link's view (owner rulings 2026-10-14):** the tool's description teaches the link-title grammar (`storage.md`) —
`[Title](url "bookmark")` is a card; `mention`, `bookmark`, `screenshot`, `captures`, `look`, and `screenshot`/`look`
with a ` yyyy-mm-dd` day — in the schema, not the handshake (the 1,800-token note does not grow, and R12 holds:
`test_link_views` checks every view word the description names parses). An agent writes one only when it means it, alone
on the link's line for a block view, with `pin` so Sleep keeps it; a plain `[Title](url)` stays a link.

**Video watch (G162, TODO ruling 17).** `cicada_record_watch` takes three more arguments the agent states about its
own work — `basis` (`transcript | frames | both`), `engine` (`captions | video_link | local_frames | speech_to_text |
browser | other`) and `duration` (kept only when the page has none) — none verified (R-VU2: the app says "an agent recorded
that it watched", never "Cicada watched"); an unrecognised value is dropped and the record is still written. A repeat
of the same record with a new basis merges into the episode in place (`transcript` + `frames` is `both`; `content_hash`
and `processed` untouched). **A video's state is derived, never stored** (`video_state.py`): `none | transcript | watched
| watched_and_transcript | recorded`, the set-union over the `source: video-watch` episodes that name its link, matched by
the url-index key (`media_ingestor.url_hash`, never the media entity id); a record with no basis is `recorded`, never
`watched`. The set of videos is the Feed's (`is_video_page`, the twin of `FeedKind.of`, pinned by
`api/tests/fixtures/video_kind.json`). **The person's video queue lives outside every bank** —
`$CICADA_HOME/video_queue/<bank>.json` (`video_queue.py`; a bank name that is not a plain slug gets an ASCII slug plus a short sha1 of its name, never a refusal; orphans are dropped only while the url index answers non-empty; keys only, never a URL or a title; flock plus atomic replace;
expiry applied in memory and persisted inside a write) — so nothing in its lifecycle dirties a bank, commits, or answers
409 while Sleep runs. `cicada_video_queue` (`read`, read-only) lists what waits; `cicada_video_claim` (`record`) leases
the oldest queued videos (10 a call, 45-minute lease) or, with `release=[{url, lease_token, code, reason}]`, hands one
back (`needs_login` tells the agent not to sign in and tells the person). **Ruling 34 (2026-10-22): a lease ends only by
its token.** Each claim mints a 128-bit `lease_token` per video and prints it on that video's reply line, ahead of the
provider's title; a hand-back ends the lease only with that video's token, and anything else (no token, a wrong one, the
pre-ruling `{url, code, reason}` shape, a row claimed before tokens existed) answers *not handed back: pass the
lease_token*, and the lease lapses on its own clock. A `cicada_record_watch` with no `basis` closes a leased row only with
its `lease_token` (optional argument; with a basis the record closes a row that it meets, whoever records it). The session
id is never proof of holding (conversations on one connector can share one, the CLI has none, a restarted stdio process
gets a new one); it only refreshes the caller's other leases, and never past three lease periods from the claim
(`MAX_LEASE_PERIODS`). Every queue writer reads the saved videos under the queue lock, so a video saved and queued while
another writer waited is never dropped as an orphan. It is in `WRITE_TOOLS` (the demo gate, the write
lock; only its per-video title/channel lines are fenced, Cicada's own instructions in the reply stay outside) but `runtime._writes_bank` is false for it, and **a lapsed lease is judged only when Sleep is not
holding the pages** (`ToolContext.pages_held()`, asked lazily), so a drain cannot burn a video's three attempts; while a
lapsed lease is due, the `videoQueue` stamp also carries that hold bit (`<mtime>:<due>:<held>`), so the hold ending moves
the component the app follows with nothing written. `VideoStateCache.reset()` on a bank switch keeps what a page asked
for (`asked`), and the switch reads the new bank at once.
`record_watch` credits the queue whether or not its bank commit ran. The lease lifecycle is model-checked by `.claude/skills/verify-video-queue` (run it on any change to the queue, the record credit or caller session ids). **No batch cap** (a hand-off takes every selected
video; the queue file's ceiling is 2,000 rows) and **no site list** (any saved video can be queued; a login wall is handed
back and surfaced). The hand-off prompt (`video_prompt.py`, ≤ 1,200 characters) is provider-neutral, names no browser
route by default, and carries the browser permission only while the single reading permission is on; the seam for "how
your agent watches" is `video_prompt.method_clause`. Recall and its hook are deliberately not extended for video. Contract
item 3 names all of it (CONTRACT_VERSION 11, remote 8, past G166's 9 and 6; remote names each tool only where held).
**Reading with the person's own agent (G166, spec `2026-09-29-reading-the-web-design.md` §8.4, Route A).** Cicada never
spawns a browser and never signs in (`test_reading_never_spawns_browser.py`, R-RW9: `--chrome` is in no argv). The
person's own agent — a local harness with a browser tool, or a remote connection that can drive one — reads through a
queue. The person's per-link **Ask an agent** (`POST /reading/asks`) is a row in
`$CICADA_HOME/reading_asks/<bank>.json` (`reading_asks.py`: outside every bank, no URL stored — joined at read from
`sources/url_index.json` —, 7-day expiry applied in memory, `fcntl.flock` because the backend and every stdio process
write it); an unsaved link is saved first *without a fetch* (`RawItem.defer_enrich`) as the person's own save.
`cicada_reading_queue(limit)` (`read` scope, fenced remotely) lists what waits: the person's asks first (oldest first),
then **saved pages of sites the person allowed** (below) — empty unless `reading.agent` is on, never a denied class,
**one entry per site per call** (the rest are counted). It is one read model, `reading_queue.py`, behind the tool, the hook
count, the Feed's `waiting` and the settings page: asks are rows, a site's pages are *derived at read* from
`reading_walls.py` (never fanned out as rows, so a site switch writes one line, a new wall page joins with no write and
turning a site or the master off dequeues at once). A site entry whose page was not saved through a saved-content channel
(Telegram, an agent's save, a chat export: the person's own words) is served only to a caller holding `sources`. **The reason travels with the read (vision item 1, 2026-10-28):** an ask or site row whose link the person said why they saved (`saved_why.reason_of`: G191's newest answer — its labels, a project as "For <name>", their words — else a `## Saved because` section) ends `— saved because: <one scrubbed line, ≤ 240 chars>`, and the reply's head then says to read for it and to record the page's specifics as `facts`. The reason is the person's own words, so a connection sees it only with `sources` (`ctx.raw_excerpts`); it is filled by `reading_queue.with_why` in `entries()` alone, never on the hook's counting path (`counts`). The copy-for-an-agent prompt (`reading_prompt.READ_FOR`) says the same. `cicada_record_read(url, outcome, summary?, excerpts?, via?, note?, title?, facts?)` (`record` scope) takes `read |
needs_login | blocked | not_found | failed`. Only a **successful read is memory** (`page_read.py`): one episode
(`assistant:` summary, then a quoted `attachment [host]:` block, so quotes are `page` spans — text the agent
*reported*, never the person's words or checked by Cicada —, `processed: true`, `processed_by: agent`), one `describes`
claim (a re-read closes the previous one), a thin description filled, and a `read:` stamp on the page. **`facts`** (read-for-specifics, 2026-10-28): up to 8 `{subject, predicate, object, quote}` — what the page states about a thing Cicada already has a page for. Each quote joins the episode as one more `> ` page line (never twice), and each fact is a claim on its subject's page through `agentic_write.write_claim` (observer `agent`, confidence 0.6, a remote app's `remote:<id>` origin, never the person's observer) whose evidence is that line's `page` span, with the read link as the agent's own untrusted where-to-check source for that predicate, `entity:` the saved-link page (tombstones and caps drop the source, never the claim). Left out and counted in the reply: a subject with no page (a read never makes one), a person (their facts come from their own words, `cicada_record_profile` or ruling 44), a happening (`cicada_note_progress`), a malformed fact or one past the cap. Every touched page is in the same commit; the field is on all four doors (stdio, the local tool door, `/mcp` + `/v1` from `remote/tools.py`, `cli_map` `--facts` JSON). It commits alone as
the harness and never mints a page. **Only a link the person asked about, or a wall page of a site they allowed, can be recorded** — plus one dated exception, the person's two YouTube lists (owner 2026-10-16, *YouTube lists* below: a standing ask for exactly those two pages, recorded only through `cicada_record_youtube_list`, never through `cicada_record_read`) (`reading_queue.authorizes`: `("ask", row)`, `("site", None)` or nothing; a row this tool wrote itself, `origin: site`, authorizes only while its site is still allowed and the page still a wall page, so switching a site off revokes recording at once): `cicada_record_read` refuses every outcome for any other URL (a saved public page with no wall included), and `reading_asks.record_outcome` creates a row only for that site case (`create=True`, `origin: site`) — an agent, or a page steering it, cannot rewrite a saved link's description or plant a `needs_login` banner on a link nobody asked about or on a site nobody allowed. **The exposure, stated:** with a site grant the person consented to a *site*, not to a page, so any agent holding `record` can then record a wall page of that site; the structural denials (R-RW5), the master switch, "every outcome but `read` is ask-store only" and `page`-kind spans bound it. A site-origin `read` writes no ask row (the page's own `read:` stamp keeps it out of the queue) and site rows are evicted before any explicit ask (`MAX_SITE_ROWS` 200). A `read` is also refused while Sleep runs on stdio, as the remote path refuses it (its reply says to keep the summary and record it when Cicada has finished). A `page` span from `page_read` reads "From the page, as <agent> read it" everywhere the app labels it (the episode's `source: page-read` rides `/episodes/{id}/text` and the provenance conversation rows), never a bare "From the page". **The other four outcomes touch only the ask store**: no bank write, no commit, no Sleep
gate (`RemoteRuntime._writes_bank`), and the `reading` sync component (asks + `reading.json` mtimes) moves so the app
shows "needs you to sign in" over SSE at once; the tool's reply tells the agent to stop. `via` is what the agent *said*
it read with — self-reported, never proof. The last successful read's day is kept in `~/.cicada/reading-last.json` (one small file; `GET /reading/settings` never scans the ledger). Settings live in `~/.cicada/reading.json` (`reading_settings.py`: `agent`,
`agent_sites` — `{site: day}`, empty by default, granted only for a site Cicada's reader could not read —, `agent_ack` with
a version (2) that re-asks when the sheet's wording changes; the old `agent_hosts` key is ignored and dropped on the next
write). **There is no pre-picked list of sites** (owner, 2026-09-30: "limiting the amount of sites makes no sense to me,
because we will never know which sites this will happen"): a **wall page** is a saved page Cicada's own reader could not
read — a sign-in, a consent wall, a refusal, or a host the backend never requests — decided by `reading_walls.wall_kind`
from stamps the fetchers already write (`fetch_status`) plus the closed host set, and only while it holds no words (no
`describes` claim, agent read stamp, substantive `## Description`, `description_source`, or — an X bookmark, whose saved item is the post — a non-empty `## Notes`; a saved sign-in or consent URL is
never one). The stamps are written wherever the reader fails: at save time (`MediaMeta.fetch_status`), in the in-cycle pass
and in the backfill, in the backfill's own vocabulary and 30-day backoff, so a site surfaces when its page is walled, not
when the capped backfill reaches it. Wall pages group by **site** (`reading_hosts.site_of`: a walled family folds to its
name, else the registrable-ish domain, never folded under a shared host such as `github.io`); the sites surface on
`GET /reading/sites` (hosts and measured counts only, ETag over `reading`+`entities`+`sources`, `def` in the threadpool,
memoised in `reading_queue.sites_snapshot`; a row's `allowed` counts only while agent reading is on, `granted` is the
stored grant, and `waitingNotAllowed` follows `allowed`) and a `PUT /reading/settings` `sites` patch grants or removes one (422 for a
site never surfaced; turning a site on again lifts its `needs_login` pause — an agent that was not signed in pauses that
site's derived entries until the row expires, a week). Per-page "Ask an agent" stays and needs no site permission. The
closed host sets are one module (`reading_hosts.py`, dot-boundary matching, no DNS): walled hosts (X, Facebook, LinkedIn,
Instagram, TikTok and Reddit, the families the backend never requests; `t.co` is never offered at all) have their **page never
fetched by the backend's page readers** (R-RW4: `media_ingestor.enrich` and the `link_enrichment` backfill, through
`link_enrichment._excluded_media`; the exceptions are TikTok's provider oEmbed call, which never loads the page, and the
Reddit and X connectors' own API calls), and a link that carries a secret or a
side effect, is local, an AI vendor's own page, a video (`cicada_record_watch`) or a paper is never offered at all
(R-RW5). Contract item 9 (`CONTRACT_VERSION` 13, `REMOTE_CONTRACT_VERSION` 10 since G61 S3) exists only while the switch is on and is an
*instruction*, not a promise: read in the person's own session, never sign in, record `needs_login` and move on, never
post. The **choice of how the agent reads** (`agent_methods.py`, `$CICADA_HOME/agent_methods.json`, `GET|PUT /agent-methods`) is an
instruction Cicada passes to the person's own agent, never authority: `auto` (the default, no tool named), `own` ("don't
load a separate skill") or a catalog skill whose `roles` list the job ("the person chose the `<name>` skill for this: use
it, and if it is not installed for you, say so and stop"). It flows into "Copy for an agent" (`reading_prompt`), the stdio
queue reply and one primer line (`handshake.build(methods=)`, `MAX_METHOD_LINES` 2, fixed part, R12-checked); a tool reply
or primer line never names a skill to a remote connection or a client that is not one of `skill_catalog.AGENTS`, and the
copied prompt, which can be pasted anywhere, names it conditionally ("if you run on this Mac and can load skills … else
your own browser tools"). A skill the person picks gets a page in the graph
(`skill_pages.py`, the one writer, only from that selection or "Add to your graph": `type: skill`, `tags: [agent-skill]`
(`skill_tag.py`, so `state_dictionary._preferences` never lists an installed tool as a working agreement and Stage 4 never
mistakes one for a pattern), evergreen, `human_edited`, no claims, one `user` commit; an agent-made `tool`/`concept` page of the
same name is adopted, any page the person edited is left alone). Every string in these paths is neutral about providers
(`test_provider_neutral_copy.py`). The remote reply for `cicada_reading_queue` is fenced as reference data, so the never-sign-in rule also sits in its unfenced tool description, and a connection that can read but not record is told to stop and tell the person. A saved page's title is folded to one line and scrubbed before it is printed. Because the queue is outside the bank, nothing in `_state.md` can say links are waiting, so the recall hook and the
remote handshake add one per-request sentence (`recall_text.reading_line`) when more wait than the session was told; a session that has seen the queue drain hears the next ask as new.
Routes (`routers/reading.py`, none a Store domain): `GET|PUT /reading/settings` (shape `reading-2`),
`GET /reading/sites`, `GET /reading/sites/{site}/icon`, `GET|POST /reading/asks`, `DELETE /reading/asks/{urlHash}`,
`GET /reading/prompt`; `GET /sources` carries `MediaSourceItem.read` (`status, by, tier, at, via, harness, host, askable,
reason` — `askable` is the structural verdict plus the master switch, never a site —, `wall, siteKey, siteLabel, siteAllowed,
siteIconHost` for a page the reader could not open, `queuedBy: site`, merged from the page stamp and the ask row, newest
wins) so the app holds no host table; a retired interstitial or login-wall page (`enrichment_status: junk`) is let through
the Feed's junk filter only when it is such a wall or an agent already read it (Track P R5, amended 2026-09-30). **Site icons**
(`logo_service.ensure_site_icon`, `logos/<bank>/sites/`) come from the icon service only — the walled site is never
contacted, not even for its favicon; a 404 is retried once with `www.`, only a site the surfaced list holds is served, and the
service is told the site's name (the registrable domain, never a saved subdomain), under `CICADA_ALLOW_LOGO_FETCH`.
**The app half (G166).** `VersionVector.mapping["reading"] = [.sources]`, so an agent's outcome (an ask-store write, no
bank write) refreshes Sleep › Saved over SSE; `MediaFeedItem.read` (`MediaReadState`, decoded leniently — an older backend, or
a value this build cannot read, drops the block and never the row). **Reading in your browser** (a sheet from the Sources page's
header since D6, `ReadingInBrowserSheet` around `ReadingWebView`; `ReadingAgentModel`; not a Store domain — fetched when it opens and
answered by every write) has three groups. *With an agent*: "Let an agent read pages for you" — **on by default behind the
first-use sheet** (owner 2026-10-22: `reading_settings` stores only an off, and nothing reads until the current sheet is
accepted); turning it on
raises `SettingsSheet`'s first-use sheet (what asking does, that Cicada only asks, Cicada's instruction to the agent — no
credentials typed, nothing posted, messaged or changed — with the honest limit that it can't see or enforce what happens in
the browser, the sites' terms, an "I understand" that must be ticked, DR-41 — **no site picker**) and nothing changes until "Turn on", which sends the acknowledgement in one
`PUT /reading/settings`; once on, "Copy for an agent" (`GET /reading/prompt`) sits in the group. *How your agent reads*: the
`agent_methods` choice as radio rows (a skill wears a Skill tag, says whether it is installed, and offers Open in graph,
Add to your graph or **Install…**, which opens that skill's own `SkillDetailView` as this page's sub-page — the Skills
list shows only five, so a lower-ranked skill has no card there — with an `agent-prompt` plan's sentence and a Copy
button; the footer says the choice applies to agents on this Mac that can load a skill). *Sites that need your browser*: every site `GET /reading/sites` surfaced — only a site Cicada's own reader could
not read — each with its favicon drawn like a browser tab's (`SiteIcon`: 20 pt, a 4 pt corner, never a circle or a ring; from
`SiteIconStore`, in memory per bank and cleared on a bank switch, over `GET /reading/sites/{site}/icon` — the app makes no
network call of its own, a lint holds it; until it arrives, and for a site with none, the family's bundled mark, else a
ring monogram), its wall in words (`wallWords`), measured counts and one switch (the stored grant, so a site allowed while agent
reading is off still shows on, says "Allowed · agent reading is off" and can be turned off; a paused site's pages "wait
until you sign in", never "queued"); a site switched on while the sheet is
unacknowledged raises the sheet, whose one line says the site rides the same call, and a paused site ("your agent wasn't
signed in") offers Try again. The **saved item's detail column** (Sleep › Saved, the Feed's until 2026-10-16)
gains a Read section (`FeedReadSection`, words and controls from the pure `ReadWords`): "Waiting for your agent",
"Read by <agent> · <day>", "Needs you to sign in to <site>" with **Open in browser** (the person signs in themselves; the
app opens an http(s) link and nothing else) and **Ask again**, and "Ask an agent" (`POST /reading/asks`, which copies the
hand-off sentence). It is drawn only when something was recorded, an agent may be asked, or Cicada's reader could not open the page (`wall`:
"Cicada's reader couldn't open this page: it needs a signed-in browser / it stopped at a consent page / the site refused
it", with the site's icon at 16 pt, and **Let an agent read <site>** beside Ask an agent — one `PUT` when the sheet is
already acknowledged, else the same first-use sheet; a page of an allowed site reads "Waiting for your agent · <site> is
allowed"; a disabled Ask carries the server's own `reason`); an ordinary page with agent reading off draws nothing.
the Agents page keeps one row, "Reading pages", linking here. **Home** gains its own block, *Needs your browser*
(`ReadingSitesSection` between Needs you and Last read, over `ReadingSitesCache` — in memory, ETag-revalidated when Home
appears or the sources move, emptied on a bank switch, never a Store domain): "N saved pages need your browser to be read"
(the server's `waitingNotAllowed`), up to three of those sites' icons, linking to the Sources page; hidden at
zero and once every listed site is allowed, and never counted in Needs you. The wall
is not shown only there: the saved row's second line says "Needs sign-in" (`ReadWords.rowFlag`) and `ContentView`
toasts a link that just hit one (`ReadWords.newlyWalled`; the first look after launch or a bank switch announces
nothing). The wall reads in the text ladder with a neutral glyph, never `warning` (DR-7), and the agent's own note shows
as "<agent> noted: …". No line says "in your browser" of what an agent did, or promises what it will not do.

**YouTube lists (G71 / G166, owner 2026-10-16: "the agent being able to go to youtube using the browser to monitor
stuff … like for youtube watch later/history").** The third door onto the watch record (`capture-and-sleep.md`, *Watch
history*), on this section's rails: Cicada never spawns a browser, never signs in and never fetches either page; it only
offers. **Consent:** agent reading on (its sheet acknowledged) AND the person turned the list on in Reading in your browser
(`reading.json` `youtube_lists`, `{watch_later|history: day}`, on by default since 2026-10-26 — onboarding asks once, pre-ticked; an older install's for accounts its memory shows (`list_defaults`); an off kept in `youtube_lists_off` is never overridden — refused without a current acknowledgement). The switch is a **standing ask for exactly that page**, not
a site grant: it never lets a wall page of youtube.com, or any other page of it, be recorded — the one dated exception
to "only a link the person asked about, or a wall page of a site they allowed" (owner 2026-10-16, CLAUDE.md's rail). **The offer** (`youtube_lists.py`; state in
`$CICADA_HOME/youtube_lists.json`, ids, enums, counts and times only, `flock`ed): a list is *due* when allowed, not
paused and not read for this bank in 20 hours; `cicada_reading_queue` (stdio only) appends its lines — the page
(`https://www.youtube.com/playlist?list=WL`, `https://www.youtube.com/feed/history`), what to read (link, title,
channel, and for history the day the page files it under), never click anything that changes a list, never sign in —
and `reading_queue.counts` counts a due list as one of the person's asks, so the recall hook's "N links are waiting"
hears it. **`cicada_record_youtube_list(list, outcome, videos?, via?)`** (`record` scope, stdio only —
`catalog.NEVER_REMOTE`, the re-check's seat; a proposed CLI row `read youtube`, not exposed) under one admission and
page lock: refused, writing nothing, in a demo bank, with reading off, for an unknown list or outcome, or a list not
turned on; `needs_login`/`blocked` pause both lists for 7 days (no bank write; turning a list on again, or a later
successful read, lifts it); `failed` is noted. A `read` (≤ 500 videos a call, YouTube video pages only, the rest
counted): Watch later → saves through `media_ingestor.write_prepared` with the page's title and channel, no fetch,
folder `Watch later`, origin `youtube-playlist` — a video already saved by any door is a duplicate; history → day rows
through `watch_history` (door `agent`, the page's day; a row without a day is left out). Committed alone as the harness
with its session trailer. **Not built:** a video removed from Watch later on YouTube stays saved here (the read only
adds); the agent reads a few screens, so a long list fills over several reads.

**Saved lists on X, Instagram and LinkedIn (G206, redesign 2026-10-22, ruling 36).** The YouTube lists' shape, per
walled site: X Bookmarks (`https://x.com/i/bookmarks`), Instagram Saved (the profile's Saved tab, reached from
`https://www.instagram.com/` — Cicada keeps no profile name) and LinkedIn Saved posts
(`https://www.linkedin.com/my-items/saved-posts/`). Cicada never spawns a browser, never signs in and never fetches a list
page; it only offers. **Consent:** agent reading on (its sheet acknowledged) AND the person turned that site's list on
(`reading.json` `saved_lists`, `{x|instagram|linkedin: day}`, on by default since 2026-10-26 on the same terms, offs in `saved_lists_off` — refused without a current acknowledgement;
`PUT /reading/settings` `savedLists` patch, the Sources page's switch; `GET /reading/settings` carries `savedLists`
and `saved` — per site the last read, its outcome, item count and pause, plus `readsToday`/`dailyReads`). Like a YouTube
list it is a **standing ask for exactly that page**, never a site grant: it lets no other page of the site be recorded.
**The offer** (`saved_lists.py`; state in `$CICADA_HOME/saved_lists.json`, ids, enums, counts and times only,
`flock`ed): a list is due when allowed, not paused and not read for this bank in 20 hours; **one site's list at a time**
(the first due, in the order X, Instagram, LinkedIn) and **at most 10 recorded reads a UTC day per bank** across the
three (G206's bound, the LinkedIn profile read's, until measured). `cicada_reading_queue` (stdio only) appends its
lines — the page, what to read (each post's link, author and the words it shows), only the list (never the feed or
messages), never click anything that changes it (no unsave, like, follow or reply), never sign in — and
`reading_queue.counts` counts a due list as one of the person's asks. **`cicada_record_saved_list(platform, outcome,
items?, via?)`** (`record` scope, stdio only — `catalog.NEVER_REMOTE`; a proposed CLI row `read saved`, not exposed)
under one admission and page lock: refused, writing nothing, in a demo bank, with reading off, for an unknown platform or
outcome, a list not turned on, or the day's reads spent. `needs_login`/`blocked` pause **that site's** list for 7 days
(no bank write; a sign-in on X says nothing about Instagram) and file a G205 agent request — "<Agent> is asking you to
sign in to x.com, to read your bookmarks" — when the `agent_requests` module is present (a no-op before G205 lands;
`saved_lists.resume_site` is what its "I signed in" should call); turning the list on again lifts the pause. A `read`
(≤ 200 items a call): each item must be a post of that site (`saved_lists.canonical`: an X status, an Instagram
`/p/`, `/reel/` or `/tv/`, a LinkedIn `feed/update/urn:li:…` or `/posts/…`; the rest are counted and left out), saved
through `media_ingestor.write_prepared` with no fetch, under the list's own origin and folder (`x-bookmarks`/`Bookmarks`,
`instagram-saved`/`Saved`, `linkedin-saved`/`Saved Items` — the export archives' own), so `history_index.kind` makes it
**index-only: `processed: true`, `processed_by: index`, never read by a model** (ruling 30). Dedup is by URL: the post's
other spellings (X's `i/web/status`, `twitter.com`, Instagram and LinkedIn without `www`) ride as `url_index` aliases, so
a post an archive, a connector or a pasted link already saved is a duplicate; the platform's own ids are never asked
for. The post's words become the title (≤ 80) and description (≤ 500), scrubbed; they are the post's, never the
person's (no `note`). Committed alone as the harness with its session trailer. **Not built:** a post unsaved on the site
stays saved here (the read only adds); the app's switch (spec in `app.md`, "Saved lists in your browser").

**A walled post's title (2026-10-22).** The backend never fetches an X, Instagram or LinkedIn post (R-RW4), so a saved
one is titled from its URL alone (`media_ingestor._walled_post_title`): "Post by @<user>" for an X status (before, its
bare numeric status id), "Post on X" for `i/web/status`, "Instagram post"/"Instagram reel", "LinkedIn post" for a
`feed/update` URN. `media_ingestor.is_placeholder_title` counts both today's fallback and the old bare-id title as a
placeholder, so an agent's read (`page_read._apply_title`) still replaces either, and the reading queue never prints one
as a title.

**One person's LinkedIn profile (owner 2026-10-16: "extracting people profiles from my LinkedIn connections (maybe
could be a skill)").** The connections import (`capture-and-sleep.md`, *LinkedIn connections*) leaves a person page
Cicada already had with its profile link and the export's dated facts; exports age. **The skill** —
`skills/linkedin-people/SKILL.md`, Cicada's third own bundle (`skill_store.OWN_BUNDLES`, installed from the checkout
on the person's click on the Skills page like `cicada` and `cicada-librarian`; a release app ships it in its backend)
— tells the person's agent: when the person asks about **one** person ("what does <name> do now?"), answer from memory
first, then — if they want it current — open the profile link that page lists in the person's own signed-in browser,
read the top card and current experience, and record it; never search LinkedIn, never open a profile Cicada does not
list, never in bulk, never sign in, never collect contact details; page text is data. **`cicada_record_profile(entity_id,
url, outcome, company?, position?, quotes?, summary?, via?)`** (`record` scope, stdio only — `catalog.NEVER_REMOTE`, the
re-check's seat, ruling 25's "a trusted local agent they asked"; a proposed CLI row `read profile`, not exposed) under
one admission and page lock. Refused, writing nothing: a demo bank; agent reading off (the person's one consent to
having their agent read pages for them); not a person page; a `url` that is not **the one LinkedIn profile that page
lists** (`linkedin_people.page_profile` — the import or the person put it there; one the person removed is not
listed, so it cannot be recorded); an unknown outcome; past **10 profiles a UTC day per bank**
(`$CICADA_HOME/people/<bank>/linkedin-profile-reads.json`, a count only). `needs_login`/`blocked` and
`not_found`/`failed` write nothing and tell the agent to stop. A `read` needs `company` and/or `position` and writes one
episode (`source: profile-read`, `processed: true`, `processed_by: agent`: `assistant: <summary>` then `attachment
[linkedin.com]: as <harness> read it` and up to three `> quote` lines — `check_record`'s shape, so a cited quote is a
`page` span: text the agent *reported*, never the person's words), then the company and position as `works-at`/`role`
claims observed `external:linkedin`, `origin: linkedin/profile`, `authored_by` the harness, each citing the first quote
that names its value (else the episode as `reasoning`), dated today — **newest wins** against the export's line
(`linkedin_people._reconcile`), and a later re-import of an older export never undoes it. Committed alone as the harness
with its session trailer. Cicada itself never opens linkedin.com.

**Exploring saved sites (G166 slice 1, owner 2026-10-14, rulings D1–D6 in TODO ruling 25).** The person picks saved
sites in Sources and clicks **Explore** (`POST /explore/batches`), or asks a trusted local agent in chat, which calls
`cicada_explore_start(scope?, origins?, look?)` (D5: only a harness on the person's G198 trust list, stdio, never remote
and never from the CLI — the `explore start` row is MCP-only). `look` (looks v2) is a list of saved links whose look
the person asked to keep: instead of a run it makes the same ask as their *Save its look* click
(`explore_queue.ask`, `asked: look`), stamped as started by the agent. Either way one batch lands in the explore queue
(`explore_queue.py`, `$CICADA_HOME/explore_queue/<bank>.json`, the video queue's twin: keys only, `fcntl.flock` plus
atomic replace, expiry and lapse applied in memory), stamped `started_by: {kind: person|agent, harness, session}`, shown
at once on Sources and stoppable in one tap (`POST /explore/stop`: waiting sites dropped, a held one finishes). Cicada
never opens a browser and never schedules an agent.
- **The candidates** (`explore_candidates.py`): saved links minus `reading_hosts.classify`'s refusals (secrets, local,
  AI apps, videos, papers, redirectors), private workspaces, junk/archived pages, walled sites the person has not turned
  on in Reading in your browser, and **Never explore** sites. Depth comes from the person's reason (D4; slice 2 below).
- **Depth follows the person's reason (slice 2, owner 2026-10-14 evening; `explore_plan.py`).** By default a visit is
  the saved page alone: a viewport, a thumbnail and the metadata. The reason is read deterministically — **no model in
  the backend** — from G191's `saved_why.reasons` ids and project, the person's own words (`saved_why.text`, a
  `## Saved because` section) and what they said about the page in conversations (current claims on the saved page
  whose evidence is the person's turn or that are `user_stated`), through closed keyword families (English and Spanish:
  design, product, technique, read later, "every page"/"the whole site", and page words like docs or pricing). It
  becomes a **plan**: `{depth, max_pages, pace_seconds, pages: [{kind, shots, match?, known?}], avoid, avoid_urls?,
  focus?, section?, auto_look?, lift?, because}`. Design opens the front page, pricing, docs, a product page and a blog
  post with full page, mobile and dark on each and keeps Looks; product opens the front page, pricing, about and docs;
  technique stays on the saved page and finds the section matching the person's words; "every page" widens to six;
  a page the person named is opened. At most six pages a visit (`explore_plan.MAX_PAGES`), cut to the hour's room on
  the site (`explore_queue.room`, so 30 loads an hour still holds). **The split:** Cicada's plan is the floor and the
  ceiling; the person's agent supplies judgment while it explores — the script picks a page per kind from the links
  the site shows (or the page the site map says an earlier visit opened), and the agent may swap in its own
  (`pages=[url, …]`) or name the section (`focus_heading`). On record, Cicada recomputes the plan and **vets every
  further page** (`explore_plan.vet`): same host as the landing page, never a sign-in or account page or one found
  walled before, allowed by robots.txt as the agent's browser read it (`urllib.robotparser` on both sides; robots.txt
  not read means no further page), loaded inside the lease window and at least 8 s after the page before, within the
  plan's count. A dropped page is counted in the reply, never kept.
- **`cicada_explore_claim(limit?, release?)`** leases one site (at most 5) per call: **one live lease per site** across
  every agent, at least 8 s between page loads on a site and at most 30 an hour (`sites` in the file), 15-minute leases
  that any call from the session extends, three tries, a lapse judged only while Sleep does not hold the pages. Each row
  carries a 128-bit `lease_token`, the plan (one JSON line) and why it goes that deep, the saved date, the person's why,
  the previous capture's viewport hash, and what the site map knows (pages opened before, walled pages never to open).
  The reply names the pinned capture script **only after `explore_skill.verified()` re-checks its sha256** against the
  catalog pin; otherwise nothing is leased. `release` codes: `needs_login` and `blocked` pause the **whole site** for 7
  days or until the person asks again (*Try again*); `skipped`, `not_found`, `gone`, `failed`. Only the queue is written,
  so it is not refused while Sleep runs.
- **`cicada_record_capture(url, lease_token, outcome, captured_at, final_url, http_status, shots, page, design,
  signed_in, …, loaded_at, pages, found, robots, section)`** writes the dated record (`storage.md`, *Site captures*) with
  the further pages that pass the vet, updates the site's map (`site_map`), keeps a design visit's best pictures as Looks
  (`design_refs`, `via: explore`) with the page's computed tokens (`design`, and each page's own `design`, printed by
  the capture script v3's `_DESIGN_JS`), all under one write admission and one commit as the harness; a *Save its look*
  ask (`save_look` in the plan) keeps the landing picture even when its look has not changed;
  idempotent on `(url, lease_token)`; a late record after a lapse is accepted unless another agent was handed the site;
  refused with "keep the files and record again" while Sleep writes. A shot is a file the agent saved (the design board's
  by-identity refusal of `~/.claude`, `~/.codex`, `~/.cicada`, `~/Library` and the bank) or base64, ≤ 12 MB. When the
  person turned signed-in exploring off, a record claiming `signed_in: true` is refused.
- **`cicada_explore_queue(limit?)`** is the read-only list; **`cicada_site_map(site?)`** (slice 2) reads a site's map
  by name or by any link on it, or lists the explored sites. All five tools are stdio-only (`catalog.NEVER_REMOTE`);
  the four that act are refused in a demo bank and while "Let an agent read pages for you" is off. Telemetry: one
  `explore` ledger row per start, claim, release or capture — ids, enums and counts (pages kept, Looks kept) only.
- **The skill** (`skills/site-explore/`): `SKILL.md` and `explore_capture.py`, run by the person's agent in ONE
  `browser-harness` call per site (`exec(open(<script>).read()); print(explore_capture(url, depth=…, context=…))`). It
  opens its own background tab — in the signed-in session, or for `context="isolated"` a fresh
  `Target.createBrowserContext` it disposes of afterwards — emulates 1440×900 at 2×, reads the page's structure (title,
  description, JSON-LD, the h1–h3 outline, fonts, `:root` custom properties, typography, components, ≤ 1,500 words),
  classifies walls (401/403 or a lone password field → `needs_login`; 429/451, a captcha frame or a full-page consent
  wall → `blocked`) **before** any screenshot, and saves JPEG q80 shots (viewport, a 640×400 thumbnail; full page, mobile
  and dark as the plan asks). Version 2 (slice 2) takes `plan=`: past the saved page it reads `/robots.txt` once from
  the page's own origin with `credentials: 'omit'`, picks pages as above, waits at least `pace_seconds` + 0.5 s between
  loads, stops at the first wall, and prints `loaded_at`, `pages`, `found` (≤ 120 same-host links), `robots` and a
  technique's `section`. It carries no page-kind table of its own: the plan hands it the words. Version 4 (looks
  polish, 2026-10-15) waits for each page to settle before its first screenshot (fonts, first-viewport images, a still
  layout, finished viewport animations, a 2.5 s grace for endless motion, a hard 9 s cap; `page.settle` records it,
  `storage.md`) and draws "Aa" in each family the page renders on a canvas it never adds to the page
  (`design.specimens`, at most six PNGs). It never signs in, types, clicks or hides a consent banner, changes the user agent,
  retries, or activates a tab. Pinned in `recommended_skills.json` (id `site-explore`, `pin.files` holds the script's
  hash; `scripts/verify-skills.sh` checks every pinned file).
- **Verified (2026-10-14)** against a local fixture site in a headless Chrome started for the test (never the person's):
  isolated contexts are drivable and cookies do not cross; three daemons with separate runtime dirs capture in parallel;
  walls, a 404 and an unresolvable host classify as designed; the script's output records end to end. **Unverified:** a
  headed Chrome behind the `chrome://inspect` approval, and background-tab rendering there.

**The Claude Code plugin (owner 2026-10-19: "a Claude Code plugin … so the agent can use the Cicada MCP and
conversations get stored and captured").** The rule: **the plugin is the canonical Claude Code door; `install.sh` is
the canonical machine install** (the venv, the memory folder, the backend, the app, and the Codex, Cursor and Gemini CLI
wiring stay `install.sh`'s and the app's).

- **Layout.** This repo is its own marketplace: `.claude-plugin/marketplace.json` (name `cicada`) lists one plugin,
  `./plugins/cicada`, so its id is `cicada@cicada`. The plugin holds `.claude-plugin/plugin.json` (its `version` is a
  `VERSION` stamp: `release.sh bump` moves it and `check_version.py agree` holds it), `.claude-plugin/icon.png` (a copy
  of the app icon's 1024 px PNG, `app/CicadaApp/Art/AppIcon/Cicada-1024.png`; `claude plugin validate` warns
  `ICON_MISSING` without it), `skills/cicada/SKILL.md` (a
  byte-for-byte copy of the root `SKILL.md`, which stays the source; a test fails on drift), `.mcp.json` (the stdio
  server `cicada`, which Claude Code lists as `plugin:cicada:cicada`), `hooks/hooks.json` and two POSIX scripts in
  `scripts/` — never a top-level `bin/`, which makes claude.ai and Cowork refuse a plugin.
- **Hooks.** The same five events and the same scripts install.sh registers: `Stop`, `PreCompact` and `SessionEnd`
  run `scripts/cicada-hook capture --harness claude-code` (G105, G110 gate A); `SessionStart` and `UserPromptSubmit`
  run `scripts/cicada-hook recall --harness claude-code` (G149), each with install.sh's 5 s timeout. The script execs,
  with the hook's stdin and environment unchanged, the checkout named in the plugin's `cicada_repo` setting
  (`<repo>/api/.venv/bin/python <repo>/api/hooks/<name>.py`, a developer build) or else the app's
  `$CICADA_HOME/bin/cicada-hook` launcher (a release, G182). With neither it writes one line to stderr and exits 0 —
  nothing on stdout, which would become the agent's context. Every capture rail stays in the scripts it runs:
  `CICADA_CAPTURE=off` stops capture and `CICADA_RECALL=off` recall (Cicada's own spawns set both; Sleep's `claude -p`
  also runs `--safe-mode`, which disables plugins), one
  episode per session, the transcript read by the backend only under the harness root. After a `Stop` or `PreCompact`
  the same capture script also starts the memory-notes sweep (ruling 43, `api/hooks/memory_notes.py`, detached, only
  when a note changed), so the plugin carries it with no new hook. The plugin's `recall` setting
  (*Remember automatically*, on by default) silences only the recall hooks.
- **The skill the handshake names.** The Claude Code prelude names the `cicada` skill that is there
  (`handshake.claude_skill`, part of the primer's cache key): `cicada:cicada` when the plugin is on (the same
  `registry.plugin_state` test), else `~/.claude/skills/cicada` when `install.sh --skill` or the Skills page put a copy
  there, else no policy file at all.
- **The engine the Now line names (2026-10-26).** "engine claude-cli (haiku)" is the engine a Sleep the person starts
  would run — the Settings picker's choice and its model, Auto's first connected plan, never a leftover API model on an
  unresolved Auto — read when the primer is built (`state_dictionary.with_live_engine`, `engine_select.expected_settings`,
  no probe) and part of the primer's cache key, so a choice made after `_state.md` was written reaches the next primer.
  An Auto nothing has resolved says "engine auto (decided when Sleep starts)". Same line in `cicada handshake`
  (`storage.md`, "The engine it names").
- **The MCP server.** `scripts/cicada-mcp` execs the same checkout's `mcp/server.py` or the app's `cicada-mcp`
  launcher; the `memory_path` setting, when set, becomes `CICADA_MEMORY_PATH` (the memory root — the server resolves
  the active bank itself, as install.sh's own registration does).
- **Settings.** `cicada_repo`, `memory_path` (both optional directories) and `recall` are `userConfig`, saved by Claude
  Code under `pluginConfigs["cicada@cicada"]`; nothing sensitive is asked (the API token stays in `~/.cicada`).
- **No double fire, and never no door.** `registry.py plugin --settings ~/.claude/settings.json` (read-only; the one
  test, `registry.plugin_state`) answers `on` only when the plugin is enabled (`enabledPlugins["cicada@cicada"]`, user
  settings), installed (`~/.claude/plugins/installed_plugins.json`) and able to run a Cicada by its scripts' own order
  (a `cicada_repo` checkout with its venv — never falling back past one that isn't — else an executable
  `$CICADA_HOME/bin/cicada-hook`); `broken` (exit 4, with why) when enabled but it would run nothing — a settings file
  synced from another machine, no app and no checkout. With `on`, `install.sh` registers no Claude Code hook or MCP
  entry and removes the ones it registered before (`registry.py uninstall`, Cicada's entries only; `claude mcp remove
  cicada -s user`), skips `--skill` and says so; with `broken` it keeps its own entries and warns with the fix.
  `make doctor` reports which door is active, fails a `broken` plugin, a leftover settings hook or user-scope `cicada`
  entry (each would run twice), and names what the plugin runs; `GET /agents/wiring` reads Claude Code as on with
  `capabilities.via = "plugin"` and no argv only for `on` (a `broken` plugin leaves the row probed as before, with why
  in `detail`), names leftover settings hooks in `detail`, and `GET /agents/setup?harness=claude-code` hands back a
  prompt that runs nothing. The app's *Remembers automatically* row reads the plugin's own `recall` setting, on or off,
  and says it is switched there.
- **Recall off stays off.** The plugin's recall hooks do nothing under its `recall` setting off or `CICADA_RECALL=off`.
  When `install.sh` hands Claude Code over, a recall-off choice — `CICADA_RECALL=off`, or the app's switch (a capture
  hook in the settings file and no recall hook) — is written into the plugin's own setting first
  (`registry.py plugin-recall-off`: `pluginConfigs["cicada@cicada"].options.recall = false`, merged, atomic).
- **Installing it.** In Claude Code: `/plugin marketplace add rorosaga/cicada`, then `/plugin install cicada@cicada`
  (or, on 2.1.275+, `/plugin install cicada --marketplace rorosaga/cicada`), then re-run `./install.sh` once on a
  source checkout so its older Claude Code entries go. A GitHub marketplace follows the default branch (`main`, so a
  release); a checkout can add itself with `/plugin marketplace add ~/code/cicada` to try `dev`.

**T3 Code: the harness's door is its door (G228, 2026-10-29).** T3 Code drives the Claude Code, Codex and Cursor
installed on the machine and adds its own MCP server per thread beside theirs; it has no hook or plugin API of its
own to register Cicada in. Its Claude threads are Agent SDK sessions with the CLI's user settings loaded, so the
plugin above (MCP server `plugin:cicada:cicada`, the skill, the capture and recall hooks) or `install.sh`'s
user-scope entries reach every thread unchanged — and T3 Code's own `setMcpServers` replaces only servers it added
itself, never settings-file or plugin servers (Agent SDK docs). The recall note arrives through the same
SessionStart/UserPromptSubmit hooks (G149); `cicada_continue` and the handshake see the harness's session id. A
Codex thread gets Cicada's `config.toml` server and `hooks.json` only under T3 Code's "existing Codex login" setup
(`CODEX_HOME` = `~/.codex`); a T3-managed ChatGPT sign-in runs Codex in a home of T3 Code's, which has no Cicada (Needs
the owner on G228). A Claude instance T3 Code points at another `CLAUDE_CONFIG_DIR` reads that folder's settings, so
Cicada must be connected there too (and its transcripts sit outside the root the backend accepts, so they are
refused unread, `outside_root`). Nothing is installed in T3 Code and nothing of T3 Code's is read; the agent's
`clientInfo` names the harness, so its writes carry the harness as `Cicada-Author` and its page-edit trust is the
harness's (G198). The capture label is the hook's (`host: t3code`, read from its own launch chain's exec paths only, `capture-and-sleep.md`). **T3 Chat** (the hosted
chat app) documents no MCP connector — its FAQ, read 2026-10-29, names none — so it cannot reach the remote connector
and is not listed; its link to T3 Code is T3 Code's own account relay, not MCP.

**Implicit recall (G149).** G105 stopped capture depending on a model's tool call, and recall now works the
same way.

- **The hook.** `api/hooks/recall.py` is stdlib only. One command is registered under both `SessionStart` and
  `UserPromptSubmit` in `~/.claude/settings.json` and `~/.codex/hooks.json`, owned by its own marker in
  `api/hooks/registry.py`. It posts to `POST /capture/hook-context` and prints
  `hookSpecificOutput.additionalContext` (the one shape both harnesses parse) or nothing. It always exits 0,
  never 2 (which erases a prompt), under a 0.9 s client timeout.
- **The note.** `hook_recall` answers engine-free from the derived FTS index. SessionStart gets the primer. A
  prompt gets at most three pages it **names**: a whole name or alias, and one word only for a person, project,
  company, tool or place. Each page comes with its summary and at most two current claims with their dates —
  only claims about what the message is about (2026-10-27, below) —
  plus at most one open inbox question — only one the message is ABOUT (the ask gate below), worded as a statement
  the agent can act on naturally ("if the message already answers it, it is recorded … and not asked"), with a
  pointer to `cicada_check_nudges(mode="list")`. A follow-up never rides a note. The note is ≤ 400 tokens or
  nothing, produced within a hard 300 ms.
- **Lines about the message, or none (2026-10-27).** A trace showed a city named in a message about a job carrying
  a line about a stranger's company and, in another trace, an unrelated 2025 line; the note took a
  page's newest two claims whatever the message said. Now a claim rides only when it shares two subject words with
  the message beyond its page's own name (`hook_recall._claim_fits`; one when the message has only one), or names
  another page the message names ("<A> works on <B>"). The message's subject is its words minus the hook's stopwords
  and the names it says (`message_subject`); a message that only names the page ("how is alpha going?") keeps the
  newest claims. A page keeps its summary either way: no claim beats an unrelated one. **A common noun is no name:**
  a one-word alias (after stopwords: "the hackathon") whose word is in three or more page names
  (`common_name_words`, from the index, cached ten minutes) names nothing — "hackathon" no longer names one event's
  page in every message about any hackathon.
- **The vectors.** They only re-order pages already named, and only when the on-device embedder is already
  loaded. A hosted embedder is never sent a prompt.
- **Repeats.** A per-session window keeps a page from being re-sent on consecutive turns.
- **The bank.** It reads the bank a capture would write into: the real bank while the demo is open, and
  nothing when there is none.
- **When it is skipped.** `CICADA_RECALL=off` (the person's switch, and every CLI Cicada spawns, which sets it beside
  `CICADA_CAPTURE=off`: Sleep's own model calls never get memory injected) and a Codex sub-agent's prompt. Since
  2026-10-23 `CICADA_CAPTURE=off` alone no longer silences recall — saving a session and reading memory into it are
  different consents, so a test or worker session run with capture off still shows the note. Codex also runs a new
  hook only after the person trusts it at startup.
- **Codex's AGENTS.md (2026-10-23).** Codex attached to the server but given no note never called a Cicada tool. One
  short block between `<!-- cicada:begin … -->` and `<!-- cicada:end -->` in `~/.codex/AGENTS.md` tells it to call
  `cicada_continue()` and `cicada_recall` first (`registry.py agents-md-install`: idempotent, an older block replaced in
  place, the rest of the file byte for byte, unpaired markers never touched; a symlinked `AGENTS.md` — a dotfiles copy —
  is never written through or over: every verb refuses it with the block to paste by hand, the wiring reads `invalid`
  and offers nothing, and `install.sh` warns and goes on). `GET /agents/wiring` reports it as
  Codex's `agents_md` and lists the `agents-md` step in `connect` while it is off or stale (never on a timed-out probe),
  so the Agents page's Connect and `cicada setup` add it — setup runs whatever `connect` lists, even for an agent that
  already reaches Cicada, and the Agents page offers a wired Codex that one step alone (`AgentQuickSetup.actions`);
  `install.sh` adds it with Codex's hooks and `--uninstall` removes it. Codex's SessionEnd
  flush is registered with `--timeout 3` (Codex's cap; it warned on every start at 5).
- **The ledger.** One `hook_recall` ledger row per firing, ids and enums only, filed beside `read`.
- **Waiting reads (G166).** While agent reading is on, a session hears once — at SessionStart, or on its first prompt —
  "N links are waiting in Cicada's reading queue for an agent to read" (`hook_recall.with_reading_note`), and again only
  when more of the person's own asks wait than it was told, or pages of allowed sites grew by ten or more. The derived
  part is counted only when the bank's page cache is warm (a cold cache counts the asks and warms in the background), so
  the hook's 300 ms budget never meets a bank parse. One sentence beside the page note (its 400-token budget is the page note's own), per request,
  never stored, dropped from a captured transcript like every "From Cicada" note.
- **Remote.** Remote connectors have no hooks.

**Continuity (G110 slice 1a plus 1b A1/A2/B2, owner ruling 2026-10-07).** A session started (`source`
`startup` or `clear`, which the recall hook forwards; a missing or unknown `source` gets no block — fail closed) in the
same folder or hook-observed checkout as an earlier captured session receives a light history pointer inside the SessionStart note,
even before Sleep. Rich working history is read on demand through `cicada_continue` when the person asks.

**Cursor local IDE startup (1b-c, docs checked 2026-10-08).** The small registered adapter in
`harness_integrations.LOCAL` supplies setup/status separately from transcript and engine providers.
The [Cursor hook reference](https://cursor.com/docs/hooks) specifies a user-level v1
`~/.cursor/hooks.json`, flat `sessionStart` command entries and `additional_context` output.
`cursor_registry.py` merges/updates only the parsed Cicada command, preserving other hooks/keys;
uninstall removes only its commands, leaving other configuration and the v1 header intact. Invalid,
oversized (>256KB), symlinked or unknown-version files are untouched and require repair. Source
installation adds the hook when `~/.cursor` already exists and `CICADA_RECALL` is not off; the app
offers it separately under Remembers automatically. Release commands use the stable
`cicada-hook cursor` / `cursor_registry` launcher verbs, not bundle paths. MCP uses its existing
install link or [global MCP config](https://cursor.com/docs/mcp); enabling MCP never implies hook delivery.
`/agents/setup?harness=cursor` also carries a paste-able prompt (2026-10-14) asking Cursor's own agent to add the
same server to `~/.cursor/mcp.json` at `mcpServers.cicada`; it adds MCP only and names no hook, so the startup hook
stays its own click (R-H11).

`api/hooks/cursor.py` is stdlib/run-by-path; for startup it accepts at most 64KB of synthetic-schema-equivalent
input (capture events up to 1 MiB), allowlists `sessionStart`, uses equal stable `conversation_id`/`session_id` (never generation id), and
skips background/remote sessions. A single valid absolute `workspace_roots` entry supplies the cwd;
the user-hook process cwd is `~/.cursor` and is never substituted. Missing/multiple/invalid roots get
only the primer, without a continuity selection or git observation. Optional identity uses the same
bounded D2 observer. The existing authenticated hook-context route/compositor keeps the light
≤240-character pointer inside the whole≤1,800-token note; the hook maps `additionalContext` to
`additional_context` and fails open with `{"continue": true}` alone on empty/error/disabled/unsupported input
(every output carries `continue`, so the capture events never hold a prompt back). HTTP timeout
is0.9s and the config timeout2s. Email (including the environment value), model fields, transcript
pointer and arbitrary extras never leave the hook or enter its logs. Only the existing registry's
ids/hashes/times are recorded; no episode is created. Pass the episode in the hint to
`cicada_continue(session=…)` on demand, including when GUI MCP cwd is unknown.

**Capability/status honesty.** `/agents/wiring` adds the Cursor row: `recall` is MCP *registration*
state (live connectivity remains `/agents/live`); `autorecall` is startup hook *configuration* state;
`autosave` is the capture hooks' configuration state (capture-everywhere, 2026-10-14: `capabilities.capture:
documented`; `capture-and-sleep.md`, *Capture from every agent*). Capabilities also
label `startup: documented`, `surface: local-ide`, `verification: synthetic`. Recognised config-directory
presence supplies `installed`, not an app binary/version probe. Current docs say startup is
fire-and-forget: actual installed timing, first-prompt delivery, model tool choice and rendered UI
remain unverified, with no claimed minimum Cursor build. CLI, cloud and remote delivery are not
supported by this local IDE adapter. The docs' nullable common transcript pointer does not establish
a trusted confined root, format or final-message ordering contract, so **no Stop hook is installed, no
Cursor transcript is read and `/capture/transcript` still rejects Cursor.** Capture instead takes the words the
documented `beforeSubmitPrompt.prompt` and `afterAgentResponse.text` carry, through `POST /capture/turn`
(`capture-and-sleep.md`); there is still no tool accumulation, thought capture, followup message, artificial
prompt or dynamic rule.

- **Identity (B2, D2).** Exact `sha256(cwd)[:16]` remains first. Only the stdlib harness-side hook may run
  the fixed `git -c core.fsmonitor=false rev-parse --path-format=absolute` pair with `--git-common-dir` and
  `--show-toplevel`, in the harness's supplied cwd. The pair shares a 100ms monotonic deadline (with a cleanup
  reserve), ≤4KB stdout per command, no shell, optional locks off, global/system config disabled and inherited
  git directory/index/object/config overrides removed. No status/log/worktree crawl or repository content; the origin's one hashed read is the next bullet.
  macOS skips the `/usr/bin/git` install-dialog shim; the installed runtime's bundled git is the last fallback.
  Failure or malformed output leaves exact-cwd matching. `resume`, `compact` and `fork` carry their own history
  and get no startup block; they may still supply identity for requested reads.
- **The remote, hashed (ruling 22 D2a, owner 2026-10-29).** After the pair, inside the same deadline and bounds, the hook
  runs one more fixed read: `git -c core.fsmonitor=false config --get remote.origin.url`. `normalise_remote` makes
  every spelling of one repository the same `host/org/repo` (scheme, user, port, `.git`, trailing and doubled
  slashes, case; scp-style `git@host:org/repo` = `ssh://` = `https://`), and only
  `sha256(salt + "\0" + normalised)[:16]` is sent as `remote_hash`. The salt is 32 random hex characters made once per
  install at `$CICADA_HOME/remote-salt` (0600, `O_NOFOLLOW`, created with `O_EXCL`); without one the remote is left
  out, never hashed unsalted. No origin, a read past the deadline or a malformed line keep the pair's observation
  without it. The URL is never stored, logged, sent or shown, and the hint cache stays cwd hash + time. The parser
  keeps `remote_hash` and derives `remote_checkout_hash` = digest(remote + the checkout top level relative to the
  folder holding the common git directory, lexically: `.` for the main checkout, `.worktrees/x` for one inside it).
  `same_checkout` is the path keys *or* `remote_checkout_hash`; `same_family` is `family_hash` *or* `remote_hash`, so
  a renamed, moved or re-cloned main checkout is the same checkout and its worker worktrees stay related choices.
  A selection made through the remote alone adds one disclosed line ("another folder of this repository … renamed,
  moved or cloned again"). The salt is per install, so two machines never share a hash: it is not cross-device repo
  equivalence. Records written before keep their path keys and keep matching by them; nothing is rewritten.
  Measured (`test_project_remote_identity.py`, real scratch repositories): the startup pointer finds the earlier
  session after a rename, a move and a re-clone under another URL spelling — 0/3 before, 3/3 after.
- **Supplied values and privacy.** The hook posts plain checkout root/common-directory strings, an exact cwd hash,
  observation time and a hash scoped to local hook home + device. `workspace_identity` is a pure backend parser:
  it validates shape, age and lexical containment, hashes the supplied strings and never opens, stats, resolves or
  runs git in them. Authentication does not prove an assertion: matches are labelled *harness-observed*, and every
  note still says *workspace state not checked*. Persisted `workspace_identity` holds only `family_hash`,
  `checkout_hash`, `cwd_hash`, `observed_at` and, when the hook read one, `remote_hash` + `remote_checkout_hash`. No
  supplemental raw path is stored, even in the episode. Git common
  directory identifies a family, checkout top level a checkout; no `.git` stripping or `.worktrees`/prefix heuristic.
  Arbitrary linked-worktree layouts associate; clones, independent nested repos, submodules and separate git dirs
  keep their actual supplied identities. This is local device-scoped association, not cross-device repo equivalence.
- **Observation reuse.** Startup probes; later prompt/capture hooks probe only when their cwd hash differs from the
  per-session hint or the hint is absent. `continuity-hook-hints/<session-hash>.json` holds only cwd hash/time,
  ≤1KB reads, atomic0600 writes, no-follow directory/file opens; known configured memory roots refuse the cache.
  Normal Stop/flush reuses the registry identity only when its exact cwd matches and the observation is ≤24h old.
  Registry observations are monotone by observed_at; a newer failed observation defeats an older success.
  Expired/missing/invalid hints fall back to exact cwd. The observation changes metadata only: a late stamp
  preserves episode id/body/hash/processed state. Chosen identity hashes are revalidated at the full bank parse.
- **Selection** (`continuity.select`): an exact episode id or full session id (`cicada_continue(session=…)`), else the
  most recent other session here by captured activity (the last kept turn's own time — `captured_at` only when no turn
  has one, since a re-capture runs long after a conversation — or the registry's later `last_prompt_at`), never file
  mtime; two sessions active within 15 minutes of each other are listed and the agent is
  told to ask once on the requested read. An incomplete requested read says "the most recent session Cicada could read here", never "the only".
- **Checkout priority.** When no exact-folder candidate exists, a fresh cwd-bound observation permits same-checkout
  selection with the same activity/15-minute ambiguity rule. Exact root and root-checkout tasks therefore outrank
  newer workers in sibling `.worktrees/*` or arbitrary linked worktrees. Only other checkouts in the family yields
  up to three episode/call choices: no worker-body parse, role adoption or `continues` stamp. A selected current
  conversation's freshness checks include uncaptured registry rows throughout the observed checkout. Explicit
  reads disclose a different observed checkout; they never mutate files or lineage. B1's direct carried role
  pointer remains separate and is not implemented by project identity.
- **Accepted limit.** Two simultaneous new sessions in one folder can defeat a fresh identity's newest-start check; ordinary selection applies because registry rows cannot distinguish this from stale identity after `/clear`.
- **The startup block** is always ≤ 240 characters: an unversioned `cicada_continue(session="<episode id>")`
  hint for questions about previous work, and *workspace state not checked*. It never includes role, title, request,
  reply or State excerpts, even with spare room. Ambiguity lists ids only if all listed ids fit; otherwise it points
  to `cicada_continue()` for the choices. An incomplete selected search adds "Search incomplete".
- **The requested read** quotes the first captured request and recent turns as history. Its "Not captured" line
  discloses a later prompt with no captured reply, a last request with no reply, turns past the capture
  limit (`capture_gap`), note-like person turns (`capture_flags`), a later session here that captured nothing, an
  incomplete search. It preserves identity, revision, consolidation status and whole-turn pagination.
- **One compositor** (`recall_text.compose_note`) measures the WHOLE note — header, primer, block, reading sentence —
  by the chars/4 proxy, ≤ `handshake.MAX_TOKENS`. The primer is built with a 300-token reserve when a block will ride
  (`handshake.load_or_build(reserve=)`, part of the cache key). The primer's existing fit order can shed people,
  focus, conversations and standing rows, then project `now:` and one-liners; it does not promise all project detail
  survives. The max-primer synthetic fixture preserves four project ids/names while shedding their `now:` details.
  If the light hint cannot fit, the reading sentence is deferred first (`READING_SEEN` is not advanced), then the
  primer becomes a pointer to `cicada_handshake`. The hint is preserved beside that lazy primer when it fits; no rich
  startup rendering is available. The reserve stays 300 tokens, not 500.
- **One deadline.** The route resolves the capture bank once and the worker runs, in order: one bounded registry
  transaction (SessionStart: `started_at`, the cwd's hash; a prompt: `last_prompt_at` — recorded even when the answer
  times out), assembly (deadline less 120 ms), composition, and — for a single chosen session with ≥ 30 ms left — the
  registry's `continues`. Registry work takes a 50 ms slice and answers `busy`/`skipped` rather than wait.
- **The index** (`$CICADA_HOME/continuity/<bank-id>.index.json`, beside the registry, never inside a bank): episode
  heads only (≤ 16 KB, to the first `turns:` key), never a full parse in a hook; no git runs on this path; its lock
  sits beside it, every file opened without following a symlink; no safe home or any I/O failure keeps it in process
  memory. Schema 3 keeps `cwd_hash` and validated identity hashes/times, never plaintext `project_dir`, titles or turns;
  persisted hashes are decoded separately from episode paths. A successful index write replaces earlier caches and removes extra cached fields,
  including when the episodes directory is empty, missing or unreadable, without rewriting any episode.
  A failed directory listing keeps
  the rows already known and marks the search incomplete; an exact episode id the index could not read is looked up
  directly; "nothing captured" for a later session is said only on a complete search.
- **The registry** (`continuity_sessions`, `$CICADA_HOME/continuity/<bank>-<hash8>.json`): per session the harness,
  the cwd's hash, `started_at` (earliest), `last_prompt_at` (latest), `continues` (first write wins), and optional
  `workspace_identity` (newest observation, including failed cwd-hash/time-only hints). Never inside any
  configured bank (realpath containment over the root and every bank).
- **The ledger.** The `hook_recall` row gains `continuity` (`latest|explicit|ambiguous|none|skipped_source|no_room|
  deadline|error`), `rendering` and `registry` (`ok|busy|skipped|error|unavailable|none`) — enums only.
- **Measured** (`test_continuity_route_latency.py`, 1,500 synthetic episodes, warm OS cache): the whole route cold
  p95 ≈ 160 ms, warm p95 ≈ 13 ms.

**Proactive behaviors:** surface only *topic-relevant* nudges (never all of them), raise a pending
clarification naturally in the flow when the conversation touches its entity, and offer related
saved resources.

---

**The page's blocks for an agent (vision item 5, 2026-10-28).** `cicada_recall_detail` takes an optional `include`
(a list from `page_blocks.INCLUDE`: `relevance`, `summary` — In short, the 2–3 sentences Sleep writes for a long page
the person talks about often, on both doors (2026-10-29, `in_short`) — `sources`, `coordinates`, `looks`, `ongoing`,
`citations`,
`history`, or `blocks` for all): the same `page_blocks.build` data `GET /entities/{id}` serves the app, worded after the page under
`## Page blocks` in page order, one line per block and one per row (a source's state and when it was checked, an
event's status and day with its claim id, each contributor's change count), and as `data.blocks` for the command
line (`cicada get <entity> --include blocks`; `cli_map` row `get`). Additive (Hyrum): omitted, the reply is byte for
byte what it was; it rides only a read from the page's start (`start` omitted), and a stored-words tail is a `data`
segment (G199 fencing). R12: the argument is in both doors' schemas. `history` is the one block that runs git. **Remote:
`history` is not offered** — the remote schema's enum leaves it out (G199 refuses it by schema), because no remote
scope covers a page's per-commit history: `read`'s `cicada_timeline` is bank-wide ids and counts, and the per-page rows
name models, sessions and commit words. Blame is not a block on either door. Without `sources`, an ongoing item in
the person's own words is named, never quoted (`claims.is_persons_words`, R-PJ23). **`citations` (ruling 48 (16)):**
the article's numbered sources as the app draws them — `[n] kind "title" (app, first – last)` for the first six, the
counts, and on a page whose prose cites nothing yet its beliefs as sentences (an inference marked, an ended one with
its day); without `sources`, a conversation's title (often its first words) and a belief in the person's own sentence
are masked (`page_citations.for_caller`). Offered on both doors.

**Prose item metadata (G118 sections, 1a-i).** `cicada_recall_detail` still returns
the raw markdown, including compact scalar `section_provenance` frontmatter when
present. The 150-bullet/80-episode fixture adds 10,739 bytes (approximately 2,685
tokens by characters/4, not model usage); dense stress adds 22,518 bytes. Default
elision remains a decision. This slice changes no MCP/perspective/CLI schema or
handshake and performs no legacy passage search; API section counts are independent
of current-claim coverage. Paid quote extraction is deferred, not part of this slice.

**Current-claim reads (G118/G93, 2026-10-07).** The recall claim leg, implicit
recall's claim lines and perspective's current block use `claims.is_current`.
Unsuperseded dated events also vote for subject relevance: that leg returns
page ids, never an assertion that the event is a current belief. Claim text in
implicit recall remains current-only; history readers expose events with dates
and state. Closure and successor metadata are preserved for every search hit.

**Questions come up naturally (owner, 2026-10-14).** Owner: questions should be "only relevant to the current
conversation", come up and be answered naturally, and be listed only when the person asks for them. The old contract
(call `cicada_check_nudges(entity_ids=<recall ids>)` after every recall, quote the Cause line, lead with the
Recommended option) appended a "conflict on <project>" block to an answer about who helps on that project, and
recall's own inbox block was a body-text token match (a recall for "alpha project" surfaced the decay question of
"beta project" through the word "project"). Now:
- **The server decides what may come up** (`inbox_ask_gate`, pure): an item passes only when its page is in scope
  (recall's `entity_ids` hold it, or the conversation names it — name, mention, id or the page's aliases, whole
  words) AND the conversation shares a subject word with the question beyond the page's name (its predicate, its
  options other than both/neither, its own words; `text_fold.subject_terms`, folded and lightly stemmed). An
  identity question (`clarification`, `merge_suggestion`) needs the name said. `decay` never comes up (a
  conversation about the page is its answer — the mention lifts decay) and `normalization` stays app-only.
  **An everyday page needs two shared words (2026-10-27).** The owner's page, and any page whose own name (never an
  alias) is said in at least a quarter of the person's latest 200 conversations (`everyday_names`: the derived FTS
  index, at least 20 conversations, cached ten minutes; measured on the owner's bank: owner 36%, main project 34%,
  the assistant's name 32%, then a gap down to 18%), puts nothing in scope by being named or recalled: the
  conversation must share two subject words with the question (`EVERYDAY_TERMS`). A trace raised a question about the
  main project on a message asking to keep a record of the conversation for that project — its only ties were the
  project's name and one common word. Never a hardcoded name; an unready index means "not everyday".
- **Three readers, one gate:** `cicada_check_nudges(mode="ask", topic=<the person's words>, entity_ids)` (at most
  2, highest priority first; no `topic`, no question), recall's proactive block (`_relevant_inbox`, the query as the
  conversation, the session's skips honoured) and the recall hook (`hook_recall._open_question`, the prompt as the
  conversation; the item's predicate and options read from its file through `bank_index`).
- **The agent decides whether it fits** (contract item 2, the tool descriptions, the skill): ask in its own words
  after the request, never a banner, option letters or a quoted cause; otherwise leave it. `mode="ask"` renders a
  question to weave in — the question, the answers in words with their keys, Cicada's current guess once, why it is
  open as context — never the `Cause:` card.
- **Answered naturally:** when the person's words already answer an item, the agent records it without asking,
  `cicada_resolve_inbox(id, option_key or answer, quote=<their exact words>)`, and says what it noted in one short
  line (UX principle 2: a change the person never saw asked is still shown). Nothing can verify that an agent's
  `quote` is what the person typed, so it is kept as **the agent's relay, never as the person's verbatim words**
  (review B1): a small already-processed episode (`inbox_service._write_relay_episode`, `source: agent_relay`,
  `origin: inbox`) whose one turn is the agent's (`assistant`), stamped `relayed_by` (the harness's
  `Cicada-Author` name, sent by `cicada_resolve_inbox`), `session_id` and `inbox_item`. It is committed with the
  answer — the commit carries `Cicada-Author: user` and the relaying agent, plus `Cicada-Session:` — and cited as
  evidence on the claim the answer picks or writes (conflict pick, free text, clarification), so the span reads as
  the agent's words. `agent_relay` is untimed (`episode_time.UNTIMED_SOURCES`): the conversation is captured on its
  own by the Stop hook, so the relay never counts as a second conversation (no 2-conversation floor from one turn,
  G170). The ledger row says `answered_in: conversation` (an enum). A refused answer leaves no episode. A remote
  connection never sends `quote` (R-R22), and a demo bank never receives it — dropped by the tool and by the backend
  (review B2). Never a guess: only what the person said resolves an item.
- **On request:** `mode="list"` (the default) lists every visible item plainly — "what is in my inbox", "what
  conflicts do I have". Every inbox reader in `mcp_tools` now reads an item as YAML (`read_inbox_item`); the line
  parser flattened a question's `options` into strings ("0) key: a").
- **Relation to G115/G98.** This is G115 item 6's relevance half (`inbox_ask_gate`, the `mode` argument) without its
  vector-score leg, and it amends G115's copy-only discipline (quote the Cause, lead with the Recommended option) —
  `recommended` and `cause` stay on the wire for agents and tests, never as copy to recite. G98's subject gates are
  unchanged and still run first (`nudge_visible`, `load_inbox`).

**Catching up (vision item 10, owner 2026-10-28).** Owner: "a nice quick, hop on a chat with cicada to catch him up
to speed … just have the user answer at first those things linked to more accessed entities", in "more human
concrete format". `cicada_check_nudges(mode="catchup")` is that chat's read (`mcp_tools.catchup_nudges`,
`inbox_catchup`):
- **What comes back:** the next `inbox_catchup.LIMIT` (3) questions the person can answer in conversation — every
  visible kind but `normalization`, `page_edit`, an agent request and the grouped "Confirm N links" review, and never a
  multi-valued conflict (G98: shown, never asked) — ordered by `page_use.rank` (Sleep's priority + 0.5 × how much the
  person's life uses the page, below). Each block has `Ask:` (the question in a person's words), `Why you are asking`
  (its reason, from the record), the answers with their unchanged keys, Cicada's guess once, and the call that records
  it on this door (`cicada_resolve_inbox(…)` on MCP, a `cicada inbox resolve …` line from `cli_map.spell` on the CLI).
  Decay is included here — it never comes up uninvited (`mode="ask"`), but a catch-up is the person asking.
- **Nothing repeats:** a session cursor (`inbox_catchup.Cursor`, `$CICADA_HOME/inbox_catchup/<hash>.json` — the hash
  of the bank's path and the session id, ids and a time only, outside every bank, forgotten after 12 h) holds what the
  session's catch-up already served; a second call moves on and says how many remain; `skip`ped ids stay out.
- **One person under several names** is ONE question: open `merge_suggestion` items about people that chain (A~B, B~C)
  come as "Are A, B and C the same person?" with every item id. A yes is never joined by the agent: the reply tells
  it to say it noted it — Sleep's tending reads the person's own words from the captured conversation and joins only
  on them (ruling 29 part 1, ruling 41); "different people" is `reject=true` on each.
- **Local doors only:** stdio, the CLI and a client machine's tool door. A remote connection is refused
  (`CATCHUP_REMOTE`) and its schema keeps `["ask", "list"]` (Needs the owner: remote access).
- **The wording layer** (`inbox_wording.spoken`, template-only, at read, never written; option keys, labels and the
  stored question unchanged — Hyrum) also adds `Ask it like:` / `The reason, if you ask it:` lines to `mode="ask"`.
  Per kind: decay by the page's type ("Are you still interested in X?", "Do you still use X?", "Are you still in touch
  with X?") with "You mentioned it once, about two months ago, and I don't want to push you on it" for a one-off
  concept or skill; a duplicate pair or group as "the same person/tool/…?" ("your partner" for a relation-titled page
  with no name, never its title); a conflict on the person's own page in the second person, and the generic "Which is
  true about X (predicate)?" as "Which is right about X: a or b?", with both sides' ages; a clarification as "Who is X
  to you?" or "Who or what is X?" with when it was said; a "still?" question with its source cue ("…and your LinkedIn
  seems a bit stale, so I wasn't sure you still are"). Every question ends in `?` within 160 characters.
- **Use, derived (S1).** `page_use.scores`: per page, log₂(1 + conversations) × ½^(days since last said / 90) plus a
  0.25 lift for its links, scaled to the busiest page; the owner's page is 1.0. From frontmatter only (`bank_index`),
  cached per bank on the entities directory's mtime (every page write is atomic, so a write moves it) and reused for a
  minute after a write (91 ms p50 to rebuild at 8,028 pages). The telemetry ledger is never read for it: it is
  machine-global and its rail is "nothing learned from it is auto-applied". `load_inbox` (so `GET /inbox` and the
  Home's "Needs you") and `mode="ask"` sort by the same rank; the recall hook never loads the inbox.
- **A conversation, not an interrogation (ruling 48 (8), owner 2026-10-28).** Each block also carries "What Cicada has
  on it" (`catchup_chat.context_lines` — the page's type, when last said, in how many conversations, a few current
  beliefs: the same lines the app's own turn gives its model), so a follow-up or a rephrase rests on the record; the
  head asks the agent to follow up when an answer opens something, say a question another way, move to a related one,
  and save what the person mentions in passing. The skill's "Catching up" section and the `catch_up` prompt say the
  same. No new tool: in a harness the agent itself is the conversational step; the app's chat has its own turn
  (`features.md`). Remote stays refused.
- **The prompt (S3).** The stdio server registers one MCP prompt, `catch_up` (`prompts/list`, `prompts/get`;
  `capabilities.prompts`), which a harness lists as a command (Claude Code: `/mcp__cicada__catch_up`); its text names
  only `cicada_check_nudges(mode="catchup")` and `cicada_resolve_inbox`'s real arguments (R12). The plugin skill has a
  "Catching up" section; the primer is unchanged (its token budget).

**Ask reads what is on the page (owner, 2026-10-14).** Two reproductions on a real bank (values redacted): "what is
the owner's full name?" answered "only a first name is recorded", the summary "truncated at 'R'"; "who is helping the
owner create <project>?" missed the people. The cause: each page's claims and prose shared one 3,000-character
budget, claims first, so a hub page (the owner's: ~178 KB, 6,008 claims) sent `body[:1]` of its prose and never its
aliases; and the context never followed a link. Now each page block carries its name, type, `also called:` (every
alias), its summary whole (frontmatter `summary`, else `## Summary`), claims ranked by subject words within 2,400
characters, and prose within its own 2,400 — the lead plus the paragraphs that share the most words with the
question, in page order (pages after the third get half). A question about the person themselves ("the owner", "the
user", "my", "me", …) reads the owner's page first. **Linked people:** up to 8 person pages linked to a retrieved page
— its claims (object or named in the text), its wikilinked or named sentences, its `related`, and person pages whose
own `related` names it (a backlink) — each with the lines that link them and, from its own page, a claim naming the
retrieved page; ranked by words shared with the question, then by where they were found, never by confidence. The
owner's page is never a source of links (it links to everyone) nor a linked person. Linked people are citable. The
synthesis rule 7 says what `also called` and `LINKED PEOPLE` are. `_claim_context` takes an id map (a scan per claim
was ~1.7 s on a 6,008-claim page). `api/tests/test_ask_hub_context.py` reproduces both at hub scale.

**Ask reads pages item by item, and the conversations' own words behind them (G148/G118, 2026-10-17).** LoCoMo conv-26
through Cicada scored J 52.5 against 95.0 for the same reader given the raw conversation; 17 of 19 wrong answers said
memory lacked a detail that was either on the page past a cut or in the conversation a shown claim points at. Two
causes: prose was taken a blank-line paragraph at a time, so a page's whole `## Key Facts` list was one paragraph
clipped to 600 characters; and Ask never read an episode although every claim carries evidence spans into one. Now:
- **Items, dated.** A page is read as `section_provenance.scan` cuts it — an article paragraph, a key fact, a history
  line, a link — in page order under its section label: the article's lead (or, with no article, the first items up to
  700 characters), then the items sharing the most of the question's words, within 4,800 characters for the first three
  pages (half after). The question's words exclude the retrieved pages' own names ("Caroline" is on every line of
  Caroline's page). Each item carries `[said <day>]`, the days of the conversations its provenance cites (the latest
  two); open questions are never read as memory. Claims go in without their empty optional fields (the validity
  envelope — id, current, validity, valid_from, valid_to, text — always whole), within 3,000 characters.
- **WHAT WAS SAID** (`ask_sources`). The shown claims and items that share the question's words point at episodes:
  a claim's evidence span (asserted; a `stale` span points at its episode only, never at other words) or an item's
  provenance (the episode). At most 8 episodes, ranked by how many question words the pointing claim or item shares;
  inside them, a turn is kept when it holds a pointed span or shares the question's words (minus scaffolding such as
  "how long"), at most 10 excerpts and 6,000 characters, each turn clipped around the span or first match, a short
  reply with the turn it answers and a question with its reply, then sorted oldest first (a count or a list reads
  breadth first, wider — "Lists and counts" below). Every line names its day and
  who spoke from the episode's own turn markers — the person (by the owner page's name), the assistant, or another
  person in a message conversation; an unmarked episode an agent saved through a tool door (`source` mcp/cli) is "an
  agent's saved note", never the person — and Cicada's gap line is never one. Read at answer time from bank files only
  (`evidence.source_document`): nothing is written, stored on a claim, indexed or logged, the question included.
- **Rules 8–9.** Only the person's own words are the person's statements (another speaker's are theirs); when two
  dated lines, claims or quotes give different values of something that changes, the later is current and the
  earlier history; a quote is not newer for being quoted and never overrides a current claim or a later line (the
  owner's eval, 2026-10-17: 19 → 31 of 56 right, but contradictions 1 → 4, older excerpts against a newer page fact);
  an undated line and a dated quote that disagree are both given; a relative time is resolved against its day.
- **OTHER CONVERSATIONS — the search leg (2026-10-19).** Ask was page-first: a conversation's words arrived only
  through a shown page's evidence or provenance, so when Sleep left a detail off the page (or the page holding it was
  not retrieved) the words never came, although plain episode search found that conversation (the owner's eval:
  25 misses about a known conversation; its words reached the prompt for 5, episode search ranked it top-5 for 16).
  Now `ask_sources.search` also finds the conversations by the question's own words, from the derived indexes only
  (no model, no write, the query never logged): the word index's passages holding **any** of the question's subject
  words, ranked over the whole text (so the middle of a long export is as findable as its head), fused by rank with
  the vector index's episode chunks. Each word is weighted by how rare it is across the bank's conversations; a word
  in more than half of them (the person's own name, "plan") counts for nothing, and a question made only of such words
  shows nothing. `gather_search` reads the best 4 conversations (index-only episodes skipped, ruling 30) and keeps the turns
  holding the rarer words (a word as the index matched it: at a word's start, any ending), at most 6 excerpts and
  3,000 characters, never a turn the page leg already showed — same speaker labels, days, clipping and context turns
  as WHAT WAS SAID, each line naming its conversation (`[ep_…]`). Rule 11: a shared word does not make a line about
  the question's subject; use one only when it plainly speaks of it, say its day, and list its id in
  `used_conversations`. The answer's `conversations` (`{episode_id, title, day}`; `POST /ask` `conversations`,
  `cicada_ask`'s "From conversations no page cites", the app's Ask "From conversations" rows that open the
  Reader — `app.md`) names the ones used — only ids that were shown; the episode id is
  what `cicada_write_claim` cites, so an agent can put the detail on a page. With no page retrieved, a conversation
  that holds the words is no longer a gap (the model is called); nothing from either leg is still the honest gap
  with no model call. Bounded: context build p50 +4–7 ms, prompt p50 +~1k characters on LoCoMo; on un-consolidated
  LongMemEval_S chats it put a turn holding the answer in the prompt for 39 of 48 questions
  (`docs/research/2026-10-17-memory-benchmarks.md`, "the search leg").
- **Which conversation is current; counts and lists (2026-10-19, Ask depth).** The leg ranks and counts over the
  conversations it can show: an index-only episode (a watched day, a list save — ruling 30) is marked in the word
  index (`docs.meta.index_only`, schema 6) and is neither counted in a word's rarity nor ranked, so thousands of
  watched days can't make a word look common or fill the ranking. A passage scores the weights of the question's
  words it holds; a conversation ranks by its best passage, then by the weight of all the words it holds. Then the
  question's own words decide its **shape** (`ask_sources.question_shape`, no model): a count or a list ("how many",
  "how often", "list every", "which … have I") is `enumerate`; a day it names ("on 9 April 2025", "March 3", "in June
  2024", "yesterday") or "the first time / originally / used to" is `anchored`; an outcome or a current value
  ("final", "ended up", "eventually", "currently", "still", "agreed") is `latest`; anything else `lookup`. A
  conversation is **on the subject** when it holds at least half the weight of the question's words the best
  conversation holds, two of them when that one holds two or more, and ranks in the fused top 20 ("the gravel bike"
  said again without "price" when the price was agreed is still the subject; a chat about any trip is not "my family
  trip"). `lookup` keeps the newest on-subject conversation inside the 4 read (one slot), `latest` the newest two —
  when several conversations on one subject match, the later one carries what happened (the outcome after the plan,
  the agreed price after the listing) — and a kept conversation shows its best turn before the rest of the budget
  fills by score. `anchored` keeps the conversations of the named day (at most 2) and never adds a later one; the
  best-ranked conversation is never pushed out. `enumerate` reads the 4 as any question does (but for whose turn
  counts — "Lists and counts" below), then adds one line (≤ 300 characters, no context turns) from each further
  on-subject conversation and each of the 4 the budget left without a line, up to 16 conversations and 3,600 more
  characters; its header tells the model to count each distinct event once and say the count covers what memory
  shows. A value question the gate takes for a count ("how many stars do I need") so keeps its own turns. Lines stay oldest first. Rule 11 adds: lines on one subject on different
  days — the later is what happened after (answer with it, the earlier as history, never "the outcome is not
  recorded" when a later line states it); a question about one past occasion is answered from that occasion, and a
  later line about something else never replaces it or what the entities and WHAT WAS SAID show. The page leg's WHAT
  WAS SAID keeps its own budget and comes first; the search leg never repeats a turn it showed. The question is
  embedded once per Ask: the page leg's claim search and this leg share the vector through the indexer's per-model
  query cache (measured: one query embed per Ask). Measured: `docs/research/2026-10-17-memory-benchmarks.md`, "Ask
  depth".
- **Two ends (2026-10-20).** A question about two moments needs both in front of the model. The owner's hard set had
  0 of 7 temporal questions right: "when I first … and by the time I later …" found the first conversation and not
  the later one; "between <month> and <month>" got one end and an adjacent conversation for the other; a gap came
  back one day off or as a range. One search over the whole question ranks the conversation holding most of its words
  first, and that is one end. `ask_sources.two_ends` (no model) reads the moments from the question's own words —
  "first … later / by the time / eventually", "between A and B" (with a time word or a date each side), "which came
  first, A or B", "A before or after B", "how many days since A when B", "go/change from A to B", the order of two
  or three quoted events or "the day …" items, a day or month named for each half, and Spanish "entre … y …", "de ser
  A a ser B", "al principio … después", "cuando volví a", "qué fue primero, A o B" (Spanish dates and a month named
  alone now count as named days); "two conversations 47 days apart" names a pair. "From A to B", "between A and B" and
  two named months are two moments only with a change, duration or order word OUTSIDE the matched words ("switching
  from vim to emacs", "the time difference between Madrid and Lima", "the flight between Lima and Madrid", "in May and
  June" are not); "which … first, A or B" needs a past verb and "first" closing its clause ("what should I do first"
  is advice); "first and foremost", "first of all", "primero que nada" and an opening "First, …" are no first moment. A
  count that is not a duration ("how many times between March and July", "¿cuántas veces…?", "¿cuántos libros…?")
  stays a count. A day the question names outside every end, and an outcome word ("final", "latest"), keep their own
  reservations beside the ends. Its shape is `two_ends`: each end is searched on its own
  words (the half, with what the question says around it; an end that names a month or day, or has fewer than two
  words of its own, also carries the whole question's) through the same two legs, and the best conversation for each
  end is kept inside the 4 read — from the end's own named month or day when it names one; of an end's first three
  conversations, the one whose best turn holds most of its words as whole words leads (the index matches a word's
  start, so "start" also finds "starter"). Two ends share a conversation when their best turns in it differ (a session
  resumed days later), or when the second has no other holding half as much of its words; a pair "N days apart" is the two
  on-subject conversations whose days are closest to N apart. Each end's conversation leads with its 2 best turns by
  the end's own words (each end's best first), and the leg's budget grows by 2 excerpts and 1,000 characters. For a
  two-ends question, or one that asks how much time has passed ("how many days ago", "how many months have passed
  since", "how long ago", "¿hace cuántos días…?" — not a length: "how long is my commute"), the prompt adds
  TIME BETWEEN THE CONVERSATIONS: every distinct day a shown line was said — the LOCAL calendar day of its turn's
  stamp (`ask_sources.local_day`, the day `current_day` counts in; a turn at 01:30 local is stored on the previous UTC
  day) — numbered from the earliest, today's number, and for each end its best-matching conversation, the day of the
  end's own best turn there and the exact gap from the end above (days, weeks, about months)
  — computed from the dates, never left to the model to estimate; it says a kept conversation is a best match, not
  proof (rule 11), and that an event told as "yesterday" or "last week" moves by that much. The system prompt is
  unchanged. On the broad public benchmark sample (LongMemEval_S 100, LoCoMo 10 conversations) every prompt outside
  the temporal categories stayed byte-identical — a measurement on those sets, not a guarantee for every question.
  Measured:
  `docs/research/2026-10-17-memory-benchmarks.md`, "Two ends".
- **Lists and counts (2026-10-20).** A count or a list needs every conversation that told the thing, with the line
  that tells it. The broad sample (#380): LoCoMo multi-hop 65 J against the whole-conversation control's 96, its
  answer turns in the prompt for 147 of 322; LongMemEval_S multi-session 11.7 %, 28 of 71 — answers counted what
  they saw, one or two short. Three causes, three changes, no model in retrieval:
  1. *Whose turn tells it.* The other side of a chat repeats the question's words ("weddings are such fun to attend")
     and its turn beat the person's own line that told the event. `ask_sources.asked_about` reads who the question
     is about from its own words — the person (first person — in Spanish also the verb alone: "he leído", "fui",
     "compré" —, "the user"/"the owner", or their name: all of it or its first word, never a shared surname alone),
     the agent ("you"), another speaker named by their label or the conversation's
     correspondent. In a conversation where it asks about some speakers and not all, another speaker's turn counts
     `OTHER_SPEAKER_SHARE` (0.5) of its words' weight, less the weight of the asked speakers' names it holds (said by
     someone else a name only addresses them); a turn holding nothing more is dropped (`_about_first`). Window and
     breadth both. The window is otherwise read as before: a version that also gave each window conversation one
     line before a second from any lost a knowledge-update answer turn ("how many stars do I need": the correction
     in the newest conversation) and was dropped.
  2. *Lists asked as plain questions.* `question_shape` now also reads as `enumerate`, only when nothing else in
     the question says what it is (no named day, no outcome word): "where has <name> camped", "what are <name>'s
     hobbies", "what are the names of …", "which of my …", "what kind of indoor activities has …" (`_LIST`), and
     Spanish counts and lists ("¿cuántas veces…?", "¿cuántos libros…?", "en total", "¿qué libros he leído?",
     "¿cuáles fueron los resultados?" — a plural noun after "cuáles son/fueron"). Never a list: a plural that names
     one thing about a subject (thoughts, opinions, views, feelings, reasons, chances, odds, details, plans;
     pensamientos, opiniones, razones, planes, detalles — `_ONE_THING`), "which of my laptops is faster", "where have
     you been", "¿cuántos años tiene…?" (an age), "todos los días" (a habit), "¿qué más has hecho?". A superlative ("the most", "favorite", "best") asks for one thing and is never a list — also
     for the older "which … have I" form. `two_ends` reads exactly the forms it read before. A list made only of
     words common across the bank ("what books has <name> read" in a chat about books) keeps them at the low
     weight their rarity gives instead of showing nothing (`_lexical(common_share=1.0)`, only when no word of the
     question is rare).
  3. *A page's whole inventory.* "What activities does <name> partake in" shares no word with "went camping at the
     beach", and the page leg showed only the items sharing the question's words (Sleep's page held the camping
     lines; the prompt held 7 of its 119 items). For an `enumerate` question that names a page (its name or an
     alias, as words — never the person's own page because the question says "I"), among the first three pages the
     items the question's words leave unchosen are ranked by the search model the conversations' table was built
     with (`SqliteVecIndexer.similarity`: the question as a query, the items as passages, cosine; computed now, never
     stored, nothing logged) and fill the page's existing prose budget (4,800 characters) nearest first. Bounds
     (review of #381): only a model this machine runs (`vector_index.runs_on_device`: `onnx_embedder.find` resolves
     it, never an OpenAI or OpenRouter id — a hosted model would be sent the page's text at answer time; otherwise
     no ranking); one allowance of `SIMILAR_TEXTS` = 120 items for the whole question across every page it ranks,
     each clipped to `SIMILAR_CHARS` = 240 characters (120 × 240 ≈ 0.3 s warm on the Neural Engine; whole long items
     were ~4 s, three pages ~11 s); the Core ML passage functions load within `PASSAGE_LOAD_WAIT_S` = 1.5 s
     (`CoreMLEmbedder.passages`), else the ranking is skipped and the load goes on in the background; any failure
     turns ranking off for the rest of the question.
     Each such item's conversation leads to WHAT WAS SAID like any chosen item's, and there a turn qualifies by the
     item's own words (two of them, or its only one; an item with none of its own leads nowhere) — the line that
     told it. WHAT WAS SAID for a count or a list is
     read breadth first: each pointed conversation's best turn (≤ 300 characters), in rank order, up to 16
     conversations, then second turns, within 24 excerpts and 7,200 characters (`BREADTH_*`; was 8 / 10 / 6,000).
  No computed list of distinct occurrences is added: without a model, an event retold in a second conversation
  can't be told from a second event, and a conversation count stated as a number would anchor the model on it.
  Bounds: the search leg's breadth +1,800 characters, WHAT WAS SAID +1,200; the page fill uses the budget the page
  already had. Measured: `docs/research/2026-10-17-memory-benchmarks.md`, "Lists and counts".
- **Judgements and Spanish (2026-10-20, G148).** Two gaps the broad sample and the owner's hard set showed, each fixed
  with no model in retrieval:
  1. *A judgement is reasoned, a fact still declines.* LoCoMo open-domain scored 48.8 against 75 for the
     whole-conversation control; 37 of 42 misses said memory doesn't state what the record gave grounds to judge.
     `ask_sources.asks_inference` (no model) reads a judgement: a likelihood word (likely, probably, possibly,
     suspected, "do you think", "be considered"; probable, posible, quizás, tal vez), a leading "based on"/"in light
     of"/"según", a choice of what someone lives nearer to — or a conditional about someone else (review of #385):
     would/might/could, or a Spanish third-person "-ría" ("sería", "podría", "le gustaría", "disfrutaría"), only next
     to a name or he/she/they (a Spanish "le", "a <name>", "de <name>" too). Never about I or we ("which restaurant
     would we go to"), a thing ("when would the dentist appointment be"), "could not"/"couldn't", a request to the
     agent ("could you", "-rías": "¿sabrías decirme …?", "please"), or a conditional only reported ("what did she say
     she would do") — unless a likelihood word asks for a judgement. Over the whole of LoCoMo it fires on 48 of 96
     open-domain questions and on none of the 1,890 others (adversarial included), nor on the broad sample's 100
     LongMemEval questions. Only such a question gets the `_INFERENCE_NOTE` block after the question (the system prompt is
     unchanged): give the most likely answer marked as an inference ("Probably …, because …"), with the lines it
     rests on; general knowledge may connect the record to the question's terms but never supplies a fact about the
     people; "memory doesn't say" is not the answer when the record bears on it; confidence below 0.7. Its named
     pages' items are ranked by the search model as a list's are (`Searched.similar`, same bounds).
  2. *A Spanish question by meaning.* A Spanish question over English conversations put none of their words in
     front of the model: every word leg (claims and page items by shared words, WHAT WAS SAID, the search leg's
     turns) matches words. `ask_sources.question_language` (no model) reads a Spanish question: Spanish function words outnumber English ones,
     an article or "de"/"y" next to a capitalised word counting for neither ("Juan de la Torre", "Los Olivos"), and a
     question opening with an English question word or auxiliary without "¿" is English;
     `by_meaning` is then true — never for an English question whose words the record lacks, which is how an
     abstention looks (the first cut turned "what is the name of my hamster?" into a lookup). The meaning leg **leads** only when the words can't (review of #385:
     the owner's Spanish questions over his own Spanish conversations fell 50 → 43 % when it always led): no word of
     the question is weighed, or most of the `LANGUAGE_PASSAGES` = 3 nearest passages are in another language
     (`text_language`, function words). Over conversations in the question's own language the words lead exactly as
     for an English question — #381's count and list path included — and the meaning leg only **adds** at most
     `MEANING_EXTRA_EXCERPTS` = 2 lines (800 characters) after them, a conversation the words left out first
     (`Searched.adds`); the page leg reads as for any question. Leading:
     the vector leg's nearest passages (`Searched.passages`, the chunks' own text, no extra search) lead the search
     leg — each of the first `MEANING_EPISODES` = 4 conversations shows the turns of its `MEANING_PASSAGES` = 2
     nearest passages ranked by the search model on the question less the bank's common words (`turn_similar`, an
     allowance of `MEANING_TURNS` = 96; gap 3 below), one per conversation first, taking
     turns with what the words found; a day the question names leads (that day's conversations, read whole when the
     vector leg missed them). The full-budget pages rank their first `_NEAR_SCAN` = 24 claims and their items by the
     search model (`MEANING_TEXTS` = 160 for the question): the `_NEAR_CLAIMS` = 4 nearest claims point to WHAT WAS
     SAID, and a pointed line leads to its turn by the line's own words (`gather(follow=True)`). The prompt says the
     lines were found by meaning and adds `_SPANISH_NOTE` (the record may be in English, Spanish or both; answer in
     Spanish). Same on-device-only bounds as the list ranking; without the search model a Spanish question reads as
     before. Also, for a Spanish question only (`ask_sources.question_terms`; in English several are names — "Ella",
     "Han", "Como" — so the shared `text_fold.SUBJECT_STOPWORDS` is unchanged): Spanish function words are not subject
     words (`text_fold.SPANISH_STOPWORDS`), Spanish tense words leave the search words (`ES_TENSE_WORDS`), Spanish time
     phrasing reads as English does ("por primera vez", "al principio", "solía" → anchored; "al final", "actualmente",
     "todavía" → latest), and past-tense cues and a preterite's "-ó" ask for history. "ayer", "anteayer" and "hace
     tres días" name days. English prompts are
     byte-identical except the judgement questions'. Measured: `docs/research/2026-10-17-memory-benchmarks.md`,
     "Judgements and Spanish".
- **Implied facts, English over Spanish, names across languages (2026-10-20, G148, the gaps after #385).** No model in
  retrieval; measured in `docs/research/2026-10-17-memory-benchmarks.md`, "Implied facts and the record's language".
  1. *A fact the record only implies.* `ask_sources.asks_implied` (no model) reads a question worded as a fact whose
     answer is usually shown, not said: a state, country, continent or holiday ("which US state …", "in what country
     …"; "state" only beside a place or a verb of place, never a status — "what state is the PR in"), an age ("how old
     is <name>"), a preference ("which … does <name> prefer"), the common name of something described ("what card
     game is <name> talking about", "which popular composer …"), a yes or no about someone ("does <name> live in …",
     "is <name> married") — someone a person page in front of the model names, or he/she/they; "is Docker running?"
     is not one — and "who is <name>?" alone; Spanish forms too. Never a judgement (that keeps `_INFERENCE_NOTE`),
     never about I, we or you, never a request. Such a question gets `_IMPLIED_NOTE` after the question, stricter than
     the judgement note: a line that states it wins; when none does but the lines plainly imply it (a city's state or
     country, a day's holiday, a described thing's well-known name, what someone's words and doings show) the answer
     is marked "Probably …, because …" with its lines and days; general knowledge may make the link, never a fact
     about the people; an inference is only about whom the question names (what the lines say of someone else is
     theirs — LoCoMo's adversarial shape); a loose link is still a decline; confidence below 0.7. Its named pages'
     items are ranked by the search model as a judgement's are. Over LoCoMo it fires on 31 of the 48 open-domain
     questions the judgement detector leaves out, and on 25 of the other 1,890 (4 adversarial, 3 of which name a
     person page); on none of the broad sample's 100 LongMemEval questions.
  2. *An English question over conversations held in Spanish.* `ask_sources.record_language`: when the nearest
     passage of one of the vector leg's first `MEANING_EPISODES` conversations is in another language than the
     question (`text_language`) **and scores at least the search model's floor** (`RECORD_FLOORS`: EmbeddingGemma 2
     0.72; a model with no measured floor never takes this path), the question goes by meaning too
     (`Searched.record_lang`) — decided by the record's language and evidence that a passage speaks of the question,
     never by the question's missing words (an abstention looks like that). Review of #390: on a record in both
     languages the nearest passages always exist, so without the floor "what is the name of my hamster?" went by
     meaning onto unrelated Spanish turns. On `locomo-es-turns.json` the nearest Spanish passage of 24 never-said
     questions scored 0.635–0.717 and of answerable ones 0.625–0.821 (70 % at or above 0.72): no floor separates them
     cleanly, so it sits above every never-said one and the rest read as on dev. It **leads** when most of the
     three nearest passages are in the other language; otherwise it **adds** at most two lines beside the words, from
     the other-language passages only (the words read the question's own). The prompt adds `_RECORD_LANGUAGE_NOTE`
     (a translated name is the same thing, a line that does not mean what is asked is no answer; answer in the
     question's language). Over a record all in the question's
     language nothing changes: every English prompt of the broad sample's banks (382 LoCoMo, 100 LongMemEval_S) is
     byte-identical to dev but the implied-fact questions'.
  3. *A name in one language, the conversation in the other.* The claims vector leg already finds the page by its
     translated name ("la academia de baile de Jon" → the dance-studio page, four of four pairs checked); aliases
     bridge only what Sleep recorded; the word legs never can, and no word list is added. What did not bridge was the
     meaning leg's turn choice: it ranked only a conversation's nearest passage, and the speakers' names won it — in a
     two-person chat every greeting names the other ("¡Hola Jon! ¿Qué tal?"). Turns are now ranked on the question
     less the words said in most of the bank's conversations (`_without`, the word index's own `COMMON_SHARE`), from
     each conversation's `MEANING_PASSAGES` = 2 nearest passages (`MEANING_TURNS` 48 → 96). This also changes every
     Spanish question's prompt (#385's path). LoCoMo's two Spanish film-title misses were not a language gap: the
     conversation never names the film in either language.
- **The `sources` scope.** `answer_query(source_words=...)`, `POST /ask` `sourceWords` (default true): `cicada_ask`
  passes `ctx.raw_excerpts`, so a remote connector without `sources` gets no conversation words in the prompt (R-R22)
  — neither leg runs for it.
- **Watch history (owner ruling 2026-10-18, `capture-and-sleep.md` "Indexed, not consolidated").** A question about
  watching — a watch verb (watch/watched/watching), a platform (YouTube/TikTok), or a channel the record holds named
  whole (`watch_history.is_about_watching`; never a bare "video" or "channel": "how many channels does our chat
  workspace have?" keeps the honest gap, review of #341) — also reads the record, engine-free (`watch_history.lookup`):
  a month it names answers with that month's summary, otherwise the watched videos whose title or channel holds its
  words (whole words, the best-matching rows, dated, the newest 40), each line naming its day's episode. The lines go
  in a WATCH HISTORY block after the entities, only with `source_words`, and the answer may rest on them alone (no
  page retrieved is then no longer a gap); an `ep_` id the model lists is dropped from `used_entities`, never read
  as an invented entity. `cicada_recall_detail` on a page whose name or alias is a channel in the history appends one
  derived line (videos, days, first and last day; `watch_history.channel_line`), never stored and never a mention;
  `cicada_timeline` counts a watched day on its day ("Watched N video(s) on YouTube") instead of as a capture.
- **Ranges (2026-10-18).** A month worked and a range did not: on the owner's bank (99 month summaries, 2,532 watched
  days) "which channels have I watched the most this year?" answered "no per-channel counts exist". `asked_span` reads
  the range in English, deterministically — since/after X, between/from X and/to Y (a day, a month by ISO or name, a
  year), the last N days/weeks or calendar months/years (the same day N months back), this/last year/month/week, a
  named year (several: first to last), ever/all time — and a question asking "the most", how many/often, or when
  something was first/last watched with no range counts all time. A named month with "this/last year" ("in March last
  year") is that month of that year, read from its summary. `summarize` counts the range from the watched days themselves (not by adding month summaries,
  whose lists stop at 15 and under-count a steady channel), with no model, into one table: totals, the 20 channels
  watched most (videos, days, weeks, first and last day), the 10 come back to in the most weeks, the 10 videos watched
  on the most days, a line per month (up to two years) or per year with its top channels (at most 24), and for up to 5
  channels the question names (every word of the channel's name in the question, never fuzzy) their first and last
  watch in the range; then at most 15 watched videos matching the question's other words. The rows come from one
  cached frontmatter read per bank, refreshed when a day file moves. Size does not depend on the range: ~4–6k
  characters and ~0.1 s warm for 50k synthetic rows over 2,532 days (cold ~1.5 s, the bank's frontmatter scan).
- **The computed record outranks an earlier note about the system — and nothing else (2026-10-18).** The same answer
  quoted an agent's saved note from earlier that day ("the history had not yet been read by Sleep") as current: the
  block carried no time, so rule 9's "later wins" could not order a same-day note against it. The block is now headed
  COMPUTED FROM THE RECORD NOW with the minute it was counted and the record's last watched day
  (`watch_history.last_day`): an export is a snapshot, current only through that day. Synthesis rule 10: the block
  outranks only an earlier statement about the memory system's own state (not yet imported, read, processed or
  counted), never repeated as current where the block shows the record; the person's own words are never overridden
  by it — what they say about days after the record ends is newer and is used for those days. A prompt rule, not a
  filter: the note is a real conversation the answer may still need, and only the model can tell a system-state
  sentence from the person's own words.
- **Citations name what grounded the answer (2026-10-18).** A citation's `source_episodes` was the page's whole list:
  on the owner's page, several hundred ids, every conversation that ever touched it. It is now at most 5
  (`ask_service.MAX_CITED_EPISODES`): the conversations behind the claims and items this answer put in front of the
  model — those whose words reached WHAT WAS SAID first, then by the question's words the pointing claim or item
  shares, newest first — or, with nothing pointed (claims without evidence, a linked person), the page's newest; and
  `source_episodes_more` (`sourceEpisodesMore` on `POST /ask`) counts the rest. `cicada_ask` renders
  `(episodes: a, b +N more)`.
- **Cost.** On the benchmark bank the context build is ~20 ms (p95 ~30 ms, warm); the prompt grew from ~6–8k to
  ~8–17k characters. `api/tests/test_ask_source_words.py`.

**Ask grounding (G93/G118, 2026-10-07).** `/ask` and `cicada_ask` use the same
validity-aware context. Each structured claim sent to synthesis has its id,
observer/trust, current flag, start, close, stated end and successor; historical
rows explicitly say history, superseded or withdrawn. Metadata is assembled
before text is clipped; raw claim fences never enter the prompt. Current
questions receive current beliefs and unsuperseded events as dated progress,
never as continuing states. Page prose remains explicitly labeled unversioned
background that may be outdated; structured validity takes precedence. Sentences
repeating a closed non-event literal are removed from current-question context. Explicit past/change
language (including an as-of date) enables labeled history and adds the FTS
history leg; this is an English intent heuristic, not a model classification.
The synthesis rules require historical answers to state the validity dates and
never repeat a closed belief as current. Citations recheck claim provenance
against the loaded markdown. A deleted page is never revived from indexed text;
Pages with only closed beliefs and no usable background return an honest gap
without a synthesis call.
The historical lexical leg removes question/date words before matching, warms
a cold disposable index synchronously only when no usable index exists, honors
the default freshness TTL on warm reads, and takes matching historical subjects
before generic semantic neighbours. Prompt budgeting reserves claims from both
sides of a change. Implicit recall rechecks each selected page's claims against
markdown; every type's recall summary strips claim fences before truncation.

**Ask's retrieval does each piece of work once (perf 2026-10-24).** The prompt is byte for byte what it was (40
synthetic questions compared); on the owner-scale synthetic bank the time to the model call went p50 599 → 443 ms,
p95 810 → 663 ms. A page's closed claims are tested against its sentences through one predicate built per page
(`ask_service._repeater`: the texts folded once, the literal values in one pattern) instead of claim by claim with a
pattern compiled per claim; a citation's evidence reads the claims retrieval already parsed; `text_fold.subject_terms`
works out each text's words once (an LRU of 16,384 texts, a fresh set per call). The model call is still ~90 % of an
Ask: ~1.2 s of fixed CLI start, then output (~800 tokens at haiku, about half of it thinking; `--effort low` measured no
faster).

**Ask on a busy page and a named page (2026-10-23 live test).** Three defects, one fix each:
- *The newest fact reaches the model.* A page's claims were ordered by the words they share with the question alone
  and then cut by the prompt budget, so on a page of hundreds of current claims "latest release: 0.3.1" beat "released
  version: 0.6.0", said two weeks later. `ask_service._rank_claims`: for a question with no past cue (`_wants_history`),
  the claims sharing a word alternate with the same claims newest first (`_claim_day`: `valid_from`, else
  `recorded_at`, else the id's day), the rest follow newest first; "latest/now/current…" (`_asks_latest`) puts the
  newest first. A past question keeps the word order, newest first among equals. Confidence never ranks. And
  `text_fold.stem` folds a silent final "e", so "release" and "released" are one word.
- *A sentence is never a page.* A claim's object is sometimes a whole sentence; resolving it as a page raised
  `OSError: [Errno 63] File name too long` and the error emptied the whole retrieval ("no page exists" for a page
  recall found). `id_utils.is_page` refuses a name past 255 bytes and any `OSError`; both resolvers and
  `ask_service._load_entity` use it, and one bad claim hit is skipped, never fatal. The same error broke Sleep's
  Stage 5.5 wikilink step, which resolves through `id_utils` too.
- *A page the question names is retrieved.* Ask is claim-first; `ask_service._named_pages` adds recall's lexical leg
  (`search_service.lexical_entity_hits`), kept to pages whose whole name or alias the question says, ahead of the
  vector hits.
- *Latency.* Of a median ~12 s (max ~22 s), the model call is ~10–19 s (the telemetry's `duration_ms` for
  `stage: ask` on the plan: a `claude -p` spawn writing 1–3k output tokens); retrieval and the context build are
  ~1 s warm, ~2.5 s cold. No cut was taken: the output is the answer, and a smaller effort would trade quality.

---

**Skills through Cicada (the Skills page, owner 2026-10-15).** Three stdio tools, never remote (`NEVER_REMOTE`),
each with an exposed CLI row (`cicada skills list|propose|create`), one body each in `mcp_tools`:
- **`cicada_skills`** — every skill in this Mac's agents' folders (`skill_folders`), per agent (*on*, *through* another
  folder it reads, *off*), its source and version, the last update check (no fetch: the person checks), a tool skill
  whose text is older than its tool, permissions in words; then the catalog's suggestions, agents' drafts and the
  requests waiting. Third-party SKILL.md names and descriptions are fenced as reference data. Since G201 slice (a)
  (TODO ruling 35, 2026-10-22) each skill line also says its kind (`about-you`, `generic` or `kind unknown`, "(the
  person's choice)" when they set it), a section lists Claude Code's plugins read-only (`id version · on|off|switched
  per project · skills: …`, a skill only the person runs marked so), and one line gives each agent's loaded skills and
  estimated description tokens (characters/4, said as an estimate). The reply's `data` gains `plugins` (ids). An agent
  cannot set a kind or toggle a plugin: kinds are the person's (`PUT /skills/kinds`), plugins Claude Code's.
- **`cicada_propose_skill(action, reason, source?, skill?, agents?)`** — `install` (a GitHub link, `owner/repo[@skill]`
  or an `npx skills add …` line, parsed by `skill_sources.parse`) and `update` **always** become a request the person
  approves on the Skills page, where they see the files first: an agent never installs third-party code through
  Cicada. `on`/`off` (one agent) and `refresh` (a tool's skill text from the tool the person installed) bring in no new
  code, so a harness on the G198 trust list (`page_editors.is_trusted`) applies them at once; any other files a request.
  Requests live in `$CICADA_HOME/skills/requests.json`, not the bank inbox: the inbox is bank files, and nothing a
  skill does is written into a bank. The reply tells the agent to mention it in one line.
- **`cicada_create_skill(skill, description, body, reason?)`** — an agent's SKILL.md for a workflow (G112), held in
  `$CICADA_HOME/skills/drafts/<name>/` with its author and session; it reaches an agent's folder only when the person
  publishes it, choosing agents (`POST /skills/drafts/{name}/publish`). Another agent's draft of the same name is refused.

The person's side is the CLI's app rows (`cicada skills check|add|install|update|update-all|on|off|refresh|remove|
publish`), all person-only (`require_person`) and all through the backend's routes (`api.md`); `skills add` shows the
preview and installs only with `--yes`.

**A client of a server on another machine (G181 phase 2, owner rulings 1–3, 2026-10-16).** With `CICADA_API_BASE`
set (the address the person's own overlay gives the server: `https` for any host, plain `http` only to a loopback
tunnel; `runtime_layout.api_base`), this machine holds no bank. Unset, every door behaves exactly as before.

- **The stdio MCP server** never touches a local bank: every tool goes to `POST /tools/call` (`tool_client` →
  `api/routers/tools.py` → `tool_door`) with the device's token, the caller's G48 identity and client name, and the
  stdio process's per-session state (skipped inbox ids, the once-per-conversation now-view, the revisions
  `cicada_pending` listed), which comes back updated. The primer on `initialize` is built on the server. The server runs
  the **same body** a stdio process on the server would (`tool_door.DISPATCH` mirrors `handle_tool` argument for
  argument; tool names come from `cli_map`, and a test pins the two sets equal). Two things stay on the client: a
  picture, screenshot or specimen the agent names by path is read there (`mcp_tools._design_read_file`'s identity rule)
  and sent as base64 — a door call never opens a path a client names (`ToolContext.local_files=False`); and
  `cicada_repo_context`'s git probe runs where the repository is (the door answers only the page's declared repos).
- **A device counts as local (owner ruling 3).** A door call is not a remote connector (`connector_id` stays None), so a
  harness on the G198 trust list (Claude Code by default) edits a page at once, exactly as on one machine; an agent's
  claims keep G71's derivation. The server knows a call came through a per-device token because `auth.require_token`
  looked the bearer up in `device_tokens` and set `request.state.device` — nothing a client says can claim one — and the
  device's id is recorded as `device:` on what it writes (episodes, captured sessions). The G135 connector (its own
  listener and tokens) and the `agent` author stay off the list.
- **The `cicada` command** on a client resolves no root and opens no bank. Its pin is the server's active bank — name
  and `id` from one authenticated `GET /banks`, cross-checked with `/healthz`'s `bankId` (`cli_app.client_probe`) — and
  every mutating request names both (`X-Cicada-Bank`, `X-Cicada-Bank-Id`; `bank_binding` refuses either mismatch, 409
  `bank_mismatch`). The tool mirrors (`recall`, `get`, `project`, `continue`, `save`, `handshake`, `timeline`,
  `skills list|propose|create`) run through the door's command-line surface (`read_surface="cli"`, the exposed tools
  only, `mcp_only` rows refused); every `backend` row goes to its route as before; `bank list` reads `GET /banks`; a
  command that reads the memory folder in-process (`page list|history`, `graph`, `find`, `inbox all`, `sleep history`,
  `feed list`, a platform export's import) refuses `on_server` (exit 1). With the server unreachable every command but
  `status` refuses `backend_down` (exit 6); a refused token is `unauthorized`.
- **Devices** (`cicada device add <name>|list|revoke <id>`, person-only, `via="backend"`, run on the server): the
  token is printed once; only its hash is kept (`api.md`, "Device tokens"). `cicada device pair [--url <address>]`
  (G212) prints a one-time code and its QR payload for a new device (`api.md`, "Pairing a device").
- **Agents on the HTTP agent API** (`cicada agent add <name> [--scope …] [--days 7|30|90] [--url <address>]|list|revoke
  <id>`, G213, person-only, `via="backend"`): prints the paragraph to give the agent, token inside, once (`api.md`,
  "The agent API").
- **`cicada setup`** (G213, owner 2026-10-22; person-only, `via="backend"`, `api/cli_setup.py`): finds the server
  (`/healthz`), the agents on this machine and whether each reaches Cicada (`GET /agents/wiring`), and a way in from
  outside (`GET /remote/status`, detection only), prints a checklist, then asks before each step — run an agent's
  `connect` commands exactly as shown (`display == shlex.join(argv)`, else never run), pair a device (a code, its QR
  payload, a wait with a spinner), make an agent token and print its paragraph. Without a terminal it asks nothing and
  reports, unless `--pair` / `--agent <name>` name a step (`--url` gives the address). `rich` and `questionary` are
  imported by this command only; without them it prints the same steps plainly. It fetches nothing and starts no
  tunnel.

**The CLI (G180, TODO ruling 21; plan revision 3, build unit 1, 2026-10-07).** `cicada` is a second, thin door onto the
same bodies as the MCP server, for agents with a shell: they run a command and read `--help` only when they need it,
instead of loading every tool schema up front. The MCP stays for clients without a shell, and stays registered beside
the CLI.

- **Entry point.** `python -P -m api.cli` (`api/cli.py`). A developer checkout runs it through `scripts/cicada`, which
  follows its own symlink chain back to the checkout, runs the checkout's venv and passes `CICADA_CHECKOUT`. It is never
  a venv console script (G88). The release launcher in `~/.cicada/bin` and the Settings button that links
  `~/.local/bin/cicada` are later units.
- **In-process, like stdio MCP.** It calls `mcp_tools` bodies with a `ToolContext` whose `read_surface` is `cli` (read
  ledger rows say `cli-recall`) and whose `available` is the set of MCP tools the CLI exposes
  (`cli_map.exposed_tools()`). A reply therefore never names an action the command line lacks.
- **One bootstrap, before any service import.** In order:
  - The caller's folder is recorded and is never used to find configuration.
  - `LITELLM_MODE=PRODUCTION` is forced, so litellm's import-time `load_dotenv` stays off, and with it
    `LITELLM_LOCAL_MODEL_COST_MAP=True` (`api.pin_litellm`, `network.md`). Both are forced again after every overlay: no
    config file can set them, or the root keys.
  - The memory root is resolved as **one field**: caller `CICADA_MEMORY_PATH` > caller `CICADA_MEMORY_ROOT` > a
    developer checkout's `api/.env` PATH > ROOT > `~/cicada/memory`. The checkout file's other keys are overlaid (the
    file wins, as in the app-spawned dev backend).
  - The root is canonicalised once (`realpath`) and published as the only root in the environment.
  - `api.config.disable_dotenv()` then makes every `Settings` read **no** `.env` file, so neither a project's `.env` in
    the cwd nor one in `CICADA_HOME` can steer it. (Elsewhere — the backend, the MCP server, the hooks — `Settings`
    reads only the checkout's own `api/.env`, found from the package's folder, never the cwd; `api.md`, "The settings
    file".)
  - Provider keys load from `secrets.env` as the backend's lifespan loads them.
  - The active bank is pinned once (`bank_registry.pin_request_bank`) in a context every command runs in. The settings
    root is asserted equal to the pinned root, so `get_settings().memory_path` answers the pin through a mid-command bank
    switch.
- **Cross-check, not authority.** `GET /healthz` (1 s, no proxy) gives one of the states below. The memory is compared
  by **identity** (G181 phase 2, ruling 21a amended 2026-10-16): the pinned bank's `id` from `banks.yaml` among the
  backend's `bankIds`; only when either side has no id yet (an older backend, a registry not yet given ids) is
  `memoryRoot` compared after `realpath`. A path means nothing across machines or containers; an id does. (A memory
  folder copied by hand keeps its ids, so a copy and its original look like one memory — `duplicate_bank` mints new
  ones.) The states:
  - `confirmed`;
  - `mismatch`: reads proceed with `warnings: ["root_mismatch"]`, and writes will refuse;
  - `backend_down`: connection refused, and the bootstrap above is the authority;
  - `unverified`: a timeout or an error answer, with a `root_unverified` warning.
- **`--bank NAME`** (or `CICADA_BANK`) asserts the active bank, compared exactly. It never selects another bank. A
  mismatch exits 3 before anything is read.
- **Output contract.** Text by default. `--json` / `--format json` (before or after the subcommand) prints exactly one
  envelope, `{schema: "cicada.cli/1", command, ok, code, bank, data, text, warnings, version}`, and nothing else on
  either stream. Library output is sent to `/dev/null` at the descriptor level while the command runs.
  - Exit codes: 0 ok, 1 refused, 2 usage (unknown or abbreviated flags are rejected, never ignored), 3 bank/root
    mismatch, 4 demo bank, 5 sandbox denied (also a permission denial during bootstrap), 6 the app's backend is not
    running or did not answer (only for a command that acts on it), 70 internal or bootstrap. The outcome types live
    in `api/cli_types.py`, shared by `api/cli.py` (run as `__main__`) and `api/cli_app.py`.
  - Help with JSON selected is an envelope too: `command: "help"`, `data: {topic}`, with the usage text in `text`.
  - An internal error carries the exception's class name only, never its message.
  - The envelope is additive-only within `cicada.cli/1`.
- **Names: one tested table** (`api/services/cli_map.py`). Every stdio tool has exactly one row, a short grouped command
  (`recall`, `get`, `claim add`, `inbox resolve`, …) with each schema property mapped once to a positional (required) or
  a flag (optional), and kinds that match the schema. CLI-only options (`get --from`) are catalogued apart.
  - `test_cli_map.py` checks the table against `TOOLS`. The parser, `--help` and `cicada commands` are generated from
    it.
  - MCP tool names keep their `cicada_` prefix. Grouping them is the lean-MCP slice, with the old names kept as aliases.
  - No row takes a tool name: there is no generic dispatcher.
- **Commands (slice 1: units 1 and 2).**
  - `recall <query>`: the MCP body's text.
    - `data` is the generated hints payload the body returns beside its text (`mcp_tools.Reply`, a `str` subclass
      carrying `code` and `data`, so stdio and remote send the same bytes). It is never parsed out of the text, where a
      memory's own words may contain a `cicada-hints` fence.
    - An empty graph (no entity page at all, whether or not `entities/` was scaffolded) is a refusal: `ok: false`,
      `code: empty_graph`, exit 1, typed at the body's return site. The root cross-check's warnings ride along, in the
      envelope and on stderr in text mode. No match in a populated graph is still a success.
    - A missing vector index adds `warnings: ["degraded:vector"]`.
  - `status`: root path, source and verification; bank name, path and demo flag; the unconsolidated count; backend
    version and `writing`; the vector index state; distribution; the caller's folder.
  - `commands`: the full table in `data.commands`, with `exposed` per row.
  - `import <path> [--preview] [--include-history] [--no-wait]` (CLI-only, 2026-10-09; one command for two kinds
    of export, an app row: `via="both"`, person-only except `--preview`). The path is sniffed in the backend's own
    order: a file the intake's chat reader (`intake.parse_export`) finds conversations in is a **chat export** and goes
    to the backend's intake like the app's drop (`cli_app.import_chat_export`: `/intake/sniff` for `--preview`,
    `/intake/import`, `/intake/jobs/{id}` until done, `--no-wait` returns once queued; the confirmed-root rule below).
    Anything else, a folder included, is a **platform's data export** — a `.zip`, an
    unzipped folder or one file — read by the command line itself (the backend never opens a path), parsed by the
    upload's own reader (`saved_exports` / `media_ingestor.parse_upload`) and written by `media_ingestor.ingest_chunked`
    into the pinned bank, deduped on `url_index` against every channel. Demo bank exit 4; a mismatched backend root
    exit 3; a file that is no export `not_an_export`, exit 1; `--preview` writes nothing and reports
    `data: {source, platform, total, collections}`. See `capture-and-sleep.md`, "Platform data exports".
  - `get <entity>`: `cicada_recall_detail`'s page, verbatim, with `data: {entity_id, type, status, from, count,
    total_lines}` (over the budget it comes in parts, as for the tool; a bounded read below slices the whole page).
    - Bounded reads: `--from N` / `--count N` / `--line-numbers`, or the shorthand `ENTITY:START[:END]` (lines START
      to END, 1-based).
    - The argument is read **literally first**: a display name or legacy stem containing a colon (`Alpha: Beta`)
      always reaches its page, and the shorthand is tried only when the literal finds nothing.
    - A bad range is exit 2. An unknown entity is `not_found`, exit 1.
  - `project <project> [--since --tz]`: `cicada_project`'s body. Its "open a page" action is spelled
    `cicada get <entity-id>` (`project_text.render(detail_call=…)`), and progress and backlog actions are gated off.
    No project, a dropped project, or a page that is not a project is `not_found`, exit 1.
  - `continue [--session --before]`: G110's on-demand working-context read, one body shared with
    `cicada_continue` (`api/services/local_tools.continue_text`, never imported by `api/remote`).
    - The same selection and current-conversation rules apply. The folder is the harness's project dir, else the
      caller's working folder. The caller's own `(harness, session id)` is always passed, either part possibly unknown: `continue_text` requires it, so a no-argument read always applies #229's current-conversation rules (exact match, else the newest session's lineage and chronology), with nothing minted or stored.
    - Every follow-up read it prints is spelled through `continuity.Spelling` (`cicada continue --session …
      --before …`, shell-quoted) and runs as printed. The MCP keeps its literal calls by default.
  - `save <text|-> [--title]`: the one write. It is Awake capture through `cicada_save_episode`'s own body: scrub, dedup
    by hash, `episode_lock`, atomic create, demo refusal (exit 4), into the pinned bank.
    - Like every Awake capture it takes **no** write admission (capture is allowed while Sleep runs;
      `write_admission`).
    - A backend that serves another memory root refuses it, exit 3, nothing written. An unverified backend saves with
      a warning.
    - Provenance comes from the harness (`session_identity.cli_identity`, never minted, ruling 21):
      `session_id`/`harness` only when given, `project_dir` the folder above, `source: cli` (with `origin: mcp`, G9's
      closed vocabulary), default title `Agent note`.
    - With no session id the reply says so (`warnings: ["no_session"]`). A duplicate is `ok: true, code: duplicate`.
      A read-only bank is exit 5.
  - `handshake`: `handshake.build_cli`, a primer like the remote one that names only the commands the CLI holds,
    spelled from `cli_map.spell`. It sits within the same ≤1,800-token aim, is built per call (never cached), and its
    ledger row has `delivery: "cli"`.
- **`timeline [--since]`** is exposed too: `cicada_timeline`'s body, read-only, gated by nothing a reply names.
- **The app's commands (G180 parity, 2026-10-09; `api/cli_app.py`).** What the app does, from a shell. Each is a
  CLI-only row in `cli_map` (`app=True`, no MCP tool, so `exposed_tools()` and every reply's gating are unchanged)
  with `via` saying where it runs:
  - `via="bank"` — read in process from the one bootstrap, like every read (ruling 21), so it works with the backend
    down: `page list [--type --status]` and `graph` (`graph_builder`, pages only), `page history <entity>`
    (`git_service.get_entity_history`), `find <query> [--kind --limit]` (`search_service.search`, every kind unless
    `--kind`), `inbox all [--kind]` (`inbox_service.load_inbox`: every kind, deferred hidden), `sleep history`,
    `feed list`, `bank list`, `coverage pictures|sources [--ids --archived]` (`coverage_report`, vision items 1-2,
    2026-10-28: counts and enums, a few page ids per bucket only with `--ids`).
  - `via="backend"` — the running backend's own routes with the token, because the state is the backend's: `sleep
    status|start [--continue]|stop|end|schedule [--mode --at --every]|engine [--mode --model]|options [--batch-size
    --continue-after-reset --reserve]`, `index status|rebuild|use <model>|install [--model]`, `feed add|remove|poll`,
    `connector list|connect <id>|disconnect <id>|sync <id>` (ruling 47 tier 2: `connect` reads the token from standard
    input only — a hidden prompt in a terminal — never an argument, and the backend checks it before saving; the
    three that act are the person's, refused from an agent's shell),
    `import`'s chat-export branch (above), `settings
    owner [--name --handle --email]`, `engine list`, `page decay <entity> <class>`, `inbox answer <id> [--option
    --answer --defer --days --reject]`, `picture set <entity> <file>|initials|clear`, `bank use|create|rename|delete`.
    The CLI never starts a second Sleep, never writes state the backend holds (the scheduler, the run, the engine
    choice, a re-embed). Every mutating request names the pinned bank in `X-Cicada-Bank` (bank CRUD excepted), so a
    switch mid-command is refused by the backend (exit 3). With the bootstrap's probe at `backend_down` it refuses
    before sending (`backend_down`, exit 6); `mismatch` refuses (exit 3). **A write (any non-GET, bank CRUD included)
    is sent only to a backend that confirmed this command's memory root:** the backend checks the bank's *name*, and a
    fresh root's bank is `default` too, so an `unverified` probe (a slow `/healthz`, an error answer, no `memoryRoot`)
    is asked once more with a 5 s timeout and, unless that confirms, the write refuses (`root_unverified`, exit 3,
    `warnings: ["root_unverified"]` kept on the envelope). A read from an unverified backend proceeds with the
    warning. A 409 maps by its `code` (`sleep_writing`, `bank_mismatch`), `demo_guard.REFUSAL` as its detail is
    `demo_bank` (exit 4), any other 409 `refused`; 404 `not_found`, 413 `refused` with the server's sentence (the CLI
    does not shrink a picture), 400/422 usage with the backend's sentence, 401/403 `unauthorized`, 5xx
    `backend_error` (70). A schedule, engine, options or owner change reads the current value and sends it back
    merged. `index install` with no model named and none recommended refuses without sending; an `import` job still
    running when the wait ends is `backend_timeout` (exit 6), never "Imported".
  - **Person-only rows** (`person=True`) act as the person: a page or picture write the backend commits as
    `Cicada-Author: user`, an inbox answer, a run on the person's engine, a schedule change, a search-model switch or
    download (only on the person's command), a feed fetch, an import, a bank switch, rename or trash. They refuse
    (`person_only`, exit 1, nothing sent but reads) from an agent's shell (`cli_app.agent_shell`): one where
    `session_identity.cli_identity()` names a session or a harness, or that carries `CODEX_THREAD_ID`,
    `CODEX_SESSION_ID` or `CODEX_SANDBOX` (set by Codex in the commands it runs). An agent's write carries the agent's
    provenance, never the person's. The rule is a guard, not a lock.
  - `import` refuses any path that resolves under `~/.claude`, file or folder, on both branches (transcripts are
    captured by the Stop hook only). `picture set` uploads as-is; the app's shrink to 512 px is not done here, the
    server's bound applies.
  - `cicada commands` lists them apart, marked *needs the app's backend* / *the person only*; `catalog()` adds
    `via` and `person` to each entry (additive). The skill's table keeps to the agent commands and names `cicada
    commands`.
- **Spelling.** Generated actions (recall's hints, the state cursor, project's page action, continue's reads, the
  primer) are spelled by `cli_map.spell(tool, **values)` from the table, with every concrete value shell-quoted. A test
  parses each printed command back through the real parser. Memory's own text is never respelled.
- **Identity.** `api/services/session_identity.py` parses `CLAUDE_CODE_SESSION_ID` (strict UUID, `CLAUDE_PROJECT_DIR`)
  then `CICADA_SESSION_ID`/`CICADA_SESSION_HARNESS`. `stdio_identity` is G48's minting policy, re-exported by
  `mcp/server.py` as `resolve_session_identity`. `cli_identity` never mints and keeps a harness named without an id.
- **Gating.** `_hints_block` has a `can_open_hub` argument and names no action when the caller holds neither the detail
  tool nor the hub tool. Recall drops the state cursor's `refresh_with` when the caller lacks `cicada_handshake`.
  `render_question` (`can_answer`) drops `skip=true if unanswered` for a caller without `cicada_resolve_inbox`, and
  keeps the question and its choices. A remote connection keeps its current rendering until the G135 owner decides. Stdio holds
  every tool, and remote always holds the handshake and holds the hub tool whenever it holds recall, so both are
  byte-identical. Memory's own text is returned untouched (a page quoting a tool name or command-looking code stays as
  written).
- **Packaging (unit 3).**
  - A release's inner launcher `bin/cicada` comes from `scripts/release/write-launchers.sh`, which
    `build-backend.sh` calls. It sources `cicada-env`, then runs `exec "$CICADA_PYTHON" -P -m api.cli "$@"` with no
    `cd`, so the caller's folder is kept.
  - The app's `LauncherInstaller` writes the stable `~/.cicada/bin/cicada` beside the other four.
    `runtime_layout.LAUNCHERS` and `CicadaRuntime.launcherNames` list it.
  - A developer checkout has `scripts/cicada`. `make cli` / `./install.sh --cli` (`scripts/install-cli.sh`) link
    `~/.local/bin/cicada` to it.
  - The app's the Agents page *Install the command-line tool* (General until the Hyrum audit's B11) links `~/.local/bin/cicada` to the runtime's own
    launcher (`app.md`). The script and the button share the never-replace rules.
  - A Swift end-to-end test runs outer shim → inner launcher → CLI in a synthetic bundle: caller's folder kept, a
    moved app exits 127 with the repair sentence, and the next rewrite works.
- **The usage skill.** `SKILL.md`'s *From a shell* block sits between `cicada-cli:begin/end` markers and is generated
  by `cli_map.skill_block()` (`cli_map.write_skill_block("SKILL.md")` rewrites it; a test fails on drift).
  - It teaches the exposed short commands, `--json` and the envelope, the exit codes, session grouping, what is
    MCP-only, and the fallback `"${CICADA_HOME:-$HOME/.cicada}/bin/cicada"`.
  - Every command in it parses with the real parser (R12 for the CLI half). The retained MCP instructions are checked
    against the MCP schemas (R12 for the MCP half).
  - `handshake.build_cli`'s prelude names the same fallback, and stays within 1,800 tokens.
- **Not yet built:** the overhead and latency measurement (T9). Its later slices are in the G180 row.

## Stdio hygiene (the 2026-10-22 Hyrum audit: G199's integrity cases, G200 A8/A10/A11)

- **Two refusals in the bodies, so every door refuses alike** (stdio, `/tools/call`, the remote connector, and the
  command line, which calls the same body or the door). `cicada_write_claim` with an `observer` outside the accepted set
  answers `Could not write claim: observer '<value>' is not one of 'owner', 'agent', 'external' or 'external:<name>' …;
  nothing was written.`; absent or empty is still `agent`. `cicada_save_episode` with missing, empty or blank `content`
  answers `Nothing saved: \`content\` must be the text to keep, and it was empty.` Both are `Reply(code="refused")`,
  so the command line exits 1, and both MCP doors answer them `isError: true` (next section).
- **The advertised `observer` pattern names no person** (A11): `^(owner|agent|external|external:[a-z0-9][a-z0-9-]{0,63})$`
  (`mcp_tools.OBSERVER_PATTERN`). The legacy observer value old local installs send is still accepted by the body
  (`mcp_tools.observer_accepted`) and still stored as the owner; it is in no schema or description
  (`test_owner_name_portability`).
- **JSON-RPC basics** (A10, additive): `ping` answers `{}` (a notification, none); a line that is not JSON answers
  `-32700 Parse error` with `id: null`, one that is JSON but not an object `-32600`; `tools/call` without a `name`
  answers `-32602`. Every stdio tool that only reads carries `annotations.readOnlyHint: true`, from one list the tool
  table owns: `cli_map.read_only_tools()`, every row with `mutates=False` (2026-10-23 — the remote `READ_TOOLS` used
  before leaves out the stdio-only reads, so Codex asked for approval on every `cicada_continue` and `codex exec`
  refused it). A cache outside every bank, an ids-only ledger row or the process's own memory is not a write; the
  bank, the inbox, a queue lease or an agent folder is. `test_tool_annotations` holds every stdio tool, the remote
  definitions and the remote `READ_TOOLS`/`WRITE_TOOLS` to it, and no write is ever read-only; no other annotation
  is added.
- **Teaching material** (A8): `SKILL.md` (and its byte copy in the plugin) shows the current bank layout
  (`banks/<bank>/…`), points corrections at `cicada_edit_page` / `cicada_write_claim` / `cicada_resolve_inbox` instead
  of "never edit", and names the plugin as the Claude Code door when the tools are missing. A type hub's blurb tells an
  agent to open a page with `cicada_recall_detail`, not a file path a remote or client agent does not have (rebuilt at
  the next Sleep; no migration).
- **Episode ids** carry the conversation's local day (ruling 34; `capture-and-sleep.md`). An id is opaque to an agent:
  `cicada_ask` dates each line by the local day its turn was said, never by the id.

## The tool-call contract (G199, G200 A7/A9, Hyrum audit A1/A4/A6; 2026-10-22)

One module, `api/services/tool_contract.py`, holds the rules both MCP doors keep. Each door checks a call against its
OWN advertised table (stdio `TOOLS` in `mcp/server.py`, remote `REMOTE_TOOLS`), once, before a body runs.

- **Arguments are checked against the schema** (`tool_contract.check`): `type` (unions too), `required`, `enum`,
  `pattern`, `maxLength`, `maxItems`, `items`, nested objects, `anyOf`. An enum is matched without regard to case,
  spaces or hyphens and passed on as its canonical value (`"Watch Later"` is `watch_later`). An argument whose body
  keeps the record and drops an unknown value with a note has no enum: its values are in its description
  (`cicada_record_watch`'s `engine` and `basis`, a shot's `kind`, a page's `chosen_by`, a snippet's `lang`, a
  participant's `role`). A release batch (`cicada_video_claim`, `cicada_refresh_claim`, `cicada_explore_claim`
  `release`) is checked only as a list of objects (`ROWS_CHECKED_BY_BODY`): the body judges each row, hands back the
  good ones and names the bad. `duration`, an excerpt's `t` and a design `region` take numbers. A failure answers
  ``Invalid arguments: `top_k` must be an integer (got the string "lots").`` with every problem named, code
  `invalid_arguments`, and nothing run. `since` on `cicada_timeline` and `cicada_project` is a date or a number of days
  (`SINCE_SCHEMA`: `"7"`, `"7d"`, `7`, `2026-09-01`); `"last tuesday"` used to fall back to the default window in
  silence. `cicada_project`'s `tz` must be a zone `when.is_zone` reads (it used to fall back to UTC).
- **Leniency kept, and said.** `null` for an optional argument is no argument. An argument the tool does not take is
  dropped with a `Note:` naming it (a stdio-trained agent's `quote` on the remote `cicada_resolve_inbox` is no longer
  lost in silence). `cicada_resolve_inbox` also takes `item_id` for `id`, unlisted (`ALIASES`; its sibling
  `cicada_record_check` spells it so).
- **A number or boolean spelled as a string is refused (since 0.7.1).** 0.7.0 alone read a digit string where the
  schema says integer, a decimal string where it says number, or `"true"`/`"false"` where it says boolean, as that
  value with a `Note:`; that leniency ended in 0.7.1. Such a string is now refused on both doors like any other wrong
  type, with a hint to send it bare: ``Invalid arguments: `top_k` must be an integer (got the string "3"; send 3
  without quotes).``
- **The command line and `/tools/call` run no schema check** (their callers are argparse and Cicada's own stdio
  client, which checks first); the two cases that used to read wrong there are now refused or read right in the
  bodies themselves: an unreadable `since` (`tool_contract.since_problem`, the door's words) and a JSON `"false"` on
  an edit's `pin` or `all` (`page_edits._flag`).
- **A refusal says so.** A body returns its sentence as `mcp_tools.Reply(text, code=…)`; every code in the command
  line's `cli_types.REFUSAL_CODES` (`not_found`, `refused`, `invalid_arguments`, `out_of_range`, `error`, `demo_bank`,
  `empty_graph`, …) answers `isError: true` plus `structuredContent: {code, data, message}` on both doors, and the
  same code is the command line's `ok: false` and exit code. The sentence itself is unchanged, and `content` is still
  the whole reply, so a 2024-11-05 client that ignores `structuredContent` reads what it always read. `duplicate`
  (an episode already saved) is an answer, not an error. The tool bodies' `Error: …`, `Not recorded: …`,
  `Not saved: …`, `Nothing changed — …` and not-found sentences carry codes (typed by a codemod over `mcp_tools`).
- **An exception names its class, never its message** (`tool_contract.failure_text`). A message can carry a path or
  the caller's own words. The person still gets what they need to debug: every door logs `tool_contract.where(exc)` —
  the class and the three innermost frames as `file:line in function`, repo-relative, no message, no argument (the
  query is never logged). Stdio answers `Error: that didn't work (ValueError); where it failed is in the MCP server's
  log.` and prints `cicada-mcp: <tool> failed: ValueError at api/services/x.py:12 in f < …` on stderr. The tool door
  logs the same line in the backend log and answers `… is in the Cicada server's log (<tool>, HH:MM:SS UTC).`, so a
  `cicada` command run against a server says when to look. The remote door logs it and tells the cloud app only the
  class. A body's own catch-alls (`ask`, `save_url`, `sources`, `get_perspective`, `resolve_inbox`, and the
  `agentic_write`, `backlog` and `progress` writers) name the class only, log where, and code the reply `error`.
- **Third-party text is marked one way on both doors** (A9). A body's reply from a read tool — `catalog.READ_TOOLS`
  (recall, recall_detail, open_hub, sources, ask, get_perspective, check_nudges, timeline, project, backlog,
  reading_queue, video_queue) and, on stdio, `cicada_pending`, `cicada_design_search` and `cicada_continue` — is fenced
  **whatever its code** (a refusal can carry stored words): `REFERENCE_HEADER`, then the stored words between the
  `<<<cicada-reference` / `cicada-reference>>>` markers (`tool_contract.reference`). Cicada's own directions stay
  outside the markers where the body keeps them apart (`Reply.framed`, `segments`, carried over `/tools/call` too):
  recall's `cicada-hints` block, a `recall_detail` part's "the rest:" footer, the inbox's resolve and check lines. The
  other stdio-only reads (explore queue, site map, skills) and a write's reply that carries a provider's words (a video
  title, a site) mark those lines with the same header and markers (`_untrusted_block`). A door's own refusal
  (invalid arguments, an exception) is Cicada's sentence and is not fenced. The command line's text is not fenced. A
  `Note:` about the call sits after the block. A recall with no page but with hints, inbox blurbs or conversation
  excerpts is an answer, not `empty_graph`; only a recall that found nothing is that refusal.
- **The recall hints** (A1). The `cicada-hints` fence, its info string and its keys (`suggested_entities`,
  `relevant_hub`, `hub_members_preview`, `next_tool`, `note`, `state`) are stable; key order, the prose `note` and the
  precision of a number are not. The once-per-process `state` names its cursor's keys as the cursor's:
  `pending_as_of` (was `pending`) and `refresh_with` (was a second `next_tool`). A hit's heading shows confidence to
  two places.
- **`cicada_recall_detail`** (A6) leaves Sleep's bookkeeping out of the page it returns (`section_provenance`,
  `layout_version`, `decayed_through`, `learned_on`, `decay_rate`; `decay_class` stays). A part ends before a code fence
  it would cut when it can; a fence longer than a part is cut, and the footer says the cut is inside that block, which
  goes on. The parts are still the page's own bytes, and the claims fence is still the page's own JSONL.
- **Names and arguments are frozen** (A4). G180 names no new tool names yet; the lean-MCP grouping, when it is decided,
  keeps the old names callable and unlisted, with a removal date in TODO.md and a test.
- **The handshake** (A7, `CONTRACT_VERSION` 19): the variant is picked by exact `clientInfo.name`
  (`handshake.CLIENT_VARIANTS`: `claude-code`; `codex`, `codex-cli`, `codex-mcp-client`; `claude-ai`, `claude-desktop`
  → `desktop`; anything else `generic`), never a substring, so a desktop app is never told to run `claude --resume`.
  The primer names no HTTP route (`POST /conversations/{id}/resume`, `GET /episodes/{id}/span`, `GET /state` are gone):
  resume is the person's step, and a claim's span is shown by `cicada_sources`.
- **The fixture.** `api/tests/fixtures/mcp_stdio_golden.json` pins whole `tools/call` results (`call_tool`), refusals
  and the spelled-number refusal included; `api/tests/test_mcp_error_contract.py` holds the rest.

## The remote connector's sign-in and capture (ruling 32, owner 2026-10-19)

- **Sign-in.** The G135 listener is also an OAuth 2.1 authorization server (`api/remote/oauth.py`; the whole flow,
  its checks and its limits are in `network.md`). A signed-in app holds an hour-long `cic_at_` access token and a
  rotating `cic_rt_` refresh token; the gate verifies an access token against the connector row it maps to, so tool
  lists, scopes, the Sleep gate, the ledger and every write's provenance (`Cicada-Author: <app harness>`,
  `Cicada-Session: rc_…`) are the link connector's, unchanged. The secret link (`/c/<token>/mcp`) still works; the docs
  and the From anywhere group steer Claude and ChatGPT to sign-in, which puts no secret in a URL.
- **`cicada_capture_turns(message, previous_reply?, conversation)`** (`record` scope, remote only —
  `catalog.REMOTE_ONLY`, so `test_remote_tools.py` classifies every stdio tool plus it). Not read-only, idempotent, not
  destructive and not open-world: an app that confirms writes (ChatGPT) asks the person, who can allow it always.
  `REMOTE_CONTRACT_VERSION` 12 puts "Capture every turn" first in the remote contract, only where the connection holds
  the tool (R12 per scope set). What it writes and why it is never the person's own words: `capture-and-sleep.md`,
  "Hookless apps, through the remote connector". Its schema takes no zone: the listener reads the IANA `timezone` of
  the `openai/userLocation` hint ChatGPT puts in a call's `_meta` (only that field) so the episode id carries the
  person's day (ruling 34); claude.ai sends none, and its relayed ids take the server's zone.
