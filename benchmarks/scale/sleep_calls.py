"""How many model calls one Sleep night makes, by stage, on a realistic synthetic bank — and what the same night
writes, so a change that removes calls can be checked against the pages, claims and questions it produces.

    S=<scratch>; export SCALE_SCRATCH=$S
    api/.venv/bin/python -m benchmarks.scale.sleep_calls build --bank $S/bank
    cp -R $S/bank $S/before && api/.venv/bin/python -m benchmarks.scale.sleep_calls run --bank $S/before \
        --record $S/before.jsonl --live                      # every call to the plan (claude -p, haiku)
    cp -R $S/bank $S/after && api/.venv/bin/python -m benchmarks.scale.sleep_calls run --bank $S/after \
        --replay $S/before.jsonl --record $S/after.jsonl --live   # a prompt asked before is answered as it was
    api/.venv/bin/python -m benchmarks.scale.sleep_calls diff $S/before $S/after

``build`` writes `sleep_calls_data`'s ~270 pages and eight conversations (no call). ``run`` reads them in one drain
on the plan engine (`llm_mode=agent`, haiku for every stage, one call at a time, articles and summary synthesis on
— the owner's settings), with the clock pinned, so every prompt that does not depend on the change is byte-identical
between two runs. ``--replay`` answers such a prompt from an earlier run's record; only a prompt the change made new
reaches the plan, and the diff of the two banks is the change's own effect, not a model's run-to-run variance.
Without ``--live`` a prompt missing from the replay file fails the run (a dry check costs nothing).

The plan call runs the production argv (`agent_engine.build_argv`) with the developer's HOME for the CLI's sign-in
only and `CICADA_CAPTURE=off`; everything else stays in the scratch home (`isolate`).
"""
from __future__ import annotations

import os

_REAL_HOME = os.environ.get("HOME", "")

from . import isolate  # noqa: E402 — pins the scratch roots before any api import

import argparse  # noqa: E402
import asyncio  # noqa: E402
import collections  # noqa: E402
import hashlib  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from .sleep_calls_data import CONVERSATIONS, OWNER, PAGES  # noqa: E402

CLOCK = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
OLD_DAYS = ["2026-08-04", "2026-08-19", "2026-09-02", "2026-09-16", "2026-09-30", "2026-10-07"]


def _slug(name: str) -> str:
    from api.services.id_utils import sanitize_id
    return sanitize_id(name)


def build(bank: Path) -> None:
    """The bank before the night: every page on one or two older conversations, the night's eight waiting."""
    from api.services import bank_registry, decay_policy, entity_body, episode_ids, markdown_parser, owner_identity

    if bank.exists() and any(bank.iterdir()):
        raise SystemExit(f"{bank} is not empty")
    bank_registry.scaffold_bank(bank)
    episodes = bank / "episodes"
    old_ids = []
    for i, day in enumerate(OLD_DAYS):
        ep_id = episode_ids.next_episode_id(episodes, day)
        fm = {"id": ep_id, "timestamp": f"{day}T10:00:00+00:00", "processed": True, "processed_by": "sleep",
              "origin": "claude-code", "title": f"Earlier notes {i + 1}"}
        markdown_parser.write(episodes / f"{ep_id}.md", fm,
                              f"user: Earlier working notes, part {i + 1}.\n\nassistant: Noted.")
        old_ids.append((ep_id, day))
    rows = [line.split("|") for line in PAGES.strip().splitlines()]
    for n, (kind, name, summary, facts) in enumerate(rows):
        sources = [old_ids[n % len(old_ids)]] + ([old_ids[(n + 3) % len(old_ids)]] if n % 2 == 0 else [])
        sources.sort(key=lambda s: s[1])
        fm = {"name": name, "type": kind, "status": "active", "confidence": 0.7,
              "created": sources[0][1], "last_referenced": sources[-1][1],
              **decay_policy.frontmatter_fields(decay_policy.default_class_for(kind)),
              "source_episodes": [s[0] for s in sources], "tags": [], "aliases": [], "related": [],
              "version": 1, "layout_version": 2}
        body = entity_body.compose_body_v2(
            summary=summary, key_facts=[f.strip() for f in facts.split(";") if f.strip()], history_entries=[],
            related=[], links=[], open_questions=[], name=name, entity_type=kind)
        markdown_parser.write(bank / "entities" / f"{_slug(name)}.md", fm, body)
    owner_identity.ensure_owner_entity(bank, OWNER)
    for hour, (day, origin, title, turns) in enumerate(CONVERSATIONS):
        ep_id = episode_ids.next_episode_id(episodes, day)
        fm = {"id": ep_id, "timestamp": f"{day}T{9 + hour:02d}:00:00+00:00", "processed": False,
              "origin": origin, "title": title}
        if origin == "claude-code":
            fm.update(harness="claude-code", session_id=f"ses_synthetic_{hour:03d}")
        body = "\n\n".join(f"{speaker}: {text}" for speaker, text in turns)
        markdown_parser.write(episodes / f"{ep_id}.md", fm, body)
    subprocess.run(["git", "add", "-A"], cwd=bank, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "synthetic bank"], cwd=bank, check=True, capture_output=True)
    print(json.dumps({"pages": len(rows) + 1, "conversations": len(CONVERSATIONS)}))


def _key(stage: str | None, kwargs: dict) -> str:
    material = json.dumps({"stage": stage, "messages": kwargs.get("messages"),
                           "json": bool(kwargs.get("response_format"))}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode()).hexdigest()


class Recorder:
    """Answers a prompt asked before from the replay file; asks the plan (``live``) for every other one."""

    def __init__(self, replay: Path | None, record: Path | None, live: bool):
        self.answers: dict[str, str] = {}
        if replay is not None:
            for line in replay.read_text().splitlines():
                row = json.loads(line)
                self.answers.setdefault(row["key"], row["content"])
        self.out = record.open("w") if record is not None else None
        self.live = live
        self.calls: list[dict] = []

    def _row(self, stage, key, content, live, seconds, kwargs):
        row = {"stage": stage, "key": key, "live": live, "seconds": round(seconds, 2), "content": content,
               "prompt": kwargs.get("messages")}
        self.calls.append({k: row[k] for k in ("stage", "live", "seconds")})
        if self.out is not None:
            self.out.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.out.flush()

    def wrap(self, fn, stage, asynchronous):
        def answer(kwargs):
            key = _key(stage, kwargs)
            if key in self.answers:
                content = self.answers[key]
                self._row(stage, key, content, False, 0.0, kwargs)
                return key, SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                                            usage=None)
            if not self.live:
                raise RuntimeError(f"no recorded answer for a {stage} prompt (run with --live)")
            return key, None

        def keep(key, response, started, kwargs):
            content = response.choices[0].message.content
            self.answers[key] = content
            self._row(stage, key, content, True, time.perf_counter() - started, kwargs)
            return response

        if asynchronous:
            async def async_call(**kwargs):
                key, hit = answer(kwargs)
                if hit is not None:
                    return hit
                started = time.perf_counter()
                response = fn(**kwargs)
                if inspect.isawaitable(response):
                    response = await response
                return keep(key, response, started, kwargs)
            return async_call

        def call(**kwargs):
            key, hit = answer(kwargs)
            if hit is not None:
                return hit
            started = time.perf_counter()
            return keep(key, fn(**kwargs), started, kwargs)
        return call


def run(bank: Path, replay: Path | None, record: Path | None, live: bool, out: Path | None) -> None:
    isolate.pin_bank(bank)
    import sys
    from unittest.mock import patch

    from api.config import Settings
    from api.services import agent_engine, providers, sleep_cycle
    from api.services.connections import base
    from benchmarks.system.engine import embed
    from benchmarks.system.runtime import CLOCK_MODULES, Runtime

    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank), llm_mode="agent", agent_model="haiku",
                        agent_disambiguation_model="haiku", agent_max_concurrency=1, sleep_resolve_concurrency=1,
                        page_articles_enabled=True, summary_synthesis_enabled=True, web_check_per_run=0,
                        link_enrich_enabled=False, embedding_mode="local", embedding_model_local="fake-hash-v1",
                        sleep_max_episodes_per_cycle=25)
    recorder = Recorder(replay, record, live)

    def runner(argv, *, stdin=None, timeout=300.0, cwd=None, env_overrides=None):
        # The CLI's own sign-in lives in the developer's HOME; nothing else does.
        return base.run_cli_sync(argv, stdin=stdin, timeout=timeout, cwd=cwd,
                                 env_overrides={**(env_overrides or {}), "HOME": _REAL_HOME,
                                                "CICADA_CAPTURE": "off"})

    original_factory = providers.resolve_llm_fn

    def factory(settings_, **kwargs):
        asynchronous = kwargs.get("is_async")
        if asynchronous is None:
            asynchronous = inspect.iscoroutinefunction(kwargs.get("completion"))
        return recorder.wrap(original_factory(settings_, **kwargs), kwargs.get("stage"), asynchronous)

    rt = Runtime(CLOCK, settings, None)
    import importlib
    modules = [importlib.import_module("api.services." + name) for name in CLOCK_MODULES]
    stages: dict = {}
    with rt.stack:
        rt.stack.enter_context(patch.object(agent_engine, "_default_runner", lambda: runner))
        for module in [providers, *modules, *[m for n, m in list(sys.modules.items()) if n.startswith("api.")]]:
            if getattr(module, "resolve_llm_fn", None) is original_factory:
                rt.stack.enter_context(patch.object(module, "resolve_llm_fn", factory))
        for name in ("resolve_embed_fn", "resolve_embed_fn_for_model"):
            rt.stack.enter_context(patch.object(providers, name, lambda *a, **k: (embed, "fake-hash-v1")))
        for module, name, label in (("entity_extractor", "extract", "extraction"),
                                    ("entity_resolver", "resolve", "resolution"),
                                    ("conflict_resolver", "resolve_and_prune", "conflicts"),
                                    ("skill_extractor", "detect_patterns", "patterns"),
                                    ("sleep_cycle", "run", "drain")):
            rt.observe(importlib.import_module("api.services." + module), name, label)
        started = time.perf_counter()
        with rt.frozen():
            asyncio.run(sleep_cycle.run(settings, "sleep_calls_probe", user_triggered=True, drain=True))
        wall = time.perf_counter() - started
    for t in rt.timings:
        stages[t["stage"]] = round(stages.get(t["stage"], 0) + t["wall_seconds"], 1)
    state = sleep_cycle.get_sleep_state()
    by_stage = collections.Counter(c["stage"] for c in recorder.calls)
    live_by_stage = collections.Counter(c["stage"] for c in recorder.calls if c["live"])
    seconds = collections.Counter()
    for c in recorder.calls:
        seconds[c["stage"]] += c["seconds"]
    result = {"wall_seconds": round(wall, 1), "error": state.error, "stage_wall_seconds": stages,
              "calls_by_stage": dict(by_stage), "live_calls_by_stage": dict(live_by_stage),
              "live_seconds_by_stage": {k: round(v, 1) for k, v in seconds.items()},
              "conversations": len(CONVERSATIONS)}
    text = json.dumps(result, indent=1, default=str)
    print(text)
    if out is not None:
        out.write_text(text)


def _pages(bank: Path) -> dict:
    from api.services import markdown_parser
    from api.services.claims import parse_claims, strip_claims_block

    pages = {}
    for path in sorted((bank / "entities").glob("*.md")):
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter or {}
        claims = parse_claims(parsed.body or "")
        pages[path.stem] = {"name": fm.get("name"), "type": fm.get("type"), "status": fm.get("status"),
                            "sources": sorted(fm.get("source_episodes") or []), "aliases": sorted(fm.get("aliases") or []),
                            "claims": sorted((c.predicate, str(c.object)) for c in claims),
                            "body": strip_claims_block(parsed.body or "")}
    return pages


def _inbox(bank: Path) -> list[tuple]:
    from api.services import markdown_parser

    rows = []
    for path in sorted((bank / "inbox").rglob("*.md")):
        fm = markdown_parser.parse(path).frontmatter or {}
        rows.append((str(path.relative_to(bank / "inbox").parent), fm.get("kind") or fm.get("type"),
                     fm.get("entity_name") or fm.get("subject") or fm.get("entity_id"), fm.get("question")))
    return rows


def diff(before: Path, after: Path) -> None:
    """Pages created, merged and changed; claims; inbox questions — what differs between two runs' banks."""
    a, b = _pages(before), _pages(after)
    report = {"pages_before": len(a), "pages_after": len(b),
              "only_before": sorted(set(a) - set(b)), "only_after": sorted(set(b) - set(a)), "changed": {}}
    for page in sorted(set(a) & set(b)):
        x, y = a[page], b[page]
        delta = {k: {"before": x[k], "after": y[k]} for k in ("name", "type", "status", "sources", "aliases", "claims")
                 if x[k] != y[k]}
        if x["body"] != y["body"]:
            delta["body"] = "differs"
        if delta:
            report["changed"][page] = delta
    ia, ib = _inbox(before), _inbox(after)
    report["inbox_only_before"] = [r for r in ia if r not in ib]
    report["inbox_only_after"] = [r for r in ib if r not in ia]
    report["inbox_before"], report["inbox_after"] = len(ia), len(ib)
    print(json.dumps(report, indent=1, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--bank", required=True, type=Path)
    r = sub.add_parser("run")
    r.add_argument("--bank", required=True, type=Path)
    r.add_argument("--replay", type=Path)
    r.add_argument("--record", type=Path)
    r.add_argument("--out", type=Path)
    r.add_argument("--live", action="store_true")
    d = sub.add_parser("diff")
    d.add_argument("before", type=Path)
    d.add_argument("after", type=Path)
    a = ap.parse_args()
    if a.cmd == "build":
        isolate.pin_bank(a.bank.resolve())
        build(a.bank.resolve())
    elif a.cmd == "run":
        run(a.bank.resolve(), a.replay, a.record, a.live, a.out)
    else:
        isolate.pin_bank(a.before.resolve())
        diff(a.before.resolve(), a.after.resolve())


if __name__ == "__main__":
    main()
