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

- **List.** Run `$CV api GET /banks`. One bank, `default`, active.
- **Demo guard.** Run `$CV api POST /banks/demo` (`active: demo`), then `$CV capture --session verify-demo1 --user hi`. The capture lands in `default` with `redirectedFrom: demo`; then `$CV api POST /banks/leave-demo` and `$CV doctor` (`active bank is inside the run`).
- **App.** The bank menu is `menu button default … Switch memory bank` in the toolbar. Its AX press does not open it (2026-10-22); click its pixels with `$CV app click`, which needs our window frontmost and refuses (`did not become frontmost`) while the person works in another app. When it refuses, report the menu as not driven.

## Gotchas

- `cicada bank use` acts as the person and refuses from an agent's shell; switch with the API.
- After switching, `$CV doctor` still passes only while the active bank is inside the run.
