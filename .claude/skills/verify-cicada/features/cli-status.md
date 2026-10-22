# The `cicada` command

A second door onto the same memory as the MCP tools, from a shell, with one JSON envelope.

## Sub-features

- `status`, `commands` (the CLI to MCP table), `--json`, `--bank` (asserts, never selects).

## How to get to it (user POV)

- `cicada <command>` from a checkout (`scripts/cicada`) or a release launcher.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Status.** Run `$CV cli -- status`. `Memory: <scratch root> (bank 'default')`, `root from env; matches the app's backend`, `Backend: running`.
- **Table.** Run `$CV cli -- commands`. Each command and its MCP tool.
- **JSON.** Run `$CV cli -- --json recall alpha-project`. One envelope.

## Gotchas

- The CLI reads no `.env`; `cv cli` gives it the run's env. A bare `cicada` in your shell talks to the person's install. Do not.
