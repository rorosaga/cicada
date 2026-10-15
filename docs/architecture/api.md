# API design

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

35 routers mounted in `api/main.py`, plus repo-context and maintenance endpoints. **Read the routers
for the endpoint list** — it is not duplicated here. What is *not* derivable:

**Prose provenance (G118 sections, 1a-i).** Existing `GET /entities/{id}/provenance`
adds `sectionSchema: 1`, `pageBodyHash` of the same parsed body, `sections[]` and
`sectionsPartial`. Section rows report item/recorded/span/reasoning/unmatched counts;
items carry opaque identity, text, server-owned Unicode `bodyRanges`, ambiguity and
expanded G118 evidence. Section statuses are tracked/partial/not_tracked/metadata_unavailable,
independent of the unchanged current-claim totals. Source rows include availability,
conversation/title, current/grown/stale/missing/unavailable/not_checked/gap and optional
`span`. Only a checked span has wash coordinates: raw evidence coordinates are metadata,
not permission to highlight; reasoning has no span. Source checks share the existing
conversation body cache and cap; no derived search/backfill occurs here.
Empty or missing sections with stored records remain visible as zero-item `not_tracked`
rows with `unmatchedRecords`. Sections hidden by any open code fence instead report
`metadata_unavailable`; a closed fence's invalid claim data does not hide prose links.

New item rows are bounded to 128 KiB, with per-section `partial` and honest full counts
if omitted; durable metadata is never truncated. There is no new endpoint/cursor/409.
The ETag retains entities/episodes/git_head, author shape and current day, and adds
`sections3` (including sections hidden by non-claims code fences); server models and defaulted Swift decode
ship together. R-PB11 still applies:
asked on demand, cached in memory, not a Store domain or a new VersionVector component.

**A page's link facts and the person's page edit (owner rulings 2026-10-14).** `GET /entities/{id}/links`
(`page_links.facts`, `storage.md`) is engine-free, never fetches and writes nothing; its ETag is entities + sources (the
URL index) + design, plus `page_links.SHAPE` and the page id. **Not a Store domain** (R-PB11): the app reads it into
`LinkFactsCache` (in memory, by entity id, revalidated on every ask, emptied on a bank switch), so it ships no
`VersionVector` mapping. `GET /entities/{id}/sources/icon/{site}` also serves the site of a page the person **saved** that
this page's prose links to (`page_links.linked_sites`), beside a trusted source's site; never on a `person` or `media`
page (G159), never a site only linked. `POST /entities/{id}/edits` (`PageEditRequest`: `reason` plus the
`cicada_edit_page` body — `edits`, `section`/`text`, `add_aliases`, `remove_aliases`) is the person's own page edit: the
same `page_edits.plan`, under the route's write admission (409 while Sleep holds the pages, G177) and the page lock,
committed alone as `Page edit <date>` with `entities/<id>.md: edited (trigger: user/companion_app)`, the `Reason:` line
and `Cicada-Author: user` — a second door onto one writer, as the CLI is (ruling 21). 400: a request the editor refuses;
409: words no longer on the page; 404: no page. The link-view switcher sends one `{old, new, all: true, pin: true}` row.

**Where a page's knowledge comes from (owner 2026-10-14, G61).** `GET /entities/{id}/sources/overview`
(`page_sources.overview`) answers the card's one section in one read: `sources[]` (each the `/sources` entry plus
`site`, a `title` (the page's `## Links` title for that URL, else the name of the saved page `entity:` links it to —
never fetched), `scope` `fact|site|page` and the current beliefs of its predicate it backs — at most
`MAX_FACTS` 4, newest first, with `factCount`; a happening, milestone or withdrawal record is never a fact a source
backs, though it still counts toward the conversations), `links[]` (the `## Links` lines that are not sources, at most
`MAX_LINKS` 12 with `linksTotal`, each with `cameFrom` — the conversation its section-provenance record names, with
the evidence the Reader opens), `conversations` (`total`, `firstSaid`/`lastSaid`, `apps[]` by harness else origin:
conversations, beliefs and passages backed, last said — grouped by `provenance.conversation_groups`, the grouping
`/provenance` uses, so the totals agree), `factsTotal`, `factsWithSource` and `lastChecked` (the newest `verified`
or `checked` stamp). Engine-free, never fetches, writes nothing; bounded so an owner-sized page answers in kilobytes,
and linear in beliefs + episodes (episode → beliefs/passages inverted once; review B1: ~170 ms warm at 5,900 beliefs over
3,000 conversations). The card reads it when the section opens or the beliefs list shows, never on every open.
ETag over `entities`+`episodes` with `extra` = `page_sources.SHAPE|<page>|<today>` (what is a current belief moves at
midnight). R-PB11: asked on demand and cached in memory by `ProvenanceCache.sourcesOverview`, not a Store domain, no
`VersionVector` mapping. The wire is pinned on both sides by `api/tests/fixtures/page_sources_overview.json`.

**Auth.** Every endpoint except `GET /healthz`, `POST /capture/telegram`, an OAuth adapter's
`GET /sources/connectors/{id}/callback`, and OpenRouter's sign-in landing
`GET /connections/byok-openrouter/callback/<nonce>` (R-AG10 — gated by its own single-use, 10-minute nonce
carried in the path, since OpenRouter appends only `code`; the PKCE verifier never leaves the backend) requires `Authorization: Bearer <token>`, from
`~/.cicada/api_token` (`CICADA_API_TOKEN` overrides; `CICADA_API_AUTH=off` for tests). The Telegram
webhook is exempt because Telegram's servers cannot send the header — today it is gated only by
Telegram being configured, not by a per-request secret (**see G57**). Each OAuth callback lands in
the user's browser, which likewise cannot send the header, so it is gated by its own single-use,
10-minute `state` nonce; `auth.py::_is_oauth_callback_path` resolves the exemption live against the
connectors registry rather than hardcoding a literal per adapter.

**ETags.** `/graph`, `/inbox`, `/contributors`, `/sources`, `/sources/channels`, `/origins` and
`/banks` all return an `ETag` and honor `If-None-Match` with a `304`. This matters: `/graph` on the
live bank is ~1.8 MB. **Ship the ETag and its client mapping together** — `GET /inbox` ETags over
`inbox`+`entities`+`episodes`, and `VersionVector.swift` maps `entities` and `episodes` onto
`.inbox`; change one half, change both. `/graph`'s `extra` carries a node-shape tag
(`graph.NODE_SHAPE`), bumped when a node gains a field a client must see or the body changes for
the same files (F1's context filter and fence strip; `+previews` when a media node's `picture` became the stored
preview path); `/sources` carries `sources.SHAPE` in its `extra` the same way (`preview-1`: items gained `preview`;
`saved-why-2`, G191 v3: items gained `savedWhyHistory`, `lastSavedAt` and `captureThumb`). Neither moved a component,
so `VersionVector` was unchanged by those — but G191 v3 also folds the `captures` component into `/sources`' ETag (a
new site capture gives a bookmark's row its thumbnail), so `VersionVector` maps `captures` → `.sources`.
**G191 v4.** `/sources` items gained `leftBrowser` `[{browser, channel, since}]` (shape `saved-why-3`): the browsers a
bookmark has left, read from the bookmark seen-set's `left` map. That file (`sources/bookmark_seen.json`) is not `*.md`, so
the `sources` component's directory fingerprint never saw it — it now rides the component by its own mtime (client
mapping unchanged: `sources` → `.sources`). `GET /sources/channels/{id}/items` for a bookmark channel also lists the links
that left the browser, each with `left` (shape `g161-2`). `POST /sources/sync-bookmarks` gained `leftMarked`;
`removalsProposed` stays on the wire and is always 0 for bookmarks. `GET /sources/saved-why/options` serves the four
reasons and an always-empty `projects`; `POST`/`PUT /sources/saved-why` still accept a retired reason (`technique`) and a
project (an edit may keep an archived one).

**G191 v3 bookmark writes** (both 409 in a demo bank and while Sleep holds the pages, both committed alone as
`Cicada-Author: user`): `PUT /sources/saved-why` `{url, at, reasons[], project?, text?}` changes the one answer given at
`at` (404 when there is none; its `at` and `addedAt` kept, `editedAt` stamped); `POST /sources/bookmarks/remove`
`{url}` archives the link's media page (never deleted) and stamps its episode `source_deleted_at` (trigger
`user/bookmark_remove`; 404 for a link not held, idempotent). `POST /sources/saved-why` gained `addedAt` (the moment of
saving it answers) and answers with `history`. The app reaches both through `Store.perform` (`SavedWhyWrite`,
`BookmarkRemove`), refreshing `.sources`. An entity node's hash also folds its derived
`contexts` and `summary`, so `GraphDiff` re-pushes a node whose derivation changed. `/projects` and
`/projects/{id}/timeline` (G141) ETag over `entities`+`episodes`+`inbox` with `extra` =
`projects|<shape>|<author shape>|<machine zone>` (`git_service.AUTHOR_SHAPE` since round 4, R4B-9) — never today, never a viewer zone — and are **not** Store domains
(no `VersionVector` mapping, fetched on demand like provenance). A timeline item carries at most
12 participants plus `participantsTotal`, and a cluster group at most 8 names no page holds yet
(round 4 D6; `PROJECT_SHAPE` g141-3). The person's writes (G141 PJ-3b) —
`POST /projects/{id}/milestones`, `PATCH /projects/{id}/milestones/{slug}`, `POST /projects/{id}/happenings`
(the Log: one time phrase becomes the day, a companion episode keeps the words), `POST
/projects/{id}/threads/{claim_id}` and `POST /projects/{id}/withdraw` (happenings only) — answer **409**
while Sleep runs and each commits alone over its own pages as `Cicada-Author: user`,
`user/companion_app`.

**The settings file (2026-10-13).** A developer checkout's settings file is `api/.env`, found by `api/settings_file.py`
from the package's own folder — **never the working directory**, so neither the repo root (the launchd backend's cwd)
nor an agent's project folder (an MCP server's or hook's cwd) can put a `.env` in its place. `Settings.env_file` is that
absolute path, so every process that builds `Settings` reads the file's `CICADA_` fields; **the environment always wins**
over it. The backend's entry (`api/main.py`, before any other import) also runs `settings_file.load()`: it forces
`LITELLM_MODE=PRODUCTION`, which turns off litellm's import-time `load_dotenv()` (it walks up from litellm's own folder,
so it read `api/.env` only when the venv sat inside `api/`, and the main checkout's file from a worktree sharing that
venv), then fills `os.environ` from the file without replacing anything already set — the outbound gates, telemetry,
the API token and litellm's provider keys read `os.environ`. The keys that reach `os.environ` are the ones litellm's
load put there before; every `claude`/`codex` child still runs under `scrubbed_env` (provider keys and plan overrides
stripped). A **release** (G182) has no settings file (`CICADA_DISTRIBUTION=release` turns the lookup off; the bundle
carries tracked files only): its settings are the launcher's and plist's environment, the app's own preferences, and
provider keys in `$CICADA_HOME/secrets.env`. The `cicada` command keeps its own bootstrap (`mcp.md`) and reads no file
through `Settings`. `GET /status` carries `settings`: `file` (`"api/.env"` or null), `fromFile`, `fromEnvironment` and
`replacedByEnvironment` (only where the environment's value differs from the file's; an equal value, as the plist's
memory path or the app-spawned developer backend's copy of the file, counts as from the file) — `CICADA_` names only,
never a value — and `effective`, the four values Sleep's pace and page
writing turn on (`agentMaxConcurrency`, `sleepResolveConcurrency`, `summarySynthesisEnabled`, `pageArticlesEnabled`).
The backend logs the same names once at startup. Settings → Advanced shows them (`app.md`).

`GET /status` has no ETag (the app refetches it whenever the vector's `sleep` component moves). Its `sleep.writing`
(G177) is `sleep_cycle.is_writing()` — the predicate behind every "Sleep is running" 409 — and the SSE `sleep` event and
the `sleep` component carry it too, so the app's write controls follow a drain's write window, not `running`.
`GET /sleep/status`'s paused run and the compact SSE paused block also carry `engineKind` (`transient | needs_fix`,
null outside an engine pause); legacy engine records default to `needs_fix`. The paused `sleep` component hashes
the kind and diagnosis, and its existing `VersionVector.swift` mapping to `.status` ships with the wire change.
The compact kind participates in SSE equality so a different engine diagnosis category refetches the full record.
The `engine` component (2026-10-08) is `<connections.json mtime_ns>.<size>`, plus `:<engine>/<model>` while a run of the
bank reads (the pair it pinned at its start): `$CICADA_HOME/connections.json` is outside every bank, so a
`PUT /sleep/engine` that did not come from the app moved nothing. No `VersionVector` mapping — the app's
`SleepEngineRefresh` reloads `GET /sleep/engine` on it; that body's `runKeepsEngine` is true while such a run reads on
an engine other than the one its kind (manual or scheduled) resolves to now.

**A request runs in one bank, and a write only in the bank it was made in (`bank_binding`, G183(d)).** One
app-wide dependency (`bank_binding.require_same_bank`, beside `require_token` in `api/main.py`) does two things:
- *The pin.* The active bank is resolved ONCE when the request starts and pinned for the rest of it
  (`bank_registry.pin_request_bank`, a ContextVar). `Settings.memory_path`, `bank_registry.active_bank_name`,
  `capture_bank` and the intake's target resolution answer the pinned bank, and the ContextVar follows the request
  into `run_in_threadpool` / `asyncio.to_thread` and into tasks it starts — so a switch while a request awaits a lock,
  a thread or its commit leaves it finishing in its own bank (`test_bank_binding.py` replays a picture upload parked on
  the real picture lock across an activation: upload and commit land in the original bank, nothing in the other).
  Reads are pinned too. Not pinned: the routes that change the active bank (`/banks/{name}/activate`, `/banks/demo`,
  `/banks/leave-demo`), bank CRUD that names its bank (`POST /banks`, duplicate, rename, import,
  `DELETE /banks/{name}` — a rename moves the active bank's directory) and the SSE stream `/sync/events` (it follows
  switches while open). Work that outlives its request is classified: a person-started Sleep run (a
  BackgroundTask of `/sleep/trigger`, `/sleep/parked/retry`) KEEPS the pin — it finishes in the bank it started in,
  and a switch is refused while it reads — and so do background work that is handed an explicit `memory_path` (the
  intake job, the bookmark enrichment, the paper resolver, the search-index / reading warmers; a `threading.Thread`
  starts with an empty context anyway). Unattended work CLEARS it: every scheduler job (`_run_if_idle`,
  `_run_after_intake_if_settled`, auto-continue's `_fire`) calls `bank_registry.unpin()` first, and `register_job` /
  the auto-continue arming call `add_job` through `bank_registry.run_unpinned`, so APScheduler's wakeup and timer
  callbacks never capture a request's pin — a schedule saved in A fires in the bank active when it fires. The remote
  listener's serving task starts in `bank_registry.unpinned_context()` (each request it serves gets a fresh context).
- *The check.* The app names the bank an operation STARTED in, percent-encoded UTF-8, on every POST/PUT/PATCH/DELETE
  (`X-Cicada-Bank`). A mutating request whose named bank is not the pinned one is answered
  `409 {"code": "bank_mismatch", "detail": "Memory switched before this was saved — nothing was written."}` before
  its handler runs. FastAPI parses the body before app dependencies (malformed JSON is a 422 whatever the header says,
  and a multipart upload is read first), so the refusal comes after body parsing but before schema validation and
  before anything is read or written. The name is compared exactly as decoded — never stripped or normalised, since
  two banks may differ only by a Unicode space; a header that is not UTF-8 matches no bank. A request without the
  header (the hooks, the MCP server, curl, an older app) is never checked. Not checked: bank CRUD (above), an intake
  import with an explicit `?bank=` (it names its target; without it the import writes into the active bank and is
  checked), the read-only `POST /intake/sniff`, and an engine connection's login, logout, key and preferences
  (machine-global, in `~/.cicada`). Reads are never checked. `bank_binding.EXEMPT` lists every exemption by route
  template, and a test keeps each pointing at a real route.

**The `cicada` command is a client too (G180 parity).** Its app commands (`api/cli_app.py`; `mcp.md`) call the
routes above as the app does: the bearer token from `CICADA_API_TOKEN` or `~/.cicada/api_token`, and `X-Cicada-Bank`
naming the bank the command pinned on every mutating request except bank CRUD, so the `bank_mismatch` check binds a
shell exactly as it binds the app. It reads the `code` of a 409 (`sleep_writing`, `bank_mismatch`) and never a
sentence. A route a browser front end would need is one the CLI can call: new features land behind a route, and the
app is one client of it.

**A Sleep-window refusal has a stable code.** Every route guarded by `sleep_cycle.is_writing()` raises
`sleep_refusal.SleepWriting` (an `HTTPException`, so a direct caller still reads `.detail`); the handler in `api/main.py`
answers `409 {"code": "sleep_writing", "detail": "<the route's sentence>"}`. Clients key off the code — never off
"sleep" in the body, since other 409s name pages (`claims block on <id>`) — and `detail` stays a string for older
clients. `test_sleep_refusal_code.py` scans `api/routers/` so a new guard cannot raise a plain 409.

`GET /videos/state` and `GET /videos/summary` (G162) ETag over `entities`+`episodes`+`sources`+`videoQueue` with
`extra` = `<name>|video-1` (`video_state.VIDEO_SHAPE`, which also rides both provenance ETags) and are **not** Store
domains (the app's `VideoStateCache` revalidates on `VideoRefresh`, no `VersionVector` mapping). The `videoQueue`
component is `<queue file mtime>:<how many leases, failed rows and finished batches have come due>`: a lease lapsing
writes nothing, yet changes the body, so the count is what moves the tag; both reads carry `nextChangeAt` so the app
schedules one revalidation there. The queue's writes (`PUT|DELETE /videos/queue/{key}`, `POST …/retry`,
`POST /videos/run/handoff`) touch no bank file: no commit, no 409 while Sleep runs, and none sits under `/capture/` or
`/sources/`, so queueing works in a demo bank (the demo's queue is a picture of the flow: `cicada_video_claim` and
`cicada_record_watch` refuse it). `GET /videos/run/prompt?count=&method=` is the pure preview.

**Skills (the Skills page, owner 2026-10-15; `routers/skills.py`).** The backend owns the logic; the app, the CLI's
person rows and the MCP tools share one set of bodies — `skill_folders` (the agents' folders, read-only), `skill_inventory`
(what the page shows), `skill_sources` (parsing and GitHub), `skill_tools` (uv, a tool's `skill` and `doctor`),
`skill_actions` (what a click does) and **`skill_store`, the one writer**. **The person's agents are one list,
`agent_wiring.AGENTS`** (Claude Code, Codex, Cursor, OpenCode, Hermes, OpenClaw, Gemini CLI — each with the skills
folder its docs name and the folders it also reads; an agent with none is left out of every skill list): the skills
table, the MCP schema's agent enum and the app (through `GET /skills`) all derive from it, and an agent whose home
folder is missing is hidden (`test_the_agent_list_is_one_place`). The rest: (`test_only_skill_store_writes_into_an_agents_
skill_folder`). Nothing is written into a bank: agent folders, and `$CICADA_HOME/skills/{library,drafts,removed}` plus
`requests.json`, `updates.json`, `onboarding.json`; write admission classes every route `OUTSIDE`.
- `GET /skills` — installed rows (source, version, `status` — `update|refresh|current|local|unchecked` —, update with
  `from` and its `changes`, agents, tool, permissions, details with an instructions `excerpt`),
  `suggested` (catalog, with `method` `tool|copy|manual|own`), `drafts`, `noticed` (the bank's held and page skills,
  G112), `requests`, `checkedAt`, `uv`, `jobs`. No ETag: not a Store domain.
- `POST /skills/check {auto}` — fetches upstream: a repo-folder skill's newest commits that touched its folder
  (against the commit recorded at install) or a tool's/tag's newer releases, each with its `changes` (≤ 20, titles and
  cut notes) and a compare or release link. `auto` (the page opening) only past an hour; a click past a minute.
- `POST /skills/preview {source, choose?}` → `{planId, name, description, skillMd, files, scripts, repo}` or
  `{choices}`; `POST /skills/install {planId | suggestion, agents, requestId?}` installs exactly the preview's files at
  its commit (a plan lives 30 min in memory), or a catalog suggestion at its reviewed pin (a tool: a job).
- `POST /skills/{name}/update` and `/skills/update-all` (jobs), `PUT /skills/{name}/agents/{agent} {on}`,
  `POST /skills/{name}/refresh`, `DELETE /skills/{name}`, `POST /skills/drafts/{name}/publish {agents}`,
  `DELETE /skills/drafts/{name}`, `POST /skills/requests/{id}/dismiss`, `GET /skills/jobs/{id}`.
- `GET /skills/onboarding` (the three suggestions, their defaults, uv, the earlier answer) and `POST /skills/onboarding
  {install, agents}` — the answer is recorded (an empty list is "No thanks"), and the rest installs as a job.
- **Fetches** go through `net_guard` (a hook on every hop), 4 s, ≤ 512 KB per response, no cookies, no token, ≤ 64
  files / 5 MB per skill; only on the person's click or the open page, never in Sleep, never an agent's call. A refusal
  is 400 (a source or GitHub problem) or 409 (a write the store refuses), each with a sentence.
- **Commands** (uv, `<tool> skill`, `<tool> doctor`) are argvs through `connections.base.run_cli` (scrubbed env,
  `CICADA_CAPTURE=off`), bounded; a uv install is pinned to a commit (`git+https://github.com/<repo>@<sha>`).
  `doctor` reports permissions for the app that started the tool, so the page names that app.

**Endpoint traps worth knowing before you touch them:**

- `GET /entities/{id}/claims` answers every belief on the page (an owner-sized page's are ~6 MB of JSON, ~90 ms to
  decode in a debug app); `?predicate=` (repeatable) keeps only those predicates. The entity card reads the whole list
  only when a section or tab asks, and a person's Works at / Role cells with `?predicate=` when it opens. Not a Store
  domain, no ETag; read in memory per card.

- `GET /entities/{id}` and `/entities/{id}/context` serve `markdownContent` **without the claims fence** (F4: the
  claims are `/claims`; an owner-sized page shipped its 2.5 MB fence twice per card open). `/provenance`'s
  `pageBodyHash` and section `bodyRanges` describe that same served text (`claims.served_prose` maps the offsets; a
  ```` ```claims ```` example inside another code fence is literal code and stays, as the section scanner reads it; an
  item whose range would cross a removed block gets no ranges rather than shortened ones).
  `rawMarkdown` is the whole file up to `RAW_INLINE_MAX_BYTES` (256 KiB); above it (and only when the file has a
  closed fence) it is the file verbatim *up to its first claims fence* with `rawOmitted: true` — every frontmatter
  reader keeps its input — and the Source view and Copy read `GET /entities/{id}/raw` for the whole file. The fence is
  also withheld when it alone is over 16 KiB, and a page whose older claims live in its ledger sends its frontmatter
  alone (its prose is `markdownContent`; owner page 2026-10-14: 490 KB → ~275 KB on a synthetic page of the measured
  shape). The card's decay pace reads only the page's own conversations' `source:` lines (`episode_time.untimed_among`,
  one awk pass), never a YAML parse of every episode — that scan was 4.4 s of a 4.4 s cold first open there. A client
  never treats that head as the file, and never substitutes a reconstruction when `/raw` fails (`RawFile`).
  Neither is a Store domain: no ETag, no `VersionVector` mapping.
- `GET /entities/{id}/history/{commit}/diff` — a file's FIRST commit has no parent, so `git show`
  diffs it against the empty tree and it comes back all-adds; a MERGE commit needs `--first-parent`,
  else git emits a combined (`--cc`) `@@@` diff the parser can't read and the endpoint silently
  returns nothing. `truncated` is the UNION of three caps; `linesTruncated` specifically means "the
  ordered list was cut" and is what a client renders its banner on.
- `GET /conversations/recent` is **CAPPED** (limit ≤ 200) and is never a membership test; filters
  (`harness`, `origin`, and `q`, a title filter) apply BEFORE the cap. Use `GET /conversations/{id}` to
  resolve one id against the whole bank.
- `GET /search` runs in the threadpool. `mode=prefix` (the per-keystroke pass) is FTS only and never
  loads the embedding model; `mode=hybrid` (the default) fuses FTS with the stored vectors and reports
  `mode: lexical` when no vector index answered. `totals` are exact **lexical** counts — semantic
  neighbours are ranked, never counted. An `indexState` other than `ready`/`stale` means entities and
  media only, from the frontmatter cache. No ETag: it is never a Store domain. Its query string (and
  `/conversations/recent`'s) is stripped from uvicorn's access log; a new query-bearing GET joins
  `_QUERY_PATHS` in `api/main.py`.
- `POST /conversations/{id}/resume` returns a validated descriptor — **transcripts are never read,
  `isfile()` only**.
- `POST /banks/demo` re-opens a demo bank that exists (200, never re-populated); a real bank that happens to be called
  `demo` still answers **409**. `POST /banks/leave-demo` activates the real bank left most recently (else `default`, else
  a new `my-memory`) and changes nothing outside the demo.
- `POST /maintenance/enrich-links` returns `409` both while a Sleep cycle runs and while another
  call is still running (a process-local lock — two overlapping clicks would stage each other's
  half-written pages under their own trailers).
- **Inside Sleep's write window (G177, `sleep_cycle.is_writing()`) these answer `409` with a sentence in `detail`, and
  go through between a drain's batches:** `PUT /entities/{id}/decay`, `PATCH /entities/{id}/repos` (which commits only
  its page, never `git add -A`), every `POST /inbox/{id}/resolve` action — a defer too — and the deprecated
  `/nudges/{id}/resolve` and `/clarifications/{id}` that route through it, and `POST /maintenance/dedup-sweep` (a dry
  run too; G183), `PUT /settings/owner` and every project, backlog, entity source and picture write. Each asks while
  holding the bank's write admission and keeps it through its commit, on the writer loop (a cancelled
  request, or its loop's teardown, does not release it early); Sleep sets its flag and then waits out every holder before it reads a page, and
  pauses rather than read past one it waited 60 s for (`storage.md`, "Write admission"). The sweep asks per merge,
  before the page lock; an inbox conflict answer's prose is synthesized before admission and used only if its
  inputs (item, pick, page, sentence) did not change. The decay and repo rewrites run write → scoped commit as one page-lock section in a worker thread, an edit
  already on the page committed apart first. The sweep answers `stoppedForSleep`, `skippedDirty`, `skippedUnsafe`,
  `failed` and `recoveryFailed` beside its merges.
  `POST /entities/{id}/read` (a ledger row) and `POST /entities/{id}/repos/observed` (a cache outside the bank) write no
  page and are never gated. MCP's `cicada_resolve_inbox` relays a 409's sentence to the agent.
- `GET /sync/version` is the cheap change-detector (<10 ms); `GET /sync/events` is the SSE stream.
  Its idle cost is shared (audit 2026-10-02 A10): `sync_ticker.current` computes the version vector and the Sleep debt
  at most once per 0.9 s per bank, and concurrent streams await that one computation. Its filesystem half runs in
  worker threads under `bank_index.shared_scans()`, which lists each directory once per tick, and `sleep_debt.compute`
  scans in a thread for `/sleep/status` too. Every tick is still a full scan, so an external in-place edit is seen on
  the next tick. `/sync/version` and `/sleep/status` never read the shared tick. Measured on generated banks
  (1,900 entities):
  - 10,000 episodes: 42 → 24 ms per tick for one stream, and 169 → 25 ms for four.
  - 2,000 episodes: 12 → 6 ms for one stream, and 50 → 6 ms for four.
- **A version stamp is a fingerprint, never "the newest mtime"** (audit 2026-10-05 P2-9). With one file dated in the
  future, an edit to any other file left the max where it was: `/sync/version` stood still, every ETag built on it
  answered 304 and the graph cache served the old page. The `entities`, `hubs`, `inbox`, `episodes` and `sources`
  components, the `backlog` stamp and the graph cache key hash every file's name, size and nanosecond mtime
  (`bank_index.dir_fingerprint`, over the same shared scan; ~2.6 ms of hashing for 10,000 files). The component
  names are unchanged, so the app's `VersionVector` mapping is too — a value is opaque to the client, and each ETag
  moves once when the new stamps first appear.
- `GET /projects[/{id}/timeline]` serve absolute days (`tzName` is the machine zone they are bucketed
  in) and never a relative word; the client derives 'yesterday', 'overdue' and 'quiet' through
  `project_state.timeline_state` (its Swift twin shares `api/tests/fixtures/timeline_state.json`). A
  404 means no page or not a `project`.
- `POST /intake/import` answers **202** with `{job}` when more than 10 episodes would be written; poll
  `GET /intake/jobs/{id}` (process-local — gone after a restart or an hour; the episodes are not). One
  stage runs at a time per process.
- `POST /conversations/upload` is a deprecated shim over the one intake — new callers use
  `POST /intake/import`; its `turns` sidecar is a list, as on Stop-hook episodes since G141 PJ-4 —
  only a Stop-hook episode written before PJ-4 holds an **integer count**, so a reader checks the type.
- `GET /memory/decay-suggestions` / `PUT /memory/decay-tuning` (G147) are not Store domains and carry
  no ETag; both answer one shape (`bank`, `windowDays`, `tuning`, `suggestions` — types and counts,
  never a page id). The PUT merges `{type: multiplier | null}` within [0.25, 3.0], answers **409**
  while Sleep runs, and commits `_decay_tuning.yaml` alone as `Cicada-Author: user`.

---

**Claim-read clocks (G118/G93, 2026-10-07).** Entity provenance and episode
citations include `validity2` and the shared current machine-local day in their ETag
recipes. Closure semantics invalidate an older cached response; a stated end
or future start changes currentness at midnight even if no page was edited.
These are on-demand reads with in-memory caches, not Store domains, and add
no VersionVector component or wire field. Search's Swift decoder now consumes
its already-existing event day/state fields so a closed event stays dated.
