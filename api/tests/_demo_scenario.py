"""The G141 demo scenario, generated fresh with `today` pinned (spec §12).

Every test that reads a project timeline builds its bank here: the on-disk
`memory/banks/demo` holds one non-synthetic capture (spec §2's flag), so no
fixture may come from it. `T` is fixed so the expected values in §12 — Q = 20,
"quiet 24 days", "1 of 4" — are literals, not arithmetic on the day the suite
ran. Every name is demo fiction and every URL is on example.com.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from api.services import bank_index, bank_registry, demo_bank, demo_guard, search_index

T = date(2026, 9, 23)
TZ = "UTC"
# The later slices' demo steps (T5 events, T6 the person's moves, T7 one
# follow-up). A test that pins "day one" turns them off, so a later task never
# rewrites an earlier task's expectations; a step that does not exist yet is
# simply not patched.
_STEPS = {"events": "_write_scenario_events", "person": "_write_scenario_person",
          "followups": "_write_scenario_followups"}


def d(offset: int) -> str:
    return (T + timedelta(days=offset)).isoformat()


def demo(tmp_path: Path, *, index: bool = True, events: bool = True, person: bool = True,
         followups: bool = True) -> Path:
    bank = tmp_path / "demo"
    bank_registry.scaffold_bank(bank)
    wanted = {"events": events, "person": person, "followups": followups}
    with ExitStack() as stack:
        for flag, name in _STEPS.items():
            if not wanted[flag] and hasattr(demo_bank, name):
                stack.enter_context(mock.patch.object(demo_bank, name, lambda *a, **k: None))
        demo_bank.populate(bank, today=T)
    bank_index.invalidate()
    if index:
        search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    return bank


def day_one(tmp_path: Path, **kw) -> Path:
    """PJ-1's bank: what every bank already holds, before any event writer ran."""
    return demo(tmp_path, events=False, person=False, followups=False, **kw)


def treat_as_real(monkeypatch) -> None:
    """The scenario bank comes from `demo_bank.populate`, so it carries the demo
    manifest (G141 capture-side R-CS10) and every MCP write tool refuses it
    (R-CS13). A test of a write tool's OWN behaviour on the scenario lifts that
    one refusal; the refusal itself is `test_demo_capture.py`'s to hold."""
    monkeypatch.setattr(demo_guard, "is_demo", lambda _path: False)
