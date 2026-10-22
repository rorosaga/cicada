# Inbox

Questions Sleep could not settle on its own wait here, one card each with Sleep's recommendation; the person answers in one tap, and Sleep's own settles can be undone.

## Sub-features

- `inbox-list`, `inbox-resolve`, `inbox-settled-undo`, `inbox-tidy`, `inbox-ask-gate` (questions surface in a conversation only on their subject).

## How to get to it (user POV)

- Sidebar `Inbox`; Home's `Open Inbox`.
- `GET /inbox`, `POST /inbox/{id}/resolve`, `GET /inbox/settled`, `POST /inbox/settled/{id}/undo`.
- MCP `cicada_check_nudges`, `cicada_resolve_inbox`; `cicada inbox all | answer`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- A Sleep run left at least one question. A conversation that names a person only by a relation does: the standard
  seed with `My sister is helping me label the recordings for alpha-project.` in `verify-s2` filed `What's the name of your sister?` (2026-10-22).

- **List.** Run `$CV api GET /inbox --save api/inbox.json`. Items with `kind`, `entityId` and option keys.
- **Ask gate.** Run `$CV mcp call cicada_check_nudges '{"mode": "ask", "topic": "my sister labelling clips", "entity_ids": ["sister"]}'`. Only that question, with its id and option keys. `{"mode": "ask", "topic": "alpha-project"}` answers `ask nothing`: the gate matches the question's own subject.
- **Answer.** A name question takes words: `$CV api POST /inbox/<id>/resolve '{"action": "answer", "answer": "Carol Example"}'`; a question with options takes `"optionKey": "<key>"` from the list. `$CV bank log` shows `Inbox resolution (clarification)` under `Cicada-Author: user`.
- **Settled.** Run `$CV api GET /inbox/settled`. What Sleep or a check settled, each undoable with `POST /inbox/settled/<id>/undo` (empty after one small Sleep).
- **App.** `vclick 'button.*Description: Inbox,'`, `$CV app shot inbox`. `Nothing pending` once answered.

## Gotchas

- A two-conversation journey about a project may file no question: `Needs you · nothing right now` is the seed, not a failure.
- Option keys are words (`rather_not_say`, `apply`, `dismiss`), not letters.
