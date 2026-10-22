# Ask

A direct question gets an answer written from memory with its citations, on the chosen engine.

## Sub-features

- `ask-mcp` answers through `cicada_ask`.
- `ask-app` answers in Home's `Ask` mode and the palette.
- `ask-api` answers `POST /ask`.

## How to get to it (user POV)

- Home: the `Ask` button beside `Find`, then type.
- MCP `cicada_ask`.
- `POST /ask {"query": ...}`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- The run was launched with `--search-model`, and the standard seed has been through `$CV sleep`. Without the model,
  Ask's page retrieval finds nothing for a natural question (observed 2026-10-22: `No entities in memory relate to…`).

- **API.** Run `$CV api POST /ask '{"query": "What FFT library does alpha-project use?"}' --save api/ask.json`. The answer names rustfft and cites `alpha-project` (a claim id and its evidence span).
- **MCP.** Run `$CV mcp call cicada_ask '{"query": "What FFT library does alpha-project use?"}' --timeout 180`. The same answer, with `[[alpha-project]]` under Citations.
- **App.** `vclick 'button Ask$'`, then `vh set_value --element_index <n> --value "What FFT library does alpha-project use?"` on the `Ask your memory` field (read its number from `vh get_app_state`) and `vh press_key --key Return`; wait about 25 s, then `$CV app shot ask`. The answer is read under the field.

## Gotchas

- Ask spends a plan call (haiku) each time.
- Without the search model a query of bare words (`alpha-project rustfft`) still answers from the conversations, but cites no page. Do not report that as Ask working on pages.
