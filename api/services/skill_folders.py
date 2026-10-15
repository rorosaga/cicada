"""Where each coding agent keeps its skills, and how Cicada reads a skill folder (the Skills page, owner 2026-10-15).

Read-only. Every write into these folders is ``skill_store``'s (the one writer); this module only names them and
reads them, so the inventory and the writer can never disagree about a path.

**The table** is ``agent_wiring.AGENTS`` — the one list of the person's agents (owner 2026-10-15), each with the
user-level skills folder its own docs name and the folders it also reads. Cicada never installs into a project.

So a skill is **on** for an agent when its own folder has it, **through** another folder when only a folder it also
reads has it (Cursor sees Claude Code's skills), and **off** otherwise. ``~/.agents/skills`` is the shared folder:
`npx skills` keeps its canonical copies there and four of the five agents read it.

The home is ``skill_catalog.agent_home()`` — the suite points it at a tmp dir, so no test reads a developer's own
``~/.claude`` (conftest).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from api.services import agent_wiring, skill_catalog

MARKER = ".cicada-managed.json"
SKILL_FILE = "SKILL.md"
SHARED = ".agents/skills"
#: What a SKILL.md read keeps; a bigger file still counts as a skill, with its text cut.
MAX_SKILL_BYTES = 256 * 1024
MAX_DIRS_PER_ROOT = 400
#: A folder copied between agents or into the library: never more than this.
MAX_FILES = 64
MAX_TOTAL_BYTES = 5 * 1024 * 1024
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class Agent:
    id: str
    label: str
    home: str                  # HOME-relative; its existence means the agent is on this Mac
    own: str                   # HOME-relative skills folder Cicada writes for this agent
    reads: tuple[str, ...]     # other folders it reads skills from


#: Derived from ``agent_wiring.AGENTS``, the one list of the person's agents; an agent with no skills folder is left out.
AGENTS: tuple[Agent, ...] = tuple(Agent(a.id, a.label, a.home, a.skills, a.reads)
                                  for a in agent_wiring.AGENTS if a.skills)
BY_ID = {a.id: a for a in AGENTS}
#: `npx skills -a` names for the same agents (vercel-labs/skills README's table).
NPX_AGENT = {"claude-code": "claude-code", "claude": "claude-code", "codex": "codex", "cursor": "cursor",
             "opencode": "opencode", "hermes-agent": "hermes", "openclaw": "openclaw", "gemini-cli": "gemini-cli"}


def home() -> Path:
    return skill_catalog.agent_home()


def present(base: Path | None = None) -> list[Agent]:
    """The agents on this Mac: those whose home folder exists. An agent that isn't installed is hidden (owner)."""
    base = base or home()
    return [a for a in AGENTS if (base / a.home).is_dir()]


def folder_label(rel: str) -> str:
    """A skills folder in words, for "through …"."""
    if rel == SHARED:
        return "the shared skills folder"
    owner = next((a for a in AGENTS if a.own == rel), None)
    return f"{owner.label}'s folder" if owner else rel


def roots(base: Path | None = None) -> list[str]:
    """Every folder worth scanning (HOME-relative): each listed agent's own folder and the shared one."""
    seen: list[str] = []
    for agent in present(base):
        for rel in (agent.own, *agent.reads):
            if rel not in seen:
                seen.append(rel)
    return seen


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def frontmatter(text: str) -> dict:
    """A SKILL.md's YAML frontmatter as a map; ``{}`` when there is none or it does not parse."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def one_line(text: str, limit: int = 200) -> str:
    words = " ".join(str(text or "").split())
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def read_marker(folder: Path) -> dict | None:
    """Cicada's marker in a skill folder: the v2 map, or the app's old ``{sha256, source}`` read as Cicada's own."""
    path = folder / MARKER
    if path.is_symlink() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("sha256"), str):
        return None
    if "v" not in data:   # written by the app's SkillInstaller before the Skills page
        data = {"v": 1, "origin": "cicada", "sha256": data["sha256"], "source": str(data.get("source") or ""),
                "files": {SKILL_FILE: data["sha256"]}}
    data.setdefault("files", {SKILL_FILE: data["sha256"]})
    return data


@dataclass
class Copy:
    """One skill folder found in one agent folder."""

    name: str
    root: str                 # HOME-relative folder it sits in
    path: Path
    linked: bool              # the folder itself is a symlink (`npx skills` links into the shared folder)
    skill_sha: str
    meta: dict
    marker: dict | None
    text: str = ""

    @property
    def cicadas(self) -> bool:
        """Written by Cicada and unchanged since: every file still matches its marker."""
        if self.linked or not self.marker:
            return False
        listed = self.marker.get("files") or {}
        try:
            present = {p.relative_to(self.path).as_posix() for p in self.path.rglob("*")
                       if p.is_file() and p.name not in (MARKER, ".DS_Store")}
        except OSError:
            return False
        if present != set(listed):   # a file the person added is theirs: never Cicada's to delete
            return False
        for rel, digest in listed.items():
            target = self.path / rel
            try:
                if target.is_symlink() or sha256(target.read_bytes()) != digest:
                    return False
            except OSError:
                return False
        return True


def read_copy(root: str, folder: Path) -> Copy | None:
    skill = folder / SKILL_FILE
    try:
        if not skill.is_file():
            return None
        raw = skill.read_bytes()
    except OSError:
        return None
    text = raw[:MAX_SKILL_BYTES].decode("utf-8", "replace")
    return Copy(name=folder.name, root=root, path=folder, linked=folder.is_symlink(), skill_sha=sha256(raw),
                meta=frontmatter(text), marker=read_marker(folder), text=text)


def scan(base: Path | None = None) -> list[Copy]:
    """Every skill folder in every folder an agent on this Mac reads. Hidden folders and anything that is not a
    folder with a SKILL.md are skipped; a symlinked skill folder is read through, never followed for anything else."""
    base = base or home()
    out: list[Copy] = []
    for rel in roots(base):
        folder = base / rel
        try:
            entries = sorted(folder.iterdir())[:MAX_DIRS_PER_ROOT] if folder.is_dir() else []
        except OSError:
            entries = []
        for entry in entries:
            if entry.name.startswith(".") or not NAME.match(entry.name):
                continue
            copy = read_copy(rel, entry)
            if copy:
                out.append(copy)
    return out


def folder_files(folder: Path) -> dict[str, bytes] | None:
    """Every file under a skill folder, relative path → bytes, for a copy into another agent's folder or the library.
    ``None`` when it holds a symlink inside, too many files or too many bytes — such a folder is not copied."""
    files: dict[str, bytes] = {}
    total = 0
    try:
        base = folder.resolve()
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".git")]
            for name in filenames:
                if name == MARKER or name == ".DS_Store":
                    continue
                path = Path(dirpath) / name
                if path.is_symlink():
                    return None
                data = path.read_bytes()
                total += len(data)
                files[path.relative_to(base).as_posix()] = data
                if len(files) > MAX_FILES or total > MAX_TOTAL_BYTES:
                    return None
    except OSError:
        return None
    return files if SKILL_FILE in files else None


@dataclass
class AgentState:
    agent: Agent
    state: str                     # on | through | off
    through: str | None = None     # HOME-relative folder it is seen through
    copies: list[Copy] = field(default_factory=list)


def agent_states(copies: list[Copy], agents: list[Agent]) -> list[AgentState]:
    by_root = {c.root: c for c in copies}
    out = []
    for agent in agents:
        if agent.own in by_root:
            out.append(AgentState(agent, "on", copies=[by_root[agent.own]]))
            continue
        seen = next((rel for rel in agent.reads if rel in by_root), None)
        out.append(AgentState(agent, "through", through=seen) if seen else AgentState(agent, "off"))
    return out
