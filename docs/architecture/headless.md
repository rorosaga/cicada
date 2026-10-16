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

## Install (phase 1)

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

**On the client** (the person's Mac, say), two settings and nothing else — Cicada writes neither:

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

## What works headless today, and what waits

| Works on the server, for the server | Works from another of the person's machines (phase 2) | Waits for phase 3 |
|---|---|---|
| The REST API, `/healthz`, SSE | The REST API with a device token | The app's server setting (Settings → General) |
| Claude Code and Codex on the server, captured by their Stop hook | Claude Code and Codex on a client, read there, posted as turns | The app's readers posting to the server, its offline queue |
| Cursor and Gemini CLI on the server (`/capture/turn`) | The same hooks on a client, spooled when the server is away | |
| The CLI and stdio MCP on the server | The stdio MCP and the CLI on a client, through the server | |
| Scheduled Sleep on a metered key | | |
| The G135 remote listener, behind the person's overlay | | |

Known limits of phase 2: the skills tools (`cicada_skills`, `skills list|propose|create`) act on the server's agent
skill folders, not the client's; `cicada_continue` reads the continuity registry the server keeps (the client's hook
posts its workspace observations with each capture); a client command that reads the memory folder in-process
(`page list`, `graph`, `find`, `inbox all`, …) refuses rather than reading over HTTP.

Linux gaps: `sips` is macOS-only, so image decode and site-capture thumbnails fail with `DecodeError` and those
features degrade. The Neural Engine model is Apple-only. Every app-side reader (browsers, Notes, Calendar, Contacts,
Messages, watched folders) stays on the Mac by design.
