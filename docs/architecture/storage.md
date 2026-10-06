# Storage, claims, provenance and git

Moved word for word from `CLAUDE.md` on 2026-10-01, when that file passed Claude Code's size limit (it is loaded into every
session). **`CLAUDE.md` keeps the rails and the map; this file keeps the detail.** A rail stated there binds here too. When
a change makes this file wrong, update it in the same PR (repository paths below are relative to the repository root).

### Markdown, not a database
Wikilinked `.md` files with YAML frontmatter, git-versioned. **The filesystem is the single source
of truth** — the API reads and writes the same files the Sleep cycle does. At personal scale
(hundreds of entities) the LLM follows wikilinks; it doesn't need Cypher. Zero infrastructure,
human-readable, portable, Obsidian-compatible.

**Every page write is atomic** (audit 2026-10-02 A02): `markdown_parser.write` stages the whole
document in a hidden sibling `.<name>.<random>.tmp` (never matched by a `*.md` scan), fsyncs it and
`os.replace`s it over the page, keeping the page's permission bits and writing through a symlink to
its target. A failed write leaves the old page byte-for-byte and removes the temp file. The
directory is not fsynced: the guarantee is "never a torn or empty page", not "the rename survives a
power cut". `markdown_parser.write_new` creates a page without ever replacing one (a hard link of the
staged file, `FileExistsError` if the name is taken) — what new episodes use (K01, below).

**A bank's boundary is its directory** (audit 2026-10-02 A04): exporting (`bank_registry.export_zip`) and
duplicating (`duplicate_bank`) a bank never follow or copy a symlink, at any depth and whatever it points at, so a
link inside a bank can never pull a file from outside it into an archive or a copy.

### Entity schema

```yaml
---
type: person | project | company | concept | tool | deadline | skill | location | media | directory
status: active | decaying | archived | dropped
confidence: 0.85
created: 2026-01-10
last_referenced: 2026-03-22
decay_rate: 0.05           # per-entity, not global
decay_class: active        # evergreen | durable | active | volatile (G66)
source_episodes: [ep_2026-01-10_001]
tags: []                   # open set, freeform
related: []                # duplicates wikilinks for programmatic access
version: 3
---
```

**Entity types are a closed set of 10** (`api/models/schemas.py::EntityType`): `person`, `project`,
`company`, `concept`, `tool`, `deadline`, `skill` (procedural memory / preferences), `location`,
`media` (ingested item with an agent-generated summary), `directory` (a filesystem path, split out
from `location` in G18).

**Two exclusions matter (G17).** `deadline` still renders for legacy pages but is **no longer
produced by Stage-1 extraction** — `PRODUCIBLE_ENTITY_TYPES` excludes it; due-dates attach as a
`due` claim on the relevant project instead of spawning a standalone entity. `media` is likewise
excluded — it comes from the ingestion path, not conversation extraction.

**Status lifecycle:** `active` → `decaying` → `archived` → `dropped` (user-dismissed, never
resurfaced).

### Decay classes (G66)
One resolver, `api/services/decay_policy.py`. `resolve(fm)` returns `(class, rate)`: an explicit
`decay_class:` wins; otherwise inferred from `type` (`media` → evergreen, `skill` → durable, else
active) so legacy pages keep working. An explicit numeric `decay_rate:` still wins for the three
decaying classes; `evergreen` pins its rate to `0.0` unconditionally.

| Class | Base entity rate/wk | Claim multiplier | Meaning |
|---|---|---|---|
| `evergreen` | 0.0 | 0.0 | Never fades. Artifacts (media/bookmarks) + anything the user pins. |
| `durable` | 0.02 | 0.5 | Stable preferences, skills, long-lived concepts. |
| `active` | 0.05 | 1.0 | Default for a belief about the user's life. |
| `volatile` | 0.15 | 2.0 | Expected to change within weeks (role, status, current focus). |

**Anti-pollution rail** (mirrors `PRODUCIBLE_ENTITY_TYPES`): Stage-1 may propose
`durable|active|volatile` and **never `evergreen`** (`AGENT_PRODUCIBLE_DECAY_CLASSES`, enforced at
extraction AND again in the create branch). Evergreen is reserved for ingest writers and the user,
so an over-eager extractor can never stop the graph from archiving.

**Both engines honor it.** `conflict_resolver.resolve_and_prune` skips evergreen entities outright —
no decay math, no nudge, never auto-archived, so a bookmark can't generate a "still interested?"
question. `claim_reconciler._decay_claims` multiplies its per-epistemic × source_trust rate by the
SUBJECT's class multiplier. Since G147 the class rate is the *base*: both engines multiply it by the
spacing factor and the per-type pace (see Temporal decay).

### Claims, evidence and provenance

**Claims** are the machine-legible half: typed predicates, bi-temporal validity, observer and trust.
A predicate the vocabulary marks multi-valued (`predicates.cardinality`) never opens a conflict.

**Contexts and the fence (F1).** `context` is an open vocabulary whose *shape* is pinned by
`claim_contexts` — a short lowercase slug. Any other value (G60's `as of <date>`) keeps its job as a
claim key but is never a graph satellite, a legend row or an edge colour. `general` means "no
particular context" and is never a facet: a satellite needs two real contexts. The claims fence sits
after a page's last section (`write_claims`, the one writer), so **every reader strips it before
sectioning** — `strip_claims_block` on the server, `EntityProse` in the app.

**A merge keeps both claim sets (audit 2026-10-05 P1-1).** `entity_merge.merge_entities` — the dedup sweep's and
the inbox's one merge primitive — carries every claim the loser held into the winner's fence: re-subjected to the
winner, a node object that named the loser repointed, and its observer, trust, sessions, evidence, validity and
supersedes/superseded_by untouched (a `page` span that cited the loser keeps naming it — its offsets and hash are
into that text, which git holds). An id the winner already uses is kept as `<id>-from-<loser>` (the loser's own
supersession links follow; a re-run after a crash finds its earlier copy); a claim identical once re-subjected is kept
once; two open claims that disagree stay two — a merge never closes a belief. A corrupt fence on either page aborts
the merge (the inbox answers 409), and two ids for one file (a case-insensitive disk) are refused. Before the loser's
page is deleted, `graph_edges.yaml` and every other page's `related:`, `[[wikilinks]]` (with `|label` or `#section`),
source `entity:` links and claims whose subject or node object named it are repointed (`repoint_references`), the
loser's name joins the winner's `aliases`, and the result lists the paths it wrote. The inbox's
rename-to-the-cleaner-slug branch repoints the same references (`rename_references`), and every inbox note lands above
the fence. `episodes/` is never rewritten. **The dedup sweep commits its own merges (G183(e)):** `POST
/maintenance/dedup-sweep` with `dryRun: false` runs each merge and its commit of exactly the result's paths under the page
lock (never across the judge's model call) — `Dedup sweep <date>`, `<path>: updated|removed (merged, trigger:
maintenance/dedup-sweep)`, `Cicada-Author: cicada`, `Cicada-Engine:` the judge's engine — and a failed commit puts those
paths back from HEAD; a dry run writes and commits nothing.

**Evidence spans (G118) — spans, not copies.** Every claim written since that slice carries
`evidence: [{episode, start, end, kind, hash}]`. `start`/`end` are character offsets into the source
document's *evidence text* (the body as `markdown_parser.parse` returns it, with the ```claims fence
stripped for an entity page, so writing a claim never stales its own span); `hash` is
`sha256[:12]` of that text, and a mismatch reads as `stale` rather than mis-highlighting. `kind` is
one of six: `user` | `assistant` | `page` | `speaker` (a meeting participant who is not the owner,
G134) | `media` (what a video said — a watch record's timed `video [m:ss]:` line, G140; its position
in the video is derived at read, never stored) | `reasoning` (the contributor's own inference:
`start == end == -1`, never a faked span); an episode's `evidence_kind: user|assistant` (a folder's
authorship rule, R-F2; a Claude memory export is always `assistant`, its lines being `system:`) overrides the line markers. One marker grammar, `evidence._marker`, reads
both line families, plus the chat importer's `attachment [<file name>]:` turn — the text Claude extracted from an
upload, every line quoted (`> `) so it can open no turn — which is `page`, never the person's words. One module, `api/services/evidence.py`, does the work for every writer: locate
is exact → whitespace-normalised → case-insensitive and **never fuzzy**; an unlocatable quote
becomes `reasoning` and **the claim is still written — provenance never blocks memory**. Legacy
claims carry no `evidence` and `to_dict` omits the empty key; there is no backfill.

**Events (G141).** Two predicates, `happened` (ongoing | done | dropped) and `milestone` (planned |
done | missed | dropped), with four optional fields omitted when empty — `status` (as of
`valid_from`), `target` (a milestone's planned date; expiry never reads it), `participants`
(`[{role, surface?, entity?, url?}]`, a closed role set; `surface` is an exact substring of the plain
sentence — no wikilinks in YAML) and `date_basis` (stated | turn | episode | person | written). A
done happening is **born closed** (`valid_to == valid_from`), so every reader that treats open as
current stays right; the history readers call `claims.is_event` (a grep gate enforces it). Events are
not records: they stay in FTS and citations, where they read as dated happenings, never 'no longer
current'. A milestone's slot is `(subject, milestone, slug)` across observers — the slug is its
`object`, never its `context`. Event cardinality is multi and lives in code. **Only `progress.py`
writes an event**: `write_claim` refuses the predicates, `claim_pipeline` relabels a stray label.
Dates are decided by `when.py`'s closed table; nothing relative is stored. `companion_app` is a
human origin (G141 R-PJ18): only `routers/projects.py` sets it (and the synthetic demo, which replays
app writes), no MCP tool accepts an `origin`, and `is_human` protects the person's milestones and Log
entries — an agent's different state on them coexists with a divergence item.

**Stated ends (G140).** A claim may carry `expected_end` — the date the fact itself says it stops
being true — and a G17 `due` claim's ISO-date object is its own. Never a future `valid_to`, which
every reader takes to mean *closed*. Sleep's engine-free tail closes such a claim the day after its
end (`claim_expiry`), in its own `Expiry <date>` commit (`Cicada-Author: cicada`, trigger
`sleep/expiry`); a failed commit restores the pages rather than leaving them for the next
`git add -A` writer. An agent withdraws a claim IT wrote with `cicada_retract_claim`: the claim
closes and a born-closed `retracts` record keeps the reason and any cited words; a human or Sleep
claim is never an agent's to withdraw.

**Reading provenance back (G118 slice 2, server half).** Three engine-free, bank-only reads, all
built in `api/services/provenance.py` and fetched on demand — none is a Store domain, so each ETag
serves the client's in-memory cache and there is no `VersionVector` mapping: `GET
/episodes/{id}/text` (the whole evidence text, capped at 400,000 chars, with `turns[]` from the
same marker lines `speaker_kind` reads — `speaker:<label>:` included, role `speaker`; a timed
`video [m:ss]:` line is role `media` with its `t` in seconds, as a span's `t` is — each turn's
role the `evidence.kind_for` answer, so an `evidence_kind` override relabels every turn — and an
asserted `start/end/hash` or derived `focus=<entity>`), `GET /entities/{id}/provenance` (contributors from claim `authored_by` plus one
trailer-only `git log` of the page — ETag includes `git_head` — conversations grouped by
`session_id`/`source_id`, the best quote per conversation, coverage over current claims), and `GET
/episodes/{id}/citations` (every claim citing the document, by a raw-text prefilter over
`entities/` — no index dependency). `/ask` citations also carry `claimId` + `evidence`, read from
the cited page rather than the index. Every claim on the wire is built by one function,
`transclusion_resolver.claim_to_model`, and carries `authorKind`/`authorProvider` from
`git_service.author_identity`. **Freshness is one rule, `evidence.span_status`:** `current`,
`grown` (an episode that was appended to after the span was minted — the Stop hook and G20 both
rewrite that way — and a turn-boundary prefix still hashes to the stored value, so the offsets are
exact) or `stale`. A stale span travels without wash offsets; a `derived` span (found by name,
`inbox_context.locate_mention`) exists on read payloads only — never in `EVIDENCE_KINDS`, never
written. The chat importer and every Local-sources draft keep each turn's time as
`turns: [{offset, ts, speaker}]` in frontmatter, written by `episode_staging` outside
`content_hash`; the Stop hook writes the same list (G141 PJ-4), and a reader treats any non-list — an
older Stop-hook episode's count — as no times. Round 4 (C2–C4):

- Every claim on the wire also carries `recordedTs` (stored on MCP writes only), and
  `authorModel`/`authorEffort` for a harness write. These are joined by
  `turn_authorship.TurnAuthorship`: the claim's session → its capture episode → the last person's
  turn at or before `recorded_ts` → the agent turn that answered it, with both sides floored to the
  second.
- An `assistant` span carries its turn's `model`/`effort`.
- A harness contributor lists `models: [{model, effort?, beliefs}]`.
- `/episodes/{id}/text` carries `agent` (the most recent agent turn's, null when that turn names
  neither) and per-turn `model`/`effort`.
- A watch episode's `/episodes/{id}/text` also carries `watch: {basis?, engine?, fidelity, authorModel?, authorEffort?}`
  (G162; `fidelity` is `approximate` for `video_link`, `other` and an absent engine, else `verbatim`; the model is the
  same turn join, from the `describes` claim that cites the episode) and each `media` turn its `fidelity`; `/citations`
  rows of kind `media` carry it too.
- `claim_to_model(claim, *, turns)` takes the request's join as a required keyword.
- `AUTHOR_SHAPE` also rides `/episodes/{id}/text` and both `/projects` ETags.

**Optional frontmatter keys**, each with a narrow meaning — don't conflate them:

- `repos:` — links a project/directory entity to local git checkouts. The page only ever *declares*
  which repos; **the backend never runs git, stats or resolves a declared path**. `GET
  /entities/{id}/repos` serves the declarations (path exactly as written), `this_device`, and per repo
  `on_this_device` — `local_refs.is_this_device`, the one device rule: no device or a word like `Mac` is this
  Mac, else any of its host, local host or computer names, folded (case, `.local`, punctuation); the app's
  `GitRunner` runs one fixed read-only list (`repo_context.REPO_COMMANDS`, pinned on both sides by
  `api/tests/fixtures/repo_commands.json`; CLT/Xcode/Homebrew git, never the `/usr/bin/git` shim) in the
  ones on this Mac and posts the raw outputs to `POST …/repos/observed`, which refuses any undeclared path
  and parses them with the one parser, `repo_context.parse_snapshot` (a refusal is `denied`, and the card
  names Files and Folders). Only the last observation per `(path, device)` is kept —
  branch, dirty, ahead/behind, status, when — in `$CICADA_HOME/repos/<bank>.json`, **never in a bank**.
  `_state.md` renders that cache: `repos_probed_at` is the oldest observation shown, one older than 7
  days reads `state: stale`, and no time sits inside a block (R1). The MCP tool `cicada_repo_context`
  still probes live, in the process the agent harness launched.
- `sources:` (G61) — *where to look a fact up*, distinct from `source_episodes` (where a belief came
  from) and from the body's `## Links`. Keyed on `(ref, predicate)`, so one link can serve two facts.
  A conflict card's `hint` is **derived at read** from them (`fact_sources.served_hint` — the wire,
  the MCP render and the lexical row), never stored since G61 phase 2 S0, and its voice follows
  `added_by`: "You said …" only when the person added it; "Claude Code added …", "Cicada found …",
  "An agent found …" otherwise, the ref always in the sentence. An older item whose sources no longer
  match keeps its stored hint. Each entry is `{ref, kind: url|path|note|app|repo, predicate?, access?,
  added_by, added_at, accepted?, only_me?}` (phase 2 S1): `access` (`public|signed_in|local|unknown`)
  is stored only when stated, else inferred at read (`fact_sources.effective_access`: a refused or
  login host is `signed_in`, a path or repo `local`, an app `signed_in`); `accepted` marks an
  agent-found source the person took; `only_me` is the person's "Only I know" for one predicate —
  never a hint. The person's repeat of an entry applies those three; an agent's never changes one.
  Stage 5.56 attaches a URL found verbatim in a new Stage-1 claim's cited span as a source for that
  predicate (`added_by: <model>`, zero LLM) when the predicate's `locus:` is `world` or `artifact` —
  the vocabulary's where-the-truth-lives marking (seed + bank map, the most conservative winning:
  `person` > `artifact` > `world`; unseen is `unknown`). Nothing is fetched. An `addressbook://` ref reads
  'Their card in your Contacts (…)' (R-SR16), and the entity card names it "Their card in Contacts", the id only in
  the tooltip (DR-54).
  **A living set (G61 S3-a, 2026-09-30).** A page holds MANY sources, per fact, capped (`MAX_SOURCES` 30, `MAX_PER_PREDICATE`
  8; past a cap an agent's add is refused in words, the person's never is). `fact_sources.rank` is the one function every
  reader that must pick uses (the person's, then one they took or Cicada's read confirmed, then Cicada's, then an agent's;
  the owner's own page counts only what the person added or took); `source_trusted` is the trust rule. Three more optional
  keys on an entry: `origin: remote:<id>` (a connection's own entry — what ownership compares), `entity: <page id>` (the page
  that knows more about this source — its own memory node; validated, never creates a page, a stale id reads as none) and
  PR2's `verified`. **Ownership:** an agent (`cicada_change_source`) changes or removes ONLY an entry it added
  (`fact_sources.owns_source`); never the person's, one they took (`accepted`), an `only_me`, Cicada's own or a Sleep model's,
  and the unidentified `agent` label owns nothing; a connection owns exactly its `origin`, a local agent never a remote app's
  and the reverse. **Removal is remembered:** the entry leaves `sources:` and a row joins the page's `sources_removed:` (≤ 20,
  newest kept; `{ref, predicate?, by, at, reason?}`; git keeps the history, the row is what makes it stick; a replace
  (`new_ref`/`new_predicate`) tombstones the old key too). Today the writers that respect it are `attach_cited_urls`, `cicada_write_claim(sources=)`,
  `cicada_add_source` and Cicada's own DOI/skill-page adds (a refusal there never fails the page write); and (G61 S3-b) Stage 1's site proposal (`fact_sources.propose_site`) and the website backfill (`site_sources`).
  `website` matches by site. An agent's
  add (`cicada_add_source`, `write_claim(sources=)`) is refused what the person or Cicada removed but may put back what an
  agent removed, and the reply says who removed it and why; the person's add clears the tombstone, and the person's removal
  (`POST /entities/{id}/sources/change`, or the older index DELETE) writes one too. A ref the scrub would alter is REFUSED, not
  stored redacted. `entity_merge` carries `sources` and `sources_removed` to the winner and repoints other pages' `entity:`.
  `entity:` is filled for existing sources by exact match only (`source_links`: a URL whose `url_hash` is a saved page's, a path
  equal to a directory page's own frontmatter `path:` exactly — not a path found in its body), never over a set link or one the person
  or an agent explicitly cleared (`entity_unlinked: true`, stamped by an unlink, removed by a later link or replace), on the Sleep tail and `POST /maintenance/link-sources`, one
  `cicada`-authored commit (`Source links <date>`, triggers `sleep/source-links`, `maintenance/source-links`). The graph draws a
  linked source as a read-time edge labelled by its predicate (never persisted, like `has repo`; `kind: "source"` on the link,
  which the person map and "What's happening" skip — a source is where to look, not a relationship); the card's row wears the linked
  page's picture and offers "Open page ›". The person's three source routes answer 409 while Sleep runs; `cicada_add_source`
  is refused then too (it used to write uncommitted). A Contacts card row offers only Remove on the card.
- `website` (G61 S3-b) — the official-site ROLE: a `sources:` entry with `predicate: website`, many allowed. Stage 1 may
  propose ONE for a `company`, `tool` or `project` (an optional `website` field on the extracted entity;
  `site_sources.sanitize_website` keeps only an https origin of a public host that is not a platform (`PLATFORM_HOSTS`:
  code hosts, encyclopedias, social, profile and article hosts) or a walled one, and drops it for every other type); the
  create branch stores it UNVERIFIED (`added_by: agent`, no network), never over a tombstone. An engine-free backfill
  (`site_sources.candidates`) proposes one for a page that has none from ONLY its own current `website` claim or a
  `## Links` URL whose host is the page's own name (or whose title says official/homepage/website) — never a domain
  guessed from a name. Cicada's own read confirms it (`link_enrichment.fetch_identity`, sharing `_stream_html` with
  `default_fetch`: 4 s, ≤ 512 KB, no cookies, `net_guard`, a block never retried; a walled or platform host is refused
  before any request): `judge` needs the page's name (or an alias, company suffix aside, every word in any order) whole-word
  in the site's title or `og:site_name` AND two distinctive words of its own summary on the page. **The destructive
  outcome needs positive evidence:** `mismatch` (removed and remembered in `sources_removed`, by `cicada`) only when the
  name IS on a substantial page but two or more of the summary's words are not (the namesake); everything merely
  unproven — no name found, a thin JS shell, a redirect to another domain (the final page is judged), a 403/bot block or a
  consent page — is `unconfirmed`: kept with `checked: {outcome: unconfirmed}` ("not confirmed", re-read after 30 days,
  one tap of "Use this site" = `accepted` trusts it). `verified` stamps `verified: {at, how}` and `access: public`. A
  network failure is `tries` up to three nights, then `checked: {outcome: unreachable}` and asked again in 30 days —
  never tombstoned. A platform host found in a `website` entry is removed without a request (reason `platform`).
  `fact_sources.trusted` (the person's, one they took, or verified) is the only trust; nothing else draws a picture (and
  only a `company` or `tool` page draws one; a project's site is a source only). The
  Sleep tail step (`sleep_cycle._site_sources_safely`: propose, then verify, ≤ 25 fetches a night, one per site) runs
  behind `CICADA_ALLOW_CONNECTOR_FETCH`, in one path-scoped `cicada` commit `Site check <date>`, trigger
  `sleep/site-check`, no engine trailer, dirty pages skipped; the run's `Report` is built first and handed to both steps,
  so ANY failure restores every page written (the G85 smear), as does a failed commit. `verify` parses and writes off the
  event loop. `POST /maintenance/verify-sites` is the person's click (ungated, at most 40 fetches — the answer carries
  `budget` and `deferred` —, 409 while Sleep runs or in a demo bank, trigger `user/companion_app`), counts only.
- `logo:` — a domain hint for `logo_service`. Logos are cached under `$CICADA_HOME/logos/<bank>/`,
  **never inside a bank** — a logo is a derived artifact of the outside world, not versioned memory. Since G61 S3-b a
  page's domain comes from a source and never a guess: `logo:` first, else the first TRUSTED `website` source
  (`logo_service.domain_for`); no `## Links` fallback, no saved link's site, no `website` claim, no `<name>.com` guess,
  no platform or walled host, and never a `person` or `media` page (G146/G159). `LOGO_RULE = 2`: a bank's cache written
  under the older rule is purged ONCE (`ensure_rule`, marker `logos/<bank>/.rule`; `sites/` is spared), and a page that
  no longer resolves a domain drops its cached mark and records a miss (an explicit `website` entry outranks a bare link the person typed). `GET /entities/{id}/sources/icon/{site}` serves
  the mark of a trusted site THIS page lists (icon service only, keyed on the site, never a ref; never for a `person` or `media` page).
- `picture:` (G146) — the person's own choice of picture for a page: `{kind: upload, sha, ext, added}` for a
  picture they uploaded, whose bytes live **in the bank** at `assets/pictures/<id>.<png|jpg>` (their record, so it
  travels with the bank; the path is derived from the id, never read from the page), or `{kind: initials, added}`
  for "Use initials instead". Written only by `POST|DELETE /entities/{id}/picture` and `…/picture/initials`, each
  committed alone as `user`, 409 while Sleep runs; never by an agent. The app shrinks a picture to ≤ 512 px before
  it leaves the Mac; the server keeps only a PNG or JPEG ≤ 512 KB (no Pillow). `entity_picture.resolve` is the one
  precedence (the person's choice → a person's Contacts photo → a brand's logo → a media page's thumbnail → a ring
  monogram), resolved at read onto `/graph` nodes and the entity; the app's `EntityPictureResolver` is its twin over
  `api/tests/fixtures/entity_picture.json`. A person never gets a logo and no service is sent a person's name (G159).
- `contacts_photo:` (G154, read by G146) — `{sha, ext}` on a `person` page Contacts matched (`ext` jpg|png, jpg when
  absent); the thumbnail itself is a cache at `$CICADA_HOME/pictures/<bank>/contacts/<id>.<ext>`, never in a bank.
  Written by the Contacts sync only (`contacts_local.photo_path`, the same path `entity_picture.contacts_path` reads).
- `owner: true` (G117) — marks the one `person` page as the bank's owner; `owner_identity.
  resolve_observer` is what decides which page gets it, and every user-stated claim's `observer`
  field is that resolved value. **Every new bank starts with it** (`bank_registry.create_bank` →
  `owner_identity.seed_owner_page`, its own `cicada` commit; never the demo, which writes its
  own): the machine-level name from `owner.json` when one was saved (a name and an id, never
  another bank's knowledge), else a neutral `Owner` page (`owner_placeholder: true`, id `owner`,
  the id `resolve_observer` already answers with) opening "The main person this memory belongs
  to." `name` stays the plain name — Stage 2 matches a mention to a page by `name`, so a stored
  "(you)" would stop the person's own name from resolving — and the app renders "Name (you)" from
  the flag. `PUT /settings/owner` **adopts** a placeholder (renames it, keeps its id and claims)
  instead of writing a second owner page. Beliefs accrue through chats and consolidation. The
  first-boot default bank is scaffolded by the lifespan, not `create_bank`, so the lifespan seeds it
  the same way when it is brand new (`seed_owner_if_brand_new`: no entity page, no episode). Because
  a bank now starts with one node, **the app's empty means "no node but the owner's"**
  (`hasNoContentBeyondOwner`: `FirstRunGate`'s graph input, the Graph's and Clusters' "Nothing here
  yet"); the `/banks` `entityCount` of a new bank is 1.
- `kept_on:` (G147) — the days the person answered *keep* to a decay question; each joins the page's
  mention weeks, so a kept page fades a little slower. Written only by the decay resolver, deduped,
  capped at 52. Not an episode id and never read as one.
- `paths:` (G133) — on a `project` page a watched folder anchors: `[{path, device}]`, where that
  folder lives on which Mac. For display and relink only; the backend never opens it.
- `media.kind: paper` + `paper:` (G133) — a paper page: `arxiv_id`, `doi`, `authors`, `published`,
  `venue`, `sections`, and `metadata_status` once a lookup failed. The ids are the identity
  (`media-arxiv-<id>` / `media-doi-<hash>`); the abstract is a `describes` claim from
  `external:arxiv` or `external:crossref`, a dated cache shown under the personal tier (G121).
- On an episode (G133/G134): `turns` (the G118 per-turn sidecar), `evidence_kind`,
  `source_deleted_at`, and a section's `content_sha` — see the Awake rails.

### Backlogs (G150)

A project's backlog is memory, not a table in some repository: **one markdown file per item** at
`<bank>/backlog/<project-id>/<item-id>.md`. Frontmatter: `id`, `title` (the brief task), `project`, `status`
(`open | doing | done | dropped`), `triage` (`apply | research | decide`, optional), `paid` (the 💸 flag), `created` /
`updated` (the machine zone's days), `added_by` (`user` | a harness label | `cicada`), `session`, `links: [{kind:
pr|commit|url|doc|entity, ref}]`, `order` (hand-set), and last a `notes: [{at, by, session}]` sidecar. Body:
`## Description` (the reasoning) then `## Notes`, append-only `### <day> · <who>` entries — a status move is itself a
signed note, and a note is edited only through git history; any heading inside a text is demoted so it can never forge
a note. **Never an entity page**: Stage 1 never extracts one, it never decays, and the writer never touches
`entities/`. Ids are `<PREFIX><n>` like G-ids — the project page's `backlog_prefix:`, else the prefix most of its items
share (an imported G-row list continues its sequence), else the name's initials (`Orchard` → `ORC`) — max+1, claimed by
an exclusive create (the backend and every stdio MCP process mint in one folder). **One writer**,
`api/services/backlog.py`, behind every door: REST (`routers/backlog.py` — `GET/POST /projects/{id}/backlog`,
`POST /projects/{id}/backlog/import`, `GET/PATCH /backlog/{project}/{item}`, `POST /backlog/{project}/{item}/notes`;
409 while Sleep runs; each write commits alone as `Backlog update <day>`, `Cicada-Author: user`, trigger
`user/companion_app`, an import as `Backlog import <day>`, `user/backlog_import`), MCP (`cicada_backlog` read;
`cicada_add_backlog_item` and `cicada_add_backlog_note` record — the harness as author and the conversation as
`Cicada-Session:`, refused while Sleep runs and in a demo bank; a remote connection without `sources` is told the
person's own words exist, never shown them), the importer (`backlog_import.py`, `scripts/import-backlog.sh`: G-row
tables and `### G<n>` sections, ids and statuses kept, an id already filed skipped) and the demo. Every text is
scrubbed (writer `backlog`), and an open item whose title matches a new one exactly refuses the new one — one row per
idea, later findings are notes. Both reads ETag over the `backlog` sync component (a stat walk) and `entities`; neither
is a Store domain (`BacklogCache` in the app, like `ProjectsCache`). A note's model and effort are joined to its turn at
read once round 4's per-turn join lands; until then a note names its harness.

### Live state + handshake (G53 / G75)

**`<bank>/_state.md` is a *cursor* into the graph, never a copy of it** — YAML frontmatter plus a
short wikilinked body, ≤ 6 KB, zero LLM, deterministic. Written only by
`state_dictionary.refresh`. A digest of the `entities`/`inbox`/`episodes`/`bank`/`backlog` sync components is
stored as `inputs_version`; unchanged inputs mean no write. **Never `git_head`** — its own
`State snapshot` commit would self-invalidate.

Every regeneration that touches disk goes through `state_dictionary.refresh_and_commit`, which
commits `_state.md` ALONE (`commit_paths`, never `git add -A`) as `State snapshot <date>` /
`Cicada-Author: cicada`. **The read path commits too, on purpose:** a projection left dirty "for
Sleep's tail" gets swept into the next `git add -A` writer's commit under the wrong author — the
G85-class smear. `sleep.next_at` is computed per request, never persisted: in the file it advanced
every day and made every idle night commit.

**`_state.md` schema v3 (G141):** each of the top 7 project rows gains `next: {slug, name, target}`
and, once happenings exist, `now: {claim, text ≤ 80, since, verbatim?}` — the first claim text the
file holds; `verbatim` marks the person's own Log sentence, which a remote primer shows as 'a note of
yours' without `sources`. Neither field depends on today, and `_fit` drops every `now` before it
drops a project. **v4 (G150)** adds `backlog_open` (items open or doing) to a project row that has any, and
`backlog` joins the input components; the primer's Current row says "backlog: n open" under the same gate as
`now`/`next`. Contract item 3 names the backlog tools (CONTRACT_VERSION 8 with G149's item 8; each branch alone had taken 7).

**The handshake** (`api/services/handshake.py`) turns `_state.md` + a fixed contract into ≤ 1,800
tokens of primer: what Cicada is, a per-harness prelude (the contract never varies), the contract
itself, the now-view, and capability notes. The now-view is **Standing** — the person's page and
one-liner (through G117's resolver), their timezone (per request, never in `_state.md`, part of the
cache key), *How to work with me* (standing `skill` pages by confidence alone), long-standing
durable/evergreen pages — then **Current** — projects, each project with its `now`/`next` (G141),
pages in focus in the last 14 days, people, recent conversations (G140, schema v2). A test holds R12 for every argument either primer names, for
every remote scope set. Contract item 3 names `cicada_note_progress` (G141 PJ-3a; remotely only when the
connection holds it). Delivered four ways: the MCP `initialize` result's
`instructions` (which Claude Code truncates), the `cicada_handshake` tool, `GET /handshake`, and the
SessionStart hook's `additionalContext` under a "From Cicada" header (G149). Contract item 8 tells an
agent what a "From Cicada" note is. **R12: a primer naming an
argument the schema rejects is a bug** — every argument it names must exist in the tool schema.
`SKILL.md` points at the generated text rather than restating the contract — one prose source.

**A reader that finds `_state.md` stale or absent must still work:** every field has a live twin
(`/status`, `/inbox`, `/conversations/recent`, `cicada_repo_context`).

### sqlite-vec (vector index)
`api/services/vector_index.py`. Embeddings are **stored, not recomputed at query time**, so search
is one in-process ANN lookup. Default backend is EmbeddingGemma-300M (768-dim, on-device) with
asymmetric query/document prompts — in a developer checkout. A release app (G182) bundles the int8 ONNX export of
`intfloat/multilingual-e5-small` (384-dim, ~100 languages, `query: ` / `passage: ` prompts from its manifest, mean
pooling, no torch; owner 2026-10-06 chose it over the English-only `bge-small-en-v1.5`; `api/services/onnx_embedder.py`,
found through `CICADA_BUNDLED_MODELS`)
and a fresh bank there is built with it unless `CICADA_EMBEDDING_MODEL_LOCAL` names another; a bank built with it is
queried with it (the recorded model, as for every bank). **Each bank's vectors are built with its own model**
(`embedding_models.build_model`, G182 phase 3): the person's choice for that bank (Settings → Memory → Search model,
kept in `$CICADA_HOME/embedding-models.json`, outside every bank), else the model its index already records when this
Mac can run it and no `CICADA_EMBEDDING_*` was set explicitly, else the configured default — so a change of default
never silently re-embeds a bank, and an explicit setting keeps its old meaning. A bank whose recorded model this Mac
can't run is rebuilt with the default at its next sync — except one built with the larger model, which keeps its
vectors (search reads words) until the person installs it or picks another model (Settings says so). EmbeddingGemma is the optional larger model
in a release: `POST /embeddings/install` installs sentence-transformers and torch with the bundled pip into
`$CICADA_HOME/extras/site-packages` (exactly the hashed packages in `api/data/extras-requirements.lock`, at the
developer lock's versions, `--no-deps`; `sitecustomize` appends it after the bundled packages, so a shared one always
resolves to the bundled copy; a failed install leaves nothing behind) and downloads the model once with the person's own Hugging Face token, used for
that request only and never stored or logged; it then loads from its local folder (`$CICADA_HOME/models.json`). The index is **derived and disposable** — synced by Sleep from
markdown, safe to delete at any time. **The sync is incremental** (`SqliteVecIndexer._sync_kind`): each
row keeps a stable `key` and the `hash` of the text that was embedded, so a cycle embeds only new and
changed texts, removes deleted ones and refreshes a page's metadata in place without an embed; a missing
table, a pre-`hash` schema, another model (recorded per kind as `model:<kind>`) or another width rebuilds
that table in full, and an embed that fails leaves the previous index untouched. Sleep runs the blocking
sync through `asyncio.to_thread`, never on the event loop.
**A query is embedded with its table's model (audit 2026-10-05 P2-4).** The kinds are re-synced one after another, so
after a model switch one table can hold the new model's vectors and another the old one's; the bank-wide `model` stamp
only names whichever kind was rebuilt last. `_query_embed_fn(kind)` reads `model:<kind>` (falling back to the bank-wide
stamp on an index written before per-kind stamps); an injected embedder is used as given unless it names a different
model than the table's. `search_kinds` embeds once per model, and a short in-process cache (≤ 16 entries, 60 s, keyed by
the model, the table's width and a hash of the query — the text is never kept; emptied whenever a table is written) lets every search of one query share that embed: MCP
recall's entity and episode legs embed once (P2-8). **Entity hits are read against the page as it is now (P2-5):**
`search_entities` drops a hit whose page is gone or `dropped` — even with `include_archived` — and decides the archived
tier on the current status, not the last sync's copy.

### SQLite FTS5 (lexical index, G136)
`api/services/search_index.py`. One `search_index.db` per bank, **beside `vector_index.db` and never
inside it**: entity names + aliases + prose, every claim (superseded ones kept as history), episode
titles + 600-character passages that tile the evidence text exactly, media/paper metadata, inbox
questions and backlog items (G150), in seven per-kind FTS5 tables (`unicode61 remove_diacritics 2`, prefix `2 3 4`; rowid
`doc_id << 16 | n`). `dropped` pages are never indexed. **Derived and disposable** (TODO ruling 3):
deleting it costs a few seconds of CPU and never a fact; a missing, corrupt or schema-mismatched file is
rebuilt, never an error. **Never tracked:** `bank_registry.ensure_derived_excluded` writes
`.git/info/exclude` before the file first exists. It follows a worktree or submodule bank's `.git` file
to the real git dir, and a new bank's `.gitignore` lists the file too. It never edits an existing
`.gitignore`, which would dirty the tree and smear into the next `git add -A` commit. **Freshness:**
Sleep brings it up to date beside the vectors (`search_index.refresh`, off the event loop — the
stamp diff `ensure_fresh` uses, so an idle night re-indexes nothing; a full build only when the file is
missing, damaged or of another schema); every read path calls `ensure_fresh`, a `bank_index` stamp diff
(at most one check a second, inline up to 64 changed files, one background worker beyond); the
lifespan and a bank switch warm it in the background. The caller always passes the active bank's path
— the module never resolves a bank (the split-brain rule). `search_service` ranks over it (QuickMatch
tiers 0–2), fuses it with the stored vectors in `mode=hybrid`, and **never embeds in `mode=prefix`**.
**The query is never logged**: not by loguru, and not by uvicorn's access log (`api/main.py` strips the
query string of `/search` and `/conversations/recent`, G136 R22).

### Telemetry ledger (`~/.cicada/telemetry/`)
Append-only JSONL, machine-global, **never in a bank or git**. `CICADA_TELEMETRY=off` disables it.
**IDs and enums only — never claim text, query text or answer text.** The `read` kind (G124) records
an entity id and a surface enum, filed in a sibling `reads-*.jsonl` that
`sync_service.components["telemetry"]` deliberately does not stat — the app maps that component onto
its consumption domain, so a card open must not move it. The `hook_recall` kind (G149) is one row per
recall-hook firing: harness, event, reason enum, the page ids and their count, token and latency buckets,
and the model id when the harness sends one. It is filed beside `read` for the same reason, and like
`capture` it is a per-turn receipt that `consumption_stats._activity` keeps out of every Usage view. The
prompt never is. The `read_agent` kind (G166) is one row per `cicada_record_read` call — entity id, an `outcome` enum, a
`host_class` enum (`walled | public`), the harness and connector id; never a URL, the tool the agent named, a note or an
excerpt — filed beside `read` and kept out of every Usage view like `capture`. The `check_agent` kind (G61 S3) is one row per `cicada_record_check` — item id, entity id, `outcome`, `host_class`, `effect` (`noted | recommended`) enums, harness, connector id; never the source, its host, a quote or a proposed value — filed beside `read_agent`. The `video_queue` kind (G162) is one row per claim, release or completion — `action`, `count`, a
closed fail-code enum, the harness and connector ids; never a link, a title or a reason — filed beside `read` and kept
out of every Usage view (`SIBLING_KINDS`, `NON_SPEND_KINDS`, `PER_TURN_KINDS`).

**Cycle usage (2026-09-28 ruling, Sleep page only).** Every `llm_call` a Sleep cycle makes carries `refs.cycle_id`
(from the ambient `sleep:<id>` scope, so it survives `to_thread`/`gather`; the engine-independent tail runs outside
that scope and is never counted), and the cycle's `sleep_run` gains `usage_tagged: true` plus, when observed,
`plan: {connection, windows: [{window, before, after, resets_at, before_is_first_seen}]}` — numbers and enums only.
Claude's windows come from the calls' rate-limit signals (`before` is the value after the first call); the ChatGPT
plan's from two fresh app-server snapshots bracketing the cycle. `api/services/cycle_usage.py` derives `usage` for
`GET /sleep/history/{commit}` and `usageSummary` for `GET /sleep/history` at read, joined after the git cache; every
figure carries its basis (`charged` | `list` | `plan` | `free`), and a cycle without the marker reads `null`, never zero.
The Sleep page's Details (Last cycle, Past nights, an opened cycle's Models) and the engine menu's captions read them
(2026-09-28 ruling); a `plan` block and a `cycle_id` are numbers and ids, never text.
Since Sleep page v5 a drain's calls also carry `refs.drain_id` (the run's id, ids only), so `GET /sleep/runs/{id}` sums a whole run — a paused or discarded batch's calls included — and `sleep_run` rows carry `drain_id`/`batch`/`batches`; `usage_for_drain` lists a plan window at the run level only when every batch saw the same reset time.

**Feedback events (G113):** every inbox resolution emits a `resolution` event (`stage: feedback`,
`refs` = item id, kind, predicate, entity id, action label, `verdict: agreed|overruled|neutral`,
winner/loser claim ids, the extractor's confidence and model — ids and enums only, never claim
text), Stage-3 reconcile emits one `audit` event per supersede/reject, and the dedup sweep emits one
`dedup_verdict` per judged pair. `telemetry.FEEDBACK_KINDS` names the three (a superset,
`NON_SPEND_KINDS`, also excludes `capture`/`handshake`/`read`); `consumption_stats.stats()` excludes
them from `by_connection` so they never show as an "unknown" connection. Nothing learned from the
ledger is auto-applied — `GET /consumption/feedback` shows the rates; feeding them back into
prompts is G78.

### Git — versioning and provenance

Every Sleep cycle commits with a **machine-parseable message**:

```
Sleep cycle 2026-03-20

entities/recruiting-thread.md: updated (source: ep_2026-03-20_002, trigger: sleep/extraction)
nudges/nudge_005.md: resolved (trigger: user/companion_app)

Cicada-Author: gpt-5.4-mini
Cicada-Engine: claude-cli
Cicada-Session: <id>
```

**Triggers:** `sleep/extraction`, `sleep/promotion`, `sleep/conflict_resolution`, `sleep/decay`,
`sleep/state`, `sleep/expiry`, `sleep/followup`, `sleep/source-links`, `maintenance/source-links`, `sleep/site-check`, `capture/calendar`, `capture/tab-groups`, `capture/contacts`, `nudge/resolved`, `clarification/resolved`, `user/manual_edit`,
`user/companion_app` (also the Projects page's writes, G141 — `Project update <date>`,
`Cicada-Author: user` — and the Backlog section's, `Backlog update <date>`), `user/backlog_import` (G150's
importer),
`mcp/<harness>` (a local agent's write), `remote/<harness>` (a remote connector's write, G135).

**Three trailer families, all inert to entity-line parsing — extend them, don't break them:**

- **`Cicada-Author:`** — *which agent authored this*. A model id for agent writes, **a harness
  label** (`claude-code`, `claude-web`, `chatgpt`, …; `agent` when none was sent) for a write that
  arrived through MCP, where the model is not disclosed (G135; the trailer never names a model — since round 4 it is joined at read from the captured
  turn), the
  literal **`user`** for manual/companion-app writes, **`unknown`** for legacy untrailered commits,
  and **`cicada`** for system maintenance with no model and no user in the loop (the one-shot
  migrations, the split-out decay commit, the `State snapshot` commit, the `Expiry` and `Follow-ups` commits). Built by
  `git_service.build_commit_message(...)`, parsed by `_parse_authors`.
  `git_service.author_identity` buckets a harness label (and `agent`) as kind `harness`, which the app
  names and marks as that app; the pre-G135 `mcp-agentic-write` claim placeholder reads as `agent`
  through `canonical_author`, never rewritten (F2-back R-B9, R-B10). A read whose body carries an
  author kind folds `git_service.AUTHOR_SHAPE` into its ETag; bump it when the buckets move.
  Powers `GET /contributors`.
- **`Cicada-Engine:`** — exactly one per main commit (`claude-cli|ollama|litellm`), **omitted
  entirely rather than guessed** when no LLM ran. Read back via git's own
  `%(trailers:key=…,valueonly)` directive, not a Python parse of `%b` — pulling the whole body to
  extract one line grew the endpoint from 787 B to 378 KB for 8 commits on the live bank.
- **`Cicada-Session:`** — one line per distinct conversation consolidated, capped at
  `MAX_SESSION_TRAILERS` (50) by the call site, not the builder. User-action commits stay
  session-less.

**G85 — decay gets its own `cicada`-authored commit.** Temporal decay runs over entities a cycle
never referenced: no LLM, no source episode, pure arithmetic. Folding it into the main commit
stamped it with whichever model happened to run Stage 1/2, inflating that model's contributor counts
for work it never did. `_finalize` splits `sleep/decay` entity lines into their own commit —
`Sleep cycle <date> (decay)`, `Cicada-Author: cicada` — committed *before* the main commit so the
main commit's `git status` scan never sees them. A split that can't happen degrades back to the old
behavior rather than aborting the cycle. **Known asymmetry, disclosed not fixed:** the split is
path-granular, not hunk-granular, so a subject that is both decay-eligible and claim-touched in the
same cycle lands whole in the `cicada` commit. Narrow in practice; fixing it needs hunk-level
staging.

**A drain's commits.** Each batch is one `Sleep cycle <date> (batch k of n)` commit (k counts batches actually run, n is
recomputed from what is still waiting, so skipped ids shrink it; a lone batch keeps the plain subject — `_cycle_kind` reads
only a trailing `(decay)`). Its manifest lists only that batch's episodes, `Cicada-Session:` only that batch's
conversations (batch size ≤ 50 keeps every one), `Cicada-Author:` the models that batch used. The `(decay)` commit exists
once, in the last batch, before its main commit.

**One git writer per bank (F2-back R-B1 … R-B4).** Every mutating git command — `git_service`'s
commits, a `_run_git` write, the one-shot migrations, the expiry restore — runs in a worker thread
under one re-entrant lock per resolved bank path, so tasks, threads and `asyncio.run` bridges queue
instead of colliding on `index.lock`; the backend is one process, git's own lock is the cross-process
guard, and only its `File exists` refusal is retried (five tries, the lock never deleted). Reads pass
`GIT_OPTIONAL_LOCKS=0`, and `test_git_write_lock.py` refuses a git write spawned anywhere else.
A folder, paper or Wispr commit that still fails keeps its paths in `cicada-pending-commits.json`
in the bank's own git dir (a worktree's, never the shared common dir), says so on its channel, and
lands on that writer's next run — or at the start of the next Sleep cycle, before any stage writes —
under its own author (R-B5).

**One page writer at a time (audit 2026-10-05 P1-2).** A claim write is read → reconcile → write; atomic replacement
keeps one write whole but not two (both reported `written`, one survived). `page_lock.page_lock(bank)` — the same
cross-process, re-entrant `flock` as `episode_lock` (`episode_ids.dir_lock`), on the bank directory itself — is held
by `agentic_write.write_claim`/`retract_claim`, `progress`'s event writers, `fact_sources`' source writers and
`paper_metadata`'s page updates, the dedup sweep's merges (each across its commit), the app's decay-class and
repo-link rewrites, and by the MCP's page-writing tools (`write_claim`, `retract_claim`, `note_progress`,
`add_source`, `change_source`, `record_check`, `record_read`, and `record_watch` around its record) across the write
**and its commit**. Nothing waits on a network call under it: such a tool asks Sleep before it takes the lock and
reuses the answer, and `record_watch`'s link save and queue credit stay outside. Some holders are `async` routes and
the inbox's follow-up resolver, which wait on the event loop — one page operation is milliseconds. **Order:** the page
lock, then the git write lock (inside the commit), then `episode_lock` — never the reverse. **Not under it yet:**
Sleep's own page writes (agent commits already defer to its write window) and the inbox's other resolvers.

**Entity-level provenance uses `git blame`** enriched with parsed commit metadata; repo-level
history uses `git log`. **No changelog in frontmatter** — git handles all history, zero storage
overhead, no growing fields.

---
