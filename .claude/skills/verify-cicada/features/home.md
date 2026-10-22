# Home

The front page: one field to search, paste a link or drop a file, what needs the person, what came in today, and what the last read changed.

## Sub-features

- `home-field` searches or asks.
- `home-needs-you` shows inbox items worth a look.
- `home-today` counts today's captures by source.
- `home-last-read` lists pages the last Sleep changed, each a link to the graph.

## How to get to it (user POV)

- Sidebar `Home` (the first button). A run whose bank has had no Sleep may open on the welcome screen first; `vclick 'button Set up later'` leaves it for Home (never `Get started`).

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- The app is launched (`$CV app build && $CV app launch`).

- **Open.** `vclick 'button.*Description: Home,'`. The heading reads `What would you like to remember?`.
- **Today.** After captures, the row reads `N captured today, mostly Cursor N` (`vh get_app_state | grep captured`).
- **Last read.** After Sleep, `Last time Cicada read` lists `alpha-project` as a button (`Help: Show alpha-project on the graph`).
- **Proof.** `$CV app shot home`.

## Gotchas

- The window fills in from disk and then the live stream; read again after a second if a count lags.
