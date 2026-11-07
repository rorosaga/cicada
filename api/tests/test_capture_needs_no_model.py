"""No LLM at capture time (CLAUDE.md, Capture): the writers every capture door goes through — the Stop hook's
transcript capture, the hook-posted turns, the staged sources, Telegram — import no model client at all, so no
capture can wait on, spend on or fail because of a model. A fresh interpreter, so what the rest of the suite imported
cannot hide an import these modules gained. A fresh interpreter sees only what importing them runs, so an import inside a
function is caught by reading the modules' source (#350 note), and the modules those function-level imports name are
imported in the fresh interpreter too."""
from __future__ import annotations

import ast
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
    "api.services.reminders_local",   # G219
    "api.services.notion_export",     # G219
    "api.services.agent_memory_notes",  # ruling 43
    "api.services.offered_episode",   # G132 phase 2: an old home's set-aside episode, offered back
)
MODEL_CLIENTS = ("litellm", "openai", "anthropic", "sentence_transformers", "torch", "onnxruntime",
                 "api.services.entity_extractor", "api.services.ask_service", "api.services.agent_engine",
                 "api.services.connections.base")


def _imports(module: str) -> list[tuple[str, bool]]:
    """Every module an import statement in ``module``'s source names, at any depth: ``(name, at_top_level)``. A
    ``from pkg import name`` yields both ``pkg`` and ``pkg.name`` (the name may be a submodule)."""
    path = REPO / (module.replace(".", "/") + ".py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    top = {id(node) for node in tree.body}
    package = module.rpartition(".")[0]
    out: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(alias.name, id(node) in top) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                base = ".".join([*package.split(".")[: len(package.split(".")) - node.level + 1], base]).strip(".")
            out.append((base, id(node) in top))
            out += [(f"{base}.{alias.name}", id(node) in top) for alias in node.names]
    return out


def _is_model_client(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in MODEL_CLIENTS)


def test_no_capture_writer_imports_a_model_client_anywhere_in_its_source():
    found = {m: sorted({name for name, _top in _imports(m) if _is_model_client(name)}) for m in CAPTURE_WRITERS}
    assert {m: v for m, v in found.items() if v} == {}


def _lazily_imported_modules() -> list[str]:
    """The ``api`` modules the capture writers import inside a function: importable modules only."""
    names = set()
    for m in CAPTURE_WRITERS:
        for name, top in _imports(m):
            if not top and name.startswith("api.") and (
                    (REPO / (name.replace(".", "/") + ".py")).is_file()
                    or (REPO / name.replace(".", "/") / "__init__.py").is_file()):
                names.add(name)
    return sorted(names)


def test_the_lazy_import_scan_reads_the_writers():
    lazy = _lazily_imported_modules()
    assert "api.services.media_ingestor" in lazy, lazy   # telegram_capture saves a link inside a function


def test_the_capture_writers_import_no_model_client():
    script = (
        "import json, sys\n"
        f"for m in {CAPTURE_WRITERS + tuple(_lazily_imported_modules())!r}: __import__(m)\n"
        f"print(json.dumps(sorted(m for m in {MODEL_CLIENTS!r} if m in sys.modules)))\n"
    )
    out = subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []
