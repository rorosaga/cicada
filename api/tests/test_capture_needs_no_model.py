"""No LLM at capture time (CLAUDE.md, Capture): the writers every capture door goes through — the Stop hook's
transcript capture, the hook-posted turns, the staged sources, Telegram — import no model client at all, so no
capture can wait on, spend on or fail because of a model. A fresh interpreter, so what the rest of the suite imported
cannot hide an import these modules gained."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CAPTURE_WRITERS = (
    "api.services.transcript_capture",
    "api.services.turn_capture",
    "api.services.episode_staging",
    "api.services.telegram_capture",
)
MODEL_CLIENTS = ("litellm", "openai", "anthropic", "sentence_transformers", "torch", "onnxruntime",
                 "api.services.entity_extractor", "api.services.ask_service", "api.services.agent_engine",
                 "api.services.connections.base")


def test_the_capture_writers_import_no_model_client():
    script = (
        "import json, sys\n"
        f"for m in {CAPTURE_WRITERS!r}: __import__(m)\n"
        f"print(json.dumps(sorted(m for m in {MODEL_CLIENTS!r} if m in sys.modules)))\n"
    )
    out = subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []
