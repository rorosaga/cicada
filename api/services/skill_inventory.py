"""What the Skills page shows (owner 2026-10-15): every skill on this Mac's coding agents, where it came from, its
version and whether upstream has a newer one, which agents have it, and — for a skill that drives a tool — whether
its text is older than the tool. Plus the catalog's suggestions, skills agents made, and agents' requests.

Read-only and derived per request, never persisted (``skill_store`` writes; this module never does). The only
network state it shows is the last check ``skill_store.updates()`` saved — the fetch itself is
``check_updates``, which runs only when the person clicks or the page opens (``routers/skills.py``).

Source, in order of trust: Cicada's own marker (it wrote the folder, so it knows the repo and the commit); the
library; the `npx skills` lock (``~/.agents/.skill-lock.json``: repo, ref, folder, when installed); a catalog entry
naming the folder; otherwise the skill is "local" — on this Mac, origin unknown.
"""
from __future__ import annotations

import json
from pathlib import Path

from loguru import logger

from api.services import skill_catalog, skill_folders, skill_sources, skill_store, skill_tools

KINDS = skill_catalog.KINDS
NOTICED_MAX = 20
#: An open page re-checks only when the last check is older than this; a click always checks.
AUTO_CHECK_AFTER_S = 60 * 60
CLICK_CHECK_MIN_S = 60


def npx_lock(base: Path) -> dict[str, dict]:
    """The `npx skills` global lock (v3), read-only: ``{name: entry}``. ``$XDG_STATE_HOME`` is honoured only for the
    real home, so a test's synthetic home never reads a developer's state folder."""
    paths = [base / ".agents" / ".skill-lock.json"]
    import os

    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and base == Path.home():
        paths.insert(0, Path(xdg) / "skills" / ".skill-lock.json")
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        skills = data.get("skills") if isinstance(data, dict) else None
        if isinstance(skills, dict):
            return {k: v for k, v in skills.items() if isinstance(k, str) and isinstance(v, dict)}
    return {}


def _lock_source(entry: dict) -> dict | None:
    if entry.get("sourceType") != "github" or not isinstance(entry.get("source"), str):
        return None
    path = str(entry.get("skillPath") or "")
    if path.endswith(skill_folders.SKILL_FILE):
        path = path[: -len(skill_folders.SKILL_FILE)].rstrip("/")
    return {"origin": "npx", "repo": entry["source"], "ref": entry.get("ref"), "path": path,
            "updatedAt": entry.get("updatedAt") or entry.get("installedAt")}


def _catalog_by_dir(catalog: dict) -> dict[str, dict]:
    out = {}
    for entry in catalog.get("skills", []):
        for d in (entry.get("detect") or {}).get("skillDirs", []):
            out.setdefault(d, entry)
    return out


def _source(name: str, copies: list, lib: dict, lock: dict, by_dir: dict) -> dict:
    for copy in sorted(copies, key=lambda c: c.linked):
        if copy.marker and copy.marker.get("origin"):
            return skill_store.source_from_marker(copy.marker)
    if name in lib:
        return lib[name]
    if name in lock:
        found = _lock_source(lock[name])
        if found:
            return found
    entry = by_dir.get(name)
    if entry and (entry.get("pin") or {}).get("repo"):
        pin = entry["pin"]
        return {"origin": "catalog", "repo": pin["repo"], "path": pin.get("path") or "", "catalogId": entry["id"]}
    if name in skill_store.OWN_BUNDLES:
        return {"origin": "cicada", "source": skill_store.OWN_BUNDLES[name]}
    return {"origin": "local"}


def _source_view(src: dict, entry: dict | None) -> dict:
    origin = src.get("origin") or "local"
    repo = src.get("repo")
    if origin == "cicada":
        return {"kind": "cicada", "label": "Made by Cicada"}
    if origin == "draft":
        author = src.get("author") or "an agent"
        return {"kind": "made", "label": f"Made by {skill_catalog_label(author)}"}
    if repo:
        path = src.get("path") or ""
        url = f"https://github.com/{repo}" + (f"/tree/{src.get('commit') or src.get('ref') or 'HEAD'}/{path}"
                                               if path else "")
        return {"kind": "github", "label": repo, "repo": repo, "url": url,
                "via": "npx skills" if origin == "npx" else None}
    if entry and entry.get("sourceUrl"):
        return {"kind": "github", "label": entry.get("publisher") or entry["sourceUrl"], "url": entry["sourceUrl"]}
    return {"kind": "local", "label": "On this Mac"}


def skill_catalog_label(harness: str) -> str:
    agent = skill_folders.BY_ID.get(harness)
    return agent.label if agent else harness


def _version(src: dict, tool_version: str | None) -> dict:
    if src.get("origin") == "tool" or tool_version:
        return {"label": f"v{tool_version}" if tool_version else (f"v{src['toolVersion']}" if src.get("toolVersion")
                                                                   else "unknown"),
                "tool": tool_version, "text": src.get("toolVersion")}
    if src.get("commit"):
        return {"label": src["commit"][:7], "commit": src["commit"], "ref": src.get("ref")}
    if src.get("origin") == "npx":
        when = str(src.get("updatedAt") or "")[:10]
        return {"label": f"added {when}" if when else (src.get("ref") or "unknown"), "ref": src.get("ref")}
    return {"label": ""}


async def _tool_view(entry: dict, copies: list, src: dict, versions: dict | None, base: Path) -> dict | None:
    tool = skill_tools.Tool.from_entry(entry)
    if tool is None:
        return None
    version = (versions or {}).get(tool.package)
    receipt = skill_tools.receipt(tool.package, base)
    installed = bool(version) or skill_tools.WHICH(tool.command) is not None
    view = {"command": tool.command, "package": tool.package, "installed": installed, "version": version,
            "from": skill_tools.repo_from_git(receipt.get("git", "")) or receipt.get("specifier") or None,
            "text": "unknown", "uv": versions is not None}
    on = [c for c in copies if not c.linked]
    if not installed or not on:
        view["text"] = "no-tool" if not installed else "unknown"
        return view
    marked = [c for c in on if c.marker and c.marker.get("toolVersion")]
    if marked and version:
        stale = any(c.marker["toolVersion"] != version for c in marked)
        view["text"] = "older" if stale else "current"
        view["textVersion"] = marked[0].marker["toolVersion"]
        if stale or len(marked) == len(on):
            return view
    printed = await skill_tools.skill_text(tool)
    if printed is None:
        return view
    digest = skill_folders.sha256(printed.encode("utf-8"))
    view["text"] = "current" if all(c.skill_sha == digest for c in on) else "older"
    return view


async def _permissions(entry: dict, tool_view: dict | None) -> dict | None:
    tool = skill_tools.Tool.from_entry(entry)
    if tool is None or not tool.doctor_args or not (tool_view or {}).get("installed"):
        return None
    report = await skill_tools.doctor(tool)
    if not report:
        return None
    return {**report, "line": skill_tools.permissions_line(report)}


def _agents_view(copies: list, agents: list, can_copy: bool) -> list[dict]:
    out = []
    for st in skill_folders.agent_states(copies, agents):
        row = {"id": st.agent.id, "label": st.agent.label, "state": st.state, "canToggle": True}
        if st.state == "through":
            row["canToggle"] = False
            row["note"] = f"Has it through {skill_folders.folder_label(st.through or '')}."
        elif st.state == "off" and not can_copy:
            row["canToggle"] = False
            row["note"] = "Cicada can't copy this one: it links outside its folder or is too big."
        out.append(row)
    return out


def _update_view(name: str, src: dict, results: dict, checked_at: str | None) -> dict:
    if src.get("origin") == "cicada":
        data = skill_store.own_bundle(name)
        if data is None:
            return {"state": "unknown"}
        same = skill_folders.sha256(data) == src.get("sha256") if src.get("sha256") else None
        return {"state": "current" if same in (True, None) else "available", "latest": "this Cicada",
                "local": True}
    hit = results.get(name)
    if not hit:
        return {"state": "unchecked" if checkable(src) else "unknown"}
    return {**hit, "checkedAt": checked_at}


#: The one word a row's status shows (owner 2026-10-15), most urgent first.
STATUSES = ("update", "refresh", "current", "local", "unchecked")
EXCERPT_CHARS = 600


def status(update: dict, tool: dict | None, src: dict) -> str:
    """``update`` (an Update chip), ``refresh`` (a tool skill's text is older than its tool), ``current`` (Up to date),
    ``local`` (nothing upstream to compare with), or ``unchecked`` (it has an upstream, not asked yet)."""
    if update.get("state") == "available":
        return "update"
    if (tool or {}).get("text") == "older":
        return "refresh"
    if update.get("state") == "current":
        return "current"
    if update.get("state") == "unchecked":
        return "unchecked"
    return "local"


def excerpt(text: str) -> str:
    """The start of a SKILL.md's instructions (after its frontmatter), for the details column."""
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        body = text[end + 4:] if end >= 0 else text
    words = " ".join(line.strip() for line in body.strip().splitlines() if line.strip() and not line.startswith("#"))
    return words[:EXCERPT_CHARS] + ("…" if len(words) > EXCERPT_CHARS else "")


def checkable(src: dict) -> bool:
    return bool(src.get("repo")) and src.get("origin") in ("github", "npx", "catalog", "tool")


async def snapshot(*, base: Path | None = None, bank: Path | None = None, run_tools: bool = True) -> dict:
    base = base or skill_folders.home()
    agents = skill_folders.present(base)
    copies = skill_folders.scan(base)
    lib = skill_store.library()
    lock = npx_lock(base)
    catalog = skill_catalog.load()
    by_dir = _catalog_by_dir(catalog)
    saved = skill_store.updates()
    results, checked_at = saved.get("results") or {}, saved.get("checkedAt")
    names = list(dict.fromkeys([c.name for c in copies] + list(lib)))
    tool_names = {n for n in names if (by_dir.get(n) or {}).get("tool")}
    versions = await skill_tools.tool_versions() if run_tools and tool_names else None

    rows = []
    for name in names:
        mine = [c for c in copies if c.name == name]
        entry = by_dir.get(name)
        src = _source(name, mine, lib, lock, by_dir)
        if src.get("origin") == "cicada":
            marked = next((c.marker for c in mine if c.marker), None)
            src = {**src, "sha256": (marked or {}).get("sha256")}
        first = next((c for c in mine if not c.linked), mine[0] if mine else None)
        meta = first.meta if first else {}
        text = first.text if first else ""
        if not text and name in lib:
            files = skill_store.library_files(name) or {}
            text = files.get(skill_folders.SKILL_FILE, b"").decode("utf-8", "replace")
            meta = skill_folders.frontmatter(text)
        can_copy = name in lib or any(skill_folders.folder_files(c.path) is not None for c in mine)
        tool_view = await _tool_view(entry, mine, src, versions, base) if (entry and run_tools) else None
        version = _version(src, (tool_view or {}).get("version"))
        update = _update_view(name, src, results, checked_at)
        if version.get("label"):
            update["from"] = version["label"]
        row = {
            "name": name,
            "title": str((entry or {}).get("title") or meta.get("name") or name),
            "description": skill_folders.one_line(meta.get("description") or (entry or {}).get("summary") or ""),
            "source": _source_view(src, entry),
            "version": version,
            "update": update,
            "status": status(update, tool_view, src),
            "agents": _agents_view(mine, agents, can_copy),
            "tool": tool_view,
            "permissions": await _permissions(entry, tool_view) if (entry and run_tools) else None,
            "catalogId": (entry or {}).get("id"),
            "details": {
                "folders": [{"path": f"~/{c.root}/{c.name}", "linked": c.linked,
                             "byCicada": bool(c.marker) and c.cicadas} for c in mine],
                "commit": src.get("commit"), "ref": src.get("ref"), "path": src.get("path"),
                "installedAt": src.get("installedAt"), "licence": src.get("licence"),
                "excerpt": excerpt(text),
            },
        }
        rows.append(row)

    installed_names = set(names)
    plugin_ids = skill_catalog.claude_plugin_ids(base)
    suggested = []
    for entry in sorted(catalog.get("skills", []), key=skill_catalog._rank):
        if entry.get("kind") not in KINDS:
            continue
        dirs = set((entry.get("detect") or {}).get("skillDirs", []))
        plugins = set((entry.get("detect") or {}).get("pluginIds", []))
        if dirs & installed_names or plugins & plugin_ids:
            continue
        suggested.append(_suggestion(entry))
    for own in skill_store.OWN_BUNDLES:
        if own not in installed_names and skill_store.own_bundle(own) is not None:
            suggested.append(_own_suggestion(own))

    return {
        "agents": [{"id": a.id, "label": a.label, "folder": f"~/{a.own}"} for a in agents],
        "installed": rows,
        "suggested": suggested,
        "drafts": [_draft_view(d) for d in skill_store.drafts()],
        "noticed": noticed(bank) if bank else [],
        "requests": [{**r, "authorLabel": skill_catalog_label(str(r.get("author") or ""))}
                     for r in skill_store.requests()],
        "checkedAt": checked_at,
        "uv": {"present": skill_tools.uv_present(), "installUrl": skill_tools.UV_INSTALL_URL,
               "installCommand": skill_tools.UV_INSTALL_COMMAND},
        "reviewedAt": catalog.get("reviewedAt", ""),
    }


_SUGGESTION_KEYS = ("id", "kind", "rank", "title", "summary", "why", "publisher", "sourceUrl", "licence", "mark",
                    "symbol", "needs", "terms", "cicadaNote", "reach", "onboarding")


def install_method(entry: dict) -> str:
    """How the Skills page installs a catalog entry: ``tool`` (uv, pinned), ``copy`` (the skill's folder at the pinned
    commit), or ``manual`` (an MCP server, a hosted service, or a licence that forbids copying: the person's agent
    runs its own installer from the text shown)."""
    if entry.get("tool"):
        return "tool"
    if entry.get("kind") in ("mcp", "mcp-hosted") or str(entry.get("licence") or "").lower() == "proprietary":
        return "manual"
    pin = entry.get("pin") or {}
    return "copy" if pin.get("repo") and pin.get("sha") and pin.get("path") is not None else "manual"


def _suggestion(entry: dict) -> dict:
    out = {k: entry[k] for k in _SUGGESTION_KEYS if k in entry}
    out["method"] = install_method(entry)
    pin = entry.get("pin") or {}
    if pin:
        out["pin"] = {"repo": pin.get("repo"), "ref": pin.get("ref"), "commit": pin.get("sha"),
                      "path": pin.get("path")}
    if out["method"] == "manual":
        manual = []
        for agent in entry.get("agents", {}):
            plan = skill_catalog.install_plan(entry, agent)
            text = plan.get("prompt") or "\n".join(" ".join(s["argv"]) for s in plan.get("steps", []))
            if text:
                manual.append({"agent": agent, "label": skill_catalog_label(agent), "text": text})
        out["manual"] = manual
    return out


def _own_suggestion(name: str) -> dict:
    words = {"cicada": ("Recall and save", "Tells your agent when to look things up in Cicada and when to save."),
             "cicada-librarian": ("Tidy as you work",
                                  "Lets your agent file what you just did into Cicada, the way Sleep would.")}[name]
    return {"id": name, "kind": "skill", "title": words[0], "summary": words[1], "publisher": "Cicada",
            "licence": "MIT", "symbol": "sparkles", "method": "own"}


def _draft_view(draft: dict) -> dict:
    return {"name": draft["name"], "description": draft.get("description", ""), "author": draft.get("author"),
            "authorLabel": skill_catalog_label(str(draft.get("author") or "an agent")),
            "reason": draft.get("reason"), "created": draft.get("created"), "updated": draft.get("updated"),
            "revision": draft.get("revision"), "state": "held", "text": draft.get("text", "")}


def noticed(bank: Path) -> list[dict]:
    """Skills Sleep noticed in this bank (G112): the held ones (one conversation so far) and the skill pages. Read
    only; turning one into an installable skill is G112's compiler, not built yet."""
    from api.services import bank_index, skill_hold, skill_tag

    out = []
    try:
        for held in skill_hold.load(bank)[:NOTICED_MAX]:
            out.append({"id": held.slug, "name": held.name, "description": skill_folders.one_line(held.description),
                        "state": "held", "conversations": 1})
        for f in bank_index.files(bank, "entities"):
            fm = f.frontmatter
            if fm.get("type") != "skill" or fm.get("status") not in (None, "active") or skill_tag.is_agent_skill(fm):
                continue
            out.append({"id": f.stem, "name": str(fm.get("name") or f.stem),
                        "description": skill_folders.one_line(fm.get("summary") or fm.get("description") or ""),
                        "state": "page", "conversations": len(fm.get("source_episodes") or [])})
            if len(out) >= NOTICED_MAX:
                break
    except Exception as exc:  # noqa: BLE001 — a bank problem never empties the Skills page
        logger.warning(f"skill_inventory: noticed skills skipped ({type(exc).__name__})")
    return out


async def check_updates(*, base: Path | None = None) -> dict:
    """Ask upstream about every installed skill that has one (the person's click or the open page). Saves and
    returns ``{checkedAt, results}``."""
    base = base or skill_folders.home()
    copies = skill_folders.scan(base)
    lib = skill_store.library()
    lock = npx_lock(base)
    catalog = skill_catalog.load()
    by_dir = _catalog_by_dir(catalog)
    names = list(dict.fromkeys([c.name for c in copies] + list(lib)))
    versions = None
    skill_tools.clear_cache()   # a check reads the tools installed now, never a minute-old answer
    jobs, keys = [], []
    for name in names:
        mine = [c for c in copies if c.name == name]
        src = _source(name, mine, lib, lock, by_dir)
        entry = by_dir.get(name) or {}
        if entry.get("tool") and (entry.get("pin") or {}).get("repo"):
            if versions is None:
                versions = await skill_tools.tool_versions() or {}
            tool = skill_tools.Tool.from_entry(entry)
            jobs.append(skill_sources.check_release(entry["pin"]["repo"], versions.get(tool.package) if tool else None))
            keys.append(name)
        elif checkable(src) and skill_tools.version_tuple(str(src.get("ref") or "")):
            # Installed from a release tag: the next release is the update, not a commit on the tag.
            jobs.append(skill_sources.check_release(str(src["repo"]), str(src["ref"])))
            keys.append(name)
        elif checkable(src):
            jobs.append(skill_sources.check_github(src))
            keys.append(name)
    outcomes = await skill_sources.gather(jobs) if jobs else []
    return skill_store.save_updates(dict(zip(keys, outcomes)))
