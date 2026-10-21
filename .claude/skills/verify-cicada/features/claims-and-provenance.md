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
- `alpha-project` exists and an episode quotes `rustfft`.

- **Write.** Run `$CV mcp call cicada_write_claim '{"subject": "alpha-project", "predicate": "uses", "object": "rustfft", "evidence": [{"episode": "<episodeId>", "quote": "alpha-project will use rustfft"}]}'`. The reply names the claim id.
- **Stored.** Run `$CV api GET /entities/alpha-project/claims`. The claim with an evidence span (offsets and hash).
- **Commit.** Run `$CV bank log`. A commit under the MCP session's author with a `Cicada-Session` trailer.
- **Retract.** Run `$CV mcp call cicada_retract_claim '{"subject": "alpha-project", "claim_id": "<id>", "reason": "verify"}'`. The claim is withdrawn.

## Gotchas

- A quote that cannot be located becomes reasoning; the claim is still written. Assert on the claim, not the span, when the quote is paraphrased.
