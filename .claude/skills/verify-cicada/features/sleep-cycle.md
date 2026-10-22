# Sleep (consolidation)

Sleep reads every waiting episode in batches, extracts entities and claims with the chosen engine, promotes pages that cleared the bar, decays what went quiet, files inbox questions, and commits each step to the bank's git with machine-readable trailers.

## Sub-features

- `sleep-trigger` starts a drain over every waiting episode.
- `sleep-status` reports stage and progress while it runs.
- `sleep-commit` writes one commit per batch with `Cicada-Author`, `Cicada-Engine`, `Cicada-Session` trailers.
- `sleep-promotion` makes a page only for a thing in 2+ conversations (or the other promotion rules).
- `sleep-cancel` stops a run; `sleep-continue` resumes a paused one.
- `sleep-history` lists past reads and their run detail.

## How to get to it (user POV)

- The Sleep page (sidebar `Sleep`): its read button, its run list (Past reads).
- `POST /sleep/trigger`, `GET /sleep/status`, `POST /sleep/cancel`, `GET /sleep/history`, `GET /sleep/runs/{drain_id}`.
- `cicada sleep status | history` (and `start`/`stop`, which refuse from an agent's shell).

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- Two sessions are captured that both name `alpha-project` (see capture-conversations).

- **Run.** Trigger and wait. Run `$CV sleep`. It prints each stage, ends `idle` with `Completed — 2 episode(s) filed`, then the bank log and the entity list.
- **Commit.** Run `$CV bank log`. The newest `Sleep cycle <date>` commit has `Cicada-Author: claude-haiku-*`, `Cicada-Engine: claude-cli` and a `Cicada-Session:` line for each session.
- **Page.** Run `$CV bank cat entities/alpha-project.md`. It exists, with a summary and claims about the facts the conversations stated.
- **Processed.** Run `$CV api GET /sleep/queue`. Nothing is waiting.
- **App.** Click `Sleep` in the sidebar (`vclick 'button.*Description: Sleep,'`), then `$CV app shot sleep`. The last read shows with its pages.
- **Proof.** `evidence/sleep/status.json`, `bank-git-log.txt`, `entities.txt`.

## Gotchas

- Without `--search-model` the run ends `completed with warnings` (search by meaning not updated). Expected.
- One conversation is not enough for a page: a single mention stays in the index. A journey that wants a page needs two sessions.
- Model output varies run to run. Assert on page ids and trailers, not prose.
- `cicada sleep start` refuses from an agent's shell (ruling 21a); use `$CV sleep`.
