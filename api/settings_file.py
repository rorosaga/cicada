"""The developer checkout's settings file, `api/.env`, read on purpose wherever the backend starts.

**Where it is.** Beside this package, found from this file's own folder — never from the working directory. The
launchd backend runs with the repo root as its cwd, an MCP server or a hook runs in an agent's project folder, and
neither folder's `.env` may steer Cicada (`config.disable_dotenv` says the same for the `cicada` command). A release
(G182) has no such file: the bundle carries tracked files only, and `CICADA_DISTRIBUTION=release` turns the lookup
off outright. A release's settings are its environment (the launcher, the plist), the app's own preferences, and
provider keys in `$CICADA_HOME/secrets.env`.

**What it did before.** Nothing on purpose. pydantic's `env_file` was `".env"`, relative to the cwd, so it read no
file in the backend. What made the file work at all was litellm's import-time `load_dotenv()`, which walks up from
litellm's own folder: with the virtualenv at `<checkout>/api/.venv` it reached `api/.env` and copied every key into
`os.environ`. A venv anywhere else read nothing, a worktree sharing the main venv read the MAIN checkout's file, and
nothing could tell a value from the file apart from one in the environment.

**What `load` does.** Turns litellm's own load off for good (`LITELLM_MODE=PRODUCTION`, which no file can undo), then
fills the process environment from this file — the environment always wins, as it did — so the code that reads
`os.environ` directly (the outbound gates, telemetry, the API token, provider keys for litellm) sees the same values
`Settings` does. The keys that land in `os.environ` are exactly the ones litellm's load put there; every CLI child
still runs under `connections.base.scrubbed_env`. It records which `CICADA_` names came from where, by NAME only, for
`GET /status`; a value never leaves this module.
"""
from __future__ import annotations

import os
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path

#: The file's name inside this package's folder, and the one way `/status` and the docs refer to it.
DISPLAY_NAME = "api/.env"

#: Names the settings file can never set: the switch that keeps litellm's walk-up `.env` load off.
CONTROL_KEYS = ("LITELLM_MODE",)

_PREFIX = "CICADA_"


@dataclass(frozen=True)
class Sources:
    """Where each `CICADA_` setting came from, names only. `file` is `DISPLAY_NAME` when a file was read."""
    file: str | None = None
    from_file: tuple[str, ...] = ()
    from_environment: tuple[str, ...] = ()
    replaced_by_environment: tuple[str, ...] = ()
    other_keys_from_file: int = field(default=0)


_disabled = False
_sources: Sources | None = None


def disable() -> None:
    """Read no settings file from now on (the `cicada` command, which overlays the file itself, and the test suite)."""
    global _disabled
    _disabled = True


def path(environ: MutableMapping[str, str] | None = None, package_dir: Path | None = None) -> Path | None:
    """`<checkout>/api/.env` as an absolute path, whether or not it exists; `None` in a release or when disabled."""
    env = os.environ if environ is None else environ
    if _disabled or (env.get("CICADA_DISTRIBUTION") or "").strip() == "release":
        return None
    base = Path(os.path.dirname(os.path.abspath(__file__))) if package_dir is None else Path(package_dir)
    return base / ".env"


def load(environ: MutableMapping[str, str] | None = None, file: Path | None = None) -> Sources:
    """Fill ``environ`` from the settings file, the environment winning; record the names. Never raises."""
    global _sources
    env = os.environ if environ is None else environ
    env["LITELLM_MODE"] = "PRODUCTION"
    target = path(env) if file is None else file
    present = {k for k in env if k.startswith(_PREFIX)}
    from_file: list[str] = []
    replaced: list[str] = []
    others = 0
    read = False
    if target is not None and target.is_file():
        try:
            from dotenv import dotenv_values

            values = dotenv_values(target)
            read = True
        except Exception:  # noqa: BLE001 - an unreadable settings file never stops the backend
            values = {}
        for key, value in values.items():
            if value is None or key in CONTROL_KEYS:
                continue
            if key in env:
                if key.startswith(_PREFIX):
                    replaced.append(key)
                continue
            env[key] = value
            if key.startswith(_PREFIX):
                from_file.append(key)
            else:
                others += 1
    _sources = Sources(
        file=DISPLAY_NAME if read else None,
        from_file=tuple(sorted(from_file)),
        from_environment=tuple(sorted(present)),
        replaced_by_environment=tuple(sorted(replaced)),
        other_keys_from_file=others,
    )
    return _sources


def sources() -> Sources:
    """What the last `load` recorded; an empty record when this process never loaded (a test, the MCP server)."""
    return _sources or Sources()


def log_summary() -> None:
    """One startup line, names only: what the file set and what the environment replaced."""
    from loguru import logger

    src = sources()
    if src.file is None:
        logger.info("Settings file: none read — settings come from the environment and Cicada's defaults")
        return
    replaced = ", ".join(src.replaced_by_environment) or "none"
    logger.info(f"Settings file {src.file}: {len(src.from_file)} setting(s) read "
                f"({', '.join(src.from_file) or 'none'}); replaced by the environment: {replaced}")
