# From anywhere: remote connector and devices

Off by default: an MCP listener on its own port for apps with no hook (claude.ai, ChatGPT) through a tunnel the person runs, with OAuth sign-in confirmed in the app; and per-device tokens for another machine that uses this one as its server.

## Sub-features

- `remote-status`, `remote-connectors` (create, rotate, revoke), `oauth-requests`, `devices` (add, list, revoke).

## How to get to it (user POV)

- Settings → Devices (its From anywhere group, and the devices list).
- `GET /remote/status`, `/remote/connectors`, `/remote/oauth/*`; `GET /devices`, `POST /devices`, `DELETE /devices/{device_id}`.
- `cicada device add | list | revoke`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Status.** Run `$CV api GET /remote/status`. `enabled: false`, `listenerUp: false`, on the run's `remote_port`.
- **Device token.** The token is shown once. Keep it in a 0600 header file and print the answer with it masked, so it
  is in no argv and no transcript:

  ```sh
  RUN=$CICADA_VERIFY_RUN; PORT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['port'])" "$RUN/run.json")
  $CV api POST /devices '{"name": "verify-laptop"}' | (umask 077; python3 -c "
  import json, sys
  out = json.load(sys.stdin); tok = out['body']['token']
  open(sys.argv[1], 'w').write('Authorization: Bearer ' + tok + '\\n')
  print(json.dumps(out, indent=2).replace(tok, '<masked device token>'))" "$RUN/device.header")
  curl -s -H @"$RUN/device.header" -H 'Content-Type: application/json' "http://127.0.0.1:$PORT/capture/turn" \
    -d '{"harness": "cursor", "session_id": "verify-dev1", "turn_id": "t1", "messages": [{"speaker": "user", "text": "alpha-project from the laptop"}]}'
  ```

  `cv api POST /devices` answers 201 (`cv` saves no file without `--save`); the capture lands an episode whose
  frontmatter says `device: <id>`. `$CV api DELETE /devices/<id>` revokes it, and
  `curl -s -o /dev/null -w '%{http_code}' -H @"$RUN/device.header" "http://127.0.0.1:$PORT/status"` then prints 401.
  Settings → Devices lists it as revoked.
- **App.** Settings → `vclick 'button Devices & access$'`: the From anywhere group (its switch, off) and Your devices; read and stop.

**Not driven in a verify run: the remote listener and an app's OAuth sign-in.** Both need a tunnel the person runs and a
public URL, and the sign-in's callback defaults to `localhost:8000`, the person's own backend. The nearest checks are the
device-token steps above and the remote tests (`api/tests/test_remote*.py`).

## Gotchas

- Turning the listener on opens `CICADA_REMOTE_PORT`. Do not, unless the journey is about it. Never expose it or start a tunnel.
