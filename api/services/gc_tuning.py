"""The backend's start-up heap, frozen out of the cyclic collector once (speed 2026-10-29, owner's call on #530).

A full (generation-2) collection walks every live object. After start-up most of them are the app itself — modules,
routes, pydantic schemas, ~190k objects that live as long as the process — and one such pass landing in a request
cost it ~85 ms (measured in the bench tier, #530). ``gc.freeze()`` moves everything alive at that moment to a
permanent generation the collector never walks again; everything made later is collected exactly as before.

**Bounded memory.** It runs once per process, after a full collection, so nothing that was already garbage is kept,
and nothing created after it is ever frozen: a frozen object is never collected, so freezing again later (after the
caches fill) would pin every cache entry replaced afterwards. A start-up object freed later by its reference count is
still freed; only one kept alive solely by a cycle stays — start-up has almost none, and they are counted here.
``CICADA_GC_FREEZE=off`` leaves the collector as Python ships it (the test suite sets it).
"""
from __future__ import annotations

import gc
import os
import threading

from loguru import logger

_DONE = False
_LOCK = threading.Lock()


def enabled() -> bool:
    return os.environ.get("CICADA_GC_FREEZE", "on").strip().lower() not in ("off", "0", "false", "no")


def freeze_after_start() -> int:
    """Collect, then freeze what is alive; once per process. Returns how many objects were frozen (0 when off or
    already done)."""
    global _DONE
    if not enabled():
        return 0
    with _LOCK:
        if _DONE:
            return 0
        _DONE = True
        gc.collect()
        gc.freeze()
        frozen = gc.get_freeze_count()
    logger.info(f"gc: {frozen:,} start-up objects frozen out of the collector")
    return frozen
