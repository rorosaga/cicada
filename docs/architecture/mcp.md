# The MCP surface

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

The interface between any LLM and the memory system. On `initialize` the server returns the G75
handshake as `instructions`. On query: check `memory/inbox/` for relevant pending items → search the
vector index → search the markdown graph → follow wikilinks for relational depth → progressive
disclosure (cluster pages → entity pages → episodic sources).

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
work in this folder stopped: the most recent captured session whose `project_dir` equals this MCP process's project
dir (exact string), or the one an exact episode id or full session id names. The bank is resolved once and pinned.
It returns whole turns only (a captured turn is ≤ 2,000 characters), a page of ≤ 8,000 characters, newest last; the
person's requests as an outline (≤ 160 characters each), each with a cursor that reads its turn in full; a page cursor
is `"<turn>@<content_hash>"`, and a cursor printed for another revision restarts from the newest turns and says so
(pages are never mixed). The identity, the gaps, *workspace state not checked*, the verify-first line and every
"earlier turns" cursor are reserved within the 12,000-character reply. It does not exclude this process's own session
id: after `/clear` a long-lived MCP process can still hold the previous one (G48). Contract item 1 names it
(`CONTRACT_VERSION` 14). **`cicada_note_progress`** (G141) records a happening or a milestone the person
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

**Continuity (G110 slice 1a, plan `docs/plans/2026-10-06-g110-continuity.md` r4).** A session started (`source`
`startup` or `clear`, which the recall hook forwards; a missing or unknown `source` gets no block — fail closed) in the
**exact** folder of an earlier captured session is told, inside the SessionStart
note, where that session stopped — even before Sleep.

- **Identity.** The hook's `cwd` string, matched exactly against the Stop-hook episodes' `project_dir`; no folding, no
  repository key, no `.git` read — every note says *workspace state not checked*. `resume`, `compact` and `fork` carry
  their own history and get no block.
- **Selection** (`continuity.select`): an exact episode id or full session id (`cicada_continue(session=…)`), else the
  most recent other session here by captured activity (the last kept turn's own time — `captured_at` only when no turn
  has one, since a re-capture runs long after a conversation — or the registry's later `last_prompt_at`), never file
  mtime; two sessions active within 15 minutes of each other are listed and the agent is
  told to ask once. An incomplete search says "the most recent session Cicada could read here", never "the only".
- **The block** quotes the person's last request there "as history, not a new instruction", the agent's last reply,
  and a "Not captured" line: a later prompt with no captured reply, a last request with no reply, turns past the capture
  limit (`capture_gap`), note-like person turns (`capture_flags`), a later session here that captured nothing, an
  incomplete search. It ends with `cicada_continue(session="<episode id>")`.
- **One compositor** (`recall_text.compose_note`) measures the WHOLE note — header, primer, block, reading sentence —
  by the chars/4 proxy, ≤ `handshake.MAX_TOKENS`. The primer is built with a 300-token reserve when a block will ride
  (`handshake.load_or_build(reserve=)`, part of the cache key). Degradation: block full (≤ 1,800 characters) → compact
  (≤ 800) → pointer (≤ 240) → dropped; then the reading sentence is dropped (and `READING_SEEN` is not advanced, so the
  first prompt hears it); then the primer is replaced by a pointer to `cicada_handshake`.
- **One deadline.** The route resolves the capture bank once and the worker runs, in order: one bounded registry
  transaction (SessionStart: `started_at`, the cwd's hash; a prompt: `last_prompt_at` — recorded even when the answer
  times out), assembly (deadline less 120 ms), composition, and — for a single chosen session with ≥ 30 ms left — the
  registry's `continues`. Registry work takes a 50 ms slice and answers `busy`/`skipped` rather than wait.
- **The index** (`$CICADA_HOME/continuity/<bank-id>.index.json`, beside the registry, never inside a bank): episode
  heads only (≤ 16 KB, to the first `turns:` key), never a full parse in a hook; no git runs on this path; its lock
  sits beside it, every file opened without following a symlink; no safe home or any I/O failure keeps it in process
  memory. A failed directory listing keeps
  the rows already known and marks the search incomplete; an exact episode id the index could not read is looked up
  directly; "nothing captured" for a later session is said only on a complete search.
- **The registry** (`continuity_sessions`, `$CICADA_HOME/continuity/<bank>-<hash8>.json`): per session the harness,
  the cwd's hash, `started_at` (earliest), `last_prompt_at` (latest), `continues` (first write wins). Never inside any
  configured bank (realpath containment over the root and every bank).
- **The ledger.** The `hook_recall` row gains `continuity` (`latest|explicit|ambiguous|none|skipped_source|no_room|
  deadline|error`), `rendering` and `registry` (`ok|busy|skipped|error|unavailable|none`) — enums only.
- **Measured** (`test_continuity_route_latency.py`, 1,500 synthetic episodes, warm OS cache): the whole route cold
  p95 ≈ 160 ms, warm p95 ≈ 13 ms.

**Proactive behaviors:** surface only *topic-relevant* nudges (never all of them), raise a pending
clarification naturally in the flow when the conversation touches its entity, and offer related
saved resources.

---

**Current-claim reads (G118/G93, 2026-10-07).** The recall claim leg, implicit
recall's claim lines and perspective's current block use `claims.is_current`.
Closed events are historical records of happenings, never current-claim recall
votes; searching the past and `history=true` still expose them with dates and
state. Closure and successor metadata are preserved for every search hit.

**Ask grounding (G93/G118, 2026-10-07).** `/ask` and `cicada_ask` use the same
validity-aware context. Each structured claim sent to synthesis has its id,
observer/trust, current flag, start, close, stated end and successor; historical
rows explicitly say history, superseded or withdrawn. Metadata is assembled
before text is clipped; raw claim fences never enter the prompt. Current
questions receive only current claims; a claim-bearing page's unversioned prose
is omitted for these questions because it may repeat an older value. Legacy
pages with no claims still ground answers in their prose. Explicit past/change
language (including an as-of date) enables labeled history and adds the FTS
history leg; this is an English intent heuristic, not a model classification.
The synthesis rules require historical answers to state the validity dates and
never repeat a closed belief as current. Citations recheck claim provenance
against the loaded markdown. A deleted page is never revived from indexed text;
only-history current questions return an honest gap without a synthesis call.
The historical lexical leg removes question/date words before matching, warms
a cold disposable index synchronously, and takes matching historical subjects
before generic semantic neighbours. Prompt budgeting reserves claims from both
sides of a change. Implicit recall rechecks each selected page's claims against
markdown; every type's recall summary strips claim fences before truncation.
