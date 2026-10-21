# From anywhere: remote connector and devices

Off by default: an MCP listener on its own port for apps with no hook (claude.ai, ChatGPT) through a tunnel the person runs, with OAuth sign-in confirmed in the app; and per-device tokens for another machine that uses this one as its server.

## Sub-features

- `remote-status`, `remote-connectors` (create, rotate, revoke), `oauth-requests`, `devices` (add, list, revoke).

## How to get to it (user POV)

- Settings → From anywhere; Settings → Devices.
- `/remote/status`, `/remote/connectors`, `/remote/oauth/*`; `GET/POST/DELETE /devices`.
- `cicada device add | list | revoke`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Status.** Run `$CV api GET /remote/status`. Off.
- **Devices.** Run `$CV api GET /devices`. Empty.

## Gotchas

- Turning the listener on opens another port; do not, unless the journey is about it and the port is recorded in the run. Never expose it.
