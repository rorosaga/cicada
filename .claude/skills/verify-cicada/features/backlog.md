# Project backlog

Items the person asked to keep for later, one markdown file per item, listed under the project with notes added over time.

## Sub-features

- `backlog-add`, `backlog-note`, `backlog-list`, `backlog-import`.

## How to get to it (user POV)

- Projects → a project → `Backlog`.
- MCP `cicada_add_backlog_item`, `cicada_add_backlog_note`, `cicada_backlog`.
- `GET/POST /projects/{id}/backlog`, `POST /backlog/{project}/{item}/notes`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- Project `alpha-project` exists.

- **Add.** Run `$CV mcp call cicada_add_backlog_item '{"project": "alpha-project", "title": "Try a mel filterbank", "description": "verify"}'`. The reply names the item.
- **Stored.** Run `$CV bank ls | grep backlog/`. One file for the item.
- **List.** Run `$CV mcp call cicada_backlog '{"project": "alpha-project"}'` and open Backlog in the app.

## Gotchas

- A backlog item is never an entity page; do not look for it under `entities/`.
