# Decay classes + commit-diff views (G66, G67)

**Status:** approved 2026-08-31 (Rodrigo: "I don't see why bookmarks would need to get decayed… maybe the agent gives the thing a decay estimate, unlimited as an option"; "commit history to a memory node… check what lines were removed and added, like the diff — also from the git history of contributions").
**Grounding:** the 2026-08-31 audit workflow's decay-pipeline and history-diff tracers (verified against code + the live bank).

## 1. Decay classes (G66)

### 1.1 Why
Decay models "absence of mention is a signal" for *beliefs about a life*. A bookmark is an
*artifact*, not a belief — it doesn't become less true by going unmentioned. Today `decay_rate`
is a hardcoded per-writer literal (0.05 extracted, 0.03 media, 0.02 skills) that no agent
reasons about and no user can change; two decay engines exist and the claim engine ignores
`decay_rate` entirely. Verified: `decay_rate = 0.0` is mechanically safe everywhere (nothing
divides; `exp(0)=1`; a 0-rate entity never decay-nudges or archives via the entity engine).

### 1.2 Vocabulary
`DecayClass` enum in `api/models/schemas.py`: `evergreen | durable | active | volatile` with
`DECAY_CLASS_RATES = {evergreen: 0.0, durable: 0.02, active: 0.05, volatile: 0.15}` and claim
multipliers `{evergreen: 0.0, durable: 0.5, active: 1.0, volatile: 2.0}`. Frontmatter gains
`decay_class:` beside the numeric `decay_rate` (kept for back-compat; an explicit numeric that
differs from the class map wins, the class stays as label). `EntityResponse.decay_class`
(camelCase `decayClass`) additive on the wire; graph nodes carry it too (additive, folded into
`content_hash`).

### 1.3 One resolver — `api/services/decay_policy.py`
- `resolve(fm) -> (DecayClass, float)`: explicit class wins; legacy inference: `type: media` →
  evergreen, `type: skill` → durable, else active with the page's existing rate (default 0.05).
- `default_class_for(entity_type, source)`: ingest writers (bookmark/media/RSS/PDF paths) →
  evergreen; skill → durable; everything else → active. `volatile` is assigned only when Stage-1
  explicitly says so.
- **Anti-pollution rail (mirrors `PRODUCIBLE_ENTITY_TYPES`): Stage-1 extraction may emit
  `durable|active|volatile` but NEVER `evergreen`.** Evergreen is reserved for ingest writers
  and the user, so an over-eager extractor can never stop the graph from archiving.

### 1.4 Agent-estimated decay (the "agent gives the estimate" half)
`entity_extractor` Stage-1 JSON schema gains optional `decay_class` with one prompt paragraph:
*volatile* = a fact you expect to change within weeks (role, status, current focus); *durable* =
a stable preference, skill, or long-lived concept; *active* = everything else; never evergreen.
Invalid values silently dropped. All hardcoded literals (media_ingestor ~1054,
conflict_resolver create ~204, inbox_generator skills ~262, agentic_write ~176,
inbox_service ~601, routers/entities ~69) go through the resolver.

### 1.5 Both engines honor it
- Entity engine (`conflict_resolver.resolve_and_prune`): rate from `resolve(fm)`; evergreen
  entities are skipped outright (no decay math, no decay nudges, never auto-archived).
- Claim engine (`claim_reconciler._decay_claims`): per-claim decay multiplied by
  `claim_multiplier(subject's class)` via an injected class-lookup fn (evergreen subject → 0.0).

### 1.6 Recovery (the missing half of "time as a signal")
On re-mention (`conflict_resolver` update branch), a `decaying`/`archived` entity is **promoted
back**: `status = active`, `confidence = max(current, 0.6)` — CLAUDE.md already promises this
("if mentioned again: promoted back, confidence restored"); today only `last_referenced` moves.

### 1.7 User override + UI honesty
- `PUT /entities/{id}/decay` `{class}` (validated; writes class + mapped rate; commit
  `user/companion_app`, `Cicada-Author: user`).
- `EntityDetailCard` frontmatter strip shows a decay chip — "evergreen · never fades",
  "durable · fades slowly", "active", "volatile · expected to change" — with a small picker
  (menu) wired to the PUT; raw `decay_rate` no longer rendered bare.

### 1.8 Migration (one-shot, startup, author `cicada`, trigger `maintenance/decay_class_backfill`)
All `type: media` entities → `decay_class: evergreen`, `decay_rate: 0.0`, and any of them
`decaying/archived` (not `dropped`) restored to `active` with `confidence = max(current, 0.7)`;
`type: skill` → `durable` (rate stays 0.02). Idempotent marker like the inbox dedup migration.
Live bank today: 602 media (601 active), 10 skills.

### 1.9 Interactions checked
Feed relevance for evergreen becomes flat `confidence × 1.0` — acceptable: the badge already
hides when rendered percentages are uniform (PR #16), and real query relevance is G65(c).
Decay inbox nudges can no longer fire for bookmarks. Graph fading (`STATUS_ALPHA`) untouched —
evergreen entities simply stay `active`.

## 2. Commit-diff views (G67)

### 2.1 What exists (verified live)
`GET /entities/{id}/history` (blame-enriched commits, `author`, `commitHash`; `?include_diff`)
and `GET /entities/{id}/history/{commit}/diff` → `{added, removed, truncated}` are shipped and
working. The app renders history rows statically — no tap target; Contributors shows per-author
aggregates with nothing clickable.

### 2.2 Backend (one new endpoint)
- `schemas.py`: `ContributorCommit {commit_hash, date, subject, entities: [str], files_changed}`;
  `ContributorCommitsResponse {author, commits}`.
- `git_service.get_contributor_commits(memory_path, author, limit=50)`: reuse the NUL-record
  `git log` + `_parse_authors` plumbing from `get_contributors`; keep commits whose trailers
  include `author` ("unknown" = no trailer); `entities` from `diff-tree --name-only` paths under
  `entities/*.md`.
- `GET /contributors/commits?author=&limit=50` (author is a QUERY param — model ids contain
  slashes). On-demand; no ETag/Store domain.

### 2.3 App
- **Entity history**: each commit row in `EntityDetailCard`'s History tab becomes a `Button`;
  tap expands an inline GitHub-style diff — added lines green/removed red on tinted backgrounds,
  monospaced, `+`/`−` gutters, `truncated` notice — fetched on demand from
  `/entities/{id}/history/{commit}/diff`, cached per `(entityId, commit)` in the view model.
  One shared `DiffView` component + a pure `DiffModel` (testable).
- **Contributors click-through**: a contributor row expands to their recent commits
  (`/contributors/commits`); each commit lists its touched entities as chips; tapping an entity
  chip shows the same `DiffView` for that entity at that commit. Loading/empty/error states
  per the state-coverage rules.

## 3. Testing
Pytest: resolver precedence + legacy inference; evergreen rail (extractor payload with
`evergreen` dropped); both engines honoring class (evergreen skipped, volatile ×2); recovery
promotion; migration idempotence + counts; `PUT /decay`; `get_contributor_commits` trailer
filtering + entity extraction; router param handling. Swift: `DiffModel` parsing/coloring;
history-row expansion state; contributor commits decoding; decay chip picker wiring over the
fake transport. Live: MongoDB entity shows tappable history with a real diff; a bookmark shows
"evergreen"; migration log on the real bank.
