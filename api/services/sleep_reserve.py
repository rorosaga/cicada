"""Leave room in my plan — the reserve, a soft stop (Sleep page v5, owner 2026-09-30).

A person on a plan engine can set a line, 5 to 30 percent of a plan window. A run
that reaches it pauses ("Paused to leave room in your plan.") instead of running
the window dry. It is **off by default** and it is a *line, not a guarantee*:

* It is a **soft stop**, not a tripped breaker. A tripped breaker mid-batch makes
  Stage 2's first judge call raise and throws the whole batch away. A soft stop
  keeps it: Stage 1 stops *starting* new reads, the conversations already read go
  through Stages 2 to 5 and are filed, the rest stay queued.
* The reads already running, and Stages 2 to 5 for what was read, finish — so a
  window can end past the line. Overshoot is not measured and no copy quotes one.
* A window is enforced only if the engine reports it. Claude reports a window's
  use after each call; the ChatGPT plan is read from the read-only app-server
  snapshot the batch's pre-flight already takes (one read per batch, never a second
  probe). A window that is never reported cannot be enforced, and the wire says so
  (``enforced: false, reason: not_reported``) rather than promise it.

Off means no reserve figure is set. The Claude rung then keeps its own R-E12 stop at
90 percent of the 5-hour window, which predates this and stays. Once a reserve is
set that stop is lifted for the run (``agent_stop_utilization`` 1.0), or a 5 percent
line would be pre-empted by the 90 percent one.
"""
from __future__ import annotations

import threading
import time

#: Claude reports these windows on its rate-limit signals; the others are per-model caps.
CLAUDE_WINDOWS = ("five_hour", "seven_day")

SENTENCE = "Paused to leave room in your plan."


def limit_kind(window: str | None) -> str:
    w = (window or "").lower()
    if w == "five_hour":
        return "five_hour"
    if w in ("seven_day", "weekly"):
        return "seven_day"
    return "unknown"   # the ChatGPT plan's `primary` / `secondary` are not assumed to be 5-hour / weekly


class ReserveGuard:
    """Watches every window the engine reports against ``1 - pct/100``."""

    def __init__(self, pct: int, *, engine: str | None = None):
        self.pct = int(pct)
        self.engine = engine
        self.line = 1.0 - self.pct / 100.0
        self.windows: dict[str, dict] = {}
        self.reached: tuple[str, int | None] | None = None
        self.calls_seen = 0
        self._lock = threading.Lock()

    # --- observations ------------------------------------------------------
    def _observe(self, window: str, utilization: float, resets_at: int | None) -> None:
        with self._lock:
            self.windows[window] = {"utilization": float(utilization), "resets_at": resets_at}
            if self.reached is None and utilization >= self.line:
                if resets_at is None or resets_at > time.time():
                    self.reached = (window, resets_at)

    def observe_signals(self, signals) -> None:
        """One Claude call's rate-limit signals. Never raises."""
        try:
            with self._lock:
                self.calls_seen += 1
            for sig in signals or ():
                name = getattr(sig, "limit_type", None)
                u = getattr(sig, "utilization", None)
                if name in CLAUDE_WINDOWS and u is not None:
                    self._observe(name, u, getattr(sig, "resets_at", None))
        except Exception:  # pragma: no cover - defensive
            return

    def observe_snapshot(self, snap) -> None:
        """The ChatGPT plan's per-window snapshot (``(name, used_percent, resets_at)``)."""
        try:
            for name, pct, at in getattr(snap, "windows", ()) or ():
                self._observe(str(name), pct / 100.0, at)
        except Exception:  # pragma: no cover - defensive
            return

    def seed_last_known(self, window: str, used_fraction: float | None, resets_at: int | None) -> None:
        """The newest recorded cycle's window (the ledger), so a Continue into a
        window that is still full pauses at once without a paid call."""
        if used_fraction is not None and window in CLAUDE_WINDOWS and (resets_at or 0) > time.time():
            self._observe(window, used_fraction, resets_at)

    # --- reads -------------------------------------------------------------
    def is_reached(self) -> bool:
        return self.reached is not None

    def stop_values(self) -> tuple[int | None, str]:
        """``(resets_at, limit kind)`` of the window that reached the line."""
        window, resets = self.reached or ("", None)
        return resets, limit_kind(window)

    def wire(self) -> dict:
        """Which windows are enforced. ``enforced`` is ``true`` only after the engine
        reported that window, ``false`` for a window that should have been reported
        and was not, and ``null`` before anything could tell."""
        wins: list[dict] = []
        if self.engine == "codex-cli":
            for name, w in sorted(self.windows.items()):
                wins.append({"window": name, "enforced": True})
            if not self.windows:
                wins.append({"window": "primary", "enforced": None})
        else:
            for name in CLAUDE_WINDOWS:
                if name in self.windows:
                    wins.append({"window": name, "enforced": True})
                elif self.calls_seen:
                    wins.append({"window": name, "enforced": False, "reason": "not_reported"})
                else:
                    wins.append({"window": name, "enforced": None})
        return {"pct": self.pct, "windows": wins}
