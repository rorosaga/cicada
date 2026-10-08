"""(d): the engine-free MCP read tools and the hook's recall, timed in process on a synthetic bank.

    SCALE_SCRATCH=<dir> api/.venv/bin/python -m benchmarks.scale.sweep_mcp --bank <dir>/bank
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from . import isolate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    ap.add_argument("--owner", default="owner-example")
    a = ap.parse_args()
    bank = a.bank.resolve()
    isolate.pin_bank(bank)

    import socket

    def no_network(*args, **kwargs):
        raise RuntimeError("offline probe forbids network access")
    socket.socket.connect = no_network
    socket.create_connection = no_network

    from api.services import hook_recall, mcp_tools
    from benchmarks.system.engine import embed
    from api.services import providers
    providers.resolve_embed_fn = lambda *a, **k: (embed, "fake-hash-v1")
    providers.resolve_embed_fn_for_model = lambda *a, **k: (embed, "fake-hash-v1")

    ctx = mcp_tools.ToolContext(memory_path=lambda: bank, session_id="ses_probe", harness="claude-code",
                                post=lambda *a, **k: {}, headers=lambda: {})
    calls = {
        "cicada_recall('alpha3-project')": lambda: mcp_tools.recall(ctx, "alpha3-project"),
        "cicada_recall('owner example')": lambda: mcp_tools.recall(ctx, "owner example"),
        "cicada_recall_detail(<owner>)": lambda: mcp_tools.recall_detail(ctx, a.owner),
        "cicada_recall_detail(alpha-0001)": lambda: mcp_tools.recall_detail(ctx, "alpha-0001"),
        "cicada_timeline(since 2026-09-01)": lambda: mcp_tools.timeline(ctx, "2026-09-01"),
        "cicada_check_nudges(<owner>)": lambda: mcp_tools.check_nudges(ctx, None, [a.owner]),
        "hook prompt_context": lambda: hook_recall.prompt_context(bank, "what did I decide about alpha3-project"),
        "hook session_primer": lambda: hook_recall.session_primer(bank, "claude-code"),
    }
    rows = []
    for name, fn in calls.items():
        times, size, err = [], 0, None
        for _ in range(3):
            t = time.perf_counter()
            try:
                out = fn()
                size = len(str(out))
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"[:120]
            times.append((time.perf_counter() - t) * 1000)
        rows.append({"call": name, "first_ms": round(times[0], 1), "warm_ms": round(min(times[1:]), 1),
                     "chars": size, "error": err})
    print(json.dumps(rows))
    for r in rows:
        print(f"{r['warm_ms']:>9} {r['first_ms']:>9} {r['chars']:>9}  {r['call']}  {r['error'] or ''}")


if __name__ == "__main__":
    main()
