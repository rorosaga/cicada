# Usage, prices and contributors

What each Sleep read cost and used (only on the Sleep page's run detail and engine menu), and who wrote what in the bank.

## Sub-features

- `run-detail`, `consumption`, `contributors`, `origins`.

## How to get to it (user POV)

- Sleep page → Past reads → a run.
- `GET /sleep/runs/{drain_id}`, `/consumption/summary`, `/contributors`, `/contributors/commits`, `/origins`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- One Sleep run has finished.

- **Run detail.** Run `$CV api GET /sleep/history`, take the `drainId` of the newest row with `kind: sleep` (inbox rows carry none), then `$CV api GET /sleep/runs/<drain_id>`. Batches with their commit, calls, plan windows before and after, and per model the tokens with `basis` and `equivCostUsd`.
- **Contributors.** Run `$CV api GET /contributors`. One row per `Cicada-Author` (`claude-haiku-*`, `cicada`, `user`, `verify`), each with commits and files; git's author field (`Verify Run`) is never what it shows.
- **App.** `vclick 'button.*Description: Sleep,'`, `vclick 'button Past reads$'`. `Last cycle … What it cost, Claude plan · under 1% of your weekly limit`.

## Gotchas

- A price shows only with its basis; plan runs show plan usage, never dollars.
