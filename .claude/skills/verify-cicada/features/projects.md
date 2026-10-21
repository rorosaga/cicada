# Projects

Each project page shows where it stands, what happened, what is planned and its backlog, with a field to log progress.

## Sub-features

- `projects-list` (Current / Past).
- `project-detail` with Where it stands, Last, Next, a band of events.
- `project-progress` logs a happening (`cicada_note_progress`).
- `project-milestone` adds a milestone.
- `project-mcp` answers `cicada_project`.

## How to get to it (user POV)

- Sidebar `Projects`.
- `GET /projects`, `/projects/{id}/timeline`, `POST /projects/{id}/milestones`, `/happenings`.
- MCP `cicada_project`, `cicada_note_progress`; `cicada project`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- Sleep has made project `alpha-project`.
- The app is launched.

- **List.** `vclick 'button.*Description: Projects,'`. A row `alpha-project, Heard today`.
- **Detail.** `vclick 'button Description: alpha-project'`. A heading `alpha-project`, its summary, `Where it stands In motion`, and `What happened` entries drawn from the conversations.
- **MCP.** Run `$CV mcp call cicada_project '{"project": "alpha-project"}'`. The same state in text.
- **Progress.** Run `$CV mcp call cicada_note_progress '{"project": "alpha-project", "kind": "happened", "summary": "CNN trained", "status": "done", "evidence": ...}'` (full shape: `$CV mcp schema cicada_note_progress`), then read the page again: a new event.
- **Proof.** `$CV app shot project-alpha`.

## Gotchas

- Don't type into the app's `Log progress` field in a journey that will be compared against a later Sleep: it is a real write to the bank.
