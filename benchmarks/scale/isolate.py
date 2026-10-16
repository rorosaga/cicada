"""Pin every root to a scratch directory BEFORE the first ``api`` import.

Import this module first in every probe: it refuses to run without an explicit scratch root, so nothing here can
resolve the developer's real HOME, ``~/.cicada`` or bank.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if any(name == "api" or name.startswith("api.") for name in sys.modules):
    raise RuntimeError("benchmarks.scale.isolate must be imported before any api module")

_root = os.environ.get("SCALE_SCRATCH")
if not _root:
    raise RuntimeError("set SCALE_SCRATCH to a scratch directory")
SCRATCH = Path(_root).resolve()
HOME = SCRATCH / "home"
HOME.mkdir(parents=True, exist_ok=True)
os.environ.update({
    "HOME": str(HOME),
    "CICADA_HOME": str(HOME / ".cicada"),
    "CICADA_CAPTURE": "off",
    "CICADA_TELEMETRY": "off",
    "CICADA_API_AUTH": "off",
    "CICADA_ALLOW_LOGO_FETCH": "off",
    "CICADA_ALLOW_CONNECTOR_FETCH": "off",
    "CICADA_ALLOW_FEED_FETCH": "off",
    "LITELLM_MODE": "PRODUCTION",
    "GIT_AUTHOR_NAME": "Cicada Scale Probe",
    "GIT_AUTHOR_EMAIL": "probe@example.com",
    "GIT_COMMITTER_NAME": "Cicada Scale Probe",
    "GIT_COMMITTER_EMAIL": "probe@example.com",
})


def pin_bank(bank: Path) -> None:
    os.environ["CICADA_MEMORY_PATH"] = str(bank)
    os.environ.pop("CICADA_MEMORY_ROOT", None)
