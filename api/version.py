"""Cicada's version: one ``VERSION`` file at the repository root (G182).

The same file is read by ``bundle.sh`` (the app's ``CFBundleShortVersionString``),
by FastAPI (``app.version``, which ``/healthz`` reports) and by the MCP server's
``serverInfo``. A release bundle copies it next to ``api/``, so the relative
lookup below holds both in a checkout and inside the app. ``make release``
is the only thing that bumps it.
"""
from __future__ import annotations

import re
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
UNKNOWN = "0.0.0+unknown"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def read_version(path: Path = VERSION_FILE) -> str:
    """The first line of ``VERSION``; ``UNKNOWN`` when it is missing or not semver,
    so a broken file reads as a mismatch in the app rather than crashing startup."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return UNKNOWN
    return text if _SEMVER.match(text) else UNKNOWN


__version__ = read_version()
