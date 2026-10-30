"""G132 phase 3a — unset or off, nothing changes: no backend module imports the relay server, nothing at startup reaches
the relay's client side, and the relay package imports nothing from the backend (it ships alone in its container)."""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RELAY_SIDE = {"sync_relay_crypto", "sync_relay_pairing", "sync_relay_client"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.add(mod)
            out |= {f"{mod}.{a.name}" if mod else a.name for a in node.names}
    return out


def _backend_files():
    for path in (REPO / "api").rglob("*.py"):
        rel = path.relative_to(REPO / "api").parts
        if rel[0] in ("tests", ".venv", "vendor"):
            continue
        yield path


def test_no_backend_module_imports_the_relay_server():
    offenders = [str(p.relative_to(REPO)) for p in _backend_files()
                 if any(name == "cicada_relay" or name.startswith("cicada_relay.") for name in _imports(p))]
    assert offenders == []


def test_only_the_relay_side_modules_import_each_other():
    """3b wires the client into the follower and the outbox; until then nothing else reaches it."""
    offenders = []
    for path in _backend_files():
        if path.stem in RELAY_SIDE:
            continue
        names = _imports(path)
        if any(any(side in name.split(".") for side in RELAY_SIDE) for name in names):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_the_relay_imports_nothing_from_the_backend():
    for path in (REPO / "relay" / "cicada_relay").glob("*.py"):
        names = _imports(path)
        assert not any(n == "api" or n.startswith("api.") or "services" in n.split(".") for n in names), path.name


def test_importing_the_backend_app_loads_no_relay_module(tmp_path):
    code = ("import sys; import api.main; "
            "bad = [m for m in sys.modules if 'sync_relay' in m or m.startswith('cicada_relay') or m.startswith('nacl')];"
            "print(bad); sys.exit(1 if bad else 0)")
    proc = subprocess.run([sys.executable, "-c", code], cwd=str(REPO), capture_output=True, text=True, timeout=120,
                          env={"HOME": str(tmp_path), "CICADA_HOME": str(tmp_path / ".cicada"),
                               "CICADA_MEMORY_PATH": str(tmp_path / "bank"), "CICADA_CAPTURE": "off",
                               "CICADA_TELEMETRY": "off", "PATH": "/usr/bin:/bin"})
    assert proc.returncode == 0, proc.stdout + proc.stderr[-2000:]
