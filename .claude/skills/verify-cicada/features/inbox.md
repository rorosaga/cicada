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
- A Sleep run left at least one question (a conversation that names a person only by a relation reliably does).

- **List.** Run `$CV api GET /inbox --save api/inbox.json`. Items with options.
- **Ask gate.** Run `$CV mcp call cicada_check_nudges '{"mode": "ask", "topic": "alpha-project"}'`. Only questions about that subject.
- **Answer.** Run `$CV api POST /inbox/<id>/resolve '{"action": "answer", "optionKey": "a"}'` (or `$CV mcp call cicada_resolve_inbox '{"id": "<id>", "option_key": "a"}'`), then `$CV bank log` for the inbox commit.
- **App.** `vclick 'button.*Description: Inbox,'`, `$CV app shot inbox`.

## Gotchas

- A two-conversation journey about a project may file no question: `Needs you · nothing right now` is the seed, not a failure. Seed a relation-only person to get one.
