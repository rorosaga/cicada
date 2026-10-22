# Imports and intake

A dropped or imported file (a chat export, a platform's saved list, a folder) is sniffed, queued and turned into episodes for Sleep.

## Sub-features

- `intake-sniff`, `intake-import`, `intake-jobs`, `conversation-upload`, `cli-import`.

## How to get to it (user POV)

- Drop onto the window or the Dock icon; File → Import…; Home's field.
- `POST /intake/sniff`, `/intake/import`, `GET /intake/jobs/{id}`, `POST /conversations/upload`.
- `cicada import <path>`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- A synthetic export under the run dir, never a real one: `api/tests/_intake_fixtures.py`'s `claude_conversations()` written as `<run>/fixtures/conversations.json` (two `alpha-project` check-ins).

- **Preview (CLI).** Run `$CV cli -- import --preview <run>/fixtures/conversations.json`. `claude: 2 new, 0 grown, 0 already here`.
- **Import (CLI).** `$CV cli -- import <file>` answers that importing acts as the person and changes nothing (exit 1). That is the rail.
- **Sniff and import (the app's drop route).** `curl -F file=@<file> -H "Authorization: Bearer $(cat <run>/cicada-home/api_token)" http://127.0.0.1:<port>/intake/sniff` names `vendor: claude` with the counts and titles; the same against `/intake/import` stages them (`episodesStaged: 2`). `cv api` sends JSON only, so these multipart routes go through curl with the run's token and port (`run.json`).
- **Stored.** `$CV bank ls | grep '^episodes/'`. Two episodes dated by the conversations' own days.

## Gotchas

- Never import the person's real exports into a verify run.
- `$CV bank ls | grep episodes/` also lists the demo bank's episodes once the demo has been opened; anchor the pattern.
