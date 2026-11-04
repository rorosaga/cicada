"""G237: does Sleep on a Claude key make the memory Sleep through Claude Code makes?

Runs the same synthetic conversations (``engine_parity_conversations.json``, placeholders only) through the production
drain on a fresh scratch bank, once per engine, and compares what each made: pages, claims, evidence spans, questions,
failures, and what it cost. Nothing here reads the person's bank or home; ``--out`` holds both.

    python -m benchmarks.engine_parity run --leg plan --model haiku --out OUT/plan
    python -m benchmarks.engine_parity estimate --from OUT/plan
    python -m benchmarks.engine_parity run --leg key --model anthropic/claude-haiku-5-5 --out OUT/key \\
        --key-file ~/.cicada/secrets.env --max-input-tokens 80000 --yes-spend
    python -m benchmarks.engine_parity compare OUT/plan OUT/key

The key leg spends the person's money, so it refuses without ``--yes-spend`` and a ``--max-input-tokens`` cap. It takes
only ``ANTHROPIC_API_KEY`` from ``--key-file`` (or the environment), never prints it, and writes it nowhere; the scratch
home has no secrets file. Past the cap the run is cancelled at its next safe point, and it says so. The plan leg uses the
Claude plan the machine is signed in to.

Tests run both legs against stand-ins at the transport (``test_engine_parity``): those prove the harness and the path,
never model quality. Only real runs compare models, and two real runs of one engine differ too (a model is not
deterministic): read a comparison against a second run of the same leg in another ``--out``, not against zero.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).with_name("engine_parity_conversations.json")
#: Conversations a batch reads, the app's default.
BATCH_SIZE = 25


def _refuse_real_paths(out: Path) -> None:
    resolved = out.resolve()
    home = Path.home().resolve()
    for real in (home / ".cicada", home / ".claude", REPO / "memory"):
        if resolved == real or real in resolved.parents:
            raise SystemExit(f"--out must be a scratch folder, not inside {real}")
    if (resolved / "bank" / "entities").exists():
        raise SystemExit(f"{resolved} already holds a run; use a fresh folder")


def read_key_file(path: Path) -> str | None:
    """Only the Claude key's line. Never returned to a caller that prints: it goes straight into this process's env."""
    for line in path.expanduser().read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == "ANTHROPIC_API_KEY" and value.strip():
            return value.strip()
    return None


def _git(bank: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(bank), *args], text=True, capture_output=True, check=True).stdout.strip()


def seed_bank(bank: Path, *, clock: datetime, conversations: list[dict]) -> None:
    from api.services import bank_registry, episode_staging, git_service, predicates

    bank.mkdir(parents=True, exist_ok=True)
    for name in ("entities", "episodes", "inbox"):
        (bank / name).mkdir(exist_ok=True)
    (bank / ".gitignore").write_text("\n".join(bank_registry.DERIVED_ARTIFACTS) + "\n")
    predicates.install_predicate_map(bank)
    _git(bank, "init", "-q")
    _git(bank, "config", "user.name", "Cicada Parity")
    _git(bank, "config", "user.email", "parity@cicada.local")
    _git(bank, "add", "-A")
    _git(bank, "commit", "-q", "-m", "Parity seed\n\nCicada-Author: cicada")
    drafts = []
    for row in conversations:
        day = (clock + timedelta(days=row["day"])).date().isoformat()
        turns = [episode_staging.Turn(text=text, speaker="user" if i % 2 == 0 else "assistant",
                                      ts=f"{day}T10:{i:02d}:00+00:00") for i, text in enumerate(row["turns"])]
        drafts.append(episode_staging.EpisodeDraft(
            title="Synthetic conversation", source_id=row["source_id"], timestamp=f"{day}T10:00:00+00:00",
            original_date=day, source="import", origin="chatgpt",
            extra={"session_id": "ses_parity_" + re.sub(r"\W", "_", row["source_id"])}, turns=turns))
    result = episode_staging.stage(drafts, bank / "episodes")
    git_service.commit_paths_sync(bank, git_service.build_commit_message("Parity intake", [], authors=["user"]),
                                  result.paths)


def settings_for(leg: str, bank: Path, *, model: str, judge: str | None):
    from api.config import Settings

    common = dict(_env_file=None, CICADA_MEMORY_PATH=str(bank), embedding_mode="local",
                  embedding_model_local="fake-hash-v1", sleep_max_episodes_per_cycle=BATCH_SIZE, link_enrich_enabled=False)
    if leg == "plan":
        return Settings(llm_mode="agent", agent_model=model, agent_disambiguation_model=judge or model, **common)
    return Settings(llm_mode="byok", litellm_model=model, consolidation_model="",
                    litellm_disambiguation_model=judge or model, **common)


def _usage_events(home: Path) -> list[dict]:
    rows: list[dict] = []
    for path in sorted((home / "telemetry").glob("events-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("kind") == "llm_call":
                rows.append(row)
    return rows


def _by_stage(events: list[dict]) -> dict:
    stages: dict[str, dict] = {}
    for e in events:
        s = stages.setdefault(e.get("stage") or "unknown", {
            "calls": 0, "failed": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.0,
            "equiv_usd": 0.0, "models": []})
        s["calls"] += 1
        s["failed"] += 0 if e.get("ok", True) else 1
        s["input"] += e.get("input_tokens") or 0
        s["output"] += e.get("output_tokens") or 0
        s["cache_read"] += e.get("cache_read_tokens") or 0
        s["cache_write"] += e.get("cache_write_tokens") or 0
        s["cost_usd"] = round(s["cost_usd"] + (e.get("cost_usd") or 0.0), 6)
        s["equiv_usd"] = round(s["equiv_usd"] + (e.get("equiv_cost_usd") or 0.0), 6)
        if e.get("model") and e["model"] not in s["models"]:
            s["models"].append(e["model"])
    return stages


def _past_reads(drain_id: str | None) -> dict | None:
    """What the Sleep page's Past reads shows for this run, from the scratch home's own ledger: the same function."""
    from api.services import cycle_usage, telemetry

    if not drain_id:
        return None
    usage = cycle_usage.usage_for_drain(cycle_usage.Ledger.build(telemetry.read_events()), drain_id)
    summary = cycle_usage.summarize(usage)
    if summary is None:
        return None
    return {"basis": summary.basis, "cost_usd": summary.cost_usd, "equiv_cost_usd": summary.equiv_cost_usd,
            "engine": summary.engine, "connection": summary.connection,
            "models": [{"model": m.model, "calls": m.calls, "basis": m.basis} for m in usage.models]}


def snapshot(bank: Path, home: Path, *, state: dict) -> dict:
    """What Sleep made, in plain data. Claim text stays here, in the scratch folder: the fixture is synthetic."""
    from api.services import claims as claims_module, markdown_parser

    pages, claims = [], []
    for path in sorted((bank / "entities").glob("*.md")):
        if path.name.endswith(".claims.jsonl"):
            continue
        parsed = markdown_parser.parse(path)
        fm = parsed.frontmatter or {}
        pages.append({"id": path.stem, "name": fm.get("name") or fm.get("title") or path.stem, "type": fm.get("type"),
                      "status": fm.get("status")})
        for c in claims_module.parse_claims(parsed.body):
            spans = [{"episode": getattr(e, "episode", None), "kind": getattr(e, "kind", None),
                      "start": getattr(e, "start", None), "end": getattr(e, "end", None)}
                     for e in (getattr(c, "evidence", None) or [])]
            claims.append({"subject": c.subject, "predicate": c.predicate, "object": str(c.object), "spans": spans,
                           "valid_from": c.valid_from, "valid_to": c.valid_to, "authored_by": getattr(c, "authored_by", None)})
    questions = []
    for path in sorted((bank / "inbox").rglob("*.md")):
        fm = markdown_parser.parse(path).frontmatter or {}
        questions.append({"kind": fm.get("kind") or fm.get("type"), "entity": fm.get("entity") or fm.get("entity_id"),
                          "status": fm.get("status")})
    processed = sum(1 for p in (bank / "episodes").glob("*.md") if markdown_parser.parse(p).frontmatter.get("processed"))
    events = _usage_events(home)
    gross = sum(e.get("input_tokens") or 0 for e in events)
    read = sum(e.get("cache_read_tokens") or 0 for e in events)
    costs = [e["cost_usd"] for e in events if e.get("cost_usd") is not None]
    trailers = sorted({line.partition(": ")[2] for line in _git(bank, "log", "--format=%B").splitlines()
                       if line.startswith("Cicada-Engine: ")})
    return {
        "past_reads": _past_reads(state.get("drain_id")),
        "pages": pages, "claims": claims, "questions": questions, "episodes_processed": processed,
        "failures": state, "engine_trailers": trailers,
        "usage": {"calls": len(events), "gross_input": gross, "output": sum(e.get("output_tokens") or 0 for e in events),
                  "cache_read": read, "cache_write": sum(e.get("cache_write_tokens") or 0 for e in events),
                  "hit_rate": round(read / gross, 4) if gross else 0.0,
                  "cost_usd": round(sum(costs), 6) if costs else None,
                  "equiv_usd": round(sum(e.get("equiv_cost_usd") or 0.0 for e in events), 6),
                  "by_stage": _by_stage(events)},
    }


async def _watch_cap(home: Path, cap: int, tripped: list[int]) -> None:
    """Past the cap, the run is cancelled at its next safe point. A cancel is never instant: calls in flight finish."""
    from api.services import sleep_cycle

    while True:
        await asyncio.sleep(2.0)
        used = sum((e.get("input_tokens") or 0) - (e.get("cache_read_tokens") or 0) for e in _usage_events(home))
        if used > cap:
            tripped.append(used)
            sleep_cycle.request_cancel()
            return


def run_leg(leg: str, *, model: str, judge: str | None, out: Path, cap: int | None = None,
            conversations: list[dict] | None = None, clock: datetime | None = None) -> dict:
    """One engine on a fresh bank, through the production drain. Sets ``CICADA_HOME``/``CICADA_MEMORY_PATH`` for this
    process before the backend reads them; a process runs one leg (the module state is the backend's own)."""
    from benchmarks.system.engine import embed

    bank, home = out / "bank", out / "home"
    home.mkdir(parents=True, exist_ok=True)
    os.environ["CICADA_HOME"] = str(home)
    os.environ["CICADA_MEMORY_PATH"] = str(bank)
    os.environ["LITELLM_MODE"] = "PRODUCTION"
    os.environ["CICADA_TELEMETRY"] = "on"   # the scratch home's ledger is what the comparison reads
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    for gate in ("CICADA_ALLOW_CONNECTOR_FETCH", "CICADA_ALLOW_FEED_FETCH", "CICADA_ALLOW_LOGO_FETCH"):
        os.environ[gate] = "off"
    from api.services import providers, sleep_cycle

    clock = clock or datetime.now(timezone.utc)
    seed_bank(bank, clock=clock, conversations=conversations if conversations is not None
              else json.loads(FIXTURE.read_text(encoding="utf-8")))
    settings = settings_for(leg, bank, model=model, judge=judge)
    tripped: list[int] = []

    async def drive() -> None:
        watcher = asyncio.create_task(_watch_cap(home, cap, tripped)) if cap else None
        try:
            await sleep_cycle.run(settings, f"sleep_parity_{leg}", user_triggered=True, drain=True)
        finally:
            if watcher is not None:
                watcher.cancel()

    fake_embed = lambda *a, **k: (embed, "fake-hash-v1")  # noqa: E731 — a search model is not what is being compared
    started = time.perf_counter()
    with patch.object(providers, "resolve_embed_fn", fake_embed), \
            patch.object(providers, "resolve_embed_fn_for_model", fake_embed), \
            patch.object(providers, "cached_embed_fn_for_model", fake_embed):
        asyncio.run(drive())
    state = sleep_cycle.get_sleep_state()
    ds = state.drain
    failures = {
        "drain_id": getattr(ds, "drain_id", None),
        "error": state.error, "stop": ds.stop.reason if ds and ds.stop else None,
        "stop_sentence": ds.stop.sentence if ds and ds.stop else None,
        "parked": dict(getattr(ds, "parked", {}) or {}), "unread": dict(getattr(ds, "unread", {}) or {}),
        "cap_tripped_at": tripped[0] if tripped else None, "seconds": round(time.perf_counter() - started, 1),
    }
    snap = snapshot(bank, home, state=failures)
    snap["leg"], snap["model"], snap["judge"] = leg, model, judge or model
    out.mkdir(parents=True, exist_ok=True)
    (out / "snapshot.json").write_text(json.dumps(snap, indent=1, sort_keys=True), encoding="utf-8")
    return snap


# ---- comparing -------------------------------------------------------------------------------------------------------


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _jaccard(a: set, b: set) -> float:
    return round(len(a & b) / len(a | b), 3) if a | b else 1.0


def _located(claims: list[dict]) -> float:
    """The share of claims with an evidence span that holds offsets (a located quote, not bare reasoning)."""
    if not claims:
        return 1.0
    return round(sum(1 for c in claims if any(s.get("start") is not None for s in c["spans"])) / len(claims), 3)


def compare(a: dict, b: dict) -> dict:
    pages_a, pages_b = ({_norm(p["name"]) for p in s["pages"]} for s in (a, b))
    triples_a, triples_b = ({(_norm(c["subject"]), _norm(c["predicate"]), _norm(c["object"])) for c in s["claims"]}
                            for s in (a, b))
    facts_a, facts_b = ({t[:2] for t in triples} for triples in (triples_a, triples_b))
    questions_a, questions_b = ({(q["kind"], q["entity"]) for q in s["questions"]} for s in (a, b))
    report = {
        "pages": {"a": len(pages_a), "b": len(pages_b), "jaccard": _jaccard(pages_a, pages_b),
                  "only_a": sorted(pages_a - pages_b), "only_b": sorted(pages_b - pages_a)},
        "claims": {"a": len(triples_a), "b": len(triples_b), "jaccard_exact": _jaccard(triples_a, triples_b),
                   "jaccard_subject_predicate": _jaccard(facts_a, facts_b),
                   "located_a": _located(a["claims"]), "located_b": _located(b["claims"])},
        "questions": {"a": len(questions_a), "b": len(questions_b), "jaccard": _jaccard(questions_a, questions_b)},
        "episodes_processed": {"a": a["episodes_processed"], "b": b["episodes_processed"]},
        "failures": {"a": a["failures"], "b": b["failures"]},
        "engine_trailers": {"a": a["engine_trailers"], "b": b["engine_trailers"]},
        "usage": {"a": {k: v for k, v in a["usage"].items() if k != "by_stage"},
                  "b": {k: v for k, v in b["usage"].items() if k != "by_stage"}},
        "calls_by_stage": {stage: {"a": a["usage"]["by_stage"].get(stage, {}).get("calls", 0),
                                   "b": b["usage"]["by_stage"].get(stage, {}).get("calls", 0)}
                           for stage in sorted({*a["usage"]["by_stage"], *b["usage"]["by_stage"]})},
    }
    return report


# ---- estimating ------------------------------------------------------------------------------------------------------


def estimate(snap: dict, *, model: str = "claude-haiku-5-5") -> dict:
    """What the key leg should cost, from a run's measured calls and tokens, at the list prices in ``price_supplement``.

    The plan's counters are the basis, less what only the plan pays: its CLI attaches its own context to the first user
    message and writes the tail of each prompt to the cache (measured ≈640 tokens a call on `claude` 2.1, Haiku 5.5); a
    direct call has neither. Cached = each stage's system prompt after its first call (one write, one-hour rate)."""
    from api.services import price_supplement

    cli_tail = 640
    total = {"calls": 0, "gross_input": 0, "uncached": 0, "cache_read": 0, "cache_write": 0, "output": 0, "cost_usd": 0.0}
    rows: dict[str, dict] = {}
    for stage, s in snap["usage"]["by_stage"].items():
        calls = s["calls"]
        gross = max(0, s["input"] - cli_tail * calls)
        system = s["cache_read"] // max(1, calls - 1) if calls > 1 and s["cache_read"] else 0
        reads = system * max(0, calls - 1)
        writes = system
        rest = max(0, gross - reads - writes)
        cost = price_supplement.claude_cost(model, input_tokens=rest, output_tokens=s["output"], cache_read=reads,
                                            cache_write=writes, cache_write_1h=writes) or 0.0
        uncached_cost = price_supplement.claude_cost(model, input_tokens=gross, output_tokens=s["output"]) or 0.0
        rows[stage] = {"calls": calls, "gross_input": gross, "cache_read": reads, "cache_write": writes,
                       "output": s["output"], "cost_usd": round(cost, 6), "cost_without_cache_usd": round(uncached_cost, 6)}
        total["calls"] += calls
        total["gross_input"] += gross
        total["uncached"] += rest + writes
        total["cache_read"] += reads
        total["cache_write"] += writes
        total["output"] += s["output"]
        total["cost_usd"] = round(total["cost_usd"] + cost, 6)
    return {"model": model, "basis": price_supplement.CLAUDE_BASIS, "total": total, "by_stage": rows}


def cost_table(snap: dict) -> dict:
    """The same measured run at each tier's price: what a person choosing a model would see coming."""
    return {m: estimate(snap, model=m)["total"]["cost_usd"]
            for m in ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-4-5")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmarks.engine_parity", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--leg", choices=("plan", "key"), required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--judge")
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--key-file", type=Path, help="a secrets file: only its ANTHROPIC_API_KEY line is read")
    run.add_argument("--max-input-tokens", type=int, help="key leg: cancel past this many uncached input tokens")
    run.add_argument("--yes-spend", action="store_true", help="key leg: this spends money on your key")
    est = sub.add_parser("estimate")
    est.add_argument("--from", dest="source", type=Path, required=True)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("a", type=Path)
    cmp_.add_argument("b", type=Path)
    args = parser.parse_args(argv)

    if args.command == "compare":
        report = compare(*(json.loads((p / "snapshot.json").read_text(encoding="utf-8")) for p in (args.a, args.b)))
        print(json.dumps(report, indent=1, sort_keys=True))
        return 0
    if args.command == "estimate":
        snap = json.loads((args.source / "snapshot.json").read_text(encoding="utf-8"))
        print(json.dumps({**estimate(snap), "by_model_usd": cost_table(snap)}, indent=1, sort_keys=True))
        return 0
    _refuse_real_paths(args.out)
    if args.leg == "key":
        if not args.yes_spend or not args.max_input_tokens:
            print("The key leg spends money on your key: pass --yes-spend and --max-input-tokens.", file=sys.stderr)
            return 2
        key = read_key_file(args.key_file) if args.key_file else os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            print("No ANTHROPIC_API_KEY in --key-file or the environment.", file=sys.stderr)
            return 2
        os.environ["ANTHROPIC_API_KEY"] = key
    snap = run_leg(args.leg, model=args.model, judge=args.judge, out=args.out,
                   cap=args.max_input_tokens if args.leg == "key" else None)
    summary = {"leg": snap["leg"], "model": snap["model"], "pages": len(snap["pages"]), "claims": len(snap["claims"]),
               "questions": len(snap["questions"]), "episodes_processed": snap["episodes_processed"],
               "failures": snap["failures"], "usage": {k: v for k, v in snap["usage"].items() if k != "by_stage"},
               "engine_trailers": snap["engine_trailers"]}
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0 if not snap["failures"]["error"] else 1


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    sys.exit(main())
