"""The G141 demo scenario, generated fresh with `today` pinned (spec §12).

Every test that reads a project timeline builds its bank here: the on-disk
`memory/banks/demo` holds one non-synthetic capture (spec §2's flag), so no
fixture may come from it. `T` is fixed so the expected values in §12 — Q = 20,
"quiet 24 days", "1 of 4" — are literals, not arithmetic on the day the suite
ran. Every name is demo fiction and every URL is on example.com.
"""
from __future__ import annotations

import atexit
import os
import shutil
import tempfile
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
          "followups": "_write_scenario_followups", "backlog": "_write_scenario_backlog",
          "showcase": "_write_showcase"}


def d(offset: int) -> str:
    return (T + timedelta(days=offset)).isoformat()


def build(tmp_path: Path, *, index: bool = True, events: bool = True, person: bool = True,
          followups: bool = True, backlog: bool = True, showcase: bool = False, today: date | None = T) -> Path:
    """The scenario bank, generated from scratch at ``tmp_path / "demo"`` (~1–3 s of writes and git). Only a test of
    the generator itself (determinism) needs this; every other test takes :func:`demo`'s copy. ``today=None`` is
    `populate`'s own default, the real day."""
    bank = tmp_path / "demo"
    bank_registry.scaffold_bank(bank)
    wanted = {"events": events, "person": person, "followups": followups, "backlog": backlog, "showcase": showcase}
    with ExitStack() as stack:
        for flag, name in _STEPS.items():
            if not wanted[flag] and hasattr(demo_bank, name):
                stack.enter_context(mock.patch.object(demo_bank, name, lambda *a, **k: None))
        demo_bank.populate(bank, today=today)
    bank_index.invalidate()
    if index:
        search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    return bank


#: One pristine bank per set of flags, built once per test process (suite cut 1, 2026-10-19: 20 files spent ~220 s
#: building the same few banks over and over). Templates live under the suite's own tmp root and are never handed out:
#: a test gets a copy.
_TEMPLATES: dict[tuple, Path] = {}


def _template_root() -> Path:
    """A fresh dir under the suite's tmp root (`conftest.py` removes it at exit); outside the suite, its own."""
    root = os.environ.get("CICADA_SUITE_ROOT")
    if root and Path(root).is_dir():
        return Path(tempfile.mkdtemp(prefix="demo-template-", dir=root))
    made = Path(tempfile.mkdtemp(prefix="cicada-demo-template-"))
    atexit.register(shutil.rmtree, made, ignore_errors=True)
    return made


def demo(tmp_path: Path, *, index: bool = True, events: bool = True, person: bool = True,
         followups: bool = True, backlog: bool = True, showcase: bool = False, today: date | None = T) -> Path:
    """The scenario bank at ``tmp_path / "demo"``: an independent copy of a template :func:`build` made once per
    process for these flags — files, git history and (``index``) the FTS index, with their mtimes, so the index reads
    as fresh. A test may write to its copy freely. ``showcase`` (round 4 T-Demo) is OFF by default: every expectation
    the scenario tests pin was written before it, and `test_projects_app_fixture.py` proves it leaves the Projects
    wire alone; the showcase's own tests turn it on. ``today=None`` is the real day (keyed by it, so a run that
    crosses midnight builds again)."""
    key = (index, events, person, followups, backlog, showcase, today or date.today())
    template = _TEMPLATES.get(key)
    if template is None or not template.is_dir():
        template = build(_template_root(), index=index, events=events, person=person, followups=followups,
                         backlog=backlog, showcase=showcase, today=today)
        _TEMPLATES[key] = template
    bank = tmp_path / "demo"
    shutil.copytree(template, bank, symlinks=True)
    bank_index.invalidate()
    if index:
        search_index.ensure_fresh(bank, wait=True, max_age_s=0)
    return bank


def day_one(tmp_path: Path, **kw) -> Path:
    """PJ-1's bank: what every bank already holds, before any event writer ran,
    and no backlog (G150): PJ-1's expectations predate it."""
    return demo(tmp_path, events=False, person=False, followups=False, backlog=False, **kw)


def treat_as_real(monkeypatch) -> None:
    """The scenario bank comes from `demo_bank.populate`, so it carries the demo
    manifest (G141 capture-side R-CS10) and every MCP write tool refuses it
    (R-CS13). A test of a write tool's OWN behaviour on the scenario lifts that
    one refusal; the refusal itself is `test_demo_capture.py`'s to hold."""
    monkeypatch.setattr(demo_guard, "is_demo", lambda _path: False)
