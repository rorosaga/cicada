"""One way to hold a bench budget (speed 2026-10-29, review of #518).

A budget is the code's cost, so it is held in CPU time (``time.process_time``: every thread of this process, never the
time spent waiting for a core) — a wall clock failed the bench tier whenever the Mac ran 30–55 other processes. CPU
time alone would pass a path that WAITS (a subprocess, a lock, a disk read, a sleep), so the wall clock is held too,
under :data:`WALL_FACTOR` times the same budget: loose enough for a loaded machine, tight enough that a new wait shows.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

WALL_FACTOR = 4


@dataclass
class Samples:
    cpu: list[float]
    wall: list[float]

    def p95(self, xs: list[float]) -> float:
        if len(xs) >= 20:
            return statistics.quantiles(xs, n=20)[18]
        return sorted(xs)[int(0.95 * (len(xs) - 1))]

    @property
    def cpu_p95(self) -> float:
        return self.p95(self.cpu)

    @property
    def wall_p95(self) -> float:
        return self.p95(self.wall)

    @property
    def cpu_min(self) -> float:
        return min(self.cpu)

    @property
    def wall_min(self) -> float:
        return min(self.wall)


def measure(fn, runs: int = 20, *, warm: bool = True) -> Samples:
    """``fn`` run ``runs`` times (once first, untimed, when ``warm``), each run's CPU and wall seconds."""
    if warm:
        fn()
    cpu, wall = [], []
    for _ in range(runs):
        c, w = time.process_time(), time.perf_counter()
        fn()
        cpu.append(time.process_time() - c)
        wall.append(time.perf_counter() - w)
    return Samples(cpu, wall)


def within(cpu_s: float, wall_s: float, budget_s: float, label: str = "") -> None:
    """``cpu_s`` under the budget, and ``wall_s`` under :data:`WALL_FACTOR` × the budget."""
    what = f"{label}: " if label else ""
    assert cpu_s <= budget_s, f"{what}CPU {cpu_s * 1000:.1f} ms over the {budget_s * 1000:.0f} ms budget"
    assert wall_s <= WALL_FACTOR * budget_s, (
        f"{what}wall {wall_s * 1000:.1f} ms over {WALL_FACTOR}× the {budget_s * 1000:.0f} ms budget: a wait, not work")


class Timer:
    """``with Timer() as t: ...`` — then ``t.cpu`` and ``t.wall`` seconds, for a loop that times one step of several."""

    def __enter__(self):
        self._c, self._w = time.process_time(), time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.cpu, self.wall = time.process_time() - self._c, time.perf_counter() - self._w
        return False
