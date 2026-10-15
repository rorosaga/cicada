# Headless: Cicada on a server, without the app (G181)

The backend, Sleep, the CLI and the MCP server run on a Linux (or macOS) machine with no companion app. The topology,
the options it was chosen over, and the later phases are in
[`docs/research/2026-10-15-headless-server.md`](../research/2026-10-15-headless-server.md). This page describes what
ships.

## The topology

**One primary.** The server's backend is its bank's only git writer and runs its Sleep. Every other device is a
client of its API (phases 2–3). Nothing syncs a bank by git merge or by a file syncer: two writers break the episode
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

- `api_token` (0600): the master token. It never leaves the server; per-device tokens are phase 2.
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

## What works headless today, and what waits

| Works on the server, for the server | Waits for phase 2/3 |
|---|---|
| The REST API, `/healthz`, SSE | Clients on other machines naming the server (`CICADA_API_BASE`) |
| Claude Code and Codex on the server, captured by their Stop hook | A harness on the Mac capturing into the server: it posts a path today, which the server must refuse (the transcript rail) |
| Cursor and Gemini CLI on the server (`/capture/turn`) | Per-device tokens |
| The CLI and stdio MCP on the server | The stdio MCP on the Mac against the server's bank |
| Scheduled Sleep on a metered key | The app's readers posting to the server; the app's server setting |
| The G135 remote listener, behind the person's overlay | |

Linux gaps: `sips` is macOS-only, so image decode and site-capture thumbnails fail with `DecodeError` and those
features degrade. The Neural Engine model is Apple-only. Every app-side reader (browsers, Notes, Calendar, Contacts,
Messages, watched folders) stays on the Mac by design.
