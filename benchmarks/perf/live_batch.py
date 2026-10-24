"""One Sleep batch on a synthetic bank, on the Claude plan at haiku — the at-scale half of the Sleep measurement.

    export SCALE_SCRATCH=<dir>
    api/.venv/bin/python -m benchmarks.perf.live_batch --bank <copy> [--batch 25]

The engine is the person's plan through the verify skill's ``plan-claude`` shim (the ``claude`` child alone gets the
real HOME for the plan's sign-in; only the locked engine argv runs; ``CICADA_CAPTURE=off``). Never a metered key: the
agent rung with ``haiku`` for every stage. Every root else is the scratch folder (``benchmarks.scale.isolate``), the
search model is the offline hashing embedder, and telemetry is on into the scratch ``CICADA_HOME`` so
``benchmarks.perf.ledger`` reads the batch's calls. Mutates the bank: run it on a copy. Synthetic text only.
"""
from __future__ import annotations

from benchmarks.scale import isolate  # noqa: F401  (first)

import argparse
import asyncio
import json
import os
import shutil
import time
from pathlib import Path

SKILL_BIN = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "verify-cicada" / "bin"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--batch", type=int, default=25)
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)
    real = shutil.which("claude")
    if not real:
        raise SystemExit("claude is not on PATH")
    os.environ.update({
        "CICADA_TELEMETRY": "on",
        "CICADA_LLM_MODE": "agent", "CICADA_AGENT_MODEL": "haiku", "CICADA_AGENT_DISAMBIGUATION_MODEL": "haiku",
        "CICADA_WEB_CHECK_AGENT_MODEL": "haiku", "CICADA_CLAUDE_CLI": str(SKILL_BIN / "plan-claude"),
        "CICADA_VERIFY_REAL_CLAUDE": real, "CICADA_VERIFY_MODEL": "haiku",
        "OMP_NUM_THREADS": "4", "TOKENIZERS_PARALLELISM": "false", "HF_HUB_OFFLINE": "1",
    })
    from benchmarks.perf import ledger
    from benchmarks.system.engine import embed

    from api.config import Settings
    from api.services import providers, sleep_cycle, telemetry

    providers.resolve_embed_fn = lambda *x, **k: (embed, "fake-hash-v1")
    providers.resolve_embed_fn_for_model = lambda *x, **k: (embed, "fake-hash-v1")
    providers.cached_embed_fn_for_model = lambda *x, **k: (embed, "fake-hash-v1")
    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank), sleep_max_episodes_per_cycle=a.batch,
                        embedding_mode="local", embedding_model_local="fake-hash-v1", link_enrich_enabled=False)
    since = telemetry.now_iso()
    started = time.perf_counter()
    asyncio.run(sleep_cycle.run(settings, "perf_live_batch", user_triggered=True, drain=False))
    wall = time.perf_counter() - started
    state = sleep_cycle.get_sleep_state()
    files = sorted(telemetry.telemetry_dir().glob("events-*.jsonl"))
    lines = [line for f in files for line in f.read_text(encoding="utf-8").splitlines()]
    summary = ledger.summarize(lines, since=since)
    print(json.dumps({"bank": bank.name, "wall_s": round(wall, 1), "episodes": state.episodes_processed,
                      "error": state.error, "ledger": summary}, indent=1, default=str))
    print(ledger.render(summary))


if __name__ == "__main__":
    main()
