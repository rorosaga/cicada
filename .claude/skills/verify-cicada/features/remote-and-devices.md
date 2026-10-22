# From anywhere: remote connector and devices

Off by default: an MCP listener on its own port for apps with no hook (claude.ai, ChatGPT) through a tunnel the person runs, with OAuth sign-in confirmed in the app; and per-device tokens for another machine that uses this one as its server.

## Sub-features

- `remote-status`, `remote-connectors` (create, rotate, revoke), `oauth-requests`, `devices` (add, list, revoke).

## How to get to it (user POV)

- Settings → Devices & access (its From anywhere group, and the devices list).
- `GET /remote/status`, `/remote/connectors`, `/remote/oauth/*`; `GET /devices`, `POST /devices`, `DELETE /devices/{device_id}`.
- `cicada device add | list | revoke`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Status.** Run `$CV api GET /remote/status`. Off.
- **Devices.** Run `$CV api GET /devices`. Empty.

## Gotchas

- Turning the listener on opens `CICADA_REMOTE_PORT`, a free port `launch` recorded as `remote_port` in run.json. Do not, unless the journey is about it. Never expose it or start a tunnel.
- Forbidden in a verify run: the app's Sign in and Connect buttons for an app's OAuth sign-in. Its callback defaults to `localhost:8000`, the person's own backend.
