"""Speed 2026-10-29: the backend freezes its start-up heap out of the cyclic collector once, after a collection."""
from __future__ import annotations

import gc

from api.services import gc_tuning


def test_it_freezes_once_after_a_collection_and_never_again(monkeypatch):
    monkeypatch.setenv("CICADA_GC_FREEZE", "on")
    monkeypatch.setattr(gc_tuning, "_DONE", False)
    collected = []
    real = gc.collect
    monkeypatch.setattr(gc, "collect", lambda *a: collected.append(1) or real(*a))
    try:
        frozen = gc_tuning.freeze_after_start()
        assert frozen > 0 and gc.get_freeze_count() > 0 and collected == [1]
        assert gc_tuning.freeze_after_start() == 0, "once per process: a later freeze would pin replaced caches"
    finally:
        gc.unfreeze()


def test_off_leaves_the_collector_alone(monkeypatch):
    monkeypatch.setenv("CICADA_GC_FREEZE", "off")
    monkeypatch.setattr(gc_tuning, "_DONE", False)
    assert gc_tuning.freeze_after_start() == 0 and gc.get_freeze_count() == 0
