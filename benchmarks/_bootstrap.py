"""Shared bootstrap for the benchmark runners.

Importing this module:

1. Puts the repo root on ``sys.path`` so ``api.*`` imports work when the
   runners are executed as ``python -m benchmarks.run_table1`` from the
   repo root.
2. Loads ``api/.env`` into ``os.environ`` so LiteLLM and LEANN pick up
   ``OPENAI_API_KEY`` and friends the same way the FastAPI server does.
3. Exposes the three paths every runner needs: the repo root, the live
   memory dir, and the benchmark results dir.

Import this FIRST in every runner, before any ``api.*`` or ``litellm``
import.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO_ROOT: Path = _HERE.parent
LIVE_MEMORY_PATH: Path = REPO_ROOT / "memory"
BENCHMARK_RESULTS: Path = REPO_ROOT / "benchmark_results"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Load api/.env into the current process so litellm and leann see API keys.
# Do NOT overwrite values already in the environment — an explicit export
# from the shell should still win.
_ENV_FILE = REPO_ROOT / "api" / ".env"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

BENCHMARK_RESULTS.mkdir(parents=True, exist_ok=True)
