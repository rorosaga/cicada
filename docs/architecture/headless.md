# Headless: Cicada on a server, without the app (G181)

The backend, Sleep, the CLI and the MCP server run on a Linux (or macOS) machine with no companion app. The topology,
the options it was chosen over, and the later phases are in
[`docs/research/2026-10-15-headless-server.md`](../research/2026-10-15-headless-server.md). This page describes what
ships.

## The topology

**One primary.** The server's backend is its bank's only git writer and runs its Sleep. Every other device is a
client of its API (phase 2: hooks, MCP and CLI; phase 3: the app). Nothing syncs a bank by git merge or by a file syncer: two writers break the episode
id rule (max-suffix+1 per local directory), the read-modify-write state files and Sleep's single mind.

**Nothing listens beyond loopback.** The service binds `127.0.0.1` only. Reaching it from another machine is an
overlay the person runs and Cicada never configures: on a tailnet, `tailscale serve --bg --https=443
http://127.0.0.1:8000` (tailnet only; never `funnel`), or an SSH tunnel. The API token is still required on every
route but `/healthz`. Tailscale's identity headers are not a substitute for it: tagged devices get none, and anyone
the device is shared with gets them.

## Install

### One line, on Linux

As the user who will own the memory (not root), on a machine with systemd:

```sh
curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/main/scripts/install-server.sh | bash
```

`scripts/install-server.sh` is a bootstrapper; everything it installs is the checkout's own `./install.sh`:

| Step | What happens |
|---|---|
| Prerequisites | `git`, `curl`, `uv` (also found in `~/.local/bin`, where uv's installer puts it) and a reachable systemd user manager, checked together; each missing one is named with the line that fixes it, and nothing is installed (exit 2). Root and non-Linux are refused (a Mac is pointed at Homebrew and the app) |
| The code | `CICADA_REF` (a branch, tag or commit; validated as a name), else the newest `vX.Y.Z` tag from `git ls-remote` — CI creates a tag only when it publishes a release, so that is the latest release, resolved as a tag only (a branch of the same name never stands in). Cloned into `CICADA_DIR` (default `~/.local/share/cicada`) and checked out detached. A folder there that is not its own checkout (another origin) is left alone; a checkout with local changes is never overwritten |
| Python | `scripts/sync-server-env.sh`: `uv sync --frozen --no-dev` from `api/uv.lock` minus `sentence-transformers` and what only it needs (torch, the CUDA wheels, transformers, scipy, …) — the release app's set. Measured on Linux arm64: a 338 MB venv |
| The rest | `CICADA_REPO=<dir> ./install.sh --cli`: search model, memory folder (`~/cicada/memory`, `CICADA_MEMORY_PATH`), `api/.env`, MCP and hook registration, the systemd unit below, `~/.local/bin/cicada` |
| Update | The same line. Same ref: nothing changes (the backend keeps its PID). A new ref: the code moves, the Python environment re-syncs, and `install-backend-service.sh` rewrites the unit and restarts it |
| Check | `/healthz` on `127.0.0.1:8000` within 60 s, then `cicada status`; the summary says where the backend's own token lives (never its value) and prints the `enable-linger` line when lingering is off |
| `--uninstall` | `install.sh --uninstall` (unit, MCP entry, hooks) when the unit is this folder's, the `cicada` link when it points here, and the code folder (its venv and logs) only when this script cloned it (a mark in its `.git`). Another install's unit is left alone. The memory folder and `~/.cicada` stay |

The script is one function called on its last line, and every child reads `/dev/null`, so `curl | bash` runs nothing
until the whole script has arrived and nothing it starts can read the rest of it from the pipe. The `main` URL works from the next
release on (`main` is 0.3.1 and has no `install-server.sh`); testers before it: `curl -fsSL https://raw.githubusercontent.com/rorosaga/cicada/dev/scripts/install-server.sh | CICADA_REF=dev bash`.

End to end, on real systemd: `scripts/dev/test-install-linux.sh [ubuntu|fedora]` (Docker; this checkout's HEAD served
from a local bare repo). `api/tests/test_install_server.py` holds the orchestration rules with fakes.

### Homebrew (macOS and Linux)

This repository is its own tap; the formula is `Formula/cicada.rb`:

```sh
brew tap rorosaga/cicada https://github.com/rorosaga/cicada
brew install cicada        # --HEAD follows dev
cicada-setup               # memory folder, search model, hooks, background service
```

- **What it installs:** the backend, the MCP server and the `cicada` command (`api`, `mcp`, `scripts`, `skills`,
  `install.sh`; no app sources, docs or tests) into `libexec`, with a venv built by the same
  `scripts/sync-server-env.sh` on Homebrew's `python@3.12` (`UV_PYTHON_DOWNLOADS=never`, so nothing points into
  the build's temporary HOME). `bin/cicada` is the checkout launcher; `bin/cicada-setup` runs
  `scripts/cicada-setup.sh`.
- **`cicada-setup`** is `install.sh` against `$(brew --prefix)/opt/cicada/libexec`, the path that survives
  `brew upgrade`, so every hook, MCP entry, plist and unit it writes names that path, never a versioned Cellar folder.
  Run again after an upgrade, it restarts a service that already runs this install (and only that one). `--uninstall`
  passes through.
- **No `service do` block.** The background service keeps one source per platform —
  `scripts/install-backend-agent.sh` (launchd `com.cicada.backend`) and `scripts/install-backend-service.sh`
  (systemd) — so `brew services` never writes a second plist or unit for the same port. `brew services` has nothing
  to start for `cicada`.
- **Settings and logs outside the keg:** `api/.env` is a link to `$(brew --prefix)/etc/cicada/api.env` (0600, kept
  across upgrades); `CICADA_LOG_DIR` is `$(brew --prefix)/var/log/cicada`.
- **The version:** the stable `url` is the git tag `v$VERSION`. `make release` stamps it and `check_version.py agree`
  holds it equal to `VERSION`, so the formula on `main` names the release that merge creates. The tap is the repo's
  default branch (`main`), so the formula is live from the next release on; until then, tap a clone of `dev`
  (`brew tap rorosaga/cicada <path-to-a-dev-clone>`) and `brew install --HEAD`.
- **No cask.** The release app carries its own backend and is installed by `scripts/install-release.sh`. A cask for
  the not-yet-notarized zip would be quarantined by Homebrew's download, and Gatekeeper would block it on every
  machine until the person clicks Open Anyway — exactly what the curl installer avoids. A cask follows notarization
  (G182's Developer ID step).
- **Beside the app, on one Mac:** there is one backend on `127.0.0.1:8000` and one launchd label
  (`com.cicada.backend`), never two. `install.sh` skips the service when a backend already answers (the app's), and the
  app spawns none when one answers (it then uses the Homebrew one, on the same `~/.cicada` and bank); whichever
  installs the agent last owns the label. `cicada-setup` restarts, and `cicada-setup --uninstall` removes, only a
  service that runs `opt/cicada/libexec`; another Cicada's service, hooks and MCP entry are left alone. On a Mac whose
  memory lives on a server (`CICADA_API_BASE` or the app's `~/.cicada/api_base`, phase 3) `install.sh` installs no
  local backend at all: the hooks, MCP and `cicada` already talk to the server. Use one install per Mac.
- **Known limit:** the backend computes its own repo path with `resolve()`, so the app's Settings → Agents, run
  against a Homebrew backend, would register hooks under the Cellar path; use `cicada-setup` to connect agents on a
  Homebrew install.

End to end on Linuxbrew: `scripts/dev/test-install-brew.sh` (Docker, `homebrew/brew` plus systemd): `brew style`,
`brew audit --new --strict`, install, `brew test`, `cicada-setup`, upgrade, uninstall. A macOS install is not run in
CI or by that harness (it would need this Mac's own Homebrew prefix); the formula's macOS path differs only in
`install.sh` step 6 choosing the launchd agent, which `test_install_backend_agent.py` covers.

### From a clone

From a clone, on Linux: `./install.sh`. It is the same installer as on a Mac. On Linux:

- step 6 installs the **systemd user unit** `cicada-backend.service` through `scripts/install-backend-service.sh`
  instead of the launchd agent, behind the same "a backend already answers `/healthz`" skip;
- `--uninstall` disables and removes the unit and keeps the memory directory and `~/.cicada`;
- step 2b's Neural Engine model is skipped (no `sw_vers`); the small ONNX model is fetched as on a Mac.

`scripts/install-backend-service.sh` is the one source of the unit, the twin of `scripts/install-backend-agent.sh`:

| | |
|---|---|
| Unit | `${XDG_CONFIG_HOME:-~/.config}/systemd/user/cicada-backend.service` (`SYSTEMD_USER_DIR`, `UNIT_NAME` override it) |
| Runs | `api/.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port $CICADA_PORT` (never the venv's `uvicorn` script) |
| Environment | `CICADA_MEMORY_PATH` (else `api/.env`'s, else `~/cicada/memory`), `CICADA_HOME`, `PYTHONPATH`, `PATH`, `CICADA_ALLOW_FEED_FETCH=1` |
| Hardening | `UMask=0077`, `Restart=always` |
| Logs | `<repo>/logs/backend.{out,err}.log`, as on a Mac; also `journalctl --user -u cicada-backend.service` |
| Flags | `--dry-run`, `--no-start`, `--uninstall`; refuses on a Mac (exit 5), a non-numeric port, or a path with a quote |

A user unit stops at logout unless lingering is on. The script checks `loginctl show-user` and prints
`sudo loginctl enable-linger <user>` when it is off; it never runs it, because it needs root and is the person's step.

The script creates no credential. The backend writes `~/.cicada/api_token` (0600) on first start. A metered key for
scheduled Sleep goes in `~/.cicada/secrets.env`, written by the person.

`make doctor` (`scripts/doctor.sh`) checks `systemctl --user is-active cicada-backend.service` on Linux in place of
the launchd agent.

## `~/.cicada` on a server

The same layout as on a Mac, created by the backend and the CLI. The ones that matter headless:

- `api_token` (0600): the master token. It never leaves the server; another device gets its own (`devices/`).
- `devices/devices.db` (0600): the person's device tokens, hashes only (phase 2).
- `secrets.env` (0600): provider keys, the person's.
- `remote/`: the G135 listener's token store and settings (off by default).
- `sleep/<bank>-<hash>/`: runs, pause sidecars and the write-admission lock.
- `models/`: the search model.
- Per-bank queues and caches: video, reading, captures, previews.

`~/.cicada/bin` launchers are a release-app thing (G182) and do not exist on a source install.

## Sleep on a server

The schedule runs inside the backend (APScheduler, `sleep_scheduler`), from the bank's `sleep_schedule.yaml`, so it
needs no app and no timer unit. **Ruling 4 binds here as everywhere:** a scheduled run never uses a Claude or ChatGPT
plan, so a server Sleeps on its schedule only with a metered key in its `secrets.env` (or a deliberate local-model
pin). A run the person starts (CLI `cicada sleep`, or a client's click) may use a plan.

## Commits with no git identity

A fresh server has no `user.name`/`user.email`, and git refuses to commit. `git_service.ensure_commit_identity_sync`,
called by `bank_registry.scaffold_bank` (every startup and every new bank), sets a repo-local
`Cicada <cicada@localhost>` **only when git resolves no identity**. It never overrides one that resolves (environment,
global or system) and never writes `~/.gitconfig`. `install.sh`'s first commit does the same. Who wrote a change is
the `Cicada-Author` trailer's job, not git's author field, so nothing about provenance changes.

## Clients on other machines (phase 2)

Owner rulings 2026-10-16 (TODO ruling 28): per-device tokens; the transcript rail amended; a tailnet device of the
person's counts as local for the G198 trust list.

**On the server**, once: `cicada device add <name>` (the person's own terminal; `POST /devices` with the master token
does the same). It prints the device's token once and keeps only its hash. `cicada device list` shows each device and
when it was last used; `cicada device revoke <id>` ends it at once. The master token (`~/.cicada/api_token`) never
leaves the server, and a device token can neither issue nor revoke one.

**On the client** (the person's Mac, say), two settings and nothing else — set by the person, or (phase 3) by the
app on the person's click in Settings → General, which puts `$CICADA_HOME/api_base` in place when Cicada next opens
and writes `device_token`, both 0600:

- `CICADA_API_BASE` — the address the person's own overlay gives the server (`https://…` for any host; plain `http://`
  only to a loopback address, i.e. an SSH tunnel's local end). Set where the hooks, agents and shells inherit it.
- the device token in `~/.cicada/device_token` (mode 0600), or `CICADA_API_TOKEN`.

Unset, every client behaves exactly as on one machine. Set, the machine holds no bank:

| Client | What it does with a base set |
|---|---|
| Claude Code / Codex Stop hook | Reads the session here with Cicada's own extractor and posts the scrubbed, capped turns to `/capture/session`; ids are minted on the server (one episode per session). A server that is away: the post waits in `~/.cicada/spool/capture/` and a later firing sends it (`capture-and-sleep.md`) |
| Cursor / Gemini CLI hooks | Post turns to `/capture/turn` as before, spooled in order when the server is away |
| Recall hooks (SessionStart, UserPromptSubmit) | Ask the server's `/capture/hook-context` |
| stdio MCP server | Every tool runs on the server through `POST /tools/call` (the same bodies); pictures named by path are read here and sent as base64; `cicada_repo_context` probes git here (`mcp.md`) |
| `cicada` command | Tool mirrors through the server, `backend` commands to its routes, the bank pinned by name and id; commands that read the memory folder refuse `on_server`; refuses `backend_down` when the server is away |

**Identity, not paths.** Every bank has an `id` in `banks.yaml` (minted by the backend at startup, new for a copy,
kept by a rename). `/healthz` reports the ids, a client pins the server's active bank by name and id, and every
mutating request names both (`X-Cicada-Bank`, `X-Cicada-Bank-Id`), so a write meant for one memory never lands in
another that happens to share a bank name. Ruling 21a's check compares these ids (path only when a side has none).

**What did not change.** Only the server commits (one git writer per bank); the server binds 127.0.0.1; reach is the
person's overlay; no installer creates, copies or logs a credential; the demo guard and the split-brain rule are the
server's, per request. The G135 remote listener is still the door for apps off the person's devices, never trusted to
edit a page.

## The Mac app as a client (phase 3)

Settings → General → *Where your memory lives*: **This Mac** (as always) or **A server** — the address the person's
overlay gives the server and this device's token from `cicada device add`. Nothing is written until the server
answers: `GET /healthz` (open) proves it is Cicada, `GET /devices` with the token proves the token and names this
device. Then the app writes `device_token` and the address to `$CICADA_HOME/api_base.next` (0600) and offers *Restart
Cicada*; at the next launch, before anything resolves, `ServerConnection.applyPending` moves it into `api_base` (or
removes `api_base` for This Mac) and the app resolves once (`ServerConnection`, like `CicadaRuntime`), so the Store, its
disk cache (one per connection), the event stream and every reader switch together. `CICADA_API_BASE` in the app's
environment wins and locks the choice. `api_base` makes this Mac's hooks, stdio MCP server and `cicada` command clients
(`runtime_layout._raw_base`, read on every call), which is why the click never writes it directly: the agents and the
app switch at the same launch, never one before the other. A file that is not UTF-8 still makes the Mac a client with an
invalid address (capture spools), never This Mac. Choosing This Mac again removes the address and keeps the token.

On a server the app:

- talks only to that address, with the device token (never the master token); an address that breaks the rule
  (https, or http to loopback only) sends every request to an unresolvable name — never falls back to this Mac's bank;
- starts no backend of its own, offers no *Keep memory working* install and repairs no service after an update; a
  background service left from This Mac is stopped at launch (`launchctl bootout`, plist kept, so This Mac again, the
  next login or *Turn on* brings it back), so nothing keeps serving this Mac's bank while everything here points
  elsewhere;
- sends the readers' bytes (bookmarks, Safari tabs, Notes, watched folders, Calendar, Contacts, tab groups, YouTube
  history, Messages, Wispr Flow) to the server, and keeps a post the server did not take in `$CICADA_HOME/spool/app/`
  (`ReaderOutbox`: 0700/0600, named by route + memory + body hash, ≤ 200 posts / 64 MB / 7 days; no answer, 401/403,
  409 and 5xx wait, 400/404/405/413/422 are dropped; a stopped run's post — the person's Cancel, or a bank switch
  replacing a reader's run (G183(d)) — never waits). A newer post on the same route and memory never overtakes one
  that waits: those go first, and while one still cannot land the newer waits behind it (a snapshot replayed late would
  put the server back to an older state). It is flushed oldest first when the event stream connects again
  (and by *Send now* on the Devices page); the readers keep their cursors and read again, so the outbox is the fast
  path and the server's dedup makes a resend harmless;
- refuses the demo (`ServerLinkError.demoStaysLocal`, before any request): a demo is a This Mac thing.

**Settings → Devices** (Customize, after From anywhere): *This app* — "Your memory lives on <host>", reachable or not
and as of when (`/healthz`, every 30 s while open), and how many captures wait on this Mac — and *Your devices*: each
device's name, when it was added and last seen, and *this Mac* on its own row. On This Mac (the master token) the page
adds a device (its token shown once, with where it goes) and revokes one; on a server's client it reads the list and
names the two commands to run on the server (ruling 28.1). Not a Store domain: `/devices` is outside every bank.

**Where memory came from.** What a device posts is stamped `device: <id>` on the server (`device_context`, `api.md`).
The app says so in one quiet word (`DeviceOrigin`, names from `DeviceDirectory`): *from laptop* on a Saved item's
"Saved from" line, in the Reader's header and on each conversation under the entity card's *Where this came from*; on a
server's client, what the server's own machine wrote reads *from this server*, and this app's own posts *from this Mac*.
On This Mac, what this Mac wrote says nothing. The bank picker's menu says *on <host>* above the memories.

## What works headless today, and what waits

| Works on the server, for the server | Works from another of the person's machines (phases 2–3) |
|---|---|
| The REST API, `/healthz`, SSE | The REST API with a device token |
| Claude Code and Codex on the server, captured by their Stop hook | Claude Code and Codex on a client, read there, posted as turns |
| Cursor and Gemini CLI on the server (`/capture/turn`) | The same hooks on a client, spooled when the server is away |
| The CLI and stdio MCP on the server | The stdio MCP and the CLI on a client, through the server |
| Scheduled Sleep on a metered key | The app (Settings → General → A server), its readers and their outbox |
| The G135 remote listener, behind the person's overlay | Settings → Devices, and the device on every conversation and save |

Known limits of phase 2: the skills tools (`cicada_skills`, `skills list|propose|create`) act on the server's agent
skill folders, not the client's; `cicada_continue` reads the continuity registry the server keeps (the client's hook
posts its workspace observations with each capture); a client command that reads the memory folder in-process
(`page list`, `graph`, `find`, `inbox all`, …) refuses rather than reading over HTTP.

Linux gaps: `sips` is macOS-only, so image decode and site-capture thumbnails fail with `DecodeError` and those
features degrade. The Neural Engine model is Apple-only. Every app-side reader (browsers, Notes, Calendar, Contacts,
Messages, watched folders) stays on the Mac by design.
