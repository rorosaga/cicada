# Whole-system benchmark (G148)

Supported entry point: `python -m benchmarks.system.runner`. This runner never
imports `benchmarks/_bootstrap.py`. The other scripts in `benchmarks/` and their
historical scores are **legacy**: retrieval/static experiments, not whole-system
acceptance evidence. Keep their dated outputs; do not compare them to this runner.

The small preset covers synthetic scenarios **1, 2, 4 and 5**. Offline fake-engine
results establish pipeline integrity, not model quality or real embedding speed.
Scenario 3 (multiple sources), scenario 6 (scale/concurrent activity), LoCoMo loading,
LongMemEval and the actual subscription pilot remain out of scope.

```sh
api/.venv/bin/python -m benchmarks.system.runner \
  --bank-dir temp --home temp --config benchmarks/system/small.json \
  --clock 2026-10-06T12:00:00+00:00 --model deterministic-v1 --effort low \
  --preset small --engine fake
```

The last stdout line identifies the manifest. It is stored under the marked
benchmark home in `results/` (0600 JSON), never inside the bank or next to an
explicit bank. Failures also
produce a manifest and a nonzero exit. A failed integrity assertion is not a score.
The config has only `batch_size` (2 for small) and the embedding model. `--validate-only`
prepares marked directories and validates arguments without importing the backend.

`temp` creates a fresh directory and writes an ownership marker. Explicit paths
require the exact `_bench.yaml` / `_bench_home.yaml` marker; symlinks and overlapping
bank/home paths are refused after symlink checks and canonical resolution. Internal model-cache symlinks in the home are permitted only when their targets stay within that home; bank symlinks are always refused. The small workload requires an empty marked bank.
Home can be reused for separately provisioned plan sign-in/model cache; a fresh bank
is required each time. Config, expected answers, judge output and manifests remain
outside banks. The child uses an allowlisted environment, isolated HOME/CICADA_HOME,
capture/fetch/telemetry off and provider keys absent. Explicit workload settings
use `_env_file=None`; the home refuses `.env`, so default read-service settings
cannot load a home dotenv file. `LITELLM_MODE=PRODUCTION` disables the transport
library's import-time `load_dotenv` call. `PYTHON_DOTENV_DISABLED` is not used: the
installed dotenv reader does not honor it. The child
uses `python -P` with the repository on `PYTHONPATH`, preventing reusable-home
packages from shadowing repository code. `PYTHONHASHSEED=0` pins set iteration. It never reads/copies a developer's bank, settings or credentials.

## Production coverage and controls

Input sentences and dated turns come from `fixtures/conversations.json`; held-out
questions/gold are a separate file that neither the fake engine nor production
stager receives. The fake engine understands a small sentence grammar and returns
extractions from the **actual input**, not gold summaries. It injects the existing
`completion=` transport seam beneath `providers.resolve_llm_fn`; the real local
route binds the model and emits telemetry events and drain call accounting. Feature-hash embeddings
replace only the embedding provider and are named `fake-hash-v1` in index metadata.
All five stage functions run. Recovery faults below are diagnostics; an accidental
network connection fails closed.

The workload uses `episode_staging.stage`, the production `sleep_cycle.run(drain=True)`
entry point, all five stages, the real tail, commits, sqlite-vec and FTS5. It checks
unchanged import, continued/revised identity, revision during extraction, pending
retirement, a dated single-valued `runs-on` change with history, a manual correction
and fixed-clock expiry. **Diagnostic recovery injections** in the fake completion
stop **within batch two** after batch one commits: a manually tripped pause breaker
and synthetic throttle, cooperative cancellation, and an unavailable-engine error.
These check Sleep's stop/resume handling; the local fake route does not verify the
subscription transport, its semaphore, or its breaker checks. The manifest labels
this limitation explicitly. Continue reloads the actual `sleep_paused` sidecar, retaining the run id.
Checks include retained claim ids, coverage of processed conversations by evidence,
no duplicate claim ids, author/session trailers and `_state.md` committing alone.

Each held-out question gets a fresh stateless call, same model/effort and six-hit
budget (3000 characters/hit on the read surfaces):

- Full context: raw staged conversation bodies, supplied directly to the answer engine.
- Before Sleep: production `SqliteVecIndexer.search_episodes` over raw episodes.
- After Sleep: production `ask_service.answer_query`, claim-first retrieval with
  entity fallback, citations and gap handling.

Prompt contracts are `ask_service.ASK_SYSTEM_PROMPT`, `_build_prompt` for Ask, and
`QUESTION:\n<question>\n\nCONTEXT:\n<raw-or-retrieved-bodies>` for the two controls.
No expected answer is included. Exact equality is meaningful only for the fake
engine's finite grammar; claim/evidence checks provide the integrity grade.
Subscription answers are **ungraded**, saved for manual grounded review; no judge
or overlap grader exists. Irrelevant retrieval/citations must be examined separately
from a correct abstention sentence. This harness does not claim a model leaderboard.

## Clock and measurement

`runtime.Runtime.frozen` replaces only imported `date`/`datetime` attributes at
benchmark service boundaries; the manifest lists every covered module. Dependencies
are preloaded before the first run. Delegating instance checks keep real date and
datetime values (including YAML frontmatter scalars) recognizable by production. The fixed clock advances deliberately by one
day for idle-tail expiry. Production code gets no new global clock setting. Real
monotonic timers, file mtimes, plan-limit/transport clocks and telemetry measurement
clocks stay real. Scope is a single isolated child, not concurrent benchmark runs
inside a shared backend process.

The manifest records revision, OS/processor/CPU count, model/effort/stage pins,
embedding metadata, fixture hashes, settings, initial/final clock, three controls,
failures, paused/resumed lineage, commits and index sizes. Transparent wrappers
measure each stage/batch/drain/tail, vector/lexical indexing, model calls and
embedding calls; the write stage includes claim writing and finalization. Nested
index/commit times overlap write time and must not be summed. Calls include failures;
transport retry counts are unknown unless reported. Fake calls report tokens as
unknown; no estimate or per-run subscription dollar figure is invented.

Resources use real `perf_counter`, process CPU plus child CPU, `RUSAGE_SELF.ru_maxrss`
(macOS bytes, Linux KiB converted), and bank/home disk growth. Model subprocess RSS
is unavailable. Throughput is unique staged episodes per whole-workload wall second,
including startup/recovery/verification; attempted extraction calls are reported
separately. Three service-latency samples per control give nearest-rank p50/p95,
with cold indexes at startup and warmed subsequent legs. These are service timings,
not HTTP latency, app responsiveness or a scale/concurrency report. Local processing
versus provider wait is not separable from these call timers.

## Later subscription-only synthetic pilot

**Needs the owner's go — spends plan quota.** These are preparation/execution
commands for a later owner-approved run; no pilot was run while building the harness.
They run the synthetic small corpus, not the still-unbuilt one-conversation/30-question
LoCoMo pilot. The fake-only interruption and mid-extraction revision injections are
not applied to a real subscription. Remaining integrity fields are explicitly unknown.

Prepare isolated directories without a generative call:

```sh
bench_setup="$(api/.venv/bin/python -m benchmarks.system.runner \
  --bank-dir temp --home temp --config benchmarks/system/pilot.json \
  --clock 2026-10-06T12:00:00+00:00 --model gpt-6-luna --effort low \
  --preset small --engine codex --validate-only)"
bench_home="$(printf '%s' "$bench_setup" | python3 -c 'import json,sys; print(json.load(sys.stdin)["home"])')"
bench_bank="$(printf '%s' "$bench_setup" | python3 -c 'import json,sys; print(json.load(sys.stdin)["bank_dir"])')"
```

Sign in through the same isolated subscription CLI home Cicada's adapter uses;
no credential is copied from the developer's setup:

```sh
api/.venv/bin/python -c '
import os, subprocess, sys
from pathlib import Path
from benchmarks.system.runner import isolated_env
home, bank = map(Path, sys.argv[1:])
env = isolated_env(bank, home, "codex")
env["CODEX_HOME"] = str(home / "codex")
subprocess.run(["codex", "login", "--device-auth"], cwd=home, env=env, check=True)
' "$bench_home" "$bench_bank"
```

Provision the public local embedding model in that home's cache ahead of the run
(one explicit download, no inference API):

```sh
HOME="$bench_home" HF_HOME="$bench_home/.cache/huggingface" \
  api/.venv/bin/python -c 'from huggingface_hub import snapshot_download; snapshot_download("intfloat/multilingual-e5-small")'
```

Exact synthetic pilot execution:

```sh
api/.venv/bin/python -m benchmarks.system.runner \
  --bank-dir "$bench_bank" --home "$bench_home" --config benchmarks/system/pilot.json \
  --clock 2026-10-06T12:00:00+00:00 --model gpt-6-luna --effort low \
  --preset small --engine codex
```

Before **any** generative control call, the runner requires positive live evidence
of ChatGPT subscription auth, the requested model on the visible roster and usable
allowance, using the existing read-only adapter/preflight. It saves only plan/window
metadata, never account email or tokens. A missing/ambiguous snapshot fails closed.
The guarded subscription adapter pins every consolidation/disambiguation/answer
call; no API-key fallback, provider substitution, automatic top-up, judge or quota
retry loop is configured. The runner requires cached local embeddings and disables
model downloads. Availability, allowance and runtime are observations at execution,
not promises this command fits any particular plan.
