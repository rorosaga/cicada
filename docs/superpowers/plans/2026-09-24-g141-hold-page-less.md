# G141 PJ-0b: Sleep holds a page-less subject's claims with its pending entity and writes them on promotion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When Sleep hears a claim about a name that has no page yet, it keeps the claim. Promotion needs 2+
conversations, substantive discussion, or a link to a high-confidence entity, so a name heard once has no page.
Since PJ-0 (#88) such a claim is counted (`claims_page_less`) and then lost: the cycle marks its episode
processed, so nothing extracts it again. The owner ruled on 2026-09-23 (G141 DECIDE (c)) that the claim waits
with the name's pending entity. It is written onto the page, through the normal Stage 3, in the cycle that
gives the name a page. It keeps its id, spans, observer, trust, validity and context. Nothing about it is ever
dropped silently.

**Architecture:** The pending store (`<bank>/pending_entities.jsonl`) moves out of `vector_index` into its own
module, `api/services/pending_store.py`, which becomes the one writer of the file. `SqliteVecIndexer` keeps its
methods and delegates to it. A pending line gains `held_claims` (a list of `Claim.to_dict()`). Stage 5.56
(`claim_pipeline.run_claim_pipeline`) does two new things:
- **Release.** Before Stage 3 it reads the lines whose name now has a page and puts their claims in front of
  this cycle's Stage-1 claims. After the write loop it removes those lines, but only when their page was
  written.
- **Hold.** It holds this cycle's page-less Stage-1 claims on the line whose slug is their subject.

Promotion (`promote_from_pending`) no longer removes a line that holds claims, and a re-park carries the hold.
So a cancel or a failure between Stage 2 and the claim write loses nothing. Everything is file work and counts:
no LLM, no endpoint, no app change.

**Tech Stack:** Python 3.12 / FastAPI / pytest; markdown + git bank. **No app changes, no Swift, no MCP
changes.**

**Spec and rulings this rests on:**
- `docs/superpowers/specs/2026-09-23-g141-project-timelines-design.md` **R-PJ17** (the page-less fix is split;
  the hold is its own slice), §15 (slices), §16 (Not in scope, which this slice now fills).
- The owner's ruling, recorded in `docs/goals/TODO.md` under Research / decisions ("G141 DECIDEs — ruled
  2026-09-23" (c)) and on the G141 row.
- `docs/superpowers/plans/2026-09-23-g141-capture-side.md` **R-CS1–R-CS4** (PJ-0 as shipped: Stage 2's
  `name_to_id`, the owner surfaces, counts never names, the `hold_page_less` seam).

Backlog rows: **G141** (this track), **G118** (spans, not copies), **G48** (an entity credits a conversation
through `source_episodes`), **G61** phase 2 S1 (cited links become sources on a first write), research **R7**
and decision **D2** (the promotion model; see R-HP9). The round-3 spec
(`2026-09-23-round3-meadow-reach-provenance-design.md`) adds nothing binding here beyond the standing rails.
`docs/design/DESIGN_RULES.md` does not apply: nothing here is UI, so no commit cites a DR id.

---

## What the code actually does today (verified at `feat/g141-hold-page-less` @ `1eb3cf5`)

**The page-less seam (PJ-0, `api/services/claim_pipeline.py`).**
- `:104-112`: `hold_page_less(subject, claims, memory_path) -> int` returns `0`. Its docstring names this slice.
- `:198`: `emitted_ids = {c.id for c in incoming}` (Stage-1 only; used by the G61 attach at `:267-278`).
- `:203`: `existing_by_subject = _load_existing_claims_by_subject(memory_path)` loads after Stage 1.
- `:230-245`: the write loop's page-less branch calls the seam per subject and counts
  `claims_page_less += len(claims) - held`.
- `:280-286`: the INFO line (`"… claim(s) on … subject(s) without a page not written"`). `:287-289`: the DEBUG
  line with opaque claim ids.
- `:291-300`: the return dict.
- `api/tests/test_claim_pipeline_subjects.py:182-196` pins the seam: `hold_page_less("zed-unknown", [], memory)
  == 0`, a monkeypatched three-argument lambda, and "no file written". `:199-202` pins that the phrases
  "re-emitted next cycle" and "waits for its subject to be promoted" are absent from `claim_pipeline.py`.

**The pending store (`api/services/vector_index.py`).**
- `:36`: `PENDING_STORE_FILE = "pending_entities.jsonl"`. `:49-83`: `PendingEntity` has seven fields, and
  `to_dict` always writes all seven keys. `:127`: `self.pending_store = self.memory_path / PENDING_STORE_FILE`.
- `:480-492`: `_load_pending` **skips any line that fails to parse**.
- `:494-500`: `_save_pending` is a plain `write_text`. It is not atomic.
- `:502-512`: `index_pending_entity` **replaces** the same-named line (case-insensitive) with the new entity.
  Everything the old line carried is gone.
- `:531-546`: `promote_from_pending` removes the first same-named line and rebuilds the pending vectors.
- `:548-570`: `_rebuild_pending_index` embeds. `:572`: `search_pending` has **no production caller**. Neither
  has `list_pending`. Verified with `grep -rn "search_pending\|list_pending" api mcp`: only `vector_index.py`
  and the tests match.
- The file is **not** in `bank_registry.DERIVED_ARTIFACTS` (`bank_registry.py:75-83`), so it is tracked in the
  bank's git and swept into each cycle's `_finalize` commit.
- **Nothing expires a pending line.** There is no TTL and no prune. The only production writers are
  `entity_resolver.resolve` (`index_pending_entity`, `promote_from_pending`, `rebuild_pending_index`) and
  `link_recon.py:345-356`. Link recon never overwrites an existing line: it checks `pending_by_name` first.

**Stage 2 (`api/services/entity_resolver.py`).**
- `:240-245`: `pending_entry = indexer.pending_by_name(name)`.
- `:251-256`: an existing pending line alone is enough to promote.
- `:266-267`: a promoted name's page id is `entity_id = sanitize_id(name)`, and `name_to_id[name_lower] =
  entity_id`.
- `:269-275`: the pending line's `history_entries` merge into the create. Its `source_episode` does **not**:
  the page credits only the episode that promoted it.
- `:293-294`: the deferred `promote_from_pending`.
- `:295-326`: a name that is not promoted is parked with a **fresh** `PendingEntity` via
  `index_pending_entity`. This includes an `unsure` match, cycle after cycle.
- `:358-375`: the deferred writes flush at the end of `resolve`, whenever its loop was not cancelled.
- `:389`: `name_to_id` is returned.
- `:689`: `SUBSTANTIVE_RELATIONSHIP_COUNT = 2`. `:668-683`: `_is_linked_to_existing`.

**Sleep (`api/services/sleep_cycle.py`).**
- `:1295`: Stage 2. Then cancel safe points at `:1311`, `:1324` and `:1347`, all **after** Stage 2's flush.
  `_cycle_cancelled` (`:251-271`) says "nothing written", but the pending store and clarifications already
  moved.
- `:1359`: `write_started`.
- `:1399-1405`: `run_claim_pipeline(..., name_to_id=resolved_result.get("name_to_id"))`, then the two PJ-0
  counters.
- `:1429-1437`: the 5.56 INFO line.
- `:1488`: `_mark_episodes_processed`.
- `SleepState`: `:57-62`, reset at `:1050-1051`. The `sleep_run` ledger refs: `:2120-2131`. `/sleep/status`
  builds its response field by field (`api/routers/sleep.py`), so a new `SleepState` field is not exposed.

**Stage 3 facts the release leans on (`api/services/claim_reconciler.py`).**
- `:125-133`: `_stamp_new` sets `recorded_at` / `authored_by` only when unset. A held claim keeps the hearing
  cycle's values.
- `:215`: `newer = valid_from > existing.valid_from`. Agent over agent is `SUPERSEDE` when newer, else
  `CONFLICT_NUDGE`.
- `:591`: the normalization audit reads `predicate_raw`, an attribute `Claim.to_dict` does not serialize.
- `:601`: `same_key_open` filters the **slot** for open claims. It never tests whether the incoming claim is
  itself open.

**Evidence (`api/services/evidence.py`).**
- `:513-549`: `verify(None, ep, quote, text=...)` returns a span, with `hash = body_hash(text)`.
- `:461-505`: `span_status(text, end=, hash=)` returns `current`, `grown` or `stale`.
- `:137-142`: `source_text` returns the stored body.

**Verified by probe on a synthetic tmp bank** (scratch script, not committed): real `entity_resolver.resolve`
with the entities `Zed Unknown` (person) and `Gamma Board` (tool), each at confidence 0.6 with one relationship.
- Cycle 1 parks both. It makes no LLM call and no inbox file.
- Cycle 2 mentions `Zed Unknown` again: Stage 2 returns a `create` for `zed-unknown` and
  `name_to_id == {"zed unknown": "zed-unknown"}`.
- Two full `sleep_cycle.run`s, with the fakes Task 3 uses, create `entities/zed-unknown.md` with
  `source_episodes: [ep_2026-09-22_001]` and **no claims**. That is the loss this slice fixes.
- A `SimpleNamespace` settings object without `inbox_stale_after_days` makes 5.56's question refresh raise
  after the claim write. Task 3's settings include it.

**Baseline:** the brief's "3167 passed" is stale. This base collects **3743** backend tests (measured
2026-09-24; one of them skips).

**Dry run of this plan (2026-09-24, repeated by the plan critic).** Every code block in Tasks 1–3 was applied
verbatim to a scratch copy of this base, outside the worktree. The full suite then reported **3769 passed,
1 skipped, 0 failed**: 3743 + 27 new tests, with the PJ-0 seam test rewritten in place. The red phases of Tasks 2
and 3 were re-run and fail as each Step 2 says. Two tests were checked against a mutation of the code they pin:
the idempotency test fails when the `on_page` guard in `_releases` is removed, and the cited-link test fails when
`emitted_ids` drops the released ids.

---

## Global Constraints

- **Where to work.** Work ONLY in `<worktree>` = `/Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b`,
  branch `feat/g141-hold-page-less`, based on `dev` @ `1eb3cf5`.
  - Every shell command is `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && <cmd>`. zoxide
    hijacks a relative `cd`; ignore its stderr warning.
  - Never pass an unquoted `--include=*.ext` to grep (zsh globs it). Grep directories and filter with
    `grep "\.py:"`.
- **Never read a real bank.** NEVER read `/Users/rorosaga/Documents/roros_lab/cicada/memory` (any bank),
  `~/.cicada`, `~/Library` or `~/.claude/projects`.
  - Every fixture is synthetic: `Zed Unknown`, `Delta Unknown`, `Echo Unknown`, `Echo Example`,
    `Gamma Board`, `Alpha Lab`, `Beta Lab`, `Zed Example`, `The User`, `Lab Cluster Example`,
    `Tool Example NN`, `alpha-lab`, `https://example.com/alpha-lab/team`, `ep_2026-09-2x_00n`.
  - `CICADA_HOME` is per-test (`api/tests/conftest.py:74-88`).
- **Python.**
  - One file: `cd <worktree> && api/.venv/bin/python -m pytest <files> -q -p no:cacheprovider`.
  - The full suite, `api/tests`, must report **0 failures** (3743 collected on this base; 3770 after Task 3:
    13 + 12 + 2 new tests).
  - `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is
    order-dependent. If it is the ONLY red, re-run it alone and report both results.
- **Git hygiene.**
  - Never `git add -A`; stage named files only.
  - Never commit `memory/`, `logs/`, `.claude/settings.json`, `api/.venv` or `*-report.md`.
  - No push, no new branches or worktrees, no subagents. Ignore Devin/PR comments.
- **Commit messages.** End every commit message with the attribution lines named by the implementing session's
  system reminder (`Co-Authored-By: …` and `Claude-Session: …`).
- **No app, MCP or router changes.** `git diff --stat dev -- app/ mcp/ api/routers/` must be empty at the end.
- **Sleep-safety.**
  - Nothing here calls an LLM or an embedder. The hold and the release are JSON file work over claims Stage 1
    already produced.
  - Transcripts are never read. Evidence stays offsets plus a hash into the stored episode.
- **Telemetry is counts.** The new `sleep_run` refs are integers. A subject id is a slug of a name, so it is
  **never logged and never put in the ledger** (R-CS3). The same holds for a pending line's name.
- **Portability.** No owner name, no author-machine path. Everything keys on the bank directory it is handed.
- **Privacy in docs** (standing, 2026-09-02). No real names, no episode titles, no claim or conversation text.
- **Docstrings explain why** and cite the row or ruling (`G141 PJ-0b`, `R-HP4`, `R-CS3`, …). Match the density
  of the file you touch.
- **Line numbers drift.** The anchors above are from `1eb3cf5` and move as tasks land. Read the cited code
  before every edit.

---

## Rulings (binding)

These hold together with the owner's DECIDE (c), R-PJ17 and R-CS1–R-CS4. Each one below is a decision this plan
takes where the brief left a choice, or where the brief and the code disagree (the code is the truth), with its
reason.

**R-HP1: the hold lives on the pending line, in the file Stage 2 already writes, and the file gets one owner
module.**
- **The line.** A line in `pending_entities.jsonl` gains `held_claims: [Claim.to_dict(), …]`. The key is omitted
  when empty, so every existing line loads and saves back byte for byte.
- **Why a field, not a second file.** The brief says "with the pending entity". Promotion, re-park and release
  all act on the line. A sibling file would need its own join key and its own lifecycle.
- **The module.** The file's reads and writes move from `SqliteVecIndexer` into
  `api/services/pending_store.py`, which owns `PendingEntity`. `vector_index` delegates to it and re-exports
  `PendingEntity` and `PENDING_STORE_FILE`, because `entity_resolver`, `link_recon` and the tests import them
  from there. Why move it:
  - the hold and the release are file work with no embedding, and Stage 5.56 must not build a vector index to
    keep a claim;
  - Sleep's tests stub `SqliteVecIndexer` wholesale with a class that has no pending methods
    (`test_claim_pipeline_subjects.py:236-255`);
  - one module is then the one writer of the file.
- **It stays tracked.** The file is not derived (TODO ruling 3): deleting it costs a first mention and, now, the
  claims heard about that name. So it stays tracked in the bank's git and committed by the cycle that changed
  it, as today. The bank is private; the repo never sees it.

**R-HP2: a claim is held on the line whose slug IS its subject, and only a Stage-1 claim that could stand on the
page is held.**
- **The join.** `sanitize_id(line.name) == claim.subject`. That is the id Stage 2's promotion writes
  (`entity_resolver.py:267`), so a held claim lands exactly where the page will be. There is no fuzzy match
  over pending names: a new matcher with no page to check against would bring R-CS5's false-merge class into
  a place nobody can see.
- **Offered.** Only claims whose id is in this cycle's Stage-1 set (`entities_to_claims`) are offered. The brief
  says "held claims are the ones Stage 1 already produced". `extra_claims` has no production caller, and a
  person's page-less claim is not Sleep's to park.
- **Never held.** Each of these is counted in `claims_page_less`, as PJ-0 did:
  - **No pending line for the slug.** Stage 1 named the endpoint differently from the entity (`"Zed"` in the
    relationship, `"Zed Unknown"` as the entity), or never listed it as an entity. M3 measures this.
  - **The owner surfaces.** The slugs of `OWNER_SURFACES` (`user`, `the-user`, `me`, `myself`, `i`) are never
    held. R-CS2 never invents a `user` page, and a pending "User" line (Stage 1 listing the person) must not
    collect the person's claims and hand them to a page named after a pronoun.
  - **A claim already closed in its own batch.** Stage 3 never tests an incoming claim's own validity
    (`claim_reconciler.py:601`), so a closed claim released later could close an open one. Its open successor
    is held, and keeps its `supersedes` id, which names a claim that is never written. That is disclosed; it is
    the same id a PJ-0 cycle would have written and dropped.
  - **An event.** `is_event` claims are never held, because only `progress.py` writes them (G141 §5.1).
    `_relabel_event_labels` already makes this unreachable from Stage 1; the filter is the rail.

**R-HP3: at most 50 held claims per name, head-stable, and the rest counted.**
- A name promotes on its next mention (`:251-256`) and on two relationships in one conversation (`:689`). So a
  held name normally carries one or two claims. Only a name Stage 2 re-parks cycle after cycle (an `unsure`
  match) can approach the cap.
- **Head-stable.** A claim held once stays held, so a count reported as "held" never turns into a loss later.
  This matches R-PB4 / R-CS9's head-stable caps.
- **Merges are not new.** A claim heard again under a held id merges its evidence and `source_episodes`, as
  `entities_to_claims` and `_reinforce` do. It counts as held, not as a new claim.
- **Refusals.** A claim past the cap is refused at the door. It counts in `claims_hold_capped` and in
  `claims_page_less`, and it appears in the INFO line as a count.
- The constant is `pending_store.MAX_HELD_CLAIMS = 50`.

**R-HP4: a line that holds claims leaves the store only through `pending_store.release`, after Stage 5.56 wrote
its claims onto the page.**
- **Promotion** (`take`, behind `promote_from_pending`) returns a holding line but does **not** remove it, and
  does not rebuild the pending vectors for it.
- **A re-park** (`upsert`, behind `index_pending_entity`) carries the replaced line's hold onto the new line.
- **Why.** Stage 2 flushes `promote_from_pending` at the end of `resolve` (`:358-375`), before Sleep's last
  three cancel points (`sleep_cycle.py:1311,1324,1347`) and before any page exists. Stage 5 or 5.56 can then
  fail. Had promotion removed the claims, a cancel or a failure in that window would lose them with nothing to
  count. Kept on the line, a cancelled cycle simply promotes the name again next time: the episode was not
  marked processed.
- **What else improves.** A promotion whose page never got written leaves the name pending. Today it vanishes
  from the store.
- **What stays.** A holding line stays in the pending vectors until the next Stage 2 rebuild. Nothing in
  production reads them.

**R-HP5: where and when held claims are released.**
- **When.** Every cycle, Stage 5.56 reads the holding lines. It never writes the store at this point.
- **Where.** Each line's target is Stage 2's own **exact** verdict on the line's name this cycle,
  `name_to_id.get(name.lower())`, else the claims' own subject. This covers a promotion (the verdict is the
  slug), a `same` match onto a page with another name, and a page whose `name` equals the line's name. There is
  no fuzzy lookup: a verdict Stage 2 did not reach is not invented here.
- **The condition.** A line is released when `entities/<target>.md` exists, whoever made the page.
- **Re-keying.** The claims are re-keyed onto the target, because R-CS1 says a claim follows Stage 2's match.
  Their ids are unchanged: an id is opaque once minted, and a later projection of the same triple is folded by
  Stage 3's same-object rule.

**R-HP6: released claims enter Stage 3 first, once, as the page's own claims would have.**
- **First.** `incoming = released + stage1 (+ extra)`. The held claims are older, so they meet the reconciler
  as if the page had existed when they were heard: a newer single-valued Stage-1 claim **supersedes** them
  (`claim_reconciler.py:215`). In the other order, the older claim would be the "new" one, not newer, and Stage
  3 would open a `CONFLICT_NUDGE` asking the person something recency already settles.
- **Once.** A held claim whose id is already on the target page is not offered again. This is the idempotency
  guard for a removal that failed after a good write. It matters once a newer claim has closed the written copy
  on the page: offered again, the open held copy would meet its own successor as an older single-valued claim,
  and Stage 3 would open a `CONFLICT_NUDGE` (for a multi-valued predicate, a second claim with the same id).
- **The normalization audit fires once.** It fired in the cycle that heard the claim; `predicate_raw` is not
  serialized, so release cannot raise it again.
- **Attribution.** `recorded_at` and `authored_by` stay the hearing cycle's values: the model that extracted
  the claim, stamped then by `_stamp_new`. Only the commit that writes the claim is the releasing cycle's.

**R-HP7: spans, not copies.**
- A held claim's evidence is the G118 span minted when it was heard: offsets plus `sha256[:12]` of the episode
  body. It is serialized verbatim, released verbatim, and never re-located.
- Freshness is the reader's, through `evidence.span_status`:
  - `current` when the episode is unchanged (the brief's case);
  - `grown` when a resumed session appended to it (G104, the Stop hook);
  - `stale` when it was rewritten.
- A claim that has since been superseded reads "no longer current". One whose stated end has passed is closed
  by `claim_expiry` in the same night's tail. Nothing about staleness is decided at release.

**R-HP8: the page credits the conversation the claim was heard in.**
- In the write that releases claims onto a page, the release unions their `source_episodes` into the page's
  frontmatter `source_episodes`. This is G48's transitive credit: without it the promoted page lists only the
  promoting episode (`entity_resolver.py:276-286`), and the first conversation's row never shows the page.
- A released claim counts as newly written for G61 phase 2 S1's cited-link attach (`claim_pipeline.py:267-278`),
  the same rule as a Stage-1 claim written for the first time.

**R-HP9: pending entities do not expire, and this slice adds no expiry.**
- **The brief's case has no trigger.** The brief says held claims "go with" a pending entity that "expires or is
  dropped". Nothing in the code expires or drops a pending line. The only paths that touch one are promotion,
  re-park and link recon's append-if-absent. Adding a TTL would change the promotion model: a name heard once
  and again months later would stop promoting. That is research R7's "decay-pruned candidates" and decision D2,
  neither of them ruled. So it is not built here, and it goes to the owner as an open question.
- **The guarantee instead is structural.** Claims live on the line; every path that can rewrite or remove a line
  keeps or carries them (R-HP4); `release` is the only exit, and it runs after a write. A future expiry has to
  go through the store and face the claims.
- **Test mapping.** The brief's "an expired pending entity takes its held claims with it" becomes Task 1's
  `test_no_path_but_release_lets_a_held_claim_go`, and `waiting()` makes a hold that never releases visible as
  a count.

**R-HP10: the seam takes the whole cycle at once; the store is settled release-first; a store failure costs only
the hold.**
- **Signature.** `hold_page_less(offers: dict[str, list[Claim]], memory_path) -> dict[str, HoldOutcome]`. That
  is one read and at most one write of the store per cycle, not one per subject. R-CS4's "PJ-0b changes this
  body and nothing else" holds for the hold. The release is a second step in `run_claim_pipeline`, and the cap
  needs its count.
- **Order after the write loop.** First `release` the lines whose target was written. Then hold, so a line is
  never handed new claims in the pass that retires it. Then `waiting`.
- **Failures.** Every store call in the pipeline is wrapped. A failed read releases nothing this cycle. A failed
  hold leaves those claims counted page-less. Neither ever stops the cycle's other claims from being written.

**R-HP11: store writes are atomic and serialized.**
- `pending_store.save` writes a `mkstemp` file in the bank directory and swaps it in with `os.replace`. On
  failure the temp file is removed and the error re-raised.
- **Why.** The file now carries facts, and `load` skips a line it cannot parse (`vector_index.py:484-491`). A
  write torn by a killed process would be read back short and saved short by the next writer, losing held
  claims with nothing to count.
- A module `threading.Lock` makes every read-modify-write atomic in-process. Stage 2's flush, Stage 5.56 and
  link recon all write the file. Today each does its read-modify-write synchronously on the event loop, so they
  cannot interleave; the lock keeps that true if one of them moves to a worker thread (`asyncio.to_thread`, as
  several of Sleep's tail steps already run).

**R-HP12: counts only, and one meaning change.**
- The pipeline result, `SleepState` (internal, never on `/sleep/status`) and the `sleep_run` row gain four
  counts:
  - `claims_held`: offered claims now held;
  - `claims_released`: held claims whose line left after a successful write;
  - `claims_hold_capped`: offered claims refused by the cap;
  - `claims_waiting`: claims still held in the store after the cycle.
- `claims_page_less` now means **neither written nor held**. `subjects_page_less` still counts subjects with no
  page, whether or not their claims were held.
- No log line or ledger ref ever carries a name, a slug or claim text (R-CS3). Claim ids at DEBUG stay opaque,
  as in PJ-0.

**R-HP13: a held claim is a hold, not a belief.**
- No reader shows a held claim: not recall, not search, not citations, not provenance, not the timeline. None of
  them reads the pending store; only Stage 2 and link recon do, for names.
- It becomes visible the moment it is written onto a page, like any claim.
- No endpoint, ETag component, Store domain or app surface changes, so the ETag ship-together rule is not
  engaged.

---

## File map

| File | Task | Change |
|---|---|---|
| `api/services/pending_store.py` | 1 | **Create.** `PendingEntity` (moved, + `held_claims`), `load`/`save` (atomic)/`upsert`/`take`/`hold`/`ready`/`release`/`waiting`, `HoldOutcome`, `Release`, `MAX_HELD_CLAIMS`. |
| `api/services/vector_index.py` | 1 | Drop the `PendingEntity` class and the `PENDING_STORE_FILE` constant (re-exported from `pending_store`); `_load_pending`/`_save_pending`/`index_pending_entity`/`promote_from_pending` delegate; drop the unused `dataclass` import. |
| `api/tests/test_pending_store.py` | 1 | **Create.** |
| `api/services/claim_pipeline.py` | 2 | Module docstring (Stage 5); `hold_page_less` body + signature; `_OWNER_SLUGS`, `_release_target`, `_releases`, `_credit_episodes`, `_settle_store`; `run_claim_pipeline` releases first, credits the page, settles the store, returns four counts. |
| `api/tests/test_claim_pipeline_hold.py` | 2 | **Create.** |
| `api/tests/test_claim_pipeline_subjects.py` | 2 | Rewrite the R-PJ17 seam test (`:182-196`) for the new signature. |
| `api/services/sleep_cycle.py` | 3 | `SleepState` + reset + assignment of the four counts; the 5.56 INFO line; the `sleep_run` refs. |
| `api/tests/test_sleep_cycle_hold.py` | 3 | **Create.** Two real cycles + the ledger row. |
| `CLAUDE.md`, `docs/goals/memory-evolution.md`, `docs/goals/TODO.md`, this plan | 4 | One sentence under Entity promotion; the G141 row; TODO (three spots + one new owner question). |

---

### Task 1: The pending store can hold claims, and only a release lets them go (R-HP1, R-HP3, R-HP4, R-HP9, R-HP11)

**Files:**
- Create: `api/services/pending_store.py`
- Modify: `api/services/vector_index.py`:
  - `:20-29` (imports);
  - `:36` (the constant moves);
  - `:49-83` (the class moves);
  - `:478-546` (the pending methods delegate).
- Test: `api/tests/test_pending_store.py` (new). Must stay green: `api/tests/test_vector_index.py`,
  `api/tests/test_entity_resolver_transactional.py`, `api/tests/test_link_recon.py`.

**Interfaces:**
- Produces:
  - `pending_store.PENDING_STORE_FILE`, `MAX_HELD_CLAIMS`, `PendingEntity(…, held_claims=[])`,
    `HoldOutcome(held, capped)` and `Release(name, target, claims)`;
  - `load(memory_path)`, `save(memory_path, entries)`, `upsert(memory_path, entity)`,
    `take(memory_path, name) -> (entry | None, removed)`;
  - `hold(memory_path, offers, *, cap=MAX_HELD_CLAIMS) -> dict[str, HoldOutcome]`,
    `ready(memory_path, target_of) -> list[Release]`, `release(memory_path, names) -> int` and
    `waiting(memory_path) -> (claims, names)`.
- Consumes: `claims.Claim`, `id_utils.bank_file`, `id_utils.sanitize_id`.
- Contracts that do not change: `SqliteVecIndexer.index_pending_entity`, `pending_by_name`, `list_pending`,
  `rebuild_pending_index` and `promote_from_pending` keep their signatures. Only a holding line's promotion
  changes (R-HP4).

- [ ] **Step 1: Write the failing tests.**

```python
# api/tests/test_pending_store.py
"""G141 PJ-0b (R-HP1, R-HP3, R-HP4, R-HP9, R-HP11): the pending store — names
Sleep parked, and since PJ-0b the claims it heard about them — as one module
that owns `pending_entities.jsonl`. A holding line leaves the store only
through `release`; promotion keeps it, a re-park carries it, nothing expires
it. Synthetic names only."""
from __future__ import annotations

import pytest

from api.services import pending_store
from api.services.claims import Claim, Evidence
from api.services.pending_store import HoldOutcome, PendingEntity
from api.services.vector_index import SqliteVecIndexer

EP = "ep_2026-09-20_001"
LEGACY = ('{"name": "Zed Unknown", "type": "person", "description": "Mentioned once.", '
          '"source_episode": "ep_2026-09-20_001", "confidence": 0.6, "tags": [], "history_entries": []}\n')


def _pending(name: str, **overrides) -> PendingEntity:
    fields = dict(name=name, type="person", description="Mentioned once.", source_episode=EP,
                  confidence=0.6, tags=[], history_entries=[])
    fields.update(overrides)
    return PendingEntity(**fields)


def _claim(cid: str, subject: str = "zed-unknown", obj: str = "gamma-board", *, start: int = 6) -> Claim:
    return Claim(id=cid, text=f"{subject} recommends {obj}", subject=subject, predicate="recommends",
                 object=obj, valid_from="2026-09-20", source_episodes=[EP],
                 evidence=[Evidence(episode=EP, start=start, end=start + 10, kind="user", hash="abc123def456")])


def _store_text(tmp_path) -> str:
    return (tmp_path / pending_store.PENDING_STORE_FILE).read_text(encoding="utf-8")


def test_a_line_written_before_pj0b_round_trips_byte_for_byte(tmp_path):
    (tmp_path / pending_store.PENDING_STORE_FILE).write_text(LEGACY, encoding="utf-8")
    (line,) = pending_store.load(tmp_path)
    assert line.held_claims == [] and "held_claims" not in line.to_dict()
    pending_store.save(tmp_path, [line])
    assert _store_text(tmp_path) == LEGACY


def test_held_claims_round_trip_as_the_claims_they_were(tmp_path):
    claim = _claim("clm_a")
    pending_store.save(tmp_path, [_pending("Zed Unknown", held_claims=[claim.to_dict()])])
    (line,) = pending_store.load(tmp_path)
    assert Claim.from_dict(line.held_claims[0]) == claim


def test_hold_goes_to_the_line_whose_slug_is_the_subject(tmp_path):
    pending_store.upsert(tmp_path, _pending("Zed Unknown"))
    pending_store.upsert(tmp_path, _pending("Gamma Board", type="tool"))
    out = pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")], "nobody-here": [_claim("clm_b")]})
    assert out == {"zed-unknown": HoldOutcome(1, 0), "nobody-here": HoldOutcome(0, 0)}
    held = {e.name: [d["id"] for d in e.held_claims] for e in pending_store.load(tmp_path)}
    assert held == {"Zed Unknown": ["clm_a"], "Gamma Board": []}


def test_hold_writes_nothing_when_no_line_matches(tmp_path):
    assert pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")]}) == {"zed-unknown": HoldOutcome(0, 0)}
    assert pending_store.hold(tmp_path, {"zed-unknown": []}) == {}
    assert not (tmp_path / pending_store.PENDING_STORE_FILE).exists()


def test_a_claim_heard_again_merges_its_evidence_by_id(tmp_path):
    pending_store.upsert(tmp_path, _pending("Zed Unknown"))
    pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a", start=6)]})
    again = _claim("clm_a", start=40)
    again.source_episodes = ["ep_2026-09-21_001"]
    assert pending_store.hold(tmp_path, {"zed-unknown": [again]}) == {"zed-unknown": HoldOutcome(1, 0)}
    (line,) = pending_store.load(tmp_path)
    (held,) = line.held_claims
    assert [e["start"] for e in held["evidence"]] == [6, 40]
    assert held["source_episodes"] == [EP, "ep_2026-09-21_001"]


def test_the_cap_is_head_stable_and_counts_what_it_refuses(tmp_path):
    pending_store.upsert(tmp_path, _pending("Zed Unknown"))
    first = pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a"), _claim("clm_b"), _claim("clm_c")]}, cap=2)
    assert first == {"zed-unknown": HoldOutcome(2, 1)}
    later = pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_d"), _claim("clm_a")]}, cap=2)
    assert later == {"zed-unknown": HoldOutcome(1, 1)}  # clm_a merges; clm_d is refused
    (line,) = pending_store.load(tmp_path)
    assert [d["id"] for d in line.held_claims] == ["clm_a", "clm_b"]
    assert pending_store.MAX_HELD_CLAIMS == 50


def test_a_same_name_re_park_carries_the_hold(tmp_path):
    pending_store.upsert(tmp_path, _pending("Zed Unknown"))
    pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")]})
    SqliteVecIndexer(tmp_path).index_pending_entity(_pending("zed unknown", description="Parked again."))
    (line,) = pending_store.load(tmp_path)
    assert line.description == "Parked again." and [d["id"] for d in line.held_claims] == ["clm_a"]


def test_promotion_keeps_a_holding_line_and_removes_a_plain_one(tmp_path, monkeypatch):
    rebuilt: list[list[str]] = []
    monkeypatch.setattr(SqliteVecIndexer, "_rebuild_pending_index",
                        lambda self, entries: rebuilt.append([e.name for e in entries]))
    indexer = SqliteVecIndexer(tmp_path)
    indexer.index_pending_entity(_pending("Gamma Board", type="tool"))
    indexer.index_pending_entity(_pending("Zed Unknown"))
    pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")]})

    holding = indexer.promote_from_pending("zed unknown")
    assert holding is not None and [d["id"] for d in holding.held_claims] == ["clm_a"]
    assert indexer.pending_by_name("Zed Unknown") is not None and rebuilt == []

    plain = indexer.promote_from_pending("Gamma Board")
    assert plain is not None and plain.name == "Gamma Board"
    assert indexer.pending_by_name("Gamma Board") is None and rebuilt == [["Zed Unknown"]]
    assert indexer.promote_from_pending("Nobody Here") is None


def test_no_path_but_release_lets_a_held_claim_go(tmp_path, monkeypatch):
    """R-HP4/R-HP9 — the brief's "expired or dropped" case: nothing expires a
    pending line today, so the guarantee is structural. Every path that can
    rewrite or remove a line keeps or carries its hold; `release` is the only
    exit, and Stage 5.56 calls it only after the page write succeeded."""
    monkeypatch.setattr(SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    indexer = SqliteVecIndexer(tmp_path)
    indexer.index_pending_entity(_pending("Zed Unknown"))
    pending_store.hold(tmp_path, {"zed-unknown": [_claim("clm_a")]})
    indexer.index_pending_entity(_pending("Zed Unknown"))            # re-parked
    indexer.promote_from_pending("Zed Unknown")                        # promoted
    indexer.index_pending_entity(_pending("Gamma Board", type="tool"))  # another name parked
    assert pending_store.waiting(tmp_path) == (1, 1)
    assert pending_store.release(tmp_path, []) == 0
    assert pending_store.release(tmp_path, ["zed unknown"]) == 1
    assert pending_store.waiting(tmp_path) == (0, 0)
    assert [e.name for e in pending_store.load(tmp_path)] == ["Gamma Board"]


def test_ready_offers_only_lines_whose_page_exists_and_follows_stage2(tmp_path):
    (tmp_path / "entities").mkdir()
    for name in ("Zed Unknown", "Delta Unknown", "Echo Unknown"):
        pending_store.upsert(tmp_path, _pending(name))
    pending_store.hold(tmp_path, {
        "zed-unknown": [_claim("clm_z", "zed-unknown")],
        "delta-unknown": [_claim("clm_d", "delta-unknown")],
        "echo-unknown": [_claim("clm_e", "echo-unknown")],
    })
    (tmp_path / "entities" / "zed-unknown.md").write_text("---\nname: Zed Unknown\n---\n\nx\n", encoding="utf-8")
    (tmp_path / "entities" / "echo-example.md").write_text("---\nname: Echo Example\n---\n\nx\n", encoding="utf-8")
    verdicts = {"echo unknown": "echo-example"}  # Stage 2 matched this name to an existing page

    out = pending_store.ready(tmp_path, lambda name, subject: verdicts.get(name.lower()) or subject)
    assert sorted((r.name, r.target, [c.subject for c in r.claims], [c.id for c in r.claims]) for r in out) == [
        ("Echo Unknown", "echo-example", ["echo-example"], ["clm_e"]),
        ("Zed Unknown", "zed-unknown", ["zed-unknown"], ["clm_z"]),
    ]
    assert pending_store.waiting(tmp_path) == (3, 3)  # ready() never writes


def test_ready_skips_a_held_claim_that_no_longer_parses(tmp_path):
    (tmp_path / "entities").mkdir()
    (tmp_path / "entities" / "zed-unknown.md").write_text("---\nname: Zed Unknown\n---\n\nx\n", encoding="utf-8")
    bad = {"id": "clm_bad", "text": "t", "subject": "zed-unknown", "confidence": "not-a-number"}
    pending_store.save(tmp_path, [_pending("Zed Unknown", held_claims=[_claim("clm_a").to_dict(), bad])])
    (release,) = pending_store.ready(tmp_path, lambda name, subject: subject)
    assert [c.id for c in release.claims] == ["clm_a"]


def test_a_failed_save_leaves_the_old_file_and_no_temp_file(tmp_path, monkeypatch):
    (tmp_path / pending_store.PENDING_STORE_FILE).write_text(LEGACY, encoding="utf-8")

    def boom(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr(pending_store.os, "replace", boom)
    with pytest.raises(OSError):
        pending_store.save(tmp_path, [])
    assert _store_text(tmp_path) == LEGACY
    assert sorted(p.name for p in tmp_path.iterdir()) == [pending_store.PENDING_STORE_FILE]


def test_vector_index_still_exports_the_store_names():
    from api.services import vector_index

    assert vector_index.PendingEntity is pending_store.PendingEntity
    assert vector_index.PENDING_STORE_FILE == pending_store.PENDING_STORE_FILE == "pending_entities.jsonl"
```

- [ ] **Step 2: Run them. They fail** because `api.services.pending_store` does not exist (ImportError).

`cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests/test_pending_store.py -q -p no:cacheprovider`

- [ ] **Step 3: Create `api/services/pending_store.py`.**

```python
"""The pending store — names Sleep heard once and has not promoted, and what it
heard about them before they had a page (G141 PJ-0b).

``<bank>/pending_entities.jsonl``, one JSON object per line. Stage 2 parks every
sub-threshold entity here (the promotion model's first rung, CLAUDE.md "Entity
promotion") and promotes it on its next mention (``entity_resolver.resolve``);
G102's link recon parks a first mention the same way. The file used to be read
and written inside ``vector_index.SqliteVecIndexer``. It moved here (R-HP1)
because PJ-0b's hold and release are file work with no embedding — Stage 5.56
must not build a vector index to keep a claim. ``SqliteVecIndexer`` keeps its
embedding of these lines and delegates the file to this module: ONE writer.

Not a derived artifact (TODO ruling 3): deleting it costs facts — a first
mention and, since PJ-0b, the claims Sleep heard about that name. So it stays
where it always was, tracked in the bank's git and committed by the cycle that
changed it.

**The hold.** A line may carry ``held_claims``: the Stage-1 claims whose subject
is this name's slug, each as ``Claim.to_dict()`` — its id, observer, trust,
context, validity and G118 evidence spans (offsets and a hash into the source
episode, never a copy of its text). Omitted when empty, so every line written
before PJ-0b loads and saves byte for byte. A line that holds claims leaves the
store ONLY through :func:`release`, called after Stage 5.56 wrote them onto the
page (R-HP4): :func:`take` (promotion) keeps it, :func:`upsert` (a re-park)
carries its hold, and nothing expires a line (R-HP9).
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, NamedTuple

from loguru import logger

from api.services.claims import Claim
from api.services.id_utils import bank_file, sanitize_id

PENDING_STORE_FILE = "pending_entities.jsonl"

#: R-HP3 — claims held per name, head-stable. A name promotes on its next
#: mention and on two relationships in one conversation
#: (``entity_resolver.SUBSTANTIVE_RELATIONSHIP_COUNT``), so a held name
#: normally carries one or two; only a name Stage 2 keeps re-parking (an
#: ``unsure`` match, cycle after cycle) comes near this. Past it a claim is
#: refused at the door and counted — a claim already held is never evicted.
MAX_HELD_CLAIMS = 50

#: R-HP11 — every read-modify-write below runs under this lock. Stage 2's
#: flush, Stage 5.56 and link recon all write this file; today each does so
#: synchronously on the event loop, and the lock keeps a lost update
#: impossible if one of them moves to a worker thread (`asyncio.to_thread`).
_LOCK = threading.Lock()


@dataclass
class PendingEntity:
    """A sub-threshold entity (first mention) awaiting a promotion trigger."""

    name: str
    type: str
    description: str
    source_episode: str
    confidence: float
    tags: list[str]
    history_entries: list[dict]
    # G141 PJ-0b (R-HP1): what Sleep heard about this name while it had no
    # page, as `Claim.to_dict()` — spans into the episode, never its text.
    held_claims: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "source_episode": self.source_episode,
            "confidence": self.confidence,
            "tags": self.tags or [],
            "history_entries": self.history_entries or [],
        }
        # Absent when empty: a line from before PJ-0b re-writes byte for byte.
        if self.held_claims:
            data["held_claims"] = list(self.held_claims)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "PendingEntity":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", "concept"),
            description=data.get("description", ""),
            source_episode=data.get("source_episode", ""),
            confidence=float(data.get("confidence", 0.3)),
            tags=data.get("tags", []) or [],
            history_entries=data.get("history_entries", []) or [],
            held_claims=[
                d for d in (data.get("held_claims") or []) if isinstance(d, dict) and d.get("id")
            ],
        )


class HoldOutcome(NamedTuple):
    """Of the claims offered for one subject: how many are now held (new, or
    merged into a claim already held under the same id) and how many the
    per-name cap refused (R-HP3)."""

    held: int
    capped: int


@dataclass
class Release:
    """One pending line whose claims can go onto a page now (R-HP5): ``name`` is
    the line's key, ``target`` the page id, ``claims`` re-keyed onto it."""

    name: str
    target: str
    claims: list[Claim]


def store_path(memory_path: Path) -> Path:
    return Path(memory_path) / PENDING_STORE_FILE


def load(memory_path: Path) -> list[PendingEntity]:
    """Every line, in file order. A line that is not JSON is skipped, as
    ``SqliteVecIndexer._load_pending`` always did."""
    path = store_path(memory_path)
    if not path.exists():
        return []
    out: list[PendingEntity] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(PendingEntity.from_dict(json.loads(line)))
        except Exception:
            continue
    return out


def save(memory_path: Path, entries: list[PendingEntity]) -> None:
    """Replace the file with ``entries`` — atomically (R-HP11).

    The file now carries claims, and :func:`load` skips a line it cannot
    parse: a write torn by a killed process would be read back short and saved
    short by the next writer, losing held claims with nothing to count. So the
    text goes to a temp file in the bank directory and replaces the old file in
    one ``os.replace``. A failed write removes the temp file — a stray file in
    the bank would ride the next ``git add -A`` commit — and re-raises."""
    path = store_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(e.to_dict()) for e in entries) + "\n" if entries else ""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".pending_entities-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _merge_into(prior: dict, incoming: dict) -> bool:
    """A claim heard again under the same id adds its evidence and episodes —
    G118 R8's rule for a restatement (``claim_reconciler._reinforce``) and
    ``entities_to_claims``'s for overlapping chunks; everything else stays as
    first heard. True when ``prior`` changed."""
    changed = False
    for key in ("evidence", "source_episodes"):
        have = list(prior.get(key) or [])
        for item in incoming.get(key) or []:
            if item not in have:
                have.append(item)
                changed = True
        if have:
            prior[key] = have
    return changed


def _merged(first: list[dict], second: list[dict]) -> list[dict]:
    """Two holds as one, by claim id: ``first`` in order, then what ``second`` adds."""
    out = [dict(d) for d in first]
    by_id = {d.get("id"): d for d in out}
    for data in second:
        prior = by_id.get(data.get("id"))
        if prior is None:
            copy = dict(data)
            out.append(copy)
            by_id[copy.get("id")] = copy
        else:
            _merge_into(prior, data)
    return out


def upsert(memory_path: Path, entity: PendingEntity) -> None:
    """Park ``entity``: append it, or replace the same-named line(s), case-insensitive.

    G141 PJ-0b (R-HP4): the replaced line's hold is CARRIED onto the new one,
    never dropped. Stage 2 re-parks a name it could not settle — an ``unsure``
    match reaches the else-branch every cycle it is heard
    (``entity_resolver.resolve``) — with a fresh ``PendingEntity`` that knows
    nothing of what was held."""
    with _LOCK:
        entries = load(memory_path)
        key = entity.name.lower()
        carried: list[dict] = []
        kept: list[PendingEntity] = []
        for e in entries:
            if e.name.lower() == key:
                carried = _merged(carried, e.held_claims)
            else:
                kept.append(e)
        entity.held_claims = _merged(carried, entity.held_claims)
        kept.append(entity)
        save(memory_path, kept)


def take(memory_path: Path, name: str) -> tuple[PendingEntity | None, bool]:
    """Promotion's read-and-remove: ``(line, removed)`` for the first line named
    ``name`` (case-insensitive); ``(None, False)`` when there is none.

    G141 PJ-0b (R-HP4): a line that holds claims is returned but NOT removed.
    Stage 2 flushes this at the end of ``resolve``, before Sleep's last three
    cancel points and before any page exists; the line leaves through
    :func:`release` once Stage 5.56 has written its claims onto the page — so
    a cancel, a failed Stage 5 or a failed claim write between the two leaves
    the claims where they were."""
    with _LOCK:
        entries = load(memory_path)
        key = (name or "").lower()
        for i, e in enumerate(entries):
            if e.name.lower() != key:
                continue
            if e.held_claims:
                return e, False
            del entries[i]
            save(memory_path, entries)
            return e, True
        return None, False


def hold(
    memory_path: Path, offers: dict[str, list[Claim]], *, cap: int = MAX_HELD_CLAIMS,
) -> dict[str, HoldOutcome]:
    """Hold each subject's claims on the pending line whose slug IS that subject (R-HP2).

    ``sanitize_id(line.name)`` is the id Stage 2's promotion gives the page, so
    a held claim lands where the page will be; there is no fuzzy match over
    pending names. A claim already held under its id merges
    (:func:`_merge_into`); a new one is appended until the line holds ``cap``
    (head-stable, R-HP3). One read and at most one write for the whole cycle,
    and nothing is written when nothing changed — a bank with no store never
    gains one. Returns an outcome for every subject offered a non-empty list:
    ``(0, 0)`` for one with no line."""
    offers = {s: list(c) for s, c in offers.items() if c}
    if not offers:
        return {}
    with _LOCK:
        entries = load(memory_path)
        by_slug: dict[str, PendingEntity] = {}
        for e in entries:
            by_slug.setdefault(sanitize_id(e.name), e)
        out: dict[str, HoldOutcome] = {}
        changed = False
        for subject, claims in offers.items():
            line = by_slug.get(subject)
            if line is None:
                out[subject] = HoldOutcome(0, 0)
                continue
            by_id = {d.get("id"): d for d in line.held_claims}
            held = capped = 0
            for claim in claims:
                data = claim.to_dict()
                prior = by_id.get(claim.id)
                if prior is not None:
                    changed = _merge_into(prior, data) or changed
                    held += 1
                elif len(line.held_claims) >= cap:
                    capped += 1
                else:
                    line.held_claims.append(data)
                    by_id[claim.id] = data
                    held += 1
                    changed = True
            out[subject] = HoldOutcome(held, capped)
        if changed:
            save(memory_path, entries)
        return out


def ready(memory_path: Path, target_of: Callable[[str, str], str]) -> list[Release]:
    """Read-only: the holding lines whose claims can go onto a page NOW (R-HP5).

    ``target_of(line_name, subject)`` names the page — Stage 5.56 passes Stage
    2's exact verdict on the name this cycle, else the claims' own subject. A
    line whose target has no page is left for a later cycle. The claims come
    back re-keyed onto the target (R-CS1: a claim follows Stage 2's match),
    everything else as held. Nothing is removed here: that is :func:`release`,
    after the write succeeded (R-HP4). A held dict that no longer parses is
    skipped and counted in a warning — a count, never a name (R-CS3)."""
    entities_dir = Path(memory_path) / "entities"
    out: list[Release] = []
    unreadable = 0
    for line in load(memory_path):
        claims: list[Claim] = []
        for data in line.held_claims:
            try:
                claims.append(Claim.from_dict(data))
            except (TypeError, ValueError):
                unreadable += 1
        if not claims:
            continue
        target = target_of(line.name, claims[0].subject) or claims[0].subject
        page = bank_file(entities_dir, target)
        if page is None or not page.is_file():
            continue
        for claim in claims:
            claim.subject = target
        out.append(Release(line.name, target, claims))
    if unreadable:
        logger.warning(f"pending store: {unreadable} held claim(s) could not be read; they leave with their line")
    return out


def release(memory_path: Path, names: Iterable[str]) -> int:
    """Remove the lines whose claims Stage 5.56 just wrote onto their page — the
    one way a holding line leaves the store (R-HP4). Returns how many lines
    left; writes nothing when there is nothing to remove."""
    keys = {n.lower() for n in names if n}
    if not keys:
        return 0
    with _LOCK:
        entries = load(memory_path)
        kept = [e for e in entries if e.name.lower() not in keys]
        gone = len(entries) - len(kept)
        if gone:
            save(memory_path, kept)
        return gone


def waiting(memory_path: Path) -> tuple[int, int]:
    """``(claims, names)`` still held — R-HP12's ``claims_waiting``. A hold that
    never releases (its name was never mentioned again, or Stage 2 merged it
    into a page with another name and never heard it again) shows up here as a
    number instead of nowhere."""
    lines = [e for e in load(memory_path) if e.held_claims]
    return sum(len(e.held_claims) for e in lines), len(lines)
```

- [ ] **Step 4: Make `vector_index.py` delegate.**
  - In the imports (`:20-29`), delete `from dataclasses import dataclass`. It is unused once the class moves;
    confirm with `grep -n "dataclass" api/services/vector_index.py`, which must print nothing after the edit.
    After `from api.services import markdown_parser`, add:

```python
from api.services import pending_store as _store
# G141 PJ-0b (R-HP1): the pending store is its own module now. These two names
# stay importable from here — entity_resolver, link_recon and the tests use them.
from api.services.pending_store import PENDING_STORE_FILE, PendingEntity  # noqa: F401
```

  - Delete the constant line `:36` (`PENDING_STORE_FILE = "pending_entities.jsonl"`) and the whole
    `PendingEntity` class (`:49-83`, from `@dataclass` through the end of `from_dict`). `:127`
    (`self.pending_store = self.memory_path / PENDING_STORE_FILE`) stays as it is.
  - Replace the pending methods `_load_pending` through `promote_from_pending` (`:478-546`) with the block
    below. `rebuild_pending_index`, `list_pending`, `pending_by_name`, `_rebuild_pending_index` and
    `search_pending` keep their bodies; `list_pending` and `pending_by_name` already go through
    `_load_pending`.

```python
    # ---------- pending (sub-threshold) index ----------
    #
    # The file is `pending_store`'s (G141 PJ-0b, R-HP1): these methods keep
    # their names and contracts for Stage 2 and link recon and delegate every
    # read and write to that one module. The vectors below stay here.

    def _load_pending(self) -> list[PendingEntity]:
        return _store.load(self.memory_path)

    def _save_pending(self, entries: list[PendingEntity]) -> None:
        _store.save(self.memory_path, entries)

    def index_pending_entity(self, entity: PendingEntity) -> None:
        """Append/replace a sub-threshold entity in the store (no vec rebuild).

        Rebuilding the vec table per add would be O(N^2) embedding calls in a
        single sleep batch; call :meth:`rebuild_pending_index` once afterward.
        A replaced line's held claims are carried, never dropped
        (``pending_store.upsert``, G141 PJ-0b R-HP4).
        """
        _store.upsert(self.memory_path, entity)

    def rebuild_pending_index(self) -> int:
        entries = self._load_pending()
        if not entries:
            return 0
        self._rebuild_pending_index(entries)
        return len(entries)

    def list_pending(self) -> list[PendingEntity]:
        return self._load_pending()

    def pending_by_name(self, name: str) -> PendingEntity | None:
        name_lower = name.lower()
        for e in self._load_pending():
            if e.name.lower() == name_lower:
                return e
        return None

    def promote_from_pending(self, entity_name: str) -> PendingEntity | None:
        """Remove and return an entry from the pending store, rebuild the index.

        G141 PJ-0b (R-HP4): an entry that still holds claims is returned but
        STAYS — it leaves through ``pending_store.release`` once Stage 5.56 has
        written its claims onto the new page — and nothing is rebuilt for it,
        since nothing left the store.
        """
        promoted, removed = _store.take(self.memory_path, entity_name)
        if removed:
            self._rebuild_pending_index(self._load_pending())
        return promoted
```

- [ ] **Step 5: Run the new tests and the store's existing callers. All pass.**

`cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests/test_pending_store.py api/tests/test_vector_index.py api/tests/test_entity_resolver_transactional.py api/tests/test_link_recon.py -q -p no:cacheprovider`

- [ ] **Step 6: Full suite.** `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` must report 0 failures.

- [ ] **Step 7: Commit.**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && git add api/services/pending_store.py api/services/vector_index.py api/tests/test_pending_store.py && git commit -F - <<'EOF'
feat(g141): PJ-0b — the pending store can hold claims, and only a release lets them go

pending_entities.jsonl gets one owner module, api/services/pending_store.py;
SqliteVecIndexer delegates and re-exports PendingEntity. A line may carry
held_claims (Claim.to_dict — spans, not copies), omitted when empty so every
existing line is byte-identical. Promotion keeps a holding line, a re-park
carries its hold, release is the only exit (R-HP4); nothing expires a line
(R-HP9). Head-stable cap of 50 per name, refusals counted (R-HP3). Saves are
atomic and serialized (R-HP11). R-HP1.

<attribution lines from the session's system reminder>
EOF
```

---

### Task 2: Sleep holds a page-less subject's claims and releases them on promotion (R-HP2, R-HP5–R-HP8, R-HP10, R-HP12, R-HP13)

**Files:**
- Modify: `api/services/claim_pipeline.py`:
  - the module docstring's Stage-5 paragraph (`:26-35`);
  - imports (`:53-58`);
  - `hold_page_less` (`:104-112`), plus new helpers after it;
  - `run_claim_pipeline` (`:156-300`).
- Modify: `api/tests/test_claim_pipeline_subjects.py:182-196` (the seam test) and its imports (`:13-16`).
- Test: `api/tests/test_claim_pipeline_hold.py` (new). Must stay green: `test_claim_pipeline.py`,
  `test_claims_corruption_guard.py`, `test_progress_writes.py`, `test_extraction_source_attach.py`,
  `test_sleep_cycle_claims_wired.py`.

**Interfaces:**
- Produces:
  - `claim_pipeline.hold_page_less(offers: dict[str, list[Claim]], memory_path) -> dict[str, HoldOutcome]`;
  - the `run_claim_pipeline` result gains `claims_held`, `claims_hold_capped`, `claims_released` and
    `claims_waiting` (ints). `claims_page_less` now means neither written nor held.
- Consumes: Task 1's `pending_store.ready`/`release`/`hold`/`waiting`, `HoldOutcome` and `Release`.

- [ ] **Step 1: Write the failing tests.**

```python
# api/tests/test_claim_pipeline_hold.py
"""G141 PJ-0b (R-HP2, R-HP5..R-HP8, R-HP10, R-HP12): Stage 5.56 holds what it
heard about a name with no page WITH that name's pending entity, and releases
it — first, through Stage 3, spans intact, the first conversation credited —
in the cycle whose Stage 5 gave the name a page. Synthetic names only."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from loguru import logger

from api.services import claim_pipeline, evidence, fact_sources, markdown_parser, pending_store, predicates
from api.services.claims import Claim, parse_claims, write_claims
from api.services.pending_store import HoldOutcome, PendingEntity

EP_A, TS_A = "ep_2026-09-20_001", "2026-09-20T10:00:00+00:00"
EP_B, TS_B = "ep_2026-09-22_001", "2026-09-22T10:00:00+00:00"
BODY_A = "user: Zed Unknown works at Alpha Lab and recommends Gamma Board.\nassistant: Noted."
BODY_B = "user: Zed Unknown works at Beta Lab now.\nassistant: Good to know."
FENCE = "`" * 3
BROKEN = f"## Summary\nA synthetic page.\n\n{FENCE}claims\n- id: [unclosed\n{FENCE}"


def _settings(memory: Path) -> SimpleNamespace:
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4, sleep_promotion_threshold=2,
                           link_enrich_enabled=False)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _episode(memory: Path, ep: str, ts: str, body: str) -> str:
    """Write an episode and return its stored evidence text (what a span hashes)."""
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "processed": True, "source": "mcp", "timestamp": ts}, body)
    return evidence.source_text(memory, ep)


def _park(memory: Path, name: str) -> None:
    """What Stage 2's flush does for a name it did not promote."""
    pending_store.upsert(memory, PendingEntity(
        name=name, type="person", description="Mentioned once.", source_episode=EP_A,
        confidence=0.6, tags=[], history_entries=[]))


def _rel(source: str, label: str, target: str, ep: str, ts: str, text: str, quote: str) -> dict:
    return {"source": source, "target": target, "label": label, "source_episode": ep,
            "source_episode_timestamp": ts,
            "evidence": [evidence.verify(None, ep, quote, text=text).to_dict()]}


def _extracted(ep: str, ts: str, *rels: dict) -> list[dict]:
    return [{"episode_id": ep, "episode_timestamp": ts, "origin": "claude-code",
             "entities": [], "relationships": list(rels)}]


def _page(memory: Path, entity_id: str, name: str, body: str = "## Summary\nA synthetic page.") -> Path:
    """What Stage 5 writes for a promoted name (credited to the promoting episode)."""
    path = memory / "entities" / f"{entity_id}.md"
    markdown_parser.write(path, {"name": name, "type": "person", "status": "active",
                                 "source_episodes": [EP_B]}, body)
    return path


def _claims(memory: Path, entity_id: str) -> list[Claim]:
    return parse_claims(markdown_parser.parse(memory / "entities" / f"{entity_id}.md").body)


def _run(memory: Path, extracted: list[dict], *, now: str, name_to_id: dict | None = None) -> dict:
    return claim_pipeline.run_claim_pipeline(extracted, [], memory, _settings(memory),
                                             now_date=now, name_to_id=name_to_id or {})


def _hear_recommendation(memory: Path) -> tuple[dict, str]:
    """Conversation 1: "Zed Unknown" is parked, has no page, and Stage 1 heard one claim about it."""
    text = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    rel = _rel("Zed Unknown", "recommends", "Gamma Board", EP_A, TS_A, text, "recommends Gamma Board")
    return _run(memory, _extracted(EP_A, TS_A, rel), now="2026-09-20"), text


def test_a_claim_on_an_unpromoted_name_is_held_with_its_span_and_no_page_is_made(tmp_path):
    memory = _bank(tmp_path)
    result, text = _hear_recommendation(memory)
    assert (result["claims_held"], result["claims_page_less"], result["claims_waiting"]) == (1, 0, 1)
    assert result["subjects_skipped"] == 1 and result["page_less_subjects"] == ["zed-unknown"]
    assert list((memory / "entities").glob("*.md")) == []
    (line,) = pending_store.load(memory)
    assert line.name == "Zed Unknown"
    (held,) = [Claim.from_dict(d) for d in line.held_claims]
    assert (held.subject, held.predicate, held.object) == ("zed-unknown", "recommends", "gamma-board")
    assert (held.observer, held.context, held.source_trust, held.valid_from) == (
        "agent", "general", "agent_extracted", "2026-09-20")
    (ev,) = held.evidence
    assert ev.episode == EP_A and text[ev.start:ev.end] == "recommends Gamma Board"


def test_promotion_writes_the_held_claim_onto_the_new_page_with_its_span_current(tmp_path):
    memory = _bank(tmp_path)
    _hear_recommendation(memory)
    held_id = pending_store.load(memory)[0].held_claims[0]["id"]
    _episode(memory, EP_B, TS_B, BODY_B)
    _page(memory, "zed-unknown", "Zed Unknown")
    result = _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})

    (claim,) = _claims(memory, "zed-unknown")
    assert claim.id == held_id and claim.valid_to is None
    (ev,) = claim.evidence
    text = evidence.source_text(memory, EP_A)
    assert text[ev.start:ev.end] == "recommends Gamma Board"
    assert evidence.span_status(text, end=ev.end, hash=ev.hash) == evidence.SPAN_CURRENT
    fm = markdown_parser.parse(memory / "entities" / "zed-unknown.md").frontmatter
    assert fm["source_episodes"] == [EP_B, EP_A]  # R-HP8: the first conversation credits the page
    assert (result["claims_released"], result["claims_waiting"]) == (1, 0)
    assert pending_store.load(memory) == []


def test_a_held_claim_keeps_its_span_when_the_episode_grew_since(tmp_path):
    memory = _bank(tmp_path)
    _hear_recommendation(memory)
    held = Claim.from_dict(pending_store.load(memory)[0].held_claims[0])
    # A resumed session: the Stop hook appends turns to the same episode (G104).
    _episode(memory, EP_A, TS_A, BODY_A + "\nuser: One more thing.\nassistant: Sure.")
    _page(memory, "zed-unknown", "Zed Unknown")
    _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    (claim,) = _claims(memory, "zed-unknown")
    assert claim.evidence == held.evidence  # never re-located (R-HP7)
    (ev,) = claim.evidence
    assert evidence.span_status(evidence.source_text(memory, EP_A), end=ev.end, hash=ev.hash) == evidence.SPAN_GROWN


def test_a_newer_claim_supersedes_the_released_one_instead_of_asking(tmp_path):
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    _run(memory, _extracted(EP_A, TS_A, _rel("Zed Unknown", "works at", "Alpha Lab", EP_A, TS_A, text_a,
                                             "Zed Unknown works at Alpha Lab")), now="2026-09-20")
    text_b = _episode(memory, EP_B, TS_B, BODY_B)
    _page(memory, "zed-unknown", "Zed Unknown")
    result = _run(memory, _extracted(EP_B, TS_B, _rel("Zed Unknown", "works at", "Beta Lab", EP_B, TS_B, text_b,
                                                      "Zed Unknown works at Beta Lab")),
                  now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    by_object = {c.object: c for c in _claims(memory, "zed-unknown")}
    old, new = by_object["alpha-lab"], by_object["beta-lab"]
    assert (old.valid_to, old.superseded_by, new.valid_to) == ("2026-09-22", new.id, None)
    assert not [n for n in result["nudges"] if n.get("action") == "conflict_nudge"]


def test_a_held_name_stage2_matched_to_an_existing_page_is_released_there(tmp_path):
    memory = _bank(tmp_path)
    _hear_recommendation(memory)
    _page(memory, "zed-example", "Zed Example")
    result = _run(memory, [], now="2026-09-22",
                  name_to_id={"zed example": "zed-example", "zed unknown": "zed-example"})
    (claim,) = _claims(memory, "zed-example")
    assert (claim.subject, claim.object) == ("zed-example", "gamma-board")
    assert not (memory / "entities" / "zed-unknown.md").exists()
    assert result["claims_released"] == 1 and pending_store.load(memory) == []


def test_release_waits_while_the_page_cannot_be_written(tmp_path):
    memory = _bank(tmp_path)
    _hear_recommendation(memory)
    page = _page(memory, "zed-unknown", "Zed Unknown", body=BROKEN)
    before = page.read_text(encoding="utf-8")
    result = _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    assert (result["claims_released"], result["claims_waiting"]) == (0, 1)
    assert page.read_text(encoding="utf-8") == before
    _page(memory, "zed-unknown", "Zed Unknown")  # the page is fixed; no mention needed to release
    result = _run(memory, [], now="2026-09-23")
    assert (result["claims_released"], result["claims_waiting"]) == (1, 0)
    assert len(_claims(memory, "zed-unknown")) == 1


def test_a_held_claim_already_on_its_page_is_not_offered_to_stage3_again(tmp_path):
    """R-HP6's idempotency guard. A release whose page write landed but whose
    store removal did not; since then a newer claim closed the released one on
    the page. Offered to Stage 3 again, the open held copy would meet its own
    successor and ask the person about a value recency already settled."""
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    _run(memory, _extracted(EP_A, TS_A, _rel("Zed Unknown", "works at", "Alpha Lab", EP_A, TS_A, text_a,
                                             "Zed Unknown works at Alpha Lab")), now="2026-09-20")
    held = Claim.from_dict(pending_store.load(memory)[0].held_claims[0])
    newer = Claim(id="clm_2026-09-21_beta0001", text="Zed Unknown works at Beta Lab", subject="zed-unknown",
                  predicate=held.predicate, object="beta-lab", valid_from="2026-09-21", supersedes=held.id)
    closed = Claim.from_dict({**held.to_dict(), "valid_to": "2026-09-21", "superseded_by": newer.id})
    page = _page(memory, "zed-unknown", "Zed Unknown")
    parsed = markdown_parser.parse(page)
    markdown_parser.write(page, parsed.frontmatter, write_claims(parsed.body, [closed, newer]))
    result = _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    assert [(c.id, c.valid_to) for c in _claims(memory, "zed-unknown")] == [
        (held.id, "2026-09-21"), (newer.id, None)]
    assert not [n for n in result["nudges"] if n.get("action") == "conflict_nudge"]
    assert pending_store.load(memory) == []


def test_owner_surfaces_events_and_claims_closed_in_their_batch_are_never_held(tmp_path):
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    text_b = _episode(memory, EP_B, TS_B, BODY_B)
    _park(memory, "Zed Unknown")
    _park(memory, "The User")  # Stage 1 listed the person as an entity; no owner page exists
    extracted = _extracted(
        EP_A, TS_A,
        _rel("the user", "connects to", "Lab Cluster Example", EP_A, TS_A, text_a, "Zed Unknown"),
        _rel("Zed Unknown", "works at", "Alpha Lab", EP_A, TS_A, text_a, "Zed Unknown works at Alpha Lab"),
    ) + _extracted(
        EP_B, TS_B,
        _rel("Zed Unknown", "works at", "Beta Lab", EP_B, TS_B, text_b, "Zed Unknown works at Beta Lab"),
    )
    result = _run(memory, extracted, now="2026-09-22")
    held = {e.name: [d["object"] for d in e.held_claims] for e in pending_store.load(memory)}
    assert held == {"Zed Unknown": ["beta-lab"], "The User": []}  # Alpha was closed by Beta in its own batch
    assert (result["claims_held"], result["claims_page_less"]) == (1, 2)
    event = Claim(id="clm_evt", text="t", subject="zed-unknown", predicate="happened", object="x", status="done")
    assert claim_pipeline.hold_page_less({"zed-unknown": [event]}, memory) == {"zed-unknown": HoldOutcome(0, 0)}


def test_the_cap_holds_fifty_per_name_and_counts_the_rest(tmp_path):
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    rels = [_rel("Zed Unknown", "uses", f"Tool Example {n:02d}", EP_A, TS_A, text_a, "Zed Unknown")
            for n in range(1, pending_store.MAX_HELD_CLAIMS + 3)]
    first = _run(memory, _extracted(EP_A, TS_A, *rels), now="2026-09-20")
    assert (first["claims_held"], first["claims_hold_capped"], first["claims_page_less"]) == (50, 2, 2)
    kept = [d["id"] for d in pending_store.load(memory)[0].held_claims]
    again = _run(memory, _extracted(EP_A, TS_A, *rels), now="2026-09-21")
    assert (again["claims_held"], again["claims_hold_capped"]) == (50, 2)
    assert [d["id"] for d in pending_store.load(memory)[0].held_claims] == kept


def test_the_hold_and_the_release_are_logged_as_counts_never_as_a_name(tmp_path):
    memory = _bank(tmp_path)
    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(str(m)), level="DEBUG",
                      filter=lambda r: r["name"] in ("api.services.claim_pipeline", "api.services.pending_store"))
    try:
        _hear_recommendation(memory)
        _page(memory, "zed-unknown", "Zed Unknown")
        _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    finally:
        logger.remove(sink)
    joined = "\n".join(lines)
    assert "1 held for a pending name" in joined and "1 released onto their page" in joined
    for needle in ("Zed Unknown", "zed-unknown", "Gamma Board", "gamma-board"):
        assert needle not in joined


def test_a_pending_store_failure_costs_the_hold_never_the_cycle_claims(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    text_a = _episode(memory, EP_A, TS_A, BODY_A)
    _park(memory, "Zed Unknown")
    _page(memory, "alpha-lab", "Alpha Lab")

    def boom(*_a, **_k):
        raise OSError("store unavailable")

    monkeypatch.setattr(pending_store, "ready", boom)
    monkeypatch.setattr(pending_store, "hold", boom)
    result = _run(memory, _extracted(
        EP_A, TS_A,
        _rel("Alpha Lab", "supports", "Gamma Board", EP_A, TS_A, text_a, "Alpha Lab"),
        _rel("Zed Unknown", "recommends", "Gamma Board", EP_A, TS_A, text_a, "recommends Gamma Board"),
    ), now="2026-09-20")
    assert [c.object for c in _claims(memory, "alpha-lab")] == ["gamma-board"]
    assert (result["claims_held"], result["claims_page_less"]) == (0, 1)


def test_a_released_claim_counts_as_newly_written_for_the_cited_link_attach(tmp_path):
    """R-HP8: G61 phase 2 S1 attaches a link found verbatim in a newly written
    claim's cited span. A released claim is written for the first time too."""
    memory = _bank(tmp_path)
    link = "https://example.com/alpha-lab/team"
    line = f"Zed Unknown works at Alpha Lab; the team page {link} lists them."
    text = _episode(memory, EP_A, TS_A, f"user: {line}\nassistant: Noted.")
    _park(memory, "Zed Unknown")
    _run(memory, _extracted(EP_A, TS_A, _rel("Zed Unknown", "works at", "Alpha Lab", EP_A, TS_A, text, line)),
         now="2026-09-20")
    _page(memory, "zed-unknown", "Zed Unknown")
    _run(memory, [], now="2026-09-22", name_to_id={"zed unknown": "zed-unknown"})
    assert [(s["ref"], s["predicate"]) for s in fact_sources.list_sources(memory, "zed-unknown")] == [
        (link, "works-at")]
```

Also rewrite the PJ-0 seam test in `api/tests/test_claim_pipeline_subjects.py`:
- add `from api.services.pending_store import HoldOutcome` to the imports (`:13-16`);
- replace `test_the_r_pj17_seam_is_asked_holds_nothing_and_writes_nothing` (`:182-196`) with:

```python
def test_a_subject_with_no_pending_line_is_offered_to_the_hold_and_nothing_is_written(tmp_path, monkeypatch):
    """R-PJ17's seam, filled by PJ-0b (R-HP10): every page-less subject is offered
    in one call; with no pending line for it nothing is held, no store is
    invented, and the claim is counted exactly as PJ-0 counted it."""
    memory = _bank(tmp_path)
    assert claim_pipeline.hold_page_less({"zed-unknown": []}, memory) == {"zed-unknown": HoldOutcome(0, 0)}
    asked: list[dict[str, int]] = []
    real = claim_pipeline.hold_page_less
    monkeypatch.setattr(claim_pipeline, "hold_page_less",
                        lambda offers, m: asked.append({s: len(c) for s, c in offers.items()}) or real(offers, m))
    before = sorted(p.relative_to(memory).as_posix() for p in memory.rglob("*") if p.is_file())
    result = claim_pipeline.run_claim_pipeline(
        _extracted(("Zed Unknown", "uses", "Alpha Project")), [], memory, _settings(memory),
        now_date="2026-09-22", name_to_id={})
    assert asked == [{"zed-unknown": 1}]
    assert (result["claims_page_less"], result["claims_held"]) == (1, 0)
    after = sorted(p.relative_to(memory).as_posix() for p in memory.rglob("*") if p.is_file())
    assert after == before
```

- [ ] **Step 2: Run them. They fail.** All 12 tests in the new file fail: a `KeyError` on a new result key
  (`claims_held`, `claims_released`), or an `IndexError` / `ValueError` / `KeyError` where no claim was released
  onto the page, or a missing log phrase or source. The rewritten seam test fails with a `TypeError` from the old
  three-argument signature. Every other test in `test_claim_pipeline_subjects.py` still passes.

`cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests/test_claim_pipeline_hold.py api/tests/test_claim_pipeline_subjects.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement in `api/services/claim_pipeline.py`.**

The module docstring's item 3 (`:26-35`) becomes:

```text
3. **Stage 5 (write).** Write the reconciled claims back INTO each entity page via
   :func:`claims.write_claims`, which preserves all surrounding human prose
   verbatim (round-trip invariant). Each endpoint is keyed through Stage 2's
   ``name_to_id`` (G141 PJ-0), so a claim lands on the page its edge does, and
   "the user" lands on the ``owner: true`` page. A subject that still has no
   page is NOT written — the promotion model owns page creation — and this
   cycle marks its episode processed, so nothing extracts those claims again.
   So they are HELD with the subject's pending entity (G141 PJ-0b, ruled
   2026-09-23 as DECIDE (c); :func:`hold_page_less`), and released — first,
   through Stage 3 like any claim — in the cycle whose Stage 5 gave the name a
   page. What cannot be held is counted (``claims_page_less``).
```

Imports (`:53-58`): change `from api.services import markdown_parser, owner_identity, telemetry` to
`from api.services import markdown_parser, owner_identity, pending_store, telemetry`, and add
`from api.services.pending_store import HoldOutcome, Release` after the `id_utils` import.

After `OWNER_SURFACES` (`:64`), add:

```python
#: G141 PJ-0b (R-HP2): the ids the owner surfaces key to when no owner page
#: exists. Never held — R-CS2 never invents a `user` page, and a pending
#: "User" line (Stage 1 listing the person as an entity) must not collect the
#: person's claims and hand them to a page named after a pronoun.
_OWNER_SLUGS = frozenset(sanitize_id(s) for s in OWNER_SURFACES)
```

Replace `hold_page_less` (`:104-112`) with the function and four helpers below:

```python
def hold_page_less(offers: dict[str, list[Claim]], memory_path: Path) -> dict[str, HoldOutcome]:
    """G141 PJ-0b — hold what Sleep heard about a name that has no page yet.

    The owner ruled (G141 DECIDE (c), 2026-09-23; R-PJ17) that an unpromoted
    subject's claims wait WITH its pending entity and are written when it is
    promoted. ``offers`` maps each page-less subject id to this cycle's Stage-1
    claims on it; each goes to the pending line whose slug is that id
    (``pending_store.hold``, R-HP2) — the id Stage 2's promotion writes, so a
    held claim lands where the page will be.

    Never held, and so counted as ``claims_page_less`` exactly as PJ-0 did:
    - a subject with no pending line (Stage 1 named the endpoint differently
      from the entity, or never listed it) — no fuzzy match over pending names;
    - the owner surfaces (``_OWNER_SLUGS``, R-CS2);
    - a claim already closed in its own batch — Stage 3 never tests an incoming
      claim's own validity (``reconcile_stage3``'s ``same_key_open``), so a
      closed claim released later could close an open one;
    - an event (``is_event``) — only ``progress.py`` writes those (G141 §5.1).

    One read and at most one write of the store per cycle (R-HP10). Returns
    ``{subject: HoldOutcome(held, capped)}`` for every subject offered."""
    eligible = {
        subject: [c for c in claims if c.valid_to is None and not is_event(c)]
        for subject, claims in offers.items()
        if subject not in _OWNER_SLUGS
    }
    outcomes = pending_store.hold(memory_path, eligible)
    return {subject: outcomes.get(subject, HoldOutcome(0, 0)) for subject in offers}


def _release_target(name_to_id: dict[str, str] | None) -> Callable[[str, str], str]:
    """G141 PJ-0b (R-HP5): where a pending line's held claims go — Stage 2's own
    EXACT verdict on that name this cycle (a promotion keys it to its slug, a
    ``same`` match to the page it matched, a page named the same to that page),
    else the claims' own subject. Never fuzzy: a verdict Stage 2 did not reach
    is not invented here."""
    table = {str(k): str(v) for k, v in (name_to_id or {}).items()}

    def target(name: str, subject: str) -> str:
        return table.get((name or "").strip().lower()) or subject

    return target


def _releases(
    memory_path: Path, name_to_id: dict[str, str] | None, existing_by_subject: dict[str, list[Claim]],
) -> tuple[list[Release], list[Claim], dict[str, list[str]]]:
    """G141 PJ-0b (R-HP5, R-HP6, R-HP8): the held claims whose name has a page now,
    read WITHOUT touching the store — the lines leave only after the write
    succeeded (R-HP4). Returns ``(releases, claims for Stage 3, credit)``. A
    claim already on its target page is not offered again: a store removal
    that failed after a good write must not have the person asked about their
    own claim. ``credit`` maps each target page to the episodes its claims
    were heard in. A store that cannot be read releases nothing this cycle."""
    try:
        releases = pending_store.ready(memory_path, _release_target(name_to_id))
    except Exception as e:  # noqa: BLE001 - a hold is never worth the cycle's claims
        logger.warning(f"pending-store release skipped: {type(e).__name__}: {e}")
        return [], [], {}
    offered: list[Claim] = []
    credit: dict[str, list[str]] = {}
    for rel in releases:
        on_page = {c.id for c in existing_by_subject.get(rel.target, [])}
        episodes = credit.setdefault(rel.target, [])
        for claim in rel.claims:
            for ep in claim.source_episodes:
                if ep and ep not in episodes:
                    episodes.append(ep)
            if claim.id not in on_page:
                offered.append(claim)
    return releases, offered, credit


def _credit_episodes(frontmatter: dict, episodes: list[str] | None) -> bool:
    """R-HP8: the conversation a released claim was heard in credits the page —
    G48's transitive credit through ``source_episodes`` — in the same write.
    True when the frontmatter changed."""
    if not episodes:
        return False
    raw = frontmatter.get("source_episodes")
    have = [str(e) for e in raw] if isinstance(raw, list) else ([str(raw)] if raw else [])
    missing = [e for e in episodes if e and e not in have]
    if not missing:
        return False
    frontmatter["source_episodes"] = have + missing
    return True


def _settle_store(
    memory_path: Path, releases: list[Release], written: set[str],
    offers: dict[str, list[Claim]], stage1_ids: set[str],
) -> dict[str, int]:
    """G141 PJ-0b, after the write: release the lines whose page took their claims
    (R-HP4), then hold what is still page-less (R-HP2) — release first, so no
    line is handed new claims in the pass that retires it. Each store call is
    guarded (R-HP10): a failure is logged and costs only the hold — what could
    not be held is counted page-less by the caller. Returns R-HP12's counts."""
    counts = {"claims_held": 0, "claims_hold_capped": 0, "claims_released": 0, "claims_waiting": 0}
    done = [rel for rel in releases if rel.target in written]
    try:
        pending_store.release(memory_path, [rel.name for rel in done])
        counts["claims_released"] = sum(len(rel.claims) for rel in done)
    except Exception as e:  # noqa: BLE001 - the lines stay and release next cycle
        logger.warning(f"pending-store release not recorded: {type(e).__name__}: {e}")
    if len(done) < len(releases):
        logger.info(
            f"Claim pipeline: {len(releases) - len(done)} pending name(s) keep their held claims "
            f"until their page can be written"
        )
    try:
        outcomes = hold_page_less(
            {s: [c for c in claims if c.id in stage1_ids] for s, claims in offers.items()}, memory_path)
        counts["claims_held"] = sum(o.held for o in outcomes.values())
        counts["claims_hold_capped"] = sum(o.capped for o in outcomes.values())
    except Exception as e:  # noqa: BLE001 - unheld claims are counted page-less, never lost silently
        logger.warning(f"page-less claims not held: {type(e).__name__}: {e}")
    try:
        counts["claims_waiting"] = pending_store.waiting(memory_path)[0]
    except Exception:  # noqa: BLE001 - a count is never worth a failure
        pass
    return counts
```

Then replace `run_claim_pipeline` (`:156-300`) with the version below. Relative to today it:
- reads the releases before Stage 3 and puts them first;
- credits the page in the write loop;
- collects page-less offers instead of calling the seam inline;
- settles the store after the loop;
- updates the log line and the return dict.

The G61 block and the audit telemetry are unchanged:

```python
def run_claim_pipeline(
    extracted: list[dict],
    existing_entities: list[dict],
    memory_path: Path,
    settings,
    *,
    now_date: str | None = None,
    extra_claims: list[Claim] | None = None,
    name_to_id: dict[str, str] | None = None,
) -> dict:
    """Emit → release → reconcile → write → hold claims over the live entity pages (additive).

    Args:
        extracted: Stage-1 extraction output (per-episode entities/relationships,
            origin-stamped). Projected into agent-extracted claims.
        existing_entities: Stage 2's ``existing`` list — read for the
            ``owner: true`` page "the user" maps onto (G141 PJ-0). Write-back
            still re-reads pages from disk, to see the entity path's fresh writes.
        memory_path: active memory bank dir.
        settings: carries ``litellm_model`` / thresholds / ``memory_path``.
        now_date: reconciliation/decay reference date (ISO); defaults to today.
        extra_claims: pre-built claims to inject alongside the projected ones —
            the manual-edit / clarification (``user_stated`` + human-origin) path.
            Never held (R-HP2).
        name_to_id: Stage 2's ``resolve(...)["name_to_id"]`` — every endpoint is
            keyed through it (R-CS1), and a held name is released onto Stage 2's
            exact verdict for it (R-HP5). ``None`` keeps ``sanitize_id``.

    Returns a dict: ``{"nudges": [...], "audit": [...], "claims_written": int,
    "subjects_written": int, "subjects_skipped": int, "claims_page_less": int,
    "page_less_subjects": [ids], "relabelled_events": int, "claims_held": int,
    "claims_hold_capped": int, "claims_released": int, "claims_waiting": int}``.
    ``claims_page_less`` counts claims neither written nor held (G141 PJ-0b);
    ``page_less_subjects`` stays in memory only (R-CS3: a subject id is a slug
    of a name, so it is never logged); the four hold counts are R-HP12's;
    ``relabelled_events`` is R-PJB12's. Never raises on a missing subject page
    or a pending-store failure — the promotion model owns page creation, and a
    store failure costs the hold, never the cycle's claims (R-HP10).
    """
    today = now_date or str(date.today())
    memory_path = Path(memory_path)

    # ---- Stage 1: emit claims from extraction ----
    owner_id = _owner_page_id(existing_entities, memory_path, settings)
    incoming: list[Claim] = entities_to_claims(
        extracted, memory_path, resolve_id=subject_resolver(name_to_id, owner_id))
    incoming, relabelled = _relabel_event_labels(incoming)
    # Stage-1 only — never the person's extra_claims, never a released claim:
    # the only claims a hold ever takes (R-HP2).
    stage1_ids = {c.id for c in incoming}

    # ---- G141 PJ-0b: release what was held for a name that has a page now ----
    # Released claims go FIRST, so they meet Stage 3 as the page's own claims
    # would have had it existed when they were heard (R-HP6): a newer
    # single-valued claim supersedes them, where the other order would ask.
    existing_by_subject = _load_existing_claims_by_subject(memory_path)
    releases, released, credit = _releases(memory_path, name_to_id, existing_by_subject)
    incoming = released + incoming
    # G61 S1 reads this as "newly written by this pass" — true of a released claim too (R-HP8).
    emitted_ids = stage1_ids | {c.id for c in released}
    if extra_claims:
        incoming = incoming + list(extra_claims)

    # ---- Stage 3: reconcile against existing in-page claims (trust-gated) ----
    reconciled, nudges, audit = reconcile_stage3(
        incoming,
        existing_by_subject,
        settings,
        now_date=today,
    )
    # G113 — every supersede/reject the reconciler decided lands in the ledger.
    # One pass covers every subject, so the subject is recovered per entry from
    # the claim ids involved rather than passed once for the whole batch.
    subject_by_id = {c.id: c.subject for claims in existing_by_subject.values() for c in claims}
    subject_by_id.update({c.id: c.subject for c in incoming})
    for entry in audit:
        subject = subject_by_id.get(entry.get("by") or entry.get("dropped")) or subject_by_id.get(
            entry.get("closed") or entry.get("kept")
        )
        telemetry.record_audit([entry], subject_hint=subject, bank=memory_path.name, stage="reconcile")

    # ---- Stage 5: write reconciled claims back INTO each entity page ----
    entities_dir = memory_path / "entities"
    claims_written = 0
    subjects_written = 0
    subjects_skipped = 0
    written_subjects: list[str] = []
    page_less_subjects: list[str] = []
    page_less_claim_ids: list[str] = []
    page_less_offers: dict[str, list[Claim]] = {}
    for subject, claims in reconciled.items():
        if not claims:
            continue
        filepath = entities_dir / f"{subject}.md"
        if not filepath.exists():
            # G141 PJ-0: not written — the promotion model owns page creation —
            # and never extracted again: this cycle marks the episode processed
            # (`sleep_cycle._mark_episodes_processed`). PJ-0b holds them with the
            # subject's pending entity after this loop; what it cannot hold is counted.
            subjects_skipped += 1
            page_less_subjects.append(subject)
            page_less_claim_ids.extend(c.id for c in claims)
            page_less_offers[subject] = claims
            continue
        try:
            parsed = markdown_parser.parse(filepath)
            # strict guard: if the existing block is unparseable, raise (caught
            # below) instead of overwriting claims we could not read.
            parse_claims(parsed.body, strict=True)
            new_body = write_claims(parsed.body, claims)
            # R-HP8: the conversation a released claim was heard in credits the page.
            credited = _credit_episodes(parsed.frontmatter, credit.get(subject))
            if new_body != parsed.body or credited:
                markdown_parser.write(filepath, parsed.frontmatter, new_body)
            subjects_written += 1
            written_subjects.append(subject)
            claims_written += len(claims)
        except Exception as e:  # never let a single bad page abort the cycle
            logger.warning(
                f"claim write-back skipped for {subject}: {type(e).__name__}: {e}"
            )

    # ---- G141 PJ-0b: settle the pending store — release, then hold (R-HP4, R-HP10) ----
    hold = _settle_store(memory_path, releases, set(written_subjects), page_less_offers, stage1_ids)
    claims_page_less = sum(len(claims) for claims in page_less_offers.values()) - hold["claims_held"]

    # ---- G61 phase 2 S1 (spec §5.2, plan R-AC33): a link the cited words contain ----
    # A URL sitting verbatim inside a newly written Stage-1 claim's evidence span
    # is where that fact can be checked. Zero LLM, never a URL Stage 1 made up;
    # only on a page this pass wrote, only for a world/artifact predicate. Its
    # frontmatter write rides this stage's pages into `_finalize`'s commit, under
    # the model that extracted it — the right author for it.
    sources_attached = 0
    if written_subjects:
        try:
            from api.services import fact_sources, predicates

            locus_of = predicates.build_locus_fn(memory_path)
            for subject in written_subjects:
                for claim in reconciled.get(subject, []):
                    if claim.id in emitted_ids and claim.valid_to is None:
                        sources_attached += len(fact_sources.attach_cited_urls(memory_path, subject, claim, locus_of))
        except Exception as e:  # a source is a convenience; it never costs the cycle
            logger.warning(f"cited-link source attach skipped: {type(e).__name__}: {e}")

    logger.info(
        f"Claim pipeline: {len(incoming)} emitted, "
        f"{subjects_written} pages written ({claims_written} claims), "
        f"{claims_page_less} claim(s) on {subjects_skipped} subject(s) without a page not written, "
        f"{hold['claims_held']} held for a pending name ({hold['claims_hold_capped']} over the cap), "
        f"{hold['claims_released']} released onto their page, {hold['claims_waiting']} waiting, "
        f"{sources_attached} cited links attached as sources, "
        f"{len(nudges)} claim nudges"
    )
    if page_less_claim_ids:
        # R-CS3: opaque claim ids only — never the subject, a slug of a name.
        logger.debug(f"Claim pipeline: page-less claim ids {sorted(page_less_claim_ids)}")

    return {
        "nudges": nudges,
        "audit": audit,
        "claims_written": claims_written,
        "subjects_written": subjects_written,
        "subjects_skipped": subjects_skipped,
        "claims_page_less": claims_page_less,
        "page_less_subjects": sorted(page_less_subjects),
        "relabelled_events": relabelled,
        **hold,
    }
```

Check before moving on:
- `grep -n "re-emitted next cycle\|waits for its subject to be promoted\|always 0 until PJ-0b" api/services/claim_pipeline.py`
  prints nothing. The first two phrases are pinned by `test_the_false_re_emitted_comment_is_gone`.
- `Callable` and `sanitize_id` are already imported in this module.

- [ ] **Step 4: Run the new tests, the rewritten seam test and every other `run_claim_pipeline` caller. All
  pass.**

`cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests/test_claim_pipeline_hold.py api/tests/test_claim_pipeline_subjects.py api/tests/test_claim_pipeline.py api/tests/test_claims_corruption_guard.py api/tests/test_progress_writes.py api/tests/test_extraction_source_attach.py api/tests/test_sleep_cycle_claims_wired.py api/tests/test_pending_store.py -q -p no:cacheprovider`

- [ ] **Step 5: Full suite.** `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` must report 0 failures.

- [ ] **Step 6: Commit.**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && git add api/services/claim_pipeline.py api/tests/test_claim_pipeline_hold.py api/tests/test_claim_pipeline_subjects.py && git commit -F - <<'EOF'
feat(g141): PJ-0b — Sleep holds a page-less subject's claims with its pending entity and writes them on promotion

Stage 5.56 holds this cycle's page-less Stage-1 claims on the pending line
whose slug is their subject (never the owner surfaces, a claim closed in its
own batch, or an event — R-HP2), and releases a line's claims first, through
Stage 3, in the cycle whose Stage 5 gave its name a page — onto Stage 2's own
exact verdict for the name (R-HP5, R-HP6). Spans are released verbatim, never
re-located (R-HP7); the first conversation credits the page, and G61 S1 treats
a released claim as newly written (R-HP8). The store is read before Stage 3 and
settled after the write, release-first; a store failure costs only the hold
(R-HP10). Four counts join the result; claims_page_less now means neither
written nor held (R-HP12). Nothing becomes visible until released (R-HP13).

<attribution lines from the session's system reminder>
EOF
```

---

### Task 3: The hold's counts on the Sleep state and the `sleep_run` row, and the two-conversation acceptance test (R-HP12)

**Files:**
- Modify: `api/services/sleep_cycle.py`:
  - `SleepState` `:57-62`;
  - the reset `:1050-1051`;
  - the assignment `:1404-1405`;
  - the 5.56 INFO line `:1430-1437`;
  - the `sleep_run` refs `:2128-2130`.
- Test: `api/tests/test_sleep_cycle_hold.py` (new). Must stay green: `api/tests/test_claim_pipeline_subjects.py`
  (its two Sleep tests).

**Interfaces:**
- Produces:
  - `SleepState.claims_held`, `claims_released`, `claims_hold_capped` and `claims_waiting` (ints, internal);
  - the same four keys in the `sleep_run` ledger refs.
- Consumes: Task 2's result keys.

- [ ] **Step 1: Write the failing tests.**

```python
# api/tests/test_sleep_cycle_hold.py
"""G141 PJ-0b acceptance (R-HP12): across two real Sleep cycles, what Stage 1
heard about a name with no page is held with its pending entity, and lands on
the page the second conversation's promotion creates — span current, the
first conversation credited, the pending line gone — and every step is a
count on the Sleep state and the `sleep_run` row.

Real: Stage 2 (`entity_resolver.resolve` — no LLM call, since nothing shares a
token), Stage 5's page write, Stage 5.56 and the pending store. Fakes:
extraction, Stage 3's legacy entity pass, Stage 4, git, and the vector index
(the pending-vector rebuild needs an embedder). Synthetic names only."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from api.config import Settings
from api.services import (entity_resolver, evidence, git_service, markdown_parser, pending_store, predicates,
                          sleep_cycle, telemetry)
from api.services.claims import parse_claims

EP_A, TS_A = "ep_2026-09-20_001", "2026-09-20T10:00:00+00:00"
EP_B, TS_B = "ep_2026-09-22_001", "2026-09-22T10:00:00+00:00"
QUOTE = "Zed Unknown recommends Gamma Board"


def _settings(memory: Path) -> SimpleNamespace:
    # `inbox_stale_after_days`: without it 5.56's question refresh raises after
    # the claim write (harmless, but the stage would end in a warning).
    return SimpleNamespace(memory_path=memory, litellm_model="gpt-5.4-mini",
                           litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
                           decay_nudge_threshold=0.4, sleep_promotion_threshold=2,
                           link_enrich_enabled=False, inbox_stale_after_days=90)


def _bank(tmp_path: Path) -> Path:
    memory = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (memory / sub).mkdir(parents=True)
    predicates.install_predicate_map(memory)
    return memory


def _episode(memory: Path, ep: str, ts: str, body: str) -> None:
    markdown_parser.write(memory / "episodes" / f"{ep}.md",
                          {"id": ep, "processed": False, "source": "mcp", "timestamp": ts}, body)


def _entity(name: str, kind: str, ep: str, ts: str) -> dict:
    # confidence 0.6: under Stage 2's substantive bar (0.75) and over the
    # clarification threshold (0.5) — the name is parked, not promoted or asked about.
    return {"name": name, "type": kind, "confidence": 0.6, "description": "Mentioned once.",
            "source_episode": ep, "source_episode_timestamp": ts, "tags": [], "history_entries": []}


def _patch(monkeypatch, queue: list[list[dict]]) -> None:
    async def fake_extract(episodes, settings, **_kw):
        return queue.pop(0)

    async def fake_detect(changes, existing, settings, **_kw):
        return []

    async def fake_resolve_and_prune(resolved, existing, settings):
        return list(resolved)

    async def fake_commit(_path, _message):
        return None

    async def fake_porcelain(_path):
        return ""

    class _FakeIndexer:
        def __init__(self, *_a, **_k):
            pass

        def index_entities(self):
            return 0

        def index_episodes(self):
            return 0

        def index_claims(self):
            return 0

    # Stage 2 keeps the REAL indexer class (bound at its import) and so the real
    # pending store; only the pending-vector rebuild, which embeds, is stubbed.
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
    monkeypatch.setattr("api.services.conflict_resolver.resolve_and_prune", fake_resolve_and_prune)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(git_service, "porcelain_status", fake_porcelain)
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)


def test_two_conversations_hold_then_write_a_claim_about_a_name_that_had_no_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _episode(memory, EP_A, TS_A, "user: Zed Unknown recommends Gamma Board for the lab.\nassistant: Noted.")
    span = evidence.verify(None, EP_A, QUOTE, text=evidence.source_text(memory, EP_A))
    assert span.is_span()
    first = [{"episode_id": EP_A, "episode_timestamp": TS_A, "origin": "claude-code",
              "entities": [_entity("Zed Unknown", "person", EP_A, TS_A), _entity("Gamma Board", "tool", EP_A, TS_A)],
              "relationships": [{"source": "Zed Unknown", "target": "Gamma Board", "label": "recommends",
                                 "source_episode": EP_A, "source_episode_timestamp": TS_A,
                                 "evidence": [span.to_dict()]}]}]
    second = [{"episode_id": EP_B, "episode_timestamp": TS_B, "origin": "claude-code",
               "entities": [_entity("Zed Unknown", "person", EP_B, TS_B)], "relationships": []}]
    _patch(monkeypatch, [first, second])

    # Conversation 1: both names are parked; the claim waits with "Zed Unknown".
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="pj0b_1"))
    state = sleep_cycle.get_sleep_state()
    assert (state.claims_held, state.claims_page_less, state.claims_released, state.claims_waiting) == (1, 0, 0, 1)
    assert list((memory / "entities").glob("*.md")) == []
    (line,) = [e for e in pending_store.load(memory) if e.held_claims]
    assert line.name == "Zed Unknown" and line.held_claims[0]["evidence"] == [span.to_dict()]

    # Conversation 2 names it again: Stage 2 promotes it, Stage 5 writes the
    # page, Stage 5.56 releases the held claim onto it.
    _episode(memory, EP_B, TS_B, "user: I met Zed Unknown again today.\nassistant: Good.")
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="pj0b_2"))
    state = sleep_cycle.get_sleep_state()
    assert (state.claims_held, state.claims_released, state.claims_waiting) == (0, 1, 0)

    page = markdown_parser.parse(memory / "entities" / "zed-unknown.md")
    (claim,) = parse_claims(page.body)
    assert (claim.subject, claim.predicate, claim.object) == ("zed-unknown", "recommends", "gamma-board")
    assert (claim.observer, claim.source_trust, claim.valid_from, claim.valid_to) == (
        "agent", "agent_extracted", "2026-09-20", None)
    (ev,) = claim.evidence
    assert ev == span
    text = evidence.source_text(memory, EP_A)
    assert text[ev.start:ev.end] == QUOTE
    assert evidence.span_status(text, end=ev.end, hash=ev.hash) == evidence.SPAN_CURRENT
    assert page.frontmatter["source_episodes"] == [EP_B, EP_A]
    assert [e.name for e in pending_store.load(memory)] == ["Gamma Board"]


def test_the_sleep_run_row_carries_the_hold_counts(tmp_path, monkeypatch):
    events: list = []

    async def fake_status(_path):
        return ""

    async def fake_commit(_path, _message):
        return "abc1234"

    monkeypatch.setattr(git_service, "porcelain_status", fake_status)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(telemetry, "record", events.append)
    for key, value in (("claims_held", 4), ("claims_released", 3), ("claims_hold_capped", 2),
                       ("claims_waiting", 7)):
        monkeypatch.setattr(sleep_cycle._state, key, value)
    asyncio.run(sleep_cycle._finalize(
        tmp_path, "sleep_1", [], Settings(llm_mode="agent"),
        engine="claude-cli", connection="claude-plan", billing="subscription", authors=["claude-sonnet-5"],
    ))
    (row,) = [e for e in events if e.kind == "sleep_run"]
    assert {k: row.refs[k] for k in ("claims_held", "claims_released", "claims_hold_capped", "claims_waiting")} == {
        "claims_held": 4, "claims_released": 3, "claims_hold_capped": 2, "claims_waiting": 7}
```

- [ ] **Step 2: Run them. They fail.** The acceptance test fails with `AttributeError: 'SleepState' object has no
  attribute 'claims_held'`. The ledger test fails at `monkeypatch.setattr` (the attribute does not exist).

`cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests/test_sleep_cycle_hold.py -q -p no:cacheprovider`

- [ ] **Step 3: Implement in `api/services/sleep_cycle.py`.**

`SleepState` (`:57-62`) becomes:

```python
    # G141 PJ-0 (R-CS3): claims Stage 5.56 could neither write nor hold (PJ-0b)
    # because their subject has no page, and how many page-less subjects there
    # were. Counts only — G141's M3 measure, carried into the `sleep_run`
    # ledger row; never on `/sleep/status`.
    claims_page_less: int = 0
    subjects_page_less: int = 0
    # G141 PJ-0b (R-HP12): the hold, per cycle — claims newly held for a
    # pending name, held claims released onto their page, claims the per-name
    # cap refused, and what still waits in the store after the cycle. Counts
    # only, internal, never on `/sleep/status`.
    claims_held: int = 0
    claims_released: int = 0
    claims_hold_capped: int = 0
    claims_waiting: int = 0
```

Reset (`:1050-1051`), after `_state.subjects_page_less = 0`:

```python
    _state.claims_held = 0
    _state.claims_released = 0
    _state.claims_hold_capped = 0
    _state.claims_waiting = 0
```

Assignment (`:1404-1405`), after `_state.subjects_page_less = …`:

```python
        _state.claims_held = int(claim_result.get("claims_held", 0) or 0)
        _state.claims_released = int(claim_result.get("claims_released", 0) or 0)
        _state.claims_hold_capped = int(claim_result.get("claims_hold_capped", 0) or 0)
        _state.claims_waiting = int(claim_result.get("claims_waiting", 0) or 0)
```

The 5.56 INFO line (`:1430-1437`) becomes:

```python
        logger.info(
            f"Stage 5.56: claim layer wrote {claim_result.get('claims_written', 0)} "
            f"claims across {claim_result.get('subjects_written', 0)} pages "
            f"({claim_result.get('claims_page_less', 0)} claim(s) on "
            f"{claim_result.get('subjects_skipped', 0)} page-less subject(s) neither written nor held; "
            f"{claim_result.get('claims_held', 0)} held for a pending name, "
            f"{claim_result.get('claims_released', 0)} released onto their page), "
            f"{nudge_result.get('written', 0)} claim nudges written, "
            f"{nudge_result.get('merged', 0)} merged into open items"
        )
```

The `sleep_run` refs (`:2128-2130`) become:

```python
            # G141 PJ-0 (R-CS3): M3's per-cycle page-less count — integers only.
            "claims_page_less": _state.claims_page_less,
            "subjects_page_less": _state.subjects_page_less,
            # G141 PJ-0b (R-HP12): the hold — integers only, never a name.
            "claims_held": _state.claims_held,
            "claims_released": _state.claims_released,
            "claims_hold_capped": _state.claims_hold_capped,
            "claims_waiting": _state.claims_waiting,
```

- [ ] **Step 4: Run the new tests and PJ-0's Sleep tests. All pass.**

`cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests/test_sleep_cycle_hold.py api/tests/test_claim_pipeline_subjects.py api/tests/test_sleep_cycle_claims_wired.py -q -p no:cacheprovider`

- [ ] **Step 5: Full suite.** `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider` must report 0 failures.

- [ ] **Step 6: Commit.**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && git add api/services/sleep_cycle.py api/tests/test_sleep_cycle_hold.py && git commit -F - <<'EOF'
feat(g141): PJ-0b — the hold's counts on the Sleep state and the sleep_run row, and the two-conversation acceptance

SleepState gains claims_held / claims_released / claims_hold_capped /
claims_waiting (internal, never on /sleep/status), reset per cycle and carried
into the sleep_run ledger row as integers (R-HP12). Acceptance across two real
Sleep cycles (real Stage 2, Stage 5 and pending store): a claim heard about a
name with no page is held, and the second conversation's promotion writes it
onto the new page with its span current, the first conversation credited and
the pending line gone.

<attribution lines from the session's system reminder>
EOF
```

---

### Task 4: Docs — where the next reader will look

**Files:**
- Modify: `CLAUDE.md:236-239` (Entity promotion).
- Modify: `docs/goals/memory-evolution.md`: the `G141` row (`:705`), its body and its status cell.
- Modify: `docs/goals/TODO.md`: `:327-331` (Pick up here), `:632-633` (the queue's 13b line), `:719-727` (the
  G141 DECIDEs bullet), and one new bullet under "Research / decisions (not builds)".
- Add: this plan (`docs/superpowers/plans/2026-09-24-g141-hold-page-less.md`), if the orchestrator has not
  already committed it.

- [ ] **Step 1: `CLAUDE.md`.** Append one sentence to the Entity promotion paragraph, after "…an explicit link to
  an existing high-confidence entity.":

  > What Sleep hears about a name before it has a page is not lost (G141 PJ-0b): Stage 5.56 holds those claims
  > on the name's line in `<bank>/pending_entities.jsonl` (`api/services/pending_store.py`: spans, not copies;
  > at most 50 per name, the rest counted) and releases them onto the page, first and through Stage 3, in the
  > cycle whose Stage 5 gives the name one — a holding line leaves the store only then.

- [ ] **Step 2: The G141 row.** The row is ONE table line (`docs/goals/memory-evolution.md:705`), as every row
  is, so the insertion is prose on that same line: no line breaks, no bullets, no blockquote. Find the exact text
  `R-PJ16 accepted. |` in the row and insert the paragraph below between `R-PJ16 accepted.` and ` |`, with one
  leading space, pasted as one line:

  ```text
  **Built PJ-0b (2026-09-24, `feat/g141-hold-page-less`, plan `docs/superpowers/plans/2026-09-24-g141-hold-page-less.md`, R-HP1…R-HP13).** The pending store moved to `pending_store.py`, now its one writer; `vector_index` delegates. Stage 5.56 holds a page-less subject's Stage-1 claims on the pending line whose slug is that subject (`held_claims`, as `Claim.to_dict()`: spans, not copies; at most 50 per name, head-stable, the rest counted), and releases them first, through Stage 3, in the cycle whose Stage 5 gave the name a page: onto Stage 2's own exact verdict for the name, with the conversation they were heard in credited on the page. A holding line leaves the store only then. Promotion keeps it and a re-park carries it, so a cancel or a failure between Stage 2 and the claim write loses no held claim. Never held (still counted as `claims_page_less`): a subject with no pending line (Stage 1 named the endpoint differently from the entity), the owner surfaces, a claim closed in its own batch, and an event. Counts only: `claims_held`, `claims_released`, `claims_hold_capped` and `claims_waiting` on the `sleep_run` row. **Open:** nothing expires a pending name (an owner question; R7 and D2).
  ```

  In the status cell, replace `🟡 PJ-1/2/3/6 built (feat/g141-read-write);` with
  `🟡 PJ-1/2/3/6 built (feat/g141-read-write); PJ-0b built (feat/g141-hold-page-less);`.

  Check: `grep -c "^| G141 " docs/goals/memory-evolution.md` still prints `1`, and
  `grep "^| G141 " docs/goals/memory-evolution.md | grep -c "Built PJ-0b"` prints `1`. Placeholders only: no
  bank content.

- [ ] **Step 3: `TODO.md`.**
  - `:329-331` (the sentence wraps over three lines there): replace "Next on the backend: **PJ-0b** (hold a
    page-less subject's claims with its pending entity, ruled 2026-09-23; the seam is
    `claim_pipeline.hold_page_less`) and **PJ-1**." with:

    > **PJ-0b** is built on `feat/g141-hold-page-less` (plan `2026-09-24-g141-hold-page-less.md`): Stage 5.56
    > holds a page-less subject's claims on its pending line and releases them, through Stage 3, in the cycle
    > that gives the name a page; a holding line leaves the store only then. Nothing expires a pending name yet;
    > that is an owner question under Research / decisions.

  - `:632-633` (the phrase wraps after "hold"): replace "**PJ-0b** hold page-less claims with the pending entity
    (ruled 2026-09-23)" with "**PJ-0b** hold page-less claims with the pending entity (built,
    `feat/g141-hold-page-less`)", keeping the list's four-space continuation indent.
  - `:725-726`: replace "`claim_pipeline.hold_page_less`, shipped with PJ-0 (PR #88) and holds nothing until
    PJ-0b." with "`claim_pipeline.hold_page_less`, shipped with PJ-0 (PR #88); PJ-0b fills it (built on
    `feat/g141-hold-page-less`)."
  - Under "### Research / decisions (not builds)", add a bullet after the G141 DECIDEs bullet:

    > - **Pending-name expiry** (raised by G141 PJ-0b, 2026-09-24): nothing expires a name Stage 2 parked once.
    >   It stays in `pending_entities.jsonl`, with any claims held for it, until it is mentioned again, and the
    >   store grows by one line per such name. Should a name heard once and never again leave after N months,
    >   taking its held claims with it (counted)? That would change the promotion model: a mention months later
    >   would no longer promote. It is research R7's "decay-pruned candidates" and decision D2's question, so it
    >   is the owner's. Until then `claims_waiting` on the `sleep_run` row shows how much is waiting.

- [ ] **Step 4: Privacy check.** Run `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && git diff -- CLAUDE.md docs/goals/`
  and read it. It must contain no real name, no episode or inbox title, and no claim or conversation text; only
  placeholders and code identifiers.

- [ ] **Step 5: Commit.**

```bash
cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && git add CLAUDE.md docs/goals/memory-evolution.md docs/goals/TODO.md docs/superpowers/plans/2026-09-24-g141-hold-page-less.md && git commit -F - <<'EOF'
docs(g141): PJ-0b — the hold in CLAUDE.md, the G141 row and TODO

Entity promotion gains the hold sentence; the G141 row records PJ-0b as built
with its rulings (R-HP1..R-HP13) and what stays open; TODO marks the slice and
files the pending-name expiry question for the owner.

<attribution lines from the session's system reminder>
EOF
```

---

## Not in scope

Listed so a reviewer does not read an absence as an oversight. Each item is either an explicit exclusion or a
pre-existing behaviour this slice discloses without changing.

- **Expiring pending names** (R-HP9). No TTL exists, and adding one changes the promotion model (R7, D2). It is
  filed as an owner question. The store's structural rule means a future expiry must face the held claims.
- **Bounding the number of pending names.** The store already grows by one line per parked name. This slice
  bounds only the claims per name (R-HP3).
- **Holding a claim whose subject has no pending line.** That covers a relationship endpoint Stage 1 spelled
  differently from its entity, and a name Stage 1 never listed as an entity. Both stay counted in
  `claims_page_less` (M3). A fuzzy join over pending names is a new matcher (R-HP2).
- **Re-keying a hold by fuzzy match.** Only Stage 2's exact verdict on the name, or the page with the claims'
  own slug, releases a hold (R-HP5). A name Stage 2 later merges into a page with another name, and never hears
  again, waits and is counted in `claims_waiting`.
- **The history a re-park loses.** `index_pending_entity` replaces a line's `description`, `history_entries` and
  `source_episode` as it always did. Only the hold is carried. Merging the rest is a separate, pre-existing
  question.
- **A promoted page's credit for a pending line that held nothing.** Stage 2 still credits only the promoting
  episode (`entity_resolver.py:276-286`). R-HP8 credits the first conversation only through a released claim.
- **Stage 2's flush before the cancel points** (`entity_resolver.py:358-375` vs `sleep_cycle.py:1311`). A
  cancelled cycle still leaves Stage 2's clarification and pending-line writes behind. This slice makes the
  hold survive that window (R-HP4) and does not move the flush.
- **A promoted line that held nothing.** `take` still removes a line with no held claims at Stage 2's flush, as
  `promote_from_pending` always did. If that cycle's page write then fails, the claims heard about the name in
  that same cycle are page-less and there is no line to hold them, so they are counted in `claims_page_less`
  as under PJ-0. R-HP4's guarantee covers claims already held before the promoting cycle.
- **The pending vectors after a release.** A released line stays in the `pending` vector table until the next
  Stage 2 rebuild. `search_pending` has no production caller.
- **Claims lost before PJ-0b.** Cycles that ran under PJ-0 already marked their episodes processed. Getting
  those claims back needs a re-extraction (G10, 💸).
- **Agent writes about a page-less subject** (`cicada_write_claim`, `cicada_note_progress`). This slice is
  Sleep's hold only. Events are never held (R-HP2).
- **Any surface for held claims**: an endpoint, the app, recall or the timeline's "pending names" (R-HP13). A
  held claim is a hold, not a belief. PJ-5's greyed "mentioned once" line reads names, not held claims.
- **App, MCP and router changes.** None.

---

## Verification the orchestrator runs at the end

1. `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests -q -p no:cacheprovider`
   reports **0 failures** (3769 passed + 1 skipped, as measured in the plan's dry run). If
   `test_agent_provenance.py::test_a_decay_only_change_lands_in_its_own_cicada_authored_commit` is the only red,
   re-run it alone and report both results.
2. The acceptance test runs alone and passes:
   `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && api/.venv/bin/python -m pytest api/tests/test_sleep_cycle_hold.py -q -p no:cacheprovider -k two_conversations`.
3. The acceptance test fails when the fix is taken out. Temporarily make `claim_pipeline._releases` return
   `([], [], {})` at its top; the acceptance test must FAIL (no claim on the page). Revert and confirm green. A
   test that has never failed is not known to work.
4. `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && git diff --stat dev -- app/ mcp/ api/routers/`
   prints nothing. `git diff --stat dev` lists only the files in the File map.
5. The store has one writer.
   `cd /Users/rorosaga/Documents/roros_lab/cicada/.worktrees/pj0b && grep -rn "pending_entities.jsonl\|PENDING_STORE_FILE =" api mcp | grep "\.py:" | grep -v "/tests/"`
   shows only `api/services/pending_store.py`. `grep -n "write_text\|\.write(" api/services/pending_store.py`
   shows only `fh.write(text)` inside `save`: every write goes through its temp-file-then-replace.
6. Logs never carry a name. `test_the_hold_and_the_release_are_logged_as_counts_never_as_a_name` passes, and a
   read of every new `logger.` call in `pending_store.py` and `claim_pipeline.py` shows only counts, exception
   types, or opaque claim ids at DEBUG.
7. The legacy line is unchanged. `test_a_line_written_before_pj0b_round_trips_byte_for_byte` passes; a
   pre-PJ-0b `pending_entities.jsonl` re-writes byte for byte.
8. Privacy. `git diff dev -- CLAUDE.md docs/` contains no real names or bank content (placeholders only).
9. **PR body must state:**
   - the four new `sleep_run` refs are integers, and `claims_page_less` now means neither written nor held;
   - `pending_entities.jsonl` keeps its format (a new optional key) and stays tracked;
   - no endpoint, ETag, Store domain or app surface changed;
   - nothing calls an LLM or an embedder;
   - the pending-name expiry question is open for the owner.

   Cite `G141` and `PJ-0b`.
