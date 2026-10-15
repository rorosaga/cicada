"""What the person's clicks on the Skills page do, as one body the routes and the ``cicada`` command share
(owner 2026-10-15). Every write is ``skill_store``'s; every fetch is ``skill_sources``'; this module decides which.

Only the person's door calls these: a route the app or a person-only CLI command hits. An agent's door
(``mcp_tools``) never reaches ``install_*`` or ``update`` — it files a request.
"""
from __future__ import annotations

from pathlib import Path

from api.services import skill_catalog, skill_folders, skill_inventory, skill_sources, skill_store, skill_tools

#: The suggestions onboarding offers: the two harnesses (ticked) and the video skill (not ticked), owner 2026-10-15.
ONBOARDING_IDS = ("browser-harness", "macos-harness", "watch")


def catalog_entry(entry_id: str) -> dict:
    entry = next((e for e in skill_catalog.load().get("skills", []) if e.get("id") == entry_id), None)
    if entry is None:
        raise skill_store.StoreError("Cicada's list of suggested skills has nothing by that name.")
    return entry


def default_agents(base: Path | None = None) -> list[str]:
    """Where a suggested skill goes when the person didn't choose: every agent installed on this Mac (none yet: the
    skill waits in the library)."""
    return [a.id for a in skill_folders.present(base)]


async def preview(text: str, choose: str | None = None) -> dict:
    source = skill_sources.parse(text)
    return await skill_sources.preview(source, choose=choose)


async def install_suggested(entry_id: str, agents: list[str], *, base: Path | None = None) -> dict:
    """A catalog suggestion, installed at its reviewed pin: a tool with uv, or the skill's folder at the commit."""
    if entry_id in skill_store.OWN_BUNDLES:
        return {"name": entry_id, "agents": skill_store.install_own(entry_id, agents or default_agents(base),
                                                                       base=base)}
    entry = catalog_entry(entry_id)
    method = skill_inventory.install_method(entry)
    agents = agents or default_agents(base)
    if method == "tool":
        return await skill_store.install_tool(entry, agents, base=base)
    if method != "copy":
        raise skill_store.StoreError("Your agent installs this one itself: copy the text shown and give it to it.")
    pin = entry["pin"]
    owner, repo = pin["repo"].split("/", 1)
    shown = await skill_sources.preview(skill_sources.Source(owner, repo, ref=pin["sha"], path=pin.get("path") or None))
    if "planId" not in shown:
        raise skill_store.StoreError("That suggestion's folder holds several skills; add it by its address instead.")
    plan = skill_sources.take(shown["planId"])
    if plan is not None:
        plan.source = {**plan.source, "ref": pin.get("ref") or plan.source.get("ref"), "catalogId": entry["id"]}
    return skill_store.install_plan(shown["planId"], agents, base=base)


def _agents_with(name: str, base: Path | None = None) -> list[str]:
    copies = [c for c in skill_folders.scan(base) if c.name == name]
    own = {a.own: a.id for a in skill_folders.AGENTS}
    return [own[c.root] for c in copies if c.root in own]


async def update(name: str, *, base: Path | None = None) -> dict:
    """Bring one installed skill up to upstream's newest, pinned to that commit, in every agent that has it."""
    base = base or skill_folders.home()
    copies = [c for c in skill_folders.scan(base) if c.name == name]
    lib = skill_store.library()
    if not copies and name not in lib:
        raise skill_store.StoreError(f"{name} isn't installed.")
    by_dir = skill_inventory._catalog_by_dir(skill_catalog.load())
    src = skill_inventory._source(name, copies, lib, skill_inventory.npx_lock(base), by_dir)
    agents = _agents_with(name, base)
    entry = by_dir.get(name) or {}
    if entry.get("tool"):
        repo = entry["pin"]["repo"]
        release = await skill_sources.latest_release(*repo.split("/", 1))
        if not release:
            raise skill_store.StoreError(f"{repo} has no release to update to.")
        sha = await skill_sources.resolve_commit(*repo.split("/", 1), release["tag"])
        return await skill_store.install_tool(entry, agents, sha=sha, base=base)
    if src.get("origin") == "cicada":
        return {"name": name, "agents": skill_store.install_own(name, agents, base=base)}
    repo = src.get("repo")
    if not repo or "/" not in str(repo):
        raise skill_store.StoreError(f"Cicada doesn't know where {name} came from, so it can't update it.")
    owner, rest = str(repo).split("/", 1)
    ref = src.get("ref")
    if ref and skill_tools.version_tuple(str(ref)):
        release = await skill_sources.latest_release(owner, rest)
        ref = release["tag"] if release else ref
    elif not ref or ref == src.get("commit") or src.get("origin") == "catalog":
        ref = (await skill_sources.repo_info(owner, rest))["defaultBranch"]
    shown = await skill_sources.preview(skill_sources.Source(owner, rest, ref=str(ref),
                                                             path=src.get("path") or None))
    if "planId" not in shown:
        raise skill_store.StoreError(f"{repo} now holds several skills there; add the one you want by its address.")
    result = skill_store.install_plan(shown["planId"], agents, base=base)
    _forget_update(name)
    return result


def _forget_update(name: str) -> None:
    saved = skill_store.updates()
    results = dict(saved.get("results") or {})
    if results.pop(name, None) is not None:
        skill_store.save_updates(results)


async def update_all(job: dict | None = None, *, base: Path | None = None) -> dict:
    saved = skill_store.updates().get("results") or {}
    names = [n for n, r in saved.items() if isinstance(r, dict) and r.get("state") == "available"]
    done, failed = [], {}
    for name in names:
        if job is not None:
            job["step"] = name
        try:
            await update(name, base=base)
            done.append(name)
        except (skill_store.StoreError, skill_sources.SourceError) as exc:
            failed[name] = str(exc)
    return {"updated": done, "failed": failed}


async def refresh(name: str, *, base: Path | None = None) -> dict:
    """Rewrite a tool skill's text from what the installed tool prints now, in every agent that has it."""
    entry = skill_inventory._catalog_by_dir(skill_catalog.load()).get(name) or {}
    tool = skill_tools.Tool.from_entry(entry)
    if tool is None:
        raise skill_store.StoreError(f"{name} doesn't come with a tool, so there is no newer text to take.")
    skill_tools.clear_cache()
    text = await skill_tools.skill_text(tool)
    if not text:
        raise skill_store.StoreError(f"{tool.command} isn't installed, or printed no skill text.")
    version = ((await skill_tools.tool_versions()) or {}).get(tool.package)
    agents = _agents_with(name, base)
    written = skill_store.write_tool_text(name, text, tool.command, version, entry["pin"]["repo"], agents,
                                          catalog_id=entry.get("id"), base=base)
    return {"name": name, "agents": written, "version": version}


def onboarding_offer(base: Path | None = None) -> dict:
    """What onboarding's skills step shows: each suggestion with its one line and what macOS or the browser will
    ask, ticked as the catalog says, plus whether uv is here and the person's earlier answer."""
    rows = []
    installed = {c.name for c in skill_folders.scan(base)}
    answer = skill_store.onboarding()
    declined = set(answer.get("declined") or []) if answer else set()
    for entry_id in ONBOARDING_IDS:
        try:
            entry = catalog_entry(entry_id)
        except skill_store.StoreError:
            continue
        ob = entry.get("onboarding") or {}
        dirs = set((entry.get("detect") or {}).get("skillDirs", []))
        rows.append({"id": entry_id, "title": ob.get("title") or entry.get("title"),
                     "line": ob.get("line") or entry.get("summary"), "skill": entry.get("title"),
                     # A saved answer wins: what the person declined starts off, everywhere, every later run.
                     "asks": ob.get("asks"),
                     "default": bool(ob.get("default")) and entry_id not in declined,
                     "declined": entry_id in declined,
                     "needsUv": skill_inventory.install_method(entry) == "tool",
                     "installed": bool(dirs & installed), "sourceUrl": entry.get("sourceUrl"),
                     "licence": entry.get("licence")})
    return {"suggestions": rows, "answer": skill_store.onboarding() or None,
            "uv": {"present": skill_tools.uv_present(), "installUrl": skill_tools.UV_INSTALL_URL,
                   "installCommand": skill_tools.UV_INSTALL_COMMAND},
            "agents": default_agents(base)}


async def onboarding_install(ids: list[str], agents: list[str], job: dict | None = None, *,
                             base: Path | None = None) -> dict:
    done, failed = [], {}
    for entry_id in ids:
        if job is not None:
            job["step"] = entry_id
        try:
            await install_suggested(entry_id, agents, base=base)
            done.append(entry_id)
        except (skill_store.StoreError, skill_sources.SourceError) as exc:
            failed[entry_id] = str(exc)
    return {"installed": done, "failed": failed}
