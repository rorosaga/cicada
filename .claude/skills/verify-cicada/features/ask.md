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
- Sleep has made `alpha-project`.

- **API.** Run `$CV api POST /ask '{"query": "What FFT library does alpha-project use?"}' --save api/ask.json`. The answer names rustfft and cites `alpha-project`.
- **MCP.** Run `$CV mcp call cicada_ask '{"query": "What FFT library does alpha-project use?"}'`. The same answer with its citations.
- **App.** `vclick 'button Ask'`, type the question with `vh type_text --text ...`, then `$CV app shot ask`.

## Gotchas

- Ask spends a plan call (haiku) each time.
- With no engine it says so and names the pages it found; that is not a failure of the feature.
