# Perf harness: memory and source collection (2026-10-24)

Repeatable measurements of what Cicada's memory and source collection cost: Sleep, recall, Ask, the handshake and the
recall hook's note, source syncs, index maintenance and memory footprint. Synthetic text only (`example.com`,
`alpha-0001`, the newuser persona). The first run's numbers and what they led to are in the 2026-10-24 perf report
(referenced from the PR that added this folder).

Every in-process probe imports `benchmarks.scale.isolate` first: it refuses to run without `SCALE_SCRATCH` and pins
`HOME`, `CICADA_HOME` and the bank to that scratch folder, with capture, telemetry and every fetch off; sockets are
blocked. Never point a probe at a real bank.

## The two banks

```sh
S=<scratch>; export SCALE_SCRATCH=$S
# Owner scale: ~2k pages, 1.5k episodes (up to 60 turns), an owner page with 5,000 claims and 2,000 links (~15 s).
api/.venv/bin/python -m benchmarks.scale.synth --bank $S/bank --pages 2000 --claims 5000 --episodes 1500 \
    --processed 1450 --jsonl --activity --related 2000 --related-section --free-labels --turns-max 60 \
    --owner-facts 30 --owner-history 400 --commits 40
# The new user: one Sleep on the plan at haiku (benchmarks/newuser/README.md), then copy its bank and search model:
cp -R <run>/memory $S/nu-bank && mkdir -p $S/home/.cicada && cp -R <run>/cicada-home/models $S/home/.cicada/models
```

`cp -R` does not keep mtimes, so a copy's lexical index reads every file as changed; `--prep` brings a copy's derived
indexes current before a read is timed.

## Probes (`benchmarks.perf.probe`)

```sh
P="api/.venv/bin/python -m benchmarks.perf.probe"
$P recall  --bank $S/r1 --prep                       # p50/p95 warm, cold first call (fresh process), reply size by part
$P recall  --bank $S/nu-bank --embedder e5 --questions benchmarks/newuser/questions.json
$P ask     --bank $S/r1 --n 40 [--dump prompts.jsonl] # retrieval time (to the model call), prompt size by block
$P primer  --bank $S/nu-bank --questions benchmarks/newuser/questions.json   # handshake, SessionStart and prompt notes
$P index   --bank <copy>                             # FTS + vector sync: first, idle, after a night's decay
$P embedcost --bank $S/r1 --embedder e5 --pages 500  # what re-embedding entity pages costs with the real model
$P sources --bank <copy>                             # bookmarks first/unchanged syncs, staging scan, Claude Code capture
$P memory  --bank $S/r1 --embedder e5                # peak RSS: import graph, then recalls with the search model
```

`index` and `sources` write into the bank: run them on a copy. `--embedder e5` uses the small on-device model from
`$SCALE_SCRATCH/home/.cicada/models`; `hash` (the default) is the deterministic offline embedder, so its vector times
leave out the model's own embedding. Sizes are characters and ~tokens (characters / 4, the handshake's own proxy);
a JSON-heavy Ask prompt measured ~1.45× that on the plan.

## Live runs and the rest

- `benchmarks.perf.ledger <run>/cicada-home/telemetry/events-YYYY-MM.jsonl` — a verify-cicada run's model calls by
  stage: calls, gross prompt tokens, the engine's prompt-cache reads and writes, output tokens, model seconds.
- `benchmarks.perf.newuser_stats results.jsonl [after.jsonl]` — latency and reply size per tool from
  `benchmarks.newuser.ask`.
- `benchmarks.perf.embed_ab --bank <bank> --embedder e5` — an entity text change side by side: the cosine of each page's
  vector both ways, and labeled queries' MRR and top-8 overlap, beside one night's decay under the old text (the noise
  floor every night already has).
- `benchmarks.perf.recall_use --bank $S/nu-bank` — which parts of a recall reply hold the newuser questions' expected
  answers (a proxy for what an agent uses).
- `benchmarks.scale.profile_sleep --bank <copy> --drain 2` — one drain through the fake engine: stage times, the index
  steps, the tail, counted reads and writes (`--profile out.prof` for cProfile).
- `benchmarks.perf.live_batch --bank <copy>` — one batch on the Claude plan at haiku through the verify skill's
  `plan-claude` shim, telemetry into the scratch home. **Not on `synth`'s banks:** their episodes are word salad, and
  the model refused every extraction call it got (15 of 15, 2026-10-24, stopped by hand). It needs a bank of
  natural-language synthetic conversations, which nothing here generates yet.
