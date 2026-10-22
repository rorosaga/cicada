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


def validate_secret_value(value: str) -> None:
    """Raise ``ValueError`` unless ``value`` is a single non-empty line —
    the same shape ``set_secret`` itself enforces, exposed separately so a
    caller can validate a whole BATCH of values before writing any of them
    (an all-or-nothing multi-field credential save, e.g.)."""
    if "\n" in value or "\r" in value or not value.strip():
        raise ValueError("secret value must be a single non-empty line")


def set_secret(name: str, value: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid secret name: {name!r}")
    validate_secret_value(value)
    values = _read()
    values[name] = value.strip()
    _write(values)
    os.environ[name] = value.strip()


def remove_secret(name: str) -> None:
    values = _read()
    values.pop(name, None)
    _write(values)
    os.environ.pop(name, None)
    mark_verified(name, None)


# --- G50/G215: what the key card may show about a key — never the key ---------------------------------------------

CHECKS_FILE_NAME = "key_checks.json"


def where(name: str) -> str | None:
    """``file`` when the key Cicada uses is the one in ``secrets.env``, ``environment`` when the backend inherited a
    different value from a shell export (which wins, ``load_secrets``), ``None`` when there is no key."""
    value = (os.environ.get(name) or "").strip()
    if not value:
        return None
    return "file" if _read().get(name) == value else "environment"


def hint(name: str) -> str | None:
    """The last four characters, after an ellipsis — the only part of a key any answer carries. A key of eight
    characters or fewer shows none of itself."""
    value = (os.environ.get(name) or "").strip()
    if not value:
        return None
    return f"…{value[-4:]}" if len(value) > 8 else "…"


def _checks_path() -> Path:
    return cicada_home() / CHECKS_FILE_NAME


def _read_checks() -> dict[str, str]:
    import json

    try:
        data = json.loads(_checks_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def mark_verified(name: str, when: str | None) -> None:
    """Record (or, with ``None``, forget) when the provider last accepted ``name``'s key. Names and times only."""
    import json

    checks = _read_checks()
    if when is None:
        if name not in checks:
            return
        checks.pop(name)
    else:
        checks[name] = when
    path = _checks_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".key_checks-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(checks, fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def verified_at(name: str) -> str | None:
    return _read_checks().get(name)


def has_secret(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())
