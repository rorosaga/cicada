# API design

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

35 routers mounted in `api/main.py`, plus repo-context and maintenance endpoints. **Read the routers
for the endpoint list** — it is not duplicated here. What is *not* derivable:

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
the same files (F1's context filter and fence strip); an entity node's hash also folds its derived
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

`GET /videos/state` and `GET /videos/summary` (G162) ETag over `entities`+`episodes`+`sources`+`videoQueue` with
`extra` = `<name>|video-1` (`video_state.VIDEO_SHAPE`, which also rides both provenance ETags) and are **not** Store
domains (the app's `VideoStateCache` revalidates on `VideoRefresh`, no `VersionVector` mapping). The `videoQueue`
component is `<queue file mtime>:<how many leases, failed rows and finished batches have come due>`: a lease lapsing
writes nothing, yet changes the body, so the count is what moves the tag; both reads carry `nextChangeAt` so the app
schedules one revalidation there. The queue's writes (`PUT|DELETE /videos/queue/{key}`, `POST …/retry`,
`POST /videos/run/handoff`) touch no bank file: no commit, no 409 while Sleep runs, and none sits under `/capture/` or
`/sources/`, so queueing works in a demo bank (the demo's queue is a picture of the flow: `cicada_video_claim` and
`cicada_record_watch` refuse it). `GET /videos/run/prompt?count=&method=` is the pure preview.

**Endpoint traps worth knowing before you touch them:**

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
  run too; G183). Each re-asks once it holds the page lock (the inbox after its awaited snapshot), before writing; Sleep
  takes no page lock, so this narrows but does not close the race (`storage.md`, "Residual race"). The decay and repo
  rewrites run write → scoped commit as one page-lock section in a worker thread, an edit already on the page committed
  apart first. The sweep answers `stoppedForSleep`, `skippedDirty`, `failed` and `recoveryFailed` beside its merges.
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
