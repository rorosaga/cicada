"""Cicada thesis benchmark harness.

Three runnable entry points, one shared scaffold:

- ``benchmarks.run_table1`` — three-condition recall evaluation (Table 1).
- ``benchmarks.run_table3`` — operational measurements on the live memory dir
  plus optional fresh-workspace sleep-cycle timing (Table 3).
- ``benchmarks.run_ablation`` — threshold sweeps over fresh workspaces (Table 2).

All runners write JSON plus human-readable CSV into ``benchmark_results/``.
None of them mutate the live ``memory/`` directory — any sleep cycle runs
happen inside a throwaway temp workspace seeded from ``memory/episodes``.
"""
