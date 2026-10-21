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

- **Folders.** Create a folder under the run with one note, run `$CV api POST /sources/folders '{"path": "<run>/fixtures/notes"}'`; the backend never reads it, so the app's reader posts the bytes once turned on. Read Settings → Integrations; `$CV app shot integrations`.
- **Read only.** For every other integration, read its row's state in the app and stop.

## Gotchas

- Forbidden in a verify run: every Connect, Disconnect, Turn on, Sign in and Sign out button here. Calendar, Contacts and Messages are the real account's whatever the home, browsers may be too, and turning one on puts the person's data into a scratch bank and raises permission prompts.
