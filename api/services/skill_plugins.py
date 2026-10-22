"""Claude Code's installed plugins and the skills each ships (G201 slice (a), TODO ruling 35, 2026-10-22).

The skills inventory read only skill folders (``skill_folders``); a plugin that ships several skills, at a version,
turned on or off, was invisible, so Cicada could not reason about the harness the person actually runs. This module
reads the plugins **read-only, from Claude Code's own files**:

- ``~/.claude/plugins/installed_plugins.json`` — ``{"version": 2, "plugins": {"<name>@<marketplace>": [{scope,
  installPath, version, installedAt, lastUpdated, gitCommitSha?, projectPath?}, …]}}``. The older flat
  ``{id: {…}}`` and ``{"plugins": {id: {…}}}`` shapes read too (as ``skill_catalog.claude_plugin_ids`` reads them).
- ``~/.claude/settings.json`` ``enabledPlugins`` — ``{id: true|false}``, the user-level switch. A plugin installed
  for one project is switched in that project's settings, which the backend never opens (the capture rail: it never
  reads a declared repo), so its ``enabled`` is ``None`` and said in words.
- each plugin's ``.claude-plugin/plugin.json`` (name, version) and its skills: ``skills/<name>/SKILL.md`` plus any
  folder the manifest's ``skills`` field adds (a ``./``-relative path or a list of them; custom paths supplement the
  default, Claude Code's plugin docs). Only each SKILL.md's frontmatter is read: ``name``, ``description`` and
  ``disable-model-invocation`` (such a skill is the person's to run, and its description is not loaded every session).

**Never an error.** A missing or corrupt file is an empty answer; an ``installPath`` that resolves outside
``~/.claude/plugins`` is not followed (its plugin is listed with no skills); a manifest path that escapes the plugin's
folder is skipped. **Never a write:** Cicada does not install, remove or toggle a plugin — the person does that in
Claude Code (``/plugin``) — so every row says ``canToggle: false``. The home is ``skill_catalog.agent_home()`` (a test
points it at a tmp dir; no test reads a developer's own ``~/.claude``).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from api.services import skill_folders

HARNESS = "claude-code"
PLUGINS_DIR = ".claude/plugins"
INSTALLED = "installed_plugins.json"
SETTINGS = ".claude/settings.json"
MANIFEST = ".claude-plugin/plugin.json"
#: Only the frontmatter is wanted; a SKILL.md's head is enough for it.
HEAD_BYTES = 16 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_PLUGINS = 200
MAX_SKILLS_PER_PLUGIN = 200
_PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}@[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")  # name@marketplace
NOTE = "Claude Code manages its plugins: turn one on or off there, with /plugin."
PROJECT_NOTE = "Installed for one project; it is switched in that project's settings, which Cicada doesn't read."


@dataclass
class PluginSkill:
    name: str
    description: str          # the whole frontmatter description (the weight counts it), not cut
    user_only: bool           # `disable-model-invocation: true`: only the person runs it; not loaded every session


@dataclass
class Plugin:
    id: str                   # "<name>@<marketplace>"
    name: str
    marketplace: str
    version: str
    scope: str                # user | project | local | "" (unknown)
    enabled: bool | None      # the user settings' switch; None when Claude Code keeps it elsewhere
    installed_at: str = ""
    updated_at: str = ""
    skills: list[PluginSkill] = field(default_factory=list)


def _read_json(path: Path) -> object:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _entries(data: object) -> dict[str, list[dict]]:
    """``{id: [install entries]}`` from any of the three shapes; anything else is ``{}``."""
    if not isinstance(data, dict):
        return {}
    table = data["plugins"] if isinstance(data.get("plugins"), dict) else data
    out: dict[str, list[dict]] = {}
    for key, value in table.items():
        if not isinstance(key, str) or not _PLUGIN_ID.match(key):
            continue
        rows = value if isinstance(value, list) else [value]
        rows = [r for r in rows if isinstance(r, dict)]
        out[key] = rows
    return out


def _pick(rows: list[dict]) -> dict:
    """The user-scope install when there is one (what every session loads), else the first."""
    return next((r for r in rows if r.get("scope") == "user"), rows[0] if rows else {})


def enabled_map(base: Path) -> dict[str, bool]:
    data = _read_json(base / SETTINGS)
    table = data.get("enabledPlugins") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return {}
    return {k: v for k, v in table.items() if isinstance(k, str) and isinstance(v, bool)}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def _skill_head(folder: Path) -> PluginSkill | None:
    path = folder / skill_folders.SKILL_FILE
    try:
        if not path.is_file():
            return None
        with path.open("rb") as handle:
            head = handle.read(HEAD_BYTES).decode("utf-8", "replace")
    except OSError:
        return None
    meta = skill_folders.frontmatter(head)
    name = str(meta.get("name") or folder.name).strip() or folder.name
    flag = meta.get("disable-model-invocation")
    return PluginSkill(name=name, description=" ".join(str(meta.get("description") or "").split()),
                       user_only=flag is True or str(flag).strip().lower() == "true")


def _skill_dirs(root: Path, manifest: dict) -> list[Path]:
    """``skills/`` plus the manifest's own ``skills`` paths, each kept only when it stays inside the plugin."""
    extra = manifest.get("skills")
    if isinstance(extra, str):
        paths = [extra]
    else:
        paths = [p for p in extra if isinstance(p, str)] if isinstance(extra, list) else []
    out = [root / "skills"]
    for rel in paths:
        rel = rel.strip()
        if not rel.startswith("./"):
            continue
        candidate = root / rel[2:]
        if _inside(candidate, root) and candidate not in out:
            out.append(candidate)
    return out


def _skills(root: Path, manifest: dict) -> list[PluginSkill]:
    found: list[PluginSkill] = []
    seen: set[str] = set()
    for folder in _skill_dirs(root, manifest):
        try:
            if not folder.is_dir():
                continue
            # A path may name one skill's own folder, or a folder of skills.
            own = _skill_head(folder)
            children = [] if own else sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            continue
        for item in ([own] if own else [s for s in (_skill_head(c) for c in children[:MAX_SKILLS_PER_PLUGIN]) if s]):
            if item.name not in seen:
                seen.add(item.name)
                found.append(item)
    return found[:MAX_SKILLS_PER_PLUGIN]


def read(base: Path | None = None) -> list[Plugin]:
    """Every plugin Claude Code records as installed, with its skills; ``[]`` when Claude Code is not on this Mac or
    its files are missing or do not parse."""
    base = base or skill_folders.home()
    plugins_root = base / PLUGINS_DIR
    table = _entries(_read_json(plugins_root / INSTALLED))
    if not table:
        return []
    switches = enabled_map(base)
    out: list[Plugin] = []
    for plugin_id, rows in list(table.items())[:MAX_PLUGINS]:
        entry = _pick(rows)
        name, _, marketplace = plugin_id.partition("@")
        scope = str(entry.get("scope") or "")
        install = entry.get("installPath")
        root = Path(install) if isinstance(install, str) and install else None
        usable = root is not None and root.is_absolute() and _inside(root, plugins_root) and root.is_dir()
        manifest = _read_json(root / MANIFEST) if usable else None
        manifest = manifest if isinstance(manifest, dict) else {}
        version = str(entry.get("version") or manifest.get("version") or "").strip()
        # A user-scope switch the settings file names; anything else (another scope, or not named) is unknown.
        enabled = switches.get(plugin_id) if scope in ("user", "") else None
        out.append(Plugin(id=plugin_id, name=str(manifest.get("name") or name), marketplace=marketplace,
                          version=version, scope=scope, enabled=enabled,
                          installed_at=str(entry.get("installedAt") or ""),
                          updated_at=str(entry.get("lastUpdated") or ""),
                          skills=_skills(root, manifest) if usable else []))
    return sorted(out, key=lambda p: p.id.lower())
