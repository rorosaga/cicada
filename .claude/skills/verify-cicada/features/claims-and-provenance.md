# Claims and provenance

Beliefs are typed claims with evidence spans into the conversation they came from; an agent can write a claim with its quoted evidence and withdraw only what it wrote.

## Sub-features

- `claim-write` (`cicada_write_claim`) with evidence quotes and sources.
- `claim-retract` (`cicada_retract_claim`) for the writer's own claim.
- `claim-timeline` shows a subject's claims over time.
- `evidence-span` locates the quote in the episode.

## How to get to it (user POV)

- MCP `cicada_write_claim`, `cicada_retract_claim`, `cicada_refresh_claim`.
- `GET /entities/{entity_id}/claims`, `GET /entities/{entity_id}/timeline`, `GET /entities/{entity_id}/provenance`, `GET /episodes/{episode_id}/span`.
- The Reader in the app.

## Driving it with verify-cicada

Preconditions:

- A run is up and `$CV doctor` is all `ok` (backend, scratch root, plan).
- `alpha-project` exists, and the seed carries a fact Sleep did not already write as a claim. The standard seed plus
  `$CV capture --session verify-s3 --turn t1 --user "My sister labelled another forty birdsong clips for alpha-project today; she wants to try a mel filterbank next."` before `$CV sleep` gives one.

- **Write.** Run `$CV mcp call cicada_write_claim '{"subject": "alpha-project", "predicate": "plans_to_try", "object": "mel filterbank", "evidence": [{"episode": "<that episode id>", "quote": "she wants to try a mel filterbank next"}]}'`. The reply names the claim id (`clm_alpha-project_plans_to_try_…`) and `evidence: 1 span verified`.
- **Stored.** Run `$CV api GET /entities/alpha-project/claims`. The claim with that id, `sessionIds: ["verify-<run id>"]` and an evidence span (offsets and hash, `kind: user`).
- **Commit.** Run `$CV bank log`. An `Agent write` commit with `Cicada-Author: verify` and `Cicada-Session: verify-<run id>`.
- **Retract.** Run `$CV mcp call cicada_retract_claim '{"subject": "alpha-project", "claim_id": "<id>", "reason": "verify"}'`. `Withdrew claim …`, with a retract record id; nothing is deleted.

## Gotchas

- A quote that cannot be located becomes reasoning; the claim is still written. Assert on the claim, not the span, when the quote is paraphrased.
- Restating a fact Sleep already wrote (`alpha-project uses rustfft` after the standard seed) folds into Sleep's claim: the reply says `action=written` but names an id that is not on the page, and a retract with that id answers `No claim …`; the surviving claim is Sleep's, so it answers `not written by this agent`. Observed 2026-10-22; G204 in the backlog. Drive the recipe on a new fact.
