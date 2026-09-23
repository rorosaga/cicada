"""G135 R-R8 — the stdio MCP server is loaded by file path, never as `mcp.server`.

Adding the official `mcp` SDK makes `mcp` a regular package on `sys.path`, and
PEP 420 lets a regular package beat the repo's namespace `mcp/` directory — so
`import mcp.server` means the SDK from now on (verified on 2.2.0)."""
from __future__ import annotations

import re
from pathlib import Path

from _stdio_server import stdio_server

REPO = Path(__file__).resolve().parents[2]
TESTS = Path(__file__).resolve().parent
_BY_NAME = re.compile(r"""import_module\(\s*["']mcp\.server|from mcp import server|import mcp\.server""")


def test_the_loader_returns_the_repo_stdio_server():
    server = stdio_server()
    assert Path(server.__file__).resolve() == REPO / "mcp" / "server.py"
    assert {"cicada_recall", "cicada_handshake"} <= {t["name"] for t in server.TOOLS}
    assert stdio_server() is server, "one module object, shared the way the name import was"


def test_no_test_resolves_the_stdio_server_by_module_name():
    offenders = [
        f"{p.name}:{i}"
        for p in sorted(TESTS.glob("test_*.py"))
        if p.name != Path(__file__).name
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if _BY_NAME.search(line)
    ]
    assert offenders == [], f"load mcp/server.py through _stdio_server.stdio_server(): {offenders}"


def test_the_sdk_owns_the_mcp_name():
    import mcp.server as sdk

    assert hasattr(sdk, "Server") and "site-packages" in (sdk.__file__ or "")
