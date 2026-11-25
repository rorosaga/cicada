"""Where a stuck backend is stuck (2026-11-25, after a night the event loop spun at 100% CPU for thirteen minutes).

A native sampler shows only the interpreter's own C frames, and nothing may attach a debugger to a person's backend.
So the process answers one signal itself: ``kill -USR1 <pid>`` writes every thread's Python stack (file, line and
function names; never a value, a local or a message) to the backend's own error log, with no effect on what it is
doing. ``faulthandler`` writes from the signal handler in C, so it works while the event loop is blocked, which is
exactly when it is needed. It also covers a fatal error (a crash leaves its stacks in the same log).

Nothing leaves the machine and nothing is written into a bank. Never raises: a platform without the signal, or a
stream with no file descriptor (a test runner's capture), installs nothing.
"""
from __future__ import annotations

import faulthandler
import signal
import sys

from loguru import logger

#: The signal that asks for the stacks. ``None`` where the platform has none (Windows).
SIGNAL = getattr(signal, "SIGUSR1", None)
_INSTALLED = False


def install(stream=None) -> bool:
    """Register the dump once per process. True when a later ``kill -USR1`` will write the stacks."""
    global _INSTALLED
    if _INSTALLED:
        return True
    out = stream if stream is not None else sys.stderr
    try:
        out.fileno()
    except Exception:  # noqa: BLE001 - no real stream to write to from a signal handler
        return False
    try:
        faulthandler.enable(file=out, all_threads=True)
        if SIGNAL is None:
            return False
        faulthandler.register(SIGNAL, file=out, all_threads=True, chain=False)
    except Exception as exc:  # noqa: BLE001 - a diagnostic aid never stops the backend starting
        logger.debug(f"stack dump: not installed ({type(exc).__name__})")
        return False
    _INSTALLED = True
    return True


def uninstall() -> None:
    """For tests: leave the process as it was."""
    global _INSTALLED
    if SIGNAL is not None:
        try:
            faulthandler.unregister(SIGNAL)
        except Exception:  # noqa: BLE001
            pass
    _INSTALLED = False
