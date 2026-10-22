# Settings

The in-app Settings panel: General, You, Privacy, Search & memory, Sleep, Integrations, Reading, Agents, Devices & access, Skills, Engines (eleven since the Hyrum audit's B1, 2026-10-22: Memory is a group on Search & memory, From anywhere on Devices & access, Plans & keys on Engines; Advanced is gone).

## Sub-features

- `settings-general` (background service, updates, Getting started).
- `settings-you` (owner name, editors).
- `settings-memory` (Search & memory: folders, search, fade pace).
- `settings-privacy` (gates).
- `settings-agents` (the CLI link, since B11).

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

- Forbidden in a verify run: every Connect, Disconnect, Sign in, Sign out, Install, Set up, Turn on/off and Update button, and the Open Cicada at login and Restart Cicada switches, in General (background service, Open at login), Devices & access, Engines (its Plans & keys group included), Integrations and Agents (the CLI link). They reach launchd, the harness configs, the keychain, browsers, Contacts or Calendar, and an OAuth sign-in's callback defaults to `localhost:8000`, the person's own backend. Read those rows and screenshot them; never press them.
- Engines and its Plans & keys group show the plan's account as `verify@example.invalid` (`plan-claude` masks it); any other email on screen is the person's, so delete that screenshot.
