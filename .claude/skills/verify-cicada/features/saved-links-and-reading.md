# Saved links and reading

A link the person saves is queued, read within the ToS rail, and becomes part of memory; walled pages are read only by the person's own agent.

## Sub-features

- `save-url`, `reading-queue`, `record-read`, `record-profile`, `record-check`, `reading-sites`.

## How to get to it (user POV)

- Home's field (paste a link); the menu-bar quick save.
- MCP `cicada_save_url`, `cicada_reading_queue`, `cicada_record_read`, `cicada_record_profile`, `cicada_record_check`.
- `POST /sources/save`, `GET /reading/asks`, `GET /reading/sites`; Settings → Reading.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Save.** Run `$CV mcp call cicada_save_url '{"url": "https://example.com/paper", "note": "verify"}'`. An episode is staged (`$CV bank ls`).
- **Queue.** Run `$CV mcp call cicada_reading_queue '{}'`. What is waiting for the person's agent.
- **App.** Paste a link into Home's field with `vh set_value` and press `Return`; `$CV app shot saved`.

## Gotchas

- A save is the person's own act, so no gate stops it: the backend fetches the link once (its title and metadata, through `net_guard`, 4 s / 512 KB, no cookies). Save `https://example.com/...` links only. What Sleep would fetch on its own stays off (`CICADA_ALLOW_CONNECTOR_FETCH=off`).
- Never record a login-walled page from a verify run.
