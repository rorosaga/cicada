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
warm 0.35–1.0 s → 0.08 s, byte-identical replies (2026-10-09). The top three pages carry a bounded
"Changed recently" block (claims closed in the last 30 days, ≤ 5 lines);
`cicada_get_perspective(history=true)` lists every earlier claim. **`cicada_timeline(since)`**
answers "what changed" from the commit manifests on demand — ids and counts only, nothing stored,
`read` scope remotely. **`cicada_record_watch`** records what an agent's own tools saw in a saved
video — a summary and ≤ 12 timestamped quotes as `media` spans; Cicada never downloads or watches a
video, and never keeps a transcript. **`cicada_project(project, since?, tz?)`** (G141 PJ-2, `read`
scope remotely) answers where a project stands — next milestones, what passed with no word, the Sleep
queue, what happened and what is around it — from the engine-free read model, printing every relative
word beside its absolute date ("yesterday (2026-09-22)"); a quote of the person's words needs
`sources` remotely. **`cicada_continue(session?, before?)`** (G110 slice 1a, stdio only — `catalog.NEVER_REMOTE`,
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
**`cicada_note_progress`** (G141) records a happening or a milestone the person
described — observer always the agent, `record` scope remotely, never creates a page, echoes how the date
was decided; `cicada_retract_claim` withdraws an event the same way.
**`cicada_add_source(subject, ref, predicate?, access?, kind?)`** (G61 phase 2 S1) records where a
fact can be checked when there is no claim to write — only a source the person named, never one the
agent guessed; it is not `cicada_sources` (conversations). `record` scope remotely, where a path, a
repo or `access: local` is refused; it commits alone under the harness. `cicada_write_claim(sources=)`
takes a string or `{ref, access}`. Since G61 S3-a (contract 12, remote 9) the primer names it, and takes an optional
`entity` (an existing page that knows more about the source). **`cicada_change_source(subject, ref, predicate, action,
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
person or saying "my"/"her" (labels ride in the prompt), a question the person already took a check back on
(`web_check: undone`), a multi-valued predicate other than what the thing *is*, or a conflict whose predicate is not
world-truth (`locus` world/artifact or a short public list: `description`, `is-a`… — `web_settle.classify`). **What it
is** (owner, 2026-10-16, his own example "Is <tool-a> an agent harness or an AI agent itself?"): a type question
(`web_settle.TYPE_PREDICATES`: `is-a`, `type`, `kind`, `category`, `genre`, `description`) is eligible though `is-a` is
multi-valued; one option settles only when the page rules the others out — defines it as that option and nowhere as
another (Sleep's answer must say `others_ruled_out: true`) — the item's own `both` option when the page describes it as
more than one of them (2026-10-19) — one cited claim per
option, nothing closed — and never an option the item does not have. **What leaves the machine:** the search query is the
subject's name plus at most one generic category word from a fixed list, read from Cicada's own description, none on a
type question and none when unsure (`web_settle.query_for`); nothing else. **What the model may read (ruling 27a,
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
option key / answer, Sleep running, ten settles a session. **Repository state** ("did PR #n merge", "is G<n> shipped")
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
1, ≤ 5) only while agent reading is on and acknowledged, the site is turned on in Reading the web, not Never explore, and —
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
"tokens left out"). The note is the agent's: it is shown as "Noted by <harness>", never as the person's words. The stdio server reads that file as the
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
the oldest queued videos (10 a call, 45-minute lease) or, with `release=[{url, code, reason}]`, hands one back
(`needs_login` tells the agent not to sign in and tells the person). It is in `WRITE_TOOLS` (the demo gate, the write
lock; only its per-video title/channel lines are fenced, Cicada's own instructions in the reply stay outside) but `runtime._writes_bank` is false for it, and **a lapsed lease is judged only when Sleep is not
holding the pages** (`ToolContext.pages_held()`, asked lazily), so a drain cannot burn a video's three attempts; while a
lapsed lease is due, the `videoQueue` stamp also carries that hold bit (`<mtime>:<due>:<held>`), so the hold ending moves
the component the app follows with nothing written. `VideoStateCache.reset()` on a bank switch keeps what a page asked
for (`asked`), and the switch reads the new bank at once.
`record_watch` credits the queue whether or not its bank commit ran. **No batch cap** (a hand-off takes every selected
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
(Telegram, an agent's save, a chat export: the person's own words) is served only to a caller holding `sources`. `cicada_record_read(url, outcome, summary?, excerpts?, via?, note?, title?)` (`record` scope) takes `read |
needs_login | blocked | not_found | failed`. Only a **successful read is memory** (`page_read.py`): one episode
(`assistant:` summary, then a quoted `attachment [host]:` block, so quotes are `page` spans — text the agent
*reported*, never the person's words or checked by Cicada —, `processed: true`, `processed_by: agent`), one `describes`
claim (a re-read closes the previous one), a thin description filled, and a `read:` stamp on the page; it commits alone as
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
a value this build cannot read, drops the block and never the row). **Settings → Reading the web** (`SettingsSection.reading`,
in Customize after Integrations; `ReadingWebView`, `ReadingAgentModel`; not a Store domain — fetched when the page opens and
answered by every write) has three groups. *With an agent*: "Let an agent read pages for you", off by default; turning it on
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
Settings → Agents keeps one row, "Reading pages", linking here. **Home** gains its own block, *Needs your browser*
(`ReadingSitesSection` between Needs you and Last read, over `ReadingSitesCache` — in memory, ETag-revalidated when Home
appears or the sources move, emptied on a bank switch, never a Store domain): "N saved pages need your browser to be read"
(the server's `waitingNotAllowed`), up to three of those sites' icons, linking to Settings → Reading the web; hidden at
zero and once every listed site is allowed, and never counted in Needs you. The wall
is not shown only there: the saved row's second line says "Needs sign-in" (`ReadWords.rowFlag`) and `ContentView`
toasts a link that just hit one (`ReadWords.newlyWalled`; the first look after launch or a bank switch announces
nothing). The wall reads in the text ladder with a neutral glyph, never `warning` (DR-7), and the agent's own note shows
as "<agent> noted: …". No line says "in your browser" of what an agent did, or promises what it will not do.

**YouTube lists (G71 / G166, owner 2026-10-16: "the agent being able to go to youtube using the browser to monitor
stuff … like for youtube watch later/history").** The third door onto the watch record (`capture-and-sleep.md`, *Watch
history*), on this section's rails: Cicada never spawns a browser, never signs in and never fetches either page; it only
offers. **Consent:** agent reading on (its sheet acknowledged) AND the person turned the list on in Reading the web
(`reading.json` `youtube_lists`, `{watch_later|history: day}`, off by default, refused without a current acknowledgement). The switch is a **standing ask for exactly that page**, not
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
  on in Reading the web, and **Never explore** sites. Depth comes from the person's reason (D4; slice 2 below).
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
  `VERSION` stamp: `release.sh bump` moves it and `check_version.py agree` holds it), `skills/cicada/SKILL.md` (a
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
  `CICADA_CAPTURE=off` (Cicada's own spawns; Sleep's `claude -p` also runs `--safe-mode`, which disables plugins), one
  episode per session, the transcript read by the backend only under the harness root. The plugin's `recall` setting
  (*Remember automatically*, on by default) silences only the recall hooks.
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

**Implicit recall (G149).** G105 stopped capture depending on a model's tool call, and recall now works the
same way.

- **The hook.** `api/hooks/recall.py` is stdlib only. One command is registered under both `SessionStart` and
  `UserPromptSubmit` in `~/.claude/settings.json` and `~/.codex/hooks.json`, owned by its own marker in
  `api/hooks/registry.py`. It posts to `POST /capture/hook-context` and prints
  `hookSpecificOutput.additionalContext` (the one shape both harnesses parse) or nothing. It always exits 0,
  never 2 (which erases a prompt), under a 0.9 s client timeout.
- **The note.** `hook_recall` answers engine-free from the derived FTS index. SessionStart gets the primer. A
  prompt gets at most three pages it **names**: a whole name or alias, and one word only for a person, project,
  company, tool or place. Each page comes with its summary and at most two current claims with their dates,
  plus at most one open inbox question — only one the message is ABOUT (the ask gate below), worded as a statement
  the agent can act on naturally ("if the message already answers it, it is recorded … and not asked"), with a
  pointer to `cicada_check_nudges(mode="list")`. A follow-up never rides a note. The note is ≤ 400 tokens or
  nothing, produced within a hard 300 ms.
- **The vectors.** They only re-order pages already named, and only when the on-device embedder is already
  loaded. A hosted embedder is never sent a prompt.
- **Repeats.** A per-session window keeps a page from being re-sent on consecutive turns.
- **The bank.** It reads the bank a capture would write into: the real bank while the demo is open, and
  nothing when there is none.
- **When it is skipped.** `CICADA_CAPTURE=off` spawns, `CICADA_RECALL=off`, and a Codex sub-agent's prompt.
  Codex also runs a new hook only after the person trusts it at startup.
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
  git directory/index/object/config overrides removed. No status/log/remote/worktree crawl or repository content.
  macOS skips the `/usr/bin/git` install-dialog shim; the installed runtime's bundled git is the last fallback.
  Failure or malformed output leaves exact-cwd matching. `resume`, `compact` and `fork` carry their own history
  and get no startup block; they may still supply identity for requested reads.
- **Supplied values and privacy.** The hook posts plain checkout root/common-directory strings, an exact cwd hash,
  observation time and a hash scoped to local hook home + device. `workspace_identity` is a pure backend parser:
  it validates shape, age and lexical containment, hashes the supplied strings and never opens, stats, resolves or
  runs git in them. Authentication does not prove an assertion: matches are labelled *harness-observed*, and every
  note still says *workspace state not checked*. Persisted `workspace_identity` holds only `family_hash`,
  `checkout_hash`, `cwd_hash`, `observed_at`. No supplemental raw path is stored, even in the episode. Git common
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
  reply with the turn it answers and a question with its reply, then sorted oldest first. Every line names its day and
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
  best-ranked conversation is never pushed out. `enumerate` reads the 4 exactly as any question does, then adds one
  line (≤ 300 characters, no context turns) from each further on-subject conversation and each of the 4 the budget
  left without a line, up to 10 conversations and 1,800 more characters; its header tells the model to count each
  distinct event once and say the count covers what memory shows. A value question the gate takes for a count ("how
  many stars do I need") so loses nothing. Lines stay oldest first. Rule 11 adds: lines on one subject on different
  days — the later is what happened after (answer with it, the earlier as history, never "the outcome is not
  recorded" when a later line states it); a question about one past occasion is answered from that occasion, and a
  later line about something else never replaces it or what the entities and WHAT WAS SAID show. The page leg's WHAT
  WAS SAID keeps its own budget and comes first; the search leg never repeats a turn it showed. The question is
  embedded once per Ask: the page leg's claim search and this leg share the vector through the indexer's per-model
  query cache (measured: one query embed per Ask). Measured: `docs/research/2026-10-17-memory-benchmarks.md`, "Ask
  depth".
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

---

**Skills through Cicada (the Skills page, owner 2026-10-15).** Three stdio tools, never remote (`NEVER_REMOTE`),
each with an exposed CLI row (`cicada skills list|propose|create`), one body each in `mcp_tools`:
- **`cicada_skills`** — every skill in this Mac's agents' folders (`skill_folders`), per agent (*on*, *through* another
  folder it reads, *off*), its source and version, the last update check (no fetch: the person checks), a tool skill
  whose text is older than its tool, permissions in words; then the catalog's suggestions, agents' drafts and the
  requests waiting. Third-party SKILL.md names and descriptions are fenced as reference data.
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
  token is printed once; only its hash is kept (`api.md`, "Device tokens").

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
    `feed list`, `bank list`.
  - `via="backend"` — the running backend's own routes with the token, because the state is the backend's: `sleep
    status|start [--continue]|stop|end|schedule [--mode --at --every]|engine [--mode --model]|options [--batch-size
    --continue-after-reset --reserve]`, `index status|rebuild|use <model>|install [--model]`, `feed add|remove|poll`,
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
  tool nor the hub tool. Recall drops the state cursor's `next_tool` when the caller lacks `cicada_handshake`.
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
  - The app's Settings → General *Install the command-line tool* links `~/.local/bin/cicada` to the runtime's own
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
