# Awake read: a conversation is recallable as soon as it lands (G207, ruling 36 D2)

Branch `feat/awake-read` off `dev`. One PR against `dev`.

## Global constraints

- **Capture stays file I/O.** Nothing here runs inside a capture write. The capture routes and the relay call
  `awake_read.after_capture(...)` *after* their writer has returned. That call only puts a job on a queue and
  returns: no read, no embed, no model. (Owner D2 amends "No LLM at capture time" only by allowing a *separate*
  job after capture. The docs worker owns the CLAUDE.md rail text.)
- **Derived-index rails.** Vectors are disposable and never tracked. The caller passes the active bank (the bank
  the capture was filed in, never re-resolved). The query is never logged. **Never during a model re-embed**:
  step 0 does nothing while `embedding_models.REINDEX` is `running`/`waiting` or `pending_switch` names a switch,
  and never while Sleep runs.
- **On-device vectors only.** Step 0 embeds only when the episodes table's recorded model runs on this machine
  (`vector_index.runs_on_device`). With a hosted embedder, the conversation waits for Sleep's sync as before.
- **Sleep stays the authority.** A quick read writes **no page, no claim fence, no pending line, no git**. Its
  output is a provisional record per episode in `<bank>/.awake/<episode>.json`. That record is a derived artifact
  (listed in `bank_registry.DERIVED_ARTIFACTS`, so `git add -A` never sweeps it). Recall reads it only while the
  episode is still `processed: false`. Sleep settles it when it retires the episode.
- **Admission (G177/G183).** The record write runs under `write_admission.admitted(bank)`, in the order
  admission → file. It is never held across the model call. A quick read never starts while
  `sleep_cycle.is_writing()` or Sleep's status is `running`. Such a read is put back on the queue.
- **Engine (rulings 4, 31).** The quick read resolves the engine like a scheduled run
  (`engine_select.resolve_settings(settings, user_triggered=False)`). So the person's plan is used only under
  "Scheduled runs may use my plan", and Auto never falls to a metered key. The model is the engine's small one
  (`agent_disambiguation_model` / `codex_disambiguation_model` / `litellm_disambiguation_model`). With no engine,
  there is no read.
- **Demo bank:** never (`demo_guard.is_demo`), on both steps.
- **Idempotent per revision:** a record carries `episode_ids.body_revision(body)`. The same revision is never
  read twice. A newer revision replaces the record.
- **No Settings toggle.** `CICADA_AWAKE_READ` = `off` (nothing), `index` (step 0 only) or `on` (step 0 + 1). When
  unset, step 0 runs, and step 1 runs only if `QUICK_READ_DEFAULT` is on. That constant is set from the
  measurement below. The suite's conftest sets `off`, and the tests for this feature turn it on.
- **Privacy:** tests and the benchmark use synthetic placeholder people and projects only.

## Rulings (this plan's)

1. **When a conversation "ends".** A harness Stop fires on every turn, so the read waits for quiet:
   `QUIET_S` (600 s) after the episode's last capture. `SessionEnd`/`session_end` reads after `ENDED_S` (5 s).
   A relayed conversation (`cicada_capture_turns`) has no end event, so it uses the quiet window. An import with
   at most `IMPORT_READ_MAX` (5) conversations reads each one after `ENDED_S`. A bigger import gets step 0 only
   and waits for Sleep. Reading a thousand-conversation export on the person's plan, unasked, is not "a quick read".
2. **A spend bound.** At most `READS_PER_HOUR` (20) quick reads per process. Past that, a conversation waits for
   Sleep, and that is logged.
3. **Reuse Stage 1, do not fork it.** The read is `entity_extractor.extract([episode], small_settings,
   stage="quick_read")`, then `entities_to_claims(..., resolve_id=...)`. Same prompt, same G118 evidence spans, same
   deterministic claim ids. That is what lets Sleep confirm a provisional claim by id.
4. **Existing pages only.** The resolver maps names to page ids from the pages' `name` and `aliases`, and maps the
   owner's self-references (`claim_pipeline.subject_resolver`). A claim whose subject has no page is not written.
   Its subject name is *held* in the record (`held`: name, type, claim count) for Sleep's promotion. Sleep reads
   the episode itself, so nothing is double counted in `pending_store`.
5. **Sleep settles.** After `_mark_episodes_processed`, `awake_read.settle(bank, retired)` classifies each
   provisional claim. **confirmed**: the same claim id is now on its page. **corrected**: the page has a claim from
   that episode with the same subject and predicate. **dropped**: anything else. It logs the counts (enums and
   numbers only) and deletes the record. A record whose episode is processed is never shown, settled or not.
6. **Recall.** The excerpt leg fuses the existing vector leg (`_leann_search_episodes`) with a word leg over the
   FTS episode passages (`search_service.search(kinds=("episode",), mode="prefix")`) by RRF, keeping 3. An excerpt
   from an unprocessed episode is labelled `(<day>, not yet read by Sleep)`. The provisional block,
   **"Not yet read by Sleep (provisional):"**, lists up to 12 claim lines: the top hits' subjects first, then
   claims sharing a query word. It is followed by up to 5 held names that match a query word. It is a normal
   `output_parts` entry, so `_fit_recall`'s 40k/20k budget (#418) still governs. Verbatim excerpts stay under the
   `sources` scope (R-R22). Provisional claim lines are Cicada's reading, not verbatim, so they follow the claim
   leg's scope (always shown).

## File map

| File | Change |
|---|---|
| `api/services/awake_read.py` | new: env, queue + worker thread, `after_capture`, `after_import`, `index_now`, `quick_read`, `provisional_for`, `held_for`, `settle` |
| `api/services/vector_index.py` | `index_episode_stems(stems)`: a targeted upsert. Never removes another episode's rows, never rebuilds a table that holds rows (a model or width mismatch skips) |
| `api/services/entity_extractor.py` | `extract(..., stage=)`, `_extract_chunk(..., stage=)`: the telemetry stage label (default unchanged) |
| `api/services/bank_registry.py` | `.awake/` in `DERIVED_ARTIFACTS` |
| `api/routers/capture.py` | transcript, session and turn routes call `after_capture` after a created/updated write |
| `api/services/relay_capture.py` | the same after a created/updated relay |
| `api/routers/intake.py` | `after_import` with the touched ids |
| `api/services/sleep_cycle.py` | `awake_read.settle` after `_mark_episodes_processed` |
| `api/services/mcp_tools.py` | recall: fused excerpt leg + labels + provisional block |
| `api/tests/conftest.py` | `CICADA_AWAKE_READ=off` per test |
| `api/tests/test_awake_read.py` | new |
| `benchmarks/awake_bench.py` | new: synthetic bank, conditions a/b/c, 3 repeats, Claude plan + haiku |
| `docs/architecture/capture-and-sleep.md`, `mcp.md`, `storage.md` | the job, recall's leg, the store |

## Tests (test-first, `api/tests/test_awake_read.py`)

- `after_capture` returns at once and runs nothing in the caller's thread (the worker is stubbed).
- `index_now` embeds only the named episode. Other rows stay byte for byte. It skips while Sleep runs, a reindex
  runs, or the model is hosted. A demo bank gets nothing.
- `quick_read` with a stub extractor: claims on existing pages land in the record with evidence spans. A new name
  is held, not written. No page, pending store or git commit changes. Same revision twice gives one model call.
  Sleep running means rescheduled. With no engine, no call.
- `settle`: confirmed / corrected / dropped counts; the record is removed.
- Recall: an unprocessed episode found only by words is shown with the label. Provisional claims appear and
  disappear once the episode is processed. The reply stays under `RECALL_BUDGET` with 50 records.
- `bank_registry.DERIVED_ARTIFACTS` holds `.awake/` (the record is never committed).

## Measure before defaulting

`benchmarks/awake_bench.py` builds a scratch bank of consolidated pages with claims fences, plus 6 new unslept
conversations, and writes 12 questions. Every question is answerable only from a new conversation, or asks about
something a new conversation changed. Conditions: (a) today (recall's vector leg with no vectors for the new
conversations, no provisional block); (b) step 0; (c) step 0 + 1. For each question, haiku on the Claude plan
answers from the recall reply, and haiku judges it against the expected facts (`benchmarks/answer_eval.py`'s judge
prompt). There are 3 repeats, and a repeat redoes the quick reads. Reported per condition: mean correct, min–max,
and the quick read's calls and tokens per conversation. **Step 1 defaults on only if (c)'s mean beats both (a)'s
and (b)'s by more than the larger spread.**

**Amendment (2026-10-22, written after the first smoke run and before any repeat).** The smoke run put (b) at
12/12, a ceiling: with only 6 new conversations, recall's 3 excerpt slots hold every one of them, so the set cannot
show whether step 1 helps. A **hard variant** adds `--distractors 30`: thirty other unslept conversations from the
same day that name the same pages and share the questions' words, like a real day of captures. **The default rule
reads the hard variant.** Step 1 is on only if (c) beats (b) there by more than the larger min–max, and (c) is not
below (b) on the easy set.

## Verify

verify-cicada on a scratch bank: a hook-path capture (`cv capture`, two sessions naming `alpha-project`), then
recall finds it before Sleep, then a quick read (`CICADA_AWAKE_READ=on`, quiet window shortened by env for the run),
then `cv sleep`, then the provisional record is settled and the claims are on the page.

## Not in scope

The CLAUDE.md rail text (docs worker), any app/Settings UI, `cicada_ask`'s own legs (it already has the word leg),
ranking by recency (G210).
