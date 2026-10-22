# Design looks

A screenshot of a look the person saved, with its palette and type, attached to the page of the thing it shows and searchable by words or picture.

## Sub-features

- `save-design`, `design-search`, `design-similar`, `looks-on-page`.

## How to get to it (user POV)

- A page's `Looks` section; Clusters' looks filter.
- MCP `cicada_save_design`, `cicada_design_search`.
- `GET/POST /design`, `POST /design/search`, `GET /design/{id}/similar`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- A PNG on disk to save as a look.

- **Save.** Run `$CV mcp call cicada_save_design '{...}'` with the shape from `$CV mcp schema cicada_save_design`. A record under the bank's design folder.
- **Search.** Run `$CV mcp call cicada_design_search '{"query": "dark"}'`.

## Gotchas

- Picture search needs the image encoder, a separate download the person makes; word search works without it.
