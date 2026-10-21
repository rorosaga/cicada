# Settings

The in-app Settings panel: General, You, Privacy, Search & files, Memory, Sleep, Integrations, Reading, Agents, From anywhere, Devices, Skills, Engines, Plans & keys, Advanced.

## Sub-features

- `settings-general` (background service, updates, CLI link).
- `settings-you` (owner name, editors).
- `settings-memory` (search model, fade pace).
- `settings-privacy` (gates).
- `settings-advanced`.

## How to get to it (user POV)

- Sidebar `Settings` (gear), or ⌘,.
- `GET/PUT /owner`, `/editors`; `GET /embeddings`; `cicada settings owner`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- The app is launched.

- **Open.** `vclick 'Description: Settings,'`, then `vh get_app_state` and click a section row by its label; `$CV app shot settings-<section>`.
- **Owner.** Run `$CV api GET /owner` and `$CV cli -- settings owner`.

## Gotchas

- General's background service and Open at login, Agents' Connect buttons, the CLI link and Integrations write to the real home (LaunchAgents, `~/.claude`, `~/.cursor`, `~/.local/bin`, browser data). Read those rows; never toggle them in a verify run.
