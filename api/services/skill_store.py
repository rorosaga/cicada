"""The one writer for skills (the Skills page, owner 2026-10-15): every byte a skill's install, update, toggle,
refresh, removal or publish writes goes through this module — the backend's routes, the stdio MCP tools and the
``cicada`` command all call it, so the three doors cannot disagree.

**What it writes, and where.** All of it outside every bank:

- an agent's own skills folder (``skill_folders.AGENTS``): one folder per skill, every file plus a
  ``.cicada-managed.json`` marker naming the source, the commit (or tool version) and each file's sha256;
- ``$CICADA_HOME/skills/library/<name>/`` — Cicada's own pinned copy of each skill it installed, so turning one on
  for another agent later needs no fetch, and a skill turned off everywhere keeps its row;
- ``$CICADA_HOME/skills/drafts/<name>/`` — skills an agent made, held until the person publishes them (G112);
- ``$CICADA_HOME/skills/{requests,updates,onboarding}.json`` — agents' asks, the last update check, the onboarding
  answer; ``removed/`` — anything Cicada took out of an agent's folder that it had not written itself, kept so it
  can be put back (a turn-off or a refresh never destroys the person's own copy).

**What it never writes:** a bank, an agent's settings or hooks (a skill is text an agent loads when it chooses; a
hook runs on every turn, and stays the person's own install), or anything through a symlink — a linked skill folder
(``npx skills`` links agents to ``~/.agents/skills``) is unlinked, never followed.

**Consent.** Third-party code arrives only from ``install_plan`` (a preview the person saw, pinned to its commit) or
``install_tool`` (a catalog tool pinned to a commit), and only the person's route or command calls them — no MCP tool
does (``mcp_tools.propose_skill`` files a request instead). Turning a skill on or off, and refreshing a tool's skill
text from the tool the person installed, bring in no new code.

One file lock (``$CICADA_HOME/skills/.lock``) serialises writers across processes; every folder lands by a rename.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from api.services import skill_folders, skill_tools
from api.services.auth import cicada_home

REPO_ROOT = Path(__file__).resolve().parents[2]
#: Cicada's own two skills, read from the checkout (a release app ships them in its backend too, G182).
OWN_BUNDLES = {"cicada": "SKILL.md", "cicada-librarian": "skills/cicada-librarian/SKILL.md"}
MAX_REQUESTS = 50
MAX_DRAFT_BODY = 40_000
MAX_DESCRIPTION = 1024


class StoreError(ValueError):
    """A write the store refuses, with a sentence for the person (or the agent)."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def state_dir() -> Path:
    path = cicada_home() / "skills"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


@contextlib.contextmanager
def _locked():
    lock = state_dir() / ".lock"
    with open(lock, "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not skill_folders.NAME.match(name):
        raise StoreError("A skill's name is letters, digits, dots, dashes and underscores, up to 64 characters.")
    return name


def _read_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# --------------------------------------------------------------------------- folders


def marker(name: str, files: dict[str, bytes], source: dict) -> dict:
    hashes = {rel: skill_folders.sha256(data) for rel, data in sorted(files.items())}
    keep = {k: v for k, v in source.items() if k in ("origin", "repo", "path", "ref", "commit", "pathCommit",
                                                       "licence", "tool", "toolVersion", "author", "from",
                                                       "catalogId", "source", "updatedAt") and v not in (None, "")}
    return {"v": 2, "name": name, **keep, "files": hashes, "sha256": hashes[skill_folders.SKILL_FILE],
            "installedAt": now_iso()}


def _safe_rel(rel: str) -> str:
    parts = [p for p in rel.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts) or rel.startswith("/"):
        raise StoreError("A file in that skill has a path Cicada won't write.")
    return "/".join(parts)


def _write_folder(dest: Path, files: dict[str, bytes], mark: dict | None) -> None:
    """Write a whole skill folder beside ``dest`` and rename it into place (``dest`` must not exist)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / f".{dest.name}.cicada-{uuid.uuid4().hex[:8]}"
    try:
        tmp.mkdir()
        for rel, data in files.items():
            target = tmp / _safe_rel(rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            if data.startswith(b"#!"):
                os.chmod(target, 0o755)
        if mark is not None:
            (tmp / skill_folders.MARKER).write_text(json.dumps(mark, indent=2, sort_keys=True) + "\n",
                                                    encoding="utf-8")
        os.rename(tmp, dest)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _set_aside(path: Path, why: str) -> None:
    """Take a skill folder out of an agent's folder: a link is unlinked, Cicada's own unchanged copy is deleted, and
    anything else is moved to ``removed/`` so the person can put it back."""
    if path.is_symlink():
        path.unlink()
        return
    if not path.exists():
        return
    copy = skill_folders.read_copy("", path)
    if copy is not None and copy.cicadas:
        shutil.rmtree(path)
        return
    keep = removed_dir() / f"{path.name}-{why}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
    keep.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(keep))


def _place(dest: Path, files: dict[str, bytes], mark: dict, why: str) -> None:
    if dest.exists() or dest.is_symlink():
        _set_aside(dest, why)
    _write_folder(dest, files, mark)


def removed_dir() -> Path:
    """Where everything Cicada takes away is kept, restorable (a library copy, or a copy it did not write)."""
    return state_dir() / "removed"


def library_dir() -> Path:
    return state_dir() / "library"


_MARKER_ONLY = ("files", "sha256", "v", "name")


def source_from_marker(mark: dict | None) -> dict:
    """A marker's source fields (origin, repo, commit, tool…), without its bookkeeping."""
    return {k: v for k, v in (mark or {}).items() if k not in _MARKER_ONLY}


def library() -> dict[str, dict]:
    """``{name: source}`` for every skill in Cicada's library (read from its marker)."""
    out: dict[str, dict] = {}
    root = library_dir()
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and not entry.is_symlink() and skill_folders.NAME.match(entry.name):
            if (entry / skill_folders.SKILL_FILE).is_file():
                out[entry.name] = source_from_marker(skill_folders.read_marker(entry)) or {"origin": "local"}
    return out


def library_files(name: str) -> dict[str, bytes] | None:
    folder = library_dir() / name
    if folder.is_symlink() or not folder.is_dir():
        return None
    return skill_folders.folder_files(folder)


def _save_library(name: str, files: dict[str, bytes], source: dict) -> None:
    dest = library_dir() / name
    if dest.exists():
        shutil.rmtree(dest)
    _write_folder(dest, files, marker(name, files, source))


def _own(agent_id: str, base: Path | None = None) -> Path:
    """An agent's own skills folder — only for an agent installed on this Mac (its home folder exists). Writing a
    skill for one that isn't would create its folders and make it look installed."""
    agent = skill_folders.BY_ID.get(agent_id)
    if agent is None:
        raise StoreError(f"Cicada doesn't know an agent called {agent_id}.")
    base = base or skill_folders.home()
    if not (base / agent.home).is_dir():
        raise StoreError(f"{agent.label} isn't installed on this Mac, so Cicada won't add skills for it.")
    return base / agent.own


def _copies(name: str, base: Path | None = None) -> list[skill_folders.Copy]:
    return [c for c in skill_folders.scan(base) if c.name == name]


def _source_of(name: str, base: Path | None = None) -> dict:
    src = library().get(name)
    if src:
        return src
    for copy in _copies(name, base):
        if copy.marker:
            return source_from_marker(copy.marker)
    return {"origin": "local"}


def install_files(name: str, files: dict[str, bytes], source: dict, agents: list[str], *,
                  base: Path | None = None) -> list[str]:
    """Put one skill into the library and into each agent's own folder. A copy already there is replaced: a link is
    unlinked, Cicada's own copy rewritten, anything else kept in ``removed/``. Returns the agents written."""
    name = _check_name(name)
    if skill_folders.SKILL_FILE not in files:
        raise StoreError("That skill has no SKILL.md.")
    if len(files) > skill_folders.MAX_FILES or sum(map(len, files.values())) > skill_folders.MAX_TOTAL_BYTES:
        raise StoreError("That skill is bigger than Cicada adds.")
    for rel in files:
        _safe_rel(rel)
    mark = marker(name, files, source)
    for agent in dict.fromkeys(agents):
        _own(agent, base)              # every agent checked before anything is written
    written = []
    with _locked():
        _save_library(name, files, source)
        for agent in dict.fromkeys(agents):
            _place(_own(agent, base) / name, files, mark, "replaced")
            written.append(agent)
    return written


def install_plan(plan_id: str, agents: list[str], *, base: Path | None = None) -> dict:
    """Install a previewed skill exactly as shown (``skill_sources.take``), pinned to its commit."""
    from api.services import skill_sources

    plan = skill_sources.take(plan_id)
    if plan is None:
        raise StoreError("That preview is too old. Paste the address again to see it fresh.")
    if not agents:
        raise StoreError("Choose at least one agent.")
    written = install_files(plan.name, plan.files, plan.source, agents, base=base)
    return {"name": plan.name, "agents": written, "commit": plan.source.get("commit")}


def turn_on(name: str, agent: str, *, base: Path | None = None) -> None:
    """Give one agent a skill another agent (or the library) already has. No fetch, no new code."""
    name = _check_name(name)
    dest = _own(agent, base) / name
    with _locked():
        if dest.exists():
            return
        files = library_files(name)
        source = library().get(name)
        if files is None:
            copy = next((c for c in _copies(name, base) if skill_folders.folder_files(c.path) is not None), None)
            if copy is None:
                raise StoreError(f"Cicada has no copy of {name} to give another agent.")
            files = skill_folders.folder_files(copy.path) or {}
            source = source_from_marker(copy.marker) or {"origin": "copied", "from": copy.root}
            _save_library(name, files, source)
        _write_folder(dest, files, marker(name, files, source or {"origin": "local"}))


def turn_off(name: str, agent: str, *, base: Path | None = None) -> None:
    """Take a skill away from one agent. The library keeps a copy so it can come back with one click."""
    name = _check_name(name)
    dest = _own(agent, base) / name
    with _locked():
        if not (dest.exists() or dest.is_symlink()):
            return
        if name not in library():
            files = skill_folders.folder_files(dest)
            if files is not None:
                copy = skill_folders.read_copy("", dest)
                source = source_from_marker(copy.marker if copy else None) or {"origin": "local"}
                _save_library(name, files, source)
        _set_aside(dest, "off")


def remove(name: str, *, base: Path | None = None) -> list[str]:
    """Remove a skill from every agent's own folder and the shared folder. Never a permanent delete: the library
    copy (made first from an agent's copy when there is none) moves to ``removed/``, so the skill's text can always be
    put back — a published draft's only text lives there, and an unchanged agent copy is deleted as its duplicate."""
    name = _check_name(name)
    base = base or skill_folders.home()
    gone = []
    with _locked():
        lib = library_dir() / name
        if not lib.exists():
            copy = next((c for c in _copies(name, base) if skill_folders.folder_files(c.path) is not None), None)
            if copy is not None:
                _save_library(name, skill_folders.folder_files(copy.path) or {},
                              source_from_marker(copy.marker) or {"origin": "local"})
        for rel in dict.fromkeys([a.own for a in skill_folders.AGENTS] + [skill_folders.SHARED]):
            path = base / rel / name
            if path.exists() or path.is_symlink():
                _set_aside(path, "removed")
                gone.append(rel)
        if lib.exists():
            keep = removed_dir() / f"{name}-library-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(lib), str(keep))
    return gone


# --------------------------------------------------------------------------- tools (browser-harness, macos-harness)


def write_tool_text(name: str, text: str, tool: str, version: str | None, repo: str, agents: list[str], *,
                    catalog_id: str | None = None, base: Path | None = None) -> list[str]:
    """Write the skill text a tool printed into each agent that has it (and the library). An older text Cicada did
    not write is kept in ``removed/`` — "the old one is kept"."""
    if not text.strip():
        raise StoreError("The tool printed no skill text.")
    files = {skill_folders.SKILL_FILE: text.encode("utf-8")}
    source = {"origin": "tool", "tool": tool, "toolVersion": version, "repo": repo, "catalogId": catalog_id}
    return install_files(name, files, source, agents, base=base)


async def install_tool(entry: dict, agents: list[str], *, sha: str | None = None,
                       base: Path | None = None) -> dict:
    """Install (or update) a catalog tool with uv, pinned to a commit of its GitHub source, then write the skill text
    it prints into each chosen agent. Runs only on the person's route or command."""
    tool = skill_tools.Tool.from_entry(entry)
    pin = entry.get("pin") or {}
    if tool is None or not pin.get("repo"):
        raise StoreError("That skill isn't a tool Cicada knows how to install.")
    if not skill_tools.uv_present():
        raise StoreError("This needs uv, which isn't on this Mac yet. Install it, then try again.")
    commit = sha or pin.get("sha")
    result = await skill_tools.RUNNER(skill_tools.install_argv(pin["repo"], commit, tool.package), timeout=600.0)
    if result.rc != 0:
        tail = "\n".join((result.stderr or result.stdout or "").strip().splitlines()[-4:])
        raise StoreError(f"uv couldn't install {tool.package}." + (f" It said: {tail}" if tail else ""))
    skill_tools.clear_cache()
    text = await skill_tools.skill_text(tool)
    if not text:
        raise StoreError(f"{tool.command} installed, but it printed no skill text.")
    version = ((await skill_tools.tool_versions()) or {}).get(tool.package)
    name = str((entry.get("detect") or {}).get("skillDirs", [entry["id"]])[0])
    # No agent installed yet: the text waits in the library, and turning an agent on later gives it.
    written = write_tool_text(name, text, tool.command, version, pin["repo"], agents, catalog_id=entry.get("id"),
                              base=base)
    return {"name": name, "agents": written, "version": version, "commit": commit}


# --------------------------------------------------------------------------- Cicada's own skills


def own_bundle(name: str) -> bytes | None:
    rel = OWN_BUNDLES.get(name)
    if rel is None:
        return None
    try:
        return (REPO_ROOT / rel).read_bytes()
    except OSError:
        return None


def install_own(name: str, agents: list[str], *, base: Path | None = None) -> list[str]:
    data = own_bundle(name)
    if data is None:
        raise StoreError("Cicada can't find its own copy of that skill.")
    return install_files(name, {skill_folders.SKILL_FILE: data}, {"origin": "cicada", "source": OWN_BUNDLES[name]},
                         agents, base=base)


# --------------------------------------------------------------------------- drafts (made by your agents)


def drafts_dir() -> Path:
    return state_dir() / "drafts"


def skill_text(name: str, description: str, body: str) -> str:
    head = yaml.safe_dump({"name": name, "description": description}, sort_keys=False, allow_unicode=True,
                          width=10_000).strip()
    return f"---\n{head}\n---\n\n{body.strip()}\n"


def save_draft(name: str, description: str, body: str, *, author: str, session: str | None = None,
               reason: str = "", base: Path | None = None) -> dict:
    """An agent's skill, held: written only under ``drafts/``, never into an agent's folder."""
    name = _check_name(name.lower())
    description = " ".join((description or "").split())
    body = (body or "").strip()
    if not description:
        raise StoreError("A skill needs a one-line description: it is what an agent matches on.")
    if len(description) > MAX_DESCRIPTION:
        raise StoreError(f"Keep the description under {MAX_DESCRIPTION} characters.")
    if not body:
        raise StoreError("A skill needs its instructions (the body).")
    if len(body) > MAX_DRAFT_BODY:
        raise StoreError(f"Keep the instructions under {MAX_DRAFT_BODY:,} characters.")
    if any(c.name == name for c in skill_folders.scan(base)) or name in library():
        raise StoreError(f"A skill called {name} is already installed. Pick another name.")
    folder = drafts_dir() / name
    with _locked():
        meta = _read_json(folder / "draft.json", {})
        if meta and meta.get("author") not in (None, author):
            raise StoreError(f"Another agent already drafted a skill called {name}. Pick another name.")
        record = {"name": name, "author": author, "session": session or None, "reason": " ".join(reason.split()),
                  "created": meta.get("created") or now_iso(), "updated": now_iso(),
                  "revision": int(meta.get("revision") or 0) + 1, "state": "held"}
        text = skill_text(name, description, body)
        if folder.exists():
            shutil.rmtree(folder)
        _write_folder(folder, {skill_folders.SKILL_FILE: text.encode("utf-8"),
                               "draft.json": json.dumps(record, indent=2, sort_keys=True).encode()}, None)
    return record


def drafts() -> list[dict]:
    root = drafts_dir()
    out = []
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.is_symlink():
            continue
        meta = _read_json(entry / "draft.json", {})
        try:
            text = (entry / skill_folders.SKILL_FILE).read_text(encoding="utf-8")
        except OSError:
            continue
        fm = skill_folders.frontmatter(text)
        out.append({**meta, "name": entry.name, "description": str(fm.get("description") or ""), "text": text})
    return out


def publish_draft(name: str, agents: list[str], *, base: Path | None = None) -> list[str]:
    name = _check_name(name)
    folder = drafts_dir() / name
    meta = _read_json(folder / "draft.json", {})
    try:
        data = (folder / skill_folders.SKILL_FILE).read_bytes()
    except OSError:
        raise StoreError(f"There is no draft called {name}.") from None
    if not agents:
        raise StoreError("Choose at least one agent.")
    for agent in agents:
        _own(agent, base)              # refuse an agent that isn't on this Mac before anything is written
    written = install_files(name, {skill_folders.SKILL_FILE: data},
                            {"origin": "draft", "author": meta.get("author")}, agents, base=base)
    with _locked():
        shutil.rmtree(folder, ignore_errors=True)
    return written


def discard_draft(name: str) -> None:
    name = _check_name(name)
    with _locked():
        shutil.rmtree(drafts_dir() / name, ignore_errors=True)


# --------------------------------------------------------------------------- requests, updates, onboarding


def requests() -> list[dict]:
    return [r for r in _read_json(state_dir() / "requests.json", {}).get("requests", []) if isinstance(r, dict)]


def add_request(action: str, *, author: str, reason: str, name: str | None = None, source: str | None = None,
                agents: list[str] | None = None, session: str | None = None) -> dict:
    """An agent's ask, waiting for the person on the Skills page. The same ask again replaces the first."""
    entry = {"id": uuid.uuid4().hex[:12], "action": action, "name": name, "source": source,
             "agents": list(agents or []), "reason": " ".join((reason or "").split())[:500], "author": author,
             "session": session or None, "at": now_iso()}
    with _locked():
        current = [r for r in requests()
                   if not (r.get("action") == action and r.get("name") == name and r.get("source") == source)]
        current.append(entry)
        _write_json(state_dir() / "requests.json", {"requests": current[-MAX_REQUESTS:]})
    return entry


def close_request(request_id: str) -> bool:
    with _locked():
        current = requests()
        kept = [r for r in current if r.get("id") != request_id]
        if len(kept) == len(current):
            return False
        _write_json(state_dir() / "requests.json", {"requests": kept})
    return True


def updates() -> dict:
    return _read_json(state_dir() / "updates.json", {})


def save_updates(results: dict[str, dict]) -> dict:
    data = {"checkedAt": now_iso(), "results": results}
    with _locked():
        _write_json(state_dir() / "updates.json", data)
    return data


def onboarding() -> dict:
    return _read_json(state_dir() / "onboarding.json", {})


def save_onboarding(install: list[str], declined: list[str]) -> dict:
    data = {"answeredAt": now_iso(), "install": sorted(set(install)), "declined": sorted(set(declined))}
    with _locked():
        _write_json(state_dir() / "onboarding.json", data)
    return data
