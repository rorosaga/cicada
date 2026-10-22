# Sources

What came into memory and from where: saved links, feeds, folders, calendars, browsers, chat exports, and each tracked source of a page with its re-check state.

## Sub-features

- `sources-overview`, `sources-channels`, `page-sources` (`cicada_sources`, `cicada_add_source`, `cicada_change_source`), `source-refresh` (`cicada_record_refresh`).

## How to get to it (user POV)

- Sidebar `Sources`.
- `GET /sources`, `/sources/overview`, `/sources/channels`, `/entities/{id}/sources`.
- MCP `cicada_sources`, `cicada_add_source`, `cicada_change_source`, `cicada_refresh_claim`, `cicada_record_refresh`; `cicada feed list | add | remove | poll`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **Overview.** Run `$CV api GET /sources/overview`. One row per channel; the captured Cursor conversations are `harness:cursor` with their counts.
- **Add.** Run `$CV mcp call cicada_add_source '{"subject": "alpha-project", "ref": "https://example.com/alpha"}'`, then `$CV api GET /entities/alpha-project/sources`. The ref, `addedBy: verify`, not trusted.
- **App.** `vclick 'button.*Description: Sources,'`, `$CV app shot sources`. `Saved by you` and `Captured for you`, Cursor with its conversation count.

## Gotchas

- Feed polling and site checks fetch the web; the verify run gates them off. A check that reports `fetch disabled` is the gate, not a bug.
- `cicada_sources` is the conversations behind a page, not this list; it takes other arguments.
