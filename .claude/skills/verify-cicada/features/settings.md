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
- `GET /settings/owner`, `PUT /settings/owner`, `GET /settings/editors`, `PUT /settings/editors`; `GET /embeddings`; `cicada settings owner`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- The app is launched.

- **Open.** `vclick 'Description: Settings,'`, then `vh get_app_state` and click a section row by its label; `$CV app shot settings-<section>`.
- **Owner.** Run `$CV api GET /settings/owner` and `$CV cli -- settings owner`. The name is `Verify Person` unless the run was launched with `--no-owner`.

## Gotchas

- Forbidden in a verify run: every Connect, Sign in, Install, Set up and Turn on button in General (background service, Open at login, the CLI link), Engines, Plans & keys, Integrations and Agents. They reach launchd, the harness configs, the keychain, browsers, Contacts or Calendar, and an OAuth sign-in's callback defaults to `localhost:8000`, the person's own backend. Read those rows and screenshot them; never press them.
- Plans & keys and Engines show the plan's account as `verify@example.invalid` (`plan-claude` masks it); any other email on screen is the person's, so delete that screenshot.
