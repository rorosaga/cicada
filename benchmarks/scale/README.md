# Scale probes: the owner-page outlier

Probe code, not a test suite. Every script imports `isolate` first. It refuses to run without `SCALE_SCRATCH` and pins
`HOME`, `CICADA_HOME` and `CICADA_MEMORY_PATH` to that scratch directory before any `api` import. Capture, telemetry
and fetches are off, and the sweeps block sockets. Everything is synthetic (`owner-example`, `alpha-0001`,
`alpha3-project`).

```sh
S=<scratch>; export SCALE_SCRATCH=$S
api/.venv/bin/python -m benchmarks.scale.synth --bank $S/bank --claims 3500 --commits 40    # ~25 s
api/.venv/bin/python -m benchmarks.scale.profile_reads --bank $S/bank                       # (a) card reads by step
cp -R $S/bank $S/run && api/.venv/bin/python -m benchmarks.scale.profile_sleep --bank $S/run  # (c) one batch, fake engine
api/.venv/bin/python -m benchmarks.scale.sweep_routes --bank $S/run                         # (d) every plain GET
api/.venv/bin/python -m benchmarks.scale.sweep_mcp --bank $S/run                            # (d) MCP read tools
api/.venv/bin/python -m benchmarks.scale.profile_route --bank $S/run /state /graph          # cProfile one route
```

The owner page as measured on 2026-10-14 (real values redacted): ~5,900 activity claims (~740-880 characters a line),
2,024 Related lines, hundreds of Sleep commits —

```sh
api/.venv/bin/python -m benchmarks.scale.synth --bank $S/bank --pages 2100 --claims 5921 --related 2024 \
    --related-section --activity --jsonl --owner-facts 6 --owner-history 100 --commits 520           # ~80 s
cp -R $S/bank $S/run && api/.venv/bin/python -m benchmarks.scale.owner_page --bank $S/run --write  # sizes, recall_detail,
                                                                       # the article's input, one stage write
```

The real labels are free-form (hundreds of verbs) and the real episodes are imported conversations with long
`turns:` lists; `--free-labels` writes `graph_edges.yaml` and Related lines from combinatorial labels, `--turns-max`
sets the turns per episode (2026-10-14 re-check: 2,024 Related lines, 3,000 episodes of up to 120 turns):

```sh
api/.venv/bin/python -m benchmarks.scale.synth --bank $S/bank --pages 2100 --claims 5400 --related 2024 \
    --related-section --activity --jsonl --free-labels --owner-facts 30 --owner-history 800 --turns-max 120 \
    --episodes 3000 --processed 2000 --commits 60
```

- `synth` builds the bank: one owner page with N claims, rewritten by `--commits` synthetic Sleep commits; 2,000 other
  pages with a Pareto tail of claims; 1,500 staged episodes, 975 of them processed.
- `profile_sleep` runs one `sleep_cycle.run` batch through the system benchmark's fake engine. The probe's grammar also
  makes the owner the speaker of every fact, so every batch writes to the owner page. It reports per-stage wall time,
  owner-sized YAML loads/dumps, and timers for the functions listed in `WATCH`. It mutates the bank, so run it on a
  copy. The first batch on a fresh synthetic bank also charges decay on every page and builds the indexes cold, so read
  batch 2 onward.

## Whole-bank scale (2026-10-16)

The owner's whole bank as the coordinator counted it (real values redacted): ~4,700 entity pages (~850 of them saved
items), a few thousand episodes, an inbox of ~240. `owner_scale` builds that on top of `synth`'s owner page; then:

```sh
api/.venv/bin/python -m benchmarks.scale.owner_scale --bank $S/bank                      # ~35 s: 4,701 pages, 3,850 episodes
cp -R $S/bank $S/run && api/.venv/bin/python -m benchmarks.scale.hot_routes --bank $S/run   # hot routes p50/p95, 304 cost,
                                                                                         # every Store domain's payload
api/.venv/bin/python -m benchmarks.scale.profile_route --bank $S/run --warm /inbox        # cProfile a warm call
cp -R $S/bank $S/s && api/.venv/bin/python -m benchmarks.scale.sleep_tokens --bank $S/s   # prompt chars by stage, cacheable share
cp -R $S/bank $S/d && api/.venv/bin/python -m benchmarks.scale.profile_sleep --bank $S/d --drain 3   # per-batch stage times
cp -R $S/bank $S/i && api/.venv/bin/python -m benchmarks.scale.index_rebuild --bank $S/i  # full + idle index builds
```

`cp -R` does not keep mtimes, so a copy's derived indexes read every file as changed: rebuild them in the copy
(`search_index.rebuild`) before timing a fresh process's first recall. `profile_sleep --parse-cache` is a prototype
measurement for a proposal (a stat-keyed `markdown_parser.parse` cache), not production code.

## Follow-ups (2026-10-16, second round)

```sh
cp -R $S/bank $S/it && api/.venv/bin/python -m benchmarks.scale.idle_tick --bank $S/it     # SSE idle CPU/s, edit latency
CICADA_SYNC_WATCH=off api/.venv/bin/python -m benchmarks.scale.idle_tick --bank $S/it      # the same, walking every tick
api/.venv/bin/python -m benchmarks.scale.hot_routes --bank $S/run --remote                # bytes on the wire for a client
                                                                                         # on another machine (gzip)
api/.venv/bin/python -m benchmarks.scale.recall_queries --bank $S/bank --out $S/q.jsonl   # a synthetic labeled query set
api/.venv/bin/python -m benchmarks.recall_ab --bank $S/bank --queries $S/q.jsonl --embedder hash [--hash-window 512]
```

`benchmarks.recall_ab` is not a scale probe (it does not import `isolate`): it is the side-by-side recall test for the
`entity_embed_text` setting, meant for the person's own bank with their own labeled queries and the bank's own search
model (`docs/architecture/storage.md`). With `--embedder hash` it runs on a synthetic bank as a proof of the harness.

## Model calls per conversation (2026-10-20)

`sleep_calls` counts a night's calls by stage on a ~290-page synthetic developer bank (names that share "google",
"model", a first name) and eight conversations, run on the plan (`claude -p`, haiku) one call at a time with the clock
pinned. `--replay` answers every prompt an earlier run already asked, so only what a change made new reaches the plan
and `diff` shows the change's own effect on pages, claims and questions (`docs/architecture/capture-and-sleep.md`,
*Fewer calls per conversation*):

```sh
api/.venv/bin/python -m benchmarks.scale.sleep_calls build --bank $S/bank
cp -R $S/bank $S/before && api/.venv/bin/python -m benchmarks.scale.sleep_calls run --bank $S/before --record $S/before.jsonl --live
cp -R $S/bank $S/after && api/.venv/bin/python -m benchmarks.scale.sleep_calls run --bank $S/after --replay $S/before.jsonl --record $S/after.jsonl --live
api/.venv/bin/python -m benchmarks.scale.sleep_calls diff $S/before $S/after
```
