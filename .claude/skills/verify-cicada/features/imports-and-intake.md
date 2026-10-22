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
- A synthetic export file under the run dir (never a real export).

- **CLI.** Run `$CV cli -- import <run>/fixtures/export.json`. A job id, then episodes in `$CV bank ls`.
- **Sniff.** `POST /intake/sniff` with the file's bytes, through the app's drop, names the vendor.

## Gotchas

- Never import the person's real exports into a verify run; build a small synthetic one.
