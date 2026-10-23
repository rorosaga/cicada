# Recall and search

An agent or the person finds what memory holds about something: pages, claims and conversation text, fused from words, meanings and claims, with hints for the next call.

## Sub-features

- `recall` returns ranked pages with hints (`cicada_recall`).
- `recall-detail` returns one page in full (`cicada_recall_detail`, `cicada get`).
- `find` searches pages, beliefs, conversations, sources and questions as the app's search does.
- `search-index` reports and rebuilds the derived word and vector indexes.

## How to get to it (user POV)

- Home's field (`Find`), the toolbar field or ⌘K (the find palette).
- MCP `cicada_recall`, `cicada_recall_detail`, `cicada_get_perspective`.
- `GET /search?q=`; `cicada recall`, `cicada get`, `cicada find`, `cicada index status | rebuild`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- Sleep has made `alpha-project` (see sleep-cycle).

- **MCP recall.** Run `$CV mcp call cicada_recall '{"query": "alpha-project spectrogram"}'`. The text starts with the "Reference data from Cicada" header, then the `cicada-hints` block (Cicada's own, outside the `<<<cicada-reference` markers) whose `suggested_entities` include `alpha-project`, then the page summary between the markers.
- **Detail.** Run `$CV mcp call cicada_recall_detail '{"entity_id": "alpha-project"}'`. The full page with its claims.
- **CLI.** Run `$CV cli -- recall alpha-project` and `$CV cli -- get alpha-project`. Same page.
- **API.** Run `$CV api GET '/search?q=alpha&mode=prefix'`. A hit for `alpha-project`.
- **App.** On Home, `vh set_value --element_index $(vidx 'text field.*Search your memory') --value alpha` and read the results; `$CV app shot find`.
- **Proof.** `evidence/mcp/*cicada_recall.jsonl` holds the JSON-RPC exchange.

## Gotchas

- Without `--search-model`, recall is word-only and the CLI warns `degraded:vector`. Expected.
- The query is never logged anywhere; do not look for it in logs.
