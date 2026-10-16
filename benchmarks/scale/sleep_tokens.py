"""What one Sleep batch sends the engine, by stage, on a synthetic bank and the deterministic fake engine: calls,
prompt characters (system vs the rest), an estimated token count (characters / 4 — no tokenizer, no network), the
share of each stage's prompts that repeats as a byte-identical prefix across its calls (what a prompt cache can serve),
and the largest single prompt. The bank is mutated: run it on a copy.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.sleep_tokens --bank <dir>/run [--batch 25]
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import isolate


def common_prefix(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--batch", type=int, default=25)
    ap.add_argument("--dump", type=Path, help="write each stage's largest prompt here (synthetic text only)")
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)

    from api.config import Settings
    from api.services import sleep_cycle
    from benchmarks.scale.profile_sleep import owner_extraction
    from benchmarks.system import engine as fake_engine
    from benchmarks.system.engine import FakeEngine
    from benchmarks.system.runtime import Runtime

    fake_engine.extraction = owner_extraction
    settings = Settings(_env_file=None, CICADA_MEMORY_PATH=str(bank), llm_mode="local",
                        litellm_model="deterministic-v1", consolidation_model="deterministic-v1",
                        ollama_model="deterministic-v1", litellm_disambiguation_model="deterministic-v1",
                        embedding_mode="local", embedding_model_local="fake-hash-v1",
                        sleep_max_episodes_per_cycle=a.batch, link_enrich_enabled=False)
    prompts: list[dict] = []
    fake = FakeEngine()
    original = fake.completion

    def recording(*, stage=None, is_async=False):
        inner = original(stage=stage, is_async=False)

        def note(messages):
            system = "\n\n".join(m.get("content") or "" for m in messages if m.get("role") == "system")
            rest = "\n\n".join(m.get("content") or "" for m in messages if m.get("role") != "system")
            prompts.append({"stage": stage, "system": system, "rest": rest})

        def call(**kw):
            note(kw.get("messages") or [])
            return inner(**kw)

        async def async_call(**kw):
            note(kw.get("messages") or [])
            return inner(**kw)
        return async_call if is_async else call
    fake.completion = recording

    runtime = Runtime(datetime.now(timezone.utc), settings, fake)
    with runtime:
        started = time.perf_counter()
        asyncio.run(sleep_cycle.run(settings, "sleep_tokens_probe", user_triggered=True, drain=False))
        wall = time.perf_counter() - started
    episodes = sleep_cycle.get_sleep_state().episodes_processed or a.batch

    by_stage = collections.defaultdict(list)
    for p in prompts:
        by_stage[p["stage"]].append(p)
    rows = []
    for stage, calls in by_stage.items():
        sys_chars = sum(len(c["system"]) for c in calls)
        rest_chars = sum(len(c["rest"]) for c in calls)
        full = [c["system"] + "\n\n" + c["rest"] for c in calls]
        # The prefix a cache could serve on call k is what call k shares with an earlier call of the same stage.
        cached = 0
        for k in range(1, len(full)):
            cached += max(common_prefix(full[k], full[j]) for j in range(max(0, k - 8), k))
        biggest = max(full, key=len)
        rows.append({"stage": stage, "calls": len(calls), "system_chars": sys_chars, "rest_chars": rest_chars,
                     "est_tokens": (sys_chars + rest_chars) // 4,
                     "est_tokens_per_episode": round((sys_chars + rest_chars) / 4 / max(1, episodes)),
                     "cacheable_pct": round(100 * cached / max(1, sys_chars + rest_chars)),
                     "max_prompt_chars": len(biggest)})
        if a.dump:
            a.dump.mkdir(parents=True, exist_ok=True)
            (a.dump / f"{stage}.txt").write_text(biggest, encoding="utf-8")
    rows.sort(key=lambda r: -r["est_tokens"])
    total = sum(r["est_tokens"] for r in rows)
    print(json.dumps({"wall_s": round(wall, 1), "episodes": episodes, "est_tokens": total,
                      "est_tokens_per_episode": round(total / max(1, episodes)), "stages": rows}, indent=1))


if __name__ == "__main__":
    os.environ.setdefault("CICADA_CAPTURE", "off")
    main()
