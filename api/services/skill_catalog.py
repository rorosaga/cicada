"""G138 — recommended agent skills: a reviewed catalog, install state read per
request, the command each agent's OWN installer takes, and the handshake lines
that tell an agent what to do in Cicada after a bridged skill ran.

The owner, 2026-09-23: "having recommended skills to install, for example …
claude-video that supposedly allows claude to see videos" (never the owner's
name in shipped code — `test_owner_name_portability.py`). Rails, each a test
(`test_skill_catalog.py`):

- the catalog is data a reviewer reads in a diff, like `logos.manifest.json`:
  every entry names its source, licence and the commit that was reviewed
  (R-O23), and never a person or a machine path;
- install state is DERIVED per request from `isfile()` on `SKILL.md` under the
  agents' skill roots and the KEYS of `~/.claude/plugins/installed_plugins.json`
  — never persisted, never a bank file, and no other agent config is opened: an
  MCP registration lives in files that also hold conversation history, so an
  MCP entry is `unknown` (R-O27);
- the backend never runs an installer and never writes into an agent's folders.
  It names the command; the app runs it after consent (R-O24, R-O26);
- a handshake line names only a tool that exists (R12), for an ACTIVE bridge:
  saving someone else's words through `cicada_save_episode` today files them as
  the owner's (`evidence.speaker_kind`), so the video and meeting bridges wait
  for Track Q's watch record and Track N's speaker-aware evidence (R-O28).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "recommended_skills.json"
AGENTS: tuple[str, ...] = ("claude-code", "codex")
KINDS = frozenset({"skill", "plugin", "mcp", "mcp-hosted"})
INSTALLED, NOT_INSTALLED, UNKNOWN = "installed", "not_installed", "unknown"
#: The only programs an install step may start — each agent's own CLI, and
#: `npx skills`, the cross-agent installer upstream READMEs document (R-O24).
PROGRAMS = frozenset({"claude", "codex", "npx"})
MAX_SHOWN = 5
MAX_BRIDGE_LINES = 3
#: Marks a card names before anyone has committed them (R-O29).
PENDING_MARKS = frozenset({"granola", "wispr-flow", "arxiv"})
_PLUGIN_ID = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$")
_SAFE_DIR = re.compile(r"^[A-Za-z0-9._-]+$")

#: Handshake text per ACTIVE bridge key; `{names}` becomes "`a` is" / "`a`, `b` are".
BRIDGE_TEXT: dict[str, str] = {
    "papers": "- Papers: {names} installed. After you look a paper up, save the one you relied on with "
              "`cicada_save_url(url)` so it joins the person's memory.",
}

_PUBLIC = ("id", "kind", "rank", "title", "summary", "why", "publisher", "sourceUrl", "licence",
           "mark", "symbol", "endpoint", "needs", "terms", "cicadaNote")


def agent_home() -> Path:
    """Where the agents keep their skills. A function so the suite points it at
    a tmp dir (conftest) — no test may read a developer's own `~/.claude`."""
    return Path.home()


def load(path: Path | None = None) -> dict[str, Any]:
    """The catalog, or an empty one — a broken file is logged, never raised."""
    try:
        data = json.loads((path or CATALOG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(f"skill_catalog: catalog unreadable ({type(exc).__name__})")
        return {"version": 0, "reviewedAt": "", "maxShown": MAX_SHOWN, "skills": []}
    data.setdefault("skills", [])
    return data


def _skill_roots(agent: str, home: Path) -> tuple[Path, ...]:
    if agent == "claude-code":
        return (home / ".claude" / "skills",)
    if agent == "codex":
        # Codex reads user skills from `$CODEX_HOME/skills` and `~/.agents/skills`
        # (openai/codex host_roots.rs); `npx skills -a codex -g` writes the first.
        return (home / ".codex" / "skills", home / ".agents" / "skills")
    return ()


def claude_plugin_ids(home: Path) -> frozenset[str]:
    """Installed Claude Code plugin ids, from the KEYS of
    `installed_plugins.json` only. Two shapes are accepted — `{"plugins": {id: …}}`
    and a flat `{id: …}`; anything else reads as no plugins, never an error."""
    path = home / ".claude" / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(data, dict):
        return frozenset()
    table = data["plugins"] if isinstance(data.get("plugins"), dict) else data
    return frozenset(k for k in table if isinstance(k, str) and _PLUGIN_ID.match(k))


def installed_state(entry: dict, home: Path, plugin_ids: frozenset[str] | None = None) -> dict[str, str]:
    detect = entry.get("detect") or {}
    dirs = [d for d in detect.get("skillDirs", []) if isinstance(d, str) and _SAFE_DIR.match(d) and d not in {".", ".."}]
    plugins = {p for p in detect.get("pluginIds", []) if isinstance(p, str)}
    if plugin_ids is None:
        plugin_ids = claude_plugin_ids(home)
    state: dict[str, str] = {}
    for agent in entry.get("agents", {}):
        if agent not in AGENTS:
            continue
        if entry.get("kind") in {"mcp", "mcp-hosted"}:
            state[agent] = UNKNOWN
            continue
        found = any((root / d / "SKILL.md").is_file() for root in _skill_roots(agent, home) for d in dirs)
        if agent == "claude-code" and plugins & plugin_ids:
            found = True
        state[agent] = INSTALLED if found else NOT_INSTALLED
    return state


def install_plan(entry: dict, agent: str) -> dict[str, Any]:
    """The agent's own installer command for this entry — argv lists, never a
    shell string. `CICADA_CAPTURE=off` rides on every plan (the app forces it
    again, R-O26)."""
    how = (entry.get("agents") or {}).get(agent) or {}
    pin = entry.get("pin") or {}
    env = {"CICADA_CAPTURE": "off"}
    method = how.get("method")
    if method == "plugin":
        return {"runnable": True, "env": env, "steps": [
            # Adding a marketplace that is already added may exit non-zero;
            # the install that follows is what must succeed.
            {"argv": ["claude", "plugin", "marketplace", "add", how["marketplace"]], "tolerateFailure": True},
            {"argv": ["claude", "plugin", "install", how["plugin"], "--scope", "user"], "tolerateFailure": False},
        ]}
    if method == "skills-cli":
        url = f"https://github.com/{pin['repo']}/tree/{pin['sha']}/{pin['path']}"
        return {"runnable": True, "env": env | {"DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"}, "steps": [
            {"argv": ["npx", "--yes", "skills", "add", url, "-g", "-a", agent, "-y"], "tolerateFailure": False},
        ]}
    if method == "mcp-stdio":
        command = list(how["command"])
        argv = (["claude", "mcp", "add", "--transport", "stdio", "--scope", "user", how["name"], "--", *command]
                if agent == "claude-code" else ["codex", "mcp", "add", how["name"], "--", *command])
        return {"runnable": True, "env": env, "steps": [{"argv": argv, "tolerateFailure": False}]}
    if method == "mcp-http":
        url = entry["endpoint"]
        argv = (["claude", "mcp", "add", "--transport", "http", "--scope", "user", how["name"], url]
                if agent == "claude-code" else ["codex", "mcp", "add", how["name"], "--url", url])
        # Copy-only: the sign-in is the agent's own OAuth (R-O24).
        return {"runnable": False, "env": env, "steps": [{"argv": argv, "tolerateFailure": False}]}
    return {"runnable": False, "env": env, "steps": []}


def _rank(entry: dict) -> tuple[int, str]:
    return (int(entry.get("rank", 999)), str(entry.get("id", "")))


def _view(entry: dict, home: Path, plugin_ids: frozenset[str]) -> dict[str, Any]:
    out = {k: entry[k] for k in _PUBLIC if k in entry}
    out["agents"] = [a for a in entry.get("agents", {}) if a in AGENTS]
    out["state"] = installed_state(entry, home, plugin_ids)
    out["install"] = {a: install_plan(entry, a) for a in out["agents"]}
    return out


def recommended(home: Path | None = None, catalog: dict | None = None) -> dict[str, Any]:
    """At most five entries not installed anywhere, by rank; then everything
    installed somewhere (shown, never counted against the five)."""
    home = home or agent_home()
    catalog = catalog or load()
    plugin_ids = claude_plugin_ids(home)
    views = [_view(e, home, plugin_ids) for e in sorted(catalog["skills"], key=_rank) if e.get("kind") in KINDS]
    installed = [v for v in views if INSTALLED in v["state"].values()]
    shown = min(int(catalog.get("maxShown", MAX_SHOWN) or MAX_SHOWN), MAX_SHOWN)
    return {
        "reviewedAt": catalog.get("reviewedAt", ""),
        "maxShown": shown,
        "catalogSize": len(views),
        "recommended": [v for v in views if INSTALLED not in v["state"].values()][:shown],
        "installed": installed,
    }


def bridge_lines(variant: str, home: Path | None = None, catalog: dict | None = None) -> list[str]:
    """At most one line per active bridge key with an installed entry in this
    agent. Never raises: the handshake must not fail on a catalog problem."""
    if variant not in AGENTS:
        return []
    try:
        home = home or agent_home()
        catalog = catalog or load()
        plugin_ids = claude_plugin_ids(home)
        grouped: dict[str, list[str]] = {}
        for entry in sorted(catalog["skills"], key=_rank):
            bridge = entry.get("bridge") or {}
            if not bridge.get("active") or bridge.get("key") not in BRIDGE_TEXT:
                continue
            if installed_state(entry, home, plugin_ids).get(variant) != INSTALLED:
                continue
            grouped.setdefault(bridge["key"], []).append(entry["id"])
        lines = []
        for key, ids in grouped.items():
            names = ", ".join(f"`{i}`" for i in ids) + (" is" if len(ids) == 1 else " are")
            lines.append(BRIDGE_TEXT[key].format(names=names))
        return lines[:MAX_BRIDGE_LINES]
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"skill_catalog: bridge lines skipped ({type(exc).__name__})")
        return []


def fingerprint(lines: list[str] | tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:12]
