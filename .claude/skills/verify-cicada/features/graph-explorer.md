# Graph explorer

The person's memory drawn as a force graph of pages and links; clicking a node opens its card.

## Sub-features

- `graph-view` draws nodes and links.
- `graph-focus` opens a node's card.
- `graph-legend` filters by type and status.
- `graph-zoom` zooms, fits and pans.

## How to get to it (user POV)

- Sidebar `Graph`; any `Show X on the graph` button.
- `GET /graph` (returns `nodes` and `links`).
- `cicada graph`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- Sleep has made at least one page besides the owner's.

- **API.** Run `$CV api GET /graph --save api/graph.json`. `nodes` includes `alpha-project` and `owner`; `links` joins them.
- **CLI.** Run `$CV cli -- graph`. Pages by type and status.
- **App.** `vclick 'button.*Description: Graph,'`, then `$CV app shot graph`. The graph is a web view (`HTML content`); its nodes are not AX elements, so click a node with `$CV app click X Y` from the screenshot.
- **Focus.** On Home, `vclick 'Description: alpha-project, Help: Show alpha-project on the graph'`. The graph opens centred on it.

## Gotchas

- d3-force keeps moving for a moment; screenshot after it settles (about 2 s).
