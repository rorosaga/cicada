"""Skills that drive a command-line tool of their own (browser-harness, macos-harness): the tool's version, where it
came from, the skill text it prints, and the macOS permissions its doctor reports (the Skills page, owner 2026-10-15).

Both harnesses are uv tools. Measured on the owner's Mac (shape only): the tool lives in uv's tool folder with a
receipt (``~/.local/share/uv/tools/<name>/uv-receipt.toml``) naming where it came from (a git URL); ``uv tool list``
shows its version (the CLI itself has no reliable ``--version``); its skill text is what ``<tool> skill`` prints,
written to the agent's ``SKILL.md`` — and a ``uv tool upgrade`` does **not** rewrite that file, so the text an agent
reads can be older than the tool it drives. That is the state this module detects: the installed SKILL.md compared
with what the installed tool prints now (or, for a copy Cicada wrote, the tool version in its marker).

``macos-harness doctor`` prints JSON without prompting: ``{ready, app, granted: {kind: bool}, missing}``
(``permissions.doctor`` in its source, v0.2.1). macOS grants these to *the app that starts the harness* and the
report names it (``app``): run from Cicada's backend it speaks for the backend, not for the person's terminal, so the
page always shows whose permissions they are.

Every command is an argv (never a shell), resolved like every vendor CLI (``connections.base.resolve_binary``), with
the scrubbed environment and ``CICADA_CAPTURE=off`` (``run_cli``), and a short timeout. ``RUNNER`` is swapped by the
suite so no test ever runs a real tool (conftest).
"""
from __future__ import annotations

import json
import re
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

from api.services import skill_folders
from api.services.connections import base

RUNNER = base.run_cli
#: Where a command lives, or ``None``. Swapped with ``RUNNER`` by the suite.
WHICH = base.resolve_binary
LIST_TTL_S = 60.0
_cache: dict[str, tuple[float, object]] = {}

#: The official uv install (docs.astral.sh/uv): shown to copy, never run by Cicada.
UV_INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"
UV_INSTALL_COMMAND = "curl -LsSf https://astral.sh/uv/install.sh | sh"

#: What each permission lets the tool do, in plain words (macos-harness's own `why`, shortened).
PERMISSION_WORDS = {
    "accessibility": "Accessibility",
    "screen_recording": "Screen Recording",
    "post_events": "sending clicks and keys",
    "input_monitoring": "Input Monitoring",
}


@dataclass(frozen=True)
class Tool:
    """A catalog entry's ``tool`` block."""

    command: str
    package: str
    skill_args: tuple[str, ...] = ("skill",)
    doctor_args: tuple[str, ...] = ()
    repo: str = ""

    @classmethod
    def from_entry(cls, entry: dict) -> "Tool | None":
        block = entry.get("tool")
        if not isinstance(block, dict) or not block.get("command"):
            return None
        pin = entry.get("pin") or {}
        return cls(command=str(block["command"]), package=str(block.get("package") or block["command"]),
                   skill_args=tuple(block.get("skill") or ("skill",)), doctor_args=tuple(block.get("doctor") or ()),
                   repo=str(pin.get("repo") or ""))


def clear_cache() -> None:
    _cache.clear()


async def _run(argv: list[str], timeout: float) -> base.CliResult:
    return await RUNNER(argv, timeout=timeout)


def uv_present() -> bool:
    return WHICH("uv") is not None


_LIST_LINE = re.compile(r"^([A-Za-z0-9._-]+)\s+v?([0-9][^\s]*)")


def parse_tool_list(text: str) -> dict[str, str]:
    """``uv tool list`` → ``{package: version}``. Lines starting ``-`` are a tool's commands."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        if not line or line.startswith(("-", " ")):
            continue
        m = _LIST_LINE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


async def tool_versions() -> dict[str, str] | None:
    """Every uv tool's version, or ``None`` when uv is missing or did not answer. Cached a minute."""
    hit = _cache.get("uv-list")
    if hit and time.monotonic() - hit[0] < LIST_TTL_S:
        return hit[1]  # type: ignore[return-value]
    if not uv_present():
        return None
    result = await _run(["uv", "tool", "list"], 10.0)
    value = parse_tool_list(result.stdout) if result.rc == 0 else None
    _cache["uv-list"] = (time.monotonic(), value)
    return value


def receipt(package: str, home: Path | None = None) -> dict:
    """Where uv installed a tool from, read from its receipt: ``{git, version, specifier}`` (any may be missing)."""
    home = home or skill_folders.home()
    path = home / ".local" / "share" / "uv" / "tools" / package / "uv-receipt.toml"
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    reqs = ((data.get("tool") or {}).get("requirements")) or []
    first = next((r for r in reqs if isinstance(r, dict) and r.get("name") == package), None) or \
        (reqs[0] if reqs and isinstance(reqs[0], dict) else {})
    out = {}
    for key in ("git", "specifier", "editable", "directory", "url"):
        if isinstance(first.get(key), str):
            out[key] = first[key]
    return out


def repo_from_git(url: str) -> str | None:
    """``https://github.com/o/r(.git)(@ref)`` → ``o/r``."""
    m = re.match(r"^(?:git\+)?https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:[@#?].*)?$",
                 url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


async def skill_text(tool: Tool) -> str | None:
    """What the installed tool prints as its skill, or ``None`` when it is missing or failed. Cached a minute."""
    key = f"skill:{tool.command}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < LIST_TTL_S:
        return hit[1]  # type: ignore[return-value]
    result = await _run([tool.command, *tool.skill_args], 8.0)
    text = result.stdout if result.rc == 0 and result.stdout.strip() else None
    _cache[key] = (time.monotonic(), text)
    return text


async def doctor(tool: Tool) -> dict | None:
    """The tool's permission report in words: ``{app, ready, items: [{id, label, granted}]}``, or ``None``."""
    if not tool.doctor_args:
        return None
    key = f"doctor:{tool.command}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < LIST_TTL_S:
        return hit[1]  # type: ignore[return-value]
    result = await _run([tool.command, *tool.doctor_args], 8.0)
    value = parse_doctor(result.stdout) if result.rc in (0, 1) else None
    _cache[key] = (time.monotonic(), value)
    return value


def parse_doctor(text: str) -> dict | None:
    try:
        data = json.loads(text or "")
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("granted"), dict):
        return None
    items = [{"id": k, "label": PERMISSION_WORDS.get(k, k.replace("_", " ")), "granted": bool(v)}
             for k, v in data["granted"].items() if isinstance(k, str)]
    return {"app": str(data.get("app") or ""), "ready": bool(data.get("ready")), "items": items}


def permissions_line(report: dict | None) -> str | None:
    """What macOS has granted, in words. The check runs from Cicada, so the page labels it "Checked for Cicada" and
    says an agent in another app may have different permissions (owner 2026-10-15)."""
    if not report:
        return None
    granted = [i["label"] for i in report["items"] if i["granted"]]
    missing = [i["label"] for i in report["items"] if not i["granted"]]
    if not missing:
        return f"{_join(granted)}: allowed." if granted else "Nothing to allow."
    return f"Not allowed yet: {_join(missing)}."


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def version_tuple(raw: str | None) -> tuple[int, ...] | None:
    m = re.match(r"^v?(\d+(?:\.\d+)*)", (raw or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def newer(latest: str | None, installed: str | None) -> bool:
    a, b = version_tuple(latest), version_tuple(installed)
    return bool(a and b and a > b)


def install_argv(repo: str, sha: str, package: str) -> list[str]:
    """uv's install of one tool, pinned to a commit of its GitHub source (the receipt then names that URL, as the
    owner's own install does). ``--force`` replaces an older install of the same tool."""
    return ["uv", "tool", "install", "--python", "3.12", "--force", f"git+https://github.com/{repo}@{sha}"]
