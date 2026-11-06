"""Keep the Mac awake while a Sleep run reads, on power (G243; the person's switch, off by default).

The one thing that needs no root: a power assertion. ``caffeinate -i -s -w <backend pid>`` asks macOS not to sleep
the system on idle (``-i``) and not to sleep it at all **while it runs on AC power** (``-s``, which macOS itself
ignores on battery). ``-w`` ties the assertion to this process, so a crash or a kill of the backend drops it with the
process — there is no system setting to put back, which is the rail ("never strand a run, never strand the Mac").

What it does not do, said in words wherever it is offered: it does not wake a sleeping Mac, and it does not keep a
closed lid awake (macOS sleeps on lid close without an external display whatever an assertion says). Those need root
(``pmset``) and are a separate, un-built step (``docs/goals/``, G243).

One holder per run id; ``release`` is idempotent; every failure to hold is a log line, never a failed run.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)

_CAFFEINATE = "caffeinate"
_held: dict[str, subprocess.Popen] = {}


def available() -> bool:
    return sys.platform == "darwin" and shutil.which(_CAFFEINATE) is not None


def acquire(run_id: str) -> bool:
    """Hold the assertion for ``run_id``. True when one is held now (already or newly); False when it cannot be."""
    held = _held.get(run_id)
    if held is not None and held.poll() is None:
        return True
    if not available():
        return False
    try:
        proc = subprocess.Popen(
            [shutil.which(_CAFFEINATE), "-i", "-s", "-w", str(os.getpid())],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as e:  # noqa: BLE001
        logger.warning("keep-awake: could not start %s (%s)", _CAFFEINATE, type(e).__name__)
        return False
    _held[run_id] = proc
    return True


def release(run_id: str) -> None:
    proc = _held.pop(run_id, None)
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=2)
    except Exception:  # noqa: BLE001 — -w still drops it with this process
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def holding(run_id: str | None = None) -> bool:
    if run_id is not None:
        proc = _held.get(run_id)
        return proc is not None and proc.poll() is None
    return any(p.poll() is None for p in _held.values())
