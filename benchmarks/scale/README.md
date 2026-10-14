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

- `synth` builds the bank: one owner page with N claims, rewritten by `--commits` synthetic Sleep commits; 2,000 other
  pages with a Pareto tail of claims; 1,500 staged episodes, 975 of them processed.
- `profile_sleep` runs one `sleep_cycle.run` batch through the system benchmark's fake engine. The probe's grammar also
  makes the owner the speaker of every fact, so every batch writes to the owner page. It reports per-stage wall time,
  owner-sized YAML loads/dumps, and timers for the functions listed in `WATCH`. It mutates the bank, so run it on a
  copy. The first batch on a fresh synthetic bank also charges decay on every page and builds the indexes cold, so read
  batch 2 onward.
