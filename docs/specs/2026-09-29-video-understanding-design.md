# Video understanding: a queue, a selection, and honest states

Status: design, 2026-09-29, **revised the same day after a code review** (§12 lists what changed and
what was disputed). Not committed. Backlog rows to be filed at the next free `G` ids (see §11); it
touches **G22** (video entities and the watch skill), **G140** (the watch record) and **Track V**
(in-app video) and moves none of their rulings without saying so.

How it was made: one research pass (the claude-video skill, YouTube transcript routes, Gemini's
native YouTube-URL analysis, thumbnails and metadata, the cost of watching) plus a read of the
code at `dev` @ `2155940`: `api/services/watch_record.py`, `video_urls.py`, `media_ingestor.py`
(`_enrich_youtube`, `_enrich_oembed`, `_media_entity_id`, `url_hash`), `mcp/server.py`,
`api/services/mcp_tools.py` (`record_watch`), `api/remote/{catalog,tools,runtime}.py`,
`api/services/agent_engine.py`, `api/services/handshake.py`, `api/services/skill_catalog.py`,
`api/data/recommended_skills.json`, `api/routers/episodes.py`, `Views/Feed/*`,
`Views/Common/MediaPreview.swift`, `docs/design/DESIGN_RULES.md`. **Nothing was built and nothing was
measured on a live bank.** §10 separates what was read in code from what came from a vendor page or a
single search result. App paths are relative to `app/CicadaApp/Sources/CicadaApp/`.

**Privacy.** Every title, channel and name below is demo-bank fiction (`Helios Labs`, `Lantern`,
`example.com`). Nothing comes from a real bank.

---

## 1. Context

The owner, 2026-09-29:

> "watching the videos might be expensive too, even youtube videos. So using skills like
> claude-video might allow us to do this but maybe we should have a queue and ask the user to run a
> separate consolidation with selection (showing thumbnails), of what videos to consolidate. By
> default we can always get whatever info from metadata or also have a transcript only. But then
> when looking at the videos consolidated show wether it was seen by an agent or just transcript
> consolidate or both or neither. And in the app i can enable to actually watch the video which
> would put that "watch" in queue, same with "transcript in queue"."

Three requirements are in there:

1. **A queue, and a separate run with a selection.** Watching is expensive, so it never happens as a
   side effect. The person picks which videos, sees thumbnails, and starts the run.
2. **Two levels above metadata.** Metadata is the default. *Transcript only* is the cheap step up.
   *Watching* is the expensive one. Each is requested per video, from the app.
3. **An honest state per video.** Seen by an agent, transcript only, both, or neither.

### What exists (read in code)

- **Classification and playback.** `video_urls.resolve` classifies a URL with no network and derives
  the provider's own player URL from the id. The app plays it in `MediaPreview`. No stream is ever
  derived (Track V's rail).
- **Metadata.** `_enrich_youtube` calls YouTube's oEmbed and keeps `title`, `author_name` (channel)
  and `thumbnail_url`; **no duration, no description, no chapters**. Vimeo, TikTok and Loom go through
  `_enrich_oembed`, which also keeps `duration_s`, the description and chapters parsed from it.
  `/sources` already serves `thumbnail`, `durationS` and `provider` on each `MediaFeedItem`.
- **Identity.** A saved page's id is `media-<slugified title>` (`_media_entity_id`); the URL hash is
  added only when a long title is truncated, so two saved videos with the same title, or the same
  fallback title, share one entity id. The one identity that never collides is the **url-index key**,
  `media_ingestor.url_hash(url)` (over `normalize_url`), which `watch_record.resolve` already uses.
  The app's `MediaFeedItem.id` is `mediaEntityId|url` for exactly this reason.
- **The watch record.** `cicada_record_watch(url, summary, excerpts=[{t, quote}], chapters?)` writes
  one episode (`assistant:` summary ≤ 1,500 characters, ≤ 12 `video [m:ss]:` quotes ≤ 240) and one
  `describes` claim on the media page whose evidence carries an `assistant` span for the summary and
  `media` spans for the quotes. The module's standing ruling: **Cicada never downloads, watches or
  transcribes a video and never keeps a transcript** (G22, R5 D3).
- **What `record_watch` does while Sleep runs (stdio).** It checks only the demo guard. When
  `ctx.sleep_running()` it **still writes** the episode and the claim and skips only
  `agent_commits.commit_write`, leaving the pages dirty for the cycle's sweep (the same "stdio write
  mid-cycle" path `mcp_tools.py` uses elsewhere). Only the **remote** runtime refuses a write tool
  while Sleep runs (`runtime.py`, R-R27 `BUSY_TEXT`, for tools in `catalog.WRITE_TOOLS`). The backlog
  tools are the ones that refuse on stdio. This spec does not change `record_watch` (§4.3).
- **The skill.** `api/data/recommended_skills.json` already recommends the `watch` skill
  (`bradautomates/claude-video`, pinned at v0.2.0) and lists `ffmpeg` and `yt-dlp` under `needs`,
  with a `terms` block (summary: "It downloads videos with yt-dlp. YouTube's terms don't allow
  downloading or automated access without YouTube's permission.", plus a link and `safeUses`) and a
  `cicadaNote`, both already rendered by the Skills page and the consent sheet.
- **Cicada's own engine cannot do this.** `agent_engine.py` spawns `claude -p` with `--safe-mode`
  (no skills, no plugins, no hooks, no MCP) so a Sleep engine can never write back into memory. A
  Cicada-spawned engine therefore cannot load claude-video, a browser skill or Cicada's own MCP tools.

### The gap

Nothing says **how** a watch happened (frames, transcript or both). There is no queue, no way to ask
for one from the app, no "neither" state to show, and no size signal before spending anything. The
person cannot see which of their 40 saved videos an agent has actually read.

---

## 2. Goals and non-goals

**Goals**

- G-a. Every saved video shows one honest state, derived, never guessed: *metadata only*,
  *transcript read*, *watched by an agent*, *watched and transcript*, or, when the agent gave no
  method, *recorded, method not given* (the owner named four; the fifth exists so a record with an
  unknown method is never dressed up as one of them).
- G-b. From the app the person can put a video in the queue as **transcript** or **watch**, remove
  it, and see it move: queued, picked up by an agent, recorded, or failed with a reason.
- G-c. A separate, explicit **run** over a selection with thumbnails. Never from Sleep, never
  scheduled, never automatic.
- G-d. The run is started by handing a batch to an agent the person already uses. Progress is
  counted from records that landed, so it is true even when the agent's own narration is not.
- G-e. Every rail holds: no download, no derived stream, no transcript kept, no scraping, no
  undocumented endpoint, in Cicada's own process.
- G-f. Honest about size: a word and a minute count, no dollar figure (§6).
- G-g. Every sentence the app writes about a video is something Cicada knows (a lease is "picked up",
  not "being watched"; `processed_by` is "read by Sleep", not "in your graph").

**Non-goals**

- N-a. Cicada does not fetch captions, audio, frames or streams, ever, in slices 1–4.
- N-b. Cicada stores no transcript. Only the summary and ≤ 12 cited quotes (G22 / R5 D3 stand).
- N-c. No watching from Sleep, and nothing video-related in the nightly tail. Sleep reads a watch
  record like any other episode.
- N-d. No second control on the Sleep page. G125 R10 (one Consolidate) is untouched (§4.7).
- N-e. No auto-queueing by default. Saving a video queues nothing (open question Q3).
- N-f. Not the general "fast scraper vs. agent with a browser" question. That is a sibling spec.
  Here a browser method is **not offered for YouTube at all** (§4.8, §5, Q8).

---

## 3. Rulings this spec proposes

| Id | Ruling | Why |
|---|---|---|
| R-VU1 | **State is about the event, not the belief.** A video is *watched* when a watch **episode** with a basis exists. A withdrawn `describes` claim does not un-watch it. | The agent did watch. What was withdrawn is a claim. The belief layer keeps its own rule (a `describes` claim with a `media` span); the two differ in two cases (§9). |
| R-VU2 | **`basis` is the agent's word.** Cicada cannot verify it, so the app says "an agent recorded that it watched", never "Cicada watched". **A record with no basis is its own state, never `watched`.** | Cicada sees no frames and reads no captions, and today's records could as well have come from captions. Provenance never claims more than it holds. |
| R-VU3 | **The queue holds user requests only, and lives outside the bank.** `$CICADA_HOME/video_queue/<bank>.json`, never an entity, never decays, never committed. | A request is an intent, not a memory. A dirty bank file is swept into the next `git add -A` writer's commit under the wrong author (the G85-class smear); committing every click is noise. |
| R-VU4 | **The run control lives in the Feed's Videos view.** The Sleep page only *reads* the queue and links to it. | G125 R10 gives the Sleep page one trigger; no click on art changes what the machine does. |
| R-VU5 | **A run is always a user trigger and never on a schedule.** | Same shape as TODO ruling 4: a scheduled path never spends plan quota. |
| R-VU6 | **Sizes are words and minutes.** "Light", "Medium", "Heavy", plus total minutes. No dollars, no tokens. | Ruling 12 shows prices on the Sleep page's Details and engine menu only; this is a different surface and a much rougher estimate. |
| R-VU7 | **Vocabulary.** *Watch* and *Read* are what an agent does; *Sleep* is consolidation. A video run never says "consolidate". | The owner's word "consolidate" already means Sleep. A watch record becomes an ordinary episode that Sleep reads later, so two steps are real (§4.1). |
| R-VU8 | **A video's identity is its url-index key (`videoKey`), never its media entity id.** The queue, the state map and every route key on it; the wire also carries `mediaEntityId` and `url` for joining to `MediaFeedItem`. | Entity ids collide across same-titled videos (§1). Queueing one video must not queue its namesake. |
| R-VU9 | **Every sentence states what Cicada knows.** A claim on a queue entry is "picked up by <agent>", not progress. "Read by Sleep" derives from `processed_by == sleep`. Nothing promises a cycle will run. | The lease is only a lease; `processed` can be flipped by an agent; the manual schedule mode has no next cycle. |
| R-VU10 | **Cicada's default prompt never steers an agent into the person's logged-in browser for a video; when the person turns on the single reading permission, the prompt carries that permission as an instruction (their consent, R-RW8), never as a promise. *Amended 2026-09-30 (§13, H1).*** | The first form, "never", made the permission page inert for video: a `needs_login` video was a dead end. The person's explicit switch is the consent; the default stays as reviewed. |
| R-VU11 | **Provider-neutral copy.** Every string a video surface, the prompt, a tool description, the contract clause or the bridge line writes describes the step ("a model that takes the link", "the reader reads"), and never names a provider or model as the one that does the job. Names appear only as data: a harness label an agent sent, a skill the person picked. A test enforces it. | Owner 2026-09-30: "Ollama and the rest are literally just providers. So don't assume or make the choice for the user." |
| R-VU12 | **No batch cap, anywhere.** A hand-off accepts every selected video; a claim leases at most 10 per call and the prompt loops. The queue file keeps a safety ceiling of 2,000 rows with a sentence. | Owner 2026-09-29 (the drain's reasoning); "Select all 13 not read yet" must not break at 200 on a bank with a few hundred saved videos. |
| R-VU13 | **No site list for video.** Any saved item the Feed shows as a video can be queued, whatever its host. When an agent cannot get a video (a login wall, private, blocked) it hands it back with a `code`, and the app **surfaces** it (a `needs_login` row); nothing pre-filters by host. Whether an agent may use the person's browser at all is the reading plan's single permission. | Owner 2026-09-30: "limiting the amount of sites makes no sense … we will never know which sites this will happen." |

R-VU3 is reversible: the file's contents would move into a bank folder unchanged if the owner prefers
it (Q2).

---

## 4. The design

### 4.1 Two steps, named apart

```
 saved video ──▶ [ queue ] ──▶ WATCH RUN (person starts it; an agent does it) ──▶ watch episode
                                                                                    │ processed: false
                                           Sleep reads it like any episode  ◀──────┘
```

- **Watch run.** Produces a record: one episode plus one `describes` claim (the shipped shape,
  extended with `basis`). It ends when the record is written.
- **Sleep.** Reads that episode in Stage 1 like any other. Its `assistant:` line is agent evidence,
  its `video [m:ss]:` lines are `media` evidence and never the person's words (existing rules).

Because there are two steps, a video has two facts the app can state truthfully: *how it was read*
(basis) and *whether Sleep has read that record* (`processed_by == sleep`). Both are cheap and
both are derived. The summary is **already on the media page** as a `describes` claim the moment the
record lands, so the app never says the record is or is not "in your graph".

### 4.2 The states (data model)

**On the watch episode's frontmatter (new, both optional):**

| Key | Values | Set by |
|---|---|---|
| `watch_basis` | `transcript` \| `frames` \| `both` | `cicada_record_watch(basis=)`, the agent's word |
| `watch_engine` | `captions` \| `video_link` \| `local_frames` \| `speech_to_text` \| `browser` \| `other` | `cicada_record_watch(engine=)` |

A closed set for `engine`, not free text: an open label invites junk, and `other` is the escape.
Both go through the existing scrub and length rules; an unknown value is dropped and the record is
still written ("provenance never blocks memory"). `harness` is already on the episode
(`ctx.session_frontmatter()`), which is where "who recorded it" comes from (§4.6).

**Derived per video** by one pure function, `api/services/video_state.py`, from the episodes whose
`source == "video-watch"` and whose `media_entity_id` **and url** match the video (read through the
`bank_index` frontmatter cache, so no page is parsed). **The rule is a set union.** Each episode
contributes a set of facts:

| Episode's `watch_basis` | Contributes |
|---|---|
| `transcript` | `T` |
| `frames` | `F` |
| `both` | `T`, `F` |
| absent (legacy, or an agent that omitted it) or any unrecognised value | `U` |

Over all the video's episodes, take the union `S`:

| State (wire) | When | Label the app shows |
|---|---|---|
| `none` | `S` is empty | Metadata only |
| `transcript` | `T` in `S`, `F` not in `S` (a `U` beside it changes nothing) | Transcript read |
| `watched` | `F` in `S`, `T` not in `S` (a `U` beside it changes nothing) | Watched by an agent |
| `watched_and_transcript` | both `T` and `F` in `S` | Watched, with transcript |
| `recorded` | `S == {U}` | Recorded, method not given |

The state is named `watched_and_transcript`, not `both`, so it is not confused with the `both` basis
value. The cases the review found — a legacy episode beside a `transcript` one, an unrecognised
value, an agent that omits `basis` — are all rows of this table and are pinned in the fixture
`api/tests/fixtures/video_state.json` (A1, A6).

- **Legacy.** A watch episode written before this change has no basis. It reads `recorded`, and the
  row's help says "The agent didn't say how it read this." (final review 2026-09-30: a basis-less record can still be made today) No backfill, no rewrite (the house
  rule). This is a change from the first draft, which read it as `watched`: most records today were
  made by an agent that was never asked for a method, and could as well be a caption read.
- **Same content, new basis.** `_write_episode` dedups on the content hash and returns the existing
  episode. If a second call arrives with the same body and a different basis, the episode's
  frontmatter takes the **union** (`transcript` + `frames` becomes `both`; `U` is replaced by a stated
  basis) in place. Only frontmatter changes, the hash is unchanged and `processed` does not flip: the
  same move the folder authorship re-derive already makes.
- **Different content.** A second episode. The state is the union across episodes.
- **Second axis.** `recorded`: the newest watch episode's day, its harness label (the episode's own
  `harness` frontmatter), and `readBySleep` (`processed_by == sleep`). The card says "Sleep hasn't
  read this yet" when `processed` is false, "Read by Sleep" when `processed_by == sleep`, and **says
  nothing** when an agent flipped `processed` (Cicada cannot tell what that meant).
- **Quote fidelity, derived.** `approximate` when the engine is `video_link` (a model reading the link
  directly; the first draft named a provider here, P7), `other` or **absent**, else `verbatim`. A model's
  transcript is output, not captions, so its timestamps and wording can drift (research; **assumed** for
  `other`). **Every legacy record therefore shows the caveat**
  (an absent engine reads approximate); that is the honest reading of "we were not told".
  The Reader's chip for a `media` span says "From the video · approximate wording" when so.
  Provenance wire additions (this slice, V1): `/episodes/{id}/text` gains a `watch` object
  (`{basis?, engine?, fidelity}`, only on a watch episode) and each `media` turn gains `fidelity`;
  `/episodes/{id}/citations` rows for a `media` span gain `fidelity`; the Swift `EvidenceDecode` types
  gain the same keys. The `extra` of both ETags folds a new **`VIDEO_SHAPE`** tag (beside
  `AUTHOR_SHAPE`, which is untouched), so a running app's in-memory `ProvenanceCache` does not 304
  stale after a backend restart.

**Not stored anywhere:** the state, the fidelity, any cost estimate. `GET /videos/state` derives them
per request.

### 4.3 The queue

A person's request, kept out of the bank (R-VU3). **Keyed by `videoKey`** (R-VU8):

```
$CICADA_HOME/video_queue/<bank>.json      atomic write (tmp + rename), one file lock
{
  "version": 1,
  "items": {
    "<videoKey: url_hash of the saved link>": {
      "mediaEntityId": "media-lantern-on-a-pi-sqlite-vec-in-five-minutes",
      "url": "https://youtu.be/…",
      "want": "transcript" | "watch",
      "requested_at": "2026-09-29T14:02:11Z",
      "state": "queued" | "claimed" | "failed",
      "batch": "b_7f3",
      "claimed_by": "claude-code", "claimed_at": "…", "lease_until": "…", "session": "ses_…",
      "attempts": 1,
      "failed": { "reason": "no captions on this video", "at": "…" }
    }
  },
  "batches": { "b_7f3": { "created_at": "…", "method": "auto",
                          "keys": ["<videoKey>", "…"], "done": [], "failed": [] } }
}
```

- **Who writes.** The backend (the app's requests) and every stdio MCP process, so one `fcntl` lock,
  the same "one writer, several processes" care `backlog.py` takes with its exclusive create.
- **A video is keyed by its `videoKey`.** It must resolve through the url index to an existing
  `media` page (`watch_record.resolve`). The item stores `mediaEntityId` and `url` so the app joins to
  `MediaFeedItem` by `mediaEntityId|url` and a namesake is never touched. At most 2,000 entries: a
  file-safety ceiling with a sentence, never a batch cap (§13, D-2).
- **`want: watch` implies a transcript.** The queue never holds both for one video; asking for a
  watch replaces a transcript request.
- **Every free-text field is scrubbed and capped.** `failed.reason` and a release reason (agents,
  local and remote, write them) go through `episode_scrub` under a new writer name, `video_queue`,
  are cut to one line of ≤ 200 characters, and are rendered as plain text, never markup. A test
  (like `test_episode_writers_scrub.py`) fails for a queue writer that skips it.
- **What satisfies a request (the queue entry only; the *state* is §4.2's and is never inflated).**
  When `record_watch` succeeds for a video that has a queue entry:

  | Recorded `basis` | `transcript` request | `watch` request |
  |---|---|---|
  | `transcript` | done | **stays claimed**; the reply tells the agent it recorded a transcript only |
  | `frames` or `both` | done | done |
  | omitted / unknown | done **only if the calling session holds the lease**; the state stays `recorded` | same |

  An omitted basis closes the entry so the queue never jams on a careless or older agent, but the run
  card shows that row as **"Recorded, method not given"**, never as "Transcript" or "Watched", and the
  reply asks the agent to pass `basis` next time. A stated `frames` record satisfying a transcript
  request is deliberate: an agent that watched has read at least a transcript. Removal of the entry
  is a write to the queue file only, so it happens **whether or not the bank commit ran** (see the
  Sleep paragraph below).
- **Lifecycle.**
  1. `queued`: the person added it.
  2. `claimed`: an agent called `cicada_video_claim`. A **lease** of 45 minutes (**assumption**)
     stops two agents taking the same video. A lapsed lease first sweeps: a watch episode for that
     video newer than `requested_at` that satisfies the request (table above, session ignored) closes
     the entry as done. Otherwise it returns to `queued` with `attempts + 1`; at 3 attempts it becomes
     `failed` with a reason **derived from what exists** ("recorded as a transcript only" when a
     non-satisfying record is there, else "no agent recorded it").
  3. Done: as above. The batch's `done` list gains the key in the same call, and a read-time sweep
     prunes any entry whose satisfying episode is newer than `requested_at` (belt and braces).
  4. `failed`: the agent released it with a reason. It stays visible with the sentence; Retry puts it
     back to `queued` and Remove deletes it.
- **While Sleep runs: the real behaviour, stated, not a new rule.**
  - *stdio (local MCP).* `record_watch` **is not refused**. It writes the episode and claim and
    **skips the commit**, leaving the pages dirty for the cycle's sweep, exactly as today. The queue
    entry is removed when the record is written (a queue-file write outside the bank). Nothing about
    this slice changes that path.
  - *remote.* `cicada_record_watch` and `cicada_video_claim` are in `catalog.WRITE_TOOLS`, so the
    runtime answers **`BUSY_TEXT`** while a cycle runs and nothing is written. The agent relays it;
    the item stays `claimed`; the lease covers the retry.
  - *`cicada_video_claim` on stdio* touches only the queue file (outside the bank), so it is **not**
    refused during a cycle, but it is refused in the demo bank (below).
  Tests: B6a (stdio: written, uncommitted, entry removed) and B6b (remote: busy text, entry stays
  claimed).
- **Demo bank.** Queueing from the app works (nothing in the bank changes; the file is
  `video_queue/demo.json`). `cicada_video_claim` and `record_watch` are refused by the demo guard
  (stdio `_demo_refusal`; remote `demo_guard`), so a demo queue is a picture of the flow and no agent
  can work it (§4.7E).

### 4.4 Metadata: what is known before anything runs

| Field | Source today | Change |
|---|---|---|
| Title, channel | oEmbed (kept) | none |
| **Thumbnail** | oEmbed's `thumbnail_url`, already stored and already drawn by `PictureStore` (`MediaFeedItem.thumbnail`) | **Use the stored one.** Where a page has none, show the play-glyph tile. **Not** derived from the id (see below) |
| Duration | Vimeo/Loom/TikTok provider (`MediaFeedItem.durationS`); **not YouTube** | (a) agent-reported: `record_watch(duration=)` fills `media.duration_s` only when empty, like `chapters`; (b) optional person-supplied key, slice 5, **kept outside the bank** |
| Description, chapters (YouTube) | not kept | only with the same optional key, slice 5, outside the bank |
| "Captions exist" | unknown | only with the key (`caption` flag). Otherwise **shown as nothing**, never guessed |

**Why not derive a thumbnail URL from the id.** The research suggested `i.ytimg.com/vi/<id>/…`. The
embed URL is derived because the embed is the provider's documented interface; the `ytimg` path
pattern is widely used but undocumented, and oEmbed already handed us a thumbnail for every page
saved through the normal path. A page without one is rare and gets a placeholder. This departs from
the research and the reason is the rail's own spirit.

**Consequence, honestly stated.** Before the first run a YouTube video's length is unknown. The size
estimate for a watch is therefore *Heavy or unknown* until a key or a previous record supplies it (§6).
There is no batch cap (§4.8): the Size line says "Heavy (length unknown)" until then, so the person
sees it before copying.

### 4.5 The MCP surface

**`cicada_record_watch` gains three optional arguments** (R12: the tool schema and the primer must
agree, and the primer's clause is updated in the same change). The argument path has **five
hand-copied sites**, all of which change together, and a lambda that silently drops an argument it
does not name:

1. the stdio schema, `mcp/server.py` (the `cicada_record_watch` entry);
2. the stdio dispatch, `mcp/server.py` (the `call_tool` branch);
3. the handler, `mcp/server.py` `handle_record_watch` → `mcp_tools.record_watch` (signature and the
   `watch_record.record` call);
4. the remote schema, `api/remote/tools.py`;
5. the remote dispatch lambda, `api/remote/runtime.py` (`_DISPATCH`), which today passes only
   `excerpts` and `chapters` and **would drop the new arguments** unless it names them.

| Argument | Type | Meaning |
|---|---|---|
| `basis` | `transcript` \| `frames` \| `both` | how the record was made. Asked for in the primer and the bridge line; omitted reads `recorded`, "method not given" |
| `engine` | closed set above | which path |
| `duration` | `m:ss`, `h:mm:ss` or seconds | the video's length, stored only when the page has none, capped at `MAX_T_S` |

**Two new tools, split by scope** (`catalog.TOOL_SCOPE` maps each tool to exactly one scope; the read
and write sets are disjoint; a tool cannot be both):

| Tool | Scope | Does |
|---|---|---|
| `cicada_video_queue(limit?)` | `read` | Lists the queue: per item the link, title, channel, what is wanted, and its state. Never a person's own words, so it needs no `sources` scope. In `catalog.READ_TOOLS`, so it carries `readOnlyHint: true`. |
| `cicada_video_claim(limit?, release?: [{url, code?, reason?}])` | `record` | With no `release`: leases up to `limit` (default 5, max 10) `queued` items to this session and returns them. With `release`: hands items back with a reason (scrubbed, ≤ 200 characters). In `catalog.WRITE_TOOLS`, so the remote runtime refuses it with the busy text during a cycle and the demo text in a demo bank, and it is fenced and capped like every write tool. |

**Every place these two tools touch** (slice V2 lists the same set):

- `mcp/server.py`: both schemas and both dispatch branches;
- `api/services/mcp_tools.py`: both handlers (`video_queue`, `video_claim`); the claim handler adds
  `_demo_refusal`;
- `api/remote/catalog.py`: `TOOL_SCOPE` (`cicada_video_queue: "read"`, `cicada_video_claim:
  "record"`), `READ_TOOLS`, `WRITE_TOOLS`;
- `api/remote/tools.py`: both remote schemas, `read_only_hint` derived from the sets;
- `api/remote/runtime.py`: `_DISPATCH` for both;
- the tests that pin the sets: `test_remote_tools.py` (stdio tools == `TOOL_SCOPE` plus
  `NEVER_REMOTE`; the read-only annotation), `test_demo_capture.py` (its write-tool map must equal
  `catalog.WRITE_TOOLS`), and `test_mcp_tools_context`.

**Contract and skills.**

- The handshake has **two contract versions**: `CONTRACT_VERSION` (local, now 8, a **static**
  `_CONTRACT` string) and `REMOTE_CONTRACT_VERSION` (now 5, built by `_remote_contract` per scope
  set). Both take the next free number at implementation (branches have collided on this before).
- Contract item 3 gains one clause: "the person's video queue: `cicada_video_claim` takes what they
  asked you to read or watch (`cicada_video_queue` lists it); record each with
  `cicada_record_watch(..., basis=)`." **The local `_CONTRACT` is static and always names the tools**
  (a stdio server exposes them all, so R12 holds); **only the remote variant names a tool "only where
  it exists"**: `cicada_video_queue` with `read`, `cicada_video_claim` with `record`.
- **R12 tests.** A case per remote scope set asserting that every argument the primer names for
  `cicada_record_watch`, `cicada_video_queue` and `cicada_video_claim` (`basis`, `engine`, `duration`,
  `limit`, `release`) exists in that scope set's schema, and that a scope set without `record` names
  neither `basis` nor `cicada_video_claim`.
- **The video bridge line** (`skill_catalog.BRIDGE_TEXT["video"]`) changes from
  `cicada_record_watch(url, summary, excerpts)` to name `basis`: "...record it with
  `cicada_record_watch(url, summary, excerpts, basis)`, `basis` being `transcript`, `frames` or
  `both`, whichever you actually used..." (its fingerprint test moves with it). This replaces the first
  draft's "unchanged" ruling, which left the main agent path never asking for a method.
- **`cicada` and `cicada-librarian` SKILL.md** point at the generated primer text rather than
  restating it (the standing one-source rule). The librarian's `/watch` line changes in V4 (§4.9).
- **Recall (G149).** Deliberately **not** extended: the hook note is ≤ 400 tokens and names pages the
  prompt names. A "you have 4 videos queued" line would spend that budget on something the person
  did not ask about.

### 4.6 REST (not Store domains)

| Route | Purpose |
|---|---|
| `GET /videos/state` | `{ items: [{key, mediaEntityId, url, state, want?, queueState?, basis?, engine?, episodeId?, recordedDay?, recordedBy?, readBySleep?, fidelity?}], queue: {queued, claimed, failed, batch?: {total, done, claimed, failed}}, shape }`, one item per saved **video** page (`VideoRef.resolve`). Thumbnail, duration, title and channel are **not** repeated: the app joins by `mediaEntityId|url` to the `MediaFeedItem` it already holds. |
| `PUT /videos/queue/{key}` | `{want}` add or change one entry |
| `DELETE /videos/queue/{key}` | remove |
| `POST /videos/queue/{key}/retry` | failed → queued |
| `POST /videos/run/handoff` | `{items: [{key, want}], method}` → upserts each into the queue, stamps one batch (replacing the active one), leases nothing, applies no batch cap (§4.8), returns the prompt (§4.8) |

- **The picker's wants are client state until Copy for an agent.** A menu change in the picker writes
  nothing. The handoff carries `[{key, want}]` and is the one place a selection reaches the queue file.
  A per-video **Queue transcript / Queue watch** button in a detail column (§4.7A) is a `PUT` at once.
  Deselecting an already-queued video in the picker leaves it queued; only Remove (a row menu) or the
  detail column's Remove deletes it.
- **`recordedBy`** is the episode's own `harness` frontmatter, so the read stays engine-free over
  `bank_index` and adds no `git log` and no `git_head` to the ETag. (A model, where the turn join
  exists, is read where the card already reads it: the Reader's provenance.)
- **The block's first quote** is not on the wire. The detail block fetches `/episodes/{episodeId}/text`
  through `ProvenanceCache` when it opens and shows the first `media` turn.
- **ETag** over `entities` + `episodes` + a new `videoQueue` sync component (a stat of the queue file
  in `sync_service.components`) with `shape` in `extra`. **Ship the ETag and its client mapping
  together:** `VideoStateCache` in the app, in memory, like `ProjectsCache`; no `VersionVector` domain,
  no disk cache, empties on a bank switch. **A `VideoRefresh` set** (like `BacklogRefresh`) lists the
  components that revalidate it on a version event: `videoQueue`, `episodes`, `entities`, `bank`. This
  is required: a claim ("Picked up by Claude Code") writes only the queue file, which moves only
  `videoQueue`, and an unmapped component refreshes nothing. A sync test asserts that a queue write
  moves `videoQueue` and `version`. `videoQueue` does **not** join `_state.md`'s input digest.
- **Auth.** Bearer, like every route. Nothing here is under `/capture/` or `/sources/`, so the demo
  gate does not apply, and the queue never touches the bank, so no 409 while Sleep runs (a stale
  read cannot corrupt anything).
- **Idempotent.** Putting the same `want` twice is a no-op.

### 4.7 App surfaces

All against `docs/design/DESIGN_RULES.md`; rule ids cited in brackets.

#### A. A video's detail column (Feed, and the entity card's Media block)

A new block between the player and "Why it's saved": **What Cicada has from this video**. It is one
group in the existing `bgFocus` card, not a card of its own [DR-37].

```
┌ Video · youtube.com ──────────────────────── ⧉  ⌘  × ┐
│ Lantern on a Pi: sqlite-vec in five minutes            │
│ ┌────────────────────────────────────────────────┐    │
│ │                   ▶  player                    │    │
│ └────────────────────────────────────────────────┘    │
│                                                        │
│ WHAT CICADA HAS FROM THIS VIDEO                        │
│ [Transcript read]  ✱ Claude Code · Sep 26              │
│ Sleep hasn't read this yet. Wording is approximate     │
│ (a model's reading, not captions).                     │
│ "A stored embedding costs one lookup, not one model    │
│  call."  12:34                                         │
│                                                        │
│ [ Queue watch ]        Open the record ›               │
│                                                        │
│ WHY IT'S SAVED   …                                     │
└────────────────────────────────────────────────────────┘
```

- **State** is a `Tag` [DR-44] with no colour dot; the five labels are in §4.2. A queued video shows
  the state and, on the next line, the request: "In the queue to be watched · Remove" with Remove a
  `TextButton`.
- **Attribution line** is mark, app, day [DR-54], never an id; the app comes from `recordedBy`. "Claude
  Code" wears its real mark [DR-52]. The model appears only where the turn join exists (existing
  rule); otherwise the line says the app did not share it.
- **Actions** are `NeutralButton`s [DR-40], no primary here. Rules:
  - `none`: **Queue transcript** and **Queue watch**.
  - `transcript`: **Queue watch** only.
  - `watched`: **Queue transcript** only, help "for exact wording".
  - `watched_and_transcript`: none.
  - `recorded`: **Queue transcript** and **Queue watch** (the method is unknown, so either can add
    something).
  - a `watch` request in the queue disables Queue transcript, help "Watching includes the transcript".
- **The Sleep line** is derived only from `readBySleep` / `processed`: "Read by Sleep" · "Sleep hasn't
  read this yet" · nothing when an agent flipped `processed` (§4.2). It never says "in your graph".
- **The quote** shown is the record's first excerpt in the quote face (fetched as §4.6 says), opening
  the Reader on that span [DR-31]. **Open the record** opens the watch episode in the Reader.
- **Failed:** "An agent couldn't do this one: <reason>" with **Try again** and **Remove**.
- **Before the queue exists (slice 1)** the block shows the state and record only, no buttons.

#### B. The Feed row

Video rows keep the 56 pt role [DR-34]. When the state is not `none`, or the video is queued, one
text word sits in the age slot's line, `textTertiary`, tabular, never a dot next to the mark
[DR-48, DR-51]: "Watched", "Transcript", "Both", "Recorded", "Queued", "Picked up", "Couldn't do".

#### C. The video run: the Feed's Videos view

The selection surface is a mode of the Feed's **Videos** tab [DR-25, DR-45]. It is not a sheet and
not the Sleep page (R-VU4). A strip at the top of the list, scrolling with it like the Connected
strip, holds one `NeutralButton`: **Choose videos…**. It opens a progressive-column state [§5.3]:
the list column becomes a thumbnail picker, and the detail column is the **run card**. While the mode
is open the eyebrow's kind and sort tabs give way to the picker's own tabs (the kind is fixed at
Videos and the sort at Recent), so there are never three tab groups at once.

```
Feed · Videos · Choose · 3 selected      [Not yet read 14][Queued 4][Read 9]   ⌕
┌ picker (328) ─────────────────────┐ ┌ Run card ────────────────────────────┐
│ ☑ ┌───────┐ Lantern on a Pi:      │ │ WATCH RUN                            │
│   │ thumb │ sqlite-vec in 5 min   │ │ 3 selected · about 41 min            │
│   └───────┘ Helios Labs · 8 min   │ │                                      │
│             Metadata only         │ │  Lantern on a Pi …   Transcript ▾    │
│ ☑ ┌───────┐ Northwind rover demo  │ │  Northwind rover …   Watch ▾         │
│   │ thumb │ Northwind · length ?  │ │  Bench notes, part 2 Transcript ▾    │
│   └───────┘ Metadata only         │ │                                      │
│ ☐ ┌───────┐ Meter Sim overview    │ │ SIZE                                 │
│   │ thumb │ Leo Fischer · 22 min  │ │  2 light · 1 heavy (length unknown)  │
│   └───────┘ Transcript read       │ │                                      │
│ ☐ …                               │ │ HOW                                  │
└───────────────────────────────────┘ │  Let the agent choose ▾              │
                                      │                                      │
                                      │ Cicada sends nothing. Your agent     │
                                      │ decides where a video goes.          │
                                      │                                      │
                                      │ [ Copy for an agent ]                │
                                      └──────────────────────────────────────┘
```

- **Picker rows** are a new row role, `videoPickRow`, 64 pt with an 88 × 50 thumbnail, the checkbox,
  title (13 regular), channel · length (12 `textTertiary`, "length unknown" when so) and the state
  word. It needs an entry in the §5.5 density table [DR-34]. The thumbnail is the stored oEmbed one;
  a missing one is a neutral tile with the play glyph.
- **Tabs** are text tabs with counts [DR-45]: *Not yet read* (state `none`), *Queued*, *Read*
  (anything else, `recorded` included). Default is *Not yet read*. **DR-45's own behaviour applies:
  tapping the active tab returns to All**, so the tab group has an All state and no departure ruling
  is needed (the Feed's sort tabs needed one, R-DL13, only because a sort has no "none").
- **Nothing is pre-selected**, including on the Queued tab; selecting queued videos includes them in
  the batch.
- **Bulk affordance.** With nothing selected the run card's empty state offers "Select all <n> not
  read yet" (the *Not yet read* tab's own count) as a `TextButton`. There is no cap (owner,
  2026-09-29, §4.8): the Size line and the total watch minutes are what the person sees before
  copying (G-f).
- **Per item `Transcript ▾` / `Watch ▾`** is a small menu (Transcript, Watch, Remove from the queue).
  The default for a picked video is **Transcript**, the cheap one. Changing it is client state (§4.6).
- **Size.** Words per §6, never a price [R-VU6]. The line reads "2 light · 1 heavy (length unknown)"
  and, when lengths are known, the total minutes of the *watch* items.
- **How** is a menu with three rows, default *Let the agent choose*: *Captions or transcript only*,
  *Use Gemini on the link*. It only changes the hint line in the prompt (§4.8). It never runs
  anything. **There is no logged-in-browser row** (R-VU10, §5, Q8).
- **The leaves-your-Mac note** is a pure function, `WatchLeavesMacNote`, in the style of
  `LeavesMacNote`: with the hand-off, "Cicada gives your agent each video's link, title, channel and length, nothing more. Your agent decides where a video goes." (final review 2026-09-30: the tools do hand those over);
  with the slice-6 Gemini run, "Google reads the video with your Gemini key."
- **The one primary** [DR-40] is **Copy for an agent**. It calls `POST /videos/run/handoff`, copies the
  prompt and moves the run card to its progress state:

```
┌ Run card ────────────────────────────────────────────┐
│ WATCH RUN · started 2:14 pm                          │
│ ▰▰▰▱▱  2 of 5 recorded                               │
│                                                      │
│  ✓ Lantern on a Pi …            Transcript · Sep 29  │
│  ✓ Bench notes, part 2          Recorded, method     │
│                                 not given · Sep 29   │
│  ● Northwind rover demo         Picked up by         │
│                                 ✱ Claude Code        │
│  ○ Meter Sim overview           Waiting              │
│  ! Helios keynote               Couldn't do: no      │
│                                 captions   Try again │
│                                                      │
│ Sleep reads these the next time it runs.             │
└──────────────────────────────────────────────────────┘
```

- **The bar is `x of y recorded`.** Its numerator is the batch's `done` list, which grows only when a
  record lands. Its noun is always on it (the Sleep page's own R-A5 rule: a meter never renders
  without its noun). "Picked up" is a claim, not progress [R-VU9].
- **No spinner that outlives its cause.** A lapsed lease shows "Waiting" again, not a stuck
  "Picked up".
- **Keys.** ↑/↓ move, Space toggles the row, ⏎ on the run card's primary, Esc closes the run card,
  then leaves the mode [DR-28, DR-60]: none of them animates.
- **Empty states** [DR-50]: no saved videos ("Videos you save will show up here."); none unread
  ("Every saved video has been read or watched.").

#### D. The Sleep page reads the queue and links to it

Under **Details → What's waiting**, one list row in D's grammar, no card, no button [DR-51]:

```
WHAT'S WAITING
  Conversations   12 waiting · oldest 2 days
  Videos          4 queued · 1 picked up by an agent · 1 couldn't be done      Choose videos ›
```

- `Choose videos ›` is a `TextButton` that lands on the Feed's Videos view. It starts nothing.
- "Picked up by an agent" is derived from `claimed`, which is only a lease; the row never says "being
  watched" [R-VU9].
- While a batch is active the room's sentence tail may say "An agent has picked up 3 videos." from the
  same `GET /videos/state` `queue.batch` block. That wording, the row's place and the worm's
  behaviour belong to the sibling Sleep-page redesign; this spec fixes only the **data** it may read
  (`queued`, `claimed`, `failed`, `batch.total`, `batch.done`) and the ruling that it triggers
  nothing (R-VU4).

#### E. Settings, the Reader and the demo

- **Settings → Skills.** The `watch` card already shows a `terms` block and a `cicadaNote`. V4 edits
  their **text** only (§4.9); no new key, no new page.
- **Settings → Agents** gains nothing in slices 1–4.
- **Reader.** The `media` span chip gains "approximate wording" (§4.2), read from the provenance
  additions listed there. Nothing else changes.
- **Demo bank.** `demo_showcase._MEDIA` has exactly one saved video today. V3 adds **two more** saved
  videos (so the count line in the "Sources ingest" commit and any test that pins the media count
  **move**, and are updated in the same change) and gives the three the states `transcript` (the NASA
  video, engine `captions`), `watched_and_transcript` and `none`. `write(bank_dir, today, commit)`
  only knows a bank folder and R-VU3 keeps the queue outside it, so **the generator seeds no queue
  entry**. The queued and in-progress run card is shown by (a) an app-side fixture,
  `app/CicadaApp/Tests/fixtures/videos-state-demo.json`, pinned by an API test as `projects-demo.json`
  is, driving a Swift preview and the layout tests, and (b) the real flow: in the demo, the person's
  own click queues (§4.3) and the run card moves to Waiting, which is truthful because nothing can
  claim it. A demo bank made **before** this change is not re-populated (`POST /banks/demo` re-opens
  it as it is) and shows only the states it already has.

#### F. Copy

| Where | Text |
|---|---|
| States | Metadata only · Transcript read · Watched by an agent · Watched, with transcript · Recorded, method not given |
| Legacy help | The agent didn't say how it read this. |
| Queue buttons | Queue transcript · Queue watch · Remove from the queue · Try again |
| Queued line | In the queue to be read · In the queue to be watched · Picked up by Claude Code |
| Empty (none) | Only the title and thumbnail so far. |
| Record | Sleep hasn't read this yet. · Read by Sleep. (nothing when an agent flipped `processed`) |
| Fidelity | Wording is approximate (a model's reading, not captions). — engine `video_link` only; `other` or none: "Wording may be approximate: the agent didn't say it came from captions." |
| Size | Light · Medium · Heavy · length unknown |
| Run card | Choose videos… · Copy for an agent · Sleep reads these the next time it runs. |
| Queue line (one wording: the Feed strip, the Sleep row, and the sum the picker's Queued tab counts) | 4 queued · 1 picked up by an agent · 1 couldn't be done (a clause is omitted at zero) |
| Feed strip | Saved videos · 8 not read yet · <queue line> · Choose videos… (a plain row on `bgBase`, no card) |
| Honesty | An agent recorded that it watched this. Cicada saw no frames itself. |

### 4.8 The run: what the hand-off prompt says

`POST /videos/run/handoff` builds a plain prompt (≤ 1,200 characters, like `GET /agents/setup`),
shown before it is copied. Sketch:

```
Cicada has 5 videos waiting for you to read or watch.
1. Call cicada_video_claim until it returns nothing. Each call returns up to 10 links and
   what is wanted (a transcript, or a watch).
2. Read or watch each one with your own tools. For a transcript job, captions or a transcript are
   enough. For a watch job, use frames or a model that takes the link. Cicada does not
   download or watch videos for you.
3. Record each with cicada_record_watch(url, summary, excerpts=[{t, quote}], basis, engine,
   duration). basis is what you actually used: transcript, frames or both. A paragraph and at most
   12 short quotes, never the transcript.
4. If you can't do one, cicada_video_claim(release=[{url, code, reason}]); code needs_login if it
   needs the person to sign in, and never sign in yourself.
Preferred method: <the run card's How line, omitted for "Let the agent choose">.
If you can run sub-agents, one per video is fine.
```

- **Parallelism** needs nothing new: each video is independent and a claim is a lease, so several
  sub-agents can each `claim` a few. That matches the owner's parallel-sub-agents idea for Sleep, and
  it is why claiming is a tool call and not a fixed list in the prompt.
- **No batch cap** (owner, 2026-09-29: “i dont want to cap the max episodes per sleep, why would we cap them? its just progress that cicada has to go through”; the same reasoning holds for a watch run). A run holds
  whatever the person selected. `cicada_video_claim` still leases at most 10 per call, so the prompt
  loops until it returns nothing. The honest signal before copying is the Size line and the total
  known watch minutes (G-f), never a refusal. The only limit left is the queue file's 2,000-row
  ceiling (§13).
- **A long run stays readable.** The run card draws one meter segment per video up to 10 and one
  continuous bar above that, always with its noun ("5 of 13 recorded"). Above 10 its rows are grouped
  under Couldn't do · Picked up · Waiting · Recorded, each label with its count, the one that needs
  the person first.
- **One batch at a time** shown as the active run; a new handoff replaces it; earlier finished batches
  drop off after a day.
- **Methods.** The `How` hint is text. "Captions or transcript only" says a transcript is enough.
  "Read the link directly" says a model that takes a video link may be handed it: nothing is downloaded. **There is no
  "Use my browser" method.** The first draft offered one, telling an agent to read YouTube transcripts
  through the person's logged-in browser (Browser Harness, Claude in Chrome). That is a Cicada-authored
  prompt steering automation of a logged-in session at a site whose terms bar automated access, the
  same act §5 rejects for `timedtext`, and CLAUDE.md's rail says "no scraping behind authentication,
  ever". A person who wants their own agent to do that is free to ask it; Cicada's prompt does not
  name it (R-VU10). Whether a logged-in read is wanted for **other** providers (a private Loom, a
  workspace video) is Q8, and belongs with the sibling reading-the-web spec.

### 4.9 The skill, and the rail-friendly path

The research's headline: claude-video's **Gemini engine** sends a YouTube URL to Google and downloads
nothing, so it fits the rail. Its **local engine downloads with yt-dlp**, everything included, and
Cicada must never run, wrap or ship that as a default.

- **What the catalog already says.** The `watch` entry's `terms` block already states that the skill
  downloads with yt-dlp and that YouTube's terms bar it, and the Skills page and consent sheet
  already render it (`skill_catalog._PUBLIC` allowlists exactly `terms` and `cicadaNote`). **No new
  key is added** (a `termsNote` would be stripped from `GET /skills/recommended` and never reach the
  app). V4 edits the existing `terms.summary` and `cicadaNote` text only, and only if the wording
  needs to change; the current D2 ("the card states the local engine downloads") is already true.
- **The Gemini path is sequenced after a re-pin.** The catalog pins v0.2.0, which declares only
  `GROQ_API_KEY` and `OPENAI_API_KEY` and no Google network host; the research read a newer README
  (about 0.3.0) that has the Gemini engine. Pointing agents at an engine the reviewed pin does not
  contain would misdescribe what the consent sheet disclosed. So:
  1. **Now (V4a):** the librarian's `/watch` line is **neutral about engines**: "the local engine
     downloads the video with yt-dlp on your machine; that is your call and your agent's, Cicada never
     does it."
  2. **After a re-pin and re-review (V4b):** bump `pin.ref`/`sha`/`skillMdSha256`, add the Gemini key
     to `needs.keys` and its API host to `needs.network`, re-run `scripts/verify-skills.sh`, and only
     then reword the librarian line to prefer the Gemini link for YouTube.
- **A Cicada-launched agent run is not proposed.** A spawned engine runs `--safe-mode` for a stated
  reason (it can never write back into memory), so it cannot load a skill or call `cicada_record_watch`.
  Making one able to would relax the invariant that protects the bank. If ever wanted it is its own
  DECIDE (§8, Q1).

### 4.10 An optional in-app Gemini run (slice 6, gated on Q1)

Only if the owner amends the rail (§5): the app or backend makes one call per video to Gemini with the
**person's own key** (the API-key card's Gemini provider already stores one in `secrets.env`), passing
the YouTube URL as the video part and asking for a summary and ≤ 12 quotes with `m:ss` times.

- **User-triggered, one click, never scheduled** [R-VU5], with the run sheet naming "leaves the Mac,
  to Google".
- **Basis** `both`, engine `gemini_url`, fidelity `approximate` by the derivation above.
- **Preview status, and a limit.** The docs describe YouTube-URL input as preview, capped at 8 hours a
  day on the free tier, no cap on paid; a batch must respect it.
- **Unverified in this repo.** Whether `litellm` (which Sleep's byok path uses) forwards a YouTube URL
  as a Gemini video part is **not confirmed**. Slice 6 begins with a one-video spike; if it does not,
  the call goes through Google's own SDK behind the same wrapper.
- **The result** is written by the same `watch_record.record` as an agent's, under the author
  `cicada` with engine `gemini_url`, so the state and the queue behave identically.

---

## 5. Rails and terms of service, explicitly

| Rail | How this design holds it |
|---|---|
| **No download, no derived stream** (Track V R-V4) | Cicada fetches no video, audio or frame in slices 1–5. The Gemini URL path (slice 6) makes Google fetch it; Cicada derives no stream. A **new** grep test (there is none today; `yt-dlp`, `googlevideo` and `.m3u8` already appear in `video_urls.py`'s docstring and `FILE_EXTENSIONS` data, `VideoRef.swift`, `AVPlaybackController.swift`, `MediaPreview`/`HeroPreview`/`VideoPlayerView`/`WebView`, `api/tests/test_video_enrichment.py`, `api/tests/fixtures/video_urls.json` and the catalog JSON) scans (a) **the new modules only** (`video_queue.py`, `video_state.py`, `routers/videos.py`, the new Swift Videos views) for every one of those strings, and (b) the **whole tree** for the strings that appear nowhere today: `timedtext`, `youtube_transcript_api`, `import yt_dlp`, and a `subprocess` argv naming `yt-dlp`. The allowlist for (b) is the files listed above, named in the test, with the reason. |
| **No transcript kept** (G22, R5 D3) | The record is a summary ≤ 1,500 characters and ≤ 12 quotes ≤ 240. The Gemini and captions paths return more; only the cap-sized record is written. A design that needs full transcripts is a dated DECIDE. |
| **YouTube's terms** | The terms bar downloading outside the official player and access by automated means, and bar circumventing that. So: the default path in Cicada's own process makes no request to YouTube beyond the documented oEmbed it already calls. The unofficial `timedtext` endpoint and `youtube-transcript-api` are **not** built in (undocumented, blocked on cloud IPs, and the terms' automated-access clause). `captions.download` is owner-only (403 on others' videos), so it is at most a connector for the person's own uploads. |
| **Where the line sits when Cicada's own prompt names the method** | The rail is about what Cicada does **and what it tells an agent to do**. The hand-off prompt may name a route that is documented and no-download (a transcript, Gemini on the link). It **never names automating the person's logged-in browser for a video** (R-VU10): that is scraping behind authentication and automated access by another route, and a Cicada-authored prompt is Cicada steering it. An agent the person drives on their own is theirs. |
| **The person's agent, on their machine, with their keys** | Watching by frames, captions or a local downloader is the agent's act. `watch_record.py` already draws this line; the prompt and catalog say so in words. |
| **YouTube API Services Developer Policies** (slice 5) | The policy (read 2026-09-29, per the review) limits how long non-authorized API data and most authorized data may be stored (**30 calendar days** before it must be refreshed or deleted). A person's bank is meant to be handed over intact and lives indefinitely, so **V5 data never enters the bank**: lengths, descriptions, chapters and the `caption` hint live in `$CICADA_HOME/video_meta/<bank>.json` with a `fetched_at`, are refreshed or dropped at 30 days, and feed only the size line and hints. Agent-reported `duration` (an observation by the agent's own tools, not API data) may fill `media.duration_s` as before. Verify the policy text before building V5. |
| **Data leaves the Mac** | Only via the agent the person chose, or the slice-6 Gemini call the person clicked. The run card says which. |
| **Capture rails** | A watch record is an MCP write under the harness as author; refused in the demo bank; scrubbed (`episode_scrub`); ids through `episode_ids`. While Sleep runs it is refused **remotely** and left uncommitted **locally** (§4.3), unchanged from today. Every queue text is scrubbed under its own writer name. Nothing here adds an ungated writer. |
| **`media` spans are never the person's words** (R5 §2) | Unchanged. `basis` and `engine` are provenance, not authorship. |
| **Backend never opens `~/Library` or transcripts under `~/.claude`** | Untouched. The queue file and the V5 cache are under `$CICADA_HOME`. |
| **Outbound gates** | Slices 1–4 add no network call. Slice 5's YouTube key call falls under `CICADA_ALLOW_CONNECTOR_FETCH` (user-initiated sync is never gated; the nightly poll is), a block is never retried with different headers. Slice 6's Gemini call is user-initiated. |

---

## 6. Cost

**How to read this.** The dollar figures come from vendor pages and one search snippet, all read on
2026-09-29, and are **not measured on a real run**. They exist to set relative sizes.
Prices differ between sources, so they must be re-verified before any dollar figure appears in the
product, and this design shows none [R-VU6].

**Assumptions.** Speech is about 150 words a minute, so a transcript is about 200 tokens a minute:
10 minutes ≈ 2k tokens, an hour ≈ 12k.

| Route | 10 min | 60 min | Basis |
|---|---|---|---|
| Transcript, summarised by a small or mid model | ≈ 2k tokens, about $0.02 | ≈ 12k tokens, about $0.04 | Sonnet 5.5 $2/M in; Haiku 4.5 about half |
| Captions themselves | free | free | when they exist |
| Speech-to-text when none exist | about $0.007 | about $0.04 | Groq `whisper-large-v3-turbo` about $0.04 an hour (snippet, unverified) |
| Watch: Gemini reads the YouTube link, low resolution | ≈ 60k tokens, about $0.02 to $0.05 | ≈ 360k tokens, about $0.11 to $0.27 | Flash-Lite 3.5 $0.30/M, Flash 3.8 promo $0.75/M; about 100 tokens a second |
| Watch: Gemini, high resolution | ≈ 180k tokens, about $0.05 to $0.14 | over a 1M context | about 300 tokens a second |
| Watch: Claude frames (about 450 tokens each) plus transcript | ≈ 25k tokens, about $0.05 (Sonnet) | ≈ 57k tokens for 100 frames, about $0.11 | Claude's image formula caps at 1,568 tokens a frame (standard tier) |
| Watch: Claude frames at full size | ≈ 80k tokens, about $0.16 | ≈ 168k tokens, about $0.34 | downsample or it triples |

- **The one solid claim:** a transcript is two orders of magnitude cheaper than any frame-based watch.
  That is why *transcript* is the default per-video choice and *watch* is always deliberate.
- **On a plan** (Claude Code, Codex) there is no per-token bill, only quota, and the limit is the
  agent's context: a 100-frame watch is one large turn. Agentic-mode savings Google reports for
  Gemini (up to 88% fewer tokens on long videos) are the vendor's own figure, unverified.
- **What the app shows** (thresholds are **assumptions** to tune from real runs):
  - **Light:** a transcript job (any length up to 3 hours).
  - **Medium:** a watch of 30 known minutes or less.
  - **Heavy:** a watch over 30 minutes, or with unknown length, or a transcript over 3 hours.
  - plus the total known minutes of the watch items. Never a price.
- **No batch cap** (§4.8). The Size words and the total known watch minutes are on the run card
  before Copy for an agent, so nobody discovers the size after the fact.

---

## 7. Phasing: shippable slices and acceptance

Each slice merges to `dev` alone and leaves the app truthful. Slices 1 → 2 → 3 are ordered; 4a can
run beside 2.

### V1: the states (no queue yet)

*Backend:* `watch_record.record` takes `basis`, `engine`, `duration`; episode frontmatter keys; union
on a same-hash repeat; `video_state.py` (the set-union rule); `GET /videos/state` (state and record
only, keyed by `videoKey`); the provenance additions and `VIDEO_SHAPE` in the two ETags (§4.2).
`AUTHOR_SHAPE` is untouched. *MCP:* the three arguments at **all five sites** (§4.5), the primer
clause, the `BRIDGE_TEXT` video line naming `basis`, and **both** contract constants
(`CONTRACT_VERSION`, `REMOTE_CONTRACT_VERSION`) bumped to their next free numbers. *App:* the state
block and the Feed row word; `VideoStateCache`; `VideoState` Swift twin over
`api/tests/fixtures/video_state.json`; the Reader's fidelity chip.

Acceptance:
- **A1.** With no watch episode, `state == none`; the fixture covers every row of §4.2's union table:
  `transcript`; `frames` → `watched`; `both` or `transcript` + `frames` → `watched_and_transcript`; a
  legacy episode with no basis → `recorded`; a legacy episode beside a `transcript` one →
  `transcript`; a legacy beside a `frames` one → `watched`; an unrecognised basis → `recorded`.
- **A2.** A repeated call with the same body and a new basis makes **no second episode**, updates the
  frontmatter to the union, keeps `content_hash`, and does not flip `processed`.
- **A3.** A retracted `describes` claim leaves the state unchanged (R-VU1). **Second divergence,
  pinned:** a record with a summary and **zero valid excerpts** has no `media` span, so the claim-based
  rule says "not watched" while the episode-based rule says it was; the test asserts both answers.
- **A4.** An unknown `engine` value is dropped and the record is still written; an unreadable
  `duration` is dropped; `duration` never overwrites an existing `media.duration_s`.
- **A5.** R12: every argument the primer names exists in the schema, for every remote scope set, at
  all five argument sites (the remote dispatch lambda passes `basis`, `engine`, `duration`).
- **A6.** The Swift twin decodes and derives the same states from `video_state.json`.
- **A7.** Fidelity is `approximate` for `gemini_url`, `other` and absent (so every legacy record),
  else `verbatim`, on `/episodes/{id}/text` and `/citations`; a bumped `VIDEO_SHAPE` changes both ETags.
- **A8.** The new rail-grep test (§5) passes with its named allowlist and fails on a planted
  `timedtext` string.
- **A9.** Two saved videos with the **same title** (same media entity id) get distinct `videoKey`s and
  distinct states; a record on one never shows on the other.

### V2: the queue, per item

*Backend:* `video_queue.py`, the file, the lock, lease, sweep and scrub; `PUT/DELETE
/videos/queue/{key}`, retry; the `videoQueue` sync component **and** the client `VideoRefresh` set
together. *MCP:* `cicada_video_queue` (read) and `cicada_video_claim` (record) at every site in §4.5
(server schema and dispatch, `mcp_tools` handlers, `catalog.TOOL_SCOPE`/`READ_TOOLS`/`WRITE_TOOLS`,
`remote/tools.py`, `remote/runtime.py` `_DISPATCH`, the three test maps), the primer clause, both
contract constants; `record_watch` removes the satisfied entry per §4.3. *App:* Queue transcript and
Queue watch in the detail block, "Queued" on the row.

Acceptance:
- **B1.** Add, replace (`watch` replaces `transcript`) and remove are idempotent; a `videoKey` that is
  not a saved media page is a 404; the 201st entry is refused with a sentence (the Q10 ceiling; this
  test goes if Q10 removes it).
- **B2.** Two processes writing at once never lose an entry (a lock test with two threads).
- **B3.** Nothing in the queue's lifecycle dirties the bank: `git status` is clean after every queue
  call.
- **B4.** `claim` leases up to `limit` and never the same item to two sessions; a lapsed lease returns
  it with `attempts + 1`; the third lapse marks it `failed` with the derived reason.
- **B5.** The satisfaction table of §4.3 as tests: `transcript` closes a transcript request and leaves a
  watch request claimed; `frames` closes both; an omitted basis closes the entry only for the leaseholder
  and leaves the state `recorded`; a lapse with a newer satisfying record closes the entry as done.
- **B6a.** *stdio, during a Sleep cycle:* `record_watch` writes the episode and claim, skips the commit
  (pages dirty), and removes the queue entry.
- **B6b.** *Remote, during a Sleep cycle:* `cicada_record_watch` and `cicada_video_claim` answer
  `BUSY_TEXT`, write nothing, and the entry stays claimed.
- **B7.** The demo bank refuses `cicada_video_claim` and `record_watch` (stdio and remote) and allows
  queueing from the app.
- **B8.** Scope: a `read`-only connector sees `cicada_video_queue` (with `readOnlyHint: true`) and does
  **not** see `cicada_video_claim`; a `record` connector sees both; `test_remote_tools`,
  `test_demo_capture` and `test_mcp_tools_context` pass with the two tools registered.
- **B9.** A bank switch shows the other bank's queue; the file is per bank.
- **B10.** A `failed.reason` containing a secret-shaped string or a newline is stored scrubbed, one line,
  ≤ 200 characters; `test_video_queue_scrubs` fails for a writer that skips it.
- **B11.** A claim writes only the queue file, moves `videoQueue` and `version` in `GET /sync/version`,
  and the app's `VideoRefresh` revalidates on it, so "Picked up" appears without a reload.

### V3: selection, thumbnails and the hand-off

*App:* the Feed's Videos mode, `videoPickRow`, the run card and its progress state, `WatchLeavesMacNote`,
the Sleep page's read-only row. *Backend:* `POST /videos/run/handoff`, batches. *Demo:* two more
saved videos, the three states, the app-side fixture (§4.7E).

Acceptance:
- **C1.** The picker's rows read only stored fields; a page with no thumbnail draws the placeholder
  and no request is made for a derived URL.
- **C2.** Nothing is pre-selected; the default per-item choice is Transcript; a per-item menu change
  writes nothing until the handoff.
- **C3.** No cap: a handoff of every unread video (14 or more) is accepted in one call, with no 422;
  the prompt tells the agent to call `cicada_video_claim` until it returns nothing, and a 14-item batch
  is claimed in two calls of at most 10. A run over 10 draws a continuous bar and grouped rows.
- **C4.** The bar's numerator equals the size of the batch's `done` list, and never moves on "picked
  up". A test drives a record and asserts the bar moves once.
- **C5.** The prompt is ≤ 1,200 characters, names only tools that exist (R12), contains no video
  content and **names no browser method**.
- **C6.** Esc closes the run card, then the mode, without animating; ⌘K and ⌘F still work; entering the
  mode swaps the eyebrow's tab groups and tapping the active picker tab returns to All (DR-45).
- **C7.** The Sleep row shows counts and a link, has no button that starts anything, uses "picked up",
  never "being watched", and the page's single Consolidate control is unchanged (`FixWaveTests`, the R10
  tests).
- **C8.** DR lints: no new literal padding on `videoPickRow`, no `.hoverLift` on rows, the checkbox
  and tabs use the shared components, every icon-only control has a help.
- **C9.** Screenshots at 1440 and 1200 wide with the rail and the labelled sidebar.
- **C10.** The demo generator writes no queue file; the demo-state API test pins the media count and the
  three states; `videos-state-demo.json` decodes in Swift.
- **C11.** The run card's record line reads "Read by Sleep" only when `processed_by == sleep`, says
  nothing when an agent flipped `processed`, and never contains "in your graph".

### V4: skills and honesty

**V4a (parallel to V2, no re-pin):** the librarian and `cicada` SKILL.md say the local engine downloads
with yt-dlp and is the person's call, neutral about engines; the `watch` entry's existing `terms` /
`cicadaNote` text is edited only if that wording needs it. **V4b (after a re-pin and re-review):**
bump the pin, add the Gemini key and API host to `needs`, then prefer the Gemini link in the librarian
line.

Acceptance: **D1.** `scripts/verify-skills.sh` passes (V4a with the unchanged pin; V4b with the new one
and its new `needs`). **D2.** The card and consent sheet state that the local engine downloads, through
the **existing** `terms` block (no new catalog key; a test that `_PUBLIC` is unchanged). **D3.** The
handshake's video capability line names `basis` (one argument added, its fingerprint test moved). **D4.**
V4b's librarian text is not merged before the catalog's `needs` declare the Gemini key and host.

### V5: durations, optional

A person-supplied YouTube Data API key in Settings → Plans & keys (a connector row, credentials only),
used by a `videos.list` call (part `snippet,contentDetails`, one quota unit) to learn duration,
description, chapters and a `caption` hint, only for saved YouTube videos, only on Sync now or an
explicit "Get lengths" click, under `CICADA_ALLOW_CONNECTOR_FETCH` for any unattended run. **Results
live in `$CICADA_HOME/video_meta/<bank>.json` with `fetched_at`, never in the bank (§5).**
Acceptance: **E1.** No key, no call. **E2.** A failure records an error, never retries with other
headers. **E3.** The key lives only in `secrets.env` and is removed by `forget()`. **E4.** The size line
becomes minutes-based for those videos. **E5.** No API-derived field is written to a media page; an
entry older than 30 days is refreshed or dropped, and the size line falls back to "length unknown".

### V6: the in-app Gemini run (gated on Q1)

Only after the owner's dated ruling. Acceptance: **F1.** A spike proves the URL-as-video call works and
records its real token use. **F2.** The run sheet names Google. **F3.** Never scheduled; refused in the
demo bank; refused while Sleep runs. **F4.** The free-tier daily cap is respected. **F5.** The record is
identical in shape to an agent's, with engine `gemini_url` and fidelity `approximate`.

---

## 8. Open questions for the owner

Only real decisions. Each has a recommendation.

- **Q1: May Cicada itself ask Gemini to watch a YouTube link (slice 6)?** It uses the person's own
  key and click, no download and no derived stream, and Google fetches the video. It still reads as
  "Cicada watches a video", which the standing wording forbids. **Recommend:** not yet. Ship the
  hand-off first (slices 1–4 need no rail change); decide with real run data, and only for the Gemini
  link route.
- **Q2: The queue outside the bank (recommended) or inside it?** Outside avoids commit noise and the
  dirty-tree smear, and a queue does not need to travel with a bank. Inside would let a bank hand-over
  carry pending requests. **Recommend:** outside.
- **Q3: Should saving a video queue a transcript automatically?** Your default is "metadata, or a
  transcript only". **Recommend:** queue nothing automatically, and add one click in the Videos view,
  "Queue transcripts for the 14 unread", plus a setting (off) that does it for new saves. Auto-queue
  is safe only because a run is still a click.
- **Q4: Where does the run live: the Feed's Videos view, or the Sleep page?** **Recommend:** the Feed,
  because videos and their thumbnails live there and the Sleep page keeps one trigger (R10). The Sleep
  page shows the queue and links to it. This decides how much of the sibling Sleep redesign carries
  video.
- **Q5: Is an optional YouTube Data API key acceptable for lengths and captions hints?** Without it a
  YouTube video's length is unknown until an agent reports it, so estimates are blind. **Recommend:**
  yes, as an optional credentials row (slice 5), off by default, its data outside the bank with a
  30-day life (§5).
- **Q6: How loud should Cicada be about the local downloader?** The catalog already recommends a skill
  whose local engine uses `yt-dlp` and already shows a terms block. **Recommend:** keep it listed, lead
  with the Gemini-link path only after a re-pin (V4b), and never make the local engine a default.
- **Q7: The word.** The owner says "consolidate"; this spec says *watch run* (and *read* for a
  transcript) so it is not confused with Sleep. **Recommend:** keep *watch run*. Change it if you
  prefer a different word for the app.
- **Q8: Is a logged-in-browser read wanted for videos on other providers** (a private Loom, a
  workspace video)? It is removed for YouTube outright (R-VU10). **Recommend:** not in this spec; decide
  it with the sibling reading-the-web spec, as an explicit per-site DECIDE, never a default.
- **Q9: Five states, not four.** The owner named four (neither, transcript, agent, both). A fifth,
  "Recorded, method not given", exists so a legacy or basis-less record is never labelled as a watch.
  **Recommend:** keep it; it is the honest answer for every record made before this change.
- **Q10: The 200-entry queue ceiling.** With no batch cap (owner, 2026-09-29), the only limit left is
  the queue file's 200 entries (§4.3, B1). Remove it, or keep it only as a file-safety ceiling no one
  should reach? **Recommend:** keep it as a safety ceiling well above any bank's saved videos, its
  refusal naming it in a sentence; revisit if a real bank comes near it. DECIDE.

---

## 9. Risks

- **`basis` is self-reported.** An agent can say `frames` after reading a transcript. The app says "an
  agent recorded" (R-VU2). Cost of a wrong label is a misleading badge, not a wrong belief. A record with
  **no** basis is no longer mislabelled; it is `recorded`.
- **Most early records will read "Recorded, method not given".** Until agents pass `basis` (the contract
  and bridge line now ask), the four sharp states fill in slowly. That is the honest cost of R-VU2.
- **Gemini's quotes are model output.** Timestamps and wording can drift. Mitigated by the derived
  fidelity note (which every legacy record also carries); not eliminated. A quote from `captions` is
  the only verbatim one.
- **Preview status and prices move.** Gemini's YouTube-URL analysis is preview with a free-tier daily
  cap; its price figures differ between sources. Nothing shipped in slices 1–5 depends on it.
- **Unknown lengths make the estimate blind** until a key or a record supplies one. "Heavy" is
  the honest default until then, and the Size line says so before copying.
- **A run depends on an agent being present.** If nobody claims, items sit `queued`. The run card
  says "Waiting for an agent" and offers the prompt again; it never pretends to be working.
- **Sleep collision, as it really is.** Locally a record made during a cycle is written and left
  uncommitted for the cycle's sweep, and the queue entry is removed regardless; remotely it is refused
  with the busy text and the lease covers the retry. If cycles run long a remote run stalls, visibly.
  `record_watch` is **not** changed to refuse locally (that would alter G140 behaviour for every
  harness; if wanted it is its own row).
- **Two "watched" definitions.** Episode-based (this spec) and claim-based (the belief layer). They
  differ in **two** cases, both on purpose: after a retraction (R-VU1), and for a record with a summary
  and no valid excerpts (no `media` span). The A3 tests pin both.
- **An omitted basis can close a watch request.** To keep the queue from jamming, a leaseholder's
  basis-less record closes its entry; the run card labels that row "method not given" so it is never
  read as a watch. The owner may prefer to keep such an entry open instead.
- **Contract bump collisions.** Two constants, `CONTRACT_VERSION` and `REMOTE_CONTRACT_VERSION`, and
  other branches have claimed the same numbers before. Take the next free ones at merge.
- **The skill's licence and terms move.** The catalog pin is reviewed; a fork or newer version is not
  adopted until re-reviewed (V4b).
- **Thumbnails are a network fetch by the app** (already so, via `PictureStore`). A hidden or
  offline picture must degrade to the placeholder, never block the picker.
- **Demo shows the flow only in part.** The generator cannot seed a queue (it is outside the bank), so
  the queued and in-progress cards are an app fixture plus the person's own click.

---

## 10. Measured, read in code, and assumed

| Claim | Status |
|---|---|
| oEmbed gives YouTube title, channel and thumbnail but no duration | read in code (`_enrich_youtube`) |
| Media entity id is `media-<slug of title>`; the URL hash only on a truncated slug | read in code (`_media_entity_id`) |
| The watch record's caps, marker and claim shape | read in code (`watch_record.py`) |
| stdio `record_watch` writes and skips only the commit during Sleep; remote refuses via `BUSY_TEXT` for `WRITE_TOOLS` | read in code (`mcp_tools.py`, `remote/runtime.py`) |
| Each tool has exactly one remote scope; read and write sets are disjoint | read in code (`remote/catalog.py`) |
| The `record_watch` argument path has five sites; the remote lambda passes only `excerpts`/`chapters` | read in code |
| Two contract versions (local static, remote dynamic) | read in code (`handshake.py`) |
| The catalog's `watch` entry already has `terms` and `cicadaNote`; `_PUBLIC` allowlists them and not `termsNote` | read in code |
| A Cicada-spawned engine runs `--safe-mode` (no skills, MCP or hooks) | read in code (`agent_engine.py`) |
| The catalog pins v0.2.0 with GROQ and OPENAI keys only | read in the catalog |
| No source-grep test for `yt-dlp`/`googlevideo`/`.m3u8` exists today | read (searched `api/tests`, the app tests) |
| claude-video's engines, detail levels and download behaviour | from the README, not run here |
| `videos.list` costs one quota unit; `captions.download` is owner-only | from Google's docs, not called here |
| YouTube API Services policy limits storing API data (30 days) | from a review finding citing the policy page; **verify before V5** |
| Gemini YouTube-URL input is preview, capped at 8 hours a day free | from Google's docs (verify before relying) |
| All dollar figures and the agentic-mode savings | vendor pages or one snippet; **not measured, re-verify** |
| Groq Whisper about $0.04 an hour | one search snippet, unverified |
| `litellm` forwards a YouTube URL as a Gemini video part | **unknown**, slice 6's spike |
| 45-minute lease, the 200-entry queue ceiling (Q10), Light/Medium/Heavy thresholds | **assumptions** to tune from real runs |
| Fidelity `approximate` for `other` and for an absent engine | **assumed** |
| Nothing here was run against a live bank or a real video | true |

---

## 11. Backlog rows to file (next free `G` ids)

**Filed 2026-09-29:** rows 1 to 3 and the V4 to V6 sub-items are **G162** in `docs/goals/memory-evolution.md`; row 8 is decided with **G166**.


1. **Video states and the record's basis** (V1): APPLY.
2. **Video queue, `cicada_video_queue` and `cicada_video_claim`** (V2): APPLY.
3. **The video run: selection, thumbnails, hand-off** (V3): APPLY.
4. **Skill honesty: the watch skill's terms, then the Gemini-link path after a re-pin** (V4a/V4b): APPLY.
5. **Video lengths from an optional YouTube key, outside the bank** (V5): DECIDE (Q5).
6. **An in-app Gemini watch** (V6) 💸: DECIDE (Q1), with the spike.
7. **A Cicada-launched agent for watching** (needs a non-`--safe-mode` spawn): RESEARCH, not
   recommended.
8. **A logged-in-browser read for non-YouTube videos** (Q8): DECIDE, with the reading-the-web spec.

Row 3 reads against **G22** (its "app watch UI" open item), **G140** and Track V; G22's "transcript
stored with the entity is superseded by cited excerpts" is not reopened.

---

## 12. Review record (2026-09-29)

A code review of the first draft produced 20 critiques. All were checked against the code at `dev` @
`2155940`. Nineteen held and are fixed above; one was partly wrong; two pairs overlapped.

| Critique | Result | Where |
|---|---|---|
| "Refused during a cycle" is not an existing rule for `record_watch` | Confirmed (stdio writes and skips only the commit; only remote refuses). Rewritten as real behaviour; B6 split into B6a and B6b; the queue-entry removal is stated | §1, §4.3, §9, B6a/b |
| `cicada_video_queue` cannot be one tool with two scopes | Confirmed. Split into `cicada_video_queue` (read) and `cicada_video_claim` (record); every registration site and test map listed | §4.5, V2, B8 |
| Queue keyed by media entity id collides | Confirmed (`_media_entity_id`). Keyed on the url-index key (`videoKey`), routes and examples fixed | R-VU8, §4.3, §4.6, A9 |
| `termsNote` is stripped by `_PUBLIC` and D2 already holds | Confirmed. No new key; existing `terms`/`cicadaNote` edited | §4.9, V4, D2 |
| Five argument sites and two contract versions | Confirmed. Listed, R12 test per remote scope set, static vs dynamic contract noted | §4.5, A5, V1 |
| State table leaves legacy plus transcript uncovered; `both` overloaded | Confirmed. Set-union rule; state renamed `watched_and_transcript`; fixture cases | §4.2, A1 |
| A `frames`-only or basis-less record jams a `transcript` request | Confirmed. Satisfaction table; lapse sweeps for a newer record and derives its reason | §4.3, B5 |
| State item shape lacks `episodeId`; `recordedBy` from a trailer needs `git_head` | Confirmed. `episodeId` added, `recordedBy` from episode `harness`; duplicated fields dropped | §4.6 |
| `videoQueue` needs a revalidation set | Confirmed (`BacklogRefresh` precedent). `VideoRefresh` and a sync test | §4.6, B11 |
| Demo cannot seed a queue | Confirmed. Generator seeds no queue; fixture plus the person's click; counts move | §4.7E, C10 |
| Picker per-item wants vs one-`want` batch | Confirmed. Handoff carries `[{key, want}]`; deselect semantics stated | §4.6 |
| Grep test "extends the existing one" | Confirmed (none exists). New test with a named allowlist and split scope | §5, A8 |
| Reader chip needs provenance payload fields and a shape tag | Confirmed. Additions listed, `VIDEO_SHAPE` in both ETags, legacy shows the caveat | §4.2, A7 |
| A basis-less record labelled "Watched" is dishonest | Confirmed. Own state `recorded`; bridge line and contract ask for `basis` (D3 changed) | R-VU2, §4.2, §4.5 |
| Copy states what Cicada does not know (claimed, processed, next cycle) | Confirmed. "Picked up"; `readBySleep`; "the next time it runs" | R-VU9, §4.7, C7, C11 |
| "Use my browser" for YouTube contradicts the ToS rail | Confirmed. Removed; §5 row; Q8 for other providers | R-VU10, §4.8, §5 |
| V4 rewords toward an engine the pin lacks | Confirmed. Split V4a (neutral) and V4b (after re-pin) | §4.9, V4, D4 |
| V5 permanent storage vs the YouTube API policy | Accepted on the review's citation; **the policy text was not re-read here**, so V5 says verify first. Data kept outside the bank, 30-day life | §5, V5, E5 |
| Free-text `failed.reason` unscrubbed | Confirmed. `video_queue` writer name, ≤ 200 chars, one line | §4.3, B10 |
| Two "watched" definitions differ only after a retraction | Confirmed (no-excerpt record). Second divergence named and pinned | §9, A3 |
| Picker tabs have no All state; needs a departure note | **Partly wrong.** DR-45 itself says tapping the active tab returns to All, so the picker has an All state and needs no departure (the Feed's sort tabs needed R-DL13 only because a sort has no "none"). The third-tab-group point held: entering the mode swaps the eyebrow's groups | §4.7C, C6 |

Two critiques overlapped and pulled in opposite directions on a basis-less record (one wanted it to
satisfy the claimed request, the other wanted it never to satisfy a watch or transcript). Resolved by
separating the two: it may **close the queue entry** for its leaseholder, and it **never changes the
state**, which stays `recorded` (§4.3, §9).

**Owner, 2026-09-29, after the review:** “i dont want to cap the max episodes per sleep, why would we cap them? its just progress that cicada has to go through” The watch run's caps went with it: §4.4, §4.6's 422,
§4.7C's "Select the first 20", §4.8, §6 and C3 now say there is no batch cap; the Size line and the
total known watch minutes are the signal before copying; the queue file's safety ceiling (now 2,000 rows, §13 D-2) is Q10.

---

## 13. Amendments, 2026-09-30 (the boards were approved; the plan was criticised; this section wins)

The owner, 2026-09-30: "I also like the watch video designs, apply them." The twelve `Video*` boards were read against the
code and a plan was written and reviewed (16 findings, all applied). Where this section and an earlier one differ, **this
one wins**. The backend half shipped first (branch `feat/video-watch`); the app half follows.

| # | Amendment | Why |
|---|---|---|
| P1 | No batch cap anywhere (R-VU12). The hand-off accepts every selected video; a claim leases at most 10 a call. The queue file's safety ceiling is **2,000 rows** (D-2), refused with a sentence naming the limit. | "Select all 13 not read yet" must not break at 200. |
| P2 | Provider-neutral copy (R-VU11), enforced by `test_video_copy_provider_neutral.py`. | Owner 2026-09-30. |
| P3 | No site list for video (R-VU13). The item set is the Feed's set (P10); an agent hands back what it cannot get with a `code`, and the app surfaces it. | Owner 2026-09-30. |
| P4 | The queue mirrors `reading_asks.py`: `$CICADA_HOME/video_queue/<bank>.json`, `fcntl.flock` on a sidecar, temp file plus `os.replace`, **no URL and no title stored**, expiry applied in memory and persisted only inside a write. Rows are keys, joined at read to the url index. | Privacy of a machine-wide file; no read-caused SSE loops. |
| P5 | `cicada_video_claim` writes only the queue file, so it is **not** refused while Sleep runs (this replaces B6b). `catalog.WRITE_TOOLS` still lists it (the demo gate, the write lock); `runtime._writes_bank` answers `False` for it. `cicada_record_watch` keeps today's behaviour (remote: `BUSY_TEXT`; stdio: written, commit skipped). **A lapsed lease is judged only when Sleep is not holding the pages** (`ToolContext.pages_held()`, asked lazily, only when a lease has lapsed, H3). | Ruling 13 makes a person-started Consolidate hours long; a drain must not burn a video's three attempts. |
| P6 | Wire additions: `GET /videos/summary` (counts and the active batch, no items), `GET /videos/run/prompt` (pure; `?count=&method=` previews and writes nothing), `recordedAt` (an ISO instant) in place of `recordedDay`, `failedCode` and `failedReason` on an item, `nextChangeAt` on both reads. | The boards show a recorder's time, a re-copyable prompt and a needs-login row; Sleep must not download every item to print three counts. |
| P7 | The engine value `gemini_url` is `video_link`; the closed set is `captions`, `video_link`, `local_frames`, `speech_to_text`, `browser`, `other`. Fidelity is `approximate` for `video_link`, `other` and absent. | A stored enum that names a provider would leak into words. |
| P9 | Contract wording: "when the person asks you to work their video queue (or hands you a Cicada prompt for it)". Not "take what is waiting". No recall-hook nudge for video. | An agent must not spend the person's plan on videos nobody asked it to work. |
| P10 | The set of videos is the Feed's set by one rule: `video_state.is_video_page(media_type, url, kind)`, the twin of `FeedKind.of == .video`, pinned by `api/tests/fixtures/video_kind.json`, over the same `url_index` entries and skip rules as `GET /sources`. | The strip must never disagree with the Videos tab. |
| P13 | The app does not re-derive state: the server is the only deriver (the episode facts are not on the wire), so a Swift twin of the union rule would be dead code. The app decodes and labels from the shared fixture. | Spec A6 asked for a twin; it cannot be fed. |
| H1 | **The permission page works for video.** `video_prompt.build(..., browser_clause=None)` keeps the default text; the routes pass `BROWSER_CLAUSE` iff the single reading permission is on (read per request, import guarded so this can merge before the reading branch). The clause names no site, no browser product and no provider, and is an instruction, not a promise. R-VU10 is amended accordingly. The app's needs-login row reads the same permission: off, a sentence and a button to Settings → Agents; on, "Try again". No site list, no `agent_hosts`. | A needs-login video was a dead end. |
| H2 | **A lapsed lease is visible.** The `videoQueue` sync component is `<mtime>:<due>`, where `due` counts leases lapsed, failed rows expired and finished batches expired with nothing written; the parse is cached by file stamp, so the ~1 Hz poll stays a `stat`. Both reads carry `nextChangeAt` and the app schedules one revalidation there. | Nothing changes on disk when a lease lapses, so the ETag would 304 "Picked up" forever. |
| M2 | The claim reply carries a provider's title and channel: fenced and capped like a read on remote (`FENCED_WRITE_REPLIES`), the same one-line header on stdio, each title and channel one line of at most 120 characters. | Untrusted text reached the agent unfenced. |
| M3 | The model on the record block is the turn join: `/episodes/{id}/text`'s `watch` object carries `authorModel` and `authorEffort` from the `describes` claim that cites the episode, or null. | `/videos/state` stays light; nothing on a watch episode records a model. |
| M4 | The ledger kind is `video_queue` at all five sites (`KINDS`, `NON_SPEND_KINDS`, `SIBLING_KINDS`, `PER_TURN_KINDS`, and the scrub writer `video_queue`). | Kept out of every Usage view. |
| M5 | A queue row whose key stops resolving (archived, junk, index entry gone) is skipped by a claim, ignored by every count and dropped by the next write; its batch shrinks the way Remove does. | Rows are keys only. |
| D-1 | Decided: the browser clause is gated on the single permission (H1). | |
| D-3 | The picker's check is the boards' neutral `NeutralCheckToggleStyle`; the accent is not spent on selection (DR-5). | |
| D-4 | `speech_to_text` and `browser` stay `verbatim` until a real record disproves it. | |
| Seam | "How your agent watches" (skills the person picked: a browser, a macOS harness, a video skill) lands with the reading branch's `agent_methods`. **`video_prompt.method_clause(memory_path)` is the one place it plugs in**: the hand-off prompt and the claim reply both read it, and it returns `None` until the person chooses. **Landed 2026-09-30:** `agent_methods` has the `watching` job (`watch`, `browser-harness`, `macos-harness`, plus the agent's own tools), and R-VU10 stands as amended: a chosen skill is the person's own instruction, and the default text still names no browser route. | Keeps this branch free of the reading branch. |
| Open | L4: a video on a host `video_urls` does not know is a `link` and cannot be queued for a watch. Recommend a follow-up "Have an agent watch this" on any saved non-paper link, reusing `PUT /videos/queue/{key}` (drop the 404). Not needed for V1 to V4a. | Consistent with the Feed's rule; the "we never know which sites" case. |
| Open | G-1: the boards do not show how to return to an unfinished run after leaving it. Ask the designer before adding a control. | |
