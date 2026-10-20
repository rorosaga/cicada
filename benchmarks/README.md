# Cicada benchmark harnesses

**Start here for answer quality** (G148, 2026-10-17 — the method and the survey behind it are in
[`docs/research/2026-10-17-memory-benchmarks.md`](../docs/research/2026-10-17-memory-benchmarks.md)):

- `benchmarks/public/` — **LoCoMo and LongMemEval end to end through Cicada** on throwaway banks and the person's
  Claude plan: sessions → episodes → Sleep → `cicada_ask` → the benchmark's own judge (Mem0's J for LoCoMo,
  LongMemEval's per-type prompts), with a full-context control, resumable, sliceable, cost measured in plan calls.
  `python -m benchmarks.public.run prepare|run|report --help`.
- `benchmarks/answer_eval.py` — **your own questions on your own bank**, graded against facts you write down
  (expected / forbidden / should abstain); the question file is gitignored (`benchmarks/*.local.*`), start from
  `benchmarks/answer_eval.example.yaml`.
- `benchmarks/hard_questions.py` — **hard questions drafted from your own bank** for `answer_eval`: seeded samples
  of the shapes hand-written questions miss (knowledge updates with the stale value forbidden, one subject months
  apart, multi-hop across two conversations, counting/listing across 3+ conversations, dated-event order, abstention
  traps, a Spanish share), one plan call per question, then a review sheet you accept or reject before use. See
  *Hard questions* below.
- `benchmarks/system/` — the whole-system integrity benchmark (synthetic, offline fake engine).
- `benchmarks/recall_ab.py` — page-ranking A/B (finds the right page; does not grade the answer).

## Hard questions (G148)

The coordinator command, on the owner's bank (outputs are gitignored `benchmarks/*.local.*`, written 0600; the
terminal shows ids and counts only; the bank is only read):

```sh
# 1. look first: samples and the review sheet, no plan call
api/.venv/bin/python -m benchmarks.hard_questions --bank <bank dir> --limit 40 --seed 1 --dry-run
# 2. draft: one `claude -p` (sonnet) call per sample, ≤ --limit calls
api/.venv/bin/python -m benchmarks.hard_questions --bank <bank dir> --limit 40 --seed 1
# 3. read benchmarks/answer_eval.hard.review.local.md; tick "- [x] accept <id>" on each fair question
api/.venv/bin/python -m benchmarks.hard_questions --accept
# 4. grade Cicada on the accepted ones
api/.venv/bin/python -m benchmarks.answer_eval --bank <bank dir> \
    --questions benchmarks/answer_eval.hard.accepted.local.yaml
```

**Sampling** (`--seed` fixes it; one sample per page; the owner page and saved links are never a subject; a
conversation is a dated episode that is not a memory-export entry or an indexed watch record):

| Kind | Drawn from | The draft |
|---|---|---|
| `update` | a claim whose `superseded_by` names a claim on the same page that is still current | asks for the current value; `forbid` holds the stale one (the old claim's text if the drafter gives none) |
| `temporal` | a page whose first and last conversations are ≥ 14 days apart | needs both moments: what changed, what came first, how long between |
| `multi-hop` | a current claim linking a page to another page, plus a current claim on that page evidenced in a *different* conversation | asks about the first page; the answer needs the second hop |
| `count` | a page in ≥ 3 conversations (up to 6 shown) | lists or counts what those conversations state |
| `event` | a page with `happened`/`milestone` claims on ≥ 2 days | order, or time between |
| `abstention` | a page in ≥ 2 conversations with claims | a plausible question none of the shown evidence answers; `abstain: true` and a `why` |

The default mix is 4 update · 4 temporal · 4 multi-hop · 3 count · 2 event · 3 abstention per 20 slots (a kind with
no candidates gives its slot to the next), and about a quarter of samples (seeded) are drafted in Spanish (`es`).
Each sample shows the drafter the page's claims and evidence snippets (a claim's own evidence span, else the first
mention of the page's name) — the same snippets the review sheet lists under each question. The drafter may decline
(`skip`); a skipped or unusable draft is listed in the sheet with its reason and never reaches the YAML. Items carry
`sources` (episode ids), `why` and `sample` beside the eval's own fields; `answer_eval` ignores the extras. A rerun
keeps every draft already in `--out` for the same sample (`--fresh` redrafts); `--kinds` narrows the mix.

The rest of this file documents the older thesis scripts.

# Cicada thesis benchmark harness

Three runnable scripts plus a shared fresh-workspace scaffold. They
produce real numbers for `tab:question_scores`, `tab:ablation`, and
`tab:performance` in `sections/results.tex`.

All runners:

- read from the live `memory/` directory only (never write to it);
- write outputs to `benchmark_results/<table>/` as timestamped JSON + CSV;
- run any sleep cycle inside a throwaway workspace under `/tmp/cicada_bench_*`.

The runners assume you invoke them from the repo root (`cicada/`) with
the API's venv Python:

```sh
cd <your cicada checkout>
api/.venv/bin/python -m benchmarks.run_table1 --questions benchmarks/questions.example.yaml
```

`api/.env` is auto-loaded by the bootstrap module, so `OPENAI_API_KEY`
and any other keys you have set for the FastAPI server work here too.

---

## Table 1 — three-condition recall eval

```sh
api/.venv/bin/python -m benchmarks.run_table1 \
    --questions benchmarks/questions.example.yaml \
    --memory memory \
    --out benchmark_results/table1
```

Runs every question in the YAML through three conditions:

| Condition | Retrieval path |
|---|---|
| `A_cicada_full` | MCP Bookworm `handle_recall` — entities, keyword fallback, wikilink hops, episode excerpts, nudges, clarifications. |
| `B_cicada_no_sleep` | Raw episode sqlite-vec index only. No entities, no keyword, no hops, no nudges, no clarifications. |
| `C_commercial_manual` | Stub row. Paste your ChatGPT / Claude answer into the `final_answer` CSV column before scoring. |

Conditions A and B both use the same answerer LLM with the same prompt,
so the only thing that differs is what the retrieval layer returned.

Outputs:

- `runs_<ts>.jsonl` — one line per `(question, condition)`, with the
  full retrieved context, synthesized answer, retrieve/synth latency,
  and any retrieval notes. Keep this for the paper's qualitative
  walkthroughs.
- `scoring_sheet_<ts>.csv` — one row per `(question, condition)` with
  four blank rubric columns (`factual_accuracy`, `relational_depth`,
  `proactive_recall`, `actionability`) and a `notes` column. Open in
  a spreadsheet, score 0-3 per the `experiments.tex` rubric, save.

> ⚠️ Scoring is manual by design — we don't want to fake rubric scores
> with an LLM judge without first validating the judge against human
> agreement. That validation is out of scope for this pass.

### Fill in your question set

`questions.example.yaml` is a TEMPLATE with placeholder entries only.
Do not commit real questions to it. Instead copy it to a gitignored
local path and edit the copy:

```sh
cp benchmarks/questions.example.yaml benchmarks/questions.local.yaml
# edit benchmarks/questions.local.yaml with your real 15-20 questions
api/.venv/bin/python -m benchmarks.run_table1 \
    --questions benchmarks/questions.local.yaml \
    --memory memory \
    --out benchmark_results/table1
```

Any file matching `benchmarks/*.local.*`, `benchmarks/questions.yaml`,
or `benchmarks/queries.txt` is already in `.gitignore` so you can fill
in personal content safely. Same pattern for the Table 3 query set:
`cp benchmarks/queries.example.txt benchmarks/queries.local.txt` and
point `--queries` at the copy.

Keep the four categories (`factual_recall`, `relational_depth`,
`proactive_recall`, `actionability`) as-is so the rubric columns stay
meaningful.

---

## Table 3 — operational measurements

Static metrics + recall latency only (fast, no API spend):

```sh
api/.venv/bin/python -m benchmarks.run_table3 \
    --memory memory \
    --queries benchmarks/queries.example.txt \
    --out benchmark_results/table3
```

Add a full fresh sleep cycle timing pass (⚠️ costs real API dollars,
spends tokens on every episode):

```sh
api/.venv/bin/python -m benchmarks.run_table3 \
    --memory memory \
    --queries benchmarks/queries.example.txt \
    --sleep-cycle-time \
    --out benchmark_results/table3
```

You can cap episodes for a smoke test first:

```sh
api/.venv/bin/python -m benchmarks.run_table3 \
    --memory memory \
    --sleep-cycle-time \
    --episode-limit 5 \
    --out benchmark_results/table3
```

Output `metrics_<ts>.{json,csv}` includes:

- `episode_count`, `entity_count`, `clarifications_count`, `nudges_count`
- `memory_total_bytes`, `leann_total_bytes`
- per LEANN index (`entities`, `episodes`, `pending`):
  - `leann_<name>_index_built` — boolean, true only when the
    `<prefix>.meta.json` build marker exists. This is the same marker
    `LeannIndexer._search` uses to decide whether the index is
    actually queryable.
  - `leann_<name>_index_bytes` — byte total of the index fileset, but
    only when `built` is true. If the index is unbuilt this field is
    0 so the CSV cannot imply the index is searchable when it isn't.
  - `leann_<name>_index_partial_bytes` — byte total of any leftover
    `<prefix>.*` artifacts when the index is NOT built (e.g. a
    half-finished `episodes.passages.jsonl` from a prior failed
    rebuild). Lets you see disk waste without misreporting it as a
    real index size.
- `leann_pending_store_bytes` — the JSONL store backing the pending index.
- recall latency: `mean`, `median`, `p95`, `min`, `max` (sample size
  reported alongside; with fewer than ~20 queries, p95 is a coarse
  approximation, treat it as indicative).
- if `--sleep-cycle-time`: `sleep_cycle_wall_clock_seconds`,
  `sleep_cycle_seconds_per_episode`, entity/nudge counts after the
  run, and the workspace path (left on disk so you can inspect).
  `sleep_cycle_succeeded` is read from `SleepState.error`, not from
  the absence of a Python exception, because `sleep_cycle.run`
  catches its own internal failures so the FastAPI background task
  doesn't crash the API. A failed run will show
  `sleep_cycle_succeeded: false` with the underlying exception in
  `sleep_cycle_error` and the last stage label in
  `sleep_cycle_progress`.

**API cost is not instrumented** — LiteLLM's `response.usage` isn't
piped through today's sleep-cycle call sites, and faking a number
would violate the "no fake results" rule. If you want to populate the
"API cost per sleep cycle" row in `tab:performance`, the cheapest
honest source is the OpenAI dashboard for the window you ran
`--sleep-cycle-time` in, labelled as "observed" not "instrumented".

---

## Table 2 — ablation study (threshold sweeps)

```sh
api/.venv/bin/python -m benchmarks.run_ablation \
    --memory memory \
    --out benchmark_results/table2
```

Smoke test (10-episode slices, much cheaper):

```sh
api/.venv/bin/python -m benchmarks.run_ablation \
    --memory memory \
    --out benchmark_results/table2 \
    --episode-limit 10
```

Run a subset of ablations:

```sh
api/.venv/bin/python -m benchmarks.run_ablation --only default promotion_1
```

Sweeps the threshold knobs currently supported by `api.config.Settings`:

| Row | `sleep_promotion_threshold` | `decay_nudge_threshold` | `archive_threshold` |
|---|---|---|---|
| `default`          | 2 | 0.4 | 0.2 |
| `promotion_1`      | 1 | 0.4 | 0.2 |
| `promotion_3`      | 3 | 0.4 | 0.2 |
| `decay_aggressive` | 2 | 0.5 | 0.2 |
| `decay_loose`      | 2 | 0.3 | 0.2 |

Each row runs in its own `/tmp/cicada_bench_table2_*` workspace. The
real `memory/` is never touched.

**What this ablation reports is structural, not rubric-based.** The
CSV gives you `entity_count`, `nudges_count`, `clarifications_count`,
`leann_*_bytes`, and sleep wall-clock time per configuration. This is
enough to answer "does varying the threshold measurably change the
consolidation output" — which is the self-consistency question
`experiments.tex` actually asks. Getting four-dimensional rubric
scores per ablation row requires re-running `run_table1` against each
workspace and scoring manually; that's a deliberate follow-up step,
not a blocker for the structural table.

### Deliberately not implemented

- **Stage 4 on/off** and **LEANN pending index on/off**. Neither is
  currently a config flag — both would need a feature toggle added to
  the respective service module. Doing that surgery right before the
  deadline was judged too risky for the 24-hour budget. If you want
  these rows, add a `skip_skill_extraction: bool = False` field to
  `Settings`, have `sleep_cycle.run` skip Stage 4 when the flag is
  set, and append new entries to `ABLATIONS` in `run_ablation.py`.

---

## Safety rails

- No runner writes to `memory/`. The only write ops happen inside
  `/tmp/cicada_bench_*` workspaces created by `workspace.py`, and
  `destroy_workspace` refuses to touch any path whose name doesn't
  include `cicada_bench_`.
- `api/.env` is loaded into `os.environ` by `_bootstrap.py`, but
  existing env vars in the shell always win.
- Every runner prints its memory path and output dir at startup so
  you can eyeball it before it spends API tokens.
- `benchmark_results/`, `benchmarks/*.local.*`,
  `benchmarks/questions.yaml`, and `benchmarks/queries.txt` are
  already in the repo `.gitignore`, so scored CSVs and personal
  question sets don't accidentally land in a commit.
