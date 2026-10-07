# The MCP surface

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

The interface between any LLM and the memory system. On `initialize` the server returns the G75
handshake as `instructions`. On query: check `memory/inbox/` for relevant pending items → search the
vector index → search the markdown graph → follow wikilinks for relational depth → progressive
disclosure (cluster pages → entity pages → episodic sources).
Recall prose summaries, including related-page blurbs, strip closed claims fences
before truncation; `cicada_recall_detail` returns the complete page for structured reads.

**Recall (G140).** Three legs fused by one RRF (`search_service.rrf_fuse`): the stored vectors, the
FTS lexical leg (names, aliases and prose, word by word), and current claims mapped to their
subject — so an alias or a relationship label reaches its page. Each leg is filtered against the pages as their
markdown says now before fusion (`_live_pages`): a page that is gone or `dropped` is never ranked, suggested in the
hints block or rendered (audit 2026-10-05 P2-5). The top three pages carry a bounded
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
**`cicada_backlog`**, **`cicada_add_backlog_item`** and **`cicada_add_backlog_note`** (G150) read and file a
project's backlog — see Backlogs.
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
the harness and never mints a page. **Only a link the person asked about, or a wall page of a site they allowed, can be recorded** (`reading_queue.authorizes`: `("ask", row)`, `("site", None)` or nothing; a row this tool wrote itself, `origin: site`, authorizes only while its site is still allowed and the page still a wall page, so switching a site off revokes recording at once): `cicada_record_read` refuses every outcome for any other URL (a saved public page with no wall included), and `reading_asks.record_outcome` creates a row only for that site case (`create=True`, `origin: site`) — an agent, or a page steering it, cannot rewrite a saved link's description or plant a `needs_login` banner on a link nobody asked about or on a site nobody allowed. **The exposure, stated:** with a site grant the person consented to a *site*, not to a page, so any agent holding `record` can then record a wall page of that site; the structural denials (R-RW5), the master switch, "every outcome but `read` is ask-store only" and `page`-kind spans bound it. A site-origin `read` writes no ask row (the page's own `read:` stamp keeps it out of the queue) and site rows are evicted before any explicit ask (`MAX_SITE_ROWS` 200). A `read` is also refused while Sleep runs on stdio, as the remote path refuses it (its reply says to keep the summary and record it when Cicada has finished). A `page` span from `page_read` reads "From the page, as <agent> read it" everywhere the app labels it (the episode's `source: page-read` rides `/episodes/{id}/text` and the provenance conversation rows), never a bare "From the page". **The other four outcomes touch only the ask store**: no bank write, no commit, no Sleep
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
bank write) refreshes the Feed over SSE; `MediaFeedItem.read` (`MediaReadState`, decoded leniently — an older backend, or
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
signed in") offers Try again. The **Feed's detail column**
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
is not shown only there: the Feed row's second line says "Needs sign-in" (`ReadWords.rowFlag`) and `ContentView`
toasts a link that just hit one (`ReadWords.newlyWalled`; the first look after launch or a bank switch announces
nothing). The wall reads in the text ladder with a neutral glyph, never `warning` (DR-7), and the agent's own note shows
as "<agent> noted: …". No line says "in your browser" of what an agent did, or promises what it will not do.

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
  plus at most one open inbox question as a pointer to `cicada_check_nudges`. The note is ≤ 400 tokens or
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
  - `LITELLM_MODE=PRODUCTION` is forced, so litellm's import-time `load_dotenv` stays off. It is forced again after
    every overlay: no config file can set it, or the root keys.
  - The memory root is resolved as **one field**: caller `CICADA_MEMORY_PATH` > caller `CICADA_MEMORY_ROOT` > a
    developer checkout's `api/.env` PATH > ROOT > `~/cicada/memory`. The checkout file's other keys are overlaid (the
    file wins, as in the app-spawned dev backend).
  - The root is canonicalised once (`realpath`) and published as the only root in the environment.
  - `api.config.disable_dotenv()` then makes every `Settings` read **no** `.env` file, so neither a project's `.env` in
    the cwd nor one in `CICADA_HOME` can steer it.
  - Provider keys load from `secrets.env` as the backend's lifespan loads them.
  - The active bank is pinned once (`bank_registry.pin_request_bank`) in a context every command runs in. The settings
    root is asserted equal to the pinned root, so `get_settings().memory_path` answers the pin through a mid-command bank
    switch.
- **Cross-check, not authority.** `GET /healthz` (1 s, no proxy, `memoryRoot` compared after `realpath`) gives one of:
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
    mismatch, 4 demo bank, 5 sandbox denied (also a permission denial during bootstrap), 70 internal or bootstrap.
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
  - `get <entity>`: `cicada_recall_detail`'s page, verbatim, with `data: {entity_id, type, status, from, count,
    total_lines}`.
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
- **Not yet built:** the release launcher (`~/.cicada/bin/cicada`) and its end-to-end test, the Settings button, the
  skill's generated CLI block, and the overhead and latency measurement. The full slice and its later units are in the
  G180 row.
