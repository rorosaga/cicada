# Round 4 — Frequency-aware decay (G147) — Implementation Plan

> **For agentic workers:** execute the tasks in order, one reviewable commit each. Steps use
> checkbox (`- [ ]`) syntax. Every task is TDD: failing test → implement → green → full suite →
> commit. No subagents.

**Goal:** Decay stops being a flat per-class weekly rate. A page that came up across many
*distinct weeks* fades more slowly than one heard in a single burst (the spacing effect), a
decay question's "keep" answer counts as one more such week, claims fade the same way, and the
person can approve a per-type pace that Cicada proposes from their own "Still tracking…?"
answers (Settings → Memory: "You kept 9 of the 10 people Cicada asked about. Let people fade
more slowly?" Apply · Not now). The entity card says the real pace in words ("Slowly —
mentioned across 12 weeks"), and CLAUDE.md finally describes the rule the code runs.

**Owner approval:** Rodrigo 2026-09-24, on the proposed fix: "ok i like the fix you propose so
please go ahead and work on that".

**Architecture:** One pure policy function, `decay_policy.effective(fm, …)`, computes a page's
weekly rate as **base × f(w) × type pace** — base from G66's resolver (class rate, or an
explicit `decay_rate:`), `w` the number of distinct ISO weeks among the page's `source_episodes`
dates plus its `kept_on` dates, `f(w) = max(floor, 1 / (1 + α·ln w))`, and the type pace from
`<bank>/_decay_tuning.yaml`. The Stage-3 entity pass and `GET /entities/{id}`'s derived `decay`
block both call it, so the card can never describe a pace Sleep does not charge. The claim engine
multiplies its existing amount by `f(w_claim)` and the subject's type pace through one memoised
`subject_lookup`. Suggestions are derived at read from the bank's own git history of decay
answers (`inbox/decay/resolved:<label>`, G113 R1) — never the telemetry ledger, never applied
without the person. Nothing about the pass's safety rails moves: the one-week cap per cycle, the
`decayed_through` watermark, the 0.2 / 0.4 thresholds, `RECOVERY_CONFIDENCE`, and G85's
`cicada`-authored decay commit are untouched. Nothing stored is migrated: the factor is derived
every cycle.

**Tech Stack:** Python 3 / FastAPI / Pydantic (`api/`), SwiftUI + XCTest (`app/CicadaApp`),
markdown + git bank.

**Backlog rows:** **G147** (new, this track), **G66** (decay classes — becomes the *base*),
**G85** (its defect (3) "rate ignores establishedness" is what this answers), **G113** (decay
verdicts become the first signal Cicada proposes from), **G78** (nothing learned is
auto-applied), **G148** (the memory benchmark pass — merged to `dev` at `ed6055f`, after this
branch's base, so its row is not in this worktree; it does not yet list a confidence-in-ranking
measurement, so this track records that as a question *for* G148 and changes no ranking).
**Round-4 contracts C1–C7:** this track changes none of their shapes and consumes none of them.

**Critic check (2026-09-24):** every task's code below was applied verbatim to a scratch copy of
`ecb59c7` (tracked files only, never this worktree) and run: backend **3837 passed, 1 skipped**
(3775 + 62 new), Swift build clean and **2020 tests, 0 failures** (2003 + 17 new). Two defects
it found are fixed in the code below (the empty-HEAD cache in Task 2, the cwd read in Task 3),
each with a test that fails without the fix.

---

## What the code actually does today (verified against `feat/r4-decay` @ `ecb59c7`)

**The entity pass — flat rate, the claim in CLAUDE.md is false.**
- `api/services/conflict_resolver.py:145` — `now = now or datetime.now()`; the loop over
  unreferenced entities starts at `:152`.
- `:168` — `decay_class, decay_rate = decay_policy.resolve(fm)`; `:169-172` skip evergreen.
- `:182-185` — baseline is `max(last_referenced, decayed_through)` (TODO ruling 1).
- `:186-199` — `decay_amount = decay_rate` (fallback, `:188`) or
  `decay_rate * (charged_days / 7.0)` (`:196`) with `charged_days = min(days_since, 7)`.
  **Nothing reads `source_episodes`** — a page with 50 episodes over 50 weeks and a page with two
  episodes on one day fade identically.
- `:201` — `new_confidence = max(0.0, confidence - decay_amount)`; `:203` archive `< 0.2`,
  `:213` nudge `< 0.4`, else `decay`. `:21` `RECOVERY_CONFIDENCE = 0.6`, `:33`
  `MAX_DECAY_DAYS_PER_CYCLE = 7`.
- `CLAUDE.md:245-249` says Sleep "drops confidence proportional to how frequently it *used* to be
  referenced" and "Below 0.2 → `archive/`". Neither is true: the rate ignores frequency, and an
  archived page stays in `entities/` with `status: archived` (`conflict_resolver.apply_changes`
  `:389-400` rewrites the same file; no code moves pages to an `archive/` directory).
- Recall does **not** rank by confidence: `api/services/search_service.py:263` sorts by
  `(status == "archived", -score, …)` and `:348` pushes archived pages last. Confidence is shown,
  never weighed.

**The resolver.**
- `api/services/decay_policy.py:103-120` `resolve(fm)` → `(class, rate)`; `:44`
  `DEFAULT_RATE = 0.05`; `:85` `claim_multiplier`; `:133-156` `class_lookup(memory_path)` — a
  memoised `entity_id → DecayClass` reader injected into the claim engine.
- `api/models/schemas.py:80-96` `DECAY_CLASS_RATES` (0 / 0.02 / 0.05 / 0.15) and
  `CLAIM_DECAY_MULTIPLIERS` (0 / 0.5 / 1 / 2).
- `api/config.py:169-170` `decay_nudge_threshold = 0.4`, `archive_threshold = 0.2`.
- `api/services/episode_ids.py:36` `EPISODE_ID_RE = ^ep_(\d{4}-\d{2}-\d{2})_(\d+)$`, `:39`
  `parse_episode_id` — every writer mints this shape (G114), so an episode id carries its date.

**The claim pass.**
- `api/services/claim_reconciler.py:47` `DecayClassFn`; `:529-537` `reconcile_stage3(…,
  decay_class_fn=None)`; `:564-565` default `decay_policy.class_lookup(memory_path)`; `:639`
  calls `_decay_claims(reconciled, referenced_subjects, settings, nudges, today, decay_class_fn)`.
- `:663-736` `_decay_claims`: `:678` one class multiplier per subject; `:686-687` base by
  epistemic × `source_trust` factor; `:700` `amount = base * factor * multiplier *
  (charged_days / 7.0)`. It reads nothing about how often the claim was restated.
- What a claim already records (`api/services/claims.py:124-200`): `source_episodes` (`:148`),
  `session_id` / `session_ids` (`:162`, `:171` — every session that wrote or reinforced it, but a
  session id carries **no date**), `evidence: [Evidence]` (`:182`, each with an `episode`
  document id — `ep_*` for a conversation, an entity id for a `page` span), `recorded_at`
  (`:147`, which `_reinforce` **overwrites** on a restatement that carries one,
  `claim_reconciler.py:153-154`). `_reinforce` (`:148-181`) merges `source_episodes`,
  `session_ids` and `evidence` — so episode ids and evidence documents are the dated record of
  every restatement.
- Other callers of `reconcile_stage3`: `claim_pipeline.py:340` (Sleep, real `Settings`),
  `agentic_write.py:507` and `progress.py:323` (one referenced subject each — the decay loop
  `continue`s before reading anything).

**"Keep" today.**
- `api/services/inbox_service.py:965-1031` `_resolve_decay`; the keep branch `:977-1008` sets
  `status: active`, `confidence = max(conf, 0.6)`, `last_referenced = today` (`:983`) and
  re-opens/raises the nudge's claim. **It records nothing that says the person kept it.**
- `:473` the G113 verdict map (`archive` → agreed, `keep_active` → overruled); `:855-903` the
  resolve flow; `git_service.commit_resolution` (`api/services/git_service.py:1345-1389`) writes
  `entities/<id>.md: status active|archived (trigger: inbox/decay/resolved:keep_active|archive)`
  under the subject `Inbox resolution (decay) <date>`, `Cicada-Author: user` (pinned by
  `api/tests/test_inbox_resolution_provenance.py:140, 152`). A `remind_later` is a deferral
  (`inbox/deferred`, `:935-962`), never a verdict. The MCP `cicada_resolve_inbox` path and the
  deprecated `routers/nudges.py:42` both go through the same `inbox_service.resolve`.

**The wire and the app.**
- `api/routers/entities.py:61-95` `get_entity` builds the one `EntityResponse` (`:76`); no ETag.
  `schemas.py:453-481` `EntityResponse` carries `decay_rate` (the resolver's base) and
  `decay_class`.
- The app memoises entity bodies in memory only (`Sync/Store.swift:578-617`, LRU of 200,
  `invalidateEntity` / `invalidateAllEntities`) — no disk cache, no `VersionVector` mapping.
- `Models/Entity.swift:637-720` `Entity` (custom `init(from:)`, `:702` CodingKeys, `:718`
  lenient `decayClass`). `Models/EntityPresentation.swift:212-225` `DetailsWords.fades(_:)`.
- `Views/Graph/EntityDetailCard.swift:610-613` the Details "Fades" `GridRow`; `:646`
  `shownDecayClass`; `:648-669` `fadesMenu` whose label is the **class** word only
  (`DetailsWords.fades(shownDecayClass)`); `:671-683` the optimistic override PUT.
- `Views/Settings/MemoryView.swift` — one group card (search index, link previews).
  `SettingsRowID.swift:55-56` Memory's two static ids; `SettingsIndex.swift:76, 109-110` their
  index entries; `SettingsRowLintTests` requires each static id rendered exactly once.
- `Theme/Copy+Settings.swift:152-161` the Memory copy block. `Services/APIClient.swift:2109`
  `fetchSearchIndexStatus` (the not-a-Store-domain precedent); `:2264` `put(_:body:)` serialises
  `[String: Any]` with `JSONSerialization` (so a JSON `null` is `NSNull()`).
- `Views/Common/NeutralButton.swift:8`, `TextButton.swift:5` — DR-40's buttons.
  `Tests/CicadaAppTests/CountLiteralLintTests.swift:40-59` the count-lint scope list.

**Baselines on this base:** backend `3775 passed, 1 skipped`; Swift `2003 tests, 0 failures`;
graph JS 8/8.

---

## Global Constraints

- Work ONLY in `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay` (branch
  `feat/r4-decay`, based on `dev` @ `ecb59c7`). Every shell command is
  `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay && <cmd>` with the absolute
  path (zoxide hijacks relative `cd`; ignore its stderr warning). No unquoted
  `--include=*.ext` (zsh globs it).
- NEVER read `<repo>/memory` (any bank), `~/.cicada`, `~/Library/Safari` or
  `~/.claude/projects`. Fixtures are synthetic: `alpha-project`, `bob-example`, `person-01…`,
  `example.com`.
- Python: `api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`; the full
  `api/tests` must report **0 failures**. If
  `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit`
  is the ONLY red, re-run it alone and report both results. Anything else red is yours. If a
  pre-existing test asserts an exact decayed confidence on a page or claim whose episodes span
  **two or more ISO weeks**, update the expected number to the spaced value with a comment citing
  G147 — never loosen the assertion. (Survey at `ecb59c7`: every existing decay fixture uses
  `source_episodes: []`, so none is expected.)
- Swift: `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay/app/CicadaApp && swift build 2>&1 | tail -5` must succeed and
  `swift test 2>&1 | tail -20` must report **0 failures**. SleepViewModelTests poll tests and the
  search-latency tests can flake under load — re-run alone before calling them yours. SourceKit
  diagnostics naming OTHER worktrees are noise. Graph JS: `node --test
  app/CicadaApp/Tests/graph/*.test.js` (untouched by this track; must stay 8/8).
- NEVER run `make dev`, `make install-app`, `swift run`, or launch/kill the app or the launchd
  backend — the owner's installed app is live; the orchestrator installs and live-checks.
- Never `git add -A`; stage named files only. Never commit `memory/`, `logs/`,
  `.claude/settings.json`, `api/.venv`, or `*-report.md`. No push, no branches, no worktrees.
  Ignore Devin/PR comments. Each commit message cites **G147** (and, for UI tasks, the DR ids it
  applies) and ends with the attribution lines your harness supplies.
- **Rails** (CLAUDE.md): no LLM anywhere in this track (decay is arithmetic, suggestions are
  counts); every read path engine-free; the bank file is committed alone with `commit_paths` as
  `Cicada-Author: user`, never `git add -A`; telemetry is not read (the ledger is never
  auto-applied, G78/G113); privacy — docs carry no owner or bank content; portability — no owner
  name, no author-machine path in code, docs or commits.
- **UI:** Direction D (`docs/design/DESIGN_RULES.md`). Fonts through `CicadaTheme` tokens (the
  font lint), counts through `UsageFormat.count` (DR-21, the count lint), buttons from DR-40's
  four kinds, no accent use outside DR-5's six, no prices/tokens/"%" in copy (DR-59). Copy is
  plain for a non-technical person.
- **Minimise conflict with the parallel round-4 entity-card track:** the only
  `EntityDetailCard.swift` change here is the Fades menu's label (Task 4). Do not restructure
  the card.
- Docstrings explain **why**, citing G147 / the ruling id / the row that motivated a rule —
  match the density of the file you touch.
- Line numbers above are from `ecb59c7` and drift as tasks land — read the cited code before
  editing.

---

## Rulings (binding)

Everything below is a choice the brief left open, decided here so no task re-opens it.

- **R-FD1 — the curve is `f(w) = max(0.25, 1 / (1 + 0.6·ln w))`, with `f(w ≤ 1) = 1`.**
  `α = 0.6` and floor `0.25` become `Settings.decay_spacing_alpha` /
  `decay_spacing_floor` (`CICADA_DECAY_SPACING_ALPHA` / `…_FLOOR`), mirrored as
  `decay_policy.SPACING_ALPHA` / `SPACING_FLOOR`, clamped by `spacing_params` to
  `α ∈ [0, 5]`, `floor ∈ [0.05, 1]` (a mis-set env var must never freeze decay — a floor of 0
  would make every well-mentioned page effectively evergreen, the class the anti-pollution rail
  reserves for ingest writers and the person). Factor values: f(2) 0.706 · f(4) 0.546 ·
  f(12) 0.401 · f(52) 0.297 · floor reached at w ≈ 148.

  **Weeks of silence to the decay question (conf < 0.4) / to archive (< 0.2), from the
  recovery floor 0.6, one cycle a week** — the numbers this ruling records:

  | Class (base/wk) | w = 1 | w = 2 | w = 4 | w = 12 | w = 52 |
  |---|---|---|---|---|---|
  | `durable` (0.02) | 10.0 / 20.0 | 14.2 / 28.3 | 18.3 / 36.6 | 24.9 / 49.8 | 33.7 / 67.4 |
  | `active` (0.05) | 4.0 / 8.0 | 5.7 / 11.3 | 7.3 / 14.7 | 10.0 / 19.9 | 13.5 / 27.0 |
  | `volatile` (0.15) | 1.3 / 2.7 | 1.9 / 3.8 | 2.4 / 4.9 | 3.3 / 6.6 | 4.5 / 9.0 |

  **Why 0.6 and not the alternatives measured beside it:** at `α = 1.0` the floor is reached at
  w ≈ 20, so five months of mentions and five years look identical — the same flattening this
  row exists to remove; at `α = 0.3` a page mentioned in 52 different weeks is still asked about
  after 8.7 silent weeks, barely twice a one-week page's 4. `α = 0.6` keeps rewarding spacing
  across a bank's whole realistic life (floor near 3 years) while a year of weekly mentions
  earns about a quarter-year of silence before the question. Revisit only on the grounded
  signal: if G147's own suggestions (R-FD6) keep proposing "slower" for most types, the curve is
  too steep a default — re-tune α then, not by argument.
- **R-FD2 — frequency is counted in distinct ISO weeks, never mentions or conversations.** The
  week key is `date.isocalendar()` (`YYYY-Www`), so the year boundary is the calendar's
  (2025-12-29 and 2026-01-04 are one week). An episode id that does not parse as
  `ep_<date>_<n>` (or parses to an impossible date) is still a mention, so all such ids together
  count **once** as an `unknown` week — bounded inflation, never zero credit. No episodes and no
  keeps → `w = 0` → `f = 1`: exactly today's behaviour. A malformed scalar `source_episodes:`
  is one id, never iterated character by character. **Known undercount, disclosed:** an id
  carries the day it was *minted*, so an episode rewritten in place — a resumed session's one
  Stop-hook episode (G104), a G20 source-keyed document edited later — counts its first week
  only, however many weeks it later grew across. Reading each episode's `turns` sidecar per page
  per cycle would put episode reads into every Stage-3 pass; the undercount only ever errs
  toward today's (faster) pace.
- **R-FD3 — "keep" is recorded as a date in a new frontmatter key, `kept_on:`.** Not an entry in
  `source_episodes` — every reader of that list (provenance, conversations, `session_stats`)
  treats its entries as episode ids — and not re-derived from git history each cycle, which
  would put a subprocess in every Stage-3 pass and tie the decay rule to the shape of history.
  Dates, not a counter: `mention_weeks` unions them with the episode weeks, so a keep in a week
  that already has a mention is not double-counted (in practice a keep always lands in a silent
  week — the question only exists after weeks of silence). Deduped, capped at the last 52 (a
  year of weekly keeps), written only by the decay resolver's keep branch. `archive` writes
  nothing. `last_referenced`, status and confidence behave exactly as today. **Known asymmetry,
  disclosed not fixed:** a merge (`entity_merge._LIST_FIELDS` = `source_episodes`, `tags`,
  `related`, `aliases`) unions the absorbed page's episodes but not its `kept_on`, so the
  survivor keeps only its own keeps — the absorbed page's episode weeks already carry most of
  its history, and widening the merge is outside this track.
- **R-FD4 — a claim's weeks come from what it already records; no new claim field.**
  `w_claim` = distinct ISO weeks among `source_episodes` ∪ the `ep_*` documents in `evidence`
  (a `page` span cites an entity id — not a conversation, not counted) ∪ the subject page's
  `kept_on`. **Session ids never count:** they carry no date, and mapping one to a date would
  mean reading capture episodes per claim per cycle. **`recorded_at` never counts:** `_reinforce`
  overwrites it, and a Sleep run the day after a Sunday episode would add a phantom second week
  (a 30 % slowdown for a single mention). A claim with nothing dated keeps `f = 1`.
- **R-FD5 — the per-type pace multiplies both engines.** Both the entity pass and the claim pass
  raise the same "Still tracking {name}?" item (`inbox_generator.py:164, 319`); a person who says
  "let people fade more slowly" means both, or the claim-level questions would keep arriving at
  the old pace. The claim engine reads it through the subject's type (R-FD13), so
  `claim_reconciler` stays free of any filesystem read of its own.
- **R-FD6 — suggestions: one vote per page, the latest, integer 80 %.** From the bank's own git
  history only (`git log --since=<today − 180 d>` with git's `--grep`, parsing the manifest line
  `commit_resolution` writes — producer and parser live in `git_service` so they cannot drift).
  Labels `archive` and `keep_active` only. Each page counts once, by its **latest** answer in
  the window (a page asked about three times cannot outvote three pages asked once), under the
  page's **current** `type`; a page that no longer exists is skipped. A type needs ≥ 5 answers;
  "≥ 80 %" is `5·kept ≥ 4·answers` (8 of 10 is on the line; no float guess) → `slower`, 0.5;
  `5·archived ≥ 4·answers` → `faster`, 1.5. A suggestion equal to the pace already set is not
  offered. The payload is types and counts — never a page id or name. Cached per
  `(bank, HEAD, since)` like `get_sleep_history` — except that an empty HEAD is never cached:
  `sync_service.git_head` reads `<bank>/.git/HEAD` and answers `""` for a worktree or submodule
  bank (whose `.git` is a file) or a bank with no commit, and a key that never moves would hide
  every answer given after the day's first read.
- **R-FD7 — `_decay_tuning.yaml` and its PUT.** Shape `types: {<type>: <multiplier>}` under a
  two-line comment header saying what it is (legible to an agent without ceremony). A key must
  be an `EntityType` value (else **422** "isn't a kind of page Cicada knows"); a value
  `null` or exactly `1.0` clears the type; any other value must be within **[0.25, 3.0]** (else
  422). The PUT merges (keys absent from the body are untouched), answers **409** while Sleep
  runs (Stage 3 reads the file, and Sleep's `git add -A` writers must never sweep a half-written
  file under the model's author — the G85 smear; `routers/projects.py:136-140` precedent), holds
  a process-local lock around read-merge-write, writes nothing and commits nothing when the
  content would not change (and never creates the file just to hold `{}`), and otherwise commits
  **only** `_decay_tuning.yaml` as `Decay tuning <date>` /
  `_decay_tuning.yaml: updated (trigger: user/companion_app)` / `Cicada-Author: user` via
  `commit_paths`. The file is tracked and travels with the bank (portability). Neither endpoint
  is a Store domain, so neither has an ETag; both return the same `DecayTuningResponse`
  (`bank`, `windowDays`, `tuning`, `suggestions`) so the page repaints from one shape.
- **R-FD8 — "Not now" is per viewer, per bank, and returns after 5 more answers.**
  `@AppStorage("cicada.memory.fadeNotNow")` holds `{"<bank>|<type>|<direction>": answers}` as
  JSON; the suggestion hides while its `answers < dismissed + 5`. A dismissal is a convenience,
  never bank state (browser-storage rule's native twin), so it makes no commit. Apply and Reset
  are the only writes.
- **R-FD9 — the wire.** `EntityResponse` gains `decay: {class, effectiveRatePerWeek,
  mentionWeeks}` (`EntityDecay`, `class` by explicit alias), built from the same
  `decay_policy.effective` the pass calls, rounded to 6 places (no float noise on the wire).
  `decayRate` / `decayClass` keep their meaning (the base) for every older reader. `GET
  /entities/{id}` has no ETag, so there is nothing to bump; `/graph` nodes are **not** given the
  block (Graph and Clusters never show a pace), so `graph.NODE_SHAPE` does not move. The app's
  entity bodies are an in-memory LRU; after a tuning write the Settings card calls
  `store.invalidateAllEntities()` so the next card open reads the new pace.
- **R-FD10 — the card: the pace replaces the Fades menu's label, not a second line.** DR-38 — a
  class word above a pace word would say "slowly" twice for a durable page. The menu still sets
  the class (G66 §1.7's override); its label is `FadeWords.detail(decay, fallback: class)`;
  while an override is in flight the label shows the chosen class's own words
  (`DetailsWords.fades`) until the reload lands. Pace thresholds are anchored on the default
  `active` rate 0.05/wk: `0` Never · `≤ 0.0125` (a quarter — the spacing floor) Very slowly ·
  `≤ 0.03` Slowly · `< 0.08` At the usual pace · else Quickly. Weeks: `0` → no clause, `1` →
  "— mentioned in a single week", `n ≥ 2` → "— mentioned across n weeks" (`UsageFormat.count`).
  No block (older backend) → the class words, exactly as before.
- **R-FD11 — one function for the pass and the card.** `decay_policy.effective` is the only
  place `base × f × pace` is spelled; the entity pass, the entity router and a test that holds
  them equal all go through it.
- **R-FD12 — a new row, G147, with G85 cross-linked.** The brief numbers this work G147. G85's
  defect (3) proposed promoting the *class* one step toward `durable` past a
  distinct-conversation threshold; this track answers it differently and the G85 row says so:
  the class is a label the person can set (G66 §1.7) and a promotion would silently overwrite it
  and commit on every threshold crossing, while a derived factor is continuous, counts weeks
  (not conversations — fifty in an afternoon are one burst) and is never stored. G85 (4)
  (reinforcement as an increment) stays open there.
- **R-FD13 — `class_lookup` becomes `subject_lookup`'s class column.** One memoised parse per
  subject yields class, type, `kept_on` and the type pace (`SubjectDecay`), so the claim engine
  does not walk the same files twice. `class_lookup(memory_path)` keeps its signature and its
  "unknown id → active" contract; `reconcile_stage3(…, decay_class_fn=…)` injection in existing
  tests keeps working. The tuning file is read lazily on the first lookup, so an MCP write (whose
  subject is always referenced) never reads it. A settings object with no `memory_path` gets
  `NEUTRAL_SUBJECT` for every subject — never a lookup under the process's working directory
  (today's default is `class_lookup(getattr(settings, "memory_path", "."))`, which with a `None`
  path raises and with no attribute reads `./entities`; the module never resolves a bank, the
  split-brain rule).

---

## File map

| File | Responsibility |
|---|---|
| `api/config.py` | `decay_spacing_alpha`, `decay_spacing_floor` (Task 1) |
| `api/services/decay_policy.py` | spacing constants, `mention_weeks`, `stability`, `spacing_params`, `entity_type`, `kept_dates`, `record_keep`, `EffectiveDecay`/`effective` (T1); `SubjectDecay`, `subject_lookup`, `class_lookup` rewrite, `claim_mention_weeks` (T3) |
| `api/services/conflict_resolver.py` | the entity pass charges `effective(...).rate` (T1), reads the bank's tuning by default (T2) |
| `api/services/inbox_service.py` | the keep branch records `kept_on` (T1) |
| `api/services/decay_tuning.py` (new) | `_decay_tuning.yaml` load/merge/save, `answers`, `suggest`, `overview` (T2) |
| `api/services/git_service.py` | `decay_verdicts(memory_path, since=)` beside `commit_resolution` (T2) |
| `api/routers/memory.py` (new) | `GET /memory/decay-suggestions`, `PUT /memory/decay-tuning` (T2) |
| `api/main.py` | mount the router (T2) |
| `api/models/schemas.py` | `DecaySuggestion`, `DecayTuningResponse` (T2); `EntityDecay`, `EntityResponse.decay` (T4) |
| `api/services/claim_reconciler.py` | `subject_fn` injection; `_decay_claims` × `f(w_claim)` × type pace (T3) |
| `api/routers/entities.py` | the derived `decay` block (T4) |
| `app/…/Models/Entity.swift` | `EntityDecay`, `Entity.decay` (lenient) (T4) |
| `app/…/Models/FadeWords.swift` (new) | pace words (T4); type nouns + suggestion copy (T5) |
| `app/…/Views/Graph/EntityDetailCard.swift` | the Fades menu's label (T4) |
| `app/…/Theme/Copy+Graph.swift` | `fadesHelp` wording (T4) |
| `app/…/Models/DecayTuning.swift` (new) | wire types, `FadeTypeRow`, `DecayTuningModel` (T5) |
| `app/…/Views/Settings/FadePaceCard.swift` (new) | "How things fade" (T5) |
| `app/…/Views/Settings/MemoryView.swift` | hosts `FadePaceCard()` (T5) |
| `app/…/Views/Settings/SettingsRowID.swift`, `SettingsIndex.swift` | `.fadePace` (+ index entry), `.fadeType(_:)` (T5) |
| `app/…/Theme/Copy+Settings.swift` | the card's static strings (T5) |
| `app/…/Services/APIClient.swift` | `fetchDecayTuning()`, `setDecayTuning(_:)` (T5) |
| `app/CicadaApp/Tests/CicadaAppTests/CountLiteralLintTests.swift` | scope += the new files (T4, T5) |
| Tests (Python) | `api/tests/test_decay_spacing.py` (new, T1 + T3), `api/tests/test_decay_tuning.py` (new, T2), `api/tests/test_decay_endpoint.py` (T4) |
| Tests (Swift) | `FadeWordsTests.swift` (new, T4), `DecayTuningTests.swift` (new, T5) |
| Docs | `CLAUDE.md`, `docs/goals/memory-evolution.md` (G66, G85, G113, **G147**), `docs/goals/TODO.md`, this plan (T6) |

---

### Task 1: Spacing-aware entity decay, and "keep" counts as a week

The core. After this task a page's weekly rate is base × f(w), and a keep answer adds its week.
The per-type pace exists as an injectable argument that defaults to "none" until Task 2 gives it
a file. Shippable: with no tuning and no multi-week pages, every number is unchanged.

**Files:**
- Modify: `api/config.py` (after `:170`)
- Modify: `api/services/decay_policy.py` (imports; new section after `resolve`, `:120`)
- Modify: `api/services/conflict_resolver.py:36-38` (signature), `:143-172` (rate)
- Modify: `api/services/inbox_service.py:983` (keep branch)
- Test: `api/tests/test_decay_spacing.py` (new)

**Interfaces:**
- Produces: `decay_policy.SPACING_ALPHA`, `SPACING_FLOOR`, `KEPT_ON_KEY`, `KEPT_ON_CAP`,
  `mention_weeks(episode_refs, kept_on=()) -> int`, `stability(weeks, *, alpha, floor) -> float`,
  `spacing_params(settings) -> (alpha, floor)`, `entity_type(fm) -> str`,
  `kept_dates(fm) -> list[str]`, `record_keep(fm, today) -> list[str]`,
  `EffectiveDecay`, `effective(fm, *, alpha, floor, tuning) -> EffectiveDecay`;
  `conflict_resolver.resolve_and_prune(…, *, now=None, tuning=None)`; the `kept_on:` key.
- Consumes: `decay_policy.resolve`, `episode_ids.parse_episode_id`.

- [ ] **Step 1: Failing tests** — create `api/tests/test_decay_spacing.py`:

```python
"""G147 — spacing-aware decay: how often a page came up sets how fast its
silence counts. Frequency is DISTINCT ISO WEEKS, never mentions (plan R-FD2):
fifty mentions in one afternoon are one burst, twelve weeks are twelve reviews.

Hermetic like `test_decay_engines.py`: `resolve_and_prune` runs with an EMPTY
`resolved` list, so the synthesis/contradiction LLM path is never entered.
"""

from __future__ import annotations

import asyncio
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from api.config import Settings
from api.models.schemas import DecayClass, InboxResolveRequest
from api.services import conflict_resolver, decay_policy, inbox_service, markdown_parser


def run(coro):
    return asyncio.run(coro)


class _FakeSettings:
    memory_path = None
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4


def _weekly(start: str, n: int) -> list[str]:
    """``n`` episode ids exactly 7 days apart — always ``n`` distinct ISO weeks."""
    d0 = date.fromisoformat(start)
    return [f"ep_{(d0 + timedelta(days=7 * i)).isoformat()}_001" for i in range(n)]


# --- mention_weeks (R-FD2) --------------------------------------------------


def test_fifty_mentions_in_one_afternoon_are_one_week():
    assert decay_policy.mention_weeks([f"ep_2026-06-01_{i:03d}" for i in range(1, 51)]) == 1


def test_twelve_weekly_mentions_are_twelve_weeks():
    assert decay_policy.mention_weeks(_weekly("2026-03-02", 12)) == 12


def test_weeks_are_iso_weeks_across_a_year_boundary():
    # 2025-12-29 (Mon) and 2026-01-04 (Sun) are both 2026-W01; 2026-01-05 opens W02.
    assert decay_policy.mention_weeks(["ep_2025-12-29_001", "ep_2026-01-04_003"]) == 1
    assert decay_policy.mention_weeks(["ep_2025-12-29_001", "ep_2026-01-05_001"]) == 2


def test_unparseable_ids_count_once_as_unknown():
    assert decay_policy.mention_weeks(
        ["ep_2026-06-01_001", "legacy-a", "ep_2026-13-40_001", ""]
    ) == 2
    assert decay_policy.mention_weeks(["legacy-a", "legacy-b"]) == 1
    assert decay_policy.mention_weeks([]) == 0
    assert decay_policy.mention_weeks(None) == 0


def test_a_bare_string_is_one_id_never_its_characters():
    assert decay_policy.mention_weeks("ep_2026-06-01_001") == 1


def test_kept_dates_join_the_week_set():
    eps = ["ep_2026-06-01_001"]
    assert decay_policy.mention_weeks(eps, ["2026-06-03"]) == 1  # same ISO week
    assert decay_policy.mention_weeks(eps, ["2026-07-20"]) == 2
    assert decay_policy.mention_weeks(eps, [date(2026, 7, 20), "not a date"]) == 2


# --- stability (R-FD1) --------------------------------------------------------


@pytest.mark.parametrize(
    "weeks,expected",
    [(0, 1.0), (1, 1.0), (2, 0.706), (4, 0.546), (12, 0.401), (52, 0.297), (148, 0.25), (1000, 0.25)],
)
def test_stability_curve_is_the_ruled_one(weeks, expected):
    assert round(decay_policy.stability(weeks), 3) == expected


def test_spacing_params_default_and_refuse_junk():
    assert decay_policy.spacing_params(_FakeSettings()) == (0.6, 0.25)

    class Junk:
        decay_spacing_alpha = "steep"
        decay_spacing_floor = True

    assert decay_policy.spacing_params(Junk()) == (0.6, 0.25)

    class Wild:
        decay_spacing_alpha = 99.0
        decay_spacing_floor = 0.0

    assert decay_policy.spacing_params(Wild()) == (5.0, 0.05)


def test_config_defaults_match_the_policy_constants():
    fields = Settings.model_fields
    assert fields["decay_spacing_alpha"].default == decay_policy.SPACING_ALPHA
    assert fields["decay_spacing_floor"].default == decay_policy.SPACING_FLOOR


# --- effective (R-FD11) -------------------------------------------------------


def test_effective_rate_is_base_times_stability_times_type_pace():
    fm = {"type": "person", "decay_class": "active", "source_episodes": _weekly("2026-03-02", 12)}
    eff = decay_policy.effective(fm, tuning={"person": 0.5})
    assert eff.decay_class is DecayClass.active
    assert eff.base_rate == 0.05
    assert eff.mention_weeks == 12
    assert eff.type_multiplier == 0.5
    assert eff.rate == pytest.approx(0.05 * decay_policy.stability(12) * 0.5)


def test_an_explicit_rate_is_still_the_base():
    eff = decay_policy.effective(
        {"decay_class": "active", "decay_rate": 0.1, "source_episodes": _weekly("2026-03-02", 4)}
    )
    assert eff.rate == pytest.approx(0.1 * decay_policy.stability(4))


def test_evergreen_stays_zero_whatever_the_weeks_or_pace():
    eff = decay_policy.effective(
        {"type": "media", "source_episodes": _weekly("2026-03-02", 30)}, tuning={"media": 3.0}
    )
    assert eff.decay_class is DecayClass.evergreen
    assert eff.rate == 0.0


def test_a_page_with_no_episodes_decays_exactly_as_before():
    assert decay_policy.effective({"decay_class": "active"}).rate == 0.05
    assert decay_policy.effective({"type": "skill"}).rate == 0.02


def test_kept_on_counts_in_effective():
    fm = {"decay_class": "active", "source_episodes": ["ep_2026-06-01_001"], "kept_on": ["2026-08-10"]}
    assert decay_policy.effective(fm).mention_weeks == 2


# --- the pass over simulated cycles (the brief's verification) -----------------


def _page(root: Path, eid: str, episodes: list[str], start: str) -> None:
    markdown_parser.write(
        root / "entities" / f"{eid}.md",
        {
            "name": eid, "type": "concept", "status": "active", "confidence": 0.62,
            "created": start, "last_referenced": start,
            "decay_class": "active", "decay_rate": 0.05,
            "source_episodes": episodes, "tags": [], "related": [], "version": 1,
        },
        "## Summary\n\nA synthetic page.\n",
    )


def _existing(root: Path) -> list[dict]:
    out = []
    for path in sorted((root / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        out.append({"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    return out


def test_a_twelve_week_page_outlasts_a_one_week_page_over_simulated_cycles(tmp_path):
    (tmp_path / "entities").mkdir()
    start = date(2026, 6, 7)
    _page(tmp_path, "spaced", _weekly("2026-03-15", 12), start.isoformat())
    _page(tmp_path, "burst", ["ep_2026-06-01_001", "ep_2026-06-02_004", "ep_2026-06-03_002"],
          start.isoformat())
    first: dict[tuple[str, str], int] = {}
    for cycle in range(1, 23):
        now = datetime.combine(start + timedelta(days=7 * cycle), datetime.min.time())
        changes = run(conflict_resolver.resolve_and_prune([], _existing(tmp_path), _FakeSettings(), now=now))
        conflict_resolver.apply_changes(changes, tmp_path)
        for change in changes:
            first.setdefault((change["id"], change["action"]), cycle)
    # Same class, same start (0.62), same silence — only the spacing differs.
    # burst:  0.05/wk            -> asked at cycle 5,  archived at 9.
    # spaced: 0.05 x f(12)/wk    -> asked at cycle 11, archived at 21 (0.0200727/wk).
    assert first[("burst", "decay_nudge")] == 5
    assert first[("burst", "archive")] == 9
    assert first[("spaced", "decay_nudge")] == 11
    assert first[("spaced", "archive")] == 21


def test_an_injected_pace_multiplies_the_pass():
    existing = [{
        "id": "bob-example",
        "frontmatter": {"type": "person", "status": "active", "confidence": 0.7,
                        "decay_class": "active",
                        "last_referenced": str(date.today() - timedelta(days=35))},
        "body": "x",
    }]
    changes = run(conflict_resolver.resolve_and_prune([], existing, _FakeSettings(), tuning={"person": 0.5}))
    assert changes[0]["new_confidence"] == pytest.approx(0.7 - 0.025)


# --- "keep" is a week (R-FD3) --------------------------------------------------


def _git(memory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(memory), *args], check=True, capture_output=True, text=True
    ).stdout


class _InboxSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.inbox_defer_days = 30
        self.litellm_model = "test-model"
        self.inbox_stale_after_days = 90


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    (m / "inbox").mkdir()
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    (m / "entities" / "alpha-project.md").write_text(
        "---\ntype: project\nstatus: decaying\nconfidence: 0.35\ncreated: 2026-01-01\n"
        "last_referenced: 2026-01-01\ndecay_rate: 0.05\nsource_episodes: []\ntags: []\n"
        "related: []\nversion: 1\n---\n# Alpha Project\n"
    )
    (m / "inbox" / "inbox-001.md").write_text(
        "---\nkind: decay\nrequired_input: choice\nstatus: pending\npriority: 0.3\n"
        "entity_id: alpha-project\nentity_name: Alpha Project\n"
        "title: Still tracking Alpha Project?\ncreated_date: 2026-08-01\n---\n"
    )
    _git(m, "add", ".")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def _fm(bank: Path) -> dict:
    return markdown_parser.parse(bank / "entities" / "alpha-project.md").frontmatter


def test_keep_records_today_as_a_kept_week(bank):
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="keep_active"), _InboxSettings(bank)))
    fm = _fm(bank)
    assert fm["kept_on"] == [date.today().isoformat()]
    assert fm["status"] == "active" and fm["confidence"] == 0.6  # unchanged behaviour
    assert decay_policy.effective(fm).mention_weeks == 1


def test_keep_appends_to_earlier_keeps_and_caps_the_list(bank):
    page = bank / "entities" / "alpha-project.md"
    parsed = markdown_parser.parse(page)
    seeds = [(date(2025, 1, 6) + timedelta(days=7 * i)).isoformat() for i in range(52)]
    parsed.frontmatter["kept_on"] = seeds
    markdown_parser.write(page, parsed.frontmatter, parsed.body)
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="resolve", option_key="keep"),
                              _InboxSettings(bank)))
    kept = _fm(bank)["kept_on"]
    assert len(kept) == decay_policy.KEPT_ON_CAP == 52
    assert kept[-1] == date.today().isoformat()
    assert kept[0] == seeds[1]


def test_archive_writes_no_kept_week(bank):
    run(inbox_service.resolve("inbox-001", InboxResolveRequest(action="archive"), _InboxSettings(bank)))
    assert "kept_on" not in _fm(bank)


def test_record_keep_is_idempotent_within_a_day():
    fm = {"kept_on": ["2026-09-01"]}
    assert decay_policy.record_keep(fm, "2026-09-01") == ["2026-09-01"]
    assert decay_policy.record_keep({"kept_on": "2026-09-01"}, "2026-09-24") == ["2026-09-01", "2026-09-24"]
```

- [ ] **Step 2: Run — red.**
  `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay && api/.venv/bin/python -m pytest api/tests/test_decay_spacing.py -q -p no:cacheprovider`
  → `AttributeError: module 'api.services.decay_policy' has no attribute 'mention_weeks'` (and
  a `KeyError` on the config fields).

- [ ] **Step 3: Implement.**

`api/config.py` — after `archive_threshold: float = 0.2` (`:170`):

```python
    # G147 — spacing-aware decay. A page's weekly rate is its class's (or its
    # explicit `decay_rate:`) x max(floor, 1 / (1 + alpha·ln w)), w = the
    # distinct ISO weeks it came up in — fifty mentions in one afternoon are one
    # week. 0.6 / 0.25 is the ruled curve (plan R-FD1: floor reached near 148
    # weeks); `decay_policy.spacing_params` clamps both so a mis-set value can
    # never freeze decay.
    decay_spacing_alpha: float = 0.6     # CICADA_DECAY_SPACING_ALPHA
    decay_spacing_floor: float = 0.25    # CICADA_DECAY_SPACING_FLOOR
```

`api/services/decay_policy.py` — imports become:

```python
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Callable, NamedTuple

from api.models.schemas import (
    AGENT_PRODUCIBLE_DECAY_CLASSES,
    CLAIM_DECAY_MULTIPLIERS,
    DECAY_CLASS_RATES,
    DecayClass,
)
from api.services import episode_ids, markdown_parser
```

and a new section directly after `resolve` (after `:120`):

```python
# --------------------------------------------------------------------------- #
# G147 — spacing: how often a page came up sets how fast its silence counts
# --------------------------------------------------------------------------- #

# Before G147 the weekly rate was flat per class from the last reference, so a
# page mentioned in fifty separate conversations faded exactly as fast as one
# mentioned twice — while CLAUDE.md promised decay "proportional to how
# frequently it used to be referenced". Frequency is counted in DISTINCT ISO
# WEEKS (plan R-FD2): fifty mentions in one afternoon are one burst, twelve
# weeks of mentions are twelve spaced reviews. The curve is plan R-FD1:
# f(12) ≈ 0.40, f(52) ≈ 0.30, the floor only near 148 weeks, so spacing keeps
# paying across a bank's whole realistic life.
SPACING_ALPHA = 0.6
SPACING_FLOOR = 0.25
# A mis-set env var must never freeze decay: a floor of 0 would make every
# well-mentioned page effectively evergreen — the class the anti-pollution
# rail reserves for ingest writers and the person, one page at a time.
_ALPHA_MAX = 5.0
_FLOOR_MIN = 0.05

# The decay question's "keep" answer is the person's own act: it counts as a
# week the page came up (plan R-FD3). Dates, deduped, capped at a year of
# weekly keeps; written only by `inbox_service._resolve_decay`.
KEPT_ON_KEY = "kept_on"
KEPT_ON_CAP = 52


class EffectiveDecay(NamedTuple):
    """The pace Sleep charges one page, and every factor that made it (G147).

    ONE spelling of ``base x f(w) x pace`` (plan R-FD11): the Stage-3 pass
    charges ``rate`` and ``GET /entities/{id}`` serves it, so the card can never
    describe a pace the pass does not charge.
    """

    decay_class: DecayClass
    base_rate: float        # the class's rate, or the page's explicit `decay_rate:` (G66)
    mention_weeks: int      # distinct ISO weeks it came up in (+1 for any unparseable id)
    stability: float        # f(mention_weeks)
    type_multiplier: float  # the per-type pace the person approved (1.0 = none)
    rate: float             # base x stability x type_multiplier; 0.0 for evergreen


def _as_list(value) -> list:
    """A frontmatter list, tolerant of a hand-edited scalar: ``ep_x`` is one id,
    never iterated character by character."""
    if value is None:
        return []
    if isinstance(value, (str, bytes, date)):
        return [value]
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return []


def _week_of(value) -> str | None:
    """``YYYY-Www`` — the ISO 8601 week of a date-ish value, else ``None``.

    ISO weeks, so the boundary is the calendar's (Dec 29 can open next year's
    W01), not a 7-day bucket from an arbitrary epoch. ``str()`` of a ``date``
    or ``datetime`` starts with its ISO day, which is all this reads.
    """
    try:
        day = date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def mention_weeks(episode_refs, kept_on=()) -> int:
    """Distinct ISO weeks among episode ids (``ep_<date>_<n>``, G114) and kept dates.

    An id that does not parse — a legacy stem, an impossible date — is still a
    mention: all of them together count ONCE as an unknown week (R-FD2), so a
    legacy page gets bounded credit, never zero and never one week per id.
    """
    weeks: set[str] = set()
    unknown = False
    for ref in _as_list(episode_refs):
        stem = str(ref or "").strip()
        if not stem:
            continue
        parsed = episode_ids.parse_episode_id(stem)
        week = _week_of(parsed[0]) if parsed else None
        if week is None:
            unknown = True
        else:
            weeks.add(week)
    for day in _as_list(kept_on):
        week = _week_of(day)
        if week is not None:
            weeks.add(week)
    return len(weeks) + (1 if unknown else 0)


def stability(weeks: int, *, alpha: float = SPACING_ALPHA, floor: float = SPACING_FLOOR) -> float:
    """``f(w) = max(floor, 1 / (1 + alpha·ln w))``; ``1.0`` for ``w <= 1`` — a page
    heard in one week (or never dated) decays exactly as it did before G147."""
    if weeks <= 1:
        return 1.0
    return max(floor, 1.0 / (1.0 + alpha * math.log(weeks)))


def spacing_params(settings) -> tuple[float, float]:
    """``(alpha, floor)`` from ``Settings``, clamped (R-FD1).

    Only a real number is read: a test double without the fields, or a mock
    whose attributes are not numbers, gets the ruled defaults.
    """

    def _number(name: str, default: float) -> float:
        value = getattr(settings, name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value)

    alpha = min(_ALPHA_MAX, max(0.0, _number("decay_spacing_alpha", SPACING_ALPHA)))
    floor = min(1.0, max(_FLOOR_MIN, _number("decay_spacing_floor", SPACING_FLOOR)))
    return alpha, floor


def entity_type(fm: dict) -> str:
    """The key a per-type pace is filed under — the page's ``type``, ``concept``
    when absent (the default `GET /entities/{id}` has always served)."""
    return str((fm or {}).get("type") or "concept").strip().lower()


def kept_dates(fm: dict) -> list[str]:
    """The page's ``kept_on:`` as ISO days, deduped, junk dropped."""
    out: list[str] = []
    for value in _as_list((fm or {}).get(KEPT_ON_KEY)):
        day = str(value).strip()[:10]
        if _week_of(day) is not None and day not in out:
            out.append(day)
    return out


def record_keep(fm: dict, today: str) -> list[str]:
    """``kept_on`` after one more "keep" today — idempotent within a day, capped."""
    kept = kept_dates(fm)
    if today not in kept:
        kept.append(today)
    return kept[-KEPT_ON_CAP:]


def effective(
    fm: dict,
    *,
    alpha: float = SPACING_ALPHA,
    floor: float = SPACING_FLOOR,
    tuning: dict[str, float] | None = None,
) -> EffectiveDecay:
    """``base x f(w) x pace`` for one page's frontmatter. Never raises."""
    fm = fm or {}
    cls, base = resolve(fm)
    weeks = mention_weeks(fm.get("source_episodes"), kept_dates(fm))
    factor = stability(weeks, alpha=alpha, floor=floor)
    pace = float((tuning or {}).get(entity_type(fm), 1.0))
    rate = 0.0 if cls is DecayClass.evergreen else base * factor * pace
    return EffectiveDecay(cls, base, weeks, factor, pace, rate)
```

`api/services/conflict_resolver.py` — the signature (`:36-38`) becomes:

```python
async def resolve_and_prune(
    resolved: list[dict],
    existing: list[dict],
    settings: Settings,
    *,
    now: datetime | None = None,
    tuning: dict[str, float] | None = None,
) -> list[dict]:
```

add to its docstring: ``tuning``: the per-type pace (G147, ``{type: multiplier}``); ``None``
means none yet. Replace `:143-145`'s comment and `now` line with:

```python
    # Temporal decay for unreferenced entities (G147). The weekly rate is
    # `decay_policy.effective`: the class's (or explicit) rate x the spacing
    # factor over distinct mention weeks x the per-type pace the person chose —
    # the SAME function `GET /entities/{id}` serves, so the card's pace is the
    # pace charged. Evergreen entities are skipped.
    now = now or datetime.now()
    alpha, floor = decay_policy.spacing_params(settings)
    tuning = tuning or {}
```

and `:167-172` (from `confidence = …` through the evergreen `continue`) with:

```python
        confidence = fm.get("confidence", 0.5)
        effective = decay_policy.effective(fm, alpha=alpha, floor=floor, tuning=tuning)
        decay_class, decay_rate = effective.decay_class, effective.rate
        if decay_class is DecayClass.evergreen:
            # An artifact, not a belief: it does not become less true by going
            # unmentioned. No decay math, no decay nudge, never auto-archived.
            continue
```

Everything after (`baseline`, the one-week cap, the watermark, thresholds) is unchanged — it
now multiplies the effective rate.

`api/services/inbox_service.py` — in the keep branch, after
`entity.frontmatter["last_referenced"] = str(date.today())` (`:983`):

```python
        # G147 (plan R-FD3): "still relevant" is the person's own act — it counts
        # as one more week the page came up, so a page kept once fades a little
        # slower than one never answered for. Dates, not a counter:
        # `decay_policy.mention_weeks` unions them with the page's episode weeks.
        entity.frontmatter[decay_policy.KEPT_ON_KEY] = decay_policy.record_keep(
            entity.frontmatter, str(date.today())
        )
```

(`decay_policy` is already imported, `inbox_service.py:20`.)

- [ ] **Step 4: Green, then the suites.**
  `api/.venv/bin/python -m pytest api/tests/test_decay_spacing.py api/tests/test_decay_engines.py api/tests/test_decay_policy.py api/tests/test_inbox_resolution_provenance.py -q -p no:cacheprovider`
  → all pass; then `api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` → 0
  failures.

- [ ] **Step 5: Commit.**
  `git add api/config.py api/services/decay_policy.py api/services/conflict_resolver.py api/services/inbox_service.py api/tests/test_decay_spacing.py`
  → `git commit` with subject
  `feat(decay): spacing-aware entity decay — distinct mention weeks slow the fade, and "keep" counts as a week (G147)`.

---

### Task 2: Per-type pace — suggested from the bank's own answers, applied only by the person

**Files:**
- Create: `api/services/decay_tuning.py`
- Modify: `api/services/git_service.py` (new `decay_verdicts` after `commit_resolution`, `:1389`)
- Create: `api/routers/memory.py`
- Modify: `api/main.py:13-45` (import `memory`), `:200-230` (mount)
- Modify: `api/models/schemas.py` (after `EntityDecayUpdate`, `:533-542`)
- Modify: `api/services/conflict_resolver.py` (the `tuning = tuning or {}` line from Task 1)
- Test: `api/tests/test_decay_tuning.py` (new)

**Interfaces:**
- Produces: `decay_tuning.FILE`, `WINDOW_DAYS`, `MIN_ANSWERS`, `SLOWER`, `FASTER`,
  `MIN_MULTIPLIER`, `MAX_MULTIPLIER`, `load(memory_path) -> dict[str, float]`,
  `merge(current, changes) -> dict[str, float]` (raises `ValueError`),
  `save(memory_path, tuning) -> bool`, `answers(memory_path, *, today)`,
  `suggest(counts, tuning) -> list[dict]`, `overview(memory_path, *, today=None) -> dict`;
  `git_service.decay_verdicts(memory_path, *, since) -> dict[str, str]`;
  `GET /memory/decay-suggestions`, `PUT /memory/decay-tuning` → `DecayTuningResponse`
  `{bank, windowDays, tuning, suggestions: [{type, direction, multiplier, kept, archived, answers}]}`.
- Consumes: `git_service._run_git`, `build_commit_message`, `commit_paths`,
  `sync_service.git_head`, `sleep_cycle.get_sleep_state`, `decay_policy.entity_type`.

- [ ] **Step 1: Failing tests** — create `api/tests/test_decay_tuning.py`:

```python
"""G147 — per-type pace: Cicada proposes from the bank's OWN decay answers
(git history, never the telemetry ledger), and nothing changes until the person
applies it (UX principle 3; G78/G113: nothing learned is auto-applied).
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import types
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from api.models.schemas import InboxResolveRequest
from api.routers import memory as memory_router
from api.services import conflict_resolver, decay_tuning, git_service, inbox_service, markdown_parser

TODAY = date(2026, 9, 24)


def run(coro):
    return asyncio.run(coro)


def _git(m: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(m), *args], check=True, capture_output=True, text=True,
        env={**os.environ, **(env or {})},
    ).stdout


class _FakeSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path


class _SleepSettings(_FakeSettings):
    archive_threshold = 0.2
    decay_nudge_threshold = 0.4


def _page(m: Path, eid: str, etype: str, **fm) -> None:
    base = {"name": eid, "type": etype, "status": "active", "confidence": 0.5}
    base.update(fm)
    markdown_parser.write(m / "entities" / f"{eid}.md", base, "A synthetic page.\n")


@pytest.fixture
def bank(tmp_path: Path) -> Path:
    m = tmp_path / "memory"
    (m / "entities").mkdir(parents=True)
    _git(m, "init", "-q")
    _git(m, "config", "user.email", "t@example.com")
    _git(m, "config", "user.name", "t")
    for i in range(1, 11):
        _page(m, f"person-{i:02d}", "person")
    for i in range(1, 4):
        _page(m, f"tool-{i:02d}", "tool")
    _git(m, "add", "-A")
    _git(m, "commit", "-q", "-m", "seed")
    return m


def _answer(m: Path, eid: str, label: str, *, days_ago: int, today: date = TODAY) -> None:
    """One decay answer, committed exactly as `git_service.commit_resolution` writes it."""
    when = datetime.combine(today - timedelta(days=days_ago), datetime.min.time()).replace(hour=12)
    change = "status active" if label == "keep_active" else "status archived"
    message = git_service.build_commit_message(
        f"Inbox resolution (decay) {when.date().isoformat()}",
        [f"entities/{eid}.md: {change} (trigger: inbox/decay/resolved:{label})"],
        authors=["user"],
    )
    stamp = when.isoformat()
    _git(m, "commit", "-q", "--allow-empty", "-m", message,
         env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})


def _suggestions(m: Path, today: date = TODAY) -> list[dict]:
    return run(decay_tuning.overview(m, today=today))["suggestions"]


# --- suggestions (R-FD6) --------------------------------------------------------


def test_nine_keeps_of_ten_people_suggest_fading_people_more_slowly(bank):
    for i in range(1, 10):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=20 + i)
    _answer(bank, "person-10", "archive", days_ago=5)
    assert _suggestions(bank) == [{
        "type": "person", "direction": "slower", "multiplier": 0.5,
        "kept": 9, "archived": 1, "answers": 10,
    }]


def test_fewer_than_five_answers_suggest_nothing(bank):
    for i in range(1, 5):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    assert _suggestions(bank) == []


def test_eighty_percent_is_on_the_line_and_seventy_is_not(bank):
    for i in range(1, 5):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    _answer(bank, "person-05", "archive", days_ago=6)
    assert [s["direction"] for s in _suggestions(bank)] == ["slower"]  # 4 of 5
    for i in range(6, 11):
        _answer(bank, f"person-{i:02d}", "archive" if i >= 9 else "keep_active", days_ago=i)
    # now 7 kept of 10 (person-05, -09, -10 archived) -> 70 %: nothing either way
    assert _suggestions(bank) == []


def test_mostly_archived_suggests_fading_faster(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "archive", days_ago=i)
    assert _suggestions(bank) == [{
        "type": "person", "direction": "faster", "multiplier": 1.5,
        "kept": 0, "archived": 5, "answers": 5,
    }]


def test_one_vote_per_page_its_latest_answer(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "archive", days_ago=40)
    for i in range(1, 5):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=3)
    assert _suggestions(bank) == [{
        "type": "person", "direction": "slower", "multiplier": 0.5,
        "kept": 4, "archived": 1, "answers": 5,
    }]


def test_answers_older_than_the_window_do_not_count(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=200)
    assert _suggestions(bank) == []
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=170)
    assert _suggestions(bank)[0]["answers"] == 5


def test_deferrals_and_other_kinds_are_not_verdicts(bank):
    for i in range(1, 7):
        message = git_service.build_commit_message(
            "Inbox resolution (conflict) 2026-09-20",
            [f"entities/person-{i:02d}.md: updated (trigger: inbox/conflict/resolved:pick:1)",
             f"inbox/inbox-{i:03d}.md: deferred until 2026-10-01 (trigger: inbox/deferred)"],
            authors=["user"],
        )
        _git(bank, "commit", "-q", "--allow-empty", "-m", message)
    assert _suggestions(bank, today=date.today()) == []


def test_a_page_that_no_longer_exists_is_skipped(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    (bank / "entities" / "person-01.md").unlink()
    assert _suggestions(bank) == []  # 4 answers left


def test_a_pace_already_applied_is_not_offered_again(bank):
    for i in range(1, 6):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    decay_tuning.save(bank, {"person": 0.5})
    out = run(decay_tuning.overview(bank, today=TODAY))
    assert out["suggestions"] == []
    assert out["tuning"] == {"person": 0.5}


def test_the_payload_carries_no_page_ids_or_names(bank):
    for i in range(1, 10):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    text = json.dumps(run(decay_tuning.overview(bank, today=TODAY)))
    assert "person-0" not in text


def test_the_real_resolver_is_what_the_parser_reads(bank):
    """Producer and parser pinned together: five real keep answers through
    `inbox_service.resolve` (the app's and the MCP tool's one path)."""
    (bank / "inbox").mkdir()
    for i in range(1, 6):
        (bank / "inbox" / f"inbox-{i:03d}.md").write_text(
            "---\nkind: decay\nrequired_input: choice\nstatus: pending\npriority: 0.3\n"
            f"entity_id: person-{i:02d}\nentity_name: Person {i}\n"
            f"title: Still tracking Person {i}?\ncreated_date: 2026-08-01\n---\n"
        )
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "items")

    class _InboxSettings(_FakeSettings):
        inbox_defer_days = 30
        litellm_model = "test-model"
        inbox_stale_after_days = 90

    for i in range(1, 6):
        run(inbox_service.resolve(f"inbox-{i:03d}", InboxResolveRequest(action="keep_active"),
                                  _InboxSettings(bank)))
    assert _suggestions(bank, today=date.today()) == [{
        "type": "person", "direction": "slower", "multiplier": 0.5,
        "kept": 5, "archived": 0, "answers": 5,
    }]


def test_an_unknown_head_never_keys_the_cache(bank, monkeypatch):
    """A worktree or submodule bank's `.git` is a FILE that `git_head` does not
    follow, so its HEAD reads as "" — a key that never moves. Caching under it
    would hide every answer given after the first read of the day (R-FD6)."""
    from api.services import sync_service

    monkeypatch.setattr(sync_service, "git_head", lambda _p: "")
    for i in range(1, 5):
        _answer(bank, f"person-{i:02d}", "keep_active", days_ago=i)
    assert _suggestions(bank) == []
    _answer(bank, "person-05", "keep_active", days_ago=1)
    assert _suggestions(bank)[0]["answers"] == 5


# --- the file (R-FD7) --------------------------------------------------------------


def test_load_keeps_only_valid_entries(bank):
    (bank / decay_tuning.FILE).write_text(
        "types:\n  person: 0.5\n  unicorn: 0.5\n  tool: fast\n  company: 9\n  concept: 1.0\n"
        "  skill: true\n"
    )
    assert decay_tuning.load(bank) == {"person": 0.5}
    (bank / decay_tuning.FILE).write_text("types: [unclosed\n")
    assert decay_tuning.load(bank) == {}
    assert decay_tuning.load(None) == {}


def test_merge_sets_clears_and_refuses():
    assert decay_tuning.merge({"person": 0.5}, {"tool": 1.5}) == {"person": 0.5, "tool": 1.5}
    assert decay_tuning.merge({"person": 0.5}, {"person": None}) == {}
    assert decay_tuning.merge({"person": 0.5}, {"person": 1.0}) == {}
    with pytest.raises(ValueError):
        decay_tuning.merge({}, {"unicorn": 0.5})
    with pytest.raises(ValueError):
        decay_tuning.merge({}, {"person": 0.1})
    with pytest.raises(ValueError):
        decay_tuning.merge({}, {"person": 4.0})


def test_save_never_creates_a_file_to_hold_nothing(bank):
    assert decay_tuning.save(bank, {}) is False
    assert not (bank / decay_tuning.FILE).exists()
    assert decay_tuning.save(bank, {"person": 0.5}) is True
    assert decay_tuning.save(bank, {"person": 0.5}) is False
    assert (bank / decay_tuning.FILE).read_text().startswith("#")


# --- the endpoints ------------------------------------------------------------------


def test_put_writes_the_file_and_commits_it_alone_as_the_person(bank):
    (bank / "entities" / "tool-01.md").write_text("an unrelated edit\n")
    out = run(memory_router.put_decay_tuning({"person": 0.5}, settings=_FakeSettings(bank)))
    assert out.tuning == {"person": 0.5}
    body = _git(bank, "log", "-1", "--format=%B")
    assert body.startswith("Decay tuning ")
    assert f"{decay_tuning.FILE}: updated (trigger: user/companion_app)" in body
    assert "Cicada-Author: user" in body
    assert _git(bank, "show", "--name-only", "--format=", "HEAD").split() == [decay_tuning.FILE]
    assert "entities/tool-01.md" in _git(bank, "status", "--porcelain")


def test_put_null_clears_and_an_unchanged_put_makes_no_commit(bank):
    run(memory_router.put_decay_tuning({"person": 0.5}, settings=_FakeSettings(bank)))
    head = _git(bank, "rev-parse", "HEAD")
    run(memory_router.put_decay_tuning({"person": 0.5}, settings=_FakeSettings(bank)))
    assert _git(bank, "rev-parse", "HEAD") == head
    out = run(memory_router.put_decay_tuning({"person": None}, settings=_FakeSettings(bank)))
    assert out.tuning == {}
    assert _git(bank, "rev-parse", "HEAD") != head


def test_put_refuses_an_unknown_type_or_an_out_of_range_pace(bank):
    for body in ({"unicorn": 0.5}, {"person": 0.1}):
        with pytest.raises(HTTPException) as exc:
            run(memory_router.put_decay_tuning(body, settings=_FakeSettings(bank)))
        assert exc.value.status_code == 422
    assert not (bank / decay_tuning.FILE).exists()


def test_put_is_refused_while_sleep_runs(bank, monkeypatch):
    from api.services import sleep_cycle

    monkeypatch.setattr(sleep_cycle, "get_sleep_state", lambda: types.SimpleNamespace(status="running"))
    with pytest.raises(HTTPException) as exc:
        run(memory_router.put_decay_tuning({"person": 0.5}, settings=_FakeSettings(bank)))
    assert exc.value.status_code == 409
    assert not (bank / decay_tuning.FILE).exists()


def test_get_answers_with_the_same_shape(bank):
    out = run(memory_router.get_decay_suggestions(settings=_FakeSettings(bank)))
    dumped = out.model_dump(mode="json")
    assert dumped == {"bank": "memory", "windowDays": 180, "tuning": {}, "suggestions": []}


def test_main_mounts_both_routes():
    from api import main

    routes = {(m, r.path) for r in main.app.routes if isinstance(r, APIRoute) for m in r.methods}
    assert ("GET", "/memory/decay-suggestions") in routes
    assert ("PUT", "/memory/decay-tuning") in routes


# --- the pass reads the bank's pace ---------------------------------------------------


def test_the_decay_pass_multiplies_by_the_bank_pace(bank):
    decay_tuning.save(bank, {"person": 0.5})
    ago = str(date.today() - timedelta(days=35))
    existing = [
        {"id": "person-01", "frontmatter": {"type": "person", "status": "active", "confidence": 0.7,
                                            "decay_class": "active", "last_referenced": ago}, "body": ""},
        {"id": "tool-01", "frontmatter": {"type": "tool", "status": "active", "confidence": 0.7,
                                          "decay_class": "active", "last_referenced": ago}, "body": ""},
    ]
    changes = {c["id"]: c for c in run(conflict_resolver.resolve_and_prune([], existing, _SleepSettings(bank)))}
    assert changes["person-01"]["new_confidence"] == pytest.approx(0.7 - 0.025)
    assert changes["tool-01"]["new_confidence"] == pytest.approx(0.7 - 0.05)
```

**Fixture order matters in the window test, on purpose.** On a linear history git's `--since`
stops walking at the first commit older than the cutoff (`revision.c`'s non-limited walk skips
that commit *and its parents*), so `test_answers_older_than_the_window_do_not_count` creates the
out-of-window answers first and the in-window ones after them — the order a real bank's clock
produces. Do not "fix" a failure by reordering the other tests' commits.

- [ ] **Step 2: Run — red.**
  `api/.venv/bin/python -m pytest api/tests/test_decay_tuning.py -q -p no:cacheprovider` →
  `ImportError: cannot import name 'memory' from 'api.routers'`.

- [ ] **Step 3: Implement.**

`api/services/decay_tuning.py`:

```python
"""G147 — how fast each KIND of page fades, as the person chose it.

Agent proposes, person disposes (UX principle 3). The proposal is derived from
the bank's OWN git history — every decay answer since G113 R1 commits as
``entities/<id>.md: status active|archived (trigger: inbox/decay/resolved:<label>)``
— never from the machine-global telemetry ledger (nothing learned there is
auto-applied, G78/G113), and nothing here applies itself: a suggestion changes
decay only after ``PUT /memory/decay-tuning``.

``<bank>/_decay_tuning.yaml`` lives IN the bank so "let people fade more
slowly" travels with it (portability), and is committed alone as
``Cicada-Author: user`` (``commit_paths``, never ``git add -A``). Plan rulings
R-FD5 … R-FD8.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml

from api.models.schemas import EntityType

FILE = "_decay_tuning.yaml"
WINDOW_DAYS = 180
MIN_ANSWERS = 5
# "At least 80 %" as integers — 5·part >= 4·whole — so 8 of 10 is exactly on
# the line, never a float's guess (R-FD6).
_SHARE_NUM, _SHARE_DEN = 4, 5
SLOWER = 0.5
FASTER = 1.5
MIN_MULTIPLIER = 0.25
MAX_MULTIPLIER = 3.0
_TYPES = frozenset(t.value for t in EntityType)
_HEADER = (
    "# How fast each kind of page fades, as a multiple of its usual pace (G147).\n"
    "# Written by Settings → Memory when you apply a suggestion; 0.5 = half as fast.\n"
)


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def load(memory_path) -> dict[str, float]:
    """The bank's per-type pace; a missing, corrupt or hand-mangled file reads as
    none, and an entry outside the rules is dropped rather than trusted."""
    if not memory_path:
        return {}
    try:
        data = yaml.safe_load((Path(memory_path) / FILE).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    types = data.get("types") if isinstance(data, dict) else None
    out: dict[str, float] = {}
    for etype, value in (types.items() if isinstance(types, dict) else []):
        number = _number(value)
        if str(etype) in _TYPES and number is not None and number != 1.0 \
                and MIN_MULTIPLIER <= number <= MAX_MULTIPLIER:
            out[str(etype)] = number
    return dict(sorted(out.items()))


def merge(current: dict[str, float], changes: dict) -> dict[str, float]:
    """Apply one PUT body (R-FD7). Keys absent from ``changes`` are untouched;
    ``None`` or exactly ``1.0`` clears a type. Raises ``ValueError`` with a plain
    sentence the app can show."""
    out = dict(current)
    for etype, value in (changes or {}).items():
        etype = str(etype)
        if etype not in _TYPES:
            raise ValueError(f"'{etype}' isn't a kind of page Cicada knows")
        number = None if value is None else _number(value)
        if value is None or number == 1.0:
            out.pop(etype, None)
            continue
        if number is None or not MIN_MULTIPLIER <= number <= MAX_MULTIPLIER:
            raise ValueError(
                f"A pace must be between {MIN_MULTIPLIER} and {MAX_MULTIPLIER} times the usual"
            )
        out[etype] = number
    return dict(sorted(out.items()))


def save(memory_path, tuning: dict[str, float]) -> bool:
    """Write the file. ``False`` when nothing would change — including never
    creating a file just to hold ``{}`` — so the caller makes no empty commit."""
    path = Path(memory_path) / FILE
    if not tuning and not path.exists():
        return False
    text = _HEADER + yaml.safe_dump({"types": dict(sorted(tuning.items()))}, sort_keys=False)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return True


async def answers(memory_path, *, today: date) -> dict[str, dict[str, int]]:
    """``{type: {"kept": n, "archived": n}}`` over the window — ONE vote per page,
    its latest answer (R-FD6), under the page's CURRENT type. Only ids and
    ``type`` are read; a page that no longer exists is skipped."""
    from api.services import decay_policy, git_service, markdown_parser

    verdicts = await git_service.decay_verdicts(
        Path(memory_path), since=today - timedelta(days=WINDOW_DAYS)
    )
    counts: dict[str, dict[str, int]] = {}
    for entity_id, label in verdicts.items():
        path = Path(memory_path) / "entities" / f"{entity_id}.md"
        if not path.is_file():
            continue
        try:
            fm = markdown_parser.parse(path).frontmatter or {}
        except Exception:  # noqa: BLE001 — one unreadable page never hides the rest
            continue
        bucket = counts.setdefault(decay_policy.entity_type(fm), {"kept": 0, "archived": 0})
        bucket["kept" if label == "keep_active" else "archived"] += 1
    return counts


def suggest(counts: dict[str, dict[str, int]], tuning: dict[str, float]) -> list[dict]:
    """A suggestion per type with >= 5 answers and >= 80 % one way, unless that
    pace is already the person's choice. Most-answered first."""
    out: list[dict] = []
    for etype, c in counts.items():
        kept, archived = int(c.get("kept", 0)), int(c.get("archived", 0))
        total = kept + archived
        if total < MIN_ANSWERS:
            continue
        if _SHARE_DEN * kept >= _SHARE_NUM * total:
            direction, multiplier = "slower", SLOWER
        elif _SHARE_DEN * archived >= _SHARE_NUM * total:
            direction, multiplier = "faster", FASTER
        else:
            continue
        if tuning.get(etype) == multiplier:
            continue
        out.append({"type": etype, "direction": direction, "multiplier": multiplier,
                    "kept": kept, "archived": archived, "answers": total})
    out.sort(key=lambda s: (-s["answers"], s["type"]))
    return out


async def overview(memory_path, *, today: date | None = None) -> dict:
    """The one response shape both endpoints return (R-FD7)."""
    today = today or date.today()
    tuning = load(memory_path)
    return {
        "bank": Path(memory_path).name,
        "window_days": WINDOW_DAYS,
        "tuning": tuning,
        "suggestions": suggest(await answers(memory_path, today=today), tuning),
    }
```

`api/services/git_service.py` — directly after `commit_resolution` (after `:1389`):

```python
# G147 — the manifest line `commit_resolution` writes for a decay answer. Its
# parser lives HERE, beside its producer, so the two cannot drift.
_DECAY_VERDICT_RE = re.compile(
    r"^entities/(?P<id>[^\s/]+)\.md: [^\n]*"
    r"\(trigger: inbox/decay/resolved:(?P<label>archive|keep_active)\)\s*$",
    re.MULTILINE,
)
_decay_verdict_cache: dict[tuple[str, str, str], dict[str, str]] = {}


async def decay_verdicts(memory_path: Path, *, since: date) -> dict[str, str]:
    """``{entity_id: label}`` — each page's LATEST decay answer committed since
    ``since`` (G147, plan R-FD6). ``archive`` / ``keep_active`` only: a
    ``remind_later`` is a deferral (``inbox/deferred``), never a verdict.

    Git's own ``--grep`` filters, as in :func:`get_sleep_history` — a bounded
    window that is not a matching window is a wrong answer, not a cheap one —
    and the body never leaves this function. Newest first, so the first line
    seen per page wins. ``--since`` ends the walk at the first commit older
    than the cutoff, so a clock-skewed old commit near HEAD would hide answers
    behind it — the same answer ``git log --since`` gives anywhere, accepted
    rather than walking all history. Cached per (bank, HEAD, since); the cache
    grows one entry per HEAD per day at most, the `_history_cache` trade-off.
    """
    from api.services import sync_service

    head = sync_service.git_head(memory_path)
    key = (str(memory_path), head, since.isoformat())
    # An empty HEAD (no commit yet, or a worktree/submodule bank whose `.git`
    # is a file `git_head` does not follow) cannot key a cache: it would
    # never move, and an answer given later today would stay invisible.
    cached = _decay_verdict_cache.get(key) if head else None
    if cached is not None:
        return dict(cached)
    try:
        output = await _run_git(
            memory_path, "log", f"--since={since.isoformat()}T00:00:00",
            "--fixed-strings", "--grep=inbox/decay/resolved:", "--format=%x1e%B",
        )
    except GitError:
        return {}
    latest: dict[str, str] = {}
    for record in output.split("\x1e"):
        for match in _DECAY_VERDICT_RE.finditer(record):
            latest.setdefault(match.group("id"), match.group("label"))
    if head:
        _decay_verdict_cache[key] = latest
    return dict(latest)
```

(`re`, `date`, `_run_git` and `GitError` already exist in `git_service`; confirm with `grep -n
"^import re\|^from datetime" api/services/git_service.py` before editing.)

`api/models/schemas.py` — after `EntityDecayUpdate` (`:533-542`):

```python
class DecaySuggestion(CamelModel):
    """G147 — one per-type pace suggestion. A type and counts only — never a
    page id or name (the payload of a Settings page, not of the graph)."""

    type: str
    direction: Literal["slower", "faster"]
    multiplier: float
    kept: int
    archived: int
    answers: int


class DecayTuningResponse(CamelModel):
    """``GET /memory/decay-suggestions`` and ``PUT /memory/decay-tuning`` (G147).
    Not a Store domain — fetched when Settings → Memory opens — so no ETag."""

    bank: str
    window_days: int
    tuning: dict[str, float] = {}
    suggestions: list[DecaySuggestion] = []
```

`api/routers/memory.py`:

```python
"""G147 — Settings → Memory's pace controls.

``GET /memory/decay-suggestions`` derives, from the bank's own decay answers,
which kinds of page the person keeps (or lets go of) far more often than
Cicada expected; ``PUT /memory/decay-tuning`` stores the pace they approve.
Neither is a Store domain, so neither carries an ETag (plan R-FD7).
"""

import asyncio
from datetime import date
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from api.config import Settings, get_settings
from api.models.schemas import DecayTuningResponse
from api.services import decay_tuning, git_service

router = APIRouter()

# One read-merge-write at a time in this process: two quick clicks (Apply,
# then Reset) must not both read the old file and drop each other's change.
_write_lock = asyncio.Lock()
BUSY = "Sleep is running — try again when it finishes"


@router.get("/memory/decay-suggestions", response_model=DecayTuningResponse)
async def get_decay_suggestions(settings: Settings = Depends(get_settings)):
    return DecayTuningResponse(**await decay_tuning.overview(settings.memory_path))


@router.put("/memory/decay-tuning", response_model=DecayTuningResponse)
async def put_decay_tuning(
    changes: dict[str, Optional[float]] = Body(...),
    settings: Settings = Depends(get_settings),
):
    """Merge ``{type: multiplier | null}`` into ``_decay_tuning.yaml``.

    409 while Sleep runs: Stage 3 reads this file, and a file written but not
    yet committed would ride the next ``git add -A`` writer's commit under the
    model's author (the G85 smear; `routers/projects.py`'s guard). The commit is
    this one file, as the person.
    """
    from api.services import sleep_cycle

    if sleep_cycle.get_sleep_state().status == "running":
        raise HTTPException(409, BUSY)
    async with _write_lock:
        try:
            tuning = decay_tuning.merge(decay_tuning.load(settings.memory_path), changes)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if decay_tuning.save(settings.memory_path, tuning):
            message = git_service.build_commit_message(
                f"Decay tuning {date.today().isoformat()}",
                [f"{decay_tuning.FILE}: updated (trigger: user/companion_app)"],
                authors=["user"],
            )
            await git_service.commit_paths(settings.memory_path, message, [decay_tuning.FILE])
    return DecayTuningResponse(**await decay_tuning.overview(settings.memory_path))
```

`api/main.py` — add `memory,` to the `from api.routers import (…)` list between
`maintenance,` and `nudges,`, and after `app.include_router(maintenance.router, …)`:

```python
app.include_router(memory.router, tags=["memory"])
```

`api/services/conflict_resolver.py` — replace Task 1's `tuning = tuning or {}` with:

```python
    if tuning is None:
        # G147: the per-type pace the person approved in Settings → Memory. One
        # small file read per cycle; a demo or test settings object without a
        # bank path has none.
        memory_path = getattr(settings, "memory_path", None)
        tuning = decay_tuning.load(memory_path) if memory_path else {}
```

and add `decay_tuning` to its `from api.services import …` line.

- [ ] **Step 4: Green, then the suites.**
  `api/.venv/bin/python -m pytest api/tests/test_decay_tuning.py api/tests/test_decay_spacing.py api/tests/test_demo_capture_routes.py -q -p no:cacheprovider`
  → pass; then the full `api/tests` → 0 failures.

- [ ] **Step 5: Commit.**
  `git add api/services/decay_tuning.py api/services/git_service.py api/routers/memory.py api/main.py api/models/schemas.py api/services/conflict_resolver.py api/tests/test_decay_tuning.py`
  → subject
  `feat(decay): per-type pace — suggested from the bank's own decay answers, applied only by the person (G147)`.

---

### Task 3: Claims fade by spacing and the subject's pace

**Files:**
- Modify: `api/services/decay_policy.py` (imports: `decay_tuning`; `class_lookup` `:133-156`
  rewritten; `SubjectDecay`, `NEUTRAL_SUBJECT`, `subject_lookup`, `claim_mention_weeks` added)
- Modify: `api/services/claim_reconciler.py:44-48` (alias), `:529-567` (signature + defaults),
  `:639` (call), `:663-700` (`_decay_claims`)
- Test: `api/tests/test_decay_spacing.py` (append a claims section)

**Interfaces:**
- Produces: `decay_policy.SubjectDecay(decay_class, entity_type, kept_on, type_multiplier)`,
  `NEUTRAL_SUBJECT`, `subject_lookup(memory_path, *, tuning=None)`,
  `claim_mention_weeks(claim, kept_on=()) -> int`;
  `reconcile_stage3(…, decay_class_fn=None, subject_fn=None)`.
- Consumes: Task 1's `mention_weeks`, `stability`, `spacing_params`, `entity_type`,
  `kept_dates`; Task 2's `decay_tuning.load`.

- [ ] **Step 1: Failing tests** — append to `api/tests/test_decay_spacing.py`:

```python
# --- claims (R-FD4, R-FD5, R-FD13) --------------------------------------------

from api.services import decay_tuning, predicates  # noqa: E402
from api.services.claim_reconciler import reconcile_stage3  # noqa: E402
from api.services.claims import Claim, Evidence  # noqa: E402


class _ClaimSettings:
    def __init__(self, memory_path: Path):
        self.memory_path = memory_path
        self.archive_threshold = 0.2
        self.decay_nudge_threshold = 0.4
        self.litellm_model = "test-model"


def _claim(cid: str, episodes=(), evidence=()) -> Claim:
    return Claim(
        id=cid, text="alpha-project uses postgres", subject="alpha-project", predicate="uses",
        object="postgres", epistemic="explicit", source_trust="agent_extracted", confidence=0.9,
        valid_from="2026-01-01", recorded_at="2026-01-01", decayed_through="2026-01-01",
        source_episodes=list(episodes), evidence=list(evidence),
    )


def _one_week_drop(root: Path, claim: Claim, **kw) -> float:
    predicates.install_predicate_map(root)
    reconciled, _nudges, _audit = reconcile_stage3(
        [], {"alpha-project": [claim]}, _ClaimSettings(root),
        cardinality_fn=lambda _p: True, now_date="2026-01-08", **kw,
    )
    return 0.9 - reconciled["alpha-project"][0].confidence


def test_a_claim_restated_across_twelve_weeks_fades_at_the_spaced_rate(tmp_path):
    burst = _one_week_drop(tmp_path, _claim("c1", ["ep_2025-10-06_001", "ep_2025-10-07_002"]))
    spaced = _one_week_drop(tmp_path, _claim("c2", _weekly("2025-10-06", 12)))
    assert burst == pytest.approx(0.02)  # explicit x agent_extracted x active x one week
    assert spaced == pytest.approx(0.02 * decay_policy.stability(12))


def test_evidence_documents_count_but_page_citations_and_sessions_do_not(tmp_path):
    ev = [Evidence(episode=e, start=0, end=4, kind="user", hash="x") for e in _weekly("2025-10-06", 4)]
    ev.append(Evidence(episode="media-alpha", start=0, end=4, kind="page", hash="y"))
    claim = _claim("c3", evidence=ev)
    claim.session_ids = ["ses_a", "ses_b", "ses_c"]
    assert decay_policy.claim_mention_weeks(claim) == 4
    assert _one_week_drop(tmp_path, claim) == pytest.approx(0.02 * decay_policy.stability(4))


def test_a_claim_with_nothing_dated_decays_exactly_as_before(tmp_path):
    assert _one_week_drop(tmp_path, _claim("c4")) == pytest.approx(0.02)


def test_the_subjects_kept_weeks_count_for_its_claims(tmp_path):
    (tmp_path / "entities").mkdir()
    markdown_parser.write(
        tmp_path / "entities" / "alpha-project.md",
        {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.5,
         "kept_on": ["2025-11-03", "2025-12-01"]},
        "A synthetic page.\n",
    )
    drop = _one_week_drop(tmp_path, _claim("c5", ["ep_2025-10-06_001"]))
    assert drop == pytest.approx(0.02 * decay_policy.stability(3))


def test_claim_decay_multiplies_by_the_subjects_type_pace(tmp_path):
    (tmp_path / "entities").mkdir()
    markdown_parser.write(
        tmp_path / "entities" / "alpha-project.md",
        {"name": "Alpha Project", "type": "project", "status": "active", "confidence": 0.5},
        "A synthetic page.\n",
    )
    decay_tuning.save(tmp_path, {"project": 0.5})
    assert _one_week_drop(tmp_path, _claim("c6")) == pytest.approx(0.01)


def test_an_injected_subject_fn_is_honoured(tmp_path):
    about = decay_policy.SubjectDecay(DecayClass.active, "project", (), 0.5)
    assert _one_week_drop(tmp_path, _claim("c7"), subject_fn=lambda _s: about) == pytest.approx(0.01)


def test_an_injected_class_fn_still_wins_over_the_page(tmp_path):
    drop = _one_week_drop(tmp_path, _claim("c8"), decay_class_fn=lambda _s: DecayClass.volatile)
    assert drop == pytest.approx(0.04)


def test_class_lookup_keeps_its_contract(tmp_path):
    (tmp_path / "entities").mkdir()
    markdown_parser.write(tmp_path / "entities" / "a.md", {"type": "skill"}, "x\n")
    lookup = decay_policy.class_lookup(tmp_path)
    assert lookup("a") is DecayClass.durable
    assert lookup("nobody") is DecayClass.active


def test_subject_lookup_reads_the_page_once_and_neutral_for_a_missing_one(tmp_path):
    (tmp_path / "entities").mkdir()
    markdown_parser.write(tmp_path / "entities" / "bob-example.md",
                          {"type": "person", "kept_on": ["2026-08-10"]}, "x\n")
    lookup = decay_policy.subject_lookup(tmp_path, tuning={"person": 0.5})
    assert lookup("bob-example") == decay_policy.SubjectDecay(
        DecayClass.active, "person", ("2026-08-10",), 0.5)
    assert lookup("nobody") == decay_policy.NEUTRAL_SUBJECT


def test_no_bank_path_means_neutral_subjects_never_the_cwd(tmp_path, monkeypatch):
    """The reconciler never resolves a bank from the process's working
    directory (the split-brain rule, R-FD13): a settings object with no bank
    path reads no page, however the cwd looks."""
    (tmp_path / "entities").mkdir()
    markdown_parser.write(tmp_path / "entities" / "alpha-project.md", {"type": "skill"}, "x\n")
    monkeypatch.chdir(tmp_path)
    reconciled, _nudges, _audit = reconcile_stage3(
        [], {"alpha-project": [_claim("c9")]}, _ClaimSettings(None),
        cardinality_fn=lambda _p: True, now_date="2026-01-08",
    )
    assert 0.9 - reconciled["alpha-project"][0].confidence == pytest.approx(0.02)
```

- [ ] **Step 2: Run — red.**
  `api/.venv/bin/python -m pytest api/tests/test_decay_spacing.py -q -p no:cacheprovider`
  → `AttributeError: … has no attribute 'claim_mention_weeks'` / `'SubjectDecay'`.

- [ ] **Step 3: Implement.**

`api/services/decay_policy.py` — add `decay_tuning` to the services import
(`from api.services import decay_tuning, episode_ids, markdown_parser`; `decay_tuning` imports
only `yaml` and `schemas` at module level, so there is no cycle) and replace `class_lookup`
(`:133-156`) with:

```python
class SubjectDecay(NamedTuple):
    """What the claim engine needs about a claim's SUBJECT page (G147, R-FD13)."""

    decay_class: DecayClass
    entity_type: str
    kept_on: tuple[str, ...]
    type_multiplier: float


# An unknown or unreadable subject: the neutral 1.0 class multiplier, no keeps,
# no pace — a page-less subject decays exactly as it did before G66 and G147.
NEUTRAL_SUBJECT = SubjectDecay(DecayClass.active, "", (), 1.0)


def subject_lookup(memory_path, *, tuning: dict[str, float] | None = None) -> Callable[[str], SubjectDecay]:
    """A memoised ``entity_id -> SubjectDecay`` reader for one bank.

    One parse per subject yields the class (G66), the type (the key of the
    per-type pace, R-FD5) and the page's kept weeks (R-FD3), so the claim
    engine never walks the same files twice. ``tuning=None`` reads the bank's
    ``_decay_tuning.yaml`` lazily, on the first page found — an MCP write, whose
    one subject is always referenced, never reads it.
    """
    entities_dir = Path(memory_path) / "entities"
    cache: dict[str, SubjectDecay] = {}
    pace: list[dict[str, float]] = [] if tuning is None else [dict(tuning)]

    def pace_for(etype: str) -> float:
        if not pace:
            pace.append(decay_tuning.load(memory_path))
        return float(pace[0].get(etype, 1.0))

    def lookup(entity_id: str) -> SubjectDecay:
        eid = str(entity_id or "")
        if eid in cache:
            return cache[eid]
        found = NEUTRAL_SUBJECT
        filepath = entities_dir / f"{eid}.md"
        if eid and filepath.exists():
            try:
                fm = markdown_parser.parse(filepath).frontmatter or {}
                etype = entity_type(fm)
                found = SubjectDecay(resolve(fm)[0], etype, tuple(kept_dates(fm)), pace_for(etype))
            except Exception:
                found = NEUTRAL_SUBJECT
        cache[eid] = found
        return found

    return lookup


def class_lookup(memory_path) -> Callable[[str], DecayClass]:
    """A memoised ``entity_id -> DecayClass`` reader for one bank.

    Injected into the claim engine so it can weight a claim by its SUBJECT's
    class without the reconciler growing a filesystem dependency. Unknown /
    unreadable ids resolve to ``DecayClass.active`` (the neutral 1.0
    multiplier). Since G147 it is :func:`subject_lookup`'s class column; the
    empty ``tuning`` means a class-only caller never reads the pace file.
    """
    subject = subject_lookup(memory_path, tuning={})
    return lambda entity_id: subject(entity_id).decay_class


def claim_mention_weeks(claim, kept_on=()) -> int:
    """Distinct ISO weeks a claim was stated or restated in (R-FD4): its
    ``source_episodes`` and the ``ep_*`` documents its evidence cites (a ``page``
    span cites an entity, not a conversation), plus the subject's kept weeks.
    Session ids carry no date and ``recorded_at`` moves on every restatement,
    so neither counts. Duck-typed on ``Claim`` to keep this module import-light.
    """
    refs = list(getattr(claim, "source_episodes", None) or [])
    for ev in getattr(claim, "evidence", None) or []:
        doc = str(getattr(ev, "episode", "") or "")
        if doc.startswith("ep_"):
            refs.append(doc)
    return mention_weeks(refs, kept_on)
```

`api/services/claim_reconciler.py`:

After `DecayClassFn = Callable[[str], DecayClass]` (`:47`):

```python
# A subject oracle (G147): the subject page's class, type, kept weeks and the
# per-type pace, read once per subject (`decay_policy.subject_lookup`).
SubjectFn = Callable[[str], "decay_policy.SubjectDecay"]
```

`reconcile_stage3` signature gains `subject_fn: SubjectFn | None = None,` after
`decay_class_fn`; its docstring gains: ``subject_fn``: ``subject_id -> SubjectDecay`` (G147) —
the subject's per-type pace and kept weeks; defaults to ``decay_policy.subject_lookup`` for
``settings.memory_path``, or ``NEUTRAL_SUBJECT`` for every subject when there is no bank path.
Replace `:564-565` with:

```python
    memory_path = getattr(settings, "memory_path", None)
    if subject_fn is None:
        # No bank path, no page to read: every subject is neutral. Never "." —
        # this module does not resolve a bank from the process's cwd (R-FD13).
        subject_fn = (decay_policy.subject_lookup(memory_path) if memory_path
                      else (lambda _sid: decay_policy.NEUTRAL_SUBJECT))
    if decay_class_fn is None:
        # One parse per subject: the class is the subject reader's own column.
        decay_class_fn = lambda sid: subject_fn(sid).decay_class  # noqa: E731
```

`:639` becomes
`_decay_claims(reconciled, referenced_subjects, settings, nudges, today, decay_class_fn, subject_fn)`.

`_decay_claims` gains the `subject_fn: SubjectFn` parameter (last). After the two threshold
lines add `alpha, floor = decay_policy.spacing_params(settings)`. After the evergreen
`continue` (`:679-680`) add:

```python
        # G147: the subject's per-type pace (the person's choice, R-FD5) and its
        # "keep" weeks — read once per subject, like the class above.
        about = subject_fn(subject)
```

and replace `:700` with:

```python
            # G147 (R-FD4): a belief restated across many weeks fades slower than
            # one heard in a single burst — weeks from what the claim already
            # records, plus the subject's kept weeks.
            spacing = decay_policy.stability(
                decay_policy.claim_mention_weeks(c, about.kept_on), alpha=alpha, floor=floor
            )
            amount = (base * factor * multiplier * about.type_multiplier * spacing
                      * (charged_days / 7.0))
```

- [ ] **Step 4: Green, then the suites.**
  `api/.venv/bin/python -m pytest api/tests/test_decay_spacing.py api/tests/test_decay_engines.py api/tests/test_claim_reconciler.py api/tests/test_decay_watermark_migration.py api/tests/test_agentic_write.py -q -p no:cacheprovider`
  → pass; then the full `api/tests` → 0 failures.

- [ ] **Step 5: Commit.**
  `git add api/services/decay_policy.py api/services/claim_reconciler.py api/tests/test_decay_spacing.py`
  → subject
  `feat(decay): claims fade by spacing too — weeks from their episodes and evidence, and the subject's pace (G147)`.

---

### Task 4: The pace on the wire and on the entity card

**Files:**
- Modify: `api/models/schemas.py` (`EntityDecay` before `EntityResponse`, `:453`;
  `EntityResponse.decay`)
- Modify: `api/routers/entities.py:12-50` (imports), `:74-95` (build)
- Test: `api/tests/test_decay_endpoint.py` (append)
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/Entity.swift` (`EntityDecay`; `Entity.decay`
  `:649`, CodingKeys `:702`, decode `:718`)
- Create: `app/CicadaApp/Sources/CicadaApp/Models/FadeWords.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift:646-669`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Graph.swift:106` (`fadesHelp`)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/CountLiteralLintTests.swift` (scope)
- Test: `app/CicadaApp/Tests/CicadaAppTests/FadeWordsTests.swift` (new)

**Interfaces:**
- Produces: wire `EntityResponse.decay = {class, effectiveRatePerWeek, mentionWeeks}`; Swift
  `EntityDecay`, `Entity.decay: EntityDecay?`, `FadeWords.Pace`, `FadeWords.pace(ratePerWeek:)`,
  `FadeWords.detail(_:fallback:locale:)`.
- Consumes: `decay_policy.effective`, `spacing_params`, `decay_tuning.load`;
  `DetailsWords.fades`, `UsageFormat.count(_:locale:)`.

- [ ] **Step 1: Failing tests.**

Append to `api/tests/test_decay_endpoint.py` (it already has `_memory`, `_FakeSettings`, `run`):

```python
# --- G147: the derived pace (plan R-FD9, R-FD11) -------------------------------

from datetime import date as _date, datetime as _datetime, timedelta as _timedelta  # noqa: E402

from api.services import conflict_resolver, decay_policy, decay_tuning  # noqa: E402


def _weekly(n: int) -> list[str]:
    return [f"ep_{(_date(2026, 3, 2) + _timedelta(days=7 * i)).isoformat()}_001" for i in range(n)]


def test_entity_response_carries_the_derived_decay_block(tmp_path):
    repo = _memory(tmp_path, decay_class="active", source_episodes=_weekly(12))
    resp = run(entities_router.get_entity("mongodb", settings=_FakeSettings(repo)))
    rate = round(0.05 * decay_policy.stability(12), 6)
    assert resp.model_dump(mode="json")["decay"] == {
        "class": "active", "effectiveRatePerWeek": rate, "mentionWeeks": 12,
    }
    assert resp.decay_rate == 0.05  # the base keeps its meaning for older readers


def test_the_decay_block_reads_the_bank_pace_and_evergreen_is_zero(tmp_path):
    repo = _memory(tmp_path)  # a `tool`, active, no episodes
    decay_tuning.save(repo, {"tool": 0.5})
    resp = run(entities_router.get_entity("mongodb", settings=_FakeSettings(repo)))
    assert resp.decay.effective_rate_per_week == 0.025
    media = _memory(tmp_path / "second", type="media")
    assert run(entities_router.get_entity("mongodb", settings=_FakeSettings(media))).decay.effective_rate_per_week == 0.0


def test_the_card_and_the_pass_agree(tmp_path):
    repo = _memory(tmp_path, decay_class="active", confidence=0.8, source_episodes=_weekly(4))
    resp = run(entities_router.get_entity("mongodb", settings=_FakeSettings(repo)))

    class _Sleep(_FakeSettings):
        archive_threshold = 0.2
        decay_nudge_threshold = 0.4

    fm = markdown_parser.parse(repo / "entities" / "mongodb.md").frontmatter
    changes = run(conflict_resolver.resolve_and_prune(
        [], [{"id": "mongodb", "frontmatter": fm, "body": ""}], _Sleep(repo),
        now=_datetime(2026, 9, 1),
    ))
    assert 0.8 - changes[0]["new_confidence"] == pytest.approx(resp.decay.effective_rate_per_week, abs=1e-6)
```

Create `app/CicadaApp/Tests/CicadaAppTests/FadeWordsTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G147 (plan R-FD9, R-FD10) — the entity card says the pace Sleep actually charges, in words.
final class FadeWordsTests: XCTestCase {
    private let us = Locale(identifier: "en_US")

    private func decay(_ cls: DecayClass, _ rate: Double, _ weeks: Int) -> EntityDecay {
        EntityDecay(decayClass: cls, effectiveRatePerWeek: rate, mentionWeeks: weeks)
    }

    func testPaceThresholdsAreAnchoredOnTheActiveRate() {
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0), .never)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.0125), .verySlowly, "the spacing floor on an active page")
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.0126), .slowly)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.03), .slowly)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.05), .usual)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.0799), .usual)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.08), .quickly)
        XCTAssertEqual(FadeWords.pace(ratePerWeek: 0.15), .quickly)
    }

    func testTheDetailsRowSaysThePaceAndTheWeeks() {
        XCTAssertEqual(FadeWords.detail(decay(.active, 0.020073, 12), fallback: .active, locale: us),
                       "Slowly — mentioned across 12 weeks")
        XCTAssertEqual(FadeWords.detail(decay(.active, 0.05, 1), fallback: .active, locale: us),
                       "At the usual pace — mentioned in a single week")
        XCTAssertEqual(FadeWords.detail(decay(.durable, 0.010918, 4), fallback: .durable, locale: us),
                       "Very slowly — mentioned across 4 weeks")
        XCTAssertEqual(FadeWords.detail(decay(.evergreen, 0, 30), fallback: .evergreen, locale: us), "Never")
        XCTAssertEqual(FadeWords.detail(decay(.volatile, 0.15, 0), fallback: .volatile, locale: us), "Quickly")
        XCTAssertEqual(FadeWords.detail(decay(.active, 0.0125, 1200), fallback: .active, locale: us),
                       "Very slowly — mentioned across 1,200 weeks")
    }

    func testAnOlderBackendKeepsTheClassWords() {
        XCTAssertEqual(FadeWords.detail(nil, fallback: .durable, locale: us), DetailsWords.fades(.durable))
        XCTAssertEqual(FadeWords.detail(nil, fallback: .active, locale: us), "If it stops coming up")
    }

    private func entityJSON(_ decay: String?) -> Data {
        let block = decay.map { #", "decay": \#($0)"# } ?? ""
        return """
        {"id": "mongodb", "name": "MongoDB", "type": "tool", "status": "active",
         "confidence": 0.8, "created": "2026-01-01", "lastReferenced": "2026-08-01",
         "decayRate": 0.05, "decayClass": "active", "version": 1,
         "markdownContent": "", "history": []\(block)}
        """.data(using: .utf8)!
    }

    func testTheEntityDecodesTheDecayBlock() throws {
        let entity = try JSONDecoder().decode(Entity.self, from: entityJSON(
            #"{"class": "active", "effectiveRatePerWeek": 0.020073, "mentionWeeks": 12}"#))
        XCTAssertEqual(entity.decay, EntityDecay(decayClass: .active, effectiveRatePerWeek: 0.020073, mentionWeeks: 12))
    }

    func testAMissingOrBrokenBlockIsNilAndAnUnknownClassIsActive() throws {
        XCTAssertNil(try JSONDecoder().decode(Entity.self, from: entityJSON(nil)).decay)
        XCTAssertNil(try JSONDecoder().decode(Entity.self, from: entityJSON(#"{"class": "active"}"#)).decay)
        let glacial = try JSONDecoder().decode(Entity.self, from: entityJSON(
            #"{"class": "glacial", "effectiveRatePerWeek": 0.05, "mentionWeeks": 2}"#))
        XCTAssertEqual(glacial.decay?.decayClass, .active)
    }

    func testTheCardsFadesRowReadsTheEffectivePace() throws {
        let card = try ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "EntityDetailCard.swift" }
        let text = try String(contentsOf: XCTUnwrap(card), encoding: .utf8)
        XCTAssertTrue(text.contains("FadeWords.detail(entity.decay, fallback: entity.decayClass)"))
    }
}
```

- [ ] **Step 2: Run — red.**
  `api/.venv/bin/python -m pytest api/tests/test_decay_endpoint.py -q -p no:cacheprovider` →
  the three new tests fail (`KeyError: 'decay'` from the dumped body, then
  `AttributeError: 'EntityResponse' object has no attribute 'decay'`); the existing ones pass;
  `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay/app/CicadaApp && swift test --filter FadeWordsTests 2>&1 | tail -20` → compile failure
  (`EntityDecay`, `FadeWords` do not exist).

- [ ] **Step 3: Implement.**

`api/models/schemas.py` — before `class EntityResponse` (`:453`):

```python
class EntityDecay(CamelModel):
    """G147 — the pace Sleep charges this page, derived at read by
    ``decay_policy.effective`` (the pass's own function) and never stored.
    ``class`` by explicit alias (a Python keyword as a field name is not an
    option); ``decayRate`` beside it keeps meaning the base (plan R-FD9)."""

    decay_class: DecayClass = Field(alias="class")
    effective_rate_per_week: float
    mention_weeks: int
```

and in `EntityResponse`, after `is_owner`:

```python
    # G147 — derived at read (never stored); None only for a caller that
    # builds an EntityResponse without a page. Additive: an older client
    # ignores it and keeps showing the class.
    decay: Optional[EntityDecay] = None
```

`api/routers/entities.py` — add `EntityDecay` to the schemas import and `decay_tuning` to the
services import; after `decay_class, decay_rate = decay_policy.resolve(fm)` (`:74`):

```python
    # G147 — the pace the decay pass actually charges, from the SAME function
    # (`decay_policy.effective`, plan R-FD11), so the card can never describe a
    # pace Sleep does not charge. Read time only; nothing is stored.
    alpha, floor = decay_policy.spacing_params(settings)
    effective = decay_policy.effective(
        fm, alpha=alpha, floor=floor, tuning=decay_tuning.load(settings.memory_path)
    )
```

and in the `EntityResponse(…)` call after `is_owner=…`:

```python
        decay=EntityDecay(
            decay_class=effective.decay_class,
            effective_rate_per_week=round(effective.rate, 6),
            mention_weeks=effective.mention_weeks,
        ),
```

`Models/Entity.swift` — after the `DecayClass` enum (before `struct Entity`):

```swift
/// G147 — the pace Sleep actually charges this page, derived at read by the backend
/// (`decay_policy.effective`, the same function the decay pass calls): the class's base
/// rate × the spacing factor over distinct mention weeks × the bank's per-type pace.
/// Never stored. Lenient: an unknown class reads `.active`; a block missing its numbers
/// fails alone (the entity decodes with `decay == nil`) and the card falls back to the
/// class's own words.
struct EntityDecay: Codable, Equatable {
    var decayClass: DecayClass
    var effectiveRatePerWeek: Double
    var mentionWeeks: Int

    enum CodingKeys: String, CodingKey {
        case decayClass = "class"
        case effectiveRatePerWeek, mentionWeeks
    }

    init(decayClass: DecayClass, effectiveRatePerWeek: Double, mentionWeeks: Int) {
        self.decayClass = decayClass
        self.effectiveRatePerWeek = effectiveRatePerWeek
        self.mentionWeeks = mentionWeeks
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        decayClass = (try? c.decode(DecayClass.self, forKey: .decayClass)) ?? .active
        effectiveRatePerWeek = try c.decode(Double.self, forKey: .effectiveRatePerWeek)
        mentionWeeks = try c.decode(Int.self, forKey: .mentionWeeks)
    }
}
```

In `struct Entity`, after `var decayClass: DecayClass = .active` (`:649`):

```swift
    /// G147 — the effective pace (`EntityDecay`); nil from an older backend or a graph stub.
    var decay: EntityDecay? = nil
```

CodingKeys `:702` becomes `case decayRate, decayClass, decay, sourceEpisodes, tags, related, version`;
after `:718` add:

```swift
        decay = (try? c.decodeIfPresent(EntityDecay.self, forKey: .decay)) ?? nil
```

Create `Models/FadeWords.swift`:

```swift
import Foundation

/// G147 — how fast a page fades, in words a person reads (plan R-FD10).
///
/// The pace comes from the rate Sleep actually charges (`EntityDecay.effectiveRatePerWeek`),
/// not the class label, so a page that came up across twelve weeks reads "Slowly" even in
/// the default class. Thresholds are anchored on the default `active` rate, 0.05 a week: at
/// or under a quarter of it (the spacing floor) is "Very slowly", at or under 0.6 of it
/// (about four spaced weeks) is "Slowly", under 1.6 of it is the usual pace, anything faster
/// is "Quickly". Counts go through `UsageFormat.count` (DR-21).
enum FadeWords {
    enum Pace: Equatable {
        case never, verySlowly, slowly, usual, quickly

        var word: String {
            switch self {
            case .never: "Never"
            case .verySlowly: "Very slowly"
            case .slowly: "Slowly"
            case .usual: "At the usual pace"
            case .quickly: "Quickly"
            }
        }
    }

    static let verySlowlyMax = 0.0125
    static let slowlyMax = 0.03
    static let usualBelow = 0.08

    static func pace(ratePerWeek rate: Double) -> Pace {
        if rate <= 0 { return .never }
        if rate <= verySlowlyMax { return .verySlowly }
        if rate <= slowlyMax { return .slowly }
        if rate < usualBelow { return .usual }
        return .quickly
    }

    /// The Details row's value: "Slowly — mentioned across 12 weeks". No block (an older
    /// backend) → the class's own words, exactly as before G147.
    static func detail(_ decay: EntityDecay?, fallback: DecayClass,
                       locale: Locale = .autoupdatingCurrent) -> String {
        guard let decay else { return DetailsWords.fades(fallback) }
        let pace = pace(ratePerWeek: decay.effectiveRatePerWeek)
        guard pace != .never else { return pace.word }
        switch decay.mentionWeeks {
        case ..<1:
            return pace.word
        case 1:
            return "\(pace.word) — mentioned in a single week"
        default:
            return "\(pace.word) — mentioned across \(UsageFormat.count(decay.mentionWeeks, locale: locale)) weeks"
        }
    }
}
```

`Views/Graph/EntityDetailCard.swift` — after `shownDecayClass` (`:646`) add:

```swift
    /// G147 (R-FD10) — the value is the pace Sleep actually charges ("Slowly — mentioned across
    /// 12 weeks"), not only the class word; while an override is in flight it shows the chosen
    /// class's own words until the reload lands (the optimistic flip).
    private var fadesLabel: String {
        if let pendingDecayClass { return DetailsWords.fades(pendingDecayClass) }
        return FadeWords.detail(entity.decay, fallback: entity.decayClass)
    }
```

and in `fadesMenu` replace `Text(DetailsWords.fades(shownDecayClass))` with `Text(fadesLabel)`
and the accessibility label with
`.accessibilityLabel("\(Copy.Graph.fades): \(fadesLabel)")`. Nothing else in the card changes.

`Theme/Copy+Graph.swift:106`:

```swift
    static let fadesHelp = "How fast this fades when it stops coming up — the more weeks it came up in, the slower"
```

`CountLiteralLintTests.swift` — append `"/Models/FadeWords.swift",` to `scope` (after
`"/Models/RelativeDay.swift",`) and add "— and G147's pace words (FadeWords)" to the scope's
docstring.

- [ ] **Step 4: Green, then the suites.**
  `api/.venv/bin/python -m pytest api/tests/test_decay_endpoint.py -q -p no:cacheprovider` →
  pass; full `api/tests` → 0 failures.
  `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay/app/CicadaApp && swift build 2>&1 | tail -5` → success;
  `swift test --filter "FadeWordsTests|DecayClassTests|EntityContentTests|CountLiteralLintTests" 2>&1 | tail -20`
  → pass; then `swift test 2>&1 | tail -20` → 0 failures.

- [ ] **Step 5: Commit.**
  `git add api/models/schemas.py api/routers/entities.py api/tests/test_decay_endpoint.py app/CicadaApp/Sources/CicadaApp/Models/Entity.swift app/CicadaApp/Sources/CicadaApp/Models/FadeWords.swift app/CicadaApp/Sources/CicadaApp/Views/Graph/EntityDetailCard.swift app/CicadaApp/Sources/CicadaApp/Theme/Copy+Graph.swift app/CicadaApp/Tests/CicadaAppTests/CountLiteralLintTests.swift app/CicadaApp/Tests/CicadaAppTests/FadeWordsTests.swift`
  → subject
  `feat(decay): the pace on the wire and on the card — "Slowly — mentioned across 12 weeks" (G147; DR-16, DR-21, DR-38, DR-39, DR-59)`.

---

### Task 5: Settings → Memory — "How things fade"

**Files:**
- Create: `app/CicadaApp/Sources/CicadaApp/Models/DecayTuning.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Models/FadeWords.swift` (nouns + suggestion copy)
- Create: `app/CicadaApp/Sources/CicadaApp/Views/Settings/FadePaceCard.swift`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Settings/MemoryView.swift` (host the card)
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsRowID.swift:55-56`
- Modify: `app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsIndex.swift:76, 109-110`
- Modify: `app/CicadaApp/Sources/CicadaApp/Theme/Copy+Settings.swift:152-161`
- Modify: `app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift` (after `:2109`)
- Modify: `app/CicadaApp/Tests/CicadaAppTests/CountLiteralLintTests.swift` (scope)
- Test: `app/CicadaApp/Tests/CicadaAppTests/DecayTuningTests.swift` (new)

**Interfaces:**
- Produces: `DecayTuningResponse`, `DecaySuggestion` (+ `Direction`), `FadeTypeRow`,
  `DecayTuningModel.{notNowKey, notNowRepeat, notNowID, decodeNotNow, encodeNotNow, isHidden,
  rows}`, `FadeWords.{noun, suggestionTitle, suggestionDetail, tunedTitle, tunedDetail}`,
  `FadePaceCard`, `SettingsRowID.fadePace`, `SettingsRowID.fadeType(_:)`,
  `APIClient.fetchDecayTuning()`, `APIClient.setDecayTuning(_:)`.
- Consumes: Task 2's endpoints; `SettingsGroupCard`, `SettingsRow`, `SettingsDivider`,
  `NeutralButton`, `TextButton`, `Store.invalidateAllEntities()`, `UsageFormat.count`.

- [ ] **Step 1: Failing tests** — create `DecayTuningTests.swift`:

```swift
import XCTest
@testable import CicadaApp

/// G147 (plan R-FD6 … R-FD8) — Settings → Memory's pace rows. The wire decodes leniently,
/// the rows are a pure function of the response and the viewer's "Not now"s, and the copy
/// says each number once, in plain words.
final class DecayTuningTests: XCTestCase {
    override func tearDown() {
        MockURLProtocol.handler = nil
        super.tearDown()
    }

    private let us = Locale(identifier: "en_US")

    private func suggestion(type: String = "person", direction: DecaySuggestion.Direction = .slower,
                            kept: Int = 9, archived: Int = 1) -> DecaySuggestion {
        DecaySuggestion(type: type, direction: direction, multiplier: direction == .slower ? 0.5 : 1.5,
                        kept: kept, archived: archived, answers: kept + archived)
    }

    // MARK: Wire

    func testTheResponseDecodesAndDropsOnlyTheSuggestionItCannotRead() throws {
        let json = """
        {"bank": "memory", "windowDays": 180, "tuning": {"tool": 1.5},
         "suggestions": [
           {"type": "person", "direction": "slower", "multiplier": 0.5, "kept": 9, "archived": 1, "answers": 10},
           {"type": "person", "direction": "sideways", "multiplier": 0.5, "kept": 9, "archived": 1, "answers": 10}
         ]}
        """.data(using: .utf8)!
        let r = try JSONDecoder().decode(DecayTuningResponse.self, from: json)
        XCTAssertEqual(r.bank, "memory")
        XCTAssertEqual(r.tuning, ["tool": 1.5])
        XCTAssertEqual(r.suggestions, [suggestion()])
    }

    func testAnEmptyBodyStillDecodes() throws {
        let r = try JSONDecoder().decode(DecayTuningResponse.self, from: Data("{}".utf8))
        XCTAssertEqual(r.suggestions, [])
        XCTAssertEqual(r.tuning, [:])
        XCTAssertEqual(r.windowDays, 180)
    }

    // MARK: Rows

    func testSuggestionsComeFirstThenChosenPacesAndNeverATypeTwice() {
        let r = DecayTuningResponse(bank: "memory", tuning: ["person": 1.5, "tool": 0.5],
                                    suggestions: [suggestion()])
        let rows = DecayTuningModel.rows(r, notNow: [:])
        XCTAssertEqual(rows.map(\.type), ["person", "tool"])
        XCTAssertEqual(rows[0].kind, .suggestion(suggestion()))
        XCTAssertEqual(rows[0].current, 1.5)
        XCTAssertEqual(rows[1].kind, .tuned(0.5))
    }

    func testNotNowHidesASuggestionUntilFiveMoreAnswersPerBank() {
        let s = suggestion()
        let notNow = [DecayTuningModel.notNowID(bank: "memory", s): 10]
        XCTAssertTrue(DecayTuningModel.isHidden(s, bank: "memory", notNow: notNow))
        XCTAssertTrue(DecayTuningModel.isHidden(suggestion(kept: 13), bank: "memory", notNow: notNow))
        XCTAssertFalse(DecayTuningModel.isHidden(suggestion(kept: 14), bank: "memory", notNow: notNow))
        XCTAssertFalse(DecayTuningModel.isHidden(s, bank: "other", notNow: notNow), "a Not now is per bank")
        let r = DecayTuningResponse(bank: "memory", tuning: ["person": 1.5], suggestions: [s])
        XCTAssertEqual(DecayTuningModel.rows(r, notNow: notNow).map(\.kind), [.tuned(1.5)],
                       "a hidden suggestion leaves the chosen pace's own row")
    }

    func testNotNowRoundTripsAndToleratesJunk() {
        let map = ["memory|person|slower": 10]
        XCTAssertEqual(DecayTuningModel.decodeNotNow(DecayTuningModel.encodeNotNow(map)), map)
        XCTAssertEqual(DecayTuningModel.decodeNotNow("not json"), [:])
        XCTAssertEqual(DecayTuningModel.decodeNotNow(""), [:])
    }

    // MARK: Copy (DR-21, DR-59)

    func testCopySaysEachNumberOnceInPlainWords() {
        XCTAssertEqual(FadeWords.suggestionTitle(suggestion()), "Let people fade more slowly?")
        XCTAssertEqual(FadeWords.suggestionDetail(suggestion(), current: nil, locale: us),
                       "You kept 9 of the 10 people Cicada asked about.")
        XCTAssertEqual(FadeWords.suggestionDetail(suggestion(kept: 7, archived: 0), current: nil, locale: us),
                       "You kept all 7 people Cicada asked about.")
        let faster = suggestion(type: "concept", direction: .faster, kept: 1, archived: 1200)
        XCTAssertEqual(FadeWords.suggestionTitle(faster), "Let ideas fade more quickly?")
        XCTAssertEqual(FadeWords.suggestionDetail(faster, current: 0.5, locale: us),
                       "You archived 1,200 of the 1,201 ideas Cicada asked about. Right now they fade more slowly.")
        XCTAssertEqual(FadeWords.tunedTitle(type: "company", multiplier: 0.5), "Companies fade more slowly")
        XCTAssertEqual(FadeWords.tunedTitle(type: "mystery", multiplier: 1.5), "Pages fade more quickly")
    }

    func testEveryKindHasAPlainNoun() {
        for type in EntityType.allCases {
            XCTAssertFalse(FadeWords.noun(type.rawValue, count: 2).isEmpty, type.rawValue)
        }
        XCTAssertEqual(FadeWords.noun("person", count: 1), "person")
        XCTAssertEqual(FadeWords.noun("location", count: 2), "places")
    }

    func testNoCopyCarriesAPercentSign() {
        let texts = [FadeWords.suggestionTitle(suggestion()),
                     FadeWords.suggestionDetail(suggestion(), current: 0.5, locale: us),
                     FadeWords.tunedTitle(type: "person", multiplier: 0.5), FadeWords.tunedDetail,
                     Copy.fadePaceDetail, Copy.fadeHeader, Copy.fadePaceTitle]
        for text in texts { XCTAssertFalse(text.contains("%"), text) }
    }

    // MARK: APIClient

    private static func body(_ request: URLRequest) -> [String: Any] {
        let data = request.httpBodyStream.map { stream -> Data in
            stream.open()
            defer { stream.close() }
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 1024)
            while stream.hasBytesAvailable {
                let read = stream.read(&buffer, maxLength: 1024)
                if read <= 0 { break }
                data.append(buffer, count: read)
            }
            return data
        } ?? request.httpBody ?? Data()
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }

    private static let reply = """
    {"bank": "memory", "windowDays": 180, "tuning": {}, "suggestions": []}
    """.data(using: .utf8)!

    func testFetchReadsTheSuggestionsEndpoint() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/memory/decay-suggestions")
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Self.reply)
        }
        let r = try await APIClient(session: MockURLProtocol.makeSession()).fetchDecayTuning()
        XCTAssertEqual(r.bank, "memory")
    }

    func testSetSendsThePaceAndANullToClear() async throws {
        MockURLProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "PUT")
            XCTAssertEqual(request.url?.path, "/memory/decay-tuning")
            let body = Self.body(request)
            XCTAssertEqual(body["person"] as? Double, 0.5)
            XCTAssertTrue(body["tool"] is NSNull, "nil clears a type")
            return (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Self.reply)
        }
        _ = try await APIClient(session: MockURLProtocol.makeSession())
            .setDecayTuning(["person": 0.5, "tool": nil])
    }

    // MARK: The page

    func testMemoryHostsHowThingsFade() throws {
        let view = try ThemeTokenTests.swiftSources().first { $0.lastPathComponent == "MemoryView.swift" }
        XCTAssertTrue(try String(contentsOf: XCTUnwrap(view), encoding: .utf8).contains("FadePaceCard()"))
    }
}
```

- [ ] **Step 2: Run — red.**
  `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay/app/CicadaApp && swift test --filter DecayTuningTests 2>&1 | tail -20`
  → compile failure (`DecayTuningResponse`, `DecaySuggestion`, `DecayTuningModel` do not exist).

- [ ] **Step 3: Implement.**

`Models/DecayTuning.swift`:

```swift
import Foundation

/// G147 — `GET /memory/decay-suggestions` and `PUT /memory/decay-tuning` (both answer this
/// shape). Not a Store domain — fetched when Settings → Memory opens, like the search index's
/// status — so no ETag and no `VersionVector` mapping. Lenient: a suggestion this build
/// cannot read is dropped alone, never the page.
struct DecayTuningResponse: Decodable, Equatable {
    var bank: String
    var windowDays: Int
    var tuning: [String: Double]
    var suggestions: [DecaySuggestion]

    enum CodingKeys: String, CodingKey { case bank, windowDays, tuning, suggestions }

    init(bank: String = "", windowDays: Int = 180, tuning: [String: Double] = [:],
         suggestions: [DecaySuggestion] = []) {
        self.bank = bank
        self.windowDays = windowDays
        self.tuning = tuning
        self.suggestions = suggestions
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        bank = (try? c.decode(String.self, forKey: .bank)) ?? ""
        windowDays = (try? c.decode(Int.self, forKey: .windowDays)) ?? 180
        tuning = (try? c.decode([String: Double].self, forKey: .tuning)) ?? [:]
        suggestions = ((try? c.decode([LossySuggestion].self, forKey: .suggestions)) ?? []).compactMap(\.value)
    }
}

/// One per-type suggestion: a kind of page and the counts behind it — never a page's name.
struct DecaySuggestion: Decodable, Equatable {
    enum Direction: String, Decodable { case slower, faster }

    var type: String
    var direction: Direction
    var multiplier: Double
    var kept: Int
    var archived: Int
    var answers: Int
}

private struct LossySuggestion: Decodable {
    let value: DecaySuggestion?
    init(from decoder: Decoder) throws { value = try? DecaySuggestion(from: decoder) }
}

/// One row under "How things fade": a suggestion to answer, or a pace already chosen.
struct FadeTypeRow: Identifiable, Equatable {
    enum Kind: Equatable {
        case suggestion(DecaySuggestion)
        case tuned(Double)
    }

    let type: String
    let kind: Kind
    /// The pace the person already chose for this kind, if any — a suggestion row says it.
    let current: Double?
    var id: String { type }
}

enum DecayTuningModel {
    /// Per viewer (plan R-FD8): "Not now" is a convenience, never state the bank keeps.
    static let notNowKey = "cicada.memory.fadeNotNow"
    /// A dismissed suggestion comes back only after this many more answers about that kind.
    static let notNowRepeat = 5

    static func notNowID(bank: String, _ s: DecaySuggestion) -> String {
        "\(bank)|\(s.type)|\(s.direction.rawValue)"
    }

    static func decodeNotNow(_ raw: String) -> [String: Int] {
        guard let data = raw.data(using: .utf8),
              let map = try? JSONDecoder().decode([String: Int].self, from: data) else { return [:] }
        return map
    }

    static func encodeNotNow(_ map: [String: Int]) -> String {
        guard let data = try? JSONEncoder().encode(map),
              let text = String(data: data, encoding: .utf8) else { return "" }
        return text
    }

    static func isHidden(_ s: DecaySuggestion, bank: String, notNow: [String: Int]) -> Bool {
        guard let dismissedAt = notNow[notNowID(bank: bank, s)] else { return false }
        return s.answers < dismissedAt + notNowRepeat
    }

    /// Suggestions first (the server's order: most answers first), then every chosen pace
    /// that has no visible suggestion, A→Z. One row per kind.
    static func rows(_ r: DecayTuningResponse, notNow: [String: Int]) -> [FadeTypeRow] {
        var rows: [FadeTypeRow] = []
        var seen = Set<String>()
        for s in r.suggestions where !isHidden(s, bank: r.bank, notNow: notNow) {
            guard seen.insert(s.type).inserted else { continue }
            rows.append(FadeTypeRow(type: s.type, kind: .suggestion(s), current: r.tuning[s.type]))
        }
        for (type, value) in r.tuning.sorted(by: { $0.key < $1.key }) where !seen.contains(type) {
            rows.append(FadeTypeRow(type: type, kind: .tuned(value), current: value))
        }
        return rows
    }
}
```

`Models/FadeWords.swift` — append inside `enum FadeWords`:

```swift
    // MARK: Settings → Memory (G147, plan R-FD6)

    /// The plain noun for a kind of page — "people", not "persons"; "ideas" for concepts.
    static func noun(_ type: String, count: Int) -> String {
        let pair: (one: String, many: String)
        switch EntityType(rawValue: type) ?? .unknown {
        case .person: pair = ("person", "people")
        case .project: pair = ("project", "projects")
        case .company: pair = ("company", "companies")
        case .concept: pair = ("idea", "ideas")
        case .tool: pair = ("tool", "tools")
        case .deadline: pair = ("deadline", "deadlines")
        case .skill: pair = ("skill", "skills")
        case .location: pair = ("place", "places")
        case .media: pair = ("saved item", "saved items")
        case .directory: pair = ("folder", "folders")
        case .hub, .unknown: pair = ("page", "pages")
        }
        return count == 1 ? pair.one : pair.many
    }

    private static func pluralNoun(_ type: String) -> String { noun(type, count: 2) }

    private static func speed(_ slower: Bool) -> String { slower ? "more slowly" : "more quickly" }

    /// "Let people fade more slowly?" — the question, stated once (DR-59).
    static func suggestionTitle(_ s: DecaySuggestion) -> String {
        "Let \(pluralNoun(s.type)) fade \(speed(s.direction == .slower))?"
    }

    /// "You kept 9 of the 10 people Cicada asked about." Each number once, through
    /// UsageFormat (DR-21); a suggestion against a pace already chosen says so, so Apply
    /// never reads as a no-op.
    static func suggestionDetail(_ s: DecaySuggestion, current: Double?,
                                 locale: Locale = .autoupdatingCurrent) -> String {
        let slower = s.direction == .slower
        let verb = slower ? "kept" : "archived"
        let part = slower ? s.kept : s.archived
        let nouns = noun(s.type, count: s.answers)
        let total = UsageFormat.count(s.answers, locale: locale)
        var text = part == s.answers
            ? "You \(verb) all \(total) \(nouns) Cicada asked about."
            : "You \(verb) \(UsageFormat.count(part, locale: locale)) of the \(total) \(nouns) Cicada asked about."
        if let current { text += " Right now they fade \(speed(current < 1))." }
        return text
    }

    /// "People fade more slowly" — a pace the person chose.
    static func tunedTitle(type: String, multiplier: Double) -> String {
        let nouns = pluralNoun(type)
        return nouns.prefix(1).uppercased() + nouns.dropFirst() + " fade " + speed(multiplier < 1)
    }

    static let tunedDetail = "You chose this. Reset to go back to the usual pace."
```

`Theme/Copy+Settings.swift` — after `alreadyRunning` (`:161`), inside `// MARK: Memory`:

```swift
    // G147 — How things fade
    static let fadeHeader = "How things fade"
    static let fadePaceTitle = "Learns from your answers"
    static let fadePaceDetail = "Pages that come up across many weeks fade more slowly. After you answer “Still tracking…?” about a few pages of one kind, Cicada may suggest a different pace for that kind here."
    static let fadeApply = "Apply"
    static let fadeNotNow = "Not now"
    static let fadeReset = "Reset"
    static let fadeBusyHelp = "Saving your last change…"
    static let fadeLoadFailed = "Couldn't read your answers just now — open this page again to retry."
    static let fadeSaveFailed = "Couldn't save that — try again."
```

`Views/Settings/SettingsRowID.swift` — after `enrichLinks` (`:56`):

```swift
    static let fadePace = SettingsRowID("fadePace")
```

and beside the other per-item ids:

```swift
    /// G147 — one row per kind of page under "How things fade" (a suggestion or a chosen pace).
    static func fadeType(_ type: String) -> SettingsRowID { SettingsRowID("fadeType:\(type)") }
```

`Views/Settings/SettingsIndex.swift` — `staticIDs` `:76` becomes `.searchIndex, .enrichLinks, .fadePace,`;
after the `enrichLinks` entry (`:110`):

```swift
        SettingsEntry(.fadePace, .memory, Copy.fadePaceTitle,
                      keywords: ["fade", "decay", "forget", "archive", "pace", "still tracking", "slower", "faster"],
                      detail: Copy.fadePaceDetail),
```

`Services/APIClient.swift` — after `fetchSearchIndexStatus` (`:2109`):

```swift
    /// `GET /memory/decay-suggestions` (G147) — the per-type pace suggestions and the pace
    /// already chosen. Not a Store domain, no ETag.
    func fetchDecayTuning() async throws -> DecayTuningResponse { try await get("/memory/decay-suggestions") }

    /// `PUT /memory/decay-tuning` (G147) — `nil` clears a kind back to the usual pace. 409
    /// while Sleep runs; 422 with a plain sentence for a pace outside what the server allows.
    func setDecayTuning(_ changes: [String: Double?]) async throws -> DecayTuningResponse {
        var body: [String: Any] = [:]
        for (type, value) in changes { body[type] = value.map { $0 as Any } ?? NSNull() }
        return try await put("/memory/decay-tuning", body: body)
    }
```

`Views/Settings/FadePaceCard.swift`:

```swift
import SwiftUI

/// G147 — Settings → Memory's "How things fade": what Cicada suggests from your own
/// "Still tracking…?" answers, and the pace you chose per kind of page. Agent proposes, person
/// disposes (UX principle 3): nothing changes how anything fades until Apply. Direction D: one
/// group card of Settings rows (DR-37, DR-33), Apply and Reset neutral and Not now a text button —
/// no primary action on this surface, no accent (DR-40, DR-7, DR-5) — counts through FadeWords'
/// UsageFormat (DR-21), plain sentences with no bare percentages (DR-59), a disabled button that
/// says why (DR-41).
struct FadePaceCard: View {
    @Environment(Store.self) private var store
    @AppStorage(DecayTuningModel.notNowKey) private var notNowRaw = ""
    @State private var response: DecayTuningResponse?
    @State private var note: String?
    @State private var busy = false

    private var rows: [FadeTypeRow] {
        guard let response else { return [] }
        return DecayTuningModel.rows(response, notNow: DecayTuningModel.decodeNotNow(notNowRaw))
    }

    var body: some View {
        SettingsGroupCard(header: Copy.fadeHeader) {
            SettingsRow(.fadePace, title: Copy.fadePaceTitle, detail: note ?? Copy.fadePaceDetail)
            ForEach(rows) { row in
                SettingsDivider()
                typeRow(row)
            }
        }
        .task { await load() }
    }

    @ViewBuilder
    private func typeRow(_ row: FadeTypeRow) -> some View {
        switch row.kind {
        case .suggestion(let s):
            SettingsRow(.fadeType(row.type), title: FadeWords.suggestionTitle(s),
                        detail: FadeWords.suggestionDetail(s, current: row.current)) {
                HStack(spacing: CicadaTheme.spacingSM) {
                    TextButton(title: Copy.fadeNotNow) { notNow(s) }
                    NeutralButton(title: Copy.fadeApply, size: .compact, isDisabled: busy,
                                  disabledHelp: Copy.fadeBusyHelp) { write([row.type: s.multiplier]) }
                }
            }
        case .tuned(let value):
            SettingsRow(.fadeType(row.type), title: FadeWords.tunedTitle(type: row.type, multiplier: value),
                        detail: FadeWords.tunedDetail) {
                NeutralButton(title: Copy.fadeReset, size: .compact, isDisabled: busy,
                              disabledHelp: Copy.fadeBusyHelp) { write([row.type: nil]) }
            }
        }
    }

    private func load() async {
        do {
            response = try await APIClient.shared.fetchDecayTuning()
            note = nil
        } catch {
            note = Copy.fadeLoadFailed
        }
    }

    /// R-FD8 — remembered per viewer and per bank with the answer count it was dismissed at.
    private func notNow(_ s: DecaySuggestion) {
        guard let response else { return }
        var map = DecayTuningModel.decodeNotNow(notNowRaw)
        map[DecayTuningModel.notNowID(bank: response.bank, s)] = s.answers
        notNowRaw = DecayTuningModel.encodeNotNow(map)
    }

    private func write(_ changes: [String: Double?]) {
        busy = true
        Task { @MainActor in
            defer { busy = false }
            do {
                response = try await APIClient.shared.setDecayTuning(changes)
                note = nil
                // R-FD9: the card's pace reads the tuning; drop cached bodies so the next open refetches.
                store.invalidateAllEntities()
            } catch APIError.httpError(409, _) {
                note = Copy.sleepIsRunning
            } catch {
                note = Copy.fadeSaveFailed
            }
        }
    }
}
```

`Views/Settings/MemoryView.swift` — inside `SettingsPage(section: .memory) { … }`, after the
existing `SettingsGroupCard { … }`:

```swift
            FadePaceCard()
```

and add to its docstring: "and G147's *How things fade* (`FadePaceCard`) — suggestions from the
person's own decay answers, applied only on Apply."

`CountLiteralLintTests.swift` — append `"/Models/DecayTuning.swift",` and
`"/Views/Settings/FadePaceCard.swift",` to `scope`, with "— and G147's Settings → Memory pace
rows" in its docstring.

The `NeutralButton` / `TextButton` / `SettingsRow` / `SettingsGroupCard(header:)` calls above
compile as written (critic check): `NeutralButton`'s memberwise order is `title, systemImage,
leading, trailingSystemImage, size, keyHint, shortcut, isDisabled, help, disabledHelp, action`
(precedent `Views/Inbox/FocusCardVariants.swift:71`); omitted arguments keep their defaults.

- [ ] **Step 4: Green, then the suites.** In
  `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay/app/CicadaApp` (`cd` to it
  with the absolute path first): `swift build 2>&1 | tail -5` → success;
  `swift test --filter "DecayTuningTests|FadeWordsTests|SettingsIndexTests|SettingsRowLintTests|CountLiteralLintTests|FontLiteralLintTests" 2>&1 | tail -20`
  → pass; then `swift test 2>&1 | tail -20` → 0 failures.

- [ ] **Step 5: Commit.**
  `git add app/CicadaApp/Sources/CicadaApp/Models/DecayTuning.swift app/CicadaApp/Sources/CicadaApp/Models/FadeWords.swift app/CicadaApp/Sources/CicadaApp/Views/Settings/FadePaceCard.swift app/CicadaApp/Sources/CicadaApp/Views/Settings/MemoryView.swift app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsRowID.swift app/CicadaApp/Sources/CicadaApp/Views/Settings/SettingsIndex.swift app/CicadaApp/Sources/CicadaApp/Theme/Copy+Settings.swift app/CicadaApp/Sources/CicadaApp/Services/APIClient.swift app/CicadaApp/Tests/CicadaAppTests/CountLiteralLintTests.swift app/CicadaApp/Tests/CicadaAppTests/DecayTuningTests.swift`
  → subject
  `feat(app): Settings → Memory "How things fade" — pace suggestions from your own answers, Apply · Not now · Reset (G147; DR-5, DR-7, DR-21, DR-33, DR-37, DR-40, DR-41, DR-59)`.

---

### Task 6: Docs — CLAUDE.md tells the truth, G147 is written down

**Files:**
- Modify: `CLAUDE.md` (Temporal decay `:245-249`; Decay classes table `:298-303` and the
  paragraph after it; Optional frontmatter keys `:391+`; Settings paragraph `:667`; API Design
  `:1010` and its traps list)
- Modify: `docs/goals/memory-evolution.md` (G66 `:630`, G85 `:649`, G113 `:677`, **G147** after
  G141 `:705`)
- Modify: `docs/goals/TODO.md` (a row in "🔄 In progress", after `:632`)
- Add: this plan file

- [ ] **Step 1: CLAUDE.md.** Replace the whole `### Temporal decay` paragraph (`:246-249`) with:

```markdown
Absence of mention IS a signal, and **how often something came up sets how fast its absence
counts** (G147). Each Sleep cycle charges an unreferenced page at most one week
(`MAX_DECAY_DAYS_PER_CYCLE`, measured from `max(last_referenced, decayed_through)` — TODO ruling 1)
at **base × f(w) × the bank's per-type pace**: the base is the decay class's rate or an explicit
`decay_rate:` (G66); `w` is the number of distinct ISO weeks among the page's `source_episodes`
dates plus the weeks the person answered *keep* to a decay question (`kept_on`; every unparseable id
together counts once); `f(w) = max(0.25, 1 / (1 + 0.6·ln w))` (`decay_spacing_alpha` /
`decay_spacing_floor`) — fifty mentions in one afternoon are one week, and a page that came up across
twelve weeks fades about 2.5× slower. The per-type pace comes from `<bank>/_decay_tuning.yaml`,
written only when the person applies a suggestion in Settings → Memory; suggestions are derived from
the bank's own decay answers in git history (`GET /memory/decay-suggestions`) and never applied on
their own. One function, `decay_policy.effective`, serves the pass and the entity wire's derived
`decay` block. Claims fade the same way (`claim_reconciler._decay_claims`: weeks from the claim's
episodes and cited `ep_*` documents plus the subject's keeps; session ids carry no date and never
count). Below 0.2 → `status: archived` (the page stays in `entities/`); below 0.4 → a decay nudge.
Mentioned again → promoted back at `confidence = max(current, 0.6)`. Evergreen entities skip all
decay math. **Confidence does not rank recall:** search puts archived pages last and otherwise ranks
by relevance (`search_service._page`'s sort key and the per-kind cut's archived tier); whether
confidence should weigh in is a question for G148's benchmark pass to measure before anything
changes.
```

(No line numbers inside CLAUDE.md — they rot; name the symbol.)

In `### Decay classes (G66)`: rename the table header `Entity rate/wk` → `Base entity rate/wk`
and append to the `**Both engines honor it.** …` paragraph (`:310`, two paragraphs after the
table — the Anti-pollution rail sits between them): "Since G147 the class rate is the *base*:
both engines multiply it by the spacing factor and the per-type pace (see Temporal decay)."

In **Optional frontmatter keys**, add after the `owner: true` bullet:

```markdown
- `kept_on:` (G147) — the days the person answered *keep* to a decay question; each joins the page's
  mention weeks, so a kept page fades a little slower. Written only by the decay resolver, deduped,
  capped at 52. Not an episode id and never read as one.
```

In the **Navigation (Direction D, DS-1)** paragraph (the Settings panel's description, `:667`),
after "…commits what it merges (R-O17).", add: "Memory also holds
G147's *How things fade*: pace suggestions from the person's own \"Still tracking…?\" answers
(Apply · Not now — the latter per viewer) and each chosen per-type pace (Reset)."

In `## API Design`, `31 routers` → `32 routers`, and add to **Endpoint traps**:

```markdown
- `GET /memory/decay-suggestions` / `PUT /memory/decay-tuning` (G147) are not Store domains and carry
  no ETag; both answer one shape (`bank`, `windowDays`, `tuning`, `suggestions` — types and counts,
  never a page id). The PUT merges `{type: multiplier | null}` within [0.25, 3.0], answers **409**
  while Sleep runs, and commits `_decay_tuning.yaml` alone as `Cicada-Author: user`.
```

- [ ] **Step 2: The backlog.** Append to G66's notes cell (before ` | ✅ |`):
  " **2026-09-24 (G147):** the class rate is now the *base* — Sleep multiplies it by a spacing
  factor over distinct mention weeks and by the per-type pace the person approved, and the
  card's Details row says the effective pace in words."

  Append to G85's notes cell (before ` | 🔲 |`):
  " **(3) answered by G147 (2026-09-24)** — not by promoting the class (that would rewrite a
  label the person can set, G66 §1.7, and commit on every threshold crossing) but by a derived
  spacing factor over distinct ISO weeks of `source_episodes`, recomputed every cycle and never
  stored. (4) stays open."

  Append to G113's notes cell (before its status cell):
  " **First consumer (G147, 2026-09-24):** decay answers in the bank's own history
  (`inbox/decay/resolved:<label>`) become per-type pace *suggestions* in Settings → Memory —
  applied only when the person says so."

  Add after the G141 row (the last row of that table on this branch's base). **Merge note:**
  `dev` gained G148 and G149 directly after G141 at `ed6055f` (after this base), and other
  round-4 tracks hold G142–G146, so this insertion conflicts textually at merge; the orchestrator
  keeps every row and orders them by number (G147 before G148).

```markdown
| G147 | **Frequency-aware decay (spacing) + per-type tuning** (Rodrigo 2026-09-24, on the proposed fix: "ok i like the fix you propose so please go ahead and work on that") | **The defect (verified 2026-09-24):** decay was a flat per-class weekly rate from the last reference (`conflict_resolver.py:168-196` at `ecb59c7`) — a page mentioned in 50 separate conversations faded exactly as fast as one mentioned twice, while CLAUDE.md claimed decay was "proportional to how frequently it used to be referenced" (it read nothing about frequency) and that archived pages move to `archive/` (they keep their file, `status: archived`). **The rule now:** weekly rate = base (class rate or explicit `decay_rate:`) × f(w) × the bank's per-type pace, `w` = distinct ISO weeks among `source_episodes` dates ∪ the person's *keep* days (`kept_on`; every unparseable id together counts once), f(w) = max(0.25, 1/(1+0.6·ln w)). Weeks of silence to the decay question / to archive from 0.6: active w=1 4/8, w=4 7.3/14.7, w=12 10/20, w=52 13.5/27; durable w=1 10/20 → w=52 33.7/67.4; volatile w=1 1.3/2.7 → w=52 4.5/9.0. α=1.0 was rejected (floor at ~20 weeks: five months and five years look alike), α=0.3 too (a 52-week page asked after 8.7 weeks, barely twice a one-week page). **Keep** records the day in `kept_on` (not `source_episodes`, whose entries every reader treats as episode ids; not git-derived, which would put a subprocess in every pass). **Claims** multiply their existing amount by f(w_claim), weeks from `source_episodes` ∪ cited `ep_*` evidence documents ∪ the subject's keeps — session ids carry no date, `recorded_at` moves on every restatement, so neither counts; no new claim field. **Per-type pace** (agent proposes, person disposes): `GET /memory/decay-suggestions` counts, per type, each page's latest decay answer in the last 180 days of the bank's own git history (never the telemetry ledger) and suggests 0.5 ("fade more slowly") at ≥ 5 answers and ≥ 80 % keep, 1.5 at ≥ 80 % archive; `PUT /memory/decay-tuning` stores `<bank>/_decay_tuning.yaml` (travels with the bank, committed alone as `Cicada-Author: user`, 409 while Sleep runs); both engines multiply by it. Settings → Memory shows "Let people fade more slowly?" with Apply · Not now (per viewer, back after 5 more answers) and each chosen pace with Reset. **Visibility:** `GET /entities/{id}` gains a derived `decay: {class, effectiveRatePerWeek, mentionWeeks}` from the pass's own function (`decay_policy.effective`), and the card's Details "Fades" row reads "Slowly — mentioned across 12 weeks". Unchanged: the one-week cap per cycle, the `decayed_through` watermark, the 0.2/0.4 thresholds, `RECOVERY_CONFIDENCE`, G85's `cicada`-authored decay commit; nothing stored is migrated. **Disclosed, not fixed:** a merge (`entity_merge._LIST_FIELDS`) unions the absorbed page's `source_episodes` but not its `kept_on`. **Not here:** ranking recall by confidence (nothing ranks by it today; a question for G148's benchmark pass to measure before anything changes); reinforcement as an increment (G85 (4)); the Feed's media relevance (media is evergreen). Plan: `docs/superpowers/plans/2026-09-24-r4-frequency-aware-decay.md` (rulings R-FD1 … R-FD13). → answers **G85** (3); builds on **G66**, **G113**; respects **G78**. | 🛠️ built on `feat/r4-decay` (round 4) |
```

- [ ] **Step 3: TODO.md.** Insert as the first row under the "🔄 In progress" table header
  (after `:632`):

```markdown
| **G147 frequency-aware decay (round 4)** | Built on `feat/r4-decay` (plan `2026-09-24-r4-frequency-aware-decay.md`): pages and claims fade by distinct mention weeks (f(w) = max(0.25, 1/(1+0.6·ln w))), "keep" counts as a week (`kept_on`), per-type pace suggestions from the bank's own decay answers with Apply · Not now in Settings → Memory, and the pace in words on the entity card. | Orchestrator verification (both suites; the 12-week vs 1-week simulation; suggestions on a synthetic history; live check of Settings → Memory and a card's Details on the demo bank), then merge to `dev`. |
```

- [ ] **Step 4: Check the privacy rule and the suites.** `git diff --stat` touches only the four
  docs files; grep the diff of `CLAUDE.md`, `memory-evolution.md` and `TODO.md` for anything that
  is not synthetic (no names but the owner's own dated opinion, no bank titles, no paths under a
  home directory: `git diff -U0 -- CLAUDE.md docs/goals | grep -n '^+.*/Users/'` prints
  nothing). This plan file's absolute worktree
  `cd` lines are execution instructions, the precedent of the committed plans beside it; they
  name no bank content. Run the full `api/tests` once more (docs-only, but
  `test_owner_name_portability.py` reads shipped files and must stay green).

- [ ] **Step 5: Commit.**
  `git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md docs/superpowers/plans/2026-09-24-r4-frequency-aware-decay.md`
  → subject
  `docs(decay): CLAUDE.md describes the real decay rule; G147 row, G66/G85/G113 cross-links, TODO (G147)`.

---

## Not in scope

- **Ranking recall by confidence** — `search_service` keeps "archived last, then relevance";
  whether confidence should weigh in is a question for G148's benchmark pass (its row does not
  list it yet), measured before anything changes.
- **Onboarding, Home and Clusters UI** (other round-4 tracks), and any restructuring of the
  entity card beyond the Fades menu's label (the round-4 entity-card track owns the card).
- **Migrating stored decay fields.** The factor is derived every cycle; no page is rewritten to
  gain it, `decay_rate:` keeps meaning the base, and no backfill of `kept_on` from history.
- **G85 (4) — reinforcement as a bounded increment.** Recovery stays the one-shot
  `max(current, 0.6)`.
- **The pass's safety rails** — the one-week cap, the watermark, the 0.2 / 0.4 thresholds,
  `RECOVERY_CONFIDENCE`, G85's split decay commit, TODO ruling 1 — are untouched.
- **The decay question's copy** (`inbox_questions.decay_question`) — the keep option's
  description is unchanged.
- **MCP surfaces** (`cicada_recall_detail`, the handshake) and **`/graph` nodes** do not gain
  the pace; `graph.NODE_SHAPE` does not move.
- **The Feed's media relevance** (`media_ingestor.compute_relevance`, `:1439-1498`) keeps `decay_policy.resolve` —
  media pages are evergreen, so spacing never applies there.
- **Auto-applying anything, or reading the telemetry ledger** for suggestions (G78/G113).
- **Per-page tuning** — the class picker on the card (G66 §1.7) already is the per-page control.

---

## Verification (the orchestrator runs this at the end)

1. **Backend suite:** `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`
   → 0 failures (3775 + this track's 62 = **3837 passed, 1 skipped**, as the critic check
   measured; the one known order-dependent case re-run alone if it is the only red). A count
   below 3837 means a test from this plan was dropped.
2. **Swift:** `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/r4-decay/app/CicadaApp && swift build 2>&1 | tail -5` → success;
   `swift test 2>&1 | tail -20` → 0 failures (2003 + this track's 17 = **2020 tests**).
   **Graph JS:** `node --test app/CicadaApp/Tests/graph/*.test.js` → 8/8.
3. **The spacing, on a synthetic bank over simulated cycles:**
   `api/.venv/bin/python -m pytest "api/tests/test_decay_spacing.py::test_a_twelve_week_page_outlasts_a_one_week_page_over_simulated_cycles" -q -p no:cacheprovider -s`
   — two `active` pages, same start confidence (0.62) and silence: the one-week page is asked at
   cycle 5 and archived at 9; the twelve-week page is asked at 11 and archived at 21.
4. **Suggestions on a synthetic history:**
   `api/.venv/bin/python -m pytest api/tests/test_decay_tuning.py -q -p no:cacheprovider` —
   in particular `test_nine_keeps_of_ten_people_suggest_fading_people_more_slowly`,
   `test_one_vote_per_page_its_latest_answer`, `test_answers_older_than_the_window_do_not_count`
   and `test_the_real_resolver_is_what_the_parser_reads` (five real keeps through
   `inbox_service.resolve` → "person, slower, 5 of 5").
5. **Diff read:** no `git add -A` artifacts; `_decay_tuning.yaml` only ever committed through
   `commit_paths`; no LLM call added; no telemetry read; no owner name or machine path.
6. **Live (after the orchestrator installs), on the demo bank:** Settings → Memory shows "How
   things fade" with the "Learns from your answers" row (and ⌘K "fade" lands on it); an entity
   card's Details → Fades reads a pace sentence (e.g. "At the usual pace — mentioned in a single
   week"), the class menu still opens and still sets the class; both themes, 1.0× and 1.4×.
