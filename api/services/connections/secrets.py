"""``$CICADA_HOME/secrets.env`` — the only place Cicada writes API keys.

Keys entered in the companion app land here (0600), never in ``api/.env``,
never in the memory repo. On backend boot and after every write the file is
projected into ``os.environ`` (shell exports win unless ``override=True``),
which is all litellm needs — no settings reload, no restart.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from api.services.auth import cicada_home

SECRETS_FILE_NAME = "secrets.env"
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def secrets_path() -> Path:
    return cicada_home() / SECRETS_FILE_NAME


def _read() -> dict[str, str]:
    path = secrets_path()
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        out[name.strip()] = value.strip()
    return out


def _write(values: dict[str, str]) -> None:
    path = secrets_path()
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".secrets-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for name, value in values.items():
            fh.write(f"{name}={value}\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_secrets(*, override: bool = False) -> dict[str, str]:
    values = _read()
    for name, value in values.items():
        if override or not os.environ.get(name):
            os.environ[name] = value
    return values


def set_secret(name: str, value: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid secret name: {name!r}")
    if "\n" in value or "\r" in value or not value.strip():
        raise ValueError("secret value must be a single non-empty line")
    values = _read()
    values[name] = value.strip()
    _write(values)
    os.environ[name] = value.strip()


def remove_secret(name: str) -> None:
    values = _read()
    values.pop(name, None)
    _write(values)
    os.environ.pop(name, None)


def has_secret(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())
