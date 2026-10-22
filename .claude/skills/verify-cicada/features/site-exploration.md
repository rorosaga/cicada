# Exploring saved sites

On the person's click or ask, a trusted local agent explores a saved site within a depth plan Cicada computes, and each visit is recorded as a dated capture with a site map.

## Sub-features

- `explore-start`, `explore-queue`, `explore-claim`, `record-capture`, `site-map`, `explore-captures`.

## How to get to it (user POV)

- Sources → a site → Explore.
- MCP `cicada_explore_start`, `cicada_explore_queue`, `cicada_explore_claim`, `cicada_record_capture`, `cicada_site_map`.
- `GET /explore/state`, `/explore/candidates`, `/explore/sites`, `POST /explore/batches`.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).

- **State.** Run `$CV api GET /explore/state` (`items: []`) and `$CV api GET /explore/candidates` (`eligible: 0` and the estimate). Empty on a fresh bank.
- **Queue.** Run `$CV mcp call cicada_explore_queue '{}'`. `Nothing is waiting in the person's explore queue.`

**Not driven in a verify run: an exploration.** It visits real sites with the person's signed-in browser. Driving stops
at reading the state; the nearest check of a run is the explore tests (`api/tests/test_explore*.py`).

## Gotchas

- Exploring visits real sites with the person's signed-in browser; do not start a run from a verify session.
