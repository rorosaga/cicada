# Clusters

Pages grouped into topical clusters, with a filter for pages that carry saved looks.

## Sub-features

- `clusters-grid` shows clusters and their pages.
- `clusters-open` opens a page from a cluster.
- `clusters-looks` filters to pages with looks.

## How to get to it (user POV)

- Sidebar `Clusters`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- A bank with several pages (a two-conversation journey gives few; seed more conversations for a meaningful grid).

- **Open.** `vclick 'button.*Description: Clusters,'` then `$CV app shot clusters`. Filters with counts (`All`, `People`, `Projects`, `Looks`…) and the tiles.
- **Page.** Click a tile by its type and name: `vclick 'button Project, alpha-project'`. Its detail opens in the right column (`Project Active · …`).

## Gotchas

- A tiny bank may show one cluster or the empty state; that is the seed, not a defect. Report it as such.
