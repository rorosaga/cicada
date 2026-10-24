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
connectors registry rather than hardcoding a literal per adapter. **`/healthz` is open but says more to a token**
(owner decision 3, 2026-10-16): without one (or with a wrong one) it answers only `status`, `version`, `bankId` and
`bankIds`; the memory's path and root, the counts, the embedding mode and model and the index state are filled only for
the master or an active device token (`auth.bearer_admits`; `response_model_exclude_none`, so an absent field is
absent, not null). Every client that reads those fields sends its token: the CLI's ruling-21a probe
(`cli_app.probe_backend`), `scripts/doctor.sh` (the header from `~/.cicada/api_token` through curl's stdin, never a
command line) and the app (`APIClient.fetchHealth`); the installers and the server check need only `status`, and the
app's server check only `version`.

**Bounds before any route (backend hunt, 2026-10-16; `request_limits`, a pure ASGI middleware).** A path segment
longer than a file name (255 bytes, decoded) is **404** before routing — a 3,000-character id used to reach
`Path.exists()` and answer 500 (`ENAMETOOLONG`). `POST /capture/session` (8 MB) and `PUT /sources/messages/photos`
(24 MB) refuse a body past their ceiling with **413**, at once from a declared `Content-Length` and, without one, the
moment the streamed bytes pass it; a Messages photo whose base64 is longer than a 256 KB photo can be is refused
before it is decoded (`messages_photos.B64_MAX`, 422 as before).

**Schedule and reading options (ruling 4b, owner decision 2).** `GET/PUT /sleep/schedule` answer the schedule plus,
while it runs on its own, `warning` and `warningCode` when a scheduled run would have no engine it may use
(`ScheduleResponse`, `engine_readiness`); the PUT body is unchanged and the app never sends them back.
`GET/PUT /sleep/run-options` carry `scheduledUsePlan` (machine-wide, on unless the person turned it off — ruling 4c,
2026-10-19; an off is stored as `false`; `null` is 422).
`POST /ask` with no engine — an API model with no key, or Auto with no plan and no local model (ruling 31: never a key
nobody chose) — answers that it has no engine, naming the pages it found, and calls nothing.
**The web-check sweep (ruling 27b, 2026-10-19).** `POST /inbox/web-check?dryRun=true|false[&limit=N][&includeRecent=true]`
answers counts only (dry run) or `{"status": "started"}` and runs in the background; `GET /inbox/web-check` its counts.
409 while Sleep, the tidy or another sweep runs. Not a Store domain, no ETag (`features.md`).

**Device tokens (G181 phase 2, owner ruling 1, 2026-10-16).** A second machine of the person's never gets the master
token: each device gets its own **named, hashed, revocable** token (`device_tokens`, the G135 store's shape kept apart:
`$CICADA_HOME/devices/devices.db`, 0700/0600, sha256 only, `cic_dev_<id>_<secret>`, no expiry, revocation immediate).
Issuing is the person's act on the server (`POST /devices` answers `sameName`, the active devices already called that,
for the client to warn about): `cicada device add <name>` (person-only) or `POST /devices` with the master
token, which answers the token once (201); `GET /devices` lists (no token), `DELETE /devices/{id}` revokes. A device
token opens every route but `/devices*` and the `POST`/`PUT`/`PATCH` writes under `/remote` (403: minting, rotating
or turning on a G135 connector would leave a credential that outlives the device's revocation; a device may still read
and revoke) and `auth.require_token` puts the device on `request.state.device` — the
only way the server learns a call came from another of the person's machines; nothing in a header or body can claim
it. `/devices*` touch no bank (`bank_binding.NO_BANK_WRITE`). On the client the token is `CICADA_API_TOKEN`, else
`$CICADA_HOME/device_token` (0600, put there by the person), read by `runtime_layout.client_token` for the hooks, the
stdio MCP server and the CLI; the base URL is `CICADA_API_BASE` (`runtime_layout.api_base`: https, or http to a
loopback tunnel only). No installer creates, copies or logs either.

**Pairing a device with a one-time code (G212, 2026-10-22).** `POST /devices/pairing` (master token only, under
`/devices`; body `{url?}`) answers 201 `{pairing: {id, createdAt, expiresAt, state, deviceId}, code, qr: {v: 1, url,
code}}` — the app draws `qr` as a QR code (JSON, compact) and shows `code` (`XXXX-XXXX`, 31 unambiguous symbols, no
I/L/O/0/1) beside it. `url` is where the new device will reach this server (https, or http to loopback only — the
client rule; never fetched; null when omitted). The new device posts `POST /pair` `{code, name}` — an **open** path,
the code being its credential, any case, dash optional — and gets 201 `{device, token}`: its own `cic_dev_` token,
named by what the device reports (`clean_name`), exactly as `POST /devices` issues one. A code lives 10 minutes, is
spent by the first redeem in the statement that checks it, is kept only as its sha256 (`devices.db`, table
`pairings`), and at most five wait at once (409 past that). Unknown, used, cancelled and expired codes are one 404;
`/pair` answers at most ten a minute (429). `GET /devices/pairing/{id}` says `waiting | paired | cancelled | expired`
(and the device once paired, so the app closes its QR); `DELETE /devices/pairing/{id}` cancels. All outside every
bank (`NO_BANK_WRITE`). **Hyrum, mode A:** stable — the paths, `qr`'s three keys and `v: 1`, the code's alphabet and
`XXXX-XXXX` spelling, `state`'s four words; not stable — the 10-minute life, the five-code cap, the rate.

**A phone is capture-only; the QR knows this machine's tailnet name (G212, owner 2026-10-22).**
- **Kinds.** `POST /devices/pairing` takes `kind: "capture"` (the default — a phone) or `"full"` (another computer);
  the answer adds `kind` and the pairing and device wires carry it. `cicada device add` and `POST /devices` issue
  `full`, as before; a store from before the column reads every device as `full`. A **capture** token reaches exactly
  `POST /sources/save`, `POST /capture/note`, `POST /capture/file` (G91, ruling 38) and `GET /capture/mine`
  (`auth.CAPTURE_ROUTES`, exact paths) — every
  other route, the device routes included, is 403 "this device may only send captures" — and `/healthz` gives it the
  open answer (status, version, bank ids; never the memory's path or counts). So a phone validates its token with
  `GET /capture/mine`, not `GET /devices`.
- **The QR's `url`.** `qr` is still exactly `{v: 1, url, code}`. With no `url` in the request the backend fills it from
  the person's own `tailscale serve` of the backend port: one bounded (2 s), read-only `tailscale funnel status
  --json` — the same ServeConfig read `GET /remote/status` already makes, no new command, no LocalAPI socket
  (`reach.tailnet_backend`). The ServeConfig is the only local answer that proves an address reaches the backend; the
  machine's DNS name alone would put a URL in the QR that leads nowhere until the port is served. A serve that is also
  **funnelled** is never used (`reach.public: true`): the backend has no public port (G181). The answer's `reach`
  (`{tailscale, url, public, serveCommand}`, null when the request named a `url`) says what the person would run when
  nothing serves the port: `tailscale serve --bg --https=8443 <port>` — tailnet only, 8443 because 443 is where the
  G135 listener's funnel goes and a port is served or funnelled, never both. Cicada never runs it.
- **A thought in the person's words: `POST /capture/note`** `{text, title?, id?}` (demo-gated, Awake: no Sleep gate, no
  model). One `user:` turn — the person's own words, never `origin: mcp` — staged through `episode_staging` (scrub,
  one writer, `source_id` `note:<device>:<id>`), queued for Sleep, `device` stamped; `origin: phone` from a capture
  device, `note` from any other token. Its identity is `id`, else the `Idempotency-Key`, else the words themselves.
  Answers `{status: created|updated|unchanged, episodeId}`. Links stay on `POST /sources/save` `{url, note?}`.
  **A voice note (G91, ruling 38, 2026-10-23):** `kind: "voice"` (default `"text"`) when the phone transcribed the
  person's speech on the device — no audio is ever sent, and no model runs here; the episode records `note_kind:
  voice` and its default title is "Voice note". A typed note records nothing new; an older server ignores the field.
- **A photo or a file: `POST /capture/file`** (G91, ruling 38; demo-gated, Awake: no Sleep gate, no model reads the
  file). Multipart: `file` plus `caption?` (the person's own words, ≤ 16k), `title?`, `id?`. Accepted by the bytes,
  never the client's word: JPEG, PNG, HEIC (magic bytes), PDF (`%PDF-`), and plain text only when declared
  `text/plain` or `.txt` **and** valid UTF-8 with no NUL — anything else is 415; past 25 MB is 413 (`capture_files.
  MAX_BYTES`; `request_limits` refuses a declared body past 26 MB before it is spooled), empty is 400. Images are kept
  exactly as sent, HEIC included: the server keeps no image library, a headless Linux host has no `sips`, and a
  re-encode would lose the person's original for nothing capture needs.
  - **Where the bytes live:** outside every bank and git repo, `$CICADA_HOME/files/<bank>/<sha256>.<ext>` (0700/0600,
    content-addressed, written atomically before the episode), never served back. The rail is the one site captures
    and Messages photos keep: pixels the scrub cannot clean never enter the bank, so **no thumbnail in the bank either**
    (a site capture showing the person's account keeps even its thumbnail outside). A photo's EXIF stays with it.
  - **What the bank holds:** one episode through `episode_staging` (scrub, one id rule, queued for Sleep, `device`
    stamped, `source_id` `file:<device>:<id>`): a `user:` turn with the caption then `[image: <name>]` or
    `[file: <name>]` (Messages' attachment shape), the file in `turn_extras` (name, size, type, never a path), and
    `file: {kind: image|pdf|text, mime, name, size, sha256}`; a plain-text file's words are a second `user:` turn
    (scrubbed, first 16k characters), as a shared text already is. `origin: phone` from a capture device,
    `device-file` from any other token (its own Sources row, "Files from your devices"). Identity: `id`, else the
    `Idempotency-Key`, else the bytes (the same file twice is one episode). Answers `{status, episodeId, file: {kind,
    size, sha256}}`. Sleep reads the caption and a text file's words; describing a picture or reading a PDF's pages
    is G195's and G91's later business.
- **`GET /capture/mine`** (a device token): the asking device's newest captures, at most 20 of the newest 500
  episodes — `{captures: [{id, title, timestamp, processed, url}]}`, never a body, never another device's.
- **`Idempotency-Key`** on `POST /sources/save`, `POST /capture/note` and `POST /capture/file`: a resend with the same key gets the first
  answer and writes nothing (`idempotency`). Measured on a scratch server: a link with a note resent **without** a key
  writes one more "Note on …" episode; with the key, none. Keys are scoped to the sender (`device:<id>` or `server`),
  the pinned bank's id (a replay after a bank switch runs in the bank now open) and the route, kept as sha256 with the answer's JSON in `$CICADA_HOME/idempotency/keys.db` (outside every bank),
  for 24 h; only a 2xx is kept, so a refused save (Sleep, a bad link) runs again.
- **Hyrum, mode A:** stable — the two kind words, `CAPTURE_ROUTES`' four routes (`/capture/file` added 2026-10-23, an
  addition only: no route left the set), `qr`'s keys, `reach`'s four keys, the note and mine shapes, the note's two
  `kind` words, the file route's form fields and answer keys, the episode's `file:` record keys, the header name; not
  stable — the 24 h TTL, the 20/500 limits, the suggested 8443, the 25 MB cap, the `$CICADA_HOME/files` layout.

**The agent API (G213, 2026-10-22).** For an agent that speaks HTTP but not MCP. `POST /v1/<op>` with
`Authorization: Bearer <connector token>` and a JSON object body. **Generated from the remote tool table (ruling 38,
2026-10-23):** every `REMOTE_TOOLS` entry is exactly one operation unless `agent_api.EXCLUDED` names it with its reason
(only `cicada_handshake`: `GET /v1/me` and `llms.txt` carry it), so the same token gives the same powers on `/mcp` and
`/v1`, and the stdio-only tools (`continue`, `edit_page`, the saved-list and profile reads, explore, design, skills)
stay off both. 27 operations. **Stable, frozen as #424 shipped them:** `recall`, `ask`, `page`, `timeline`,
`project`, `save_note`, `save_url`, `write_claim`, `retract_claim`, `inbox`, `resolve_inbox` (`agent_api.STABLE`;
`cli_map`'s `api_op` column spells the seven that are not their CLI command). **Added, each its `cli_map` command
spelled with underscores (`Row.operation`):** `hub`, `perspective`, `source_list`, `source_add`, `source_change`,
`progress_add`, `backlog_list`, `backlog_add`, `backlog_note`, `inbox_record_check`, `video_queue`, `video_claim`,
`video_record`, `read_queue`, `read_record`, and `capture_turns` (remote-only, so named in
`agent_api.REMOTE_ONLY_OPS`: a relayed turn is stored `evidence_kind: assistant` with `relay.connector`, never the
person's own words). **One episode per conversation (ruling 32, G104):** `capture_turns` alone keeps the
`conversation` argument on `/v1`. `"conversation": "new"` starts one — Cicada mints the handle (`mint_handle`) and
answers it as `data.conversation` — and every later turn passes that handle back; a handle another token got (or any
other string) is 400 `invalid_arguments`, nothing written, never merged into someone else's record. With no
`conversation` a turn goes to the token's day bucket (`rc_<id>_<day>`) — the documented fallback, as on `/mcp` without
a handle — so a caller relaying two conversations a day must start each with `"new"`. `test_agent_api.py` pins the operation set to
`REMOTE_TOOLS − EXCLUDED`, the eleven names to their tools, each new name to its row, each operation's scope to
`catalog.TOOL_SCOPE`, and `/v1/openapi.json`'s validity; a tool added to one table and not the other fails CI.
Each operation is one remote tool (`api/remote/agent_api.OPS`), its arguments the remote schema's minus
`conversation` (except `capture_turns`, above), run through the shared
`RemoteRuntime` (scopes, G199 contract, Sleep and demo gates, the daily `ask` cap, fenced reads, `connector:` and
`origin: remote:<id>` provenance, one ids-only `remote_call` row). Every answer is `{text, isError, code, data}`:
200 (isError true for a body's refusal), 400 `invalid_arguments`, 401 `invalid_token`, 403 `denied` / `origin`,
404 `unknown_operation`, 409 `sleep_writing` (with `Retry-After`) / `demo`, 413 `too_large`, 429 `capped` /
`rate_limited`, 500 `error` (the class only). `GET /v1/me` names the token, its scopes, expiry and operations;
`GET /v1/openapi.json` (OpenAPI 3.1, generated from the remote schemas) and `GET /v1/llms.txt` = `GET /llms.txt`
describe it and are open. `/v1/*` sits outside the app-wide bearer check (`auth._OpenPaths`) and checks its own:
**only a connector token** — the master token and a device token are the person's machines, an agent is not, so both
are 401 there. Any `Origin` is refused. The same API rides the G135 listener (`network.md`). **No third door**
(ruling 38): an MCP client uses `/mcp`; everything else uses `/v1` and `/v1/openapi.json`. A scope-denied or malformed
call answers the same sentence and `code` on both doors (one `RemoteRuntime.call`, one `tool_contract`); `sources`
gates every verbatim word on `/v1` as on `/mcp` (`ToolContext.raw_excerpts`).
**Agent tokens:** `POST /agent-api/tokens` `{name, scopes?, expiresInDays?, baseUrl?}` (master only:
`MASTER_ONLY_WRITE_PREFIXES`) makes a connector row with `auth: "api"` and answers once `{token, agent, prompt,
baseUrl}` — `cic_api_<id>_<secret>`, scoped (default `search`/`read`/`record`), expiring 7/30/90, revocable at
`DELETE /agent-api/tokens/{id}`, listed at `GET /agent-api/tokens` and never in `GET /remote/connectors`; `prompt` is
the one paragraph the person gives the agent (base URL, the header, "read llms.txt first"). It opens `/v1` only,
never `/mcp`, and is never rotated (revoke and make a new one). Its writes carry `harness: agent-api` (an enum, for
frontmatter and the ledger) and `Cicada-Author: api:<name>` (the agent's name as the person typed it, `[a-z0-9-]`,
≤ 32), a `harness` contributor. **Why the connector token, not a device token:** a device counts as local (ruling 28:
the G198 trust list, every route); a third-party agent must be scoped, expiring and never the person's own words —
exactly a connector. **Hyrum, mode A:** stable — the paths, operation and argument names, the envelope's four keys,
the status codes and their `code` words, the `cic_api_` prefix, `api:` authors; not stable — reply wording (which may
name a `cicada_…` tool; `llms.txt` maps each to its operation), `data`'s shape, the documents' prose, the rate limits.

**Phase 3 (G181, 2026-10-16): the app as a client, and where memory came from.**
- `GET /devices` is open to a device token too (read-only: `auth._DEVICE_READABLE`), so the app's Settings → Devices
  can show the person their devices from any of them; each row adds `current` (the device whose token asked). Issuing
  and revoking stay the master token's (403). Ids, names and times only; `lastUsedAt` is "last seen" (stamped at most
  once a minute by `device_tokens.touch`).
- `auth.require_token` also binds the device for the request (`device_context`, a ContextVar): a NEW episode written
  while serving a device's request records `device: <id>` (`episode_ids.create_episode`, unless its writer set one),
  so every door a device posts through — the app's readers, an upload, a save, a session, a tool call — carries it
  without each route threading it. The master token binds nothing. `sleep_cycle.run` clears it first: a client's
  click may start Sleep inside its own request, and nothing Sleep writes is that device's.
- The device rides three reads, ids only (the app names it from `GET /devices`): `GET /sources` rows (`device`, from
  the save's episode; `SHAPE` `device-1` moves the ETag once, and the app's `SnapshotCache.schema` is 3 in the same
  change), `GET /entities/{id}/provenance` conversations (`device`, the newest one in the group) and
  `GET /episodes/{id}/text` (`device`). The last two are not Store domains.
- `CICADA_API_BASE`, else the app's `$CICADA_HOME/api_base` (written only on the person's click in Settings → Devices,
  0600): `runtime_layout._raw_base` and its stdlib twin `hook_client.raw_base` read the file only from the real
  environment or one that names its own `CICADA_HOME`, so a test's bare dict never reaches a home.

**The connection model's routes (G217, G205, G212, G50/G215; 2026-10-22).** Backend only; the app's redesign reads them.
- `GET /providers` — the one table (`agent_catalog`): `{providers: [{id, label, logo, tier, ways: [{id, label, connects,
  tier, clients, setup, remoteApp, pill, note, remoteLabel}], intelligence: [{connection, label, kind, note}], later}], pills,
  featured}`. One umbrella per provider, one logo slug each (the shared logo set's); `connects` ⊆ `stdio hooks remote rest
  messages export`; `setup` ids are `GET /agents/setup` harness ids; `intelligence.connection` is a `GET /connections` id.
  `remoteLabel` (additive, ruling 39) names a way that is two products where it arrives through the remote
  connector or its export (`claude`: `Claude Desktop` here, `claude.ai` there); null when one name fits.
  Static per release, no ETag. **Stable:** `providers[].id`, `ways[].id` (they are `/agents/live` ids), `logo` slugs,
  the `connects` words. **Not stable:** order, labels, notes, tier-3 rows.
- `GET /agents/live` now answers every tracked way (`agent_catalog.TRACKED`): the eleven pills first in their old order
  and spelling, then the rest (tier 2 and 3); a non-pill way also lights `other`, as an unmatched client always did. A
  fourth signal, the last-seen registry `$CICADA_HOME/agents/seen.db` (`agent_seen`: catalog id, device id, `mcp|tool|
  remote|call`, times, a call count — never a raw client string, query or path), is stamped by the stdio server on
  `initialize` and every call and by `POST /tools/call`, at most once a minute per process, so detection survives
  `CICADA_TELEMETRY=off`. Row shape unchanged (`via` stays `mcp|remote|config`).
- `GET /agents/live` rows gain `lastCalledAt` (onboarding v3, 2026-10-24, additive): the agent's latest tool call — a
  stdio `tools/call` (stamped `via: call` beside the `initialize`'s `mcp` row) or `POST /tools/call` (`tool`) — and
  never a connect, so a harness's own wiring check (`claude mcp get`, which initializes as the agent) never moves it.
  Null until one; onboarding's Agents step confirms a first call from it. `lastSeenAt` and `via` are unchanged (`call`
  counts as an MCP sighting).
- `GET /devices/status` — `{devices: [{id, name, role: server|device, current, connected, how, lastSeenAt, queue}],
  connectedWithinSeconds}`: this server first, named by its own Computer Name (macOS `scutil`, else the host name),
  then each active device token by the name the person gave it. `how` is read from the device's last request
  (`agent_seen.how_from_request`: a Tailscale Serve header or tailnet address → `tailscale`, another private address →
  `lan`, a device token on loopback → `ssh`), stamped in `auth.require_token` once a minute. `queue` = that machine's
  episodes still waiting for Sleep (`device` frontmatter; none = this server). Device tokens may read it. No ETag.
- **Agent requests (G205).** `POST /agent-requests {site, reason?, agent?, kind?: "sign_in"}` → 201 `{id, kind, agent,
  agentName, umbrella, logo, site, reason, createdAt, notification: {id, title, body, openUrl}}`; 422 for a non-host
  site or an unknown kind; 409 in a demo bank. A `needs_login` from `cicada_record_read` or `cicada_record_check` files
  one too, naming the agent by the surface it asked from (row `via: local|remote`; a remote-connector request of
  `claude` is `claude.ai`, a local one `Claude Desktop`, a row without `via` `An agent`). Stored in `$CICADA_HOME/agent_requests/<bank>.json` (outside every bank, flock + atomic
  replace, 14-day expiry, one open request per agent·site·reason). `GET /inbox` serves them first as `kind:
  "agent_request"` with `request` set and options `done` / `dismiss`; `POST /inbox/{req-…}/resolve` with `optionKey`
  `done` lifts the site's `needs_login` pause, `dismiss` only closes it — never a bank write, no Sleep gate, 403 when
  `via: "agent"` or a relayed quote rides along. Never served in a demo bank; agents never see the kind
  (`APP_ONLY_INBOX_KINDS`). The requests file's mtime folds into the `inbox` sync component only once one exists, so
  `/inbox`'s ETag moves with it and a bank that never had one keeps its old stamp.
- **Keys are checked before they are saved (G50/G215).** `PUT /connections/byok-<p>/key {key, check?: true}` first makes
  one free, authenticated GET of the provider's own model list (OpenRouter: its key endpoint) on a fixed host
  (`key_check.PROBES`), 6 s, through `net_guard`, nothing logged: 422 "This key was refused by <brand>" (401/403; 400 for
  xAI and Gemini, measured) and nothing saved; 503 when the provider could not be reached — the app offers `check:
  false`, "Save without checking". A key card's status adds `keyHint` ("…1234"; no route returns a key), `keyStore`
  (`file` | `environment`), `verifiedAt` (`$CICADA_HOME/key_checks.json`, names and times) and `termsNote`. New cards:
  `byok-fireworks`, `byok-deepinfra`, `byok-together`. The xAI default moved off the retired `grok-4-1-fast-*` to
  `xai/grok-4.20-0309-non-reasoning`, priced by `price_supplement` (a row LiteLLM 1.83.4 lacks, with its basis; a newer
  table wins).

**Bank identity (G181 phase 2).** Every bank's `banks.yaml` record carries a random `id`, minted by the backend at
startup (`bank_registry.ensure_bank_ids`, which persists a legacy root's synthesized registry with no change to
resolution), by `create_bank` and by `duplicate_bank` (a copy is another bank); a rename keeps it. `GET /healthz`
reports `bankId` (the request's bank) and `bankIds` (every bank in the root) — ids only, never a name, since it is
unauthenticated; `GET /banks` carries each bank's `id`. A mutating request may name the id in `X-Cicada-Bank-Id`
beside `X-Cicada-Bank`; either mismatch is 409 `bank_mismatch` before anything runs.

**`POST /capture/session` and `POST /tools/call` (G181 phase 2).** The first takes a Claude Code or Codex session read
on the client by Cicada's own extractor (`capture-and-sleep.md`, "A session from another machine"), with an optional
`utc_offset_minutes` (−840…840; ruling 34, also on `/capture/turn`) so the id it mints carries the client's local day; the second is the
tool door (`mcp.md`, "A client of a server on another machine"). Both run their work off the event loop; the door
answers `{text, code, data, error, state, bank}` with 200 for anything a body said (a body's exception is `error`, the
stdio server's `Error: …`), 404 for an unknown tool and 403 for a tool the command-line surface does not hold.

**ETags.** `/graph`, `/inbox`, `/contributors`, `/sources`, `/sources/channels`, `/origins`,
`/banks` and `/sleep/episodes` (not a Store domain, below) all return an `ETag` and honor `If-None-Match` with a `304`. This matters: `/graph` on the
live bank is ~1.8 MB. **Ship the ETag and its client mapping together** — `GET /inbox` ETags over
`inbox`+`entities`+`episodes`, and `VersionVector.swift` maps `entities` and `episodes` onto
`.inbox`; change one half, change both. `/graph`'s `extra` carries a node-shape tag
(`graph.NODE_SHAPE`), bumped when a node gains a field a client must see or the body changes for
the same files (F1's context filter and fence strip; `+previews` when a media node's `picture` became the stored
preview path; `+quiet`, owner ruling 2026-10-20, when a node gained `quiet` — omitted when false, derived from the
entity files the ETag already covers and from episodes whose kind never changes, so no component moved; folded into
the node's `contentHash` only when true, so a lit node's hash is unchanged; `GET /entities/{id}` carries the same
`quiet`, no ETag); `/sources` carries `sources.SHAPE` in its `extra` the same way (`preview-1`: items gained `preview`;
`saved-why-2`, G191 v3: items gained `savedWhyHistory`, `lastSavedAt` and `captureThumb`). Neither moved a component,
so `VersionVector` was unchanged by those — but G191 v3 also folds the `captures` component into `/sources`' ETag (a
new site capture gives a bookmark's row its thumbnail), so `VersionVector` maps `captures` → `.sources`.
**G191 v4.** `/sources` items gained `leftBrowser` `[{browser, channel, since}]` (shape `saved-why-3`): the browsers a
bookmark has left, read from the bookmark seen-set's `left` map. That file (`sources/bookmark_seen.json`) is not `*.md`, so
the `sources` component's directory fingerprint never saw it — it now rides the component by its own mtime (client
mapping unchanged: `sources` → `.sources`). `GET /sources/channels/{id}/items` for a bookmark channel also lists the links
that left the browser, each with `left` (shape `g161-2`). Sources v3 (2026-10-19, shape `g161-3`): a saved link's row adds `host`, `site` and `why` (the newest *Ask why* answer, read only for the page served), and a channel-less saved import is listed by its Sources row id; `GET /sources/overview` rows carry `intent` (`saved` | `captured`, ETag shape `overview-v3`; `app.md`, "Sources page — v3"). `GET /sources/saved/{media_entity_id}/site-icon` serves a saved link's own site icon, asked of that site only (owner ruling 2026-10-19; `storage.md`); 404 = draw the monogram; `GET /sources/saved/episodes/{episode_id}/site-icon` serves the same for a Waiting row of a saved link with no page yet (2026-10-20), and `GET /sources` items carry `siteKey` (shape `site-key-1`), `GET /sleep/episodes` rows `site` (`episodes-2`) and `device`, the device id that posted it, null for this server (`episodes-3`, G212: the Sleep page's machines strip) — client mappings unchanged, both are in-memory reads. Sources v4 (2026-10-19, shapes `g161-4` / `overview-v4`): an overview row adds `waiting`, `faces` and `facesMore`, and its ETag folds in `photos` (a chat face carries its photo's hash) — `VersionVector` maps `photos` to `.sourcesOverview` in the same PR; a list row drops a trailing " · <its day>", a Messages row carries `chat`, a watched day `videos` (month summaries unlisted). Review of #358 (shape `g161-5`): Messages lists one row per chat (`kind: chat`, `sittings`), a saved row's faces come from the set its list lists and only while its count is above zero, and the items ETag folds in `photos` too (`messages_photos.stamp` hashes every stored photo). New: `GET /sources/watch-history/days/{episode}` (a day's videos, ETag, not a Store domain), `GET /sources/watch-history/days/{episode}/videos/{video_id}/thumbnail`, `GET /sources/saved/{media_entity_id}/still` (marks-2: a saved YouTube video's still by its page's id, the same store; items shape `g161-6` adds `video` on such a row and `host`/`site` on a saved link's waiting episode row; the overview's ETag folds the `siteIcons` sync component — the own-site icon index, mapped by `VersionVector` to `.sourcesOverview` in the same PR — because a saved row's faces put cached icons first), `GET /sources/messages/chats/{conversation}/sittings` (ETag, not a Store domain) and `GET /sources/messages/chats/{conversation}/photo` (404 = no picture; `storage.md`). `POST /sources/sync-bookmarks` gained `leftMarked`;
`removalsProposed` stays on the wire and is always 0 for bookmarks. `GET /sources/saved-why/options` serves the four
reasons and an always-empty `projects`; `POST`/`PUT /sources/saved-why` still accept a retired reason (`technique`) and a
project (an edit may keep an archived one). **G191 v7 (2026-10-23):** the options add `more`, the 38-reason bank the panel
suggests from (`saved_why.MORE`; `reasons` is unchanged, so an older app shows the same four); a bank key is accepted and
stored exactly like a fixed one (its key in `saved_why`, its label as the person's line in the section). The two sides
share `api/tests/fixtures/saved_why_reasons.json`. New, read-only (`NONE` in the write-admission table):
`POST /sources/saved-why/suggest` `{url, title}` → `{basis, scores[{key, score}]}` — cosine similarity of each bank
reason to the link's title, host and path (never its query) by EmbeddingGemma **only when it is already installed**
(`onnx_embedder.find(PREFERRED_ID)`; never a download, a bundled-model fallback or a metered embedding service), else
`basis: none`. Nothing written, nothing logged.

**G191 v3 bookmark writes** (both 409 in a demo bank and while Sleep holds the pages, both committed alone as
`Cicada-Author: user`): `PUT /sources/saved-why` `{url, at, reasons[], project?, text?}` changes the one answer given at
`at` (404 when there is none; its `at` and `addedAt` kept, `editedAt` stamped; 2026-10-19: an edit that changes nothing —
the same reasons in any order, project and words — writes nothing, stamps nothing and commits nothing, so the panel the
star opens on a saved page can be left as it was); `POST /sources/bookmarks/remove`
`{url}` archives the link's media page (never deleted) and stamps its episode `source_deleted_at` (trigger
`user/bookmark_remove`; 404 for a link not held, idempotent). `POST /sources/saved-why` gained `addedAt` (the moment of
saving it answers) and answers with `history`. The app reaches both through `Store.perform` (`SavedWhyWrite`,
`BookmarkRemove`), refreshing `.sources`. An entity node's hash also folds its derived
`contexts` and `summary`, so `GraphDiff` re-pushes a node whose derivation changed. `/projects` and
`/projects/{id}/timeline` (G141) ETag over `entities`+`episodes`+`inbox` with `extra` =
`projects|<shape>|<author shape>|<machine zone>` (`git_service.AUTHOR_SHAPE` since round 4, R4B-9) — never today, never a viewer zone — and are **not** Store domains
(no `VersionVector` mapping, fetched on demand like provenance). A timeline item carries at most
12 participants plus `participantsTotal`, and a cluster group at most 8 names no page holds yet
(round 4 D6). A list row's `activity` is the window's first day only — the row bar's start, all the list draws from it;
the detail keeps the series (`PROJECT_SHAPE` g141-4, 2026-10-19: 40 % of the list's body at 700 projects). g141-5 (2026-10-22, ruling 36 D4): a row carries `origin` (`repo` | `words` | null — read from the page alone, no conversation), the detail `origin` {kind, stored, why, day, episode, quote, repoName, via}, the six standard `sections` (`project_sections.SECTIONS`: overview · timeline · done · expected · design · people; each {key, title, writtenBy, entries ≤ 40 + more, markdown}) and `people` (every linked person page). g141-6 (2026-10-23): a row and the detail carry `lastRepoDay` (the newest local day an agent session ran in the project's repository, from the hook's observation in episode frontmatter); `momentDays` / `lastMomentDay` are every day a claim about the project was said, a happening's day and those repository days (the list's rule, so list and detail agree, R-PJB19); a moment is listed only where the project is discussed in substance (`project_timeline._substantive`). The person's writes (G141 PJ-3b) —
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
The backend logs the same names once at startup. No Settings page shows them since 2026-10-22 (settings defaults,
`app.md`): they are a developer's to read, here and in that log.

**`GET /sleep/episodes` (2026-10-19)** answers a bare list of episode rows, as before. With no query it is every
episode (the original shape, kept for any client still asking); `processed=false` is only the waiting ones — what the
app asks for (`APIClient.fetchEpisodeQueue(etag:)`: the Sleep page's Waiting rows and count fallback, a source's queue
strip) — and `processed=true` with `offset`/`limit` (≤ 1000) pages the read ones; `X-Total-Count` is the filtered total.
The paged call has no app client, and none is needed (checked 2026-10-19): no surface lists read conversations from
this route — Sleep › Past reads runs (`/sleep/history`, `/sleep/runs/{id}`), the waiting list is `/sleep/queue` (≤ 200)
and `processed=false`, and a source's conversations are `/conversations/recent` (≤ 200, filtered before its cap). A
surface that one day lists read episodes pages here instead of downloading them all.
Rows are chosen from `bank_index`'s cached headers (`sleep_cycle.episode_headers`) and only the sent rows' bodies are
read: on a synthetic 8,237-episode bank (10 waiting) the bare call is 4.3 MB / 1.7 s warm before and 0.4 s after, the
waiting list 5 KB / 45 ms, a 304 ~25 ms. ETag over `episodes` with `extra` = `sleep.EPISODES_SHAPE|<query>|<folders.json
mtime>` (a folder file's row copies its path from that registry). Not a Store domain: no `VersionVector` mapping —
`SleepViewModel` holds the rows and the tag in memory, sends `If-None-Match` on every `load()` and drops both on a bank
switch.

**Unit tests reach no backend (2026-10-19).** Under XCTest `APIClient.shared` is `APIClient.pointingAtNothing()`: a
session whose transport (`NoBackendURLProtocol`) fails every request with `cannotConnectToHost` before a byte leaves the
process, an unresolvable base and a home that does not exist; and `APIClient.loadToken` reads a token only from a folder
under the temporary directory and ignores `CICADA_API_TOKEN` (`testMayReadToken`). A view model's defaults call `shared`,
so a test that forgets to inject a closure gets an offline answer, never the running backend or the person's token
(`APIClientIsolationTests`). The shipped app is unchanged: both checks key on `AppPasteboard.isRunningTests`.
The same goes for every other default that reads `CicadaRuntime.current` (#348 follow-up): under XCTest it is
`CicadaRuntime.underTests()`, the same code root with a home under the temporary directory
(`cicada-xctest-<pid>/home`, the shell's `CICADA_HOME` ignored), so `ServerConnection`'s files, the device token, the
updater's token file, log and Trash never resolve to the person's; and `SleepProbe.live` answers over
`NoBackendURLProtocol` (`RuntimeHomeIsolationTests`).

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
`requests.json`, `updates.json`, `onboarding.json`, `kinds.json`; write admission classes every route `OUTSIDE`.
- `GET /skills` — installed rows (source, version, `status` — `update|refresh|current|local|unchecked` —, update with
  `from` and its `changes`, agents, tool, permissions, details with an instructions `excerpt`),
  `suggested` (catalog, with `method` `tool|copy|manual|own`), `drafts`, `noticed` (the bank's held and page skills,
  G112), `requests`, `checkedAt`, `uv`, `jobs`. No ETag: not a Store domain. **Additive since G201 slice (a)** (TODO
  ruling 35, 2026-10-22): every installed, draft, noticed and plugin skill carries `kind` (`about-you|generic|unknown`),
  `kindBy` (`person|cicada`) and `kindKey`; `plugins` lists Claude Code's installed plugins (`id` `name@marketplace`,
  `name`, `marketplace`, `version`, `scope`, `enabled` true/false/null, `installedAt`, `updatedAt`, `harness`,
  `canToggle: false`, `note`, and `skills` — `name`, one-line `description`, `userOnly` for
  `disable-model-invocation`); `weight` is `{agents: [{id, label, skills, fromPlugins, userOnly,
  descriptionTokens}], basis, estimate: true}`. Field order is not a contract.
- **Plugins (`skill_plugins`), read-only.** From Claude Code's own files under the agent home:
  `.claude/plugins/installed_plugins.json` (v2 `{version, plugins: {id: [entries]}}`, and the older flat shapes), the
  user `settings.json`'s `enabledPlugins`, each plugin's `.claude-plugin/plugin.json`, and its skills' SKILL.md
  frontmatter (`skills/` plus the manifest's own `./` paths). The user-scope entry wins; a project-scoped install's
  switch lives in that project's settings, which the backend never opens, so its `enabled` is null and its `note` says
  so. An `installPath` outside `.claude/plugins` and a manifest path that escapes the plugin are never followed; a
  missing or corrupt file is an empty answer, never an error. Shown only when Claude Code is on this Mac. Cicada never
  installs, removes or toggles a plugin.
- **Kinds (`skill_kind`), no model call.** Third-party text (a plugin, GitHub, `npx skills`, the catalog, a tool) and
  Cicada's own bundles are `generic`; a candidate (a held or page skill Sleep noticed, an agent's draft, a published
  draft) is `about-you` when its evidence pages (`related`, a held line's `evidence_ids`) or its text's `[[links]]`
  name a `person` or `project` page or the owner's page, else `unknown`; a local skill folder of unknown origin is
  `unknown`. `PUT /skills/kinds {key, kind}` (`kind` null clears) stores the person's choice in
  `$CICADA_HOME/skills/kinds.json` through `skill_store.set_kind`, the one writer; it wins over the rule.
- **Weight.** Per agent on this Mac: the skills it loads (its own folder and the folders it also reads; for Claude
  Code also every switched-on plugin's skills) and `descriptionTokens`, an estimate — the characters of each loaded
  skill's name and description divided by 4 (a `userOnly` skill loads no description). No cap is enforced (ruling 35
  §6's ask past 12 is slice (d)).
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
- **Never lost, never for an absent agent:** Remove moves the library copy (made first from an agent's copy when
  there is none) to `removed/`, so a skill's only text — a published draft's — is always restorable; a write for an
  agent whose home folder is missing is refused before anything is written (it would create the folder and make the
  agent look installed). A saved onboarding answer is where a later run starts: declined ids come back `default:
  false, declined: true`.
- **Commands** (uv, `<tool> skill`, `<tool> doctor`) are argvs through `connections.base.run_cli` (scrubbed env,
  `CICADA_CAPTURE=off`), bounded; a uv install is pinned to a commit (`git+https://github.com/<repo>@<sha>`).
  `doctor` reports permissions for the app that started the tool — here Cicada — so the page labels them "Checked for
  Cicada" and says an agent in another app may have different ones (owner 2026-10-15).

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
  `_QUERY_PATHS` in `api/main.py`. An OAuth callback's query (`/sources/connectors/<id>/callback`,
  `/connections/<id>/callback/<nonce>`) is stripped too: its `code` is a credential (2026-10-16).
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
  scans in a thread for `/sleep/status` too. `/sync/version` and `/sleep/status` never read the shared tick. Measured
  on generated banks (1,900 entities):
  - 10,000 episodes: 42 → 24 ms per tick for one stream, and 169 → 25 ms for four.
  - 2,000 episodes: 12 → 6 ms for one stream, and 50 → 6 ms for four.
- **The tick walks the bank on a file-change event or every 10 s (2026-10-16, owner decision 2).** `bank_watch` keeps
  one watcher per bank — `watchfiles` (already installed by `uvicorn[standard]`): FSEvents on macOS, inotify on Linux —
  over the bank and its machine-local Sleep folder, counting reported changes except git's own (`.git/`) and the index
  databases at the bank's root. `sync_ticker` walks the bank only when that count moved since its last walk (read
  before the walk, so a change during it walks again) or the walk is `bank_watch.FALLBACK_S` (10 s) old — the net for
  an event the OS dropped. Between, a tick answers from the last walk's listings (`bank_index.shared_scans(seed=…)`,
  and the `backlog`/`captures` stamps walked outside `bank_index`) and reads everything else as before: git HEAD, the
  files outside the bank, every TTL expiry, the Sleep state and the clock. An editor's in-place write is an event like
  any other. No notifier, a failed one (retried once a minute), a bank directory replaced, or
  `CICADA_SYNC_WATCH=off`: every tick walks. A watcher nobody asked about for 60 s stops; shutdown stops them all.
  Owner-scale synthetic bank, 8,791 files (`benchmarks.scale.idle_tick`): 33.2 → 6.3 ms of CPU a second, an idle
  tick 31 → 3.3 ms; an outside in-place edit reaches the stream in ~640 ms either way. FSEvents also reports writes
  made just *before* a watcher started, late (0.4–1.9 s measured on a loaded machine), and under contention any report
  can take seconds (up to ~2.9 s with five watchers, ~10 s with five suites at once; 2026-10-18): harmless here (an
  extra walk, or the fallback walk), but `test_sync_watch.py` failed 1–2 of 12 on every run on a loaded machine. Its
  tests no longer sleep or wait a fixed time for the OS: `_settle` writes a marker the watcher never counts and waits
  for it to be reported (events arrive in order, so nothing older is in flight), and whether a change was *reported*
  is read from the watcher's count; the fallback test drives the ticker's clock. The watcher now looks at every path
  of a batch (no short-circuit) so a marker is always seen.
- **Compressed only for another machine (2026-10-16, owner decision 3).** `response_compression.RemoteGZipMiddleware`
  gzips (level 1) a response for a client that asked for it and is on another machine: a non-loopback peer, a request
  a proxy forwarded (`X-Forwarded-For`, `Forwarded`, `X-Real-IP`, `Tailscale-User-Login` — `tailscale serve` in front
  of `127.0.0.1`), or one signed with a per-device token (ruling 28; covers an SSH tunnel, which arrives from loopback).
  Loopback is answered byte for byte as before. ETags are computed by the routes before compression and a 304 has no
  body, so conditional requests are unchanged; the SSE stream, bodies under 1 KB and already-compressed types (images,
  video, audio, PDF, archives) pass through. Owner-scale synthetic bank: `/graph` 10.5 MB → 0.92 MB on the wire
  (~25 ms more server time), `/inbox` 498 → 59 KB, `/sources` 742 → 103 KB.
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
