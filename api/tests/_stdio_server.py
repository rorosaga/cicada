"""The stdio MCP server, loaded by FILE PATH — never as ``mcp.server`` (G135 R-R8).

The repo's ``mcp/`` directory has no ``__init__.py``: it was a namespace
package, so ``importlib.import_module("mcp.server")`` used to find
``mcp/server.py``. G135 adds the official ``mcp`` SDK, a *regular* package, and
a regular package anywhere on ``sys.path`` beats a namespace portion (PEP 420),
so that name now means the SDK's ``mcp.server`` (verified on 2.2.0). Renaming
``mcp/`` is not an option — every user's registered stdio command contains
``mcp/server.py``. One loader, one module object registered under a private
name and shared by every caller, exactly as the name import used to share it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_NAME = "cicada_stdio_mcp_server"
_PATH = Path(__file__).resolve().parents[2] / "mcp" / "server.py"


def stdio_server():
    module = sys.modules.get(_NAME)
    if module is None:
        spec = importlib.util.spec_from_file_location(_NAME, _PATH)
        module = importlib.util.module_from_spec(spec)
        sys.modules[_NAME] = module
        spec.loader.exec_module(module)
    return module
