"""Where a skill comes from: what the person pasted, what GitHub holds at a commit, and whether upstream moved on
(the Skills page, owner 2026-10-15).

**What can be pasted** — the spellings `npx skills add` takes for GitHub (vercel-labs/skills ``source-parser.ts``),
so a line copied from any README works:

- ``owner/repo``, ``owner/repo@skill``, ``owner/repo/path/to/skill``, ``github:owner/repo``;
- ``https://github.com/owner/repo`` (``.git``, ``/tree/<ref>/<path>``, ``/blob/<ref>/<path>/SKILL.md``), and
  ``git@github.com:owner/repo.git``;
- a whole ``npx skills add <source> [--skill X] [-a agent …] [-g] [-y]`` line (also ``npx -y``, ``bunx``,
  ``pnpm dlx``): its source, its ``--skill`` and its ``-a`` agents are kept; ``-g``/``-y``/``--copy`` mean nothing
  here (Cicada installs for the person, never into a project, and always shows first).

Other hosts are refused in words: Cicada reads GitHub's public API and raw files only.

**Cicada imitates `npx skills` rather than running it.** Same folders and spellings, but every install is pinned to
a commit and shown before it happens, needs no Node, sends no telemetry, and copies into each agent's own folder
instead of linking every agent to ``~/.agents/skills`` (which Codex, Cursor, Gemini CLI and OpenCode all read, so a
link there turns a skill on for four agents at once).

**The fetch.** Only on the person's click or the open Skills page — never in Sleep, never an agent's call — and every
request through ``net_guard`` (``httpx_request_guard`` on each hop), 4 s, ≤ 512 KB per response, no cookies, no
token, a fixed User-Agent (the ToS rail). A preview reads the repo, resolves the ref to a commit, lists the skill's
folder (≤ 64 files, ≤ 5 MB) and downloads those files by the commit, so what installs is what was shown. ``FETCH``
is swapped by the suite: no test touches the network (conftest).

**Updates.** For a skill from a repo folder: the newest commit on its ref that touched that folder
(``commits?path=``), against the commit Cicada recorded at install; a newer one is "Update available" with a compare
link. For a tool: its latest GitHub release against the installed version, with the release notes link.
"""
from __future__ import annotations

import asyncio
import json
import re
import shlex
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import quote, urlparse

from loguru import logger

from api.services import net_guard, skill_folders

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
TIMEOUT_S = 4.0
MAX_BYTES = 512 * 1024
USER_AGENT = "cicada-skills/1"
MAX_LISTINGS = 24
MAX_DEPTH = 4
PLAN_TTL_S = 30 * 60
MAX_PLANS = 8
SKILL_SHOWN_CHARS = 20_000
SCRIPT_SUFFIXES = (".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".swift", ".go")

_SEG = r"[A-Za-z0-9_.-]+"
_OWNER_REPO = re.compile(rf"^({_SEG})/({_SEG})$")


class SourceError(ValueError):
    """Something the person pasted or GitHub answered that Cicada cannot use; the message is for the person."""


@dataclass
class Source:
    owner: str
    repo: str
    ref: str | None = None
    path: str | None = None
    skill: str | None = None
    agents: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    def to_dict(self) -> dict:
        return {"repo": self.slug, "ref": self.ref, "path": self.path, "skill": self.skill, "agents": self.agents}


def _clean_path(raw: str | None) -> str | None:
    if not raw:
        return None
    parts = [p for p in raw.strip("/").split("/") if p]
    if any(p in (".", "..") or not re.fullmatch(_SEG, p) for p in parts):
        raise SourceError("That path has parts Cicada won't follow. Paste the repo or the skill's folder link.")
    return "/".join(parts) or None


def _repo_name(raw: str) -> str:
    return raw[:-4] if raw.endswith(".git") else raw


def _parse_url(text: str) -> Source:
    if text.startswith("git@"):
        m = re.fullmatch(rf"git@github\.com:({_SEG})/({_SEG})", text)
        if not m:
            raise SourceError("Cicada adds skills from GitHub for now. Paste a github.com link or owner/repo.")
        return Source(m.group(1), _repo_name(m.group(2)))
    if not re.match(r"^https?://", text):
        text = "https://" + text
    parsed = urlparse(text)
    if (parsed.hostname or "").lower() not in ("github.com", "www.github.com"):
        raise SourceError("Cicada adds skills from GitHub for now. Paste a github.com link or owner/repo.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise SourceError("That link doesn't name a repository. It should look like github.com/owner/repo.")
    owner, repo = parts[0], _repo_name(parts[1])
    if not re.fullmatch(_SEG, owner) or not re.fullmatch(_SEG, repo):
        raise SourceError("That link doesn't name a repository. It should look like github.com/owner/repo.")
    ref = path = None
    if len(parts) >= 4 and parts[2] in ("tree", "blob"):
        ref = parts[3]
        rest = parts[4:]
        if parts[2] == "blob" and rest and rest[-1] == skill_folders.SKILL_FILE:
            rest = rest[:-1]
        path = _clean_path("/".join(rest))
    return Source(owner, repo, ref=ref, path=path)


def _parse_short(text: str) -> Source:
    if text.startswith("github:"):
        text = text[len("github:"):]
    m = re.fullmatch(rf"({_SEG})/({_SEG})@({_SEG})", text)
    if m:
        return Source(m.group(1), _repo_name(m.group(2)), skill=m.group(3))
    m = re.fullmatch(rf"({_SEG})/({_SEG})(?:/(.+?))?/?", text)
    if not m:
        raise SourceError("Paste a GitHub link, owner/repo, or an `npx skills add …` line.")
    return Source(m.group(1), _repo_name(m.group(2)), path=_clean_path(m.group(3)))


_RUNNERS = (("npx",), ("bunx",), ("pnpm", "dlx"), ("yarn", "dlx"))


def _parse_command(tokens: list[str]) -> Source:
    i = 0
    for runner in _RUNNERS:
        if tokens[: len(runner)] == list(runner):
            i = len(runner)
            break
    while i < len(tokens) and tokens[i].startswith("-"):   # `npx -y skills …`
        i += 1
    if i >= len(tokens) or not re.fullmatch(r"skills(@[A-Za-z0-9._-]+)?", tokens[i]):
        raise SourceError("Only `npx skills add …` lines can be pasted as a command.")
    i += 1
    if i >= len(tokens) or tokens[i] not in ("add", "a", "install", "i"):
        raise SourceError("Only `npx skills add …` lines can be pasted as a command.")
    i += 1
    source: Source | None = None
    skills: list[str] = []
    agents: list[str] = []
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("--skill", "-s"):
            i += 1
            while i < len(tokens) and not tokens[i].startswith("-"):
                skills.append(tokens[i])
                i += 1
            continue
        if tok in ("--agent", "-a"):
            i += 1
            while i < len(tokens) and not tokens[i].startswith("-"):
                agents.append(tokens[i])
                i += 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if source is not None:
            raise SourceError("That line names more than one source. Paste one skill at a time.")
        source = parse(tok, _nested=True)
        i += 1
    if source is None:
        raise SourceError("That line doesn't say which skill to add.")
    if len([s for s in skills if s != "*"]) > 1:
        raise SourceError("That line adds several skills. Cicada adds one at a time: keep one --skill.")
    if skills and skills[0] != "*":
        source.skill = skills[0]
    source.agents = [skill_folders.NPX_AGENT[a] for a in agents if a in skill_folders.NPX_AGENT]
    return source


def parse(text: str, *, _nested: bool = False) -> Source:
    """What the person pasted, as a GitHub source. Raises ``SourceError`` with a sentence for them."""
    text = (text or "").strip()
    if not text:
        raise SourceError("Paste a GitHub link, owner/repo, or an `npx skills add …` line.")
    if len(text) > 2000:
        raise SourceError("That is too long to be a skill's address.")
    if not _nested and re.search(r"\s", text):
        try:
            tokens = shlex.split(text)
        except ValueError:
            raise SourceError("That line has an unclosed quote.") from None
        if any(t in ("|", "||", "&&", ";", "&") or t.endswith(";") for t in tokens):
            raise SourceError("Paste one `npx skills add …` command, nothing chained to it.")
        return _parse_command(tokens)
    if text.startswith(("http://", "https://", "git@", "github.com/", "www.github.com/")):
        return _parse_url(text)
    if "://" in text:
        raise SourceError("Cicada adds skills from GitHub for now. Paste a github.com link or owner/repo.")
    return _parse_short(text)


# --------------------------------------------------------------------------- the network


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self):
        try:
            return json.loads(self.body.decode("utf-8"))
        except ValueError:
            raise SourceError("GitHub answered something Cicada couldn't read. Try again in a moment.") from None


async def _httpx_fetch(url: str, accept: str | None = None) -> Response:
    import httpx

    headers = {"User-Agent": USER_AGENT, "Accept": accept or "application/vnd.github+json"}
    async with httpx.AsyncClient(timeout=TIMEOUT_S, follow_redirects=True, headers=headers,
                                 event_hooks={"request": [net_guard.httpx_request_guard]}) as client:
        async with client.stream("GET", url) as resp:
            chunks, total = [], 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise SourceError("A file in that skill is bigger than Cicada reads (512 KB).")
                chunks.append(chunk)
            return Response(resp.status_code, b"".join(chunks), {k.lower(): v for k, v in resp.headers.items()})


#: ``async (url, accept) -> Response``. The suite swaps it (conftest): a test never reaches the network.
FETCH = _httpx_fetch


async def _get(url: str, accept: str | None = None) -> Response:
    try:
        resp = await FETCH(url, accept)
    except SourceError:
        raise
    except net_guard.UnsafeURL:
        raise SourceError("Cicada won't fetch from that address.") from None
    except Exception as exc:  # noqa: BLE001 — a timeout or a dropped connection, said in words
        logger.info(f"skill_sources: fetch failed ({type(exc).__name__})")
        raise SourceError("GitHub didn't answer in time. Check your connection and try again.") from None
    if resp.status == 404:
        raise SourceError("GitHub has nothing public there. Check the address; private repositories can't be added.")
    if resp.status in (403, 429):
        raise SourceError("GitHub is limiting how often Cicada can ask. Try again in a little while.")
    if resp.status >= 400:
        raise SourceError(f"GitHub answered with an error ({resp.status}). Try again in a moment.")
    return resp


async def repo_info(owner: str, repo: str) -> dict:
    data = (await _get(f"{API}/repos/{owner}/{repo}")).json()
    if not isinstance(data, dict):
        raise SourceError("GitHub answered something Cicada couldn't read. Try again in a moment.")
    if data.get("private"):
        raise SourceError("That repository is private. Cicada adds public skills only.")
    licence = (data.get("license") or {}).get("spdx_id") if isinstance(data.get("license"), dict) else None
    return {"defaultBranch": str(data.get("default_branch") or "main"), "licence": licence if licence != "NOASSERTION"
            else None, "url": str(data.get("html_url") or f"https://github.com/{owner}/{repo}"),
            "description": str(data.get("description") or "")}


async def resolve_commit(owner: str, repo: str, ref: str) -> str:
    resp = await _get(f"{API}/repos/{owner}/{repo}/commits/{quote(ref, safe='')}", "application/vnd.github.sha")
    sha = resp.body.decode("utf-8", "replace").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SourceError(f"Cicada couldn't find {ref} in that repository.")
    return sha


async def path_commit(owner: str, repo: str, ref: str, path: str) -> dict | None:
    """The newest commit on ``ref`` that touched ``path``: ``{sha, date}``, or ``None``."""
    url = f"{API}/repos/{owner}/{repo}/commits?sha={quote(ref, safe='')}&per_page=1"
    if path:
        url += f"&path={quote(path, safe='/')}"
    data = (await _get(url)).json()
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    commit = data[0]
    date = (((commit.get("commit") or {}).get("committer") or {}).get("date")) or ""
    return {"sha": str(commit.get("sha") or ""), "date": str(date)}


async def latest_release(owner: str, repo: str) -> dict | None:
    resp = await _get(f"{API}/repos/{owner}/{repo}/releases/latest")
    data = resp.json()
    if not isinstance(data, dict) or not data.get("tag_name"):
        return None
    return {"tag": str(data["tag_name"]), "url": str(data.get("html_url") or ""),
            "date": str(data.get("published_at") or "")}


async def _listing(owner: str, repo: str, sha: str, path: str) -> list[dict]:
    url = f"{API}/repos/{owner}/{repo}/contents/{quote(path, safe='/')}?ref={sha}" if path else \
        f"{API}/repos/{owner}/{repo}/contents?ref={sha}"
    data = (await _get(url)).json()
    if isinstance(data, dict):   # a file, not a folder
        return [data]
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


#: Folders `npx skills` looks in for skills when a repo holds several (its README, "skill discovery").
_CONTAINERS = ("skills", ".claude/skills", ".agents/skills", "skills/.curated")


async def discover(owner: str, repo: str, sha: str, path: str | None, skill: str | None) -> list[str]:
    """The skill folders (repo paths, "" for the root) a source points at, at most one level of guessing."""
    if path:
        names = {e.get("name") for e in await _listing(owner, repo, sha, path)}
        if skill_folders.SKILL_FILE in names:
            return [path]
        return await _children_with_skill(owner, repo, sha, path, skill)
    root = {e.get("name"): e for e in await _listing(owner, repo, sha, "")}
    if skill_folders.SKILL_FILE in root and (not skill or skill == repo):
        return [""]
    found: list[str] = []
    for container in _CONTAINERS:
        head = container.split("/")[0]
        if head not in root or (root[head].get("type") != "dir"):
            continue
        try:
            found += await _children_with_skill(owner, repo, sha, container, skill)
        except SourceError:
            continue
        if found:
            break
    if not found and skill_folders.SKILL_FILE in root:
        return [""]
    return found


async def _children_with_skill(owner: str, repo: str, sha: str, folder: str, skill: str | None) -> list[str]:
    entries = await _listing(owner, repo, sha, folder)
    dirs = [e for e in entries if e.get("type") == "dir" and isinstance(e.get("path"), str)]
    if skill:
        dirs = [e for e in dirs if e.get("name") == skill]
    out = []
    for entry in dirs[:MAX_LISTINGS]:
        names = {e.get("name") for e in await _listing(owner, repo, sha, entry["path"])}
        if skill_folders.SKILL_FILE in names:
            out.append(entry["path"])
    return out


async def _files(owner: str, repo: str, sha: str, folder: str) -> list[dict]:
    """Every file under a skill folder, from listings: ``[{path, rel, size}]``, within the caps."""
    out: list[dict] = []
    queue = [(folder, 0)]
    listings = 0
    total = 0
    while queue:
        current, depth = queue.pop(0)
        listings += 1
        if listings > MAX_LISTINGS:
            raise SourceError("That skill's folder is bigger than Cicada adds (too many folders).")
        for entry in await _listing(owner, repo, sha, current):
            kind, path = entry.get("type"), str(entry.get("path") or "")
            if kind == "dir":
                if depth + 1 <= MAX_DEPTH and not entry.get("name", "").startswith(".git"):
                    queue.append((path, depth + 1))
            elif kind == "file":
                rel = path[len(folder) + 1:] if folder else path
                size = int(entry.get("size") or 0)
                total += size
                out.append({"path": path, "rel": rel, "size": size})
            elif kind == "symlink":
                raise SourceError("That skill links to files outside its folder; Cicada doesn't add those.")
        if len(out) > skill_folders.MAX_FILES:
            raise SourceError(f"That skill has more than {skill_folders.MAX_FILES} files; Cicada doesn't add it.")
        if total > skill_folders.MAX_TOTAL_BYTES:
            raise SourceError("That skill is bigger than Cicada adds (5 MB).")
    return out


def is_script(rel: str, data: bytes) -> bool:
    return rel.lower().endswith(SCRIPT_SUFFIXES) or data.startswith(b"#!")


@dataclass
class Plan:
    """A previewed skill: exactly the files the person saw, pinned to one commit."""

    id: str
    name: str
    source: dict
    files: dict[str, bytes]
    preview: dict
    created: float = field(default_factory=time.monotonic)


_PLANS: dict[str, Plan] = {}


def remember(plan: Plan) -> None:
    now = time.monotonic()
    for key in [k for k, p in _PLANS.items() if now - p.created > PLAN_TTL_S]:
        _PLANS.pop(key, None)
    while len(_PLANS) >= MAX_PLANS:
        _PLANS.pop(min(_PLANS, key=lambda k: _PLANS[k].created))
    _PLANS[plan.id] = plan


def take(plan_id: str) -> Plan | None:
    plan = _PLANS.get(plan_id)
    if plan and time.monotonic() - plan.created > PLAN_TTL_S:
        _PLANS.pop(plan_id, None)
        return None
    return plan


async def preview(source: Source, *, choose: str | None = None) -> dict:
    """Fetch what a source points at and describe it for the person. Returns either ``{choices: [...]}`` (the repo
    holds several skills; the caller asks again with ``choose``) or ``{planId, …}`` remembered for the install."""
    info = await repo_info(source.owner, source.repo)
    ref = source.ref or info["defaultBranch"]
    sha = await resolve_commit(source.owner, source.repo, ref)
    folders = [choose] if choose is not None else await discover(source.owner, source.repo, sha, source.path,
                                                                 source.skill)
    if choose is not None and _clean_path(choose) != (choose or None):
        raise SourceError("That choice isn't one of the skills in the repository.")
    if not folders:
        raise SourceError("Cicada found no SKILL.md there. Paste the skill's own folder link.")
    if len(folders) > 1:
        return {"choices": [{"path": f, "name": f.rsplit("/", 1)[-1] or source.repo} for f in folders[:40]],
                "repo": {**source.to_dict(), "url": info["url"]}}
    folder = folders[0]
    listed = await _files(source.owner, source.repo, sha, folder)
    if not any(f["rel"] == skill_folders.SKILL_FILE for f in listed):
        raise SourceError("Cicada found no SKILL.md there. Paste the skill's own folder link.")
    files: dict[str, bytes] = {}
    for entry in listed:
        resp = await _get(f"{RAW}/{source.owner}/{source.repo}/{sha}/{quote(entry['path'], safe='/')}",
                          "application/octet-stream")
        files[entry["rel"]] = resp.body
    text = files[skill_folders.SKILL_FILE].decode("utf-8", "replace")
    meta = skill_folders.frontmatter(text)
    dir_name = folder.rsplit("/", 1)[-1] if folder else source.repo
    name = str(meta.get("name") or dir_name).strip()
    if not skill_folders.NAME.match(name):
        name = dir_name
    if not skill_folders.NAME.match(name):
        raise SourceError("That skill's name has characters an agent's folder can't hold.")
    touched = await path_commit(source.owner, source.repo, sha, folder)
    scripts = sorted(rel for rel, data in files.items() if is_script(rel, data))
    src = {"origin": "github", "repo": source.slug, "path": folder, "ref": ref, "commit": sha,
           "pathCommit": (touched or {}).get("sha") or sha, "licence": info["licence"]}
    shown = {
        "name": name,
        "description": skill_folders.one_line(meta.get("description") or "", 400),
        "skillMd": text[:SKILL_SHOWN_CHARS],
        "skillMdCut": len(text) > SKILL_SHOWN_CHARS,
        "files": [{"path": rel, "size": len(files[rel]), "script": rel in scripts} for rel in sorted(files)],
        "scripts": scripts,
        "repo": {"repo": source.slug, "url": info["url"], "licence": info["licence"], "ref": ref, "commit": sha,
                 "commitUrl": f"https://github.com/{source.slug}/tree/{sha}/{folder}".rstrip("/"),
                 "path": folder},
        "agents": source.agents,
    }
    plan = Plan(id=uuid.uuid4().hex, name=name, source=src, files=files, preview=shown)
    remember(plan)
    return {"planId": plan.id, **shown}


#: An update lists at most this many changes (commits that touched the skill, or releases), each cut short: the Skills
#: page shows them when the person opens the update, so they never have to leave Cicada to see what changed.
MAX_CHANGES = 20
CHANGE_TITLE_CHARS = 140
CHANGE_NOTES_CHARS = 600


async def path_commits(owner: str, repo: str, ref: str, path: str, count: int) -> list[dict]:
    """The newest ``count`` commits on ``ref`` that touched ``path``: ``[{sha, date, title, url}]``."""
    url = f"{API}/repos/{owner}/{repo}/commits?sha={quote(ref, safe='')}&per_page={count}"
    if path:
        url += f"&path={quote(path, safe='/')}"
    data = (await _get(url)).json()
    out = []
    for commit in data if isinstance(data, list) else []:
        if not isinstance(commit, dict) or not commit.get("sha"):
            continue
        inner = commit.get("commit") or {}
        message = str(inner.get("message") or "").strip().splitlines()
        out.append({"sha": str(commit["sha"]), "date": str((inner.get("committer") or {}).get("date") or ""),
                    "title": skill_folders.one_line(message[0] if message else "", CHANGE_TITLE_CHARS),
                    "url": str(commit.get("html_url") or "")})
    return out


async def releases(owner: str, repo: str, count: int = 10) -> list[dict]:
    """The newest releases, newest first: ``[{tag, date, notes, url}]`` (drafts and pre-releases left out)."""
    data = (await _get(f"{API}/repos/{owner}/{repo}/releases?per_page={count}")).json()
    out = []
    for rel in data if isinstance(data, list) else []:
        if not isinstance(rel, dict) or not rel.get("tag_name") or rel.get("draft") or rel.get("prerelease"):
            continue
        notes = " ".join(str(rel.get("body") or "").split())
        out.append({"tag": str(rel["tag_name"]), "date": str(rel.get("published_at") or ""),
                    "notes": notes[:CHANGE_NOTES_CHARS] + ("…" if len(notes) > CHANGE_NOTES_CHARS else ""),
                    "url": str(rel.get("html_url") or "")})
    return out


def _commit_changes(commits: list[dict]) -> list[dict]:
    return [{"title": c["title"] or c["sha"][:7], "date": c["date"][:10], "ref": c["sha"][:7], "url": c["url"]}
            for c in commits[:MAX_CHANGES]]


async def check_github(src: dict) -> dict:
    """Is a newer version of a repo-folder skill upstream? ``{state, latest, changes, link, linkLabel}`` — the
    changes are the commits that touched the skill's folder since the one installed, newest first."""
    repo, path = str(src.get("repo") or ""), str(src.get("path") or "")
    m = _OWNER_REPO.match(repo)
    if not m:
        return {"state": "unknown"}
    owner, name = m.groups()
    ref = src.get("ref") or (await repo_info(owner, name))["defaultBranch"]
    commits = await path_commits(owner, name, str(ref), path, MAX_CHANGES)
    if not commits:
        return {"state": "unknown"}
    newest = commits[0]
    pinned = str(src.get("pathCommit") or src.get("commit") or "")
    if pinned:
        if newest["sha"] in (pinned, str(src.get("commit") or "")):
            return {"state": "current", "latest": newest["sha"][:7]}
        newer = []
        for commit in commits:
            if commit["sha"] == pinned:
                break
            newer.append(commit)
        return {"state": "available", "latest": newest["sha"][:7], "latestCommit": newest["sha"],
                "changes": _commit_changes(newer),
                "link": f"https://github.com/{repo}/compare/{pinned[:12]}...{newest['sha'][:12]}",
                "linkLabel": "What changed"}
    since = str(src.get("updatedAt") or "")
    if since and newest.get("date") and newest["date"] > since:
        return {"state": "available", "latest": newest["sha"][:7], "latestCommit": newest["sha"],
                "changes": _commit_changes([c for c in commits if c["date"] > since]),
                "link": f"https://github.com/{repo}/commits/{quote(str(ref), safe='')}/{path}".rstrip("/"),
                "linkLabel": "What changed"}
    return {"state": "current" if since else "unknown", "latest": newest["sha"][:7]}


async def check_release(repo: str, installed: str | None) -> dict:
    """Is there a release newer than ``installed``? The changes are every newer release with its notes."""
    from api.services import skill_tools

    m = _OWNER_REPO.match(repo or "")
    if not m:
        return {"state": "unknown"}
    found = await releases(*m.groups())
    if not found:
        return {"state": "unknown"}
    latest = found[0]
    if not skill_tools.newer(latest["tag"], installed):
        return {"state": "current" if installed else "unknown", "latest": latest["tag"]}
    newer = [r for r in found if skill_tools.newer(r["tag"], installed)][:MAX_CHANGES]
    return {"state": "available", "latest": latest["tag"], "link": latest["url"], "linkLabel": "Release notes",
            "changes": [{"title": r["tag"], "date": r["date"][:10], "detail": r["notes"], "url": r["url"]}
                        for r in newer]}


async def gather(jobs: list, limit: int = 4) -> list:
    """Run checks a few at a time; a failed one is its own error, never the batch's."""
    sem = asyncio.Semaphore(limit)

    async def one(job):
        async with sem:
            try:
                return await job
            except SourceError as exc:
                return {"state": "unknown", "error": str(exc)}

    return await asyncio.gather(*(one(j) for j in jobs))
