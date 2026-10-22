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
- A PNG under the run dir. Any small synthetic one does, for example a 64×40 dark fill written with Python's `zlib` and `struct` into `<run>/fixtures/look.png`.

- **Save.** Run `$CV mcp call cicada_save_design '{"note": "verify: a dark, quiet header", "url": "https://example.com/", "image_path": "<run>/fixtures/look.png", "title": "Example dark", "tags": ["dark"], "subject": "alpha-project"}'`. `Saved <date>-example-com … on the page alpha-project (its Looks section)`, with its palette.
- **Stored.** `$CV bank ls | grep design` shows `design/<date>-example-com.md`; `$CV bank cat entities/alpha-project.md` has a `## Looks` section linking it.
- **Search.** Run `$CV mcp call cicada_design_search '{"query": "dark"}'`. The look, `matched by words`.

## Gotchas

- Picture search needs the image encoder, a separate download the person makes; word search works without it (`Only words were compared`).
- Without `subject` the look is kept but sits on no page.
