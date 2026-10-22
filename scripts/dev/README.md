# Live-check helpers (macOS, the orchestrator's tools)

Synthetic `osascript … click at` and plain keystrokes do not reach SwiftUI rows in Cicada's window, so
the live checks after a merge use these three instead. Build each once with `swiftc -O <file> -o <name>`.

- `winall` — lists on-screen windows as `<id> <owner> | <title> | W x H @ X Y`; the app window is the line
  containing `Cicada | Cicada`. Capture it with `screencapture -x -o -l <id> out.png` (2× pixels).
- `axfind "<text>" [press]` — lists accessibility elements whose description, title or value contains the
  text; with `press`, AX-presses the first matching button (rail items, inbox rows, "Show in
  conversation", menus).
- `cgclick <x> <y>` — posts a real mouse click at SCREEN points (the graph canvas is a web view, which
  AX cannot reach); window points are window origin + offset.

They need Accessibility permission for the terminal. Never point them at a real bank for screenshots —
README images come from a freshly generated demo bank only (the privacy rule).

## Keep privacy grants across rebuilds

`app/CicadaApp/install_app.sh` signs ad hoc unless it finds something better, and macOS keeps a privacy grant
(Documents, Contacts, Calendar, Apple Events) against the app's designated requirement. An ad-hoc signature's
requirement is the build's own code hash, so every rebuild — `make install-app`, `make dev`, or the auto-update after
each merge to `dev` — looks like a new app and asks again. A certificate-signed build's requirement is "this bundle id,
signed by this certificate", which a rebuild keeps.

Measured 2026-10-14: Full Disk Access granted to an ad-hoc build read "Needs Full Disk Access" again after the next
dev auto-update — TCC keys an ad-hoc app's grants to its cdhash, so Full Disk Access, Contacts, Calendar, Automation
and Screen Recording are all dropped silently by every update.

Once per Mac, make a self-signed code-signing certificate (free, no Apple account):

1. `make signing-identity` (`scripts/dev/make-signing-identity.sh`), at the keyboard. It (1) creates **Cicada Local**
   in the login keychain with `openssl` and `security import … -T /usr/bin/codesign`, keeping one already there;
   (2) authorises codesign to use that key without a dialog — sets its partition list to `apple-tool:,apple:`, what
   `security set-key-partition-list` writes, asking for the login password once on the terminal; (3) signs a throwaway
   copy of `/usr/bin/true` under a 30 s limit to prove it. Each failure names its step and the reason. Step 2 names the
   key by its public-key hash, read from the chosen certificate, and changes it with `authorise-signing-key.swift`
   (built with `swiftc`): `security import` labels every key "Imported Private Key", so the old
   `set-key-partition-list -l "Cicada Local"` found no key, and matching that label would change every other imported
   key. A re-run after that failure keeps the identity step 1 made and authorises it.
2. `make install-app`, then grant Full Disk Access (and any other permission) once more, to this first
   certificate-signed build.

The auto-update installs with `CICADA_UNATTENDED=1`: `install_app.sh` then signs under a time limit
(`CICADA_CODESIGN_TIMEOUT`, 120 s; `cicada_codesign_bounded`), and a key prompt nobody answers skips the update — the
installed app kept, a log line naming `make signing-identity` — instead of hanging the job.

The install then says `Signed and verified with "Cicada Local" (<hash>)`. It finds the certificate in
`security find-identity -p codesigning`, where an untrusted self-signed one is listed only without `-v`, and signs by
its hash. `CICADA_SIGN_IDENTITY` overrides the choice (`-` forces ad hoc). The chooser is
`app/CicadaApp/sign_identity.sh`.

Grants given to the last ad-hoc build do not carry over: macOS asks once more after the first build signed with
Cicada Local, and from then on a rebuild keeps them. This is a local signature, not a Gatekeeper-trusted one.

## The auto-updater waits out Sleep

`auto-update.sh` asks the backend (`GET /sleep/status`, 10 s, the bearer token from `$CICADA_HOME/api_token`, port
`$CICADA_PORT` or 8000) before it fetches. A running cycle, an open write window, an unfinished drain (paused
included) or a running inbox tidy (`inboxTidy`, ruling 29) logs `deferred: Sleep is running` and changes nothing — no fast-forward, restart, app build or stamp move; the
next tick retries. Only a refused connection (nothing listening) or a missing token proceeds: a timeout, any other failure, an HTTP
error or an unreadable answer means a busy backend, so it defers too.
`CICADA_AUTOUPDATE_FORCE=1` skips the check. The backend restarts only when runtime code moved (`api` outside
`api/tests`, `mcp`, the dependency files); a test-only or benchmark-only merge never restarts it.

## The auto-updater on a Linux server (G181)

`scripts/dev/install-auto-update.sh` on Linux writes a systemd **user** timer instead of the launchd job:
`cicada-dev-autoupdate.timer` (`OnCalendar=*:0/5`, `Persistent=true`, so a mark the machine was off through runs once at
boot) starts the oneshot `cicada-dev-autoupdate.service`, which runs `auto-update.sh` with uv's folder on its `PATH`.
The installer starts one run at once (launchd's `RunAtLoad`); `--uninstall` disables and removes both units.
`SYSTEMD_USER_DIR` overrides the unit folder, as for `install-backend-service.sh`. The job's own output goes to
`logs/auto-update.systemd.log`; what it did goes to `logs/auto-update.log`, as on a Mac.

`auto-update.sh` keeps every guard (on `dev`, no tracked changes, fast-forward only, waits out Sleep, the installed
stamp). On Linux it then restarts the systemd user unit `scripts/install-backend-service.sh` installs
(`cicada-backend.service`, or `CICADA_BACKEND_UNIT`) when runtime code moved and the unit exists; re-syncs the venv in
its own shape when the lock moved — `scripts/sync-server-env.sh` for a server venv (no sentence-transformers), `uv
sync` for a full one; and moves the stamp, since there is no app to build or sign — only when the sync and the restart both worked, so a failure is retried on the next tick (a failed sync also skips the restart: new code on old dependencies is not started). It asks `/sleep/status` on the port and `CICADA_HOME` the backend unit itself names (`--port N`, `Environment=CICADA_HOME=`), so a server on another port is never restarted under a running Sleep; `CICADA_PORT`/`CICADA_HOME` in the job's environment still win. A user timer stops at logout unless
lingering is on (`sudo loginctl enable-linger <user>`, the person's step).

## Install tests in Docker (G181)

- `scripts/dev/test-install-linux.sh [ubuntu|fedora]` — the one-line Linux install (`scripts/install-server.sh`) on
  real systemd: missing prerequisite, install, loopback-only listener, CLI, token never printed, re-run no-op, update
  restarts, `--uninstall`.
- `scripts/dev/test-install-brew.sh` — the Homebrew formula on Linuxbrew: `brew style`, `brew audit --new --strict`,
  install, `brew test`, `cicada-setup`, upgrade, uninstall.

Both serve the committed HEAD from a local bare repo (commit first), never fetch Cicada from GitHub, and remove every
container and image they build. `CICADA_TEST_CACHE` (Linux) shares uv's and the model's downloads between runs.
