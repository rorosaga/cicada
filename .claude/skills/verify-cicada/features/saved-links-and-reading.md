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

- **Save.** Run `$CV mcp call cicada_save_url '{"url": "https://example.com/paper", "note": "verify"}' --timeout 60`. `Saved "paper" as url media`, with its episode id; `$CV bank ls | grep '^episodes/'` shows it.
- **Queue.** Run `$CV mcp call cicada_reading_queue '{}'`. On a fresh run: `Agent reading is off`. Turn it on in the run (the setting lives in the scratch `CICADA_HOME`) with `$CV api PUT /reading/settings '{"agentEnabled": true, "acknowledge": true}'`, then ask again: `Nothing is waiting` (a public link needs no agent).
- **App.** On Home, `vh set_value --element_index <n> --value "https://example.com/reading"` on the `Search your memory` field and `vh press_key --key Return`. A new episode with `origin: saved-link`; `$CV app shot saved`.

- **Every save is read (ruling 80), and what the app says about it.** A single save lands waiting (`processed: false`) and the next `$CV sleep` reads it; a bulk (more than 10 new in one record call), an old or an already-kept save waits in the older pile (`processed_by: index`) and Sleep releases about `SAVES_PER_DAY` a night, newest first; a post with only a title and a link on a walled site is `no-words`. Turn an X list on (`$CV api PUT /reading/settings '{"savedLists": {"x": true}}'`), record rows with `cicada_record_saved_list`, then `GET /sources/channels/x/items?stream=x.bookmarks` gives each row's `depth` (`read`, `kept` = not read yet, `empty` = nothing to read yet, `asked`), `GET /sleep/queue` gives `kept` and `keptPerNight`, and the app says it: the Sleep page's "Saves not read yet" card and each source row's word. A conversation captured with the post's link in the person's turn leaves an ask for their own agent (`asked`, "waiting for your AI app"). Evidence: `~/cicada-verify-evidence/words-on-screen/`.

## Gotchas

- A save is the person's own act, so no gate stops it: the backend fetches the link once (its title and metadata, through `net_guard`, 4 s / 512 KB, no cookies). Save `https://example.com/...` links only. What Sleep would fetch on its own stays off (`CICADA_ALLOW_CONNECTOR_FETCH=off`).
- Never record a login-walled page from a verify run.
