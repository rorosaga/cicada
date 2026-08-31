---
name: thesis-benchmarks
description: Use when running or modifying Cicada's thesis benchmarks (Tables 1-3, the ablation sweep, or the sqlite-vec index rebuild) — the runbook, the fresh-workspace rails, and the personal-data privacy pattern for questions/queries files.
---

# Thesis benchmarks runbook

Benchmark tooling for the Results chapter lives in `benchmarks/`. The canonical runbook is
[`benchmarks/README.md`](../../../benchmarks/README.md); this skill is the agent-facing summary.

## The four scripts

- `benchmarks.rebuild_leann` — one-shot index rebuild. **Historical name**: the index is sqlite-vec
  now, and this script still imports the deleted `api.services.leann_indexer`, so treat it as a
  LEANN-era artifact pending a port, not a working script.
- `benchmarks.run_table1` — three-condition recall eval (Cicada full vs episodes-index-only vs a
  manual commercial baseline). Writes JSONL + a scoring-sheet CSV; scoring is manual against the
  four-dimensional rubric in `sections/experiments.tex`.
- `benchmarks.run_table3` — operational measurements: static counts, disk sizes, recall latency
  (median/p95), and optional `--sleep-cycle-time` for fresh-workspace wall clock.
- `benchmarks.run_ablation` — Table 2 threshold sweep; one fresh sleep cycle per config in
  throwaway `/tmp/cicada_bench_table2_*` workspaces.

## Running them

```sh
cp benchmarks/questions.example.yaml benchmarks/questions.local.yaml
cp benchmarks/queries.example.txt     benchmarks/queries.local.txt
# fill the .local files with real content — they are gitignored

api/.venv/bin/python -m benchmarks.run_table1 \
    --questions benchmarks/questions.local.yaml --memory memory --out benchmark_results/table1

api/.venv/bin/python -m benchmarks.run_table3 \
    --memory memory --queries benchmarks/queries.local.txt --out benchmark_results/table3
```

`api/.env` is auto-loaded into `os.environ` by `benchmarks/_bootstrap.py`; shell exports still win.

## Rails that are not obvious from the code

- No runner mutates the live `memory/` directory — sleep-cycle runs happen inside
  `/tmp/cicada_bench_*` workspaces seeded from `memory/episodes`.
- `workspace.destroy_workspace` refuses to delete any path whose name lacks `cicada_bench_`.
- **The personal-data privacy pattern is in the root `CLAUDE.md` and is binding** — never put real
  names, projects, or organizations in the committed `*.example.*` templates, never add files under
  `benchmarks/` with real content unless they use the `*.local.*` suffix, and never move a
  `run_table1` scoring sheet (which contains retrieved context verbatim) out of the gitignored
  `benchmark_results/`.
