"""G243: a run holds a no-root power assertion only when the person's switch is on, and always lets it go."""
from __future__ import annotations

import sys

import pytest

from api.services import keep_awake, sleep_run_prefs


class _Reg:
    def __init__(self):
        self.p = {}

    def prefs(self):
        return self.p

    def set_pref(self, key, field, value):
        e = self.p.setdefault(key, {})
        if value is None:
            e.pop(field, None)
        else:
            e[field] = value


def test_off_by_default_and_only_an_explicit_true_turns_it_on():
    reg = _Reg()
    assert sleep_run_prefs.load(reg).keep_awake is False
    reg.p["sleep-run"] = {"keep_awake": "yes"}
    assert sleep_run_prefs.load(reg).keep_awake is False
    sleep_run_prefs.write(reg, keep_awake=True)
    assert sleep_run_prefs.load(reg).keep_awake is True
    sleep_run_prefs.write(reg, keep_awake=False)
    assert sleep_run_prefs.load(reg).keep_awake is False


@pytest.mark.skipif(not keep_awake.available(), reason="needs macOS caffeinate")
def test_acquire_holds_and_release_lets_go():
    assert keep_awake.acquire("t1") and keep_awake.holding("t1")
    assert keep_awake.acquire("t1"), "idempotent"
    keep_awake.release("t1")
    assert not keep_awake.holding("t1")
    keep_awake.release("t1")  # twice is fine


def test_an_unavailable_tool_is_a_false_never_a_raise(monkeypatch):
    monkeypatch.setattr(keep_awake, "available", lambda: False)
    assert keep_awake.acquire("t2") is False
    assert not keep_awake.holding()
