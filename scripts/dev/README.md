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

Once per Mac, make a self-signed code-signing certificate:

1. Keychain Access → Keychain Access menu → Certificate Assistant → Create a Certificate…
2. Name **Cicada Local** (exactly), Identity Type **Self-Signed Root**, Certificate Type **Code Signing**. Create.
3. Run `make install-app` by hand once. macOS asks whether codesign may use the new key: **Always Allow**. An
   unattended auto-update would otherwise wait on that dialog.

The install then says `Signed and verified with "Cicada Local" (<hash>)`. It finds the certificate in
`security find-identity -p codesigning`, where an untrusted self-signed one is listed only without `-v`, and signs by
its hash. `CICADA_SIGN_IDENTITY` overrides the choice (`-` forces ad hoc). The chooser is
`app/CicadaApp/sign_identity.sh`.

Grants given to the last ad-hoc build do not carry over: macOS asks once more after the first build signed with
Cicada Local, and from then on a rebuild keeps them. This is a local signature, not a Gatekeeper-trusted one.

## The auto-updater waits out Sleep

`auto-update.sh` asks the backend (`GET /sleep/status`, 10 s, the bearer token from `$CICADA_HOME/api_token`, port
`$CICADA_PORT` or 8000) before it fetches. A running cycle, an open write window or an unfinished drain (paused
included) logs `deferred: Sleep is running` and changes nothing — no fast-forward, restart, app build or stamp move; the
next tick retries. Only a refused connection (nothing listening) or a missing token proceeds: a timeout, any other failure, an HTTP
error or an unreadable answer means a busy backend, so it defers too.
`CICADA_AUTOUPDATE_FORCE=1` skips the check. The backend restarts only when runtime code moved (`api` outside
`api/tests`, `mcp`, the dependency files); a test-only or benchmark-only merge never restarts it.
