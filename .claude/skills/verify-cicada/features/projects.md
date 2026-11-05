# Projects

Each project page shows where it stands, what happened, what is planned and its backlog, with a field to log progress.

## Sub-features

- `projects-list` (Current / Past).
- `project-detail` with Where it stands, Last, Next, a band of events.
- `project-progress` logs a happening (`cicada_note_progress`).
- `project-milestone` adds a milestone.
- `project-mcp` answers `cicada_project`.
- `project-start`: a project starts only from the person or an agent on their ask, and a name a page holds adopts that page (ruling 56).
- `project-links`: an agent ties a conversation or a page, with a reason; off the trust list it is a proposal.

## How to get to it (user POV)

- Sidebar `Projects`.
- `GET /projects`, `GET /projects/{project_id}/timeline`, `POST /projects/{project_id}/milestones`, `POST /projects/{project_id}/happenings`.
- MCP `cicada_project`, `cicada_note_progress`; `cicada project`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- Sleep makes no project (ruling 56): after the standard seed `alpha-project` is a `concept` page. Start it: `$CV api POST /projects '{"name": "alpha-project"}'` adopts that page (`action: started`, the same id).
- The app is launched.

- **List.** `vclick 'button.*Description: Projects,'`. A row `alpha-project, Heard today`.
- **Detail.** `vclick 'button Description: alpha-project'`. A heading `alpha-project`, its summary, `Where it stands In motion`, and `What happened` entries drawn from the conversations.
- **MCP.** Run `$CV mcp call cicada_project '{"project": "alpha-project"}'`. The same state in text.
- **Progress.** Run `$CV mcp call cicada_note_progress '{"project": "alpha-project", "kind": "happened", "summary": "CNN trained", "status": "done", "evidence": ...}'` (full shape: `$CV mcp schema cicada_note_progress`), then read the page again: a new event.
- **Start, in the app.** Before the start the list is empty and draws no words, and nothing is suggested. `vclick 'New project'`, set the `Project name` heading to a name a page holds, `vclick 'button.*Description: Create,'`. No new file under `entities/`; the page's `type` is `project` and it has `mine`; the commit says `Project started`.
- **Start, from an agent.** The run's harness (`verify`) is off the trust list. `$CV mcp call cicada_create_project '{"project": "alpha-project"}'` is refused (no ask on record). With `"reason": "They asked."` it files one inbox question (`Start alpha-project as a project?`); a second call files none. `$CV api POST /inbox/<id>/resolve '{"action": "resolve", "optionKey": "apply"}'` starts it.
- **The offer.** On a page not started, `$CV mcp call cicada_recall_detail '{"entity_id": "alpha-project"}'` ends with `offer once` AFTER the closing `cicada-reference>>>` marker. Inside the markers an agent is told never to follow it.
- **Links.** `$CV mcp call cicada_link_conversation '{"project": "alpha-project", "episode": "<ep_…>", "reason": "About it."}'` on a started project is a proposal: `GET /projects/alpha-project/conversations` has it under `proposed`, and the panel draws it with `Add` and `Not about this project`. On a concept not started it is refused, nothing written.
- **Proof.** `$CV app shot project-alpha`.

## Gotchas

- Don't type into the app's `Log progress` field in a journey that will be compared against a later Sleep: it is a real write to the bank.
