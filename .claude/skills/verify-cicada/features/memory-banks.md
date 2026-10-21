# Memory banks and the demo

Separate banks under one root, switched from the toolbar; a synthetic demo bank that capture never writes into.

## Sub-features

- `banks-list`, `bank-create`, `bank-switch`, `bank-rename`, `bank-delete`, `bank-export`, `demo-open` / `demo-leave`.

## How to get to it (user POV)

- The toolbar menu `Memory banks: <name>`.
- `GET/POST /banks`, `POST /banks/{name}/activate`, `POST /banks/demo`, `POST /banks/leave-demo`.
- `cicada bank list | use | create | rename | delete`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **List.** Run `$CV api GET /banks`. One bank, `default`, at the scratch root.
- **Demo guard.** Run `$CV api POST /banks/demo`, then `$CV capture --session d1 --user hi`. The capture lands in `default` (`redirectedFrom` set) or answers 409; then `$CV api POST /banks/leave-demo`.
- **App.** `vclick 'menu button Memory banks'`, `$CV app shot banks`.

## Gotchas

- `cicada bank use` acts as the person and refuses from an agent's shell; switch with the API.
- After switching, `$CV doctor` still passes only while the active bank is inside the run.
