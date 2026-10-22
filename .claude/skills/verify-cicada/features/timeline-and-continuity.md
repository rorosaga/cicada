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

- **Handshake.** Run `$CV mcp init`. The server info (`cicada-bookworm`, the version) and the instructions text.
- **Timeline.** Run `$CV mcp call cicada_timeline '{"since": "2026-01-01"}'`. Today's captures by origin, the Sleep run and agent writes, ids and counts only. A `since` older than 90 days is clamped to 90 days.
- **Continue.** Run `$CV mcp call cicada_continue '{}'`. With no captured work for this folder: `No captured session in this folder yet.`

## Gotchas

- `cicada_mark_processed` flips episodes outside Sleep; never use it in a journey that then runs Sleep.
