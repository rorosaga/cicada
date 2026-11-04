"""G230 — repositories on the graph: connecting GitHub by a code, the synced lists, a project's repositories, and a
page's repository card with its README preview. ``github_repos`` is the writer, ``github_auth`` the sign-in; this
router is their door for every client (the app, the CLI through ``cli_map``).

Every write is the person's act: demo-gated (``refuse_capture_into_demo``), one admitted transaction around the page
writes and their scoped commit (409 while Sleep holds the pages, G183), any request to GitHub made BEFORE the
admission is taken. Nothing is added by hand (owner 2026-11-03: "there shouldn't be added manually, always sync"):
every repository page comes from a sync. The token is never read back, logged or returned; a refusal is GitHub's in
words.
"""
from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from api.config import Settings, get_settings
from api.models.schemas import CamelModel
from api.routers.capture import refuse_capture_into_demo
from api.services import git_service, github_repos, markdown_parser, media_preview, sync_state, write_admission
from api.services.connectors import github, github_auth, tier2
from api.services.sleep_refusal import SleepWriting

router = APIRouter()
_DEMO_GATE = [Depends(refuse_capture_into_demo)]
BUSY = "Sleep is updating your memory — try again in a moment."
VIAS = frozenset({"app", "cli"})
NOT_A_REPO = "That is not a GitHub repository. Name one like owner/name."
NOT_IN_MEMORY = ("{full} has no page in memory yet. Repositories come in with a GitHub sync: connect GitHub "
                 "(Sources → GitHub) and press Refresh.")


class RepoProject(CamelModel):
    project: str
    name: str
    how: str


class RepoRow(CamelModel):
    id: int
    full_name: str
    url: str
    description: Optional[str] = None
    language: Optional[str] = None
    topics: list[str] = []
    owner_kind: str = "User"
    private: bool = False
    archived: bool = False
    fork: bool = False
    starred: bool = False
    starred_at: Optional[str] = None
    unstarred_on: Optional[str] = None
    owned: bool = False
    added: bool = False
    entity_id: Optional[str] = None
    #: The first project it belongs to, else a suggestion (``how: name``, or ``origin`` not linked yet).
    project: Optional[RepoProject] = None
    #: Every project it belongs to (a repository may serve several; a project may list several).
    projects: list[RepoProject] = []


class RepoLists(CamelModel):
    connected: bool
    owned: list[RepoRow] = []
    starred: list[RepoRow] = []


class RepoProjectRequest(CamelModel):
    full_name: str
    #: The project page to link (or unlink); absent, a new project is made in the person's list, named after it.
    project: Optional[str] = None
    #: Unlink instead: the person's "not part of it", remembered.
    remove: bool = False
    #: Which of the person's doors made it (ruling 45's ``mine.via``): ``app`` or ``cli``.
    via: str = "app"


class RepoProjectResponse(CamelModel):
    project: str
    created: bool
    linked: bool = True


class Readme(CamelModel):
    state: str              # fresh | stale | missing | none (the repository has no README)
    text: Optional[str] = None
    truncated: bool = False
    path: Optional[str] = None
    fetched_at: Optional[str] = None


class RepoDetail(RepoRow):
    entity_id: str
    readme: Readme
    #: Projects it could be linked to: a suggestion first, then every other live project.
    candidates: list[RepoProject] = []


class ProjectRepo(RepoRow):
    #: How it was linked: ``user`` (the person), ``agent``, ``origin`` (the checkout's hashed remote), ``linked``
    #: (from before projects listed theirs).
    how: str = "linked"
    by: Optional[str] = None


class ProjectRepos(CamelModel):
    project: str
    repos: list[ProjectRepo] = []
    candidates: list[RepoRow] = []


class ConnectStart(CamelModel):
    user_code: str
    verification_uri: str
    expires_at: int
    interval: int


class ConnectStatus(CamelModel):
    #: This build can connect by code (its GitHub app is registered).
    available: bool
    connected: bool
    #: ``app`` (connected by code), ``token`` (a pasted token), or None.
    how: Optional[str] = None
    #: Connected by code: whether the app is installed on the person's account (what lets it see their repositories).
    installed: Optional[bool] = None
    selection: Optional[str] = None
    #: Connected by code, but GitHub no longer renews the sign-in (its refresh token lapsed or was revoked): the panel
    #: says Reconnect, never Connected.
    reconnect: bool = False
    install_url: Optional[str] = None
    #: GitHub's own page where the person removes the grant.
    grants_url: str = github_auth.GRANTS_URL
    pending: Optional[ConnectStart] = None
    words: Optional[str] = None
    #: The first sync, started by the backend itself the moment a code sign-in completes, is running.
    syncing: bool = False


class ConnectPoll(CamelModel):
    state: str              # pending | connected | denied | expired | error | none
    interval: Optional[int] = None
    words: Optional[str] = None
    status: Optional[ConnectStatus] = None


def _row(block: dict, **extra) -> RepoRow:
    return RepoRow(**_row_fields(block), **extra)


def _row_fields(block: dict) -> dict:
    full = str(block.get("full_name") or "")
    return dict(
        id=int(block.get("id") or 0), full_name=full, url=github.repo_url(full),
        description=block.get("description") or None, language=block.get("language") or None,
        topics=[str(t) for t in block.get("topics") or []], owner_kind=str(block.get("owner_kind") or "User"),
        private=bool(block.get("private")), archived=bool(block.get("archived")), fork=bool(block.get("fork")),
        starred=bool(block.get("starred")), starred_at=block.get("starred_at") or None,
        unstarred_on=block.get("unstarred_on") or None, owned=bool(block.get("owned")),
        added=bool(block.get("added")))


def _projects(rows) -> list[RepoProject]:
    return [RepoProject(**p) for p in rows or []]


# --- connecting --------------------------------------------------------------------------------------------------


def _connect_status(words: str | None = None) -> ConnectStatus:
    connected = github.is_connected()
    how = (github_auth.HOW_APP if github_auth.is_app_token() else "token") if connected else None
    account = github_auth.account() if how == github_auth.HOW_APP else {}
    return ConnectStatus(
        available=github_auth.available(), connected=connected, how=how,
        installed=bool(account.get("installed")) if how == github_auth.HOW_APP else None,
        selection=account.get("selection") if how == github_auth.HOW_APP else None,
        install_url=github_auth.install_url() if how == github_auth.HOW_APP else None,
        reconnect=github_auth.needs_reconnect(),
        pending=ConnectStart(**github_auth.pending()) if github_auth.pending() else None,
        words=words or (github_auth.RECONNECT_WORDS if github_auth.needs_reconnect() else None),
        syncing=first_sync_running())


# --- the first sync after a sign-in ------------------------------------------------------------------------------
#
# 2026-11-04 (owner, live: connected by code, "I don't see … any of the repos", the connector's `lastSync` null). A
# code sign-in stamped the credentials and checked the installation, and nothing read GitHub: the app's panel synced
# only on "I installed it" or Refresh, and the scheduled job's first run is `tier2.SCHEDULE_HOURS` after the backend
# starts — so a person who connected saw no stars (which need no install) and no repositories for hours. The sign-in
# completing is the person's act, so the first sync starts here, at once, for every client (the app, the CLI): in the
# background, so the poll answers within its interval, never gated (`allow_fetch=True`, the person's click), on the
# bank active at that moment (the split-brain rule), one at a time. `tier2.run` never raises and yields to Sleep.

_first_sync: Optional[asyncio.Task] = None


def first_sync_running() -> bool:
    return _first_sync is not None and not _first_sync.done()


def start_first_sync(memory_path) -> bool:
    """Start one sync of GitHub into ``memory_path`` in the background, unless one is already running."""
    global _first_sync
    if first_sync_running():
        return False

    async def run() -> None:
        result = await github.sync(memory_path, allow_fetch=True)
        logger.info(f"github: first sync after sign-in {result.get('status')}, {int(result.get('new') or 0)} new")

    _first_sync = asyncio.create_task(run())
    return True


@router.get("/sources/github/connect", response_model=ConnectStatus)
async def connect_status():
    """Whether this build can connect by code, whether it is connected and how, and — connected by code — whether the
    app is installed on the person's account. Reads only (the last check is kept outside every bank)."""
    return _connect_status()


@router.post("/sources/github/connect", response_model=ConnectStart, dependencies=_DEMO_GATE)
async def connect_start():
    """The person's *Connect GitHub*: GitHub's device flow gives a short code to enter at github.com/login/device. The
    person's click, so never gated; the device code itself stays here."""
    try:
        started = await github_auth.start()
    except tier2.Refused as exc:
        raise HTTPException(409 if exc.kind == "setup" else 502, exc.words) from exc
    return ConnectStart(**started)


@router.post("/sources/github/connect/poll", response_model=ConnectPoll, dependencies=_DEMO_GATE)
async def connect_poll(settings: Settings = Depends(get_settings)):
    """One check on the sign-in under way (GitHub is asked at most once an interval). Connected, the app's
    installation on the person's account is checked once, so the panel can offer *Install on GitHub* next."""
    try:
        answer = await github_auth.poll()
    except tier2.Refused as exc:
        return ConnectPoll(state="error", words=exc.words, status=_connect_status())
    if answer["state"] == "connected":
        sync_state.record_credentials_changed(settings.memory_path, github.CHANNEL_ID)
        await _check_installation()
        # Stars need no install, and an installed app sees the person's repositories: read them now.
        start_first_sync(settings.memory_path)
    return ConnectPoll(state=answer["state"], interval=answer.get("interval"), words=answer.get("words"),
                       status=_connect_status())


async def _check_installation() -> str | None:
    try:
        await github_auth.check_installation(github.client())
    except tier2.Refused as exc:
        return exc.words
    except Exception as exc:  # noqa: BLE001 — the class only, never the message
        logger.info(f"github: installation not checked ({type(exc).__name__})")
        return "Cicada could not reach GitHub; try again in a moment."
    return None


@router.post("/sources/github/connect/installation", response_model=ConnectStatus, dependencies=_DEMO_GATE)
async def connect_installation():
    """After the person installed the app on GitHub (*I installed it*): ask GitHub again whether it is there."""
    await github_auth.fresh_token()
    return _connect_status(await _check_installation())


@router.delete("/sources/github/connect", response_model=ConnectStatus)
async def connect_cancel():
    """The person closed the code before approving: the sign-in under way is dropped (nothing was saved)."""
    github_auth.cancel()
    return _connect_status()


# --- the lists ------------------------------------------------------------------------------------------------------


@router.get("/sources/github/repos", response_model=RepoLists)
async def list_repos(settings: Settings = Depends(get_settings)):
    """The repositories the last sync found the person owns — each with its page and the projects it belongs to, or a
    suggestion — and every other repository page (starred, or added before adds were retired). Reads the bank only;
    never asks GitHub."""
    memory_path = settings.memory_path

    def read():
        pages = github_repos.starred(memory_path)
        by_id = {r["id"]: r["entity_id"] for r in pages}
        owned = github_repos.with_matches(memory_path, github_repos.owned(memory_path))
        mine = {r.get("id") for r in owned}
        others = github_repos.with_matches(memory_path, [r for r in pages if r.get("id") not in mine])
        return owned, others, by_id

    owned, others, by_id = await asyncio.to_thread(read)

    def row(r: dict, entity_id) -> RepoRow:
        return _row(r, entity_id=entity_id, project=RepoProject(**r["project"]) if r.get("project") else None,
                    projects=_projects(r.get("projects")))

    return RepoLists(connected=github.is_connected(), owned=[row(r, by_id.get(r.get("id"))) for r in owned],
                     starred=[row(r, r["entity_id"]) for r in others])


async def _commit(memory_path, paths: list[str], subject: str) -> None:
    if not paths or not (memory_path / ".git").exists():
        return
    message = git_service.build_commit_message(
        f"{subject} {date.today().isoformat()}",
        [f"{p}: updated (trigger: user/github)" for p in paths], authors=["user"])
    await git_service.commit_paths(memory_path, message, paths)


def _page_record(memory_path, entity_id: str) -> github_repos.Repo | None:
    page = memory_path / "entities" / f"{entity_id}.md"
    block = github_repos.page_repo(markdown_parser.parse(page, ledger=False).frontmatter) if page.exists() else None
    return github_repos.Repo.from_block(block) if block else None


@router.post("/sources/github/repos/project", response_model=RepoProjectResponse, dependencies=_DEMO_GATE)
async def repo_project(request: RepoProjectRequest, settings: Settings = Depends(get_settings)):
    """The person's link from either page: this repository is one of ``project``'s (or, with ``remove``, is not —
    remembered, so no automatic link puts it back). With no ``project``, a new project in their list named after it,
    which lists it (ruling 45: their act). The repository must have its page (it comes from a sync)."""
    from api.services import project_ownership

    full = github.parse_repo(request.full_name)
    if full is None:
        raise HTTPException(422, NOT_A_REPO)
    if request.via not in VIAS:
        raise HTTPException(422, "via is app or cli")
    if request.remove and not request.project:
        raise HTTPException(422, "Name the project to unlink it from.")
    memory_path = settings.memory_path
    entity_id = await asyncio.to_thread(github_repos.repository_page, memory_path, full)
    if entity_id is None:
        raise HTTPException(404, NOT_IN_MEMORY.format(full=full))

    async def write():
        if request.project:
            try:
                paths = await asyncio.to_thread(github_repos.link, memory_path, request.project, entity_id,
                                                remove=request.remove)
            except LookupError as exc:
                raise HTTPException(404, f"{request.project!r} is not a project page") from exc
            if not request.remove:
                # Ruling 56: the person linking their repository to a page they never started is them starting it.
                page = Path(memory_path) / "entities" / f"{request.project}.md"
                if project_ownership.unstarted(markdown_parser.parse(page, ledger=False).frontmatter, page):
                    paths = [*paths, *await asyncio.to_thread(project_ownership.accept, memory_path, request.project)]
            await _commit(memory_path, paths, "Repository unlinked from a project" if request.remove
                          else "Repository linked to its project")
            return request.project, False
        repo = await asyncio.to_thread(_page_record, memory_path, entity_id)
        if repo is None:
            raise HTTPException(404, NOT_IN_MEMORY.format(full=full))
        try:
            eid, paths = await asyncio.to_thread(github_repos.make_project, memory_path, repo, via=request.via)
        except project_ownership.OwnershipError as exc:
            raise HTTPException(409, str(exc)) from exc
        await _commit(memory_path, paths, "Project made from a repository")
        return eid, True

    project, created = await write_admission.run_admitted(memory_path, write, refuse=lambda: SleepWriting(BUSY))
    return RepoProjectResponse(project=project, created=created, linked=not request.remove)


# --- a page's card ----------------------------------------------------------------------------------------------


@router.get("/entities/{entity_id}/repository", response_model=RepoDetail)
async def get_repository(entity_id: str, settings: Settings = Depends(get_settings)):
    """A repository page's card: GitHub's record as the page keeps it, the projects it belongs to and the ones it
    could join, and its README preview — kept outside every bank, read through the API when missing or a week old
    while the picture-fetch gate is on (the page's open is the person's view, like its logo). 404 for any other page
    (a project's repositories are ``/entities/{id}/repositories``)."""
    memory_path = settings.memory_path
    page = memory_path / "entities" / f"{entity_id}.md"
    if not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    fm = (await asyncio.to_thread(markdown_parser.parse, page)).frontmatter
    block = github_repos.page_repo(fm)
    if block is None or not github_repos.is_repository_page(fm):
        raise HTTPException(404, f"{entity_id!r} is not a repository")
    if media_preview.fetch_allowed():
        await github_auth.fresh_token()
    readme = await github_repos.ensure_readme(memory_path, entity_id, block, allowed=media_preview.fetch_allowed())
    full = str(block["full_name"])

    def derive():
        mine = bool(block.get("owned")) or any(
            str(r.get("full_name") or "").lower() == full.lower() for r in github_repos.owned(memory_path))
        [row] = github_repos.with_matches(memory_path, [{"full_name": full}])
        linked = {p["project"] for p in row["projects"]}
        return mine, row, github_repos.project_candidates(memory_path, full, linked=linked)

    mine, row, candidates = await asyncio.to_thread(derive)
    match = row["project"]
    # A same-name suggestion only for one the person owns; a settled link for any repository.
    if match and match["how"] == "name" and not mine:
        match = None
        candidates = [c for c in candidates if c["how"] != "name"]
    state = github_repos.readme_state(readme)
    if readme and readme.get("none"):
        state = "none"
    fields = {**_row_fields({**block, "owned": mine})}
    return RepoDetail(**fields, entity_id=entity_id, project=RepoProject(**match) if match else None,
                      projects=_projects(row["projects"]), candidates=_projects(candidates),
                      readme=Readme(state=state, text=(readme or {}).get("text"),
                                    truncated=bool((readme or {}).get("truncated")),
                                    path=(readme or {}).get("path"), fetched_at=(readme or {}).get("fetched_at")))


@router.get("/entities/{entity_id}/repositories", response_model=ProjectRepos)
async def get_project_repositories(entity_id: str, settings: Settings = Depends(get_settings)):
    """A project's repositories — every one it lists, each with its page when it has one and how it was linked — and
    the repository pages it could link (the person's own first, one with the project's name before the rest). 404 for
    a page that is not a project. Reads only."""
    memory_path = settings.memory_path
    page = memory_path / "entities" / f"{entity_id}.md"
    if not page.exists():
        raise HTTPException(404, f"Entity {entity_id} not found")
    fm = (await asyncio.to_thread(markdown_parser.parse, page, ledger=False)).frontmatter or {}
    if str(fm.get("type") or "") != "project":
        raise HTTPException(404, f"{entity_id!r} is not a project")

    def derive():
        rows = github_repos.project_repositories(memory_path, entity_id)
        linked = {r["entity_id"] for r in rows if r.get("entity_id")}
        return rows, github_repos.repository_candidates(memory_path, entity_id, linked=linked)

    rows, candidates = await asyncio.to_thread(derive)
    repos = [ProjectRepo(**_row_fields(r["block"] or {"full_name": r["full_name"]}), entity_id=r.get("entity_id"),
                         how=r["how"], by=r.get("by")) for r in rows]
    return ProjectRepos(project=entity_id, repos=repos,
                        candidates=[_row(r, entity_id=r["entity_id"]) for r in candidates])
