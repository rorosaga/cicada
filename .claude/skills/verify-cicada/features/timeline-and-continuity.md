# Timeline, handshake and continuity

An agent arriving cold gets the contract and current state in the MCP handshake, sees what changed day by day, and picks up where work in this folder stopped.

## Sub-features

- `handshake` (rides `initialize`, ≤ 1,800 tokens).
- `timeline` (`cicada_timeline`).
- `continue` (`cicada_continue`).
- `pending` / `mark-processed` for an agent consolidating by hand.

## How to get to it (user POV)

- MCP `initialize` instructions, `cicada_handshake`, `cicada_timeline`, `cicada_continue`, `cicada_pending`, `cicada_mark_processed`.
- `GET /handshake`, `GET /state`.
- `cicada handshake`, `cicada timeline`, `cicada continue`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Handshake.** Run `$CV mcp init`. The server info and the instructions text naming the scratch bank.
- **Timeline.** Run `$CV mcp call cicada_timeline '{"since": "2026-01-01"}'`. Today's pages.
- **Continue.** Run `$CV mcp call cicada_continue '{}'`. With no captured work for this folder it says so.

## Gotchas

- `cicada_mark_processed` flips episodes outside Sleep; never use it in a journey that then runs Sleep.
