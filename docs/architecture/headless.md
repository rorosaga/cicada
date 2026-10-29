# Headless: Cicada on a server, without the app (G181)

The backend, Sleep, the CLI and the MCP server run on a Linux (or macOS) machine with no companion app. The topology,
the options it was chosen over, and the later phases are in
[`docs/research/2026-10-15-headless-server.md`](../research/2026-10-15-headless-server.md). This page describes what
ships.

## The topology

**One primary.** The server's backend is its bank's only git writer and runs its Sleep. Every other device is a
client of its API (phase 2: hooks, MCP and CLI; phase 3: the app). Nothing syncs a bank by git merge or by a file syncer: two writers break the episode
id rule (max-suffix+1 per local directory), the read-modify-write state files and Sleep's single mind.
What the owner decided next — a movable home, replicas on every computer, a relay — is not built; it is at the end of
this page ("Decided, not built").

**Nothing listens beyond loopback.** The service binds `127.0.0.1` only. Reaching it from another machine is an
overlay the person runs and Cicada never configures: on a tailnet, `tailscale serve --bg --https=443
http://127.0.0.1:8000` (tailnet only; never `funnel`), or an SSH tunnel. **The one public exception is not this
port (ruling 32, owner 2026-10-19):** to let claude.ai or ChatGPT sign in, the person may funnel the G135 remote
listener (`127.0.0.1:8765`, MCP and OAuth only — `network.md`), never the API. The API token is still required on every
route but `/healthz`, and `/healthz` without the token says only `status`, `version` and the bank ids — the memory's
path, its counts and the index's state need the token (owner decision 3, 2026-10-16: through the overlay, any device
on the tailnet could otherwise read the server's account name from the path; `auth.bearer_admits`; the CLI's 21a probe,
`doctor.sh` and the app send it). Tailscale's identity headers are not a substitute for it: tagged devices get none, and anyone
the device is shared with gets them.
Responses to another machine are gzipped at level 1 (`/graph` ~11× smaller); the app on the server's own Mac is
answered uncompressed. Who counts as another machine — a non-loopback peer, a forwarded request, a device token — and
why ETags are unaffected is in [`api.md`](api.md) ("Compressed only for another machine"); the headers only choose
compression, never access.

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
| Check | `/healthz` on `127.0.0.1:8000` within 60 s, then `cicada status`; the summary says where the backend's own token lives (never its value) and prints the `enable-linger` line when lingering is off. On a client (`CICADA_API_BASE` or `$CICADA_HOME/api_base` set) there is no unit to wait for and an update starts none: the check is `cicada status` against the server, a warning with the fix when it does not confirm |
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
brew install rorosaga/cicada/cicada        # --HEAD follows dev
cicada-setup                               # memory folder, search model, hooks, background service
```

The formula is named in full: Homebrew 7 refuses to load a formula by its short name from a tap the person
has not trusted — "Refusing to load formula rorosaga/cicada/cicada from untrusted tap"; the full name installs it (so does `brew trust rorosaga/cicada`, once).

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
  (`brew tap rorosaga/cicada <path-to-a-dev-clone>`) and `brew install --HEAD rorosaga/cicada/cicada`.
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
- **Known limit:** the backend computes its own repo path with `resolve()`, so the app's the Agents page, run
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

**A developer server that follows `dev`:** `scripts/dev/install-auto-update.sh` installs the same 5-minute auto-update
the Mac's developer checkout runs, as a systemd user timer (`cicada-dev-autoupdate.timer`, `Persistent=true`): it
fast-forwards the checkout to `origin/dev`, re-syncs the venv in its own shape and restarts `cicada-backend.service`,
never under a running Sleep (`scripts/dev/README.md`). Developer tooling only; a person's server follows releases by
re-running the install line.

`make doctor` (`scripts/doctor.sh`) checks `systemctl --user is-active cicada-backend.service` on Linux in place of
the launchd agent. Where there is no `make` (a minimal server) or no Makefile (a Homebrew keg), `install.sh` names
`bash <repo>/scripts/doctor.sh` as the next step instead (`doctor_hint`).

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
needs no app and no timer unit. A run the person starts (`cicada sleep start`, or a client's click) may use a plan.
**A scheduled run uses a plan only when the person said so** (TODO ruling 4b, owner 2026-10-16: "The server should be
allowed to use plans too. Just have to set them up somehow"; "Yeah chat too"): the machine's switch — **on unless the
person turned it off** (ruling 4c, 2026-10-19) — is `cicada sleep schedule --use-plan on|off` here and Settings → Sleep →
*Scheduled runs may use my plan* in the app, beside the words that nightly runs count against the plan's limits. With
it off, a server Sleeps on its schedule with a local model, or with a metered key only when the person chose it as
Sleep's engine (`cicada sleep engine --mode byok`; ruling 31: Auto never falls to a key by itself;
`capture-and-sleep.md`).

### Setting a plan up on a server

```sh
cicada engine connect claude-plan     # Claude Code's own sign-in: `claude auth login --claudeai`
cicada engine connect chatgpt-plan    # the Codex CLI's own device sign-in: `codex login --device-auth`
cicada sleep engine --mode agent      # or --mode codex: what Sleep reads with
cicada sleep schedule --use-plan on   # and let scheduled runs use it
```

`engine connect` runs in the person's own terminal on the server (it refuses from a client, from an agent's shell,
without a terminal and under `--json`, which would hide the prompts). It runs the plan CLI's own sign-in — its link,
its code, its storage — with Cicada's scrubbed environment (a provider key in the shell never turns it metered; the
Codex CLI signs in to Cicada's own `CODEX_HOME`), then asks the backend to probe the plan again. Cicada never sees,
prints or stores the token. Where `claude auth login` cannot finish, `claude setup-token` on any machine prints a
long-lived token the person sets as `CLAUDE_CODE_OAUTH_TOKEN` in the unit's own environment (`systemctl --user edit
cicada-backend.service`); Claude Code reports it as `authMethod: oauth_token`, which reads as a signed-in plan.

**Readiness is said, not guessed** (owner decision 2, 2026-10-16). `cicada engine list` says each engine's state in
words — `key set` / `no key`, `signed in (<plan>)` / `not signed in` / `not installed`, `running` / `not running` — then
what a run you start and a scheduled run would use, and whether scheduled runs may use the plan. While a schedule is
on and a scheduled run would have no engine it may use, `GET`/`PUT /sleep/schedule` carry `warning` and `warningCode`
(`engine_readiness`: `no_engine`, `plan_signed_out`, `plan_not_chosen`, `local_down`), and `cicada sleep schedule`,
`engine list` and Settings → Sleep say it with the fix — connecting a plan first. `ask` on a machine with no engine
says so and names the pages it found, never a keyless call.

## Commits with no git identity

A fresh server has no `user.name`/`user.email`, and git refuses to commit; a fresh Mac has none either, and git guesses
one from the account (its full name and `user@hostname`), so every commit of a bank handed to someone else would carry
both (G203). `git_service.ensure_commit_identity_sync` runs for every bank that becomes active: `scaffold_bank` (startup
and every new or copied bank) and `run_bank_migrations` (every runtime switch, the demo's two doors included, before any
migration commits). It fills, in the bank's own config, **only the half nobody configured** with the neutral value
(`user.name Cicada`, `user.email cicada@localhost`). Each half is asked of git with `user.useConfigOnly=true` and the
other half stood in, so a guessed half counts as missing; `EMAIL` counts as a configured email, since git honours it.
A configured half is the person's choice and stays: a global `user.name` with no email commits as that name with the
neutral email, rather than having the name hidden in this bank. It never writes `~/.gitconfig` and never rewrites a
commit already made: a bank's older commits keep the author they were made under. `install.sh`'s first commit asks the
same way, half by half. Who wrote a change
is the `Cicada-Author` trailer's job, not git's author field, so nothing about provenance changes (the readers are in
`storage.md`, "Git — versioning and provenance").

**A verify run on a headless host (2026-10-22).** The verify skill (`.claude/skills/verify-cicada/`) runs Sleep on the
plan through `claude`. On a Linux host with no keychain the plan signs in through `CLAUDE_CODE_OAUTH_TOKEN`: export it
in the shell that runs `cv launch`, and `cv` hands it to the engine's `claude` child alone, through a 0600 file in the
run dir, never the scratch backend's environment; `cv cleanup` deletes the file and masks the value in the evidence.

## Clients on other machines (phase 2)

**A phone or another machine pairs by code (G212, 2026-10-22):** `cicada device pair [--kind capture|full]` (or the
app's QR) shows a one-time code; the device trades it once at `POST /pair` for its own token — a phone's is
capture-only (`api.md`, "A phone is capture-only"). The QR names this machine's tailnet address for the backend only
when the person already serves the backend port to their tailnet themselves, e.g. `tailscale serve --bg --https=8443
8000` — tailnet only, never funnel; the backend still binds 127.0.0.1 and Cicada runs no tunnel command except that
one serve and its off, on the person's click (below).

**Guided, checked and key-bound (G212, 2026-10-29).** Settings → Devices reads the overlay's state (`GET
/devices/reach`: Tailscale missing, not running, signed out, off, serving or funnelled) and shows the one next step,
the serve as a command to copy — and, since the owner's "Yes, one click" (2026-10-29, `network.md`), *Run it for me*
runs exactly that command and *Stop serving* that one mapping's off, never a funnel; *Check again* fetches the served address the way a phone would and names the step that
failed (the name, the overlay, the backend, something else answering). A phone pairs with a proof of its Secure-Enclave
key, so its token is useless off the phone (`api.md`, "Key-bound device tokens"). A computer client stays unbound for
now: its hooks, MCP server and CLI share one token and the hooks are stdlib-only, so none of them can sign yet.

Owner rulings 2026-10-16 (TODO ruling 28): per-device tokens; the transcript rail amended; a tailnet device of the
person's counts as local for the G198 trust list.

**On the server**, once: `cicada device add <name>` (the person's own terminal; `POST /devices` with the master token
does the same; its answer's `sameName` lists the active devices already called that, and the command warns — two
devices may share a name, but the list then cannot tell them apart). It prints the device's token once and keeps only its hash. `cicada device list` shows each device and
when it was last used; `cicada device revoke <id>` ends it at once. The master token (`~/.cicada/api_token`) never
leaves the server, and a device token can neither issue nor revoke one.

**On the client** (the person's Mac, say), two settings and nothing else — set by the person, or (phase 3) by the
app on the person's click in Settings → Devices, which puts `$CICADA_HOME/api_base` in place when Cicada next opens
and writes `device_token`, both 0600:

- `CICADA_API_BASE` — the address the person's own overlay gives the server (`https://…` for any host; plain `http://`
  only to a loopback address, i.e. an SSH tunnel's local end). Set where the hooks, agents and shells inherit it.
- the device token in `~/.cicada/device_token` (mode 0600), or `CICADA_API_TOKEN`.

A Linux client gets the code, the hooks and the command with the server's own one line, run with `CICADA_API_BASE`
exported (`install.sh` then installs no backend; the summary names the device token, not a master token). On a Mac,
the app's Settings → Devices → *A server*, or Homebrew's `cicada-setup` with `CICADA_API_BASE` set.

Unset, every client behaves exactly as on one machine. Set, the machine holds no bank — and gets none: `install.sh`
on a client makes no memory folder, writes no `CICADA_MEMORY_PATH` and registers the MCP server without one (owner
decision 4, 2026-10-16); the app in client mode spawns no backend, the only thing that ever made the folder. Every client sends its token
straight to that address: no proxy from the environment, and no redirect followed (`runtime_layout.opener`,
`hook_client.opener`) — urllib would re-send a redirected post as a GET, token included, to wherever it points, and its
200 would read as delivered. A 3xx is the answer: a hook keeps the post in its spool (its log line names the redirect), and a tool call, the
command and `cicada status` say in words where it pointed (scheme and host only) and to set `CICADA_API_BASE` to the
server's own address — an `http://` base the server sends to `https://` is the case a person meets
(`runtime_layout.redirect_text`).

| Client | What it does with a base set |
|---|---|
| Claude Code / Codex Stop hook | Reads the session here with Cicada's own extractor and posts the scrubbed, capped turns to `/capture/session`; ids are minted on the server (one episode per session). A server that is away: the post waits in `~/.cicada/spool/capture/` and a later firing — or any MCP call or command that reaches the server — sends it (`capture-and-sleep.md`, "What waits goes only where it was meant" below) |
| Cursor / Gemini CLI hooks | Post turns to `/capture/turn` as before, spooled in order when the server is away |
| Recall hooks (SessionStart, UserPromptSubmit) | Ask the server's `/capture/hook-context` |
| stdio MCP server | Every tool runs on the server through `POST /tools/call` (the same bodies); pictures named by path are read here and sent as base64; `cicada_repo_context` probes git here (`mcp.md`) |
| `cicada` command | Tool mirrors through the server, `backend` commands to its routes, the bank pinned by name and id; commands that read the memory folder refuse `on_server`; refuses `backend_down` when the server is away |

**Identity, not paths.** Every bank has an `id` in `banks.yaml` (minted by the backend at startup, new for a copy,
kept by a rename). `/healthz` reports the ids, a client pins the server's active bank by name and id, and every
mutating request names both (`X-Cicada-Bank`, `X-Cicada-Bank-Id`), so a write meant for one memory never lands in
another that happens to share a bank name. Ruling 21a's check compares these ids (path only when a side has none).

**What waits goes only where it was meant (G202, 2026-10-22).** The two-device test found a session split across
two memories: a hook's capture waiting offline was delivered to whichever server the client pointed at next. Now:

- Each hook spool entry names its **target** — the address (`runtime_layout.api_base`) and, once heard, the bank id the
  server's capture answer gave (`bankId`, kept per address in `spool/capture/.servers`). A flush sends only the entries
  for the address in use; a resend carries `bank_id`, and `/capture/session` and `/capture/turn` refuse it with 409
  `bank_mismatch` only when no bank of that server's memory has the id — the address now leads to another memory. A
  bank switch on the server itself files the resend where a live capture of the same session goes (a session is never
  split between two banks of one memory). Entries for another server wait, never dropped; the hook's log line says how
  many and for which host. A session keeps one entry per server. An entry from before (no target) goes where the
  client points, as it did.
- A refused entry is **held** for its own memory (review of #408): counted as waiting for another memory, never in
  front of this server's turns, retried at most every 10 minutes; the address's remembered bank is forgotten, and a
  turn queued behind waiting turns is stamped only after they were flushed, so new captures never carry a refused
  bank. The next capture that lands teaches the address its bank again.
- The app's outbox posts carry the same target (`base`, `bankId` beside the bank's name); a flush sends only this
  connection's, and every write on a server names `X-Cicada-Bank-Id` (ids learned from `/banks`). This Mac sends names
  only, as before.
- Waiting captures are said: `cicada status` (client and local) and Settings → Devices count the hooks' spool and the
  outbox, for this server and for a server this machine no longer uses. A successful stdio MCP call (in the background)
  or `cicada` command flushes what waits for its server, not only a hook's next firing.
- The handshake's Now line names the bank as the roster does (`default`, never the folder) and, on a client,
  `on <host>` (host and port only); a running MCP session whose server or bank changed says so once, in one line, on its
  next reply (`tool_client.where_changed`).

Not fixed here: a device on claims and commits (G181's open item), queued MCP/CLI writes while the server is away, and
two primaries (G132: both mint the same episode ids and both call their bank `default`, and nothing warns).

**What did not change.** Only the server commits (one git writer per bank); the server binds 127.0.0.1; reach is the
person's overlay; no installer creates, copies or logs a credential; the demo guard and the split-brain rule are the
server's, per request. The G135 remote listener is still the door for apps off the person's devices, never trusted to
edit a page. **Sign-in on a server with no app (ruling 32):** an app's sign-in waits for a yes the app would give; on a
headless server the person gives it on the server itself, through the loopback API with the token —
with the code the app's sign-in page shows: `POST http://127.0.0.1:8000/remote/oauth/match` with `{"userCode": "<code>"}`
(and `-H "Authorization: Bearer $(cat ~/.cicada/api_token)"`) says who it is and where it returns, and
`POST …/remote/oauth/approve` with `{"userCode": "<code>", "scopes": ["search","read","record"], "expiresInDays": 30}`
approves it; `GET …/remote/oauth/requests` lists what waits (times only) and `…/requests/deny-all` clears it.

## The Mac app as a client (phase 3)

Settings → Devices → *Where your memory lives*: **This Mac** (as always) or **A server** — the address the person's
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
  (`ReaderOutbox`: 0700/0600, named by route + memory (server, bank name and id, G202) + body hash, ≤ 200 posts / 64 MB / 7 days; no answer, 401/403,
  409 and 5xx wait, 400/404/405/413/422 are dropped; a stopped run's post — the person's Cancel, or a bank switch
  replacing a reader's run (G183(d)) — never waits). A newer post on the same route and memory never overtakes one
  that waits: those go first, and while one still cannot land the newer waits behind it (a snapshot replayed late would
  put the server back to an older state). It is flushed oldest first when the event stream connects again
  (and by *Send now* on the Devices page), **lane by lane** (route + memory, owner decision 6, 2026-10-16): no answer
  or a refused token (401/403) stops the flush, but a post the server answered and did not take — another memory's
  409 after a bank switch, a 5xx — waits with the newer posts of its own lane while the other lanes, the active
  memory's among them, still go; the readers keep their cursors and read again, so the outbox is the fast
  path and the server's dedup makes a resend harmless;
- refuses the demo (`ServerLinkError.demoStaysLocal`, before any request): a demo is a This Mac thing.

**Settings → Devices** (Customize, after Agents; From anywhere is its last group since the Hyrum audit's B1): *Where your memory lives* — the choice above and, only while
this app runs on a server, "This app is using <host> now.", reachable or not and as of when (`/healthz`, every 30 s
while open), and how many captures wait on this Mac (the outbox and the hooks' spool, G202) — plus, on either mode, those kept for a server this Mac no longer uses — and *Your devices*: each
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
| Scheduled Sleep on a metered key, a local model, or the person's plan when they allow it (ruling 4b) | The app (Settings → Devices → A server), its readers and their outbox |
| The G135 remote listener, behind the person's overlay | Settings → Devices, and the device on every conversation and save |

Known limits of phase 2: the skills tools (`cicada_skills`, `skills list|propose|create`) act on the server's agent
skill folders, not the client's; `cicada_continue` reads the continuity registry the server keeps (the client's hook
posts its workspace observations with each capture); a client command that reads the memory folder in-process
(`page list`, `graph`, `find`, `inbox all`, …) refuses rather than reading over HTTP.

Linux gaps: `sips` is macOS-only, so image decode and site-capture thumbnails fail with `DecodeError` and those
features degrade. The Neural Engine model is Apple-only. Every app-side reader (browsers, Notes, Calendar, Contacts,
Messages, watched folders) stays on the Mac by design.

## The home publishes its log (G132 phase 1, ruling 51a/d/e — built, off by default)

The first half of phase 1: the machine that holds the bank (the home) can publish its history so a replica (phase 1's
second half, not built yet) can follow it. **Off by default**: on only with `CICADA_SYNC_PUBLISH=on` or
`$CICADA_HOME/sync/settings.json` `{"publish": true}`, which `PUT /sync/publish` writes (the server's own token only;
the Settings → Devices switch arrives with the replica). The environment wins over the file both ways. Off, `/sync/log`,
`/sync/pack`, `/sync/status` and `/sync/publish/from-here` answer a plain 404, nothing is written under
`$CICADA_HOME/sync/`, the capture writers record nothing, and the lifespan, the MCP door and every client route never
read the switch (`test_sync_off_unchanged.py`). **A demo bank is never published**, nor a bank that is not its own git
repository. Every route takes a full device token or the server's own; a capture-only device gets 403.

- **The log** (`sync_log`, `GET /sync/log?since=<seq>&limit=≤1000`): `{bankId, head: {seq, sha}, entries: [{seq, sha,
  parent, at}], more}`. A commit's **seq** is its position on the first-parent chain from the root (the root is 1):
  derived, no trailer, the same on every device holding the same history, and it only grows (no bank writer rewrites
  history). The sidecar `$CICADA_HOME/sync/<bank key>/log.db` is disposable (rebuilt from `git log --first-parent`);
  it catches up from loose commit objects read with zlib (a just-made commit), else one read-only `git log`. The log
  never carries a subject, a path or a title. **A rewritten history freezes it** (51e3): when the last published commit
  is no longer the first parent of what follows it on HEAD's chain (a hand amend, a reset, a rebase), every route answers
  409 `history_rewritten` with its last seq and sha and a sentence, and stays frozen — new commits heal nothing —
  until the person's "publish from here" (`POST /sync/publish/from-here`, the server's own token), which starts the
  sidecar over; replicas then copy the bank again. A failed git read answers 503 and freezes nothing.
- **The pack** (`sync_pack`, `GET /sync/pack?have=<sha>`): a git bundle of `have..HEAD`, or the whole history without
  `have`, built with `git bundle create` into a private temporary folder outside every bank and removed once sent —
  read-only on the bank (no ref, index or lock), and since a bundle holds only committed objects, never a derived index
  or an untracked file. Headers `X-Cicada-Seq`, `X-Cicada-Head`, `X-Cicada-Bank-Id`; 204 when nothing is new; 404
  `unknown_base` for a `have` this home never published (ask again without it); 413 past `CICADA_SYNC_PACK_MAX_MB`
  (2 GB). Only its size and seq are logged.
- **The status frame** (`sync_status`, `GET /sync/status`): `{bankId, seq, log, home: {device, name}, sleep, schedule:
  {mode, enabled, hour, minute, intervalHours, nextAt}, queue: {waiting, parked}, engine: {label}}`. `sleep` is the SSE
  `sleep` event's payload, built by the same function (`sync_status.sleep_event`, which `/sync/events` now calls);
  the queue is episode ids only, never a title; the engine label is `plan`, `key`, `local`, `auto` or `none` (never a
  provider's or model's name).
- **The primer** (51e): `/sync/log` and `/sync/status` bring `_state.md` current first (`state_dictionary.refresh_admitted`:
  it still commits alone, and is skipped while Sleep holds the pages), so a replica never serves an older primer than
  the home's.
- **The capture commit** (`capture_commit`, 51e1): only while publishing, `transcript_capture.write_session` — the one
  writer behind the session, turn and relay capture paths, at the point its write completes — records the path, the
  sha256 of what it wrote and the hash of what the path held before its chain began (`$CICADA_HOME/sync/<bank
  key>/captured.json`: paths, hashes, times). A daemon thread (it ends when nothing waits) commits a path once it has
  settled 10 s, at most once a minute per bank (all due paths in one commit), and only while the file still hashes to
  what the writer recorded: the bytes it checks are the bytes it commits, through a private index
  (`git_service.commit_contents_sync`), so nothing else staged or dirty rides in. `Capture <date>`, manifest lines
  `episodes/<id>.md: created|updated (source: n/a, trigger: sync/capture)`, `Cicada-Author: cicada`, under write
  admission shared, skipped while Sleep writes. A path someone else changed after the writer is dropped and left
  uncommitted; when what the writer wrote over was someone's uncommitted edit, that edit is committed first, alone, as
  `Uncommitted edit kept apart <date>` with no author (trigger `sync/kept-apart`). Kept apart is only ever bytes that
  are neither committed nor a capture writer's: each record keeps every hash its own chain wrote, so when another
  writer's `add -A` (a poll, a Sleep batch) committed one of them meanwhile, the path is clean and nothing older is put
  back on top of it (review of #565). Measured cadence (an owner-bank copy,
  28 captured sessions, 1,090 reply gaps, p50 211 s): a session's busiest hour makes p50 8 / p90 24 / max 41 commits.
  The capture path itself still commits nothing and runs no model. Each capture commit moves `git_head`, so the app's
  `version` event and the ETags keyed on it move with it.
- **Idempotent tool writes** (51a): `POST /tools/call` takes an `Idempotency-Key` on a mutating tool (cli_map's
  `mutates`), scoped by the device (or `server`) and the pinned bank id, under the route `/tools/call:<tool>`, kept 8
  days (`idempotency.TOOLS_TTL_S`; every other route keeps a day). A resend replays the first answer; a refusal (a
  `REFUSAL_CODES` code) or an error is never kept, so it runs again. A read is never keyed. While publishing, the reply
  adds `seq` — the home's head once the write committed — and a body's `base_seq` is recorded beside it in the sidecar
  (`bases`), never enforced. Off, the reply is byte-for-byte what it was.

## A computer keeps a copy (G132 phase 1 B, ruling 51a/d/e2 — built, off unless set)

**The mode.** `runtime_layout.mode()` is `local`, `client` or `replica`. Replica: `CICADA_REPLICA_OF` (else
`$CICADA_HOME/replica_of`, one line, 0600 — `PUT /sync/replica` writes it with the device token after checking the
home answers with that token and publishes a memory that is not a demo), the same address rule as `api_base` and the
same device token (`device_token`). Both a client address and a home set: **client**, and `mode_conflict()` says so
in words (logged at start, shown by `GET /sync/replica`). Unset, nothing changes (`test_replica_off_unchanged.py`): the
mode is what it was, the lifespan schedules as before, the route table and the guard are inert, no thread starts, and
a home that does not publish adds no header.

**What a replica runs.** Its own backend on loopback, with a lifespan of its own (`main._replica_lifespan`): no
scaffold, migration, owner seed, schedule, catch-up, poll, connector sync, remote listener, Telegram or reindex job —
only the query embedder's warm-up, the words index and the follower. **The backstop** (`replica_guard`) refuses every
bank writer outside the follower's apply (`replica_guard.applying()`): git's write subcommands and `.git` writers
(`git_service._git_sync`, the private-index commit), `markdown_parser.write` / `write_new` (and so
`episode_ids.create_episode` and every capture writer), with `ReplicaReadOnly` (a `PermissionError`; under git also
a `GitError`, which every caller handles); `state_dictionary.refresh` is a no-op (`reason: replica`), so `GET /state`
serves the home's `_state.md`. Every GET route walked on a copy writes nothing and none answers 500
(`test_replica_get_routes_write_nothing.py`).

**Bootstrap and follow** (`replica`). With no copy: the home's `/sync/status` (bank id and name), the whole
`/sync/pack`, `git_service.bootstrap_from_bundle_sync` into `<root>/banks/<name>` (`-copy` when the name is taken),
registered in `banks.yaml` **under the home's bank id** with `replica: true`, and made active; every other bank on the
computer is left as it was, inactive. The marker `$CICADA_HOME/sync/<bank key>/replica.json` (`{home, bankId, seq,
sha, appliedAt}`) is this computer's alone. Then a reader thread holds the home's `/sync/events` open: a `version`
whose `git_head` is not the copy's wakes the follower, and each `sleep` event is kept as the home's frame. The follower
also wakes every 10 s by itself, and on a write's `seq`. It asks `/sync/pack?have=<copy's sha>` and
`git_service.fast_forward_sync` applies it under the bank's write lock: fetch into `refs/cicada/home` (`fetch` is now
a write subcommand), **the ancestry checked by the copy itself** (`merge-base --is-ancestor`, never a seq trusted),
a dirty tracked file refused, each changed file written atomically (a temp file beside it, fsynced, `os.replace`) and
each removed one unlinked, then `update-ref HEAD <new> <old>` and the index brought to it. The page cache and
`bank_index` are invalidated, the words index catches up inline (`ensure_fresh(wait=True, max_age_s=0)`), and the
meaning index catches up in the background from the changed episode stems only (`index_episode_stems`; a changed
entity page runs the hash-skipping sync). Offline it backs off 1 s doubling to 60 s. A 401/403 (a revoked device)
stops it at once: status `revoked`, nothing more fetched or sent. A rewritten home (409 `history_rewritten`) or a
head that does not descend stops it (`home_rewritten`, `diverged`) and says so; only the person's "Copy again"
(`POST /sync/replica/recopy`) writes the home's tree over the copy. Only seqs, counts and timings are logged.

**Writes are transactions** (`tx_outbox`, `$CICADA_HOME/spool/tx/`, 0700/0600, oldest first). Three doors:

- **The tool door.** cli_map's `replica` column says where a tool runs on a copy: every `mutates` row and the reads
  of the stores the home keeps outside every bank (`cicada_video_queue`, `cicada_reading_queue`,
  `cicada_explore_queue`) are `home`, every other `local`. The stdio MCP server and the `cicada` command send a `home`
  row to this computer's own backend (`tool_client.call(local=True)`; the CLI after its ruling 21a probe and
  `require_person`), whose `/tools/call` keeps it in the outbox and sends it to the home's `/tools/call` with its
  `Idempotency-Key` and the bank id. The home's answer comes back; its `seq` wakes the follower and the reply waits up
  to about 2 s for the copy to reach it (read-your-writes). Unreachable: "Queued for the home…" (`code:
  queued_for_home`), sent in order when the home answers again. A replica's transaction (it carries `base_seq`) that
  saves an episode — a note, a link — commits alone at the home under its harness, as a remote save does (R-R11), so
  the copy can read it back; a stdio save on the home itself stays uncommitted as before.
- **The app's REST writes** (`replica_routes`, hand-written, every non-GET route; `replica_forward`, one ASGI
  middleware): `forward` (the same route at the home, keyed, naming the home's bank id; 503 `home_away` when the home
  is unreachable, nothing changed), `capture` (the same, but kept in the outbox and answered 202 `queued` while the
  home is away), `refuse` (409 `replica_read_only`: bank lifecycle, devices, the remote listener, publishing,
  maintenance runs, the home's source sign-ins), `local` (this computer's engine sign-ins, search model, skills
  folders, sealed traces, reads computed here). The app's bank name is checked against the copy first; only this
  computer's own token is accepted. A home that publishes adds `X-Cicada-Seq` to every write's answer, so a forwarded
  write waits for the copy to catch up too. `test_replica_routes_inventory.py` fails on a route the table misses.
- **The hooks.** On a copy, capture goes to the home the way a client's does (`hook_client.captures_elsewhere`,
  the existing spool and its targets); recall reads this computer's own backend, the copy.

The outbox keeps hook_spool's rules: no answer, 401/403, `sleep_writing` and 5xx wait (and stop the flush, so order
holds); 400/404/405/413/422 are dropped and counted; 409 `bank_mismatch` is held aside and retried every 10 minutes;
any other refusal (the item was answered elsewhere) leaves the outbox and is kept in `rejected.json` by id, tool or
route and code, never its arguments (the G132 g1 gate's first answer: shown, never silently lost). An entry expires
after 7 days, a day before the home's key.

**Reads are local; §3a holds.** MCP read tools, the handshake (built from the copy, R12 and the budget unchanged), the
app's pages and `/search` answer from the copy. `/sync/status` on a copy is the home's frame (Sleep from the home's
own events, schedule, engine label, name) with the copy's seq and queue and an `outbox` block beside it (counts: this
device's transactions, held, rejected, and its hooks' captures waiting); the SSE `sleep` event is the home's payload
plus the same `outbox`; `GET /sleep/status` is the home's (503 `home_away` with the last frame when it is away); the
inbox and the queue are the copy's files, so at the same seq they are the home's (`test_replica_two_machines.py`).
"Sleep now" pressed on a copy is the home's `POST /sleep/trigger`.

`GET /sync/replica` (a full device or this computer's own token) says the mode, the follower's words, seqs and how far
behind it is, and the outbox counts; `PUT`/`DELETE /sync/replica` and `POST /sync/replica/recopy` are this computer's
own token only (`auth.MASTER_ONLY_WRITE_PREFIXES`). A change of mode takes effect from the backend's next start.

Known limits of phase 1: a copy's media files and pictures posted from it live at the home (outside every bank) and
are not copied; `cicada_continue` reads this computer's own continuity registry; `cicada_ask` uses this computer's
engine; an interactive app write made while the home is away is refused, not queued (phases 4/5).

## Decided, not built (G132, ruling 51)

Everything above describes what ships (the home's publishing, just above, is phase 1's first half). This section
records what the owner decided on 2026-10-29
([TODO ruling 51](../goals/TODO.md), [the plan](../plans/2026-10-29-g132-sync-engine.md), the G132 row's phases); none of
it is built, and until each phase ships the topology above is the one that runs. Unset or off, nothing here changes a
single-machine install: no relay, no replica mode, no new process.

**The home and its replicas.** The "one primary" above becomes **the home**: exactly one replica of the bank applies
writes, mints ids (the id rule unchanged — at apply time, under the same lock), commits and runs Sleep. It may be a
server or any of the person's computers. Every other computer may hold **a full replica** — the bank's git checkout and
its derived index — and answers reads from it (recall, the graph, `cicada_ask`'s retrieval, the app's pages, the MCP
read tools), so memory keeps working with the home asleep or the network gone. A replica only **fast-forwards**: it
asks for the home's commits since its own sequence number and never commits, so a fast-forward always succeeds and
nothing is ever merged by git or a file syncer. Its derived index updates from the changed paths, as it is rebuilt from
files today.

**Writes are transactions.** On a device that is not the home, every write — a capture, a save, an inbox answer, a
claim written or withdrawn, a page edit, a backlog item — is `{idempotency key, device, bank_id, base_seq, tool, args}`,
kept in that device's outbox (the hook spool and the app's outbox, generalised) and applied by the home **through the
same tool body it runs today** (`/tools/call`). Scrub, staging, the demo guard, authorship and write admission therefore
apply at the home by construction; a transaction is a tool call, never a file diff. One that no longer applies (the
inbox item was answered elsewhere) is rejected with a reason. Capture never blocks on the network: an unreachable home
queues, it does not fail.

**Capture commits on the home, replicas are a mode, history only grows (ruling 51e).** Today the session, turn and
relay capture paths write the episode file and leave the commit to Sleep's batch or a poll's sweep; a replica follows
commits, so while the home publishes its log a debounced background step commits only the episodes those capture
writers themselves wrote: each writer records the path and content hash it wrote, and the step commits a path, settled
≥ 10 s, only while its hash still matches — as `cicada` with trigger `sync/capture`, holding write admission shared,
skipped while Sleep is writing, never another path and never `_state.md`. Any other dirty `ep_*.md` (the person's own
hand edit, another writer's) keeps its edit uncommitted or is set apart as `agent_commits` does ("Uncommitted edit kept
apart"), never committed as `cicada` — a write commits alone, under its true author. The capture path itself still makes no commit and runs no
model; with publishing off, nothing changes. **Replica mode** is a third runtime mode beside local and client:
read-only, never Sleep or a schedule, never a commit of its own, with a backstop guard that refuses every bank writer;
reads write nothing there, so `GET /state`'s refresh-and-commit is a no-op on a replica and refreshes at the home. If
the home's published history is ever rewritten (a hand amend or reset in the bank), publishing freezes and says so in
words; only the person's "publish from here" resumes it, and the replicas re-copy. **A demo bank is never published or
replicated.**

**The bank's state is the bank's.** The consolidation queue (the replica's `processed: false` episodes), the inbox and
Sleep's status (running, its stage, the last run, the schedule — a small frame the home publishes) read the same on
every device at the same sequence. "Sleep now" pressed anywhere is a transaction to the home. What is still on its way
— this device's outbox, the relay mailbox's count per sending device — is shown beside the queue, never mixed into it.
Ruling 4 is untouched: Sleep runs only on the home, a scheduled run under the person's switch as today.

**Moving the home.** The Sleep page names the device that consolidates now, with its state, and every other device with
how far behind it is and whether it is online; picking another and confirming (or `cicada home move <device>`) is a
hand-off: the target catches up, the current home stops admitting transactions, finishes or parks a running Sleep and
writes a signed hand-off record `{bank_id, seq, from, to, at}` as its last commit; the target fast-forwards to it,
verifies it and starts admitting. Queued transactions carry `bank_id`, not an address, so they re-target by themselves.
"Who consolidates" and "who orders writes" are one concept and never split. **A lost home** is taken over by another
replica only after the person confirms, with the replication lag shown first; an old home that comes back sees the
newer hand-off and becomes a replica, its later commits offered back as transactions, never merged.

**Reach and the phone.** Every device dials out to the relay (`network.md`, "Decided, not built"), or reaches the others
directly on a LAN or tailnet; no device listens on a public port, and the backend's own loopback bind is unchanged.
The phone becomes a full device with a partial replica (its scope is open; the plan proposes the inbox, the entity
index and recently opened pages, the rest on open), its writes transactions like a computer's, its token still bound to
its Secure-Enclave key; revoking any device rotates the device-group key.

**Open, decided in the build (the G132 row's phase gates):** what happens to a transaction the home rejects while its
device is offline; the mailbox's bounds and expiry; how the device-group key is distributed at pairing and rotated on
revoke; the relay's stack (measured in phase 3); how a device gets a TLS certificate for a relay-issued hostname under
TLS passthrough; the phone's partial-replica scope.
