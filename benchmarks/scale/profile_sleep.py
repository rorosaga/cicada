"""(c): one Sleep batch on a synthetic bank, deterministic fake engine, no network. Counts how often the batch reads,
YAML-parses, re-renders and commits the owner page, and times each stage.

    cp -R <dir>/bank <dir>/run1
    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.profile_sleep --bank <dir>/run1 [--profile out.prof]

The bank is mutated (one batch is consolidated): run it on a copy.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import isolate

BIG = 1_000_000          # a YAML stream or document this large is the owner page's fence
OWNER_NAME = "Owner Example"
FACT = re.compile(r"\b([a-z0-9]+-project) (uses) ([a-z][a-z0-9-]*)\.")


def owner_extraction(text: str) -> dict:
    """The system benchmark's grammar, plus the owner as the speaker of every fact — as a real conversation's
    first-person turns land on the owner's page (G169)."""
    entities, rels = {}, []
    for subject, predicate, obj in FACT.findall(text):
        for name, kind in ((subject, "project"), (obj, "tool")):
            entities[name] = {"name": name, "type": kind, "aliases": [], "confidence": 0.8,
                              "summary": f"{name} is discussed in synthetic conversations.",
                              "description": f"{name} is discussed in synthetic conversations.",
                              "key_facts": [f"{subject} {predicate} {obj}."], "history_entries": [],
                              "tags": ["synthetic"], "decay_class": "active"}
        rels.append({"source": subject, "target": obj, "label": predicate,
                     "evidence_quote": f"{subject} {predicate} {obj}.", "confidence": 0.8})
        for target, label in ((subject, "works-on"), (obj, "uses")):
            rels.append({"source": OWNER_NAME, "target": target, "label": label,
                         "evidence_quote": f"{subject} {predicate} {obj}.", "confidence": 0.8})
    entities[OWNER_NAME] = {"name": OWNER_NAME, "type": "person", "aliases": [], "confidence": 0.9,
                            "summary": "The person this memory belongs to.",
                            "description": "Works on several synthetic projects.",
                            "key_facts": [f"Works on {s}." for s, _, _ in FACT.findall(text)],
                            "history_entries": [], "tags": [], "decay_class": "durable"}
    return {"entities": list(entities.values()), "relationships": rels}


class Meter:
    def __init__(self):
        self.calls = collections.Counter()
        self.ms = collections.Counter()

    def wrap(self, owner, name, label, big):
        original = getattr(owner, name)

        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                key = label + (" [owner-size]" if big(args, kwargs) else "")
                self.calls[key] += 1
                self.ms[key] += (time.perf_counter() - started) * 1000
        setattr(owner, name, wrapper)
        return original


WATCH = [
    "conflict_resolver:_reconcile_related", "conflict_resolver:apply_changes", "conflict_resolver:resolve_and_prune",
    "claim_pipeline:_load_existing_claims_by_subject", "claim_pipeline:run_claim_pipeline",
    "claim_reconciler:reconcile_stage3", "claims:write_claims", "claims:parse_claims",
    "graph_builder:regenerate_edges_from_claims", "inbox_generator:_write_graph_edges",
    "inbox_generator:_update_related_fields", "wikilink_resolver:materialize_wikilink_edges",
    "hub_builder:regenerate_hubs_and_index", "owner_identity:owner_name", "state_dictionary:refresh",
    "session_stats:aggregate_conversations", "project_timeline:list_projects", "followups:propose",
    "search_index:refresh", "git_service:commit_paths_sync", "git_service:commit_touched_sync",
    "git_service:commit_changes_sync", "sleep_cycle:_mark_episodes_processed", "id_utils:build_name_index",
]


def watch(meter: Meter, specs: list[str]) -> None:
    """Time named functions in place, patching every module that imported the name too."""
    import importlib
    import inspect
    import sys
    for spec in specs:
        mod_name, fn_name = spec.split(":")
        module = importlib.import_module("api.services." + mod_name)
        original = getattr(module, fn_name)
        label = f"{mod_name}.{fn_name}"

        def make(original=original, label=label):
            if inspect.iscoroutinefunction(original):
                async def wrapper(*args, **kwargs):
                    started = time.perf_counter()
                    try:
                        return await original(*args, **kwargs)
                    finally:
                        meter.calls[label] += 1
                        meter.ms[label] += (time.perf_counter() - started) * 1000
            else:
                def wrapper(*args, **kwargs):
                    started = time.perf_counter()
                    try:
                        return original(*args, **kwargs)
                    finally:
                        meter.calls[label] += 1
                        meter.ms[label] += (time.perf_counter() - started) * 1000
            return wrapper
        wrapper = make()
        for other in list(sys.modules.values()):
            if getattr(other, "__name__", "").startswith("api.") and getattr(other, fn_name, None) is original:
                setattr(other, fn_name, wrapper)


def _size(value) -> int:
    if isinstance(value, (str, bytes)):
        return len(value)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--profile", type=Path)
    ap.add_argument("--drain", type=int, default=0,
                    help="run a drain over this many batches (decay charged in the last only, as in production)")
    ap.add_argument("--watch", nargs="*", default=[], help="extra module:function timers beside WATCH")
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)

    import subprocess
    import yaml
    from api.config import Settings
    from api.services import markdown_parser, sleep_cycle
    from benchmarks.system import engine as fake_engine
    from benchmarks.system.engine import FakeEngine
    from benchmarks.system.runtime import Runtime

    fake_engine.extraction = owner_extraction
    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank), llm_mode="local",
                        litellm_model="deterministic-v1", consolidation_model="deterministic-v1",
                        ollama_model="deterministic-v1", litellm_disambiguation_model="deterministic-v1",
                        embedding_mode="local", embedding_model_local="fake-hash-v1",
                        sleep_max_episodes_per_cycle=a.batch, link_enrich_enabled=False)
    assert settings.memory_path == bank
    owner_page = bank / "entities" / "owner-example.md"
    before = owner_page.stat().st_size

    meter = Meter()
    meter.wrap(yaml, "load", "yaml.load", lambda args, kw: _size(args[0] if args else kw.get("stream")) > BIG)
    meter.wrap(yaml, "dump", "yaml.dump",
               lambda args, kw: isinstance(args[0], list) and len(args[0]) > 1000 if args else False)
    meter.wrap(markdown_parser, "parse", "markdown_parser.parse",
               lambda args, kw: Path(args[0]).name == owner_page.name)
    meter.wrap(markdown_parser, "write", "markdown_parser.write",
               lambda args, kw: Path(args[0]).name == owner_page.name)
    meter.wrap(markdown_parser, "write_document", "markdown_parser.write_document",
               lambda args, kw: Path(args[0]).name == owner_page.name)
    original_read = Path.read_text

    def read_text(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            return original_read(self, *args, **kwargs)
        finally:
            if self.name == owner_page.name:
                meter.calls["Path.read_text [owner]"] += 1
                meter.ms["Path.read_text [owner]"] += (time.perf_counter() - started) * 1000
    Path.read_text = read_text
    meter.wrap(subprocess, "run", "subprocess.run",
               lambda args, kw: bool(args) and isinstance(args[0], (list, tuple)) and args[0][:1] == ["git"])

    import api.services  # noqa: F401 — load every module the watch list names first
    watch(meter, WATCH + a.watch)
    fake = FakeEngine()
    runtime = Runtime(datetime.now(timezone.utc), settings, fake)
    queued = len(sleep_cycle._get_unprocessed_episodes(bank))

    async def one_batch():
        if a.drain:
            ids = sorted(e["id"] for e in sleep_cycle._get_unprocessed_episodes(bank))[:a.drain * a.batch]
            await sleep_cycle.run(settings, "sleep_scale_probe", user_triggered=True, drain=True, only_ids=ids)
        else:
            await sleep_cycle.run(settings, "sleep_scale_probe", user_triggered=True, drain=False)

    with runtime:
        started = time.perf_counter()
        if a.profile:
            import cProfile
            prof = cProfile.Profile()
            prof.enable()
            asyncio.run(one_batch())
            prof.disable()
            prof.dump_stats(str(a.profile))
        else:
            asyncio.run(one_batch())
        wall = time.perf_counter() - started
    state = sleep_cycle.get_sleep_state()
    stages = collections.defaultdict(float)
    for t in runtime.timings:
        stages[t["stage"]] += t["wall_seconds"] * 1000
    out = {
        "wall_ms": round(wall * 1000), "queued_before": queued,
        "queued_after": len(sleep_cycle._get_unprocessed_episodes(bank)), "error": state.error,
        "owner_bytes_before": before, "owner_bytes_after": owner_page.stat().st_size,
        "model_calls": collections.Counter(c["stage"] for c in fake.calls),
        "stages_ms": {k: round(v) for k, v in stages.items()},
        "batches_ms": [round(t["wall_seconds"] * 1000) for t in runtime.timings if t["stage"] == "batch"],
        "counters": {k: {"calls": meter.calls[k], "ms": round(meter.ms[k])} for k in sorted(meter.calls)},
    }
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
