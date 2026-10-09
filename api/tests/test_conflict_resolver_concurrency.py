"""Stage 3's model calls overlap across pages; what it decides and writes does not change.

Stage 3 asks the engine once or twice per page a batch updates (the synthesis, then the contradiction check), and
those calls used to run one after another. Each page's calls depend only on that page's change and the pages as
read before the stage — never on another page's answer — so ``resolve_and_prune`` runs up to
``agent_max_concurrency`` pages at once and applies every result in the pages' order.

These tests pin: every written page, inbox item and change is byte-identical to the serial run at any concurrency,
with the per-call latency randomized so pages finish out of order (both synthesis settings); the bound; a plan
limit is still the exception Stage 3 raises, the earliest page's, with nothing left running and nothing started
after it; and a cancel starts no new page. Synthetic data only, no real model calls.
"""
import asyncio
import hashlib
import json
import random
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import conflict_resolver as cr
from api.services import engine_errors, inbox_generator, markdown_parser

NOW = datetime(2026, 10, 9, 12, 0, 0)
WORDS = ["alpha", "bravo", "cobalt", "delta", "ember", "fjord", "garnet", "harbor", "indigo", "juniper",
         "kelvin", "lumen", "mosaic", "nectar", "onyx", "prism"]


def _h(text: str, mod: int) -> int:
    return int(hashlib.sha1(text.encode()).hexdigest()[:8], 16) % mod


def _page_body(i: int) -> str:
    a, b = WORDS[i % len(WORDS)], WORDS[(i * 5 + 3) % len(WORDS)]
    return (f"## Summary\nA synthetic {a} {b} subject used in testing, number {i}.\n\n"
            f"## Key Facts\n- It is built from {a} parts.\n- It runs on {b} power.\n\n"
            f"## History\n- 2026-0{1 + i % 8}-1{i % 10}: First noted as {a}.\n")


def _build_bank(root: Path) -> None:
    """32 pages (one owner page, one hand-edited page, six never mentioned so decay runs) and an open conflict."""
    for name in ("entities", "episodes", "inbox"):
        (root / name).mkdir(parents=True)
    for i in range(38):
        fm = {"name": f"Page {i:02d}", "type": ["project", "tool", "concept", "person"][i % 4], "status": "active",
              "confidence": 0.3 + (i % 7) / 10, "created": "2026-01-01",
              "last_referenced": f"2026-0{1 + i % 8}-1{i % 10}", "source_episodes": [f"ep_2026-01-0{1 + i % 9}_001"],
              "tags": [WORDS[i % len(WORDS)]], "aliases": [], "related": [], "version": 1, "layout_version": 2}
        if i == 7:
            fm["human_edited"] = True
        markdown_parser.write(root / "entities" / f"page-{i:02d}.md", fm, _page_body(i))
    markdown_parser.write(root / "entities" / "owner-example.md",
                          {"name": "Owner Example", "type": "person", "owner": True, "status": "active",
                           "confidence": 0.9, "decay_class": "evergreen"},
                          "## Summary\nThe person this synthetic bank belongs to.\n")
    markdown_parser.write(root / "inbox" / "inbox-001.md",
                          {"kind": "conflict", "required_input": "choice", "status": "pending", "priority": 0.8,
                           "entity_id": "page-10", "entity_name": "Page 10", "predicate": "description",
                           "title": "Which is it?", "created_date": "2026-10-01",
                           "options": [{"key": "a", "label": "Older claim", "claim_id": None}]},
                          "An older open question about Page 10.")


def _load_existing(root: Path) -> list[dict]:
    existing = []
    for path in sorted((root / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        existing.append({"id": path.stem, "frontmatter": parsed.frontmatter, "body": parsed.body})
    return existing


def _update(i: int, variant: int, ep: str) -> dict:
    a, b = WORDS[(i + variant) % len(WORDS)], WORDS[(i * 3 + variant) % len(WORDS)]
    entity: dict = {"name": f"Page {i:02d}", "type": ["project", "tool", "concept", "person"][i % 4]}
    kind = (i + variant) % 6
    if kind == 0:
        entity.update(summary=f"A {a} subject that now runs on {b} power.", key_facts=[f"It ships with {a} {b}."],
                      history_entries=[{"date": "2026-10-02", "event": f"Moved to {b}."}])
    elif kind == 1:
        entity.update(key_facts=[f"It was rated {a}.", f"It is stored in {b}."])
    elif kind == 2:
        entity.update(description=f"The {a} subject, described again.",
                      history_entries=[{"date": "2026-10-03", "event": f"Reviewed {a}."}])
    elif kind == 3:
        entity.update(summary=f"A synthetic {WORDS[i % len(WORDS)]} {WORDS[(i * 5 + 3) % len(WORDS)]} subject "
                              f"used in testing, number {i}.")
        ep = f"ep_2026-01-0{1 + i % 9}_001"  # a re-read of a conversation the page already credits
    elif kind == 4:
        entity.update(summary=f"It is no longer {a}; it is {b} now.", description=f"It is {b} now.")
    else:
        entity.update(links=[{"url": f"https://example.invalid/{a}", "title": f"{a} notes"}], open_questions=[f"Will it move to {b}?"])
    return {"id": f"page-{i:02d}", "action": "update", "entity": entity, "source_episode": ep,
            "source_episodes": [ep], "source_episode_timestamp": f"2026-10-0{1 + i % 8}T12:00:00Z",
            "source_episode_timestamps": [f"2026-10-0{1 + i % 8}T12:00:00Z"], "trigger": "sleep/resolve"}


def _batch() -> list[dict]:
    """30 updates of every shape, two pages touched twice, one page that is gone, two creates."""
    changes = [_update(i, 0, f"ep_2026-10-0{1 + i % 8}_00{i % 3}") for i in range(30)]
    changes += [_update(4, 4, "ep_2026-10-08_009"), _update(10, 1, "ep_2026-10-08_008"),
                _update(10, 4, "ep_2026-10-08_007")]
    changes.append({"id": "ghost-page", "action": "update", "entity": {"name": "Ghost", "summary": "Gone."},
                    "source_episode": "ep_2026-10-08_001"})
    for n in range(2):
        changes.append({"id": f"fresh-{n}", "action": "create",
                        "entity": {"name": f"Fresh {n}", "type": "concept", "summary": f"A new thing {n}.",
                                   "key_facts": [f"Fact {n}."]},
                        "source_episode": "ep_2026-10-08_002", "source_episodes": ["ep_2026-10-08_002"],
                        "source_episode_timestamp": "2026-10-08T09:00:00Z",
                        "source_episode_timestamps": ["2026-10-08T09:00:00Z"]})
    return changes


class _Engine:
    """A fake engine: each answer is a function of the prompt alone; the latency is random per call."""

    def __init__(self, seed: int, *, delay: float = 0.004, fail=None):
        self.rng = random.Random(seed)
        self.delay = delay
        self.fail = fail  # fail(prompt, n) -> an exception to raise, or None
        self.prompts: list[str] = []
        self.inflight = 0
        self.peak = 0
        self.closed = False

    async def __call__(self, **kwargs):
        assert not self.closed, "a call started after Stage 3 returned"
        prompt = kwargs["messages"][-1]["content"]
        self.prompts.append(prompt)
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        try:
            await asyncio.sleep(self.rng.random() * self.delay)
            if self.fail is not None:
                exc = self.fail(prompt, len(self.prompts))
                if exc is not None:
                    raise exc
        finally:
            self.inflight -= 1
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._answer(prompt)))])

    @staticmethod
    def _answer(prompt: str) -> str:
        roll = _h(prompt, 12)
        if roll == 11:
            raise ValueError("synthetic unreadable answer")  # a non-engine failure: logged, the page goes on
        if "checking whether two descriptions" in prompt:
            if roll % 3:
                return json.dumps({"has_unresolvable_contradiction": False, "contradiction": "", "question": "",
                                   "options": []})
            return json.dumps({"has_unresolvable_contradiction": True,
                               "contradiction": f"Two states, variant {roll}.",
                               "question": f"Which state holds, variant {roll}?",
                               "options": [{"label": f"State {roll}a", "description": "From the page."},
                                           {"label": f"State {roll}b", "description": "From the new conversation."}]})
        if "SECTION-AWARE ORIENTATION" in prompt:
            return json.dumps({"summary": f"A synthetic subject in its variant {roll} form.",
                               "restated": [0] if roll % 4 == 0 else [], "covered": []})
        return (f"## Summary\nA synthetic subject, rewritten as variant {roll}.\n\n"
                f"## History\n- 2026-10-0{1 + roll % 8}: Rewrite note {roll}.\n")


def _settings(synthesis: bool, concurrency: int) -> Settings:
    return Settings(_env_file=None, summary_synthesis_enabled=synthesis, agent_max_concurrency=concurrency)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _run_stage3_and_write(template: Path, work: Path, monkeypatch, *, synthesis: bool, concurrency: int, seed: int):
    """Stage 3 over a fresh copy of the bank, then Stage 5's page and inbox writes from its changes."""
    shutil.copytree(template, work)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(work))
    engine = _Engine(seed)
    monkeypatch.setattr(cr.litellm, "acompletion", engine)
    progress: list[tuple[int, int]] = []
    changes = asyncio.run(cr.resolve_and_prune(_batch(), _load_existing(work), _settings(synthesis, concurrency),
                                               now=NOW, tuning={}, progress_callback=lambda d, t: progress.append((d, t))))
    engine.closed = True
    inbox_generator._generate_sync(changes, [], work, relationships=[])
    return json.dumps(changes, sort_keys=True, default=str), _snapshot(work), engine, progress


@pytest.mark.parametrize("synthesis", [False, True], ids=["legacy-synthesis", "section-aware-synthesis"])
def test_overlapped_stage3_writes_exactly_what_the_serial_stage_writes(tmp_path, monkeypatch, synthesis):
    template = tmp_path / "template"
    _build_bank(template)
    serial_changes, serial_files, serial_engine, serial_progress = _run_stage3_and_write(
        template, tmp_path / "serial", monkeypatch, synthesis=synthesis, concurrency=1, seed=1)
    assert serial_engine.peak == 1
    # The synthetic batch must reach every branch: conflicts filed (one merged into the open item), rewrites
    # applied, failed answers survived, and every page of the bank touched by Stage 5.
    assert any(c["action"] == "conflict_nudge" for c in json.loads(serial_changes))
    assert any(c.get("synthesized_body") for c in json.loads(serial_changes))
    assert any(_h(p, 12) == 11 for p in serial_engine.prompts)
    assert len([k for k in serial_files if k.startswith("inbox/")]) >= 3
    assert serial_files != _snapshot(template)

    for concurrency in (2, 3, 5, 10):
        for seed in (2, 3):
            changes, files, engine, progress = _run_stage3_and_write(
                template, tmp_path / f"c{concurrency}-s{seed}", monkeypatch,
                synthesis=synthesis, concurrency=concurrency, seed=concurrency * 100 + seed)
            assert 1 < engine.peak <= concurrency
            assert sorted(engine.prompts) == sorted(serial_engine.prompts), "the same calls, not just the outcome"
            assert changes == serial_changes
            assert files.keys() == serial_files.keys()
            for path, data in serial_files.items():
                assert files[path] == data, f"{path} differs at concurrency {concurrency}"
            done = [d for d, _ in progress]
            assert done == sorted(done) and progress[-1][0] == progress[-1][1] == serial_progress[-1][1]


def _template(tmp_path) -> Path:
    template = tmp_path / "template"
    _build_bank(template)
    return template


def _stage3(bank: Path, monkeypatch, engine: _Engine, concurrency: int, cancel_check=None):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    monkeypatch.setattr(cr.litellm, "acompletion", engine)
    try:
        return asyncio.run(cr.resolve_and_prune(_batch(), _load_existing(bank), _settings(True, concurrency),
                                                now=NOW, tuning={}, cancel_check=cancel_check))
    finally:
        engine.closed = True


def test_a_plan_limit_is_still_raised_and_nothing_runs_or_starts_after_it(tmp_path, monkeypatch):
    bank = _template(tmp_path)
    before = _snapshot(bank)
    full = _Engine(7)
    _stage3(bank, monkeypatch, full, 4)

    engine = _Engine(8, fail=lambda prompt, n: engine_errors.EngineThrottled("synthetic plan limit") if n == 6 else None)
    with pytest.raises(engine_errors.EngineThrottled):
        _stage3(bank, monkeypatch, engine, 4)
    # Only the pages already in flight when the limit came back finish their calls; no page starts after it.
    assert len(engine.prompts) <= 6 + 2 * 4 < len(full.prompts)
    assert engine.inflight == 0, "no call is left running behind the pause"
    assert _snapshot(bank) == before, "Stage 3 writes nothing"


def test_the_earliest_pages_engine_error_is_the_one_raised(tmp_path, monkeypatch):
    """The serial loop met the first failing page's error first; a later page failing sooner does not replace it."""
    bank = _template(tmp_path)
    order: list[str] = []

    def fail(prompt, n):
        if n == 1:
            order.append("first page")
            return engine_errors.EngineThrottled("synthetic plan limit on the first page")
        if n in (2, 3):
            order.append("later page")
            return engine_errors.EngineUnavailable("synthetic outage on a later page")
        return None

    class _SlowFirst(_Engine):
        async def __call__(self, **kwargs):
            if not self.prompts:  # the first page's call comes back last
                self.prompts.append(kwargs["messages"][-1]["content"])
                self.inflight += 1
                self.peak = max(self.peak, self.inflight)
                try:
                    await asyncio.sleep(0.05)
                    raise fail("", 1)
                finally:
                    self.inflight -= 1
            return await super().__call__(**kwargs)

    engine = _SlowFirst(9, fail=fail)
    with pytest.raises(engine_errors.EngineThrottled):
        _stage3(bank, monkeypatch, engine, 3)
    assert order[0] == "later page", "the later page's error came back first"
    assert engine.inflight == 0


def test_concurrency_is_bounded_and_one_is_the_serial_loop(tmp_path, monkeypatch):
    bank = _template(tmp_path)
    serial = _Engine(10)
    _stage3(bank, monkeypatch, serial, 1)
    assert serial.peak == 1
    three = _Engine(11)
    _stage3(bank, monkeypatch, three, 3)
    assert 2 <= three.peak <= 3


def test_a_cancel_starts_no_new_page_and_waits_out_the_ones_in_flight(tmp_path, monkeypatch):
    bank = _template(tmp_path)
    full = _Engine(12)
    _stage3(bank, monkeypatch, full, 3)
    engine = _Engine(13)
    seen_at_cancel: list[int] = []

    def cancel_after_some_pages():
        if len(engine.prompts) >= 4:
            if not seen_at_cancel:
                seen_at_cancel.append(len(engine.prompts))
            return True
        return False

    _stage3(bank, monkeypatch, engine, 3, cancel_check=cancel_after_some_pages)
    # Each page in flight at the cancel may still make its second call; no new page starts.
    assert len(engine.prompts) <= seen_at_cancel[0] + 3 < len(full.prompts)
    assert engine.inflight == 0
