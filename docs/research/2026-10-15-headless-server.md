# Headless Cicada on a server, synced with the Mac — research (2026-10-15)

Owner, 2026-10-15: *"work on the Cicada version that runs on a server, headless without the app, and is actually
synced, maybe through Tailscale or other options; e.g. a home server connected to the Mac."* Backlog: **G181**
(server mode, primary-writer topology) with **G132** (sync across devices) and the existing order *"P4: replication
and sharing after the primary-writer topology"*. This note settles the topology and sizes phase 1. Evidence is from
`dev` at 57a52f77, plus a probe on a Linux host (Ubuntu, systemd 259) with scratch HOME, CICADA_HOME and bank.

## 1. What exists today

**The backend already runs on Linux.** Nothing macOS-only runs at import or in the lifespan
(`api/main.py:118-215`): no pyobjc, FSEvents, `osascript`, `launchctl` or keychain. Core ML is lazy and gated on
Darwin/arm64 (`coreml_embedder.py:86-92`); ONNX and sentence-transformers are portable. Probe: `python -m uvicorn
api.main:app --host 127.0.0.1 --port <p>` on the Linux host answered `/healthz` with a scaffolded bank, `/status`
401 without the token, and wrote `$CICADA_HOME/api_token` 0600 plus `remote/` and `sleep/`. Degraded on Linux:
`sips` (`image_decode.py:23`, `site_captures.py:182`) is missing, so image decode and site thumbnails fail with a
`DecodeError`, which those modules already expect.

**What broke on the probe (fixed in phase 1):**
- **No commit identity.** A fresh server has no `user.name`/`user.email`, and every bank commit failed ("Author
  identity unknown"): the owner page was written but never committed. The demo bank already sets a repo-local
  identity for exactly this reason (`demo_bank.py:409-421`); the real bank did not.
- **`install.sh` died on Linux** at step 2b: `MACOS_MAJOR="$(sw_vers … | cut …)"` under `set -euo pipefail` exits
  127 where there is no `sw_vers`.
- **No service manager path.** `install.sh` step 6 and `scripts/doctor.sh` step 8 are launchd only.

**Already headless-capable:**
- **Sleep's scheduler is in the backend** (APScheduler in the lifespan, `main.py:190-194`; the schedule lives in the
  bank, `sleep_schedule.yaml`), not in the app or launchd. **Ruling 4 holds by construction**: an unattended run
  resolves to `byok` (`engine_select.py:28-46`), so a server Sleeps on its schedule only with a metered key in its
  own `secrets.env` (or a deliberate local-model pin). On a metered key it drains everything (ruling 16).
- **Capture on the server itself**: Claude Code or Codex running *on the server* are captured by the Stop hook into
  the server's backend exactly as on a Mac (`/capture/transcript` validates the path under the server's own
  `~/.claude/projects`). Cursor/Gemini post words to `/capture/turn`. The CLI (G180) and stdio MCP work on the server
  against its own bank.
- **The remote connector (G135)** is an MCP-only listener on `127.0.0.1:8765` with hashed, scoped, expiring tokens,
  meant to sit behind a tunnel the person runs (`api/remote/`).

**What assumes one machine** (from the code, each a phase-2/3 item):
- Every client hardcodes the host: the hook (`api/hooks/capture.py:243`), `runtime_layout.backend_url()`
  (`127.0.0.1:$CICADA_PORT`), the app's base URL (`APIClient.swift`).
- `/capture/transcript` posts a **path**; a Mac hook posting to a server backend fails `outside_root`/`not_a_file`
  by design (the transcript rail).
- The stdio MCP's recall, write_claim, save_episode, edit_page… read and write **bank files directly**; only `ask`,
  `save_url`, `resolve_inbox` and the Sleep probe use HTTP.
- The CLI's ruling-21a check compares `realpath(/healthz memoryRoot)` with its own root, which only matches on the
  same filesystem.
- One API token, no per-device scoping (`auth.py`); CORS is loopback-only; there is no TrustedHost check, so the bind
  address is the real boundary.
- Locks are per machine: the git write lock is a thread lock plus git's `index.lock`; write admission is an `flock`
  under `$CICADA_HOME`. Episode ids are max-suffix+1 per date on the local disk (`episode_ids.py`).

## 2. What headless must do (without the app)

1. Run the backend as a service that survives logout and reboot, bound to loopback.
2. Run Sleep on its schedule there (ruling 4: a metered key or a local model on the server).
3. Take capture over HTTP and MCP: the server's own harness hooks, `/capture/turn`, the CLI, MCP tools, and later the
   Mac's posts.
4. Serve MCP to agents: stdio on the server, and the G135 listener for anything off-box.
5. Keep every rail: one git writer per bank, the write window, the split-brain rule, the demo guard, credentials only
   in `$CICADA_HOME/secrets.env`, nothing listening beyond loopback without an overlay the person runs.

## 3. Sync options compared

| | A. git push/pull between two full nodes | B. Syncthing on the bank folder | **C. One primary backend on the server; the Mac is a client over the tailnet** | D. Primary on the Mac; the server is a replica |
|---|---|---|---|---|
| **One git writer** | Broken: two writers. Episode ids collide on the first same-day capture (max-suffix+1 per local dir); `_state.md`, `sync_state.json`, `_merge_rejected.yaml` are read-modify-write and merge silently wrong; a clean merge can join contradictory facts | Broken worse: two live writers on one `.git` through a file syncer; partial-file sync can corrupt the object store; `search_index.db`/`vector_index.db` sit in the bank dir and would sync mid-write | **Kept**: the server is the bank's only writer; every client writes through its API | Kept: the Mac writes; the server only fetches |
| **Sleep in one place** | No: two Sleeps consolidate the same `processed: false` episodes | No | **Yes, on the server, uninterrupted** (the owner's point: the Mac's lid no longer stops it) | Yes, on the Mac, so it still stops when the lid closes |
| **Mac-only capture** (browsers, Notes, Calendar, Messages, folders, all app readers) | Each node captures locally, then the merge problems above | Same | The app keeps reading `~/Library` and **posts bytes to the server** instead of to loopback (the rail already says "the app reads, the backend parses bytes"; only the address changes). The Claude Code/Codex Stop hook on the Mac cannot send a path: it runs the existing pure extractor locally and posts scrubbed, capped turns (G132's "distributed Awake" shape, a rail amendment the owner must rule on) | Unchanged on the Mac; the server's own sessions post turns to the Mac |
| **Auth** | SSH keys for git | Device keys | The API token today (one per machine, unscoped). Phase 2 adds per-device tokens (G135's hashed token store) before a second device. The tailnet adds identity (`tailscale serve` sets `Tailscale-User-Login` and strips a spoofed one), never a replacement for the token: the headers are absent for tagged devices and present for anyone the device is shared with | Same as C, reversed |
| **Nothing public** | SSH on the tailnet | Syncthing relays reach the internet unless disabled | The backend stays on 127.0.0.1; `tailscale serve` (tailnet-only) proxies to it. **Never `tailscale funnel`, never a 0.0.0.0 bind** | Same |
| **Latency** | Local reads; sync lag | Local reads; sync lag | Tailnet round trip per call (a LAN hop ~1–5 ms; remote ~20–80 ms). Recall over HTTP is one call; the app's Store already syncs over HTTP + SSE | Local on the Mac |
| **Offline** | Works offline, conflicts later | Same | Server down or Mac away: capture spools on the Mac and flushes on reconnect (hash dedup makes a resend safe); the app shows the last Store snapshot dated, never blank (R-A12). Reads need the server, or a read-only mirror later | Mac closed: the server can only read a stale mirror and queue posts |
| **What breaks** | The id rule, the git rail, Sleep's single mind, the split-brain rule | All of A, plus `.git` integrity | Hard-coded `127.0.0.1` in four clients; the transcript path rail for remote harnesses; the stdio MCP's direct-file tools on the Mac (they need the HTTP door or the G135 listener); the CLI's same-path root check | The owner's goal: Sleep still stops with the lid |

**Rejected:** A and B break the one-git-writer rail and the id rule outright. Git stays useful only as **push-only
backup** from the single writer (already scoped in G181/G132, AMR §5) and as a **read-only mirror** (G132's second
slice), never as a merge transport. D keeps today's weakness (Sleep stops with the lid) and is G132's thin-satellite
shape, which stays the right answer for *a laptop that is not the primary*; it is not what the owner asked for here.

**Recommended: C**, the shape G181 already argues: one primary on the server, every other device a client of its API
over an overlay the person runs. It is the only option that keeps every storage rail unchanged. Its costs are all on
the client side and can be built one door at a time.

## 4. Phased plan

**Phase 1: the server stands alone (this branch, `feat/headless-server`).** Backend only, Linux-capable.
- `scripts/install-backend-service.sh`: the systemd *user* unit `cicada-backend.service`, the twin of the launchd
  agent. `python -m uvicorn` bound to **127.0.0.1 only**; `Restart=always`; `UMask=0077`; logs in the same place;
  `--dry-run`, `--no-start`, `--uninstall`. It creates no credential (the backend writes its own token). It checks
  lingering and prints the `sudo loginctl enable-linger` line; it never runs it.
- `install.sh`: on Linux, step 6 installs that unit and `--uninstall` removes it; the `sw_vers` crash is fixed; the
  bank's first commit works with no git identity.
- The backend: `git_service.ensure_commit_identity_sync`, called from `bank_registry.scaffold_bank` (every startup and
  every new bank). It gives the bank a repo-local `Cicada <cicada@localhost>` **only when git resolves no identity**,
  never overrides one and never touches `~/.gitconfig`. Who wrote a change stays the `Cicada-Author` trailer's job.
- `doctor.sh` step 8 checks the systemd unit on Linux.
- `~/.cicada` is the same layout on both platforms (the backend creates it); the doc lists it.
- Reaching it from the Mac in phase 1 is the person's own overlay: `tailscale serve --bg --https=443
  http://127.0.0.1:8000` (tailnet only) or an SSH tunnel. Cicada runs neither. With the server's token (which the
  person copies), the REST API, `/healthz` and the CLI's backend routes work from the Mac through it.
- Tests: synthetic banks and fake `systemctl`/`loginctl`/`uname` in scratch dirs; systemd's own parser on the unit;
  `install.sh --dry-run` on both platforms.

**Phase 2: clients over the tailnet (backend + hooks + MCP; no Swift).** *Built 2026-10-16 on the owner's rulings
(TODO ruling 28): per-device tokens, the transcript read on its own machine, a device counted as local for G198; the
stdio MCP reaches the server through a tool door on the main API (`POST /tools/call`) rather than the G135 listener,
so a device's agent keeps the trust a local one has. What ships is in [`headless.md`](../architecture/headless.md).*
- One client base URL, `CICADA_API_BASE`, read by `runtime_layout.backend_url()`, the hooks and the CLI (env only,
  never a hardcoded host; the portability rail).
- Per-device tokens from the G135 store (hashed, named per device, revocable), so the server's master token never
  leaves it. **Owner decision**: per-device tokens before any second device (recommended), or the one token copied.
- A turn-posting capture route for a harness on another machine: the device runs the existing pure extractor and
  posts scrubbed, capped turns; ids are minted on the server under its lock, so G104/G114 hold. **Owner ruling
  needed**: it amends "the backend reads the transcript" to "the transcript is read on the machine it lives on, by
  Cicada's own extractor".
- A capture spool on the client (FIFO under `$CICADA_HOME`, full payload per retry, hash-dedup on the server), so a
  server that is down loses nothing and the hook stays inside its time budget.
- The CLI's 21a check compares a **bank identity** (an id in `banks.yaml`) instead of a filesystem path.
- MCP from the Mac: the G135 listener on the server through the same tailnet (it already serves MCP with scoped
  tokens). **Owner decision**: whether a tailnet device of the person's own counts as "local" for the trust list
  (G198 writes at once only for local harnesses today; remote is never on it).

**Phase 3: the Mac app as a client (Swift, on the Mac).**
- Settings → General (Settings → Devices since 2026-10-22): *This Mac* or *A server* (address + device token). The Store, ETags and SSE already run over
  HTTP; only `APIClient`'s base URL constant changes.
- The readers (browsers, Notes, Calendar, Contacts, folders, Messages) post bytes to the server; an offline queue
  flushes on reconnect. The app's backend agent is not installed in server mode.
- Demo banks stay local to the app (a demo never reaches the server, `demo_guard`).

**Phase 4 (the backlog's P4): replication and sharing after the primary-writer topology.** Push-only backup from the
primary under the git lock; G132's read-only mirror for fast offline reads; several laptops; G16 multi-person.

## 5. Rails each phase keeps

- One git writer per bank: only the server's backend commits; no client ever commits to a copy.
- Nothing listens beyond loopback; reach is an overlay the person runs; no funnel, no public port.
- No credential is created, copied or logged by an installer; `secrets.env` stays 0600 and the person's.
- Ruling 4: unattended Sleep on the server never spends a plan.
- The demo guard and the split-brain rule are unchanged: the caller passes the active bank; a client names it.
- No hostname, address or home path in code or docs (env-var configuration only).
