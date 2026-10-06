# Whole-system benchmark (G148)

Supported entry point: `python -m benchmarks.system.runner`. This runner never
imports `benchmarks/_bootstrap.py`. The other scripts in `benchmarks/` and their
historical scores are **legacy**: retrieval/static experiments, not whole-system
acceptance evidence.

The small preset covers synthetic scenarios 1, 2, 4 and 5. Offline fake-engine
results establish deterministic pipeline integrity, not generative quality or
real embedding performance. Scenario 3 (multiple sources), scenario 6 (scale),
LoCoMo loading, LongMemEval and the actual subscription pilot remain out of scope.

```sh
api/.venv/bin/python -m benchmarks.system.runner \
  --bank-dir temp --home temp --config benchmarks/system/small.json \
  --clock 2026-10-06T12:00:00+00:00 --model deterministic-v1 --effort low \
  --preset small --engine fake --validate-only
```

`temp` creates a fresh directory and writes an ownership marker. Reuse requires
that exact `_bench.yaml` / `_bench_home.yaml` marker; symlinks and overlapping
bank/home paths are refused before importing Cicada. Config, expected answers
and result artifacts live outside banks. The child has an allowlisted environment,
isolated HOME/CICADA_HOME, capture/fetch/telemetry off, provider keys absent and
dotenv disabled. No API fallback is permitted.

The worker will document executable scenario commands and measurement details
alongside the end-to-end implementation. No subscription run is authorized by
this document.
