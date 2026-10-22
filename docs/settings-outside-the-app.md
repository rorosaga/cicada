# Settings that live outside the app

Cicada's Settings shows good defaults and the choices that matter, in words. A few values can also be fixed by how
Cicada was set up on a machine — an environment variable the backend starts with, or a developer checkout's
`api/.env`. When one is set, the app honours it, says so in words, and links here. This page says how to change each.

Every variable below is read when the backend starts. After you change one, restart Cicada (quit and open the app; on
a server, restart its service) for it to take effect.

Where a value can be set:

- **The Mac app from a release:** the backend inherits the environment `launchd` gives it. Nothing here is set by the
  installer.
- **A developer checkout:** `api/.env` in the checkout, or the shell that starts the backend. The environment wins over
  the file.
- **A server without the app:** the systemd unit's environment, or the shell that starts it
  ([headless.md](architecture/headless.md)).

## The engine is fixed

Settings → Engines says *"Cicada's setup on this Mac fixes the engine, so a choice here won't take effect."* when
`CICADA_LLM_MODE` is set (one of `auto`, `agent`, `codex`, `local`, `byok`). It outranks the choice made in the app and
in `cicada sleep engine`, which answer that the engine is fixed rather than change nothing silently.

To choose in the app again, remove `CICADA_LLM_MODE` from wherever it is set and restart Cicada. Cicada then uses
**Auto** unless you chose another engine: your Claude plan if you're signed in, else your ChatGPT plan, else a model
running on this Mac — never an API key you didn't choose (ruling 31 in [TODO.md](goals/TODO.md)).

## Where your memory lives is fixed

Settings → Devices & access says *"Cicada's setup on this Mac fixes the server, so it can't be changed here."* when
`CICADA_API_BASE` is in the app's environment. It points this Mac at a Cicada server elsewhere and wins over the choice
in Settings → Devices & access.

To choose in the app again (*This Mac* or *A server*), remove `CICADA_API_BASE` from the environment the app starts
with and open Cicada again. The address and device token the app saved itself are kept in `$CICADA_HOME/api_base` and
`$CICADA_HOME/device_token`; see "The Mac app as a client" in [headless.md](architecture/headless.md).

## The usage ledger

Settings → Privacy & data shows whether the usage ledger is on. The ledger records ids, counts and durations of what
Cicada did — never your words, never in a memory bank or git ([storage.md](architecture/storage.md), "Telemetry
ledger"). It is on by default and stays on this machine.

To turn it off, set `CICADA_TELEMETRY=off` in the environment the backend starts with and restart Cicada. To turn it
on again, remove the variable (or set it to `on`). The app shows the new state after the restart.
