# P3 — Sleep Link-Enrichment Subagent Design

**Status:** Design artifact — pre-M5a, no code changes.
**Context:** CPCG architecture (`d2-architecture-final.md`, ADDENDUM §6). Extends `api/services/media_ingestor.py`
and inserts a new Sleep stage between the existing 5.55 (`inject_media_edges`) and 5.6 (`regenerate_hubs_and_index`).

---

## Motivation: the John example

Prof. John recommends two conference websites in conversation. The episode captures his recommendation
and the two URLs. At ingest time `media_ingestor.enrich()` fetches Open-Graph tags and writes a media
entity for each site. Both sites have a short `og:description` — fine for a title, useless for
retrieval. Three months later Rodrigo asks "/ask which conference sites did John recommend for robotics?".
The `/ask` path searches the claims index. If the media entities carry no description claim anchored to
"robotics conference," the query misses.

The enrichment subagent exists to close this gap: when a saved link lands in Sleep with no meaningful
description, a small model fetches the page, reads the visible text, and writes a `description` claim
(and a `recommends` claim from John) into the CPCG store so the link is retrievable when the context
matters.

---

## 1. Trigger condition

The subagent runs as **Stage 5.57** — after `inject_media_edges` (5.55, which wires `about` edges
using shared source episodes) and before `regenerate_hubs_and_index` (5.6), so any new description
claim is visible to the hub tier.

A media entity is a candidate for enrichment if **all three** hold:

1. `type: media` in its frontmatter.
2. `description` claim is absent OR the only description is the raw Open-Graph tag (≤ 120 characters,
   no sentence-ending punctuation, likely a tagline not a summary — heuristic: `len < 120 and not
   any(c in text for c in ".!?")`).
3. `enrichment_attempted` is NOT set in frontmatter (idempotency guard — set on first attempt,
   success or offline failure, so re-runs don't re-spend tokens).

YouTube videos are **excluded** — the oEmbed title + channel is sufficient retrieval signal; their
"description" is a transcript, too long for a single claim.

Instagram URLs are **excluded** — login-walled by design (existing `media_ingestor` behavior).

---

## 2. Pipeline: reuse vs. new LLM call

### 2a. Reuse existing enrichment (zero LLM cost)

Before making any LLM call, the subagent checks whether `_enrich_opengraph` already produced a
description that is substantive (> 120 chars, contains at least one sentence-ending character). If so,
it promotes that string into a proper CPCG `description` claim (see §4) and sets `enrichment_attempted:
true` on the entity. No network call, no LLM call.

This covers the common case where Open-Graph `og:description` or `<meta name="description">` was
present at ingest time but not surfaced as a claim — the existing `write_media_entity` writes it only
into the markdown body (`## Description`), not into the claims store.

### 2b. Scour + summarize (LLM call, triggered only when OG is absent/thin)

When OG description is absent or thin:

1. **Fetch** the URL with the existing `_enrich_opengraph` HTTP path (re-uses `USER_AGENT`, `_TIMEOUT`,
   `_MAX_READ` = 1.5 MB cap, `follow_redirects=True`). If the site was already fetched at ingest time
   and produced a thin description, the raw HTML is not cached — we re-fetch. This is intentional:
   enrichment runs once at Sleep time (not at save time) when the cycle is already a background batch.
2. **Extract visible text.** From the parsed HTML (`BeautifulSoup`), collect:
   - `<h1>` and `<h2>` headings (structural signal for topic)
   - `<main>` or `<article>` body text, truncated to first 2,000 characters
   - Fallback: `<body>` text stripped of `<nav>`, `<footer>`, `<script>`, `<style>` blocks
3. **Summarize** with one call to the configured mini model (`settings.litellm_model`, same model
   Sleep Stage 1 uses). Prompt:

   ```
   You are summarizing a web page for a personal memory system.
   Given the page title and a text excerpt, write a 1–2 sentence description
   of what this site or page is about. Be specific about the topic.
   Be concise. Do not start with "This site" or "This page".

   Title: {meta.title}
   Excerpt:
   {excerpt[:2000]}

   Description (1-2 sentences):
   ```

   Max output tokens: 100. Temperature: 0 (deterministic). Expected cost per call: ~400 in + ~60 out
   tokens on a mini model ≈ $0.0003 per URL.

4. Write the resulting string as a `description` claim (§4).
5. Set `enrichment_attempted: true` on the entity frontmatter. If the fetch or LLM call fails, still
   set the flag with `enrichment_status: failed` so the retry gate is not re-triggered every Sleep
   cycle (see §5).

---

## 3. Cost bound

The subagent enforces a hard cap of **`LINK_ENRICH_MAX_PER_CYCLE = 20`** LLM calls per Sleep cycle
(configurable in `Settings`). Selection priority when candidates exceed the cap:

1. Entities whose source episode overlaps with a person entity (e.g. John's episode created both John
   and the two sites — these are highest value because the `recommends` claim from §4 needs a
   description to be useful).
2. Most recently saved (`last_referenced` DESC).
3. Truncate at 20.

Network fetches use the same `asyncio.Semaphore(8)` concurrency gate as `ingest_batch` — no more
than 8 simultaneous outbound connections. LLM calls are sequential within the semaphore (one fetch
→ one LLM call per item, no parallel LLM calls) to keep the per-cycle token burst predictable.

Total worst-case cost per cycle: 20 × $0.0003 ≈ **$0.006** (half a cent). Over a month of daily
cycles on a link-heavy day: $0.18. Negligible.

---

## 4. Claims produced (CPCG schema)

All claims are written into the media entity's claims file (`claims/<media-entity-id>.claims.yaml`).
The subagent calls the same `write_claims_file()` function that M5a will provide (in `markdown_parser`),
so it is a clean consumer of the M5a API.

### 4a. Description claim (always produced if enrichment succeeds)

```yaml
- id: clm_{date}_{seq}
  text: "{summarized description}"
  subject: media-{slug}
  predicate: describes
  object: "{summarized description}"     # literal — object_kind: literal
  object_kind: literal
  observer: agent
  context: general
  epistemic: explicit
  source_trust: agent_extracted
  confidence: 0.75
  valid_from: "{today}"
  valid_to: null
  superseded_by: null
  supersedes: null
  recorded_at: "{today}"
  source_episodes: ["{episode_id}"]      # the episode that created this media entity
  premises: []
  authored_by: "{settings.litellm_model}"
  origin: sleep/link_enrichment
```

### 4b. Recommender claim (written when a person entity is the observer)

When the source episode contains a person entity (resolved in Stage 2's `changes` list), the
subagent also writes a `recommends` claim **on the person entity**:

```yaml
# In claims/john.claims.yaml (appended)
- id: clm_{date}_{seq}
  text: "John recommended {site title} ({url})."
  subject: john
  predicate: recommends
  object: media-{slug}
  object_kind: node
  observer: agent
  context: general
  epistemic: explicit
  source_trust: agent_extracted
  confidence: 0.80
  valid_from: "{episode date}"
  valid_to: null
  superseded_by: null
  supersedes: null
  recorded_at: "{today}"
  source_episodes: ["{episode_id}"]
  premises: []
  authored_by: "{settings.litellm_model}"
  origin: sleep/link_enrichment
```

The person-entity detection heuristic: any entity in `changes` whose `source_episode` matches the
media entity's `source_episodes[0]` AND whose `type` is `person`. In the John example both site
episodes share John's episode, so two `recommends` claims are written on John's claims file.

### 4c. Concrete claims for the John example

Assume John's entity id is `john`, and the two sites are `media-robotics-conf-site-1` and
`media-humanoid-robotics-2026`.

**In `claims/media-robotics-conf-site-1.claims.yaml`:**
```yaml
- id: clm_2026-06-18_041
  text: "A curated list of robotics conferences and workshops for graduate researchers,
         with submission deadlines and location details."
  subject: media-robotics-conf-site-1
  predicate: describes
  object: "A curated list of robotics conferences and workshops for graduate researchers,
           with submission deadlines and location details."
  object_kind: literal
  observer: agent
  context: general
  epistemic: explicit
  source_trust: agent_extracted
  confidence: 0.75
  valid_from: "2026-06-18"
  valid_to: null
  source_episodes: [ep_2026-06-17_003]
  authored_by: gpt-5.4-mini
  origin: sleep/link_enrichment
```

**In `claims/media-humanoid-robotics-2026.claims.yaml`:**
```yaml
- id: clm_2026-06-18_042
  text: "The 2026 International Conference on Humanoid Robots — program, speaker list,
         and registration for the Tokyo event."
  subject: media-humanoid-robotics-2026
  predicate: describes
  object: "The 2026 International Conference on Humanoid Robots — program, speaker list,
           and registration for the Tokyo event."
  object_kind: literal
  observer: agent
  context: general
  epistemic: explicit
  source_trust: agent_extracted
  confidence: 0.75
  valid_from: "2026-06-18"
  valid_to: null
  source_episodes: [ep_2026-06-17_003]
  authored_by: gpt-5.4-mini
  origin: sleep/link_enrichment
```

**In `claims/john.claims.yaml` (two new entries appended):**
```yaml
- id: clm_2026-06-18_043
  text: "John recommended Robotics Conf Site 1 (https://robotics-conf-list.example.com)."
  subject: john
  predicate: recommends
  object: media-robotics-conf-site-1
  object_kind: node
  observer: agent
  context: general
  epistemic: explicit
  source_trust: agent_extracted
  confidence: 0.80
  valid_from: "2026-06-17"
  valid_to: null
  source_episodes: [ep_2026-06-17_003]
  authored_by: gpt-5.4-mini
  origin: sleep/link_enrichment

- id: clm_2026-06-18_044
  text: "John recommended Humanoid Robotics 2026 (https://humanoid2026.example.org)."
  subject: john
  predicate: recommends
  object: media-humanoid-robotics-2026
  object_kind: node
  observer: agent
  context: general
  epistemic: explicit
  source_trust: agent_extracted
  confidence: 0.80
  valid_from: "2026-06-17"
  valid_to: null
  source_episodes: [ep_2026-06-17_003]
  authored_by: gpt-5.4-mini
  origin: sleep/link_enrichment
```

---

## 5. Offline / failure fallback

| Failure mode | Behavior |
|---|---|
| Network timeout on fetch | Mark `enrichment_attempted: true`, `enrichment_status: fetch_failed`. Skip LLM call. No claim written. |
| HTTP error (4xx, 5xx) | Same — mark and skip. |
| LLM call fails or returns empty | Mark `enrichment_attempted: true`, `enrichment_status: llm_failed`. No claim written. |
| LLM returns only the title or < 20 chars | Discard (treat as failed). Same flags. |
| Site requires JS rendering (blank `<body>`) | Detected by `len(stripped_text) < 100`; mark as `enrichment_status: js_required`. No claim. |
| Claims file write fails | Log warning; leave `enrichment_attempted` unset so the next cycle retries. This is the one failure mode that does NOT set the idempotency flag — the claim never landed, so retry is safe. |

The `enrichment_attempted` flag lives in the media entity's own frontmatter (not in a separate
index file), so it is git-diffable and inspectable with `cat entities/media-*.md`.

---

## 6. Deduplication

Three-layer dedup:

1. **URL-level (existing):** `url_index.json` prevents the same URL from being ingested twice.
   Enrichment never re-runs on a duplicate because the entity already exists with `enrichment_attempted`.
2. **Entity-level (new flag):** `enrichment_attempted: true` in frontmatter — skip unconditionally.
3. **Claim-level (M5a `write_claims_file`):** The claim writer checks for an existing claim with
   the same `(subject, predicate, object_kind=literal)` before appending; if a description claim
   already exists (e.g. from a prior cycle where the flag was lost), it skips silently.

---

## 7. Bidirectional inline transclusion

After the claims are written, the subagent authors **two transclusion directives** (written into the
generated entity cards during Stage 5's card render, not by the subagent directly — the subagent
emits instructions as a structured side-channel to the card renderer):

### 7a. John's page embeds the sites

In `entities/john.md`, the `## Related` section (authored by Stage 4 / Stage 5 card renderer) includes:

```markdown
## Related

### Recommended links
![[media-robotics-conf-site-1]]
![[media-humanoid-robotics-2026]]
```

This is produced deterministically from John's `recommends` claims: any claim with
`predicate: recommends, object_kind: node` on a `media` entity → emit `![[{object}]]` in the
person's `## Related / Recommended links` subsection.

### 7b. Each site's page embeds John as recommender

In `entities/media-robotics-conf-site-1.md` and `entities/media-humanoid-robotics-2026.md`, the
`## Related` section includes:

```markdown
## Related

### Recommended by
![[john]]
```

This is produced from the `recommends` edge in the reverse direction: the graph edge
`john --recommends--> media-*` is traversed and expressed as `![[john]]` in the media card's
`## Recommended by` subsection.

Both transclusion directives resolve under the depth-cap-3 + cycle-guard contract of
`transclusion_resolver.py` (M5a). They are **read-only embeds**: editing John does not write back
to the site card. The cycle guard prevents `![[john]] → ![[media-*]] → ![[john]]` ping-pong.

### Observer record in the recommends claim

The `recommends` claim uses `observer: agent` (the Sleep cycle noticed the recommendation from the
episode) rather than `observer: external:john`. This is correct: the system extracted the recommendation
from context; John did not write it into the system himself. The claim text explicitly names John
(`"John recommended …"`) so the attribution is human-readable without requiring `observer` to carry it.
If John directly saves a URL via a Telegram `/save` command or future "recommended by" annotation,
that write path sets `observer: external:john, source_trust: user_stated` — a higher-trust variant
that the Stage-3 conflict resolver will let supersede the `agent_extracted` version.

---

## 8. Sleep pipeline placement

```
Stage 5     generate() — write entities, nudges, relationships
Stage 5.5   materialize_wikilink_edges()
Stage 5.55  inject_media_edges()          ← existing: about edges from shared source episodes
Stage 5.57  enrich_media_links()          ← NEW: fetch + summarize + write description/recommends claims
Stage 5.6   regenerate_hubs_and_index()   ← sees new description claims in hub card excerpts
```

The stage runs in a `try/except` wrapper identical to 5.55, so any failure logs a warning and
continues — the Sleep cycle cannot be hard-blocked by a network timeout.

```python
# In sleep_cycle.run(), after inject_media_edges block:
try:
    from api.services.link_enrichment import enrich_media_links
    n_enriched = await enrich_media_links(memory_path, changes, settings)
    logger.info(f"Stage 5.57: enriched {n_enriched} media link(s)")
except Exception as e:
    logger.warning(f"Stage 5.57 link enrichment failed: {type(e).__name__}: {e}")
```

---

## 9. New module: `api/services/link_enrichment.py`

Public surface (to be implemented in M5a/M5e):

```python
async def enrich_media_links(
    memory_path: Path,
    changes: list[dict],        # Stage 2/3 resolved changes — used to detect recommender persons
    settings: Settings,
    *,
    max_per_cycle: int = 20,    # LINK_ENRICH_MAX_PER_CYCLE
) -> int:
    """
    Scan media entities for thin/absent descriptions, fetch+summarize,
    and write description + recommends claims into CPCG.
    Returns the count of entities successfully enriched.
    """
```

Internal helpers (all in the same module):

- `_candidates(memory_path, changes, max_per_cycle)` — select and rank entities needing enrichment
- `_extract_visible_text(html: str) -> str` — BeautifulSoup visible-text extractor (re-uses bs4,
  already a dep via `media_ingestor`)
- `_summarize(title: str, excerpt: str, settings: Settings) -> str | None` — single LLM call
- `_build_description_claim(subject_id, text, episode_id, today, model) -> dict` — claim dict factory
- `_build_recommends_claim(person_id, media_id, title, url, episode_date, today, model) -> dict`
- `_detect_recommender(media_entity, changes) -> str | None` — find person entity sharing episode
- `_write_enrichment_flag(entity_path, status)` — set `enrichment_attempted` + optional `enrichment_status`

Imports reused from `media_ingestor`: `USER_AGENT`, `_TIMEOUT`, `_MAX_READ`, `_enrich_opengraph`
signature (HTTP fetch). Does NOT re-export or modify `media_ingestor`; imports only.

---

## 10. Config additions to `Settings`

```python
link_enrich_max_per_cycle: int = 20       # hard cap on LLM calls per Sleep cycle
link_enrich_min_desc_len: int = 120       # chars; OG desc shorter than this → trigger LLM
link_enrich_excerpt_chars: int = 2000     # chars of visible body text fed to LLM
link_enrich_enabled: bool = True          # kill switch (offline, cost-sensitive mode)
```

---

## 11. Query path: how the John example resolves after enrichment

```
/ask "which conference sites did John recommend for robotics?"
```

1. KNN over `claims` kind: hits description claim for `media-robotics-conf-site-1` (text contains
   "robotics conferences") and `media-humanoid-robotics-2026` (text contains "Humanoid Robots").
2. 1-hop expansion from those media node ids → `recommends` edge from `john`.
3. Retrieval context includes: both description claims + both `recommends` claims (John as subject).
4. Answer: names both sites, attributes them to John, cites `clm_2026-06-18_043/044` as provenance.
5. In the app: John's card shows `![[media-robotics-conf-site-1]]` and `![[media-humanoid-robotics-2026]]`
   inline in `## Recommended links`; each site card shows `![[john]]` in `## Recommended by`.

Without enrichment (baseline): description claims absent → KNN misses both sites → `/ask` returns no
results or hallucinates. The `recommends` claims alone (without content description) hit John but
cannot surface the sites by topic.

---

## Summary

This design introduces a bounded, offline-safe Sleep substage (5.57) that converts thin Open-Graph
metadata into searchable CPCG description claims and bidirectional `recommends` claims. It reuses
the existing `_enrich_opengraph` HTTP path and bs4 dep, adds one mini-model call per uncached link
(capped at 20/cycle, ~$0.006/cycle worst case), writes clean CPCG claims with the full
`observer/context/epistemic/source_trust/origin` schema, and authors `![[…]]` transclusions so the
recommendation is visible from both John's page and each site's page. The idempotency flag
(`enrichment_attempted`) ensures each URL is processed at most once regardless of how many Sleep
cycles run.
