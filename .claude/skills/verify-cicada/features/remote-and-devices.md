# From anywhere: remote connector and devices

Off by default: an MCP listener on its own port for apps with no hook (claude.ai, ChatGPT) through a tunnel the person runs, with OAuth sign-in confirmed in the app; and per-device tokens for another machine that uses this one as its server.

## Sub-features

- `remote-status`, `remote-connectors` (create, rotate, revoke), `oauth-requests`, `devices` (add, list, revoke).

## How to get to it (user POV)

- Settings → From anywhere; Settings → Devices.
- `GET /remote/status`, `/remote/connectors`, `/remote/oauth/*`; `GET /devices`, `POST /devices`, `DELETE /devices/{device_id}`.
- `cicada device add | list | revoke`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Status.** Run `$CV api GET /remote/status`. `enabled: false`, `listenerUp: false`, on the run's `remote_port`.
- **Device token.** `$CV api POST /devices '{"name": "verify-laptop"}'` (201) issues a token shown once: mask it in every transcript. A `/capture/turn` with that token as the bearer lands an episode with `device: <id>`; `$CV api DELETE /devices/<id>` revokes it, and the same token then gets 401. Settings → Devices lists it as revoked.
- **App.** Settings → `vclick 'button From anywhere$'` (the switch, off) and `vclick 'button Devices$'`; read and stop.

**Not driven in a verify run: the remote listener and an app's OAuth sign-in.** Both need a tunnel the person runs and a
public URL, and the sign-in's callback defaults to `localhost:8000`, the person's own backend. The nearest checks are the
device-token steps above and the remote tests (`api/tests/test_remote*.py`).

## Gotchas

- Turning the listener on opens `CICADA_REMOTE_PORT`. Do not, unless the journey is about it. Never expose it or start a tunnel.
