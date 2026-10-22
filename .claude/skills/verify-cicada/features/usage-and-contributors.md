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

- **Run detail.** Run `$CV api GET /sleep/history`, take the newest run's drain id, then `$CV api GET /sleep/runs/<drain_id>`.
- **Contributors.** Run `$CV api GET /contributors`. Cicada and the haiku author from the Sleep commit.

## Gotchas

- A price shows only with its basis; plan runs show plan usage, never dollars.
