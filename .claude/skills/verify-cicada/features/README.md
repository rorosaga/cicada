# Cicada verification map

This directory is the maintained source for verifying Cicada's user-facing behavior. Read the index, then use the
matching feature file as the recipe. `$CV` is the absolute path
`"$(git rev-parse --show-toplevel)/.claude/skills/verify-cicada/bin/cv"`, set at the start of every Bash call together
with `export CICADA_VERIFY_RUN=<run dir>`; `vh`, `vidx` and `vclick` come from sourcing `bin/harness.sh` in that same
call (see `../SKILL.md`).

## Baseline preconditions

- A run started with `$CV launch` (add `--search-model` when a journey needs search by meaning; `--checkout <path>`
  to verify another worktree), and its run dir passed on every call.
- `$CV doctor` is all `ok`: our pids, our port, the scratch root and bank, this worktree's version, the plan reachable.
- For app journeys, `$CV app build && $CV app launch`, and `$CV doctor` again (it adds the app checks).
- The seed is what the journey captures. A fresh bank holds only the owner page (`Verify Person`). The standard
  seed is three turns in two sessions about `alpha-project`, then `$CV sleep`:

  ```sh
  $CV capture --session verify-s1 --turn t1 --user "I am starting alpha-project, a birdsong classifier in Rust." --assistant "Noted."
  $CV capture --session verify-s1 --turn t2 --user "alpha-project will use rustfft."
  $CV capture --session verify-s2 --turn t1 --user "Back on alpha-project: it turns birdsong recordings into spectrograms before classifying them." --assistant "Got it."
  $CV sleep
  ```
- Never drive an instance this run did not start, and never the person's own app, backend or bank.

## Driving conventions

- Start every recipe from the baseline unless its preconditions say otherwise.
- In the app, match elements by their accessibility text (`Description: Projects,`, `heading alpha-project`), never by
  a remembered number: numbers change with every page. `vclick '<regex>'` reads fresh each time.
- Treat commands as literal; keep quoted JSON exactly. Before calling an MCP tool for the first time, read
  `$CV mcp schema <tool>`.
- Use `$CV api` for routes, `$CV mcp` for tools, `$CV cli -- ...` for the `cicada` command.
- A mutation is followed by a read-only second view: `$CV bank log`, `$CV bank cat`, a GET, or the app's screen.

## Proof and skip reporting

- Capture the action and the resulting state, not only the final screen. Every `cv` verb writes its request and
  answer under the run's evidence dir; app proof is `$CV app shot <name>` plus the `vh get_app_state` lines quoted.
- Mutation proof includes the bank's git commit and its trailers.
- Record the feature file and entry point used with every artifact.
- Report an unreachable path with the command tried and the unmet precondition. Do not report a skipped entry point
  as verified through a different one.
- Model output differs between runs (the plan runs for real at haiku). Assert on ids, trailers and named facts.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible behavior, then exactly four
H2 sections in this order: `Sub-features`, `How to get to it (user POV)`, `Driving it with verify-cicada` (starting
with `Preconditions:`, then labelled steps pairing an action, an exact command and the observable result), and
`Gotchas`. Keep implementation detail out; name only user paths, stable handles, required state, commands and proof.

## Features

"Driven" is the last date a recipe was run end to end through `cv` and what it covered. Blank means written from the
code and docs but not yet driven: drive it before trusting it, and fix the file when it is wrong.

| Feature | Covers | Driven |
|---|---|---|
| [Capture conversations](./capture-conversations.md) | `/capture/turn`, one episode per session, agent saves, the demo guard | 2026-10-22: `/capture/turn`, `verify-s1` (two turns) and `verify-s2`, the episode files |
| [Sleep](./sleep-cycle.md) | trigger, status, commits and trailers, promotion, history | 2026-10-22: `cv sleep` on the plan at haiku (2 processed, 0 requeued, 0 left), commit trailers, page made |
| [Sleep engine and schedule](./sleep-engine-and-schedule.md) | engine readiness and choice, schedule, run options | 2026-10-22: `GET /sleep/engine`; Plans & keys read in the app, email masked |
| [Recall and search](./recall-and-search.md) | `cicada_recall`, detail, `cicada recall/get/find`, the app's find | 2026-10-22: MCP recall (meaning query), CLI recall, Home find in the app |
| [Ask](./ask.md) | `POST /ask`, `cicada_ask`, Home's Ask | 2026-10-22: `POST /ask`, `cicada_ask`, Home's Ask; fixed (needs `--search-model`) |
| [Home](./home.md) | the field, needs-you, today, last read | 2026-10-22: app, read and screenshot |
| [Graph explorer](./graph-explorer.md) | `/graph`, `cicada graph`, the Graph page, focus a node | 2026-10-22: `GET /graph`, Graph page by pixel click |
| [Entity pages and the Reader](./entity-pages.md) | read, history, blame, edit, picture, decay, evidence span | 2026-10-22: read, history, propose, apply, blame, the page from Clusters; fixed |
| [Claims and provenance](./claims-and-provenance.md) | write, retract, claims and spans | 2026-10-22: write, stored span, trailers, retract; fixed (a restated Sleep fact, G204) |
| [Clusters](./clusters.md) | the Clusters grid | 2026-10-22: the grid and a tile's page; fixed (tile selector) |
| [Projects](./projects.md) | list, detail, progress, milestones, `cicada_project` | 2026-10-22: app list and detail, `cicada_project` |
| [Project backlog](./backlog.md) | add, note, list | 2026-10-22: add, note, list, the app's Backlog; fixed (note step) |
| [Inbox](./inbox.md) | list, ask gate, answer, undo a settle | 2026-10-22: list, ask gate, answer, settled; fixed (gate and answer shapes) |
| [Sources](./sources.md) | overview, channels, a page's sources | 2026-10-22: overview, add a source, Sources page; as written |
| [Saved links and reading](./saved-links-and-reading.md) | save a link, the reading queue, reads by the person's agent | 2026-10-22: save (MCP and Home), queue on and off; fixed |
| [Video queue and watching](./video.md) | queue, claim, record a watch | 2026-10-22: empty queue and claim, a watch on a saved link; the lease lifecycle cannot be driven |
| [Exploring saved sites](./site-exploration.md) | explore state and queue (read only in a verify run) | 2026-10-22: state, candidates, queue; a run cannot be driven |
| [Design looks](./design-looks.md) | save and search a look | 2026-10-22: save onto a page, search by words; fixed (exact call) |
| [Skills](./skills.md) | Installed, Discover, Drafts, propose and create | 2026-10-22: list, a held draft, Skills page; fixed |
| [Timeline, handshake and continuity](./timeline-and-continuity.md) | `initialize` handshake, timeline, continue | 2026-10-22: handshake, timeline, continue |
| [Memory banks and the demo](./memory-banks.md) | list, create, switch, the demo bank's capture guard | 2026-10-22: list, demo guard, leave; the bank menu not driven (needs focus) |
| [Imports and intake](./imports-and-intake.md) | drop, File → Import, `cicada import` | 2026-10-22: preview, sniff and import over the app's route; fixed (CLI import is person-only) |
| [Settings](./settings.md) | the Settings panel's sections (read only where they write the real home) | 2026-10-22: `cicada settings owner`; Plans & keys opened, read only |
| [Local integrations](./integrations.md) | browsers, Calendar, Contacts, Messages, folders (read only) | 2026-10-22: a watched folder, Integrations and Search & files read; fixed |
| [Connect agents](./agents-connect.md) | Settings → Agents (read only) | 2026-10-22: `/agents/wiring`, Settings → Agents read; as written |
| [From anywhere: remote connector and devices](./remote-and-devices.md) | the remote listener, OAuth, device tokens | 2026-10-22: status, a device token issued, used and revoked; the listener and OAuth cannot be driven |
| [The `cicada` command](./cli-status.md) | status, commands, JSON envelope | 2026-10-22: `cicada status`, `cicada recall`, `sleep start` refused `person_only` |
| [Usage, prices and contributors](./usage-and-contributors.md) | run detail, consumption, contributors | 2026-10-22: run detail, contributors, Past reads; as written |
