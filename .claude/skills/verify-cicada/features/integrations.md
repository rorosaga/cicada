# Local integrations

Readers the app runs on this Mac after the person turns each on: browsers' bookmarks and history, Calendar, Contacts, Messages (ticked chats), Chrome tab groups, YouTube watch history, watched folders, Wispr Flow, and the bookmark prompt.

## Sub-features

- `browsers`, `calendar`, `contacts`, `messages`, `tab-groups`, `watch-history`, `folders`, `wispr-flow`, `save-why` (the bookmark prompt from the notch).

## How to get to it (user POV)

- Settings → Integrations; Sources.
- `POST /sources/calendar-local/sync`, `/sources/contacts-local/sync`, `/sources/messages/*`, `/sources/folders`, `/sources/tab-groups/sync`, `/sources/watch-history/sync`, `/sources/sync-bookmarks`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Folders.** Create `<run>/fixtures/notes/note.md`, then `$CV api POST /sources/folders '{"label": "verify notes", "path": "<run>/fixtures/notes"}'` (`label` is required). `GET /sources/folders` lists it. The backend never reads it: the app's reader posts the bytes.
- **App.** Settings → `vclick 'button Integrations$'`: chat exports, browsers, Calendar and the rest, each with its state. Folders live in Settings → Search & memory (`vclick 'button Search & memory ›'`, the pointer under Integrations); `$CV app shot settings-integrations`.
- **Read only.** For every other integration, read its row's state in the app and stop.

## Gotchas

- Forbidden in a verify run: every Connect, Disconnect, Turn on, Sign in and Sign out button here. Calendar, Contacts and Messages are the real account's whatever the home, browsers may be too, and turning one on puts the person's data into a scratch bank and raises permission prompts.
- Observed 2026-10-22: the verify copy said a folder under the run's `/private/var/...` dir `isn't on this Mac`, though it exists. Not chased; a real folder on a real home is the person's path.
